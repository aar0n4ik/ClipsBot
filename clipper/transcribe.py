"""Речь → слова с таймкодами. Транскрибируем только окна кандидатов.

v5: два движка.
  • gemini — облачная модель gemini-3.5-transcribe (Google, 2026) с таймкодами слов. Все окна куска
    расшифровываются параллельно за секунды, а не по очереди на 4 ядрах раннера; Whisper даже
    не загружается, если облако справилось.
  • whisper — faster-whisper large-v3-turbo на CPU (как в v4) + словарь подсказок (имена, сленг стрима)
    и пакетный режим, если версия библиотеки его поддерживает. Запасной путь для каждого окна,
    где облако не ответило или вернуло сомнительные таймкоды.
engine: auto (облако → Whisper), gemini, whisper.
"""
from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .util import log, run

LANG_CODES = {"ru": "ru-RU", "uk": "uk-UA", "en": "en-US", "kk": "kk-KZ", "be": "be-BY"}


def cut_wav(src: Path, start: float, dur: float, out: Path) -> Path:
    # src — уже чистый m4a (twitch.download_audio): быстрый поиск до -i здесь точен до сэмпла (проверено тестом)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, start):.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-ac", "1", "-ar", "16000", str(out)], quiet=True)
    return out


def plausible(words: list[dict], dur: float) -> bool:
    """Таймкоды облака выглядят правдоподобно: в пределах окна, по порядку, не нулевой длины."""
    if not words:
        return False
    bad = sum(1 for i, w in enumerate(words)
              if not (-0.2 <= w["s"] <= dur + 0.5) or w["e"] < w["s"] or (i and w["s"] < words[i - 1]["s"] - 0.3))
    return bad <= len(words) // 10


class Transcriber:
    def __init__(self, model: str = "large-v3-turbo", compute_type: str = "int8", language: str = "ru", *,
                 engine: str = "auto", llm=None, hotwords: str = ""):
        self.model_name, self.compute_type, self.language = model, compute_type, language
        self.engine = engine if engine in ("auto", "gemini", "whisper") else "auto"
        self.llm = llm
        self.hotwords = (hotwords or "").strip()
        self._model = None
        self._batched = None
        self._lock = threading.Lock()
        self.used: dict[str, int] = {}

    # ── whisper ─────────────────────────────────────────────────
    def _load(self):
        with self._lock:
            if self._model is None:
                import os

                from faster_whisper import WhisperModel
                log(f"загружаю whisper {self.model_name}")
                self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type,
                                           cpu_threads=os.cpu_count() or 4)
                try:
                    from faster_whisper import BatchedInferencePipeline
                    self._batched = BatchedInferencePipeline(model=self._model)
                except Exception:  # noqa: BLE001 — старая версия: обычный режим
                    self._batched = None
        return self._model

    def _whisper(self, wav: Path) -> list[dict]:
        model = self._load()
        kw = dict(language=self.language, word_timestamps=True, vad_filter=True, beam_size=5,
                  condition_on_previous_text=False, vad_parameters={"min_silence_duration_ms": 400})
        if self.hotwords:
            kw["hotwords"] = self.hotwords
        engine = self._batched or model
        if self._batched is not None:
            kw["batch_size"] = 8
        allowed = set(inspect.signature(engine.transcribe).parameters)
        kw = {k: v for k, v in kw.items() if k in allowed}
        with self._lock:  # один CPU-движок — не грузим ядра двумя расшифровками сразу
            segs, _ = engine.transcribe(str(wav), **kw)
            out = []
            for seg in segs:
                for w in seg.words or []:
                    txt = w.word.strip()
                    if txt:
                        out.append({"w": txt, "s": round(w.start, 2), "e": round(w.end, 2)})
        self._count("whisper")
        return out

    # ── облако ──────────────────────────────────────────────────
    def _gemini(self, wav: Path, dur: float) -> list[dict] | None:
        if self.llm is None or self.engine == "whisper":
            return None
        if self.used.get("cloud_fail", 0) >= 3 and not self.used.get("gemini"):
            return None   # облако не ответило ни разу из трёх — в этом запуске не тратим время
        try:
            words = self.llm.transcribe(wav.read_bytes(), "audio/wav", language=LANG_CODES.get(self.language, self.language))
        except Exception as e:  # noqa: BLE001 — облако не обязательно
            log(f"облачная расшифровка {wav.name}: {str(e)[:140]} — Whisper")
            self._count("cloud_fail")
            return None
        if not plausible(words, dur):
            log(f"облачная расшифровка {wav.name}: таймкоды сомнительные — Whisper")
            return None
        self._count("gemini")
        return words

    def _count(self, k: str):
        with self._lock:
            self.used[k] = self.used.get(k, 0) + 1

    # ── публичное ───────────────────────────────────────────────
    def words(self, wav: Path, dur: float | None = None) -> list[dict]:
        if dur is None:
            from .util import ffprobe_json
            try:
                dur = float(ffprobe_json(wav)["format"]["duration"])
            except Exception:  # noqa: BLE001
                dur = 1e9
        got = self._gemini(wav, dur)
        return got if got is not None else self._whisper(wav)

    def words_many(self, items: list[tuple[Path, float]], workers: int = 6) -> list[list[dict]]:
        """Все окна сразу: облако параллельно, провалившиеся — Whisper по очереди."""
        res: list[list[dict] | None] = [None] * len(items)
        if self.llm is not None and self.engine != "whisper" and items:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as ex:
                res = list(ex.map(lambda it: self._gemini(*it), items))
        if self.engine == "gemini" and any(r is None for r in res):
            log("облачная расшифровка недоступна для части окон — Whisper их доделает")
        return [r if r is not None else self._whisper(wav) for r, (wav, _) in zip(res, items)]


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
