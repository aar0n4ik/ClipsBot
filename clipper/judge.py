"""ИИ в два прохода, как в живой команде клиперов.

1) ОТБОРЩИК: честные подоценки удержания, точные границы по словам, тема, РИСК (то, за что площадки режут показы).
2) РЕДАКТОР: 4 хука в разных стилях (бот потом выбирает стиль по статистике), авторский слой
   (контекстные подписи на видео, точки зума, «холодное открытие»), свои тексты под каждую площадку
   (TikTok — поисковые слова; Shorts — заголовок до 100 символов; Reels — подпись с хештегами),
   первый комментарий.
Потом «очеловечивание»: убираем признаки нейросети в текстах.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from . import schemas
from .llm import LLM, LLMError
from .render import PROFANITY, mask_profanity
from .transcribe import words_to_timed_text
from .util import log

HOOK_STYLES = ("tease", "conflict", "number", "quote")

EDITOR = """Ты — редактор каналов с нарезками русскоязычного IRL-стримера.
О стримере: {persona}

Для каждого клипа (транскрипт выбранного куска со временем в секундах от начала клипа, чат, суть) напиши тексты.
{style}
1. hooks — РОВНО 4 заголовка поверх видео в стилях tease (недосказанность), conflict (конфликт или ставки),
   number (конкретика или цифра ИЗ РОЛИКА), quote (дословная фраза из ролика). pick — индекс лучшего.
