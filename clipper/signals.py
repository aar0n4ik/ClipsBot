"""Поиск «живых» моментов без ИИ — дёшево и по всему стриму.

Сигналы (посекундно):
  • всплеск чата относительно ЛОКАЛЬНОЙ нормы (норма меняется с онлайном)
  • смех/шок/«клипните» в чате
  • волны спама одинаковых сообщений
  • громкость звука (крики, смех стримера, сигналы)
  • клипы, которые зрители сами нарезали на Twitch (самый точный сигнал)
Чат реагирует с задержкой, поэтому чатовые сигналы сдвигаются назад.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from .util import log

PATTERNS = [
    ("laugh", 1.0, re.compile(r"(?:[ах]{2,}[хаx]{2,})|ору|ржу|ржак|угар|лол|кек|lol|lmao|kekw|\bkek\b|lul|omegalul|icant|😂|🤣|💀|\bxd\b", re.I)),
    ("shock", 0.9, re.compile(r"жест|капец|пипец|офиге|нифига|ниху|ебат|ебан|ахуе|охуе|бля|пздц|пизд|дичь|кринж|ужас|wtf|omg|monka|вау|\bого+\b|\?{3,}|!{3,}|чт[оo]{2,}", re.I)),
    ("clip", 1.6, re.compile(r"клип|clip|нарез|в тикток|tiktok|тикток|запишите|момент дня", re.I)),
    ("hype", 0.6, re.compile(r"\bpog|\bпог\b|poggers|\bgg\b|\bez\b|красав|легенд|gigachad|\bгига|\bбаза\b|\bимба", re.I)),
    ("sad", 0.5, re.compile(r"^f$|^ф$|\brip\b|помянем|sadge|biblethump", re.I)),
]


def audio_rms_db(path: Path, length: int) -> np.ndarray:
    """dB громкости по секундам. Читаем потоком — 10 часов звука не держим в памяти."""
    sr = 8000
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                            stdout=subprocess.PIPE)
    out = np.zeros(length, dtype=np.float32)
    i, block = 0, sr * 2 * 60  # минута за раз
    buf = b""
    while i < length:
        chunk = proc.stdout.read(block)
        if not chunk:
            break
        buf += chunk
        n_sec = len(buf) // (sr * 2)
        if n_sec == 0:
            continue
        arr = np.frombuffer(buf[: n_sec * sr * 2], dtype=np.int16).astype(np.float32).reshape(n_sec, sr)
        buf = buf[n_sec * sr * 2:]
        rms = np.sqrt((arr ** 2).mean(axis=1))
        take = min(n_sec, length - i)
        out[i:i + take] = 20 * np.log10(rms[:take] + 1.0)
        i += take
    proc.stdout.close()
    proc.wait()
    return out


def robust_z(x: np.ndarray, win: int) -> np.ndarray:
    win = max(5, min(win, len(x) // 2 * 2 + 1))
    med = median_filter(x, size=win, mode="nearest")
    mad = median_filter(np.abs(x - med), size=win, mode="nearest")
    scale = np.maximum(1.4826 * mad, 0.3 * np.abs(med) + 0.1 * (np.mean(np.abs(x)) + 1e-3))
    return np.clip((x - med) / scale, -3, 8)


def shift_back(x: np.ndarray, delay: int) -> np.ndarray:
    """value_at_moment[t] = reaction[t + delay]"""
    if delay <= 0:
        return x
    y = np.zeros_like(x)
    y[:-delay] = x[delay:]
    return y


def chat_features(msgs: list[dict], chunk_start: float, length: int):
    rate = np.zeros(length, np.float32)
    kw = np.zeros(length, np.float32)
    wave = np.zeros(length, np.float32)
    buckets: dict[int, Counter] = {}
    for m in msgs:
        i = int(m["t"] - chunk_start)
        if not 0 <= i < length:
            continue
        rate[i] += 1
        text = (m.get("text") or "").strip()
        full = text + " " + " ".join(m.get("emotes") or [])
        w = sum(weight for _, weight, rx in PATTERNS if rx.search(full))
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            w += 0.3
        kw[i] += w
        norm = re.sub(r"\s+", " ", text.lower())[:40]
        if norm:
            buckets.setdefault(i // 10, Counter())[norm] += 1
    for b, cnt in buckets.items():
        n = sum(v for v in cnt.values() if v >= 3)
        if n:
            wave[b * 10:(b + 1) * 10] += n / 10
    return rate, kw, wave


def clip_feature(viewer_clips: list[dict], chunk_start: float, length: int) -> np.ndarray:
    out = np.zeros(length, np.float32)
    t = np.arange(length)
    for c in viewer_clips:
        off = c.get("vod_offset")
        if off is None:
            continue
        center = off - chunk_start + float(c.get("duration", 30)) * 0.6
        if -60 < center < length + 60:
            amp = 2.0 + 0.5 * np.log1p(c.get("view_count", 0))
            out += amp * np.exp(-0.5 * ((t - center) / 8.0) ** 2)
    return out


def score_series(cfg: dict, msgs, viewer_clips, audio_db, chunk_start: float) -> dict[str, np.ndarray]:
    length = len(audio_db)
    p = cfg["processing"]
    w = p["weights"]
    delay = int(p.get("chat_delay_seconds", 9))
    rate, kw, wave = chat_features(msgs, chunk_start, length)
    s = {
        "chat": np.maximum(0, robust_z(uniform_filter1d(rate, 8), 600)),
        "keywords": np.maximum(0, robust_z(uniform_filter1d(kw, 8), 600)),
        "spam_wave": np.minimum(uniform_filter1d(wave, 5), 6),
        "audio": np.maximum(0, robust_z(uniform_filter1d(audio_db, 3), 300)),
        "viewer_clips": clip_feature(viewer_clips, chunk_start, length),
    }
    for k in ("chat", "keywords", "spam_wave"):
        s[k] = shift_back(s[k], delay)
    # чатовые сигналы весят меньше, если чат совсем пустой (мало данных → шум)
    if len(msgs) < length / 120:
        for k in ("chat", "keywords", "spam_wave"):
            s[k] *= 0.4
    total = sum(float(w.get(k, 0)) * v for k, v in s.items())
    s["total"] = uniform_filter1d(total, 6)
    s["rate"] = rate
    return s


def pick_peaks(score: np.ndarray, n: int, min_gap: int, exclude: list[float] | None = None) -> list[int]:
    exclude = exclude or []
    order = np.argsort(score)[::-1]
    picked: list[int] = []
    for i in order:
        if score[i] <= 0.3:
            break
        if all(abs(i - j) >= min_gap for j in picked) and all(abs(i - e) >= min_gap * 0.6 for e in exclude):
            picked.append(int(i))
            if len(picked) >= n:
                break
    return sorted(picked)


def find_candidates(cfg: dict, msgs, viewer_clips, audio_db, chunk_start: float,
                    already: list[float] | None = None, ignore_tail: int = 0) -> list[dict]:
    """already — абсолютные секунды VOD уже взятых моментов (перекрытие кусков)."""
    p = cfg["processing"]
    s = score_series(cfg, msgs, viewer_clips, audio_db, chunk_start)
    if ignore_tail:
        s["total"][max(0, len(audio_db) - ignore_tail):] = 0
    hours = len(audio_db) / 3600
    n = min(int(p["max_candidates_per_chunk"]), max(3, round(hours * p["candidates_per_hour"])))
    excl = [a - chunk_start for a in (already or [])]
    peaks = pick_peaks(s["total"], n, int(p["min_gap_seconds"]), excl)
    delay = int(p.get("chat_delay_seconds", 9))
    out = []
    for i in peaks:
        lo, hi = i - 15, i + 25 + delay
        near = [m for m in msgs if lo <= m["t"] - chunk_start <= hi]
        breakdown = {k: round(float(s[k][i]), 2) for k in ("chat", "keywords", "spam_wave", "audio", "viewer_clips")}
        vc = [c for c in viewer_clips if c.get("vod_offset") is not None and abs(c["vod_offset"] - chunk_start - i) < 60]
        out.append({
            "peak_rel": i,
            "peak_abs": chunk_start + i,
            "signal": round(float(s["total"][i]), 2),
            "breakdown": breakdown,
            "chat_count": len(near),
            "chat_sample": _chat_sample(near, chunk_start + i),
            "viewer_clips": [{"title": c.get("title"), "views": c.get("view_count", 0)} for c in vc][:3],
        })
    log(f"кандидатов: {len(out)} (из {hours:.1f} ч)")
    return out


def _chat_sample(near: list[dict], peak_abs: float, k: int = 22) -> list[str]:
    """Самые «реакционные» сообщения + немного обычных — ИИ по ним понимает, что произошло."""
    def weight(m):
        full = (m.get("text") or "") + " " + " ".join(m.get("emotes") or [])
        return sum(wt for _, wt, rx in PATTERNS if rx.search(full)) + min(len(m.get("text", "")), 80) / 200
    top = sorted(near, key=weight, reverse=True)[:k]
    top.sort(key=lambda m: m["t"])
    return [f"[{m['t'] - peak_abs:+.0f}с] {m['user']}: {m['text'][:120]}" for m in top]
