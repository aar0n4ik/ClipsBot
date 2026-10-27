"""Корректор речи: субтитры, заголовки и подписи должны совпадать с тем, что реально сказано.

Проблема: распознавание путает похожие по звучанию слова и не знает сленг стрима («лутка» вместо «лудка»,
бренды, имена, англицизмы). Исправлять по одному слову руками бессмысленно — нужен механизм.

Три слоя:
  1. Словарь стримера (config.yaml → streamer.glossary/spelling + выученное). Подсказывает Whisper (hotwords)
     и корректору, как пишутся частые слова этого стрима.
  2. Корректор по звуку: для каждого финалиста ИИ СЛУШАЕТ фрагмент и сверяет с пронумерованными словами
     распознавания. Правит только ошибки распознавания (не стиль речи), с опорой на звук, контекст и чат —
     зрители часто пишут сленг правильно. Работает параллельно с остальными финалистами, ~секунды.
  3. Самообучение: каждое исправление «было → стало» копится в glossary.json. Повторилось ≥ 2 раз — дальше
     применяется сразу и бесплатно ко всем новым расшифровкам (ещё до оценки ИИ) и к текстам: хукам,
     названиям, подписям. Ошибка, пойманная однажды, больше не повторяется.
Почему не субтитры YouTube: они появляются только ПОСЛЕ заливки ролика (а нам нужен текст до монтажа),
и это тот же класс автоматического распознавания — сленг стрима он не знает так же.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import schemas
from .util import log, now_iso

GLOSSARY = "glossary.json"
LEARN_MIN = 2                 # столько раз встретилось одно и то же исправление — применяем автоматически
_WORD = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)

PROMPT = """Ты — корректор субтитров русскоязычного IRL-стрима. Перед тобой звук фрагмента и пронумерованные слова,
которые распознала машина. В них бывают ошибки: похожее по звучанию другое слово, искажённый сленг, имена, бренды,
англицизмы, числа и суммы, неверное окончание, меняющее смысл.
О стримере: {persona}
Как на этом стриме пишутся частые слова: {glossary}
Что происходит в ролике: {what}
Чат в этот момент (зрители часто пишут сленг и имена правильно): {chat}

Слова (номер:слово):
{words}

Слушай звук и исправь ТОЛЬКО то, что распознано неверно. Не улучшай стиль и разговорную речь — если стример так
и сказал, оставь. Мат не исправляй и не цензурируй. Не уверен — не трогай. Одно исправление = один номер i,
новый текст — 1–3 слова (если машина разбила или склеила слово — исправь на первом номере).
Ответ строго JSON: {{"fixes":[{{"i":12,"w":"лудка","why":"сленг: казино"}}]}}. Нет ошибок — пустой список."""


def norm(w: str) -> str:
    return re.sub(r"[^\wё-]+", "", (w or "").lower().replace("ё", "е"))


def _keep_punct(orig: str, new: str) -> str:
    """Сохранить знаки препинания и заглавную букву исходного слова (Whisper пишет «лутка,» — станет «лудка,»)."""
    m = _WORD.match(orig or "")
    pre, core, post = (m.group(1), m.group(2), m.group(3)) if m else ("", orig, "")
    nm = _WORD.match(new)
    new_core = nm.group(2) if nm else new
    if core[:1].isupper() and new_core[:1].islower():
        new_core = new_core[:1].upper() + new_core[1:]
    return pre + new_core + post


# ── словарь ─────────────────────────────────────────────────────
def load(store) -> dict:
    g = store.read_json(GLOSSARY, {}) or {}
    g.setdefault("fixes", {})
    g.setdefault("terms", {})
    return g


def known_fixes(store, cfg: dict) -> dict[str, str]:
    """неверно (нормализовано) → верно: из config (всегда) + выученные (≥ LEARN_MIN раз)."""
    out = {norm(k): v for k, v in ((cfg.get("streamer") or {}).get("spelling") or {}).items() if norm(k)}
    for wrong, x in (load(store).get("fixes") or {}).items():
        if int(x.get("n", 0)) >= LEARN_MIN and x.get("to") and wrong not in out:
            out[wrong] = x["to"]
    return out


def terms(store, cfg: dict, k: int = 40) -> list[str]:
    base = list((cfg.get("streamer") or {}).get("glossary") or [])
    learned = sorted((load(store).get("terms") or {}).items(), key=lambda kv: -int(kv[1]))
    return list(dict.fromkeys(base + [t for t, _ in learned]))[:k]


def learn(store, pairs: list[tuple[str, str]]):
    """Запомнить исправления «было → стало» (только однословные — их можно применять автоматически)."""
    pairs = [(norm(a), b.strip()) for a, b in pairs if norm(a) and b.strip() and len(b.split()) == 1 and norm(a) != norm(b)]
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
            tm[right] = int(tm.get(right, 0)) + 1
        g["fixes"] = dict(sorted(fx.items(), key=lambda kv: -int(kv[1].get("n", 0)))[:500])
        g["terms"] = dict(sorted(tm.items(), key=lambda kv: -int(kv[1]))[:300])
        return g
    store.update_json(GLOSSARY, upd, {})


def apply_known(words: list[dict], fixes: dict[str, str]) -> int:
    """Исправить в словах расшифровки всё, что уже известно. → сколько исправлено."""
    if not fixes:
        return 0
    n = 0
    for w in words:
        to = fixes.get(norm(w["w"]))
        if to and norm(to) != norm(w["w"]):
            w["w"] = _keep_punct(w["w"], to)
            n += 1
    return n


def fix_text(text: str, fixes: dict[str, str]) -> str:
    """Те же исправления в тексте (хук, название, подпись), с сохранением регистра и пунктуации."""
    if not text or not fixes:
        return text
    return re.sub(r"[\wёЁ-]+", lambda m: _keep_punct(m.group(0), fixes[norm(m.group(0))])
                  if norm(m.group(0)) in fixes else m.group(0), text)


def fix_texts(ed: dict, fixes: dict[str, str]) -> dict:
    """Все тексты ответа режиссёра: хуки, подписи, названия, теги, комментарий, описание момента."""
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
              glossary: list[str] | None = None) -> dict[int, str]:
    """→ {номер слова: исправленный текст}. Пусто — ошибок нет (или корректор недоступен)."""
    if not words:
        return {}
    prompt = PROMPT.format(persona=cfg["streamer"]["persona"].strip(), glossary=", ".join(glossary or []) or "—",
                           what=(what or "—")[:300], chat="; ".join((chat or [])[:12]) or "—",
                           words=" ".join(f"{i}:{w['w']}" for i, w in enumerate(words)))
    ai = cfg.get("ai") or {}
    mime = "audio/ogg" if audio.suffix == ".ogg" else "audio/mp3"
    js = llm.media_json([(mime, audio.read_bytes())], prompt, model=ai.get("text_model", "gemini-3.8-flash"),
                        fallback_models=["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"],
                        max_tokens=2000, low_res=False, schema=schemas.PROOF, thinking="low")
    fixes = {}
    for f in js.get("fixes") or []:
        try:
            i, w = int(f.get("i")), str(f.get("w", "")).strip()
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(words) and w and len(w.split()) <= 3 and norm(w) != norm(words[i]["w"]):
            fixes[i] = w
    if len(fixes) > max(3, len(words) // 4):   # переписал четверть текста — это уже не исправления, не доверяем
        log(f"корректор: {len(fixes)} правок на {len(words)} слов — подозрительно много, не применяю")
        return {}
    return fixes
