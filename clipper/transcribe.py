"""Речь → слова с таймкодами (faster-whisper на CPU раннера GitHub). Транскрибируем только кандидатов."""
from __future__ import annotations

from pathlib import Path

from .util import log, run


def cut_wav(src: Path, start: float, dur: float, out: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, start):.2f}", "-t", f"{dur:.2f}", "-i", str(src),
         "-ac", "1", "-ar", "16000", str(out)], quiet=True)
    return out


class Transcriber:
    def __init__(self, model: str = "large-v3-turbo", compute_type: str = "int8", language: str = "ru"):
        self.model_name, self.compute_type, self.language = model, compute_type, language
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            import os
            log(f"загружаю whisper {self.model_name}")
            self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type,
                                       cpu_threads=os.cpu_count() or 4)
        return self._model

    def words(self, wav: Path) -> list[dict]:
        segs, _ = self._load().transcribe(
            str(wav), language=self.language, word_timestamps=True, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400}, beam_size=5, condition_on_previous_text=False)
        out = []
        for seg in segs:
            for w in seg.words or []:
                txt = w.word.strip()
                if txt:
                    out.append({"w": txt, "s": round(w.start, 2), "e": round(w.end, 2)})
        return out


def words_to_timed_text(words: list[dict], every: float = 3.0) -> str:
    """'[0.0] привет как дела [3.2] ...' — компактно для промпта."""
    if not words:
        return "(речи нет)"
    parts, last = [], -999.0
    for w in words:
        if w["s"] - last >= every:
            parts.append(f"\n[{w['s']:.1f}]")
            last = w["s"]
        parts.append(w["w"])
    return " ".join(parts).strip()