2. tiktok — {{"caption": до 110 символов, разговорно, в начале поисковые слова по теме, "hashtags": 3–5 нишевых}}.
3. youtube — {{"title": до 70 символов, с ключевым словом, "description": 1–2 предложения, "tags": 5–8 фраз}}.
4. instagram — {{"caption": 1–2 строки, вопрос к зрителю в конце, "hashtags": 4–6}}.
5. comment — первый комментарий автора, вопрос к зрителям по теме, до 80 символов.
Без длинных тире, без кавычек-ёлочек, максимум 1 эмодзи на текст. Ответ строго JSON:
{{"clips":[{{"id":"…","hooks":[{{"style":"tease","text":"…"}},{{"style":"conflict","text":"…"}},{{"style":"number","text":"…"}},{{"style":"quote","text":"…"}}],"pick":0,"tiktok":{{"caption":"…","hashtags":["#…"]}},"youtube":{{"title":"…","description":"…","tags":["…"]}},"instagram":{{"caption":"…","hashtags":["#…"]}},"comment":"…"}}]}}"""


# ── очеловечивание ───────────────────────────────────────────────
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_BANNED = re.compile(r"\b(вы не поверите|невероятн\w*|шок\w*|эпичн\w*|смотрите до конца|до конца|это нужно видеть|"
                     r"не пропустите|в этом видео|давайте разберёмся|погрузимся)\b", re.I)
_BAD_TAGS = {"#fyp", "#foryou", "#foryoupage", "#рекомендации", "#viral", "#тренды", "#рек", "#хочуврек", "#xyzbca"}


_TOK = re.compile(r"[а-яёa-z0-9]+", re.I)


def grounded(text: str, transcript: str) -> float:
    """Доля значимых слов текста, которые реально прозвучали в речи. 1.0 — всё подтверждено.

    Сравниваем по первым 5 буквам, чтобы не спотыкаться об окончания («курьер» / «курьера»)."""
    stems = {w.lower()[:5] for w in _TOK.findall(transcript or "") if len(w) >= 3}
    toks = [w.lower()[:5] for w in _TOK.findall(text or "") if len(w) >= 4]
    if not toks:
        return 1.0
    return sum(1 for t in toks if t in stems) / len(toks)


def humanize(text: str, keep_emoji: int = 1, kind: str = "caption") -> str:
    t = (text or "").strip()
    t = t.replace("«", "").replace("»", "").replace("„", "").replace("“", "\"").replace("”", "\"")
    t = re.sub(r"(?<!\d)\s*—\s*|\s+[—–]\s+", ", " if kind == "caption" else " ", t)  # «0–100» не трогаем
    t = _BANNED.sub("", t)
    emojis = _EMOJI.findall(t)
    if len(emojis) > keep_emoji:
        t = _EMOJI.sub("", t)
        if keep_emoji and emojis:
            t = t.rstrip() + " " + emojis[0]
    t = re.sub(r"!{2,}", "!", t)
    t = re.sub(r"\?{3,}", "??", t)
    t = " ".join(w for w in t.split() if not PROFANITY.search(w))  # мат — не пишем вообще (ни маской, ни целиком)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.")
    if kind == "hook":
        t = t.rstrip(".").replace("\"", "")
        if t.isupper() and len(t) > 6:
            t = t.capitalize()
    return t


def humanize_tags(tags: list[str], n: int = 5) -> list[str]:
    out = []
    for t in tags or []:
        t = re.sub(r"[^\w#]", "", str(t).strip().replace(" ", ""))
        if not t:
            continue
        t = (t if t.startswith("#") else f"#{t}").lower()
        if t not in _BAD_TAGS:
            out.append(t)
    return list(dict.fromkeys(out))[:n]


# ── промпты ──────────────────────────────────────────────────────
def learned_block(examples: dict | None) -> str:
    if not examples or (not examples.get("top") and not examples.get("bottom")):
        return ""
    lines = ["\nЧто на ЭТИХ каналах перевыполнило и недовыполнило норму (учитывай темы и подачу):"]
    for e in examples.get("top", []):
        lines.append(f"  выше нормы {e['vs_norm']}: «{e['overlay']}» ({e.get('category', '')}, {e.get('platform', '')})")
    for e in examples.get("bottom", []):
        lines.append(f"  ниже нормы {e['vs_norm']}: «{e['overlay']}» ({e.get('category', '')}, {e.get('platform', '')})")
    return "\n".join(lines) + "\n"


def _img(path: Path) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode(),
                                               "detail": "low"}}


def candidate_block(c: dict) -> list[dict]:
    b = c["breakdown"]
    vc = "; ".join(f"«{x['title']}» ({x['views']} просм.)" for x in c.get("viewer_clips", [])) or "нет"
    au = c.get("audio") or {}
    extra = ""
    if au.get("music", {}).get("score", 0) >= 0.5:
        extra = "Звук: похоже, в фоне музыка.\n"
    text = (f"### Кандидат id={c['id']}\nОкно {c['ctx_dur']:.0f} с, пик реакции ≈ {c['peak_in_ctx']:.0f} с.\n"
            f"Сигналы: чат {b['chat']}, смех/шок {b['keywords']}, спам-волна {b['spam_wave']}, громкость {b['audio']}, "
            f"клипы зрителей {b['viewer_clips']}. Сообщений рядом: {c['chat_count']}. Клипы зрителей: {vc}\n{extra}"
            + (f"Заметка разведчика (слушал весь стрим): {c['scout'].get('what')} (его оценка {c['scout'].get('guess')})\n" if c.get('scout') else "")
            + f"Транскрипт:\n{words_to_timed_text(c['words'])}\n"
            f"Чат (время от пика):\n" + ("\n".join(c["chat_sample"]) or "(пусто)") + "\n")
    parts = [{"type": "text", "text": text}]
    if c.get("frames"):
        parts.append({"type": "text", "text": "Кадры: " + ", ".join(f"{t:.0f} с" for t, _ in c["frames"])})
        parts += [_img(p) for _, p in c["frames"]]
    return parts


def _judge_messages(system: str, batch: list[dict], frames: bool) -> list[dict]:
    content = [p for c in batch for p in candidate_block(c if frames else {**c, "frames": []})]
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _judge_batch(llm: LLM, system: str, batch: list[dict]) -> dict:
    has_frames = any(c.get("frames") for c in batch)
    try:
        return llm.chat_json(_judge_messages(system, batch, True), max_tokens=1500, schema=schemas.PICKER, thinking="medium")
    except LLMError as e:
        if not has_frames:
            raise
        log(f"повтор без кадров: {str(e)[:120]}")
        return llm.chat_json(_judge_messages(system, batch, False), max_tokens=1500, schema=schemas.PICKER, thinking="medium")


def judge_candidates(llm: LLM, cfg: dict, cands: list[dict], learned: dict | None = None,
                     hints: str = "") -> dict[str, dict]:
    from .brain import CATS, PICKER, RISK, SCALE, length_rule
    st, cl = cfg["streamer"], cfg["clips"]
    system = PICKER.format(persona=st["persona"].strip(), audience=st.get("audience", "").strip(),
                           length=length_rule(cfg), scale=SCALE, cats=CATS, risk=RISK,
                           hints=(hints + "\n") if hints else "",
                           learned=learned_block(learned) if cfg["judge"].get("learn_from_stats") else "")
    bs = max(1, int(cfg["judge"].get("batch_size", 4)))
    results: dict[str, dict] = {}
    batches = list(range(0, len(cands), bs))

    def one(i):
        batch = cands[i:i + bs]
        try:
            return batch, llm.chat_json(_judge_messages(system, batch, False), max_tokens=700 * len(batch) + 600,
                                        schema=schemas.PICKER, thinking="medium")
        except LLMError as e:
            # одна пачка не ответила — пропускаем только её, остальные кандидаты не теряем
            log(f"пачка {i + 1}–{i + len(batch)} пропущена: {str(e)[:160]}")
            return batch, None
    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, min(int(cfg["judge"].get("parallel", 4)), len(batches)))
    with ThreadPoolExecutor(max_workers=workers) as ex:   # пачки независимы — оцениваются одновременно
        done = list(ex.map(one, batches))
    failed = sum(1 for _, js in done if js is None)
    for batch, js in done:
        ids = {c["id"] for c in batch}
        for r in (js or {}).get("clips", []):
            if str(r.get("id")) in ids:
                results[str(r["id"])] = r
    log(f"отборщик: оценено {len(results)}/{len(cands)} ({len(batches)} пачек параллельно)")
    if batches and failed == len(batches):
        raise LLMError("ИИ-отборщик не ответил ни на одну пачку кандидатов")
    return results


def edit_clips(llm: LLM, cfg: dict, items: list[dict]) -> dict[str, dict]:
    if not items:
        return {}
    from .brain import STYLE_RULES
    system = EDITOR.format(persona=cfg["streamer"]["persona"].strip(), style=STYLE_RULES)
    out: dict[str, dict] = {}
    for i in range(0, len(items), 3):
        batch = items[i:i + 3]
        text = "\n\n".join(
            f"### Клип id={it['id']} ({it['dur']:.0f} с, тема: {it.get('category')}, суть: {it.get('why', '')})\n"
            f"Транскрипт:\n{words_to_timed_text(it['words'], every=2.5)}\nЧат:\n" + "\n".join(it.get("chat_sample", [])[:12])
            for it in batch)
        try:
            js = llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": text}],
                               max_tokens=3500, schema=schemas.EDITOR, thinking="low")
        except LLMError as e:
            log(f"редактор недоступен: {e}")
            continue
        for r in js.get("clips", []):
            out[str(r.get("id"))] = r
    return out


def fallback_texts(pick: dict, words: list[dict]) -> dict:
    """Если ИИ-редактор недоступен — простые тексты из транскрипта (клип не теряем)."""
    first = " ".join(w["w"] for w in words[:6]).strip(" ,.")
    hook = humanize(first[:28], 0, "hook") or "Смотри, что было"
    return {"hooks": [{"style": "quote", "text": hook}], "pick": 0, "tiktok": {"caption": hook.lower(), "hashtags": []},
            "youtube": {"title": hook, "description": "", "tags": []}, "instagram": {"caption": hook, "hashtags": []},
            "comment": "", "notes": [], "punch_at": [], "cold_open": {"use": False}}


def target_texts(ed: dict, platform: str, style: str | None, cfg: dict) -> dict:
    """Тексты конкретной площадки + хук нужного стиля (стиль выбирает обучение)."""
    hooks = [h if isinstance(h, dict) else {"style": "tease", "text": str(h)} for h in (ed.get("hooks") or [])]
    hooks = [{"style": h.get("style", "tease"), "text": humanize(h.get("text", ""), 0, "hook")} for h in hooks if h.get("text")]
    pick = int(ed.get("pick", 0) or 0)
    chosen = next((h for h in hooks if h["style"] == style), None) or (hooks[pick] if 0 <= pick < len(hooks) else None) \
        or (hooks[0] if hooks else {"style": "tease", "text": ""})
    alts = [chosen["text"]] + [h["text"] for h in hooks if h is not chosen]
    fixed = cfg["posting"].get("fixed_hashtags") or []
    p = ed.get(platform) or {}
    if platform == "youtube":
        title = humanize(p.get("title") or chosen["text"], 1, "caption")[:90]
        tags = [humanize(t, 0, "hook") for t in (p.get("tags") or [])][:8]
        desc = humanize(p.get("description", ""), 1, "caption")
        streamer = cfg["streamer"].get("twitch_login", "")
        desc = (desc + (f"\n\nСтримы: twitch.tv/{streamer}" if streamer else "") + "\n#shorts " + " ".join(fixed)).strip()
        return {"hook": chosen["text"], "hook_style": chosen["style"], "hook_alts": alts, "title": title,
                "description": desc, "tags": tags, "caption": title}
    cap = humanize(p.get("caption", ""), 1, "caption")[:150]
    tags = humanize_tags(p.get("hashtags") or [], 6 if platform == "instagram" else 5)
    return {"hook": chosen["text"], "hook_style": chosen["style"], "hook_alts": alts, "caption": cap, "hashtags": tags}


def snap_bounds(words: list[dict], start: float, end: float, ctx_dur: float, cfg: dict) -> tuple[float, float]:
    cl = cfg["clips"]
    mn, mx = float(cl["min_seconds"]), float(cl["max_seconds"])
    start, end = max(0.0, float(start)), min(ctx_dur, float(end))
    if end <= start:
        end = min(ctx_dur, start + mn)
    if words:
        cand = [w["s"] for w in words if w["s"] >= start - 0.6]
        if cand:
            start = max(0.0, min(cand, key=lambda s: abs(s - start)) - 0.25)
        inside = [w for w in words if w["s"] < end + 0.3]
        if inside:
            end = min(ctx_dur, max(end, inside[-1]["e"] + 0.45))
    if end - start > mx:
        end = start + mx
        ends = [w["e"] for w in words if start < w["e"] <= end]
        if ends:
            end = ends[-1] + 0.35
    if end - start < mn:
        pad = (mn - (end - start)) / 2
        start, end = max(0.0, start - pad), min(ctx_dur, end + pad)
    return round(start, 2), round(end, 2)


REVIEW = """Ты — последний контроль перед публикацией короткого ролика со стрима. Смотри на текст ролика (слова со временем),
название и хуки. Ролик должен:
• совпадать с названием и хуком: то, что написано в заголовке, реально происходит и говорится в ролике;
• быть понятным без контекста стрима: не начинаться с середины мысли без смысла и не заканчиваться на полуслове;
• нести смысл: не бубнёж, не пустой разговор, не пересказ ничего, не бессвязный набор слов;
• не выглядеть как ошибка распознавания: если ключевая фраза явно искажена, отметь это.
Ответ строго JSON: {"ok": true или false, "title_matches": true/false, "makes_sense": true/false, "problems": ["коротко, по-русски"]}.
Будь строгим: сомневаешься — ok=false и объясни в problems."""


def review_clip(llm: LLM, cfg: dict, pl: dict, ed: dict) -> tuple[bool, str]:
    """Проверка слов и смысла до рендера. Если ИИ недоступен — не блокируем выпуск (логируем)."""
    words = pl.get("words") or []
    if not words:
        return False, "в клипе нет речи, без неё без контекста непонятно"
    dur = float(pl.get("dur", 0) or 0)
    prev = -1.0
    for w in words:
        if w["s"] < -0.05 or w["e"] > dur + 0.6 or w["s"] < prev - 0.05:
            return False, "субтитры не совпадают по времени со звуком"
        prev = w["s"]
    hooks = [h.get("text", "") if isinstance(h, dict) else str(h) for h in (ed.get("hooks") or [])][:4]
    yt = (ed.get("youtube") or {}).get("title", "")
    text = (f"Заголовки: {' | '.join(h for h in hooks if h)}\nНазвание YouTube: {yt}\n"
            f"Длина: {dur:.0f} с\nСлова со временем:\n{words_to_timed_text(words, every=2.5)}")
    try:
        js = llm.chat_json([{"role": "system", "content": REVIEW}, {"role": "user", "content": text}],
                           max_tokens=600, schema=schemas.REVIEW, thinking="low")
    except LLMError as e:
        log(f"проверка клипа пропущена: ИИ недоступен ({str(e)[:100]})")
        return True, ""
    title_ok = bool(js.get("title_matches", True))
    sense_ok = bool(js.get("makes_sense", True))
    ok = bool(js.get("ok")) and title_ok and sense_ok
    probs = "; ".join(str(x) for x in (js.get("problems") or []))[:200]
    if ok:
        return True, ""
    if not probs:
        probs = "не совпадает с названием" if not title_ok else "бессмысленно без контекста"
    return False, probs


def translate_lines(llm: LLM, lines: list[str]) -> list[str]:
    if not lines:
        return []
    js = llm.chat_json([
        {"role": "system", "content": "Translate each Russian subtitle line to short natural spoken English, "
                                      "casual tone, no profanity stronger than original. "
                                      'Return JSON {"lines":[...]} with the SAME number of lines in the same order.'},
        {"role": "user", "content": "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))},
    ], max_tokens=1500, schema=schemas.TRANSLATE, thinking="low")
    out = [str(x) for x in js.get("lines", [])]
    return out if len(out) == len(lines) else [""] * len(lines)
