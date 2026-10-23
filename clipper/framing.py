"""Кадрирование без дёрганий.

Видео в шаблоне всегда одного крупного размера. Горизонтальный стрим обрезается по бокам,
поэтому важно, ГДЕ резать: в IRL-стриме из машины стример обычно сидит сбоку.

  1. Раз в 0,5 с определяем, где в кадре человек: модель лиц YuNet (если скачана) либо,
     без неё, по оттенку кожи и резкости — этого хватает, чтобы не обрезать стримера.
  2. Камера стоит на месте. Сдвигается, только если человек устойчиво (≥1,5 с) ушёл далеко
     от центра кадра, и делает это плавно за ~1,2 с, не чаще 3 раз за клип.
  3. Ничего не нашли — ровный центр.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .config import ROOT
from .util import log

MODEL = ROOT / "assets" / "face_detection_yunet.onnx"
SW, SH = 320, 180


def _frames(src: Path, start: float, end: float, step: float) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, start):.2f}", "-t", f"{max(0.5, end - start):.2f}", "-i", str(src),
           "-vf", f"fps={1 / step},scale={SW}:{SH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (SW * SH * 3)
    return np.frombuffer(raw, np.uint8)[: n * SW * SH * 3].reshape(n, SH, SW, 3) if n else np.zeros((0, SH, SW, 3), np.uint8)


def _yunet(frames: np.ndarray, start: float, step: float) -> list[tuple[float, float, float]]:
    if not MODEL.exists():
        return []
    try:
        import cv2
        det = cv2.FaceDetectorYN.create(str(MODEL), "", (SW, SH), 0.7, 0.3, 50)
    except Exception as e:  # noqa: BLE001 — нет модели или сборки без неё
        log(f"кадр: YuNet недоступен ({str(e)[:80]}), беру запасной способ")
        return []
    out = []
    for i, f in enumerate(frames):
        _, faces = det.detect(f[:, :, ::-1].copy())  # BGR
        if faces is not None and len(faces):
            x, y, w, h = max(faces, key=lambda b: b[2] * b[3])[:4]
            out.append((start + i * step, float((x + w / 2) / SW), float(w / SW)))
    return out


def _skin(frames: np.ndarray, start: float, step: float) -> list[tuple[float, float, float]]:
    """Запасной способ: столбцы с оттенком кожи и высокой резкостью — там человек, а не небо и дорога."""
    out = []
    for i, f in enumerate(frames):
        x = f.astype(np.float32)
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        y = .299 * r + .587 * g + .114 * b
        cb, cr = 128 - .169 * r - .331 * g + .5 * b, 128 + .5 * r - .419 * g - .081 * b
        skin = ((cb > 77) & (cb < 128) & (cr > 134) & (cr < 176) & (y > 45) & (y < 240)
                & (r > g + 8) & (r > b + 12))
        cols = skin.sum(0).astype(np.float32)
        if cols.sum() < SH * 0.25:
            continue
        k = SW // 12
        sm = np.convolve(cols, np.ones(2 * k + 1) / (2 * k + 1), "same")
        peak = int(sm.argmax())
        strong = sm > 0.45 * sm[peak]
        lo = peak
        while lo > 0 and strong[lo - 1]:
            lo -= 1
        hi = peak
        while hi < SW - 1 and strong[hi + 1]:
            hi += 1
        out.append((start + i * step, (lo + hi) / 2 / SW, (hi - lo) / SW))
    return out


def detect_subject(src: Path, start: float, end: float, step: float = 0.5) -> list[tuple[float, float, float]]:
    frames = _frames(src, start, end, step)
    if not len(frames):
        return []
    if MODEL.exists():
        return _yunet(frames, start, step)  # лица не нашли — пусть камера стоит, а не цепляется за предметы
    return _skin(frames, start, step)


HOLD_S = 3.0     # стример должен устойчиво быть далеко от центра столько секунд, иначе камеру не трогаем
MOVE_AT = 0.32   # насколько далеко от текущей позиции (доля ширины кадра) считаем сдвигом
MAX_MOVES = 2    # больше двух переездов за клип — уже не «умный оператор», а дёрганье


def plan_pan(dets: list[tuple[float, float, float]], start: float, end: float, crop_frac: float,
             move_at: float = MOVE_AT, max_moves: int = MAX_MOVES, ease: float = 1.6,
             hold: float = HOLD_S, smooth: int = 9) -> list[tuple[float, float]]:
    """Ключевые точки положения кадра [(время исходника, центр 0..1)].

    Камера стоит на месте. Переезд только если человек устойчиво (hold секунд подряд) ушёл далеко,
    короткий взгляд в сторону (птица, телефон, чат) её не трогает. Сглаживание окном smooth.
    """
    lo, hi = crop_frac / 2, 1 - crop_frac / 2
    clamp = lambda v: float(min(hi, max(lo, v)))
    need = max(3, 0.25 * (end - start) / step_of(dets, start))
    if len(dets) < need:
        return [(start, clamp(float(np.median([d[1] for d in dets])) if len(dets) >= 2 else 0.5))]
    t = np.array([d[0] for d in dets])
    x = np.array([d[1] for d in dets])
    xs = np.array([np.median(x[max(0, i - smooth // 2): i + smooth // 2 + 1]) for i in range(len(x))])
    pos = clamp(float(np.median(xs[t < start + 2.5])) if (t < start + 2.5).any() else float(xs[0]))
    keys, moves, i = [(start, pos)], 0, 0
    while i < len(t) and moves < max_moves:
        if abs(xs[i] - pos) / crop_frac > move_at:
            j = i
            while j < len(t) and abs(xs[j] - pos) / crop_frac > move_at and t[j] - t[i] < hold:
                j += 1
            held = (t[min(j, len(t) - 1)] - t[i]) >= hold
            if held:
                target = clamp(float(np.median(xs[i:max(j, i + 1)])))
                t0 = float(t[i])
                if t0 + ease < end and abs(target - pos) > 0.01:
                    keys += [(t0, pos), (t0 + ease, target)]
                    pos, moves = target, moves + 1
                i = j
                continue
        i += 1
    if moves:
        log(f"кадр: {moves} плавных переезда(ов) за стримером")
    return keys


def step_of(dets, start):
    return (dets[1][0] - dets[0][0]) if len(dets) > 1 else 0.5


def x_expr(keys: list[tuple[float, float]], seg_start: float, crop_frac: float) -> str:
    """Выражение для левого края кропа ffmpeg (t внутри сегмента идёт с нуля)."""
    px = lambda c: f"(iw*{c:.4f}-ow/2)"
    if len(keys) == 1:
        return f"max(0\\,min(iw-ow\\,{px(keys[0][1])}))"
    T = f"({seg_start:.3f}+t)"
    expr = px(keys[-1][1])
    for (ta, a), (tb, b) in reversed(list(zip(keys[1::2], keys[2::2]))):
        s = f"(({T}-{ta:.3f})/{tb - ta:.3f})"
        ease = f"({s}*{s}*(3-2*{s}))"   # плавный старт и плавная остановка
        mid = f"(iw*({a:.4f}+({b - a:.4f})*{ease})-ow/2)"
        expr = f"if(lt({T}\\,{ta:.3f})\\,{px(a)}\\,if(lt({T}\\,{tb:.3f})\\,{mid}\\,{expr}))"
    return f"max(0\\,min(iw-ow\\,{expr}))"
