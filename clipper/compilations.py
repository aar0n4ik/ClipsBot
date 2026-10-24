"""Сборные нарезки («связки»): моменты из РАЗНЫХ мест стрима в одном ролике.

Два вида:
  series   — один и тот же тип события несколько раз за стрим («4 раза промахнулся мимо адреса»);
  callback — фраза, обещание или ситуация в начале и её эхо/развязка спустя час-два.

Как работает:
1. Пока бот режет стрим кусками, каждый момент, который отборщик счёл живым (даже если он не стал отдельным клипом),
   запоминается в ветке data: moments/<vod>.json — время, пересказ, теги, мотив, оценка.
2. Когда стрим дорезан до конца, ИИ получает список всех моментов и предлагает связки.
3. Бот скачивает нужные куски, заново расшифровывает речь, монтирует один ролик (метки «№2», «через 1 ч 20 мин»)
   и кладёт в очередь как обычный клип, категория «compilation»: обучение само поймёт, заходят ли связки.
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path

from . import decisions, health, learn, releases
from .audio import inspect_clip_audio
from .framing import detect_subject, plan_pan
from .judge import edit_clips, fallback_texts, humanize, snap_segments, target_texts, translate_lines
from .llm import LLM, LLMError
from .qa import hook_quality, platform_maxrate, validate_render
from .render import PANEL_H, SRC_STRIDE, W, chunk_words, fit_title, probe, render_clip, thumb_b64, words_to_output
from .store import Store
from .transcribe import cut_wav
from .twitch import download_video
from .util import fmt_hms, log, now_iso

DEFAULTS = {"enabled": True, "min_moments": 4, "max_per_vod": 3, "min_seconds": 25, "max_seconds": 80,
            "min_score": 7, "max_pieces": 8, "min_piece": 1.5, "max_kept_moments": 150}

COMPILER = """Ты — монтажёр сборных нарезок для TikTok, YouTube Shorts и Instagram Reels. Тебе дан список моментов ОДНОГО стрима
(время от начала стрима, оценка, теги, мотив, реплики). Найди связки, которые вместе смотрятся ЛУЧШЕ, чем по отдельности.

Виды связок:
• series — 3–6 однотипных моментов: стример несколько раз за стрим делает одно и то же («4 раза промахнулся мимо адреса»,
  «все споры с навигатором», «каждый раз пытался отказаться от заказа»). Ставь от слабого к сильному, самый сильный в конце.
• callback — фраза, обещание, шутка или ситуация в одном месте, которая спустя время (даже через час-два) возвращается,
  оказывается важной, смешной или иронично сбывается. Сначала сетап (коротко), потом развязка. Часы между ними — это
  хорошо: зритель увидит «через час».
Смотри на теги и мотивы, но ищи и по репликам: повтор одной фразы, то же место, тот же человек, то же обещание.

Правила:
• Берёшь только моменты, у которых правда есть общее. Нет связок — верни пустой список, ничего не выдумывай.
• Каждый момент можно сократить: start/end в секундах от начала стрима внутри его границ (не указал — берём целиком).
  Режь всё, что не нужно для связки.
