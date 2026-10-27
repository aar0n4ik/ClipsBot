"""JSON-схемы ответов ИИ (structured output Gemini).

Модель физически не может вернуть битый JSON или пропустить обязательное поле: генерация идёт
по схеме. Если какая-то модель схему не принимает, движок (llm.py) сам откатится на старый
режим «просто JSON» + терпимый парсер, так что схемы — это гарантия, а не точка отказа.
Схемы держим компактными: слишком большие и вложенные Gemini отвергает («too many states»).
"""
from __future__ import annotations

SHELF = ["now", "weeks", "forever"]
CATS = ["funny", "conflict", "money", "america", "customer", "road", "emotional", "chat", "story", "other"]
HOOK_STYLES = ["tease", "conflict", "number", "quote"]

S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
STRS = {"type": "array", "items": S}


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": list(props) if required is None else required}


RISK = obj({"level": I, "flags": STRS})
SUBSCORES = obj({"hook": I, "payoff": I, "clarity": I, "emotion": I, "rewatch": I})
HOOK = obj({"style": {"type": "string", "enum": HOOK_STYLES}, "text": S})
PLATFORM_TEXTS = {
    "tiktok": obj({"caption": S, "hashtags": STRS}),
    "youtube": obj({"title": S, "description": S, "tags": STRS}),
    "instagram": obj({"caption": S, "hashtags": STRS}),
}

SCOUT = obj({"moments": {"type": "array", "items": obj({"at": S, "end": S, "guess": I, "what": S}, ["at", "guess", "what"])}})

PICKER = obj({"clips": {"type": "array", "items": obj({
    "id": S, "keep": B, "score": I, "hook": I, "payoff": I, "clarity": I, "emotion": I, "rewatch": I,
    "start": N, "end": N, "category": {"type": "string", "enum": CATS},
    "shelf": {"type": "string", "enum": SHELF}, "risk": RISK, "why": S})}})

DIRECTOR = obj({
    "verdict": {"type": "string", "enum": ["post", "reject"]}, "score": I, "subscores": SUBSCORES,
    "what_happens": S, "moment": S, "technical": obj({"lag": I, "issues": STRS}),
    "start": N, "end": N, "cuts": {"type": "array", "items": {"type": "array", "items": N}},
    "standalone": B, "category": {"type": "string", "enum": CATS}, "risk": RISK,
    "hooks": {"type": "array", "items": HOOK}, "pick": I, **PLATFORM_TEXTS, "comment": S, "reject_reason": S})

CRITIC = obj({"ok": B, "title_matches": B, "makes_sense": B, "fix_hook": S, "fix_title": S, "problems": STRS})

REVIEW = obj({"ok": B, "title_matches": B, "makes_sense": B, "problems": STRS})

EDITOR = obj({"clips": {"type": "array", "items": obj({
    "id": S, "hooks": {"type": "array", "items": HOOK}, "pick": I, **PLATFORM_TEXTS, "comment": S})}})

PRODUCER = obj({"action": {"type": "string", "enum": ["post", "wait"]}, "clip": {"type": ["string", "null"]}, "reason": S})

PRODUCER_CRITIC = obj({"agree": B, "action": {"type": "string", "enum": ["post", "wait"]},
                       "clip": {"type": ["string", "null"]}, "reason": S})

BUNDLES = obj({"groups": {"type": "array", "items": obj({"ids": STRS, "title": S, "why": S,
                                                          "category": {"type": "string", "enum": CATS}})}})

TRANSLATE = obj({"lines": STRS})

PROOF = obj({"fixes": {"type": "array", "items": obj({"i": I, "w": S, "why": S}, ["i", "w"])},
             "english": {"type": "array", "items": obj({"from": I, "to": I, "en": S, "ru": S})}}, ["fixes", "english"])

LENGTH = obj({"keep_long": B, "start": N, "end": N, "cuts": {"type": "array", "items": {"type": "array", "items": N}}, "why": S},
             ["keep_long", "start", "end", "why"])
