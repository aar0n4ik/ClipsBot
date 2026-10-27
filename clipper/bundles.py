"""Связки: несколько уже отобранных моментов стрима, склеенных в один ролик.

Что это: серия провалов подряд, повтор одной шутки, «сказал в начале, а через час это стало важным».
ИИ только предлагает, какие моменты связаны (одним запросом на весь список). Склейку, субтитры и
монтаж делает код по тем же правилам, что и обычные клипы.
"""
from __future__ import annotations

import datetime as dt
import random
import shutil
from pathlib import Path

from . import learn, releases
from .config import WORK_DIR
from .judge import edit_clips, fallback_texts, target_texts
from .llm import LLM, LLMError, parse_json_loose
from .qa import validate_render
from .render import fit_title, render_clip, thumb_b64, words_to_output
from .store import Store
from .twitch import download_video
from .util import ffprobe_json, fmt_hms, log, now_iso, now_utc, parse_iso, run

MOMENTS = "moments.json"
MAX_MOMENTS = 150
KEEP_HOURS = 48
PAD = 0.3  # запас по краям каждого куска, чтобы не резать первое и последнее слово

PROMPT = """Ты монтажёр нарезок стримера. Ниже список уже отобранных коротких моментов стрима.
Найди ТОЛЬКО те, что вместе смешнее или понятнее, чем по отдельности. Подходящие связки:
• серия провалов или неудач подряд (пытался несколько раз и не получилось);
• повтор одной и той же шутки, фразы или реакции;
• продолжение истории: сказал раньше, позже это стало важным или смешным;
• установка и развязка, разнесённые по времени.
Не объединяй моменты только за похожесть темы. Лучше пустой список, чем слабая связка.
В группе от 2 до 3 моментов. Ответ строго JSON, без текста вокруг:
{"groups":[{"ids":["…","…"],"title":"до 40 символов по-русски, без эмодзи","why":"одна фраза","category":"funny|conflict|money|america|customer|road|emotional|chat|other"}]}
Моменты:
"""


def record_moment(store: Store, rec: dict) -> None:
    """Запоминаем клип для связок: где он в записи и какие в нём слова (в абсолютном времени VOD)."""
    items = store.read_json(MOMENTS, []) or []
    items.append(rec)
    cutoff = now_utc() - dt.timedelta(hours=KEEP_HOURS)
    items = [x for x in items if parse_iso(x["created_at"]) >= cutoff][-MAX_MOMENTS:]
    store.write_json(MOMENTS, items)


def propose(llm: LLM, moments: list[dict]) -> list[dict]:
    lines = []
    for m in moments:
        lines.append(f"- id={m['id']} время={fmt_hms(m['t'])} категория={m.get('category')} "
                     f"текст: «{m.get('text', '')[:220]}»")
    try:
        from . import schemas
        js = llm.chat_json([{"role": "user", "content": PROMPT + "\n".join(lines)}],
                           max_tokens=1200, schema=schemas.BUNDLES, thinking="medium")
    except LLMError as e:
        log(f"связки: ИИ недоступен ({str(e)[:120]})")
        return []
    return js.get("groups", []) if isinstance(js, dict) else []


def validate_groups(raw: list, moments: dict[str, dict], min_gap: float = 120.0) -> list[dict]:
    """Оставляем только честные группы: известные id, 2–3 момента, не одно и то же место записи."""
    out, used = [], set()
    for g in raw or []:
        if not isinstance(g, dict):
            continue
        ids = list(dict.fromkeys(str(i) for i in g.get("ids", []) if str(i) in moments))
        if not (2 <= len(ids) <= 3) or used & set(ids):
            continue
        ms = sorted((moments[i] for i in ids), key=lambda m: (m["vod_id"], m["t"]))
        too_close = any(a["vod_id"] == b["vod_id"] and b["t"] - a["t"] < min_gap for a, b in zip(ms, ms[1:]))
        if too_close:
            continue
        out.append({"ids": [m["id"] for m in ms], "title": str(g.get("title", ""))[:60],
                    "why": str(g.get("why", ""))[:200], "category": str(g.get("category", "other"))})
        used |= set(ids)
    return out


def _piece(m: dict, work: Path, k: int) -> dict:
    """Скачать и привести к единому виду (1920×1080, 30 fps) один момент."""
    a0 = min(a for a, _ in m["segments"]) - PAD
    a1 = max(b for _, b in m["segments"]) + PAD
    raw = download_video(m["vod_id"], a0, a1, work / f"p{k}_raw.mp4")
    norm = work / f"p{k}.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", raw,
         "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=30,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", norm], timeout=1200)
    dur = float(ffprobe_json(norm)["format"]["duration"])
    return {"path": norm, "a0": a0, "dur": dur}