• Итоговая длина связки {min_s}–{max_s} с (обычно 6–20 с на момент), моментов в связке 2–6.
• Один момент — только в одной связке. Если момент уже выложен отдельным клипом, бери его, только если он центр связки.
• score 1–10 — шанс на просмотры именно этой связки; выше 7 только если она явно цепляет.
Ответ строго JSON:
{{"compilations":[{{"id":"k1","kind":"series","title":"что объединяет, 3–8 слов","why":"почему это работает вместе","score":8,
"parts":[{{"moment":"m123","start":1234.0,"end":1250.0}}]}}]}}"""


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("compilations") or {})}


# ── память о моментах ────────────────────────────────────────────
def moments_file(vid: str) -> str:
    return f"moments/{vid}.json"


def load(store: Store, vid: str) -> dict:
    d = store.read_json(moments_file(vid), None) or {}
    d.setdefault("moments", {})
    d.setdefault("compilations", [])
    return d


def _text(words: list[dict], segs: list[tuple[float, float]]) -> str:
    return " ".join(w["w"] for w in words if any(a - 0.05 <= w["s"] < b for a, b in segs))[:420]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    return inter / max(1e-6, min(a1 - a0, b1 - b0))


def record_moments(store: Store, vod: dict, cfg: dict, alive: list[dict], verdicts: dict, plans: list[dict],
                   made_ids: set[str]):
    """Запоминаем все живые моменты куска (не только ставшие клипами): связки собираются из них."""
    if not settings(cfg)["enabled"]:
        return
    data = load(store, vod["id"])
    planned = {pl["id"]: pl for pl in plans}
    for c in alive:
        v = verdicts.get(c["id"])
        if not v:
            continue
        score = int(v.get("score", 0) or 0)
        if not v.get("keep") and score < 3:
            continue
        pl = planned.get(c["id"])
        if pl:
            win = [(pl["s"] + a, pl["s"] + b) for a, b in pl["segs"]]
        else:
            win = snap_segments(c["words"], v.get("segments"), v.get("start", 0), v.get("end", c["ctx_dur"]),
                                c["ctx_dur"], cfg)
        segs = [[round(c["ctx_start"] + a, 1), round(c["ctx_start"] + b, 1)] for a, b in win]
        m = {"id": f"m{int(c['peak_abs'])}", "start": segs[0][0], "end": segs[-1][1], "segs": segs, "score": score,
             "category": v.get("category", "other"), "tags": [str(t)[:30] for t in (v.get("tags") or [])][:3],
             "motif": str(v.get("motif") or "")[:80], "why": str(v.get("why") or "")[:160],
             "text": _text(c["words"], win), "keep": bool(v.get("keep")),
             "clip_id": f"{vod['id']}_{int(c['ctx_start'] + pl['s'])}" if pl and
             f"{vod['id']}_{int(c['ctx_start'] + pl['s'])}" in made_ids else None}
        dup = next((k for k, o in data["moments"].items()
                    if k != m["id"] and _overlap(o["start"], o["end"], m["start"], m["end"]) >= 0.5), None)
        if dup:
            if data["moments"][dup]["score"] >= score:
                continue
            data["moments"].pop(dup)
        data["moments"][m["id"]] = m
    keep_n = int(settings(cfg)["max_kept_moments"])
    if len(data["moments"]) > keep_n:
        best = sorted(data["moments"].values(), key=lambda x: -x["score"])[:keep_n]
        data["moments"] = {x["id"]: x for x in best}
    store.write_json(moments_file(vod["id"]), data)
    log(f"моментов для связок: {len(data['moments'])}")


# ── подбор связок ────────────────────────────────────────────────
def _clip_segments(segs: list[list[float]], a: float, b: float, min_piece: float) -> list[tuple[float, float]]:
    out = []
    for x, y in segs:
        lo, hi = max(x, a), min(y, b)
        if hi - lo >= min_piece:
            out.append((round(lo, 1), round(hi, 1)))
    return out


def validate(js: dict, moments: dict, cfg: dict, existing: list[set[str]]) -> list[dict]:
    """Проверяем ответ ИИ: известные моменты, границы внутри моментов, длина, повторы. Годные связки — по убыванию оценки."""
    cc = settings(cfg)
    out, used = [], set()
    for comp in (js.get("compilations") or [])[:6]:
        pieces, ids = [], []
        for p in comp.get("parts") or []:
            m = moments.get(str(p.get("moment")))
            if not m or m["id"] in ids or m["id"] in used:
                continue
            try:
                a, b = float(p.get("start", m["start"])), float(p.get("end", m["end"]))
            except (TypeError, ValueError):
                a, b = m["start"], m["end"]
            a, b = max(m["start"], a), min(m["end"], b)
            segs = _clip_segments(m["segs"], a, b, cc["min_piece"]) if b > a else []
            if not segs:
                segs = _clip_segments(m["segs"], m["start"], m["end"], cc["min_piece"])
            if not segs:
                continue
            ids.append(m["id"])
            pieces.append({"moment": m["id"], "segs": segs})
        total = lambda: sum(b - a for pc in pieces for a, b in pc["segs"])
        while total() > cc["max_seconds"] and len(pieces) > 2:   # длинно — убираем самый слабый из средних
            mid = range(1, len(pieces) - 1) if len(pieces) > 2 else range(len(pieces))
            drop = min(mid, key=lambda i: moments[pieces[i]["moment"]]["score"])
            ids.remove(pieces[drop]["moment"])
            pieces.pop(drop)
        if len(pieces) < 2 or not (cc["min_seconds"] <= total() <= cc["max_seconds"]):
            continue
        if sum(len(pc["segs"]) for pc in pieces) > cc["max_pieces"]:
            continue
        key = set(ids)
        if any(len(key & e) / max(1, min(len(key), len(e))) >= 0.6 for e in existing):
            continue
        score = int(comp.get("score", 0) or 0)
        if score < cc["min_score"]:
            continue
        used |= key
        out.append({"id": str(comp.get("id") or uuid.uuid4().hex[:4]),
                    "kind": comp.get("kind") if comp.get("kind") in ("series", "callback") else "series",
                    "title": str(comp.get("title") or "")[:80], "why": str(comp.get("why") or "")[:200],
                    "score": min(10, score), "parts": pieces, "key": sorted(key)})
    out.sort(key=lambda x: -x["score"])
    return out[: cc["max_per_vod"]]


def plan_compilations(llm: LLM, cfg: dict, data: dict) -> list[dict]:
    cc = settings(cfg)
    moments = data["moments"]
    lines = []
    for m in sorted(moments.values(), key=lambda x: x["start"]):
        extra = "; уже выложен отдельным клипом" if m.get("clip_id") else ""
        tags = ", ".join(m.get("tags") or []) or "—"
        motif = f"; мотив: {m['motif']}" if m.get("motif") else ""
        lines.append(f"[{m['id']}] {fmt_hms(m['start'])}–{fmt_hms(m['end'])} (секунды стрима {m['start']:.0f}–{m['end']:.0f}, "
                     f"оценка {m['score']}, {m.get('category', '')}{extra}) теги: {tags}{motif}\\n   «{m.get('text', '')}»")
    system = COMPILER.format(min_s=cc["min_seconds"], max_s=cc["max_seconds"])
    js = llm.chat_json([{"role": "system", "content": system},
                        {"role": "user", "content": "Моменты стрима:\n" + "\n".join(lines).replace("\\n", "\n")}],
                       temperature=0.4, max_tokens=4000)
    existing = [set(c.get("key") or []) for c in data.get("compilations", [])]
    return validate(js, moments, cfg, existing)


# ── сборка ролика ────────────────────────────────────────────────
def _gap_text(sec: float) -> str:
    m = int(round(sec / 60))
    h, mm = divmod(m, 60)
    return "через " + (f"{h} ч {mm} мин" if h and mm else f"{h} ч" if h else f"{max(1, mm)} мин")


def merge_pan(parts: list[list[tuple[float, float]]], gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Положение кадра по нескольким кускам в одной оси времени. Между кусками — «переезд» в паузе, которую никто не видит.
    parts[i] — ключи куска i (время уже виртуальное); gaps[i] = (конец куска i, начало куска i+1)."""
    keys = list(parts[0])
    for i in range(1, len(parts)):
        end_t, start_t = gaps[i - 1]
        keys += [(end_t, keys[-1][1]), (start_t, parts[i][0][1])] + list(parts[i][1:])
    return keys


