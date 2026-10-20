"""Звук клипа: заглушённые Twitch куски, чужая музыка, отделение голоса.

Зачем:
  • Twitch глушит в записях куски с музыкой (полная цифровая тишина) — такой клип бессмысленен.
  • Музыка из машины/фона = Content ID на YouTube, заглушка звука в Reels, иногда в TikTok.
    Детектор дешёвый (спектр + ритм); если он насторожился — Demucs отделяет голос от музыки,
    и если музыка действительно есть, в ролик идёт только голос.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from .util import log, run

SR = 16000


def load_wav(src: Path, start: float | None = None, dur: float | None = None, sr: int = SR) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0, start):.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(src), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def muted_fraction(x: np.ndarray, sr: int = SR) -> float:
    """Доля времени в «цифровой тишине» кусками от 1.5 с (так выглядит заглушка Twitch)."""
    if len(x) < sr:
        return 0.0
    hop = sr // 20
    n = len(x) // hop
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1))
    silent = rms < 10 ** (-75 / 20)
    run_len, total = 0, 0
    for s in silent:
        if s:
            run_len += 1
        else:
            if run_len >= 30:
                total += run_len
            run_len = 0
    if run_len >= 30:
        total += run_len
    return total / max(1, n)


def music_score(x: np.ndarray, sr: int = SR) -> dict:
    """0..1: насколько похоже, что в звуке есть музыка.
    Музыка: устойчивые тональные гармоники (спектр меняется медленно) + регулярный ритм.
    Речь: спектр скачет каждые ~100 мс, паузы, ритма нет."""
    if len(x) < sr * 3:
        return {"score": 0.0, "stability": 0.0, "beat": 0.0}
    nfft, hop = 1024, 512
    n = 1 + (len(x) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(nfft)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    band = (freqs > 150) & (freqs < 4000)
    S = np.log1p(mag[:, band] * 50)
    energy = S.mean(1)
    active = energy > np.percentile(energy, 30)
    # 1) устойчивость спектра: корреляция соседних кадров через ~0.3 с
    lag = max(1, int(0.3 * sr / hop))
    A, B = S[:-lag], S[lag:]
    A = A - A.mean(1, keepdims=True)
    B = B - B.mean(1, keepdims=True)
    corr = (A * B).sum(1) / (np.sqrt((A * A).sum(1) * (B * B).sum(1)) + 1e-9)
    act = active[:-lag] & active[lag:]
    stability = float(np.median(corr[act])) if act.any() else 0.0
    # 2) тональность: доля энергии в узких устойчивых пиках
    peak = (S - np.maximum.reduce([np.roll(S, k, 1) for k in (-3, -2, -1, 1, 2, 3)])) > 0.35
    persist = (peak[:-lag] & peak[lag:]).sum(1) / (peak[:-lag].sum(1) + 1)
    tonal = float(np.median(persist[act])) if act.any() else 0.0
    # 3) ритм: автокорреляция огибающей атак на темпах 70–180 BPM
    full = np.log1p(mag[:, (freqs > 40) & (freqs < 8000)] * 50)
    flux = np.maximum(0, np.diff(full, axis=0)).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    beat = float(ac[lo:hi].max()) if hi < len(ac) else 0.0
    score = 1 / (1 + np.exp(-(8.0 * (stability - 0.35) + 4.0 * (tonal - 0.10) + 3.0 * (beat - 0.25))))
    return {"score": round(float(score), 3), "stability": round(stability, 3), "tonal": round(tonal, 3),
            "beat": round(beat, 3)}


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def separate_vocals(src: Path, out_dir: Path) -> tuple[Path, float] | None:
    """Demucs (htdemucs, CPU). → (путь к голосу 44.1 кГц, доля энергии музыки 0..1)."""
    if not demucs_available():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "mix.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "2", "-ar", "44100", str(wav)], quiet=True)
    try:
        run(["python", "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-d", "cpu", "-j", "2",
             "-o", str(out_dir), str(wav)], timeout=900)
    except RuntimeError as e:
        log(f"demucs не отработал: {str(e)[:200]}")
        return None
    stem_dir = out_dir / "htdemucs" / "mix"
    voc, acc = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    if not voc.exists() or not acc.exists():
        return None
    v, a = load_wav(voc), load_wav(acc)
    m = min(len(v), len(a))
    ev, ea = float((v[:m] ** 2).sum()), float((a[:m] ** 2).sum())
    # фон может быть просто шумом улицы/мотора — музыкой считаем, только если и сам фон «музыкальный»
    musical = music_score(a[:m])["score"]
    return voc, (ea / (ev + ea + 1e-9)) * (1.0 if musical >= 0.5 else 0.0)


def inspect_clip_audio(src: Path, start: float, dur: float, work: Path, cfg: dict) -> dict:
    """Итог для клипа: {"muted": доля, "music": {...}, "action": "ok|skip|vocals", "audio_override": path|None}"""
    acfg = cfg.get("audio") or {}
    x = load_wav(src, start, dur)
    res = {"muted": round(muted_fraction(x), 3), "music": music_score(x), "action": "ok", "audio_override": None}
    if res["muted"] > float(acfg.get("max_muted", 0.15)):
        res["action"] = "skip"
        res["reason"] = f"Twitch заглушил звук ({int(res['muted'] * 100)}% клипа в тишине)"
        return res
    if res["music"]["score"] >= float(acfg.get("music_suspect", 0.5)):
        sep = separate_vocals(src, work / f"sep_{int(start * 10)}") if acfg.get("separate_music", False) else None
        if sep:
            voc, share = sep
            res["music"]["share"] = round(share, 3)
            if share >= float(acfg.get("music_share_remove", 0.18)):
                res["action"] = "vocals"
                res["audio_override"] = voc
                res["reason"] = f"в фоне музыка ({int(share * 100)}% энергии), оставлен только голос"
        else:
            res["action"] = "flag"
            res["reason"] = "в фоне слышна музыка — звук оставлен как есть, клип помечен"
    return res


def have_demucs_cli() -> bool:
    return shutil.which("python") is not None and demucs_available()
