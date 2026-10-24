"""watch (каждые 10 мин) и process (нарезка) — основная логика."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import random

from . import decisions, health, learn, releases
from .audio import inspect_clip_audio
from .bundles import record_moment
from .cuts import speech_runs
from .clips import normalize
from .config import WORK_DIR, env
from .judge import edit_clips, fallback_texts, grounded, judge_candidates, review_clip, snap_bounds, target_texts, translate_lines
from .llm import LLM
from .platforms import connected_platforms
from .qa import hook_quality, plan_opening, validate_render
from .render import PANEL_H, W, chunk_words, extract_frames, fit_title, probe, render_clip, thumb_b64
from .signals import audio_rms_db, find_candidates
from .store import Store
from .transcribe import Transcriber, cut_wav
from .twitch import Twitch, download_audio, download_chat, download_video
from .util import ffprobe_json, fmt_hms, log, now_iso, now_utc, parse_iso, run

W_PANEL_ASPECT = W / PANEL_H

PROCESS_BUDGET_SEC = int(os.environ.get("PROCESS_BUDGET_SEC", 5 * 3600 + 15 * 60))  # лимит джобы GitHub — 6 ч


def twitch_client() -> Twitch:
    return Twitch(env("TWITCH_CLIENT_ID"), env("TWITCH_CLIENT_SECRET"))


def ensure_meta(cfg: dict, store: Store, tw: Twitch) -> dict:
    meta = store.read_json("meta.json", {}) or {}
    login = cfg["streamer"]["twitch_login"].lower()
    if meta.get("login") != login:
        u = tw.user(login)
        since = now_utc() - dt.timedelta(hours=float(cfg["processing"].get("backfill_hours", 12)))
        meta = {"login": login, "user_id": u["id"], "display_name": u["display_name"],
                "avatar": u.get("profile_image_url"), "since": since.replace(microsecond=0).isoformat()}
        store.write_json("meta.json", meta)
    return meta


def is_live_vod(vod: dict, live: dict | None) -> bool:
    if not live:
        return False
    return parse_iso(vod["created_at"]) >= parse_iso(live["started_at"]) - dt.timedelta(minutes=15)


def vod_settled(v: dict, live: dict | None, durations: dict) -> bool:
    """VOD закончился и его длина больше не растёт (Twitch иногда дописывает длительность с задержкой)."""
    if is_live_vod(v, live):
        return False
    end_time = parse_iso(v["created_at"]) + dt.timedelta(seconds=v["duration_sec"])
    if now_utc() - end_time >= dt.timedelta(minutes=60):
        return True
    d = durations.get(v["id"]) or {}
    return d.get("duration") == v["duration_sec"] and d.get("changed_at") and \
        now_utc() - parse_iso(d["changed_at"]) >= dt.timedelta(minutes=15)


def next_chunk(cfg: dict, store: Store, vods: list[dict], live: dict | None, meta: dict):
    """Следующий кусок: (vod, start, end, final) или None.

    Гарантия «ни секунды мимо»:
      • пока идёт эфир — куски по chunk_minutes (кроме последних минут, они ещё пишутся);
      • после эфира хвост любой длины добирается целиком, когда длина VOD перестала расти;
      • если Twitch позже удлинил VOD — недостающее тоже доберётся (проверка 48 ч);
      • короткий хвост расширяется назад до min_window, чтобы у ИИ был контекст (дубли отсекаются).
    """
    p = cfg["processing"]
    chunk, margin, overlap = int(p["chunk_minutes"]) * 60, int(p["live_margin_seconds"]), int(p["overlap_seconds"])
    min_window = int(p.get("min_window_seconds", 360))
    state = store.read_json("vods.json", {}) or {}
    durations = store.read_json("status/vod_durations.json", {}) or {}
    since = parse_iso(meta["since"])
    retry = os.environ.get("RETRY_GAPS") == "1"
    for v in sorted(vods, key=lambda x: (0 if is_live_vod(x, live) else 1, x["created_at"])):
        created = parse_iso(v["created_at"])
        if created < since - dt.timedelta(hours=24) or now_utc() - created > dt.timedelta(hours=72):
            continue
        rec = state.get(v["id"], {})
        if retry and rec.get("gaps"):
            g = rec["gaps"][0]
            return v, g["start"], g["end"], True
        if not rec and created < since:  # VOD начался до установки бота
            rec = {"processed_until": max(0, int((since - created).total_seconds()))}
        done = int(rec.get("processed_until", 0))
        live_now = is_live_vod(v, live)
        if live_now:
            if v["duration_sec"] - margin - done >= chunk:
                return v, max(0, done - overlap), done + chunk, False
            continue
        remaining = v["duration_sec"] - done
        if remaining <= 0:
            continue
        if remaining >= chunk:  # большой остаток можно резать, не дожидаясь стабилизации
            return v, max(0, done - overlap), done + chunk, False
        if vod_settled(v, live, durations):
            start = max(0, min(done - overlap, v["duration_sec"] - min_window))
            return v, start, v["duration_sec"], True
    return None


def observe_durations(store: Store, vods: list[dict]):
    d = store.read_json("status/vod_durations.json", {}) or {}
    changed = False
    for v in vods:
        cur = d.get(v["id"]) or {}
        if cur.get("duration") != v["duration_sec"]:
            d[v["id"]] = {"duration": v["duration_sec"], "changed_at": now_iso()}
            changed = True
    keep = {v["id"] for v in vods}
    if set(d) - keep:
        d = {k: x for k, x in d.items() if k in keep}
        changed = True
    if changed:
        store.write_json("status/vod_durations.json", d)


# ── WATCH ───────────────────────────────────────────────────────
def process_running() -> bool:
    r = run(["gh", "run", "list", "--workflow", "process.yml", "--limit", "5", "--json", "status"], check=False, quiet=True)
    try:
        return any(x["status"] in ("queued", "in_progress", "waiting", "pending", "requested") for x in json.loads(r.stdout or "[]"))
    except json.JSONDecodeError:
        return False


def update_live(store: Store, live: dict | None):
    prev = store.read_json("status/live.json", {}) or {}
    cur = {"is_live": bool(live)}
    if live:
        cur.update(title=live.get("title"), started_at=live.get("started_at"), viewers=live.get("viewer_count"),
                   game=live.get("game_name"))
    else:
        cur["last_seen_live"] = prev.get("started_at") if prev.get("is_live") else prev.get("last_seen_live")
    # пишем, только если что-то важное поменялось или раз в 30 минут (зрители)
    important = {k: cur.get(k) for k in ("is_live", "title", "started_at")} != {k: prev.get(k) for k in ("is_live", "title", "started_at")}
    stale = time.time() - parse_iso(prev["updated_at"]).timestamp() > 1800 if prev.get("updated_at") else True
    if important or stale:
        cur["updated_at"] = now_iso()
        store.write_json("status/live.json", cur)


def cmd_watch(cfg: dict, store: Store):
    tw = twitch_client()
    meta = ensure_meta(cfg, store, tw)
    live = tw.live_stream(meta["user_id"])
    update_live(store, live)
    vods = tw.archives(meta["user_id"], 5)
    observe_durations(store, vods)
    if live and not any(is_live_vod(v, live) for v in vods):
        lv = store.read_json("status/live.json", {}) or {}
        if not lv.get("vod_missing"):
            lv.update(vod_missing=True, updated_at=now_iso())
            store.write_json("status/live.json", lv)
        log("⚠️ стрим идёт, но VOD не сохраняется — включите «Сохранять прошлые трансляции» на Twitch")
    job = next_chunk(cfg, store, vods, live, meta)
    log(f"live={bool(live)} vods={len(vods)} работа={'да' if job else 'нет'}")
    if job and not process_running():
        log("запускаю нарезку")
        run(["gh", "workflow", "run", "process.yml"])
        store.write_json("status/watch.json", {"last_dispatch": now_iso(), "updated_at": now_iso()})
    health.report(store, "watch", "ok", ("эфир идёт" if live else "эфира нет") + (", нарезка запущена" if job else ""))
    store.sync("watch")


# ── PROCESS ─────────────────────────────────────────────────────
def cmd_process(cfg: dict, store: Store):
    t0 = time.time()
    tw = twitch_client()
    meta = ensure_meta(cfg, store, tw)
    llm = LLM(cfg["llm"]["providers"])
    wh = cfg.get("whisper", {})
    transcriber = Transcriber(wh.get("model", "large-v3-turbo"), wh.get("compute_type", "int8"),
                              cfg["streamer"].get("language", "ru"))
    n = 0
    tried: set[str] = set()
    while time.time() - t0 < PROCESS_BUDGET_SEC - 50 * 60:
        live = tw.live_stream(meta["user_id"])
        update_live(store, live)
        vods = tw.archives(meta["user_id"], 5)
        job = next_chunk(cfg, store, vods, live, meta)
        if not job:
            break
        vod, start, end, final = job
        key = f"{vod['id']}:{int(start)}-{int(end)}"
        if key in tried:  # этот кусок уже пробовали в этом запуске — не крутимся по кругу
            break
        tried.add(key)
        try:
            process_chunk(cfg, store, tw, llm, transcriber, meta, vod, start, end, final)
            n += 1
        except Exception as e:  # noqa: BLE001
            log(f"❌ кусок {vod['id']} {fmt_hms(start)}–{fmt_hms(end)}: {e}")
            if record_failure(store, vod, start, end, str(e)):
                continue  # 3 провала подряд — кусок ушёл в «пропуски», идём дальше
            health.report(store, "process", "error", f"кусок {fmt_hms(start)}–{fmt_hms(end)}: {str(e)[:300]}")
            store.set_status("process", state="error", stage="Ошибка, повторю через 10 минут", detail=str(e)[:500])
            raise
    try:  # связки — после всех кусков и только если осталось время; сбой связок не валит процесс
        if time.time() - t0 < PROCESS_BUDGET_SEC - 40 * 60:
            from .bundles import run_pass
            made = run_pass(cfg, store, llm, targets_for(cfg, store))
            if made:
                log(f"связок собрано: {made}")
    except Exception as e:  # noqa: BLE001
        log(f"связки пропущены: {str(e)[:200]}")
    health.report(store, "process", "ok", f"обработано кусков: {n}")
    store.set_status("process", state="idle", stage="Жду новый стрим" if n == 0 else "Готово, жду новые куски",
                     detail=f"обработано кусков: {n}", progress=None)


def record_failure(store: Store, vod: dict, start: float, end: float, err: str) -> bool:
    """Считает провалы одного куска. После 3-го — фиксирует пропуск (виден в дашборде, можно перезапустить)
    и двигается дальше, чтобы один битый кусок не остановил весь стрим. Возвращает True, если пропущен."""
    vs = store.read_json("vods.json", {}) or {}
    rec = vs.setdefault(vod["id"], {"title": vod.get("title"), "created_at": vod["created_at"]})
    key = f"{int(start)}-{int(end)}"
    fails = rec.setdefault("fails", {})
    fails[key] = fails.get(key, 0) + 1
    skipped = fails[key] >= 3
    if skipped:
        gaps = [g for g in rec.get("gaps", []) if not (g["start"] == int(start) and g["end"] == int(end))]
        rec["gaps"] = gaps + [{"start": int(start), "end": int(end), "error": err[:300], "at": now_iso()}]
        rec["processed_until"] = max(int(rec.get("processed_until", 0)), int(end))
        fails.pop(key, None)
    store.write_json("vods.json", vs)
    store.sync(f"vod {vod['id']}: сбой куска {key} ({'пропуск' if skipped else 'повтор'})")
    return skipped


def process_chunk(cfg, store: Store, tw: Twitch, llm: LLM, transcriber: Transcriber, meta: dict,
                  vod: dict, start: float, end: float, final: bool):
    p, jcfg = cfg["processing"], cfg["judge"]
    vid = vod["id"]
    work = WORK_DIR / vid / str(int(start))
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    label = f"{fmt_hms(start)}–{fmt_hms(end)}"
    st = lambda stage, prog=None, **kw: store.set_status("process", state="running", stage=stage, vod_id=vid,
                                                       vod_title=vod.get("title"), chunk=label, progress=prog, **kw)
    log(f"=== VOD {vid} кусок {label} final={final}")

    st("Скачиваю звук", 5)
    audio = download_audio(vid, start, end, work / "audio.m4a")
    length = int(float(ffprobe_json(audio)["format"].get("duration", end - start)))

    st("Читаю чат и клипы зрителей", 15)
    msgs = download_chat(vid, start, end, work / "chat.json")
    created = parse_iso(vod["created_at"])
    try:
        vclips = tw.clips(meta["user_id"], (created + dt.timedelta(seconds=start)).isoformat().replace("+00:00", "Z"),
                          now_iso())
        vclips = [c for c in vclips if c.get("video_id") == vid and c.get("vod_offset") is not None
                  and start <= c["vod_offset"] <= end]
    except Exception as e:  # noqa: BLE001
        log(f"клипы зрителей недоступны: {e}")
        vclips = []
    log(f"клипов зрителей: {len(vclips)}")

    st("Ищу пики реакции", 22)
    db = audio_rms_db(audio, length)
    vstate = store.read_json("vods.json", {}) or {}
    rec = vstate.get(vid, {})
    tail = 0 if final else int(p["context_after"] + p.get("chat_delay_seconds", 9) + 5)  # хвост доберёт следующий кусок
    cands = find_candidates(cfg, msgs, vclips, db, start, rec.get("candidate_times", []), ignore_tail=tail)

    # транскрипция + кадры
    for i, c in enumerate(cands):
        st(f"Расшифровываю речь {i + 1}/{len(cands)}", 25 + int(35 * i / max(1, len(cands))))
        cs = max(start, c["peak_abs"] - p["context_before"])
        ce = min(start + length, c["peak_abs"] + p["context_after"])
        c.update(id=f"c{i}", ctx_start=cs, ctx_dur=ce - cs, peak_in_ctx=c["peak_abs"] - cs)
        wav = cut_wav(audio, cs - start, ce - cs, work / f"{c['id']}.wav")
        c["words"] = transcriber.words(wav)
        c["frames"] = []
        if jcfg.get("use_frames"):
            try:
                low = download_video(vid, cs, ce, work / f"{c['id']}_low.mp4", max_height=360)
                c["frames"] = extract_frames(low, [c["peak_in_ctx"] - 8, c["peak_in_ctx"], c["peak_in_ctx"] + 6], work)
            except Exception as e:  # noqa: BLE001
                log(f"кадры не получены: {str(e)[:150]}")
    # пустые моменты (нет речи и почти нет реакции) — даже не показываем ИИ
    alive = [c for c in cands if len(c["words"]) >= 5 or c["chat_count"] >= 10 or c["breakdown"]["viewer_clips"] >= 1]
    log(f"живых кандидатов: {len(alive)}/{len(cands)}")

    st("ИИ выбирает лучшие моменты", 62)
    policy = learn.load(store, cfg)
    try:
        learned = learn.learned_examples(store, cfg)
    except Exception as e:  # noqa: BLE001
        log(f"примеры из статистики недоступны: {e}")
        learned = {}
    u0 = llm.totals()
    verdicts = judge_candidates(llm, cfg, alive, learned, (policy.get("hints") or {}).get("length", "")) if alive else {}
    scored = []
    for c in alive:
        v = verdicts.get(c["id"])
        if not v or not v.get("keep"):
            continue
        if int((v.get("risk") or {}).get("level", 0)) >= 3:
            decisions.record(store, "skip", f"Клип {fmt_hms(c['peak_abs'])} не выложен: риск для аккаунта "
                             f"({', '.join((v.get('risk') or {}).get('flags', [])) or 'высокий'})", reversible=False)
            continue
        scored.append((c, v))
    scored.sort(key=lambda x: (-int(x[1].get("score", 0)), -x[0]["signal"]))
    picked = select_for_chunk(cfg, store, scored, end - start)
    log(f"к рендеру: {len(picked)} из {len(scored)} подходящих")

    # границы → первые секунды (подрезка под первое слово) → второй проход ИИ
    plans = []
    for c, v in picked:
        s0, e0 = snap_bounds(c["words"], v.get("start", 0), v.get("end", c["ctx_dur"]), c["ctx_dur"], cfg)
        s0, opening = plan_opening(c["words"], s0, e0, cfg)
        cw = [{"w": w["w"], "s": round(w["s"] - s0, 2), "e": round(w["e"] - s0, 2)} for w in c["words"] if s0 - 0.1 <= w["s"] < e0]
        plans.append({"c": c, "v": v, "s": s0, "e": e0, "id": c["id"], "words": cw, "dur": e0 - s0, "opening": opening,
                      "chat_sample": c["chat_sample"], "category": v.get("category"), "why": v.get("why")})
    if plans:
        st("ИИ пишет хуки и тексты под площадки", 68)
    platforms = targets_for(cfg, store)
    made = 0
    # сначала тексты для всех клипов чанка (быстрый шаг, ИИ), потом монтаж и выкладка строго по одному:
    # первый готовый клип уходит сразу, не дожидаясь остальных
    edits = edit_clips(llm, cfg, plans) if plans else {}
    for k, pl in enumerate(plans):
        st(f"Монтирую клип {k + 1}/{len(plans)}", 70 + int(28 * k / max(1, len(plans))))
        ed = edits.get(pl["id"])
        if not ed and not cfg["clips"].get("allow_fallback_texts", False):
            log(f"клип {pl['id']} отложен: ИИ-редактор не ответил, а тексты без него не выпускаю")
            health.report(store, "render", "warn", f"клип {pl['id']} отложен: редактор не ответил")
            continue
        try:
            ed = ed or fallback_texts(pl["v"], pl["words"])
            made += bool(make_clip(cfg, store, llm, policy, vod, pl, ed, platforms, work))
        except Exception as e:  # noqa: BLE001 — один битый клип не валит всё
            log(f"⚠️ клип не собран: {str(e)[:400]}")
            health.report(store, "render", "warn", f"клип не собран: {str(e)[:200]}")

    spent = llm.delta(u0)
    if spent["by_model"]:
        log(f"ИИ за кусок: {sum(x['calls'] for x in spent['by_model'].values())} запросов, ≈${spent['usd']:.4f}, "
            + ", ".join(f"{k} {v['in']}+{v['out']} ток." for k, v in spent["by_model"].items()))
    rec.update(title=vod.get("title"), created_at=vod["created_at"], duration=vod["duration_sec"],
               llm=spent,
               processed_until=max(int(rec.get("processed_until", 0)), int(end)), finished=bool(final),
               candidate_times=(rec.get("candidate_times", []) + [c["peak_abs"] for c in cands])[-300:],
               clips=int(rec.get("clips", 0)) + made, updated_at=now_iso())
    rec["gaps"] = [g for g in rec.get("gaps", []) if not (g["start"] >= start and g["end"] <= end)]
    rec.get("fails", {}).pop(f"{int(start)}-{int(end)}", None)
    vstate = store.read_json("vods.json", {}) or {}
    vstate[vid] = rec
    store.write_json("vods.json", vstate)
    store.sync(f"vod {vid}: кусок {label}, клипов {made}")
    shutil.rmtree(work, ignore_errors=True)


def targets_for(cfg: dict, store: Store) -> list[str]:
    """Под какие площадки рендерить: TikTok всегда + всё, что подключено."""
    plats = ["tiktok"] + sorted(connected_platforms(cfg, store) - {"tiktok"})
    return [p for p in plats if p in (cfg.get("platforms") or {"tiktok": 1, "youtube": 1, "instagram": 1})]


def select_for_chunk(cfg: dict, store: Store, scored: list, chunk_s: float) -> list:
    """Сколько клипов рендерим из куска стрима. Не больше дневной нормы на весь день, а не на кусок:
    средний стрим ~8 ч, значит кусок в 2 ч — это четверть дня. Слабые клипы не выпускаем, даже если их много.
    Исключения: очень сильный момент (exceptional_score) и свежая по времени тема (fresh_score) берём сверх лимита."""
    from datetime import datetime, timedelta, timezone
    from .platforms import accounts as list_accounts
    p = cfg["processing"]
    policy = learn.load(store, cfg)
    per_plat = {}
    for a in list_accounts(cfg):
        per_plat[a["platform"]] = per_plat.get(a["platform"], 0) + learn.daily_cap(policy, a, cfg)
    day_target = max(per_plat.values() or [4])          # клипов в сутки (каждый выходит на всех площадках)
    # сколько уже есть: готовые в очереди и выложенные за последние сутки
    ready, posted = 0, 0
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    for raw in store.list_json("queue"):
        c = normalize(raw)
        if any(t.get("status", "ready") == "ready" for t in c["targets"].values()):
            ready += 1
        for pst in c.get("posts", {}).values():
            try:
                ts = datetime.fromisoformat(str(pst.get("posted_at", "")).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= since:
                    posted += 1
                    break
            except ValueError:
                continue
    room = day_target - ready - posted
    share = max(1, round(day_target * (chunk_s / 60) / (float(p.get("expected_stream_hours", 8)) * 60)))
    hard = int(p.get("max_renders_per_chunk", 3))
    exc, fresh_bar = int(p.get("exceptional_score", 9)), int(p.get("fresh_score", 8))
    bar = int(cfg["judge"].get("min_score", 5))
    limit = min(hard, room, share + 1) if room > 0 else 0   # за кусок не больше share+1, чтобы норма не сгорела в первом куске
    if room <= 0:
        bar = max(bar, exc)                              # день уже полон: только по-настоящему сильное
    def is_exc(v):
        sc = int(v.get("score", 0))
        return sc >= exc or (bool(v.get("fresh")) and sc >= fresh_bar)
    picked = [x for x in scored if int(x[1].get("score", 0)) >= max(bar, 7 if room > 0 else bar)][:limit]
    for x in scored:
        if len(picked) >= hard:
            break
        if x not in picked and is_exc(x[1]):
            picked.append(x)
    if not picked and room > 0 and scored and int(scored[0][1].get("score", 0)) >= 6:
        picked = scored[:1]                              # хотя бы один лучший, если совсем ничего не прошло
    log(f"дневная норма {day_target}: в очереди {ready}, выложено за сутки {posted}, осталось {max(room, 0)}; кусок ≈{share} клип(а)")
    return picked


def make_clip(cfg, store: Store, llm: LLM, policy: dict, vod: dict, pl: dict, ed: dict, platforms: list[str],
              work: Path) -> bool:
    c, v = pl["c"], pl["v"]
    s, e = pl["s"], pl["e"]
    cl = cfg["clips"]
    abs_s, dur = c["ctx_start"] + s, e - s
    clip_id = f"{vod['id']}_{int(abs_s)}"
    ok, why = review_clip(llm, cfg, pl, ed)
    if not ok:
        decisions.record(store, "skip", f"Клип {fmt_hms(abs_s)} не выложен после проверки: {why}", reversible=False)
        return False
    pad = min(3.0, abs_s)
    src_off = abs_s - pad  # время в записи VOD, с которого начинается скачанный исходник
    src = download_video(vod["id"], src_off, abs_s + dur + 2, work / f"{clip_id}_src.mp4")

    # звук: заглушка Twitch / музыка в фоне
    au = inspect_clip_audio(src, pad, dur, work, cfg)
    if au["action"] == "skip":
        decisions.record(store, "skip", f"Клип {fmt_hms(abs_s)} пропущен: {au['reason']}", reversible=False)
        return False
    risk = dict(v.get("risk") or {"level": 0, "flags": []})
    if au["action"] in ("vocals", "flag"):
        decisions.record(store, "audio", f"Клип {fmt_hms(abs_s)}: {au['reason']}", reversible=False)
    if au["action"] == "flag":
        risk["flags"] = sorted(set(risk.get("flags", [])) | {"music"})

    words_src = [{"w": w["w"], "s": w["s"] + pad, "e": w["e"] + pad} for w in pl["words"]]

    # обрезка пауз: длинное молчание и пустые секунды вырезаются, короткие паузы остаются
    mn = float(cl["min_seconds"])
    if cl.get("trim_silence", True):
        segs_main = speech_runs(words_src, pad, pad + dur, max_gap=float(cl.get("trim_gap_seconds", 1.2)))
        if sum(b - a for a, b in segs_main) < 0.8 * mn:
            segs_main = [(pad, pad + dur)]
    else:
        segs_main = [(pad, pad + dur)]
    kept = sum(b - a for a, b in segs_main)
    main = (segs_main[0][0], segs_main[-1][1])

    co = ed.get("cold_open") or {}
    co_seg = None
    try:
        a, b = float(co.get("start", -1)), float(co.get("end", -1))
        if co.get("use") and 5 <= a < b <= dur and b - a <= 3.0 and dur >= 16:
            co_seg = (pad + a, pad + b)
    except (TypeError, ValueError):
        pass
    if pl["opening"].get("speech_start") is None and co_seg is None and v.get("payoff_at"):
        pa = float(v["payoff_at"]) - s  # в начале нет речи — показываем развязку первой
        if 5 <= pa <= dur - 1:
            co_seg = (pad + pa - 0.3, pad + min(dur, pa + 2.0))
    # контекстные подписи сверху (белые, временные) по умолчанию выключены
    notes = ([n for n in (ed.get("notes") or []) if isinstance(n, dict)][:2]
             if cl.get("context_notes", False) else [])
    out_dir = work / "out"
    out_dir.mkdir(exist_ok=True)
    from .framing import detect_subject, plan_pan
    panel_asp = W_PANEL_ASPECT
    sw, sh, _ = probe(src)
    crop_frac = min(1.0, (sh * panel_asp) / sw) if sw else 1.0
    pan = (plan_pan(detect_subject(src, main[0], main[1]), main[0], main[1], crop_frac)
           if cl.get("follow_subject", True) and crop_frac < 0.98 and sh <= sw * 1.2 else None)
    # хук и тексты должны опираться на то, что реально сказано: иначе ролик врёт про стримера
    tr = " ".join(w["w"] for w in pl["words"])
    hooks_ok = [h for h in (ed.get("hooks") or []) if isinstance(h, dict) and grounded(h.get("text", ""), tr) >= 0.6]
    if not hooks_ok:
        decisions.record(store, "skip", f"Клип {fmt_hms(abs_s)} не выложен: хуки не совпадают с речью стримера",
                         reversible=False)
        return False
    ed = {**ed, "hooks": hooks_ok}
    for key, field in (("tiktok", "caption"), ("youtube", "title"), ("instagram", "caption")):
        p = ed.get(key) or {}
        if grounded(p.get(field, ""), tr) < 0.5:
            ed[key] = {**p, field: hooks_ok[0]["text"]}
    rng = random.Random(clip_id)
    targets, thumb, en_cache = {}, None, {}
    for plat in platforms:
        variant = learn.choose_variant(policy, plat, cfg, rng)
        tx = target_texts(ed, plat, variant.get("hook_style"), cfg)
        use_cold = bool(co_seg and variant.get("cold_open", True))
        segs = ([co_seg] if use_cold else []) + segs_main
        variant["cold_open"] = use_cold
        lag = (co_seg[1] - co_seg[0]) if use_cold else 0.0
        pnotes = [{"t": float(n.get("t", 0)) + lag, "text": n.get("text", "")} for n in notes]
        en = None
        if variant.get("subtitles") == "both" and pl["words"]:
            if "en" not in en_cache:
                try:
                    en_cache["en"] = translate_lines(llm, [" ".join(x["w"] for x in ch)
                                                           for ch in chunk_words(pl["words"])])
                except Exception as ex:  # noqa: BLE001
                    log(f"перевод недоступен: {ex}")
                    en_cache["en"] = None
            en = en_cache["en"]
            if not en:
                variant["subtitles"] = "ru"
        title = fit_title(*tx["hook_alts"])
        out = out_dir / f"{clip_id}_{plat}.mp4"
        total = sum(b - a for a, b in segs)
        problems = []
        for attempt in range(2):
            try:
                render_clip(src, segs, words_src, title, cfg, out, notes=pnotes, variant=variant,
                            audio_override=au.get("audio_override"), en_lines=en, pan_keys=pan)
                problems = validate_render(out, total, plat)
            except Exception as ex:  # noqa: BLE001
                problems = [f"рендер упал: {str(ex)[:160]}"]
            if not problems:
                break
            log(f"⚠️ {clip_id} {plat}: {problems} — попытка {attempt + 2}")
            variant = {**variant, "progress_bar": False}
        if problems:
            health.report(store, "render", "warn", f"{clip_id} {plat}: " + "; ".join(problems))
            continue
        if thumb is None:
            thumb = thumb_b64(out, at=min(1.0, total / 2))
        hq = hook_quality(pl["opening"], use_cold, title[0])
        targets[plat] = {**{k: val for k, val in tx.items() if k != "hook_alts"}, "hook_alts": tx["hook_alts"][:4],
                         "asset": releases.upload(out), "size": out.stat().st_size, "duration": round(total, 1),
                         "variant": variant, "hook_quality": hq, "status": "ready",
                         "comment": humanize_comment(ed.get("comment", "")), "cover_ms": 600}
    if not targets:
        decisions.record(store, "skip", f"Клип {fmt_hms(abs_s)} не собран ни под одну площадку (рендер/проверка)",
                         reversible=False)
        return False
    store.write_json(f"queue/{clip_id}.json", {
        "id": clip_id, "vod_id": vod["id"], "vod_title": vod.get("title"), "vod_time": round(abs_s, 1),
        "duration": round(kept, 1), "score": int(v.get("score", 0)),
        "subscores": {k: v.get(k) for k in ("hook", "payoff", "clarity", "emotion", "relate")},
        "category": v.get("category", "other"), "risk": risk, "why": v.get("why", ""),
        "overlay": next(iter(targets.values()))["hook"], "signal": c["signal"], "breakdown": c["breakdown"],
        "audio": {k: au[k] for k in ("muted", "music", "action") if k in au} | {"reason": au.get("reason")},
        "opening": pl["opening"], "notes": notes, "transcript": " ".join(w["w"] for w in pl["words"])[:600],
        "thumb": thumb, "targets": targets, "posts": {}, "created_at": now_iso(),
        "live_when_made": bool((store.read_json("status/live.json", {}) or {}).get("is_live")),
        "uid": uuid.uuid4().hex[:8],
        "vod_url": f"https://www.twitch.tv/videos/{vod['id']}?t={_hms(src_off + segs_main[0][0])}",
    })
    # для связок: где в записи лежат куски и какие в них слова (абсолютное время VOD)
    record_moment(store, {
        "id": clip_id, "vod_id": vod["id"], "vod_title": vod.get("title"), "created_at": now_iso(),
        "t": round(src_off + segs_main[0][0], 2), "category": v.get("category", "other"),
        "score": int(v.get("score", 0)), "text": " ".join(w["w"] for w in pl["words"])[:400],
        "segments": [[round(src_off + a, 2), round(src_off + b, 2)] for a, b in segs_main],
        "words": [[w["w"], round(src_off + w["s"], 2), round(src_off + w["e"], 2)] for w in words_src][:120],
    })
    store.sync(f"клип {clip_id} готов (score {v.get('score')}, площадки: {', '.join(targets)})")
    hooks = ", ".join(p + ": «" + t["hook"] + "»" for p, t in targets.items())
    log(f"✅ {clip_id} score={v.get('score')} {kept:.0f}с → {hooks}")
    return True


def _hms(sec: float) -> str:
    s = int(max(0, sec))
    return f"{s // 3600}h{s % 3600 // 60}m{s % 60}s"


def humanize_comment(text: str) -> str:
    from .judge import humanize
    return humanize(text, 1, "caption")[:90]