def make_compilation(cfg: dict, store: Store, llm: LLM, transcriber, policy: dict, vod: dict, comp: dict,
                     platforms: list[str], work: Path, cap_height: int | None) -> bool:
    cc = settings(cfg)
    moments = load(store, vod["id"])["moments"]
    kid = f"{vod['id']}_k{int(moments[comp['parts'][0]['moment']]['start'])}"
    work.mkdir(parents=True, exist_ok=True)

    # 1. куски: скачиваем, проверяем звук, расшифровываем
    srcs: list[Path] = []
    segs: list[tuple[float, float]] = []
    words_src: list[dict] = []
    piece_meta: list[dict] = []
    pan_parts, pan_gaps = [], []
    risk_flags: set[str] = set()
    for pc in comp["parts"]:
        for a, b in pc["segs"]:
            if len(srcs) >= cc["max_pieces"]:
                break
            want = min(2.0, a)
            src, t0 = download_video(vod["id"], a - want, b + 1.5, work / f"{kid}_p{len(srcs)}.mp4", max_height=cap_height)
            pad = a - t0
            ln = b - a
            _, _, has_audio = probe(src)
            if not has_audio:
                log(f"связка {kid}: у куска {fmt_hms(a)} нет звука — пропускаю")
                continue
            au = inspect_clip_audio(src, pad, ln, work, cfg)
            if au["action"] == "skip":
                log(f"связка {kid}: кусок {fmt_hms(a)} пропущен: {au['reason']}")
                continue
            if au["action"] == "flag":
                risk_flags.add("music")
            i = len(srcs)
            base = i * SRC_STRIDE
            wav = cut_wav(src, pad, ln, work / f"{kid}_{i}.wav")
            for w in transcriber.words(wav):
                words_src.append({"w": w["w"], "s": round(base + pad + w["s"], 2), "e": round(base + pad + w["e"], 2)})
            srcs.append(src)
            segs.append((base + pad, base + pad + ln))
            piece_meta.append({"moment": pc["moment"], "abs": a, "dur": ln, "pad": pad})
    if len({m["moment"] for m in piece_meta}) < 2:
        decisions.record(store, "skip", f"Связка «{comp['title']}» не собрана: после проверки осталось меньше двух моментов",
                         reversible=False)
        return False

    sw, sh, _ = probe(srcs[0])
    asp = W / PANEL_H
    crop_frac = min(1.0, (sh * asp) / sw) if sw else 1.0
    pan = None
    if cfg["clips"].get("follow_subject", True) and crop_frac < 0.98 and sh <= sw * 1.2:
        for i, (a, b) in enumerate(segs):
            la, lb = a - i * SRC_STRIDE, b - i * SRC_STRIDE
            keys = plan_pan(detect_subject(srcs[i], la, lb), la, lb, crop_frac)
            pan_parts.append([(t + i * SRC_STRIDE, x) for t, x in keys])
            if i:
                pan_gaps.append((segs[i - 1][1], a))
        pan = merge_pan(pan_parts, pan_gaps)

    # 2. итоговая шкала времени, метки перехода
    words_out = words_to_output(words_src, segs)
    dur = sum(b - a for a, b in segs)
    notes, off, seen, order = [], 0.0, {}, []
    for (a, b), pm in zip(segs, piece_meta):
        if pm["moment"] not in seen:
            seen[pm["moment"]] = off
            order.append((pm["moment"], off, pm["abs"]))
        off += b - a
    if comp["kind"] == "series" and len(order) >= 3:
        notes = [{"t": o + 0.25, "text": f"№{k + 1}"} for k, (_, o, _) in enumerate(order)]
    elif comp["kind"] == "callback":
        first_abs = order[0][2]
        notes = [{"t": o + 0.25, "text": _gap_text(ab - first_abs)} for _, o, ab in order[1:] if ab - first_abs >= 600]

    # 3. тексты
    item = {"id": kid, "dur": dur, "words": words_out, "words_out": words_out, "chat_sample": [],
            "category": "compilation", "why": comp["why"],
            "note": (f"Это СБОРНАЯ нарезка из {len(order)} моментов одного стрима ({comp['kind']}): {comp['why']}. "
                     "Заголовок обещает связку целиком, не один момент. cold_open не используй. "
                     "notes не добавляй: метки переходов бот ставит сам.\n")}
    ed = (edit_clips(llm, cfg, [item]) or {}).get(kid)
    if not ed:
        ed = fallback_texts({}, words_out)
        t = humanize(comp["title"][:28], 0, "hook") or ed["hooks"][0]["text"]
        ed["hooks"] = [{"style": "tease", "text": t}]
        ed["tiktok"] = {"caption": t.lower(), "hashtags": []}
        ed["youtube"] = {"title": comp["title"][:70] or t, "description": comp["why"], "tags": []}
        ed["instagram"] = {"caption": t, "hashtags": []}
    ed["cold_open"] = {"use": False}
    ed["notes"] = []

    # 4. рендер под каждую площадку
    out_dir = work / "out"
    out_dir.mkdir(exist_ok=True)
    rng = random.Random(kid)
    targets, thumb, en_cache = {}, None, {}
    for plat in platforms:
        variant = learn.choose_variant(policy, plat, cfg, rng)
        variant["cold_open"] = False
        tx = target_texts(ed, plat, variant.get("hook_style"), cfg)
        en = None
        if variant.get("subtitles") == "both" and words_out:
            if "x" not in en_cache:
                try:
                    en_cache["x"] = translate_lines(llm, [" ".join(x["w"] for x in ch) for ch in chunk_words(words_out)])
                except Exception as ex:  # noqa: BLE001
                    log(f"перевод недоступен: {ex}")
                    en_cache["x"] = None
            en = en_cache["x"]
            if not en:
                variant["subtitles"] = "ru"
        title = fit_title(*tx["hook_alts"])
        out = out_dir / f"{kid}_{plat}.mp4"
        problems: list[str] = []
        for attempt in range(2):
            try:
                render_clip(srcs[0], segs, words_src, title, cfg, out, notes=notes, variant=variant, en_lines=en,
                            pan_keys=pan if pan is not None else [], extra_srcs=srcs[1:],
                            max_bitrate=platform_maxrate(cfg, plat, dur))
                problems = validate_render(out, dur, plat)
            except Exception as ex:  # noqa: BLE001
                problems = [f"рендер упал: {str(ex)[:160]}"]
            if not problems:
                break
            log(f"⚠️ {kid} {plat}: {problems} — попытка {attempt + 2}")
            variant = {**variant, "progress_bar": False}
        if problems:
            health.report(store, "render", "warn", f"{kid} {plat}: " + "; ".join(problems))
            continue
        if thumb is None:
            thumb = thumb_b64(out, at=min(1.0, dur / 2))
        targets[plat] = {**{k: val for k, val in tx.items() if k != "hook_alts"}, "hook_alts": tx["hook_alts"][:4],
                         "asset": releases.upload(out), "size": out.stat().st_size, "duration": round(dur, 1),
                         "variant": variant, "hook_quality": hook_quality({"speech_start": 0.0}, False, title[0]),
                         "status": "ready", "comment": humanize(ed.get("comment", ""), 1, "caption")[:90], "cover_ms": 600}
    if not targets:
        decisions.record(store, "skip", f"Связка «{comp['title']}» не собрана ни под одну площадку (рендер/проверка)",
                         reversible=False)
        return False

    first_abs = piece_meta[0]["abs"]
    store.write_json(f"queue/{kid}.json", {
        "id": kid, "vod_id": vod["id"], "vod_title": vod.get("title"), "vod_time": round(first_abs, 1),
        "duration": round(dur, 1), "score": int(comp["score"]), "subscores": {}, "category": "compilation",
        "kind": "compilation", "compilation": {"kind": comp["kind"], "title": comp["title"], "moments": comp["key"]},
        "risk": {"level": 0, "flags": sorted(risk_flags)}, "why": comp["why"],
        "overlay": next(iter(targets.values()))["hook"], "signal": 0, "breakdown": {},
        "audio": {"action": "flag" if risk_flags else "ok"}, "opening": {"speech_start": 0.0, "trimmed": 0.0},
        "notes": notes, "transcript": " ".join(w["w"] for w in words_out)[:600],
        "thumb": thumb, "targets": targets, "posts": {}, "created_at": now_iso(),
        "live_when_made": False, "uid": uuid.uuid4().hex[:8],
    })
    store.sync(f"связка {kid} готова ({comp['kind']}, {len(order)} моментов, площадки: {', '.join(targets)})")
    decisions.record(store, "hint", f"Собрана связка «{comp['title']}» ({comp['kind']}, {len(order)} моментов, {dur:.0f} с)",
                     reversible=False)
    log(f"✅ связка {kid} {comp['kind']} {dur:.0f}с")
    return True


