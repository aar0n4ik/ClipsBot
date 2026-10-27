"""Корректор речи: субтитры, заголовки и подписи совпадают с тем, что реально сказано.

Распознавание (облако или Whisper) путает похожие по звучанию слова, сленг, имена, бренды, числа,
а английскую речь при русском режиме превращает в кашу. Поэтому для каждого финалиста:

  1. ИИ СЛУШАЕТ звук фрагмента и сверяет с пронумерованными словами распознавания. Правит только ошибки
     распознавания (не стиль речи), опираясь на звук, смысл всей фразы, происходящее в ролике и чат.
  2. Английская речь: участки, где говорят по-английски, записываются по-английски, а снизу — перевод
     на русский в кавычках (рендер показывает его второй строкой).
  3. Память без слепых замен: каждое исправление «было → стало» копится в glossary.json и в следующий раз
     идёт корректору подсказкой («раньше распознавание путало X и Y»), а выученные слова — подсказкой
     Whisper. Решение всегда принимается по звуку конкретного ролика, поэтому слово, которое в другом
     контексте правильное, автозаменой не испортится.
Субтитры YouTube не используем: они появляются только после заливки, а это тот же класс автоматического
распознавания — на шумной уличной речи он не точнее.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import schemas
from .util import log, now_iso

GLOSSARY = "glossary.json"
_WORD = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)

PROMPT = """Ты — корректор субтитров IRL-стрима (русская речь, иногда английская). Перед тобой звук фрагмента
и пронумерованные слова, которые распознала машина. В них бывают ошибки: похожее по звучанию другое слово,
искажённый сленг, имена, бренды, числа и суммы, неверное окончание, меняющее смысл, английская речь,
записанная кириллицей или ерундой.
О стримере: {persona}
Что происходит в ролике: {what}
Чат в этот момент (зрители часто пишут слова правильно): {chat}
{hints}
Слова (номер:слово):
{words}

1. fixes — исправь ТОЛЬКО то, что распознано неверно. Слушай звук и понимай смысл всей фразы. Не улучшай
   стиль и разговорную речь: если стример так и сказал — оставь. Мат не исправляй и не цензурируй.
   Не уверен — не трогай. Одно исправление = один номер i, новый текст — 1–3 слова.
2. english — участки, где человек говорит по-английски: from/to — номера первого и последнего слова участка,
   en — что сказано по-английски (как реально звучит, с нормальной орфографией), ru — короткий естественный
   перевод на русский. Русскую речь сюда не включай. Нет английского — пустой список.
