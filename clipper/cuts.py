"""Обрезка мёртвых пауз внутри клипа: тишина, долгое молчание, пауза без действия.

Слова Whisper дают точные границы речи. Паузы длиннее max_gap вырезаются, короткие остаются:
так ролик не рвётся посреди фразы и не превращается в рубленую нарезку.
"""
from __future__ import annotations


def drop_short_pauses(cuts: list[tuple[float, float]], words: list[dict], min_len: float) -> list[tuple[float, float]]:
    """Убрать из вырезов ИИ те, что просто съедают короткую паузу: слов внутри нет, а длина меньше min_len.
    Вырезы со словами внутри (повтор, уход в сторону) остаются как есть. cuts и words — в одной шкале времени."""
    keep = []
    for a, b in cuts:
        has_words = any(a - 0.05 <= w["s"] < b for w in words)
        if has_words or b - a >= min_len:
            keep.append((a, b))
    return keep


def speech_runs(words: list[dict], a: float, b: float, max_gap: float = 2.0,
                lead: float = 0.2, tail: float = 0.25) -> list[tuple[float, float]]:
    """Куски речи внутри окна [a, b] (секунды исходника). words — с полями s и e в тех же секундах."""
    inside = [w for w in words if a - 0.05 <= w["s"] < b]
    if not inside:
        return [(a, b)]
    runs = []
    cur_a = max(a, inside[0]["s"] - lead)
    prev_e = inside[0]["e"]
    for w in inside[1:]:
        if w["s"] - prev_e > max_gap:
            runs.append((cur_a, min(b, prev_e + tail)))
            cur_a = max(a, w["s"] - lead)
        prev_e = max(prev_e, w["e"])
    runs.append((cur_a, min(b, prev_e + tail)))
    runs = [(round(x, 2), round(y, 2)) for x, y in runs if y - x > 0.3]
    return runs or [(a, b)]