def run_for_vod(cfg: dict, store: Store, llm: LLM, transcriber, policy: dict, vod: dict, platforms: list[str],
                work: Path, cap_height: int | None) -> int:
    """Вызывается, когда последний кусок стрима обработан. Возвращает, сколько связок собрано."""
    cc = settings(cfg)
    if not cc["enabled"]:
        return 0
    data = load(store, vod["id"])
    if len(data["moments"]) < cc["min_moments"]:
        log(f"связки: моментов {len(data['moments'])} < {cc['min_moments']}, пропускаю")
        return 0
    try:
        plans = plan_compilations(llm, cfg, data)
    except LLMError as e:
        log(f"связки: ИИ недоступен: {str(e)[:160]}")
        return 0
    log(f"связки: ИИ предложил {len(plans)}")
    made = 0
    for comp in plans:
        try:
            ok = make_compilation(cfg, store, llm, transcriber, policy, vod, comp, platforms, work / "compilations", cap_height)
        except Exception as e:  # noqa: BLE001 — одна связка не должна валить остальное
            log(f"⚠️ связка не собрана: {str(e)[:300]}")
            health.report(store, "render", "warn", f"связка не собрана: {str(e)[:200]}")
            ok = False
        data["compilations"].append({"key": comp["key"], "title": comp["title"], "kind": comp["kind"], "at": now_iso(),
                                     "ok": bool(ok)})
        made += bool(ok)
    store.write_json(moments_file(vod["id"]), data)
    return made