def build(cfg: dict, store: Store, llm: LLM, group: dict, moments: dict[str, dict],
          platforms: list[str]) -> dict | None:
    ms = [moments[i] for i in group["ids"]]  # уже в хронологическом порядке
    gid = f"b{ms[0]['id']}"
    work = WORK_DIR / "bundles" / gid
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    off, segs_out, words_out, pieces = 0.0, [], [], []
    for k, m in enumerate(ms):
        p = _piece(m, work, k)
        pieces.append(p)
        for a, b in m["segments"]:
            segs_out.append((off + a - p["a0"], off + b - p["a0"]))
        for w, s, e in m["words"]:
            words_out.append({"w": w, "s": round(off + s - p["a0"], 2), "e": round(off + e - p["a0"], 2)})
        off += p["dur"]

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p['path'].resolve()}'\n" for p in pieces), encoding="utf-8")
    src = work / "bundle_src.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", src], timeout=900)

    total = sum(b - a for a, b in segs_out)
    item = {"id": gid, "dur": total, "words": words_to_output(words_out, segs_out),
            "category": group.get("category", "other"), "why": group.get("why", ""), "chat_sample": []}
    ed = edit_clips(llm, cfg, [item]).get(gid)
    if not ed:
        if not cfg["clips"].get("allow_fallback_texts", False):
            log(f"связка «{group.get('title')}»: редактор не ответил, не выпускаю")
            return None
        ed = fallback_texts({}, item["words"])

    policy = learn.load(store, cfg)
    rng = random.Random(gid)
    targets, thumb = {}, None
    for plat in platforms:
        variant = learn.choose_variant(policy, plat, cfg, rng)
        tx = target_texts(ed, plat, variant.get("hook_style"), cfg)
        title = fit_title(group.get("title") or "", *tx["hook_alts"])
        out = work / f"{gid}_{plat}.mp4"
        try:
            render_clip(src, segs_out, words_out, title, cfg, out, variant=variant)
        except Exception as ex:  # noqa: BLE001
            log(f"связка {gid} {plat}: рендер упал: {str(ex)[:160]}")
            continue
        problems = validate_render(out, total, plat)
        if problems:
            log(f"связка {gid} {plat}: {problems}")
            continue
        if thumb is None:
            thumb = thumb_b64(out, at=min(1.0, total / 2))
        targets[plat] = {**{k: v for k, v in tx.items() if k != "hook_alts"}, "hook_alts": tx["hook_alts"][:4],
                         "asset": releases.upload(out), "size": out.stat().st_size, "duration": round(total, 1),
                         "variant": variant, "hook_quality": {}, "status": "ready",
                         "comment": "", "cover_ms": 600}
    if not targets:
        return None
    rec = {"id": gid, "vod_id": ms[0]["vod_id"], "vod_title": ms[0].get("vod_title"),
           "vod_time": round(ms[0]["t"], 1), "duration": round(total, 1), "score": 0, "subscores": {},
           "category": group.get("category", "other"), "risk": {"level": 0, "flags": []},
           "why": group.get("why", ""), "overlay": next(iter(targets.values()))["hook"], "signal": 0,
           "breakdown": {}, "audio": {}, "opening": {}, "notes": [], "transcript": "",
           "thumb": thumb, "targets": targets, "posts": {}, "created_at": now_iso(), "live_when_made": False,
           "bundle": [m["id"] for m in ms], "uid": gid[-8:]}
    store.write_json(f"queue/{gid}.json", rec)
    store.sync(f"связка {gid}: {len(ms)} моментов")
    log(f"✅ связка {gid} «{group.get('title')}» {total:.0f}с → {', '.join(targets)}")
    shutil.rmtree(work, ignore_errors=True)
    return rec


def run_pass(cfg: dict, store: Store, llm: LLM, platforms: list[str]) -> int:
    bc = cfg.get("bundles") or {}
    if not bc.get("enabled", False):
        return 0
    cutoff = now_utc() - dt.timedelta(hours=float(bc.get("window_hours", 24)))
    fresh = [m for m in (store.read_json(MOMENTS, []) or [])
             if not m.get("bundled") and parse_iso(m["created_at"]) >= cutoff]
    fresh = fresh[-int(bc.get("max_candidates", 40)):]
    if len(fresh) < 2:
        return 0
    by_id = {m["id"]: m for m in fresh}
    groups = validate_groups(propose(llm, fresh), by_id)[: int(bc.get("max_per_run", 2))]
    made = 0
    for g in groups:
        try:
            if build(cfg, store, llm, g, by_id, platforms):
                made += 1
                for i in g["ids"]:
                    by_id[i]["bundled"] = True
        except Exception as e:  # noqa: BLE001 — одна связка не валит остальные
            log(f"связка «{g.get('title')}» не собрана: {str(e)[:200]}")
    if made:
        all_items = store.read_json(MOMENTS, []) or []
        for m in all_items:
            if m["id"] in by_id and by_id[m["id"]].get("bundled"):
                m["bundled"] = True
        store.write_json(MOMENTS, all_items)
    return made