Ответ строго JSON: {{"fixes":[{{"i":12,"w":"…","why":"…"}}],"english":[{{"from":20,"to":24,"en":"…","ru":"…"}}]}}"""


def norm(w: str) -> str:
    return re.sub(r"[^\wё-]+", "", (w or "").lower().replace("ё", "е"))


def _keep_punct(orig: str, new: str) -> str:
    """Сохранить знаки препинания и заглавную букву исходного слова («лутка,» → «лудка,»)."""
    m = _WORD.match(orig or "")
    pre, core, post = (m.group(1), m.group(2), m.group(3)) if m else ("", orig, "")
    nm = _WORD.match(new)
    new_core = nm.group(2) if nm else new
    if core[:1].isupper() and new_core[:1].islower():
        new_core = new_core[:1].upper() + new_core[1:]
    return pre + new_core + post


# ── память исправлений (подсказки, не автозамена) ──────────────
def load(store) -> dict:
    g = store.read_json(GLOSSARY, {}) or {}
    g.setdefault("fixes", {})
    g.setdefault("terms", {})
    return g


def hints(store, k: int = 25) -> list[str]:
    """«лутка → лудка (3)» — самые частые прошлые исправления, для подсказки корректору."""
    fx = sorted((load(store).get("fixes") or {}).items(), key=lambda kv: -int(kv[1].get("n", 0)))[:k]
    return [f"{wrong} → {x.get('to')} ({x.get('n', 1)})" for wrong, x in fx if x.get("to")]


def terms(store, cfg: dict | None = None, k: int = 40) -> list[str]:
    """Слова, которые часто звучат на этом стриме (выучены из исправлений) — подсказка Whisper."""
    learned = sorted((load(store).get("terms") or {}).items(), key=lambda kv: -int(kv[1]))
    return [t for t, _ in learned][:k]


def learn(store, pairs: list[tuple[str, str]]):
    pairs = [(norm(a), b.strip()) for a, b in pairs if norm(a) and b.strip() and norm(a) != norm(b)]
    if not pairs:
        return

    def upd(g):
        g = g or {}
        fx, tm = g.setdefault("fixes", {}), g.setdefault("terms", {})
        for wrong, right in pairs:
            cur = fx.get(wrong) or {"to": right, "n": 0}
            if norm(cur.get("to")) != norm(right):   # спорное исправление: побеждает более частое
                cur = {"to": right, "n": 0} if cur.get("n", 0) <= 1 else cur
            if norm(cur.get("to")) == norm(right):
                cur["n"] = int(cur.get("n", 0)) + 1
            cur["at"] = now_iso()
            fx[wrong] = cur
            if len(right.split()) == 1:
                tm[right] = int(tm.get(right, 0)) + 1
        g["fixes"] = dict(sorted(fx.items(), key=lambda kv: -int(kv[1].get("n", 0)))[:500])
        g["terms"] = dict(sorted(tm.items(), key=lambda kv: -int(kv[1]))[:300])
        return g
    store.update_json(GLOSSARY, upd, {})


def fix_text(text: str, fixes: dict[str, str]) -> str:
    """Исправления ЭТОГО ролика (подтверждённые звуком) в тексте: хук, название, подпись."""
    if not text or not fixes:
        return text
    return re.sub(r"[\wёЁ-]+", lambda m: _keep_punct(m.group(0), fixes[norm(m.group(0))])
                  if norm(m.group(0)) in fixes else m.group(0), text)


def fix_texts(ed: dict, fixes: dict[str, str]) -> dict:
    if not fixes:
        return ed
    out = dict(ed)
    for k in ("what_happens", "moment", "comment"):
        if isinstance(out.get(k), str):
            out[k] = fix_text(out[k], fixes)
    out["hooks"] = [{**h, "text": fix_text(h.get("text", ""), fixes)} if isinstance(h, dict) else h
                    for h in (out.get("hooks") or [])]
    for plat in ("tiktok", "youtube", "instagram"):
        p = dict(out.get(plat) or {})
        for k in ("caption", "title", "description"):
            if isinstance(p.get(k), str):
                p[k] = fix_text(p[k], fixes)
        for k in ("hashtags", "tags"):
            if isinstance(p.get(k), list):
                p[k] = [fix_text(str(x), fixes) for x in p[k]]
        out[plat] = p
    return out


# ── английская речь ─────────────────────────────────────────────
def apply_english(words: list[dict], seg: dict) -> dict | None:
    """Заменить слова участка [from..to] английским текстом (время распределяется по длине слов).
    → {"s","e","ru"} для строки перевода, во времени words."""
    try:
        a, b = int(seg["from"]), int(seg["to"])
    except (KeyError, TypeError, ValueError):
        return None
    en, ru = str(seg.get("en", "")).strip(), str(seg.get("ru", "")).strip()
    if not (0 <= a <= b < len(words)) or not en:
        return None
    s, e = words[a]["s"], max(words[b]["e"], words[a]["s"] + 0.3)
    toks = en.split()
    total = sum(len(t) + 1 for t in toks)
    new, t0 = [], s
    for tok in toks:
        dur = (e - s) * (len(tok) + 1) / total
        new.append({"w": tok, "s": round(t0, 2), "e": round(t0 + dur, 2), "lang": "en"})
        t0 += dur
    words[a:b + 1] = new
    return {"s": round(s, 2), "e": round(e, 2), "ru": ru}


# ── корректор по звуку ──────────────────────────────────────────
def audio_of(video: Path, out: Path) -> Path:
    """Звук превью → лёгкий ogg/opus (десятки КБ на минуту)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "libopus", "-b:a", "24k", str(out)], capture_output=True, timeout=300)
    if r.returncode != 0 or not out.exists():
        out = out.with_suffix(".mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                        "-b:a", "32k", str(out)], check=True, capture_output=True, timeout=300)
    return out


def proofread(llm, cfg: dict, audio: Path, words: list[dict], *, what: str = "", chat: list[str] | None = None,
              past: list[str] | None = None) -> tuple[dict[int, str], list[dict]]:
    """→ ({номер слова: исправление}, [английские участки {"from","to","en","ru"}])."""
    if not words:
        return {}, []
    hint = ("Раньше на этом стриме распознавание путало (было → правильно, сколько раз). Это подсказка, а не правило: "
            "решай по звуку и смыслу: " + "; ".join(past) + "\n") if past else ""
    prompt = PROMPT.format(persona=cfg["streamer"]["persona"].strip(), what=(what or "—")[:300],
                           chat="; ".join((chat or [])[:12]) or "—", hints=hint,
                           words=" ".join(f"{i}:{w['w']}" for i, w in enumerate(words)))
    ai = cfg.get("ai") or {}
    mime = "audio/ogg" if audio.suffix == ".ogg" else "audio/mp3"
    js = llm.media_json([(mime, audio.read_bytes())], prompt, model=ai.get("text_model", "gemini-3.8-flash"),
                        fallback_models=["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"],
                        max_tokens=2500, low_res=False, schema=schemas.PROOF, thinking="medium")
    fixes = {}
    for f in js.get("fixes") or []:
        try:
            i, w = int(f.get("i")), str(f.get("w", "")).strip()
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(words) and w and len(w.split()) <= 3 and norm(w) != norm(words[i]["w"]):
            fixes[i] = w
    if len(fixes) > max(3, len(words) // 4):   # переписал четверть текста — это уже не исправления, не доверяем
        log(f"корректор: {len(fixes)} правок на {len(words)} слов — подозрительно много, правки не применяю")
        fixes = {}
    english = []
    for seg in js.get("english") or []:
        try:
            a, b = int(seg.get("from")), int(seg.get("to"))
        except (TypeError, ValueError):
            continue
        if 0 <= a <= b < len(words) and str(seg.get("en", "")).strip() and \
                not any(x["from"] <= b and a <= x["to"] for x in english):
            english.append({"from": a, "to": b, "en": str(seg["en"]).strip()[:300], "ru": str(seg.get("ru", "")).strip()[:300]})
    return fixes, sorted(english, key=lambda x: x["from"])
