"""Проверки качества: до рендера (первые секунды) и после (битый файл, чёрный экран, тишина, размер)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .util import ffprobe_json

LIMITS = {"tiktok": 287 * 1024 * 1024, "youtube": 2 * 1024 ** 3, "instagram": 100 * 1024 * 1024}
MAX_DUR = {"tiktok": 600, "youtube": 180, "instagram": 180}


def plan_opening(words: list[dict], start: float, end: float, cfg: dict) -> tuple[float, dict]:
    """Первые секунды решают всё. Если речь начинается поздно — подрезаем начало под первое слово.
    words — во времени окна. Возвращает (новый start, отчёт)."""
    mn = float(cfg["clips"]["min_seconds"])
    inside = [w for w in words if start - 0.05 <= w["s"] < end]
    rep = {"speech_start": None, "trimmed": 0.0}
    if not inside:
        rep["issue"] = "в начале нет речи"
        return start, rep
    first = inside[0]["s"] - start
    rep["speech_start"] = round(first, 2)
    if first > 0.6 and end - (inside[0]["s"] - 0.15) >= mn:
        new = inside[0]["s"] - 0.15
        rep["trimmed"] = round(new - start, 2)
        rep["speech_start"] = 0.15
        return new, rep
    return start, rep


def hook_quality(rep: dict, cold_open: bool, title: str) -> dict:
    """Оценка первых 1.5 секунды (0–100) + причины. Используется в журнале и в обучении."""
    score, why = 100, []
    ss = rep.get("speech_start")
    if ss is None:
        score -= 35
        why.append("нет речи в начале")
    elif ss > 0.6:
        score -= 25
        why.append(f"речь начинается на {ss:.1f} с")
    if not title:
        score -= 30
        why.append("нет заголовка")
    elif len(title) > 34:
        score -= 10
        why.append("длинный заголовок")
    if cold_open:
        score += 5
    return {"score": max(0, min(100, score)), "issues": why}


def validate_render(path: Path, expect_dur: float, platform: str = "tiktok", expect_audio: bool = True) -> list[str]:
    """Пустой список = файл годен. Иначе — причины (файл в публикацию не пойдёт)."""
    problems = []
    if not path.exists() or path.stat().st_size < 50_000:
        return ["файл не создан или пустой"]
    try:
        info = ffprobe_json(path)
    except Exception as e:  # noqa: BLE001
        return [f"файл не читается: {str(e)[:120]}"]
    v = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    a = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not v:
        return ["нет видеодорожки"]
    if (int(v[0]["width"]), int(v[0]["height"])) != (1080, 1920):
        problems.append(f"размер {v[0]['width']}x{v[0]['height']}, а нужен 1080x1920")
    if v[0].get("codec_name") != "h264":
        problems.append(f"кодек {v[0].get('codec_name')}")
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    vdur = float(v[0].get("duration", 0) or 0)
    adur = float(a[0].get("duration", 0) or 0) if a else 0.0
    if a and vdur and adur and abs(vdur - adur) > 0.25:
        problems.append(f"звук и картинка расходятся на {abs(vdur - adur):.2f} с")
    if abs(dur - expect_dur) > 0.6:
        problems.append(f"длина {dur:.1f} с вместо {expect_dur:.1f} с")
    if dur > MAX_DUR.get(platform, 600):
        problems.append(f"длиннее лимита {platform} ({MAX_DUR[platform]} с)")
    if expect_audio and not a:
        problems.append("пропал звук")
    if path.stat().st_size > LIMITS.get(platform, 10 ** 12):
        problems.append("файл слишком большой")
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", "blackdetect=d=0.4:pix_th=0.08",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    black = sum(float(m) for m in re.findall(r"black_duration:([\d.]+)", r.stderr))
    if dur and black / dur > 0.3:
        problems.append(f"чёрный экран {black:.1f} с")
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    if expect_audio and m and float(m.group(1)) < -45:
        problems.append(f"почти тишина ({m.group(1)} dB)")
    return problems
