"""watch (каждые 10 мин) и process (нарезка) — основная логика."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import random

from . import health, learn, releases
from .audio import inspect_clip_audio
from .bundles import record_moment
from .cuts import speech_runs
from .clips import normalize
from .config import WORK_DIR, env
from .judge import edit_clips, grounded, judge_candidates, snap_bounds, target_texts
from .llm import LLM
from .platforms import connected_platforms
from .qa import hook_quality, validate_render
from .render import PANEL_H, W, fit_title, probe, render_clip, thumb_b64
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
    # живой стрим — всегда приоритет: сортируем так, чтобы live VOD шёл первым
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
    ai = cfg.get("ai") or {}
    llm = LLM(cfg["llm"]["providers"], text_chain=[ai["text_model"]] if ai.get("text_model") else None)
    wh = cfg.get("whisper", {})
    transcriber = Transcriber(wh.get("model", "large-v3-turbo"), wh.get("compute_type", "int8"),
                              cfg["streamer"].get("language", "ru"), engine=(cfg.get("transcribe") or {}).get("engine", "auto"),
                              llm=llm, hotwords=" ".join([wh.get("hotwords", "")] + proofread_terms(store, cfg)).strip())
    n = 0
    tried: set[str] = set()
    from . import settings
    while time.time() - t0 < PROCESS_BUDGET_SEC - 50 * 60:
        if settings.stopped(store, "process"):
            log("⏹ нарезка остановлена из дашборда — выхожу после текущего куска")
            break
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


FUNNEL = "status/funnel.json"


def note_reject(store: Store, vod: dict, t_abs: float, stage: str, reason: str, score=None, what: str = ""):
    """Почему момент НЕ стал клипом — коротко, для дашборда («Почему не взял»). Не засоряет журнал решений."""
    item = {"at": now_iso(), "vod_id": vod["id"], "t": round(t_abs, 1), "stage": stage, "score": score,
            "reason": str(reason)[:220], "what": str(what)[:200]}

    def add(f):
        f = f or {}
        f["rejected"] = (f.get("rejected") or [])[-249:] + [item]
        return f
    store.update_json(FUNNEL, add, {})   # потокобезопасно: режиссёр работает параллельно


def note_chunk(store: Store, vod: dict, label: str, counts: dict):
    item = {"at": now_iso(), "vod_id": vod["id"], "vod_title": vod.get("title"), "chunk": label, **counts}

    def add(f):
        f = f or {}
        f["chunks"] = (f.get("chunks") or [])[-59:] + [item]
        return f
    store.update_json(FUNNEL, add, {})


def _merge_scout(cands: list[dict], scouted: list[dict], chunk_start: float, length: float, p: dict) -> list[dict]:
    """Моменты разведчика добавляются к пикам сигналов. Рядом с пиком (±45 с) — пик получает заметку и приоритет."""
    out = list(cands)
    for m in scouted:
        near = [c for c in out if abs(c["peak_abs"] - m["abs"]) < 45]
        if near:
            near[0]["scout"] = m
            continue
        out.append({"peak_rel": int(m["abs"] - chunk_start), "peak_abs": m["abs"] + 8, "signal": 0.0,
                    "breakdown": {"chat": 0, "keywords": 0, "spam_wave": 0, "audio": 0, "viewer_clips": 0},
                    "chat_count": 0, "chat_sample": [], "viewer_clips": [], "scout": m})
    return out


def process_chunk(cfg, store: Store, tw: Twitch, llm: LLM, transcriber: Transcriber, meta: dict,
                  vod: dict, start: float, end: float, final: bool):
    from . import brain
    from .signals import PATTERNS, _chat_sample
    p, ai, q = cfg["processing"], cfg.get("ai") or {}, cfg.get("quality") or {}
    make_min = int(q.get("make_min", 7))
    vid = vod["id"]
    work = WORK_DIR / vid / str(int(start))
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    label = f"{fmt_hms(start)}–{fmt_hms(end)}"
    counts = {"peaks": 0, "scout": 0, "candidates": 0, "text_pass": 0, "video_checked": 0, "video_pass": 0, "made": 0}

    def st(stage_id, stage, prog=None):
        store.set_status("process", state="running", stage=stage, stage_id=stage_id, vod_id=vid, vod_title=vod.get("title"),
                         chunk=label, progress=prog, funnel=counts)
    log(f"=== VOD {vid} кусок {label} final={final}")

    st("audio", "Скачиваю звук, чат и клипы зрителей (одновременно)", 4)
    created = parse_iso(vod["created_at"])

    def viewer_clips():
        try:
            vc = tw.clips(meta["user_id"], (created + dt.timedelta(seconds=start)).isoformat().replace("+00:00", "Z"), now_iso())
            return [c for c in vc if c.get("video_id") == vid and c.get("vod_offset") is not None
                    and start <= c["vod_offset"] <= end]
        except Exception as e:  # noqa: BLE001
            log(f"клипы зрителей недоступны: {e}")
            return []
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_audio = ex.submit(download_audio, vid, start, end, work / "audio.m4a")
        f_chat = ex.submit(download_chat, vid, start, end, work / "chat.json")
        f_clips = ex.submit(viewer_clips)
        audio, msgs, vclips = f_audio.result(), f_chat.result(), f_clips.result()
    length = int(float(ffprobe_json(audio)["format"].get("duration", end - start)))

    st("peaks", "Ищу пики реакции чата и звука", 14)
    db = audio_rms_db(audio, length)
    rec = (store.read_json("vods.json", {}) or {}).get(vid, {})
    tail = 0 if final else int(p["context_after"] + p.get("chat_delay_seconds", 9) + 5)
    cands = find_candidates(cfg, msgs, vclips, db, start, rec.get("candidate_times", []), ignore_tail=tail)
    counts["peaks"] = len(cands)

    if ai.get("scout_audio", True):
        st("scout", "ИИ слушает весь кусок стрима целиком", 18)
        try:
            taken = rec.get("candidate_times", [])
            scouted = [m for m in brain.scout(llm, cfg, audio, length, msgs, start, work, PATTERNS)
                       if not any(abs(m["abs"] - t) < 60 for t in taken)
                       and (final or m["abs"] < start + length - tail)]
        except Exception as e:  # noqa: BLE001 — разведчик не обязателен
            log(f"разведчик упал: {str(e)[:200]}")
            scouted = []
        counts["scout"] = len(scouted)
        cands = _merge_scout(cands, scouted, start, length, p)
    cands = cands[: int(p.get("max_candidates_per_chunk", 22))]
    counts["candidates"] = len(cands)

    # транскрипт окна вокруг каждого кандидата: все окна сразу (облако параллельно, Whisper — запасной)
    st("speech", f"Расшифровываю речь: {len(cands)} окон одновременно", 22)
    items = []
    for i, c in enumerate(cands):
        sc = c.get("scout") or {}
        before, after = float(p["context_before"]), float(p["context_after"])
        if sc and sc.get("end_abs") and not c.get("signal"):
            cs, ce = sc["abs"] - 20, min(sc["abs"] + 130, max(sc["end_abs"] + 15, sc["abs"] + 40))
        else:
            cs, ce = c["peak_abs"] - before, c["peak_abs"] + after
        cs, ce = max(start, cs), min(start + length, ce)
        c.update(id=f"c{i}", ctx_start=cs, ctx_dur=ce - cs, peak_in_ctx=c["peak_abs"] - cs)
        if not c["chat_sample"]:
            near = [m for m in msgs if cs <= m["t"] <= ce + 15]
            c["chat_sample"], c["chat_count"] = _chat_sample(near, c["peak_abs"]), len(near)
        items.append((cut_wav(audio, cs - start, ce - cs, work / f"{c['id']}.wav"), ce - cs))
    used0 = dict(transcriber.used)
    for c, words in zip(cands, transcriber.words_many(items)):
        c["words"], c["frames"] = words, []
    counts["asr"] = {k: v - used0.get(k, 0) for k, v in transcriber.used.items() if v - used0.get(k, 0)}
    alive = [c for c in cands if len(c["words"]) >= 6 or c["breakdown"]["viewer_clips"] >= 1]

    st("judge", f"ИИ оценивает {len(alive)} кандидатов по тексту", 52)
    policy = learn.load(store, cfg)
    try:
        learned = learn.learned_examples(store, cfg)
    except Exception as e:  # noqa: BLE001
        log(f"примеры из статистики недоступны: {e}")
        learned = {}
    u0 = llm.totals()
    verdicts = judge_candidates(llm, cfg, alive, learned, (policy.get("hints") or {}).get("length", "")) if alive else {}
    text_pass = []
    for c in alive:
        v = verdicts.get(c["id"])
        if not v:
            continue
        sc = int(v.get("score", 0) or 0)
        if int((v.get("risk") or {}).get("level", 0)) >= 3:
            note_reject(store, vod, c["peak_abs"], "текст", "риск для аккаунта: " + ", ".join((v.get("risk") or {}).get("flags", [])), sc, v.get("why", ""))
            continue
        if sc < make_min - 1:
            note_reject(store, vod, c["peak_abs"], "текст", v.get("why") or "слабый момент", sc)
            continue
        text_pass.append((c, v))
    text_pass.sort(key=lambda x: (-int(x[1].get("score", 0)), -x[0]["signal"]))
    finalists = text_pass[: max(2, int(q.get("max_per_chunk", 4)) * 2)]
    for c, v in text_pass[len(finalists):]:
        note_reject(store, vod, c["peak_abs"], "текст", "есть моменты сильнее в этом куске", v.get("score"), v.get("why", ""))
    counts["text_pass"] = len(text_pass)
    log(f"по тексту прошли {len(text_pass)} из {len(alive)}, на видео-проверку {len(finalists)}")

    # режиссёр смотрит видео финалистов — одновременно (загрузка превью и ответ ИИ — это ожидание, не CPU)
    st("video", f"ИИ смотрит видео {len(finalists)} финалистов одновременно", 58)

    def review(item):
        c, v = item
        s0, e0 = snap_bounds(c["words"], v.get("start", 0), v.get("end", c["ctx_dur"]), c["ctx_dur"], cfg)
        try:
            return _review_on_video(cfg, store, llm, vod, c, v, s0, e0, work)
        except Exception as e:  # noqa: BLE001 — один финалист не валит кусок
            log(f"⚠️ проверка {c['id']} упала: {str(e)[:200]}")
            return None
    with ThreadPoolExecutor(max_workers=max(1, min(int(ai.get("parallel_reviews", 3)), len(finalists) or 1))) as ex:
        plans = [x for x in ex.map(review, finalists) if x]
    counts["video_checked"] = len(finalists)
    plans.sort(key=lambda x: -x["score"])
    counts["video_pass"] = len(plans)

    exc = int(q.get("exceptional", 9))
    limit = int(q.get("max_per_chunk", 4))
    picked = [x for x in plans if x["score"] >= make_min][:limit]
    picked += [x for x in plans if x not in picked and x["score"] >= exc]
    for x in plans:
        if x not in picked:
            note_reject(store, vod, x["abs_s"], "отбор", "в куске есть клипы сильнее (лимит на кусок)", x["score"], x.get("what", ""))

    # один момент, найденный дважды (пик + разведчик, перекрытие кусков), монтируем один раз
    uniq = []
    for x in picked:
        xa, xb = x["c"]["ctx_start"] + x["s"], x["c"]["ctx_start"] + x["e"]
        same = next((u for u in uniq if min(xb, u[2]) - max(xa, u[1]) >= 0.4 * max(1.0, min(xb - xa, u[2] - u[1]))), None)
        if same:
            note_reject(store, vod, xa, "дубль", f"тот же момент, что и {clip_key(vod, same[0])}", x["score"], x.get("what", ""))
        else:
            uniq.append((x, xa, xb))
    picked = [u[0] for u in uniq]
    platforms = targets_for(cfg, store)
    made = 0
    # исходники всех отобранных качаем параллельно заранее; монтаж (CPU) идёт по очереди
    pre = ThreadPoolExecutor(max_workers=3)
    for k, pl in enumerate(picked):
        a, b = source_range(pl)
        pl["_src"] = pre.submit(download_video, vod["id"], a, b, work / f"{clip_key(vod, pl)}_pre{k}.mp4")   # свои имена файлов
    try:
        for k, pl in enumerate(picked):
            st("render", f"Монтирую клип {k + 1}/{len(picked)}", 80 + int(18 * k / max(1, len(picked))))
            try:
                made += bool(make_clip(cfg, store, llm, policy, vod, pl, platforms, work))
            except Exception as e:  # noqa: BLE001 — один битый клип не валит всё
                log(f"⚠️ клип не собран: {str(e)[:400]}")
                health.report(store, "render", "warn", f"клип не собран: {str(e)[:200]}")
    finally:
        pre.shutdown(wait=True)
    counts["made"] = made

    spent = llm.delta(u0)
    if spent["by_model"]:
        log(f"ИИ за кусок: {sum(x['calls'] for x in spent['by_model'].values())} запросов, ≈${spent['usd']:.4f}")
    counts["usd"] = spent["usd"]
    note_chunk(store, vod, label, counts)
    vstate = store.read_json("vods.json", {}) or {}
    rec = vstate.get(vid, rec)
    rec.update(title=vod.get("title"), created_at=vod["created_at"], duration=vod["duration_sec"],
               llm={"usd": round(float((rec.get("llm") or {}).get("usd", 0) or 0) + spent["usd"], 4)},
               processed_until=max(int(rec.get("processed_until", 0)), int(end)), finished=bool(final),
               candidate_times=(rec.get("candidate_times", []) + [c["peak_abs"] for c in cands])[-400:],
               clips=int(rec.get("clips", 0)) + made, updated_at=now_iso())
    rec["gaps"] = [g for g in rec.get("gaps", []) if not (g["start"] >= start and g["end"] <= end)]
    rec.get("fails", {}).pop(f"{int(start)}-{int(end)}", None)
    vstate[vid] = rec
    store.write_json("vods.json", vstate)
    store.sync(f"vod {vid}: кусок {label}, клипов {made}")
    shutil.rmtree(work, ignore_errors=True)


def _review_on_video(cfg, store: Store, llm: LLM, vod: dict, c: dict, v: dict, s0: float, e0: float, work: Path) -> dict | None:
    """Скачать фрагмент в 360p → проверить зависания → Gemini смотрит и режет → план клипа (или None с причиной)."""
    from . import brain
    ai, q = cfg.get("ai") or {}, cfg.get("quality") or {}
    make_min = int(q.get("make_min", 7))
    pad = 3.0
    p0 = max(c["ctx_start"], c["ctx_start"] + s0 - pad)          # начало превью, абсолютное время VOD
    p1 = c["ctx_start"] + min(c["ctx_dur"], e0 + pad)
    t_abs = c["ctx_start"] + s0
    try:
        low = download_video(vod["id"], p0, p1, work / f"{c['id']}_low.mp4", max_height=480)
        tech = brain.freeze_report(low)
    except Exception as e:  # noqa: BLE001
        log(f"превью {c['id']} не скачалось: {str(e)[:160]}")
        low, tech = None, {}
    off = p0 - c["ctx_start"]                                    # секунды окна → секунды превью: x - off
    if tech.get("frozen_frac", 0) > 0.35:
        note_reject(store, vod, t_abs, "видео", f"лаги записи: картинка стоит {tech['frozen']} с из {tech['duration']} с",
                    v.get("score"), v.get("why", ""))
        return None
    js = None
    if ai.get("video_review", True) and low is not None:
        try:
            prev = brain.preview_clip(low, work / f"{c['id']}_prev.mp4")
            words_rel = [{"w": w["w"], "s": round(w["s"] - off, 2), "e": round(w["e"] - off, 2)}
                         for w in c["words"] if off - 0.1 <= w["s"] <= p1 - c["ctx_start"]]
            js = brain.direct(llm, cfg, prev, words_rel, c.get("chat_sample", []), v, tech)
        except Exception as e:  # noqa: BLE001
            log(f"режиссёр не ответил по {c['id']}: {str(e)[:200]}")
            js = None
    if js is None:
        # без видео-проверки выпускаем только очень уверенные по тексту моменты
        if int(v.get("score", 0)) < make_min + 1:
            note_reject(store, vod, t_abs, "видео", "видео-проверка недоступна, а по тексту момент не железный", v.get("score"), v.get("why", ""))
            return None
        ed = edit_clips(llm, cfg, [{"id": c["id"], "dur": e0 - s0, "category": v.get("category"), "why": v.get("why"),
                                     "words": [{"w": w["w"], "s": round(w["s"] - s0, 2), "e": round(w["e"] - s0, 2)} for w in c["words"] if s0 - 0.1 <= w["s"] < e0],
                                     "chat_sample": c.get("chat_sample", [])}]).get(c["id"])
        if not ed:
            note_reject(store, vod, t_abs, "тексты", "ИИ-редактор не ответил", v.get("score"))
            return None
        e0, _ = cap_kept(s0, e0, [], 60.0)   # без просмотра видео длинное не выпускаем
        return {"c": c, "v": v, "s": s0, "e": e0, "cuts": [], "ed": ed, "score": int(v.get("score", 0)), "abs_s": t_abs,
                "what": v.get("why", ""), "brain": {"text": _brief(v), "video": None, "tech": tech}}
    score = int(js.get("score", 0) or 0)
    lag = int((js.get("technical") or {}).get("lag", 0) or 0)
    why_bad = None
    if str(js.get("verdict", "")).lower() != "post":
        why_bad = js.get("reject_reason") or "режиссёр не советует публиковать"
    elif lag >= 2:
        why_bad = "лаги: " + ", ".join((js.get("technical") or {}).get("issues") or ["картинка тормозит"])
    elif js.get("standalone") is False:
        why_bad = "непонятно без контекста стрима"
    elif score < make_min:
        why_bad = f"после просмотра видео оценка {score}: {js.get('moment') or js.get('what_happens') or ''}"
    elif int((js.get("risk") or {}).get("level", 0) or 0) >= 3:
        why_bad = "риск для аккаунта: " + ", ".join((js.get("risk") or {}).get("flags", []))
    if not why_bad and ai.get("second_opinion", True) and score == make_min:
        # пограничный клип: второй независимый просмотр, итог — среднее (вниз). Дёшево: только на границе порога
        try:
            js2 = brain.direct(llm, cfg, prev, words_rel, c.get("chat_sample", []), v, tech)
            s2 = int(js2.get("score", 0) or 0) if str(js2.get("verdict", "")).lower() == "post" else min(
                int(js2.get("score", 0) or 0), make_min - 1)
            score = (score + s2) // 2
            if score < make_min:
                why_bad = f"второе мнение: {s2}/10 — {js2.get('reject_reason') or js2.get('moment') or 'не уверен'}"
        except Exception as e:  # noqa: BLE001
            log(f"второе мнение недоступно ({str(e)[:120]}) — остаюсь при первом")
    if why_bad:
        note_reject(store, vod, t_abs, "видео", why_bad, score, js.get("what_happens", ""))
        return None
    # время превью → время окна
    try:
        ns, ne = float(js.get("start", s0 - off)) + off, float(js.get("end", e0 - off)) + off
    except (TypeError, ValueError):
        ns, ne = s0, e0
    ns, ne = max(0.0, min(ns, c["ctx_dur"] - 1)), min(c["ctx_dur"], max(ne, ns + 1))
    s1, e1 = snap_bounds(c["words"], ns, ne, c["ctx_dur"], cfg)
    cuts = []
    for cut in js.get("cuts") or []:
        try:
            a, b = float(cut[0]) + off, float(cut[1]) + off
        except (TypeError, ValueError, IndexError):
            continue
        if s1 < a < b < e1 and b - a >= 0.6:
            cuts.append((round(a, 2), round(b, 2)))
    length_note = None
    if kept_len(s1, e1, cuts) > 60:
        # длиннее минуты — только после отдельной строгой проверки: держит ли ролик внимание всё время
        try:
            lc = brain.check_length(llm, cfg, prev, words_rel, s1 - off, e1 - off, [[a - off, b - off] for a, b in cuts],
                                    float(tech.get("duration") or (p1 - p0)))
            if not lc.get("keep_long"):
                try:
                    ns2, ne2 = float(lc.get("start")) + off, float(lc.get("end")) + off
                except (TypeError, ValueError):
                    ns2, ne2 = s1, e1
                if s1 - 0.5 <= ns2 < ne2 <= e1 + 0.5 and ne2 - ns2 >= float(cfg["clips"]["min_seconds"]):
                    s1, e1 = snap_bounds(c["words"], ns2, ne2, c["ctx_dur"], cfg)
                    cuts = [(round(float(x[0]) + off, 2), round(float(x[1]) + off, 2)) for x in lc.get("cuts") or []
                            if isinstance(x, (list, tuple)) and len(x) == 2 and s1 < float(x[0]) + off < float(x[1]) + off < e1
                            and float(x[1]) - float(x[0]) >= 0.6]
                # «не держит длинный хронометраж» — значит, в итоге не длиннее минуты, что бы ни вернула модель
                e1, cuts = cap_kept(s1, e1, cuts, 60.0)
            length_note = {"keep_long": bool(lc.get("keep_long")), "why": str(lc.get("why", ""))[:200],
                           "final_s": round(kept_len(s1, e1, cuts), 1)}
        except Exception as e:  # noqa: BLE001 — проверка недоступна: длинное не выпускаем, режем до минуты
            log(f"проверка длины {c['id']} недоступна ({str(e)[:120]}) — ограничиваю минутой")
            e1, cuts = cap_kept(s1, e1, cuts, 60.0)
            length_note = {"keep_long": False, "why": "проверка недоступна — ограничено минутой"}
    if ai.get("proofread", True) and low is not None:
        js = _proofread(cfg, store, llm, c, js, low, off, p1, work)   # субтитры и тексты = то, что реально сказано
    v2 = {**v, "score": score, "category": js.get("category") or v.get("category"), "risk": js.get("risk") or v.get("risk"),
          "why": js.get("moment") or v.get("why"), "subscores": js.get("subscores") or {}}
    return {"c": c, "v": v2, "s": s1, "e": e1, "cuts": cuts, "ed": js, "score": score, "abs_s": c["ctx_start"] + s1,
            "what": js.get("what_happens", ""),
            "brain": {"text": _brief(v), "video": {k: js.get(k) for k in ("verdict", "score", "subscores", "what_happens",
                                                                        "moment", "technical", "standalone")},
                      "tech": tech, "proofread": js.get("proofread") or [], "length": length_note}}


def _proofread(cfg, store: Store, llm: LLM, c: dict, js: dict, low: Path, off: float, p1: float, work: Path) -> dict:
    """ИИ слушает звук финалиста и правит ошибки распознавания в словах (→ субтитры) и в текстах режиссёра."""
    from . import proofread as PR
    idx = [i for i, w in enumerate(c["words"]) if off - 0.1 <= w["s"] <= p1 - c["ctx_start"]]
    if not idx:
        return js
    try:
        audio = PR.audio_of(low, work / f"{c['id']}_proof.ogg")
        fixes, english = PR.proofread(llm, cfg, audio, [c["words"][i] for i in idx], what=js.get("what_happens", ""),
                                      chat=c.get("chat_sample"), past=PR.hints(store))
    except Exception as e:  # noqa: BLE001 — корректор не обязателен
        log(f"корректор {c['id']} недоступен: {str(e)[:140]}")
        return js
    pairs = []
    eng_idx = {idx[k] for seg in english for k in range(seg["from"], seg["to"] + 1)}
    for k, new in sorted(fixes.items()):
        if idx[k] in eng_idx:
            continue                                  # английский участок перепишется целиком ниже
        w = c["words"][idx[k]]
        pairs.append((w["w"], new))
        w["w"] = PR._keep_punct(w["w"], new)
    trans = []
    for seg in sorted(english, key=lambda x: -x["from"]):   # с конца: индексы начала не сдвигаются
        t = PR.apply_english(c["words"], {**seg, "from": idx[seg["from"]], "to": idx[seg["to"]]})
        if t and t["ru"]:
            trans.append(t)
    if trans:
        c["trans"] = sorted((c.get("trans") or []) + trans, key=lambda x: x["s"])
        log(f"корректор {c['id']}: английская речь — {len(trans)} участок(ов), перевод снизу")
    if pairs:
        PR.learn(store, pairs)
        log(f"корректор {c['id']}: " + ", ".join(f"{a}→{b}" for a, b in pairs[:10]))
        still = {PR.norm(w["w"]) for w in c["words"]}   # слово ещё звучит в ролике правильно — в текстах не трогаем
        js = PR.fix_texts(js, {PR.norm(a): b for a, b in pairs
                               if len(b.split()) == 1 and len(PR.norm(a)) >= 4 and PR.norm(a) not in still})
    js["proofread"] = [f"{a} → {b}" for a, b in pairs][:20] + [f"EN: {s['en'][:60]} — «{s['ru'][:60]}»" for s in english][:5]
    return js


def _brief(v: dict) -> dict:
    return {k: v.get(k) for k in ("score", "hook", "payoff", "clarity", "emotion", "rewatch", "why", "category")}


def targets_for(cfg: dict, store: Store) -> list[str]:
    """Под какие площадки готовить тексты: включённые в настройках и подключённые (TikTok — всегда, если включён)."""
    on = cfg.get("platforms") or {"tiktok": 1, "youtube": 1, "instagram": 1}
    plats = ["tiktok"] + sorted(connected_platforms(cfg, store) - {"tiktok"})
    return [p for p in plats if p in on]


def make_clip(cfg, store: Store, llm: LLM, policy: dict, vod: dict, pl: dict, platforms: list[str], work: Path) -> bool:
    """Один монтаж → один файл → одинаковое видео на всех площадках (разные только тексты под площадку)."""
    from . import brain
    from .framing import static_crop
    c, v, ed = pl["c"], pl["v"], pl["ed"]
    s, e = pl["s"], pl["e"]
    cl = cfg["clips"]
    abs_s, dur = c["ctx_start"] + s, e - s
    clip_id = clip_key(vod, pl)
    if store.read_json(f"queue/{clip_id}.json"):
        log(f"{clip_id} уже есть в очереди — пропускаю")
        return False
    dup = overlapping_clip(store, vod["id"], abs_s, abs_s + dur)
    if dup:   # куски записи перекрываются, разведчик и пики могут найти один момент дважды
        note_reject(store, vod, abs_s, "дубль", f"этот момент уже есть в клипе {dup}", pl["score"], pl.get("what", ""))
        return False
    pad = min(2.0, abs_s)
    src_off = abs_s - pad
    src = None
    if pl.get("_src") is not None:
        try:
            src = pl["_src"].result()
        except Exception as ex:  # noqa: BLE001
            log(f"заранее скачанный исходник {clip_id} не готов: {str(ex)[:160]} — качаю заново")
    if src is None:
        src = download_video(vod["id"], src_off, abs_s + dur + 1.5, work / f"{clip_id}_src.mp4")

    au = inspect_clip_audio(src, pad, dur, work, cfg)
    if au["action"] == "skip":
        note_reject(store, vod, abs_s, "звук", au["reason"], pl["score"], pl.get("what", ""))
        return False
    risk = dict(v.get("risk") or {"level": 0, "flags": []})
    if au["action"] == "flag":
        risk["flags"] = sorted(set(risk.get("flags", [])) | {"music"})

    # слова и вырезы — во времени исходника (src)
    to_src = lambda t: t - s + pad
    words_src = [{**w, "s": round(to_src(w["s"]), 2), "e": round(to_src(w["e"]), 2)}
                 for w in c["words"] if s - 0.1 <= w["s"] < e]
    mn = float(cl.get("min_seconds", 10))
    segs = [(pad, pad + dur)]
    if cl.get("trim_silence", True):
        runs = speech_runs(words_src, pad, pad + dur, max_gap=float(cl.get("trim_gap_seconds", 1.2)))
        if sum(b - a for a, b in runs) >= 0.75 * mn:
            segs = runs
    if pl.get("cuts"):
        cut = brain.apply_cuts(segs, [(to_src(a), to_src(b)) for a, b in pl["cuts"]])
        if sum(b - a for a, b in cut) >= 0.75 * mn:
            segs = cut
    kept = sum(b - a for a, b in segs)
    from .render import trans_to_output, words_to_output
    words_final = words_to_output(words_src, segs)
    trans_out = trans_to_output([{"s": to_src(t["s"]), "e": to_src(t["e"]), "ru": t["ru"]}
                                 for t in c.get("trans") or [] if t["e"] > s and t["s"] < e], segs)

    # хуки: правдивые, не скопированные из примеров; критик — последний голос
    tr = " ".join(w["w"] for w in words_final)
    orig = [h for h in (ed.get("hooks") or []) if isinstance(h, dict)]
    try:
        pick_text = orig[int(ed.get("pick", 0) or 0)].get("text")
    except (IndexError, ValueError, TypeError):
        pick_text = None
    hooks = [h for h in orig if h.get("text") and not brain.leaked(h["text"])]
    if not hooks:
        note_reject(store, vod, abs_s, "тексты", "нет нормального заголовка", pl["score"], pl.get("what", ""))
        return False
    pick = next((i for i, h in enumerate(hooks) if h.get("text") == pick_text), 0)
    ed = {**ed, "hooks": hooks, "pick": pick}
    rng = random.Random(clip_id)
    variant = learn.choose_variant(policy, "all", cfg, rng)
    if variant.get("hook_style") not in {h.get("style") for h in hooks}:
        variant["hook_style"] = hooks[pick].get("style")
    tx0 = target_texts(ed, "tiktok", variant.get("hook_style"), cfg)
    crit = brain.criticize(llm, cfg, ed, words_final, tx0["hook"])
    if not crit.get("ok", True) or crit.get("title_matches") is False or crit.get("makes_sense") is False:
        fix = (crit.get("fix_hook") or "").strip()
        if crit.get("makes_sense") is False or not fix or brain.leaked(fix):
            note_reject(store, vod, abs_s, "критик", "; ".join(crit.get("problems") or ["заголовок не совпадает с роликом"]),
                        pl["score"], pl.get("what", ""))
            return False
        hooks = [{"style": tx0["hook_style"], "text": fix}] + [h for h in hooks if h.get("text") != tx0["hook"]
                                                              and h.get("style") != tx0["hook_style"]]
        variant["hook_style"] = tx0["hook_style"]
        if crit.get("fix_title"):
            ed = {**ed, "youtube": {**(ed.get("youtube") or {}), "title": crit["fix_title"]}}
        ed = {**ed, "hooks": hooks, "pick": 0}
    for key, field in (("tiktok", "caption"), ("youtube", "title"), ("instagram", "caption")):
        pp = ed.get(key) or {}
        if grounded(pp.get(field, ""), tr + " " + str(pl.get("what", ""))) < 0.4:
            ed[key] = {**pp, field: hooks[0]["text"]}

    out_dir = work / "out"
    out_dir.mkdir(exist_ok=True)
    sw, sh, _ = probe(src)
    crop_frac = min(1.0, (sh * W_PANEL_ASPECT) / sw) if sw else 1.0
    pan = static_crop(src, segs[0][0], segs[-1][1], crop_frac) if crop_frac < 0.98 and sh <= sw * 1.2 else None
    tx_all = {plat: target_texts(ed, plat, variant.get("hook_style"), cfg) for plat in platforms}
    lead = tx_all.get("tiktok") or next(iter(tx_all.values()))
    title = fit_title(*lead["hook_alts"])
    out = out_dir / f"{clip_id}.mp4"
    problems = []
    for attempt in range(2):
        try:
            render_clip(src, segs, words_src, title, cfg, out, variant={}, audio_override=au.get("audio_override"),
                        pan_keys=pan, trans=trans_out)
            problems = validate_render(out, kept, "instagram")
        except Exception as ex:  # noqa: BLE001
            problems = [f"рендер упал: {str(ex)[:160]}"]
        if not problems:
            break
        log(f"⚠️ {clip_id}: {problems} — попытка {attempt + 2}")
    if problems:
        health.report(store, "render", "warn", f"{clip_id}: " + "; ".join(problems))
        note_reject(store, vod, abs_s, "монтаж", "; ".join(problems), pl["score"])
        return False
    thumb = thumb_b64(out, at=min(1.2, kept / 2))
    asset = releases.upload(out)
    hq = hook_quality({"speech_start": (words_final[0]["s"] if words_final else None)}, False, title[0])
    targets = {}
    for plat, tx in tx_all.items():
        targets[plat] = {**{k: val for k, val in tx.items() if k != "hook_alts"}, "hook_alts": tx["hook_alts"][:4],
                         "hook": lead["hook"], "hook_style": lead["hook_style"],
                         "asset": asset, "size": out.stat().st_size, "duration": round(kept, 1),
                         "variant": {"hook_style": lead["hook_style"]}, "hook_quality": hq, "status": "ready",
                         "comment": humanize_comment(ed.get("comment", "")), "cover_ms": 500}
    store.write_json(f"queue/{clip_id}.json", {
        "id": clip_id, "vod_id": vod["id"], "vod_title": vod.get("title"), "vod_time": round(abs_s, 1),
        "duration": round(kept, 1), "span": round(dur, 1), "score": int(pl["score"]), "subscores": v.get("subscores") or {},
        "category": v.get("category", "other"), "risk": risk, "why": v.get("why", ""), "what": pl.get("what", ""),
        "overlay": lead["hook"], "signal": c.get("signal", 0), "breakdown": c.get("breakdown", {}),
        "audio": {k: au[k] for k in ("muted", "music", "action") if k in au} | {"reason": au.get("reason")},
        "brain": {**pl.get("brain", {}), "critic": {k: crit.get(k) for k in ("ok", "problems", "fix_hook", "skipped")},
                  "cuts": len(segs) - 1, "trimmed_s": round(dur - kept, 1)},
        "transcript": tr[:700], "thumb": thumb, "targets": targets, "posts": {}, "created_at": now_iso(),
        "live_when_made": bool((store.read_json("status/live.json", {}) or {}).get("is_live")), "fresh": bool(v.get("fresh")),
        "uid": uuid.uuid4().hex[:8], "asset": asset,
        "vod_url": f"https://www.twitch.tv/videos/{vod['id']}?t={_hms(src_off + segs[0][0])}",
    })
    record_moment(store, {
        "id": clip_id, "vod_id": vod["id"], "vod_title": vod.get("title"), "created_at": now_iso(),
        "t": round(src_off + segs[0][0], 2), "category": v.get("category", "other"), "score": int(pl["score"]),
        "text": tr[:400], "segments": [[round(src_off + a, 2), round(src_off + b, 2)] for a, b in segs],
        "words": [[w["w"], round(src_off + w["s"], 2), round(src_off + w["e"], 2)] for w in words_src][:160],
    })
    store.sync(f"клип {clip_id} готов (оценка {pl['score']}, {kept:.0f} с)")
    log(f"✅ {clip_id} оценка={pl['score']} {kept:.0f}с (вырезано {dur - kept:.1f} с) «{lead['hook']}»")
    return True


def proofread_terms(store: Store, cfg: dict) -> list[str]:
    from . import proofread as PR
    try:
        return PR.terms(store, cfg)
    except Exception:  # noqa: BLE001
        return []


def kept_len(s: float, e: float, cuts: list) -> float:
    """Длина ролика после вырезов (учитываются только вырезы внутри [s, e])."""
    return (e - s) - sum(max(0.0, min(b, e) - max(a, s)) for a, b in cuts)


def cap_kept(s: float, e: float, cuts: list, limit: float) -> tuple[float, list]:
    """Сдвинуть конец так, чтобы после вырезов осталось не больше limit секунд. → (новый конец, вырезы внутри)."""
    if kept_len(s, e, cuts) <= limit:
        return e, [(a, b) for a, b in cuts if s < a < b < e]
    pos, left, inside = s, limit, []
    for a, b in sorted((a, b) for a, b in cuts if s < a < b < e):
        if a - pos >= left:
            break
        left -= a - pos
        inside.append((a, b))
        pos = b
    return round(pos + left, 2), inside


def clip_key(vod: dict, pl: dict) -> str:
    return f"{vod['id']}_{int(pl['c']['ctx_start'] + pl['s'])}"


def source_range(pl: dict) -> tuple[float, float]:
    """Какой кусок VOD нужен для монтажа (с запасом 2 с до и 1.5 с после) — то же, что считает make_clip."""
    abs_s = pl["c"]["ctx_start"] + pl["s"]
    return abs_s - min(2.0, abs_s), abs_s + (pl["e"] - pl["s"]) + 1.5


def overlapping_clip(store: Store, vod_id: str, a: float, b: float, share: float = 0.4) -> str | None:
    """id клипа этого VOD, который покрывает ≥ share нового момента (или наоборот) — это один и тот же момент."""
    for q in store.list_json("queue"):
        if q.get("vod_id") != vod_id or q.get("bundle"):
            continue
        qa = float(q.get("vod_time") or 0)
        qb = qa + float(q.get("span") or q.get("duration") or 0)
        ov = min(b, qb) - max(a, qa)
        if ov > 0 and ov >= share * max(1.0, min(b - a, qb - qa)):
            return q.get("id")
    return None


def _hms(sec: float) -> str:
    s = int(max(0, sec))
    return f"{s // 3600}h{s % 3600 // 60}m{s % 60}s"


def humanize_comment(text: str) -> str:
    from .judge import humanize
    return humanize(text, 1, "caption")[:90]
