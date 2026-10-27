"""ИИ-движок v5: нативный Gemini API для всего (текст, звук, видео, расшифровка речи).

Что изменилось против v4 и почему:
  • Нативный generateContent вместо OpenAI-совместимой прослойки — доступны structured output
    (JSON по схеме: битый ответ невозможен), уровни размышления (thinkingLevel), разрешение медиа.
  • Для Gemini 3+/4 НЕ передаём temperature/topP/topK: Google прямо требует убрать их при переходе на
    Gemini 3 (значения ниже 1.0 вызывают зацикливание и деградацию ответа). v4 слал 0.1–0.3 везде.
  • Лимиты считаются по паре ключ×модель (у Google квоты на модель): исчерпанная суточная квота
    gemini-4-argon больше не выключает ключ для flash. Пауза берётся из RetryInfo ответа Google.
  • Модель недоступна / переименована → следующая по цепочке, в конце — алиас «*-latest».
    Список реально доступных моделей запрашивается один раз, лишних 404 нет.
  • Неподдержанное моделью поле (схема, thinking, mediaResolution) отключается для этой модели
    автоматически и запрос повторяется — бот не ломается от изменений API.
  • Потокобезопасность: конвейер дёргает ИИ параллельно (режиссёр, отборщик, расшифровка).
  • Большие файлы (> 90 МБ) идут через Files API, остальное — inline (лимит inline теперь 100 МБ).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import threading
import time

import requests

from .util import log


class LLMError(RuntimeError):
    """kind: rate, daily, model, feature, blocked, bad_json, too_large, server, network, auth, temp"""

    def __init__(self, msg: str, kind: str = "temp"):
        super().__init__(msg)
        self.kind = kind


GEMINI = "https://generativelanguage.googleapis.com"
INLINE_MAX = 90 * 1024 * 1024            # inline до 100 МБ на запрос — держим запас
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
DEFAULT_TEXT_CHAIN = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"]

# $ за 1M токенов (вход, выход) — только для оценки трат в журнале
MODEL_PRICES = {"gemini-4-argon": (2.0, 10.0), "gemini-3.8-flash": (0.75, 3.75), "gemini-3.6-flash": (0.5, 3.0),
                "gemini-3.5-flash-lite": (0.3, 2.5), "gemini-3.5-transcribe": (0.5, 2.0),
                "gemini-flash-latest": (0.75, 3.75)}
THINK_EXTRA = {"low": 2048, "medium": 6144, "high": 12288}


def is_modern(model: str) -> bool:
    """Gemini 3+/4 и алиасы *-latest: без temperature, с thinkingLevel."""
    m = re.match(r"gemini-(\d+)", model or "")
    return bool(m and int(m.group(1)) >= 3) or (model or "").endswith("-latest")


def _retry_after(msg: str, default: float) -> float:
    """«retryDelay": "37s"» (Google RetryInfo) или «try again in 1m30.5s» (OpenAI-совместимые)."""
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', msg)
    if m:
        return float(m[1])
    m = re.search(r"try again in\s+(\d+)m([\d.]+)s", msg)
    if m:
        return float(m[1]) * 60 + float(m[2])
    m = re.search(r"try again in\s+([\d.]+)ms", msg)
    if m:
        return float(m[1]) / 1000
    m = re.search(r"(?:try again|retry) in\s+([\d.]+)\s*s", msg)
    if m:
        return float(m[1])
    return default


def _estimate_tokens(contents_chars: int, media_bytes: int, max_tokens: int) -> int:
    """Грубо и с запасом: текст ~2 символа на токен, медиа ~40 байт на токен."""
    return contents_chars // 2 + media_bytes // 40 + max_tokens


def _to_openapi(schema):
    """JSON Schema → OpenAPI-подмножество для старого поля responseSchema (если responseJsonSchema не принят)."""
    if isinstance(schema, list):
        return [_to_openapi(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, list):
            types = [t for t in v if t != "null"]
            out["type"] = (types[0] if types else "string").upper()
            if "null" in v:
                out["nullable"] = True
        elif k == "type":
            out["type"] = str(v).upper()
        elif k in ("properties",):
            out[k] = {pk: _to_openapi(pv) for pk, pv in v.items()}
        elif k in ("items",):
            out[k] = _to_openapi(v)
        elif k in ("required", "enum", "description", "format", "minimum", "maximum"):
            out[k] = v
    return out


def _classify(status: int, text: str) -> tuple[str, float]:
    """(вид ошибки, пауза ключу в секундах) по ответу Gemini."""
    low = text.lower()
    if status == 429 or "resource_exhausted" in low:
        if re.search(r"perday|per_day|per day|daily", low):
            return "daily", 0.0
        return "rate", max(5.0, min(_retry_after(text, 30.0), 120.0))
    if status in (401,) or "api_key_invalid" in low or "api key not valid" in low:
        return "auth", 0.0
    if status == 403:
        return "denied", 0.0
    if status == 404 or "not_found" in low or "is not found" in low or "not supported for generatecontent" in low:
        return "model", 0.0
    if status == 413 or "request payload size" in low or "too large" in low:
        return "too_large", 0.0
    if status == 400:
        return "feature", 0.0
    if status in (500, 502, 503, 504) or "overloaded" in low or "unavailable" in low or "high demand" in low:
        return "server", 25.0 + random.uniform(0, 20)
    return "temp", 20.0


FEATURE_HINTS = (  # 400 с упоминанием поля → это поле модель не принимает
    ("jsonschema", ("responsejsonschema", "response_json_schema")),
    ("schema", ("responseschema", "response_schema", "too many states", "schema")),
    ("thinking", ("thinking",)),
    ("mediares", ("mediaresolution", "media_resolution", "video_metadata", "videometadata")),
    ("temperature", ("temperature", "top_p", "topp", "top_k", "topk")),
    ("transcribe_cfg", ("audiotranscriptionconfig", "audio_transcription_config", "wordtimestamp")),
    ("inline", ("inline_data", "inlinedata", "inline data")),
)


class LLM:
    def __init__(self, providers: list[dict], *, text_chain: list[str] | None = None):
        active = [p for p in providers if os.environ.get(p.get("key_env", ""), "")]
        skipped = [p["name"] for p in providers if p not in active]
        self.providers = active
        if not self.providers:
            raise SystemExit("Нет ни одного ключа для ИИ (GEMINI_API_KEY_* в Secrets)")
        first_model = next((p.get("model") for p in active if p.get("model")), None)
        chain = list(text_chain or ([first_model] if first_model else [])) + DEFAULT_TEXT_CHAIN
        self.text_chain = list(dict.fromkeys(m for m in chain if m))
        self._lock = threading.RLock()
        self._local = threading.local()
        self.dead: set[tuple[str, str]] = set()          # (ключ, модель): суточная квота — до конца запуска
        self.dead_keys: set[str] = set()                 # ключ отозван/невалиден
        self.cool: dict[tuple[str, str], float] = {}     # (ключ, модель) → до какого времени пауза
        self.unsupported: set[tuple[str, str]] = set()   # (модель, функция) — не слать
        self.missing_models: set[str] = set()
        self._rr = 0
        self.usage: dict[str, list[int]] = {}            # "ключ:модель" → [запросы, вход, выход]
        self._sent: dict[tuple[str, str], list[tuple[float, int]]] = {}
        self._models: set[str] | None = None
        self._files: dict[tuple[str, str], str] = {}     # (ключ, sha1) → uri в Files API
        msg = "ИИ-ключи: " + ", ".join(p["name"] for p in self.providers)
        if skipped:
            msg += f" (без ключа пропущены: {', '.join(skipped)})"
        log(msg)

    # ── служебное ───────────────────────────────────────────────
    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = self._local.s = requests.Session()
        return s

    def gemini_keys(self) -> list[dict]:
        return [p for p in self.providers if "generativelanguage.googleapis.com" in p.get("base_url", GEMINI)
                and p["name"] not in self.dead_keys]

    def _key(self, p: dict) -> str:
        return os.environ[p["key_env"]]

    def available_models(self) -> set[str] | None:
        """Какие модели реально доступны ключу (один запрос за запуск). None — не удалось узнать."""
        with self._lock:
            if self._models is not None:
                return self._models or None
        keys = self.gemini_keys()
        names: set[str] = set()
        try:
            token = None
            for _ in range(5):
                params = {"pageSize": 1000, **({"pageToken": token} if token else {})}
                r = self._session().get(f"{GEMINI}/v1beta/models", params=params, timeout=30,
                                        headers={"x-goog-api-key": self._key(keys[0])})
                if r.status_code != 200:
                    break
                js = r.json()
                names |= {m.get("name", "").split("/", 1)[-1] for m in js.get("models", [])}
                token = js.get("nextPageToken")
                if not token:
                    break
        except (requests.RequestException, ValueError, IndexError, KeyError):
            names = set()
        with self._lock:
            self._models = names
        if names:
            log(f"ИИ: доступно моделей {len(names)}")
        return names or None

    def resolve_chain(self, model: str | None, fallback: list[str] | None) -> list[str]:
        chain = list(dict.fromkeys([m for m in [model, *(fallback or []), *self.text_chain] if m]))
        chain = [m for m in chain if m not in self.missing_models]
        avail = self.available_models()
        if avail:
            known = [m for m in chain if m in avail]
            chain = known or chain
        return chain

    def _pick(self, model: str, skip: set[str]) -> dict | None:
        """Ключ для модели по кругу. Все на паузе — ждём ближайший (не дольше 150 с). Нет живых — None."""
        while True:
            with self._lock:
                keys = [p for p in self.gemini_keys() if (p["name"], model) not in self.dead and p["name"] not in skip]
                if not keys:
                    return None
                now = time.time()
                ready = [p for p in keys if self.cool.get((p["name"], model), 0) <= now]
                if ready:
                    p = ready[self._rr % len(ready)]
                    self._rr += 1
                    return p
                wait = min(max(1.0, min(self.cool[(p["name"], model)] for p in keys) - now), 150.0)
            log(f"⏳ все ключи для {model} на паузе, жду {wait:.0f} с")
            time.sleep(wait)

    def _budget(self, p: dict, model: str, est: int):
        tpm = p.get("tpm")
        if not tpm:
            return
        if est > tpm * 4:  # даже с запасом не влезет — пусть Google решает сам, но не ждём впустую
            return
        while True:
            with self._lock:
                now = time.time()
                key = (p["name"], model)
                window = [(t, n) for t, n in self._sent.get(key, []) if now - t < 60]
                if sum(n for _, n in window) + est <= tpm or not window:
                    window.append((now, est))
                    self._sent[key] = window
                    return
                wait = max(1.0, 60 - (now - min(t for t, _ in window)))
            time.sleep(min(wait, 60))

    def _account(self, p: dict, model: str, usage: dict):
        with self._lock:
            cur = self.usage.setdefault(f"{p['name']}:{model}", [0, 0, 0])
            cur[0] += 1
            cur[1] += int(usage.get("promptTokenCount", 0) or 0)
            cur[2] += int(usage.get("candidatesTokenCount", 0) or 0) + int(usage.get("thoughtsTokenCount", 0) or 0)

    # ── сборка запроса ──────────────────────────────────────────
    def _gen(self, model: str, *, max_tokens: int, temperature, schema, thinking, low_res, json_out=True) -> dict:
        un = lambda f: (model, f) in self.unsupported or (self._strip_all() and f != "temperature")
        gen: dict = {}
        if json_out:
            gen["responseMimeType"] = "application/json"
            if schema and not un("jsonschema"):
                gen["responseJsonSchema"] = schema
            elif schema and not un("schema"):
                gen["responseSchema"] = _to_openapi(schema)
        mt = max_tokens
        if thinking and is_modern(model) and not un("thinking"):
            gen["thinkingConfig"] = {"thinkingLevel": thinking}
            mt += THINK_EXTRA.get(thinking, 4096)
        gen["maxOutputTokens"] = min(65536, int(mt))
        if temperature is not None and not is_modern(model) and not un("temperature"):
            gen["temperature"] = temperature
        if low_res and not un("mediares"):
            gen["mediaResolution"] = "MEDIA_RESOLUTION_LOW"
        return gen

    def _media_parts(self, p: dict, media: list[tuple[str, bytes]], fps: float | None, model: str) -> list[dict]:
        parts = []
        for mime, data in media:
            if len(data) > INLINE_MAX or (model, "inline") in self.unsupported:
                part = {"fileData": {"mimeType": mime, "fileUri": self._upload_file(p, mime, data)}}
            else:
                part = {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}
            if fps and mime.startswith("video/") and (model, "mediares") not in self.unsupported:
                part["videoMetadata"] = {"fps": fps}
            parts.append(part)
        return parts

    # ── главный цикл: ключи × модели × откаты функций ──────────
    def _run(self, *, chain: list[str], build, parse, est: int, what: str):
        """build(p, model) → тело запроса, parse(p, model, ответ) → результат.
        Два круга: если по всей цепочке были только временные паузы (лимит в минуту, перегрузка) —
        второй круг ждёт, пока ключи оттают, а не сдаётся."""
        last: Exception | None = None
        for round_ in range(2):
            if round_ and not isinstance(last, _Paused):
                break
            try:
                return self._run_once(chain=chain, build=build, parse=parse, est=est, what=what)
            except _ChainExhausted as e:
                last = e.last
        raise LLMError(f"{what}: все модели и ключи недоступны: {last}", getattr(last, "kind", "temp"))

    def _strip_all(self) -> bool:
        return bool(getattr(self._local, "strip_all", False))

    def _run_once(self, *, chain: list[str], build, parse, est: int, what: str):
        last: Exception | None = None
        for model in chain:
            self._local.strip_all = False
            skip: set[str] = set()
            bad = 0
            strips = 0
            for _ in range(max(3, len(self.gemini_keys()) * 3)):
                p = self._pick(model, skip)
                if p is None:
                    break
                self._budget(p, model, est)
                try:
                    body = build(p, model)
                    url = f"{GEMINI}/v1beta/models/{model}:generateContent"
                    try:
                        r = self._session().post(url, json=body, timeout=300,
                                                 headers={"x-goog-api-key": self._key(p), "Content-Type": "application/json"})
                    except requests.RequestException as e:
                        raise LLMError(f"network {str(e)[:160]}", "network") from e
                    if r.status_code != 200:
                        kind, pause = _classify(r.status_code, r.text)
                        if kind in ("rate", "server", "temp"):
                            raise _Paused(f"{r.status_code} {r.text[:300]}", kind, pause)
                        raise LLMError(f"{r.status_code} {r.text[:500]}", kind)
                    try:
                        js = r.json()
                    except ValueError as e:
                        raise LLMError(f"ответ не JSON: {r.text[:160]}", "bad_json") from e
                    self._account(p, model, js.get("usageMetadata") or {})
                    return parse(p, model, js)
                except _Paused as e:
                    last = e
                    with self._lock:
                        self.cool[(p["name"], model)] = time.time() + e.pause
                    skip.add(p["name"])
                    log(f"↪ {what}: {p['name']}:{model} {e.kind}, пауза {e.pause:.0f} с — другой ключ")
                except LLMError as e:
                    last = e
                    msg = str(e).lower()
                    if e.kind == "daily":
                        with self._lock:
                            self.dead.add((p["name"], model))
                        log(f"⚠️ {p['name']}: суточная квота {model} исчерпана — этот ключ для {model} до конца запуска выключен")
                    elif e.kind == "auth":
                        with self._lock:
                            self.dead_keys.add(p["name"])
                        log(f"⚠️ {p['name']}: ключ отклонён Google — выключен до конца запуска")
                    elif e.kind == "denied":  # у этого ключа нет доступа к модели (биллинг/права) — другие ключи могут
                        with self._lock:
                            self.dead.add((p["name"], model))
                        skip.add(p["name"])
                        log(f"⚠️ {p['name']}: нет доступа к {model} — пробую другие ключи")
                    elif e.kind == "model":
                        with self._lock:
                            self.missing_models.add(model)
                        log(f"⚠️ {model}: модель недоступна ({str(e)[:100]}) — беру следующую")
                        break
                    elif e.kind == "feature":
                        feat = next((f for f, keys in FEATURE_HINTS if any(k in msg for k in keys)), None)
                        if feat is None and not self._strip_all():
                            # непонятный 400: один повтор «голым» запросом, но ничего не запоминаем навсегда
                            self._local.strip_all = True
                            log(f"ИИ: {model} отклонил запрос без пояснения — повторяю без доп. полей")
                            continue
                        if feat is None or strips >= 4:
                            log(f"⚠️ {what}: {model} отклонил запрос: {str(e)[:200]}")
                            break
                        strips += 1
                        with self._lock:
                            self.unsupported.add((model, feat))   # только то поле, которое Google назвал
                        log(f"ИИ: {model} не принимает «{feat}» — отключаю и повторяю")
                    elif e.kind == "blocked":
                        raise
                    elif e.kind == "too_large":
                        skip.add(p["name"])
                    elif e.kind == "network":
                        with self._lock:
                            self.cool[(p["name"], model)] = time.time() + 15
                        skip.add(p["name"])
                    else:  # bad_json и прочее: один повтор тем же ключом, дальше — другой ключ
                        bad += 1
                        if bad >= 2:
                            skip.add(p["name"])
                        log(f"↪ {what}: {p['name']}:{model} {e.kind}: {str(e)[:140]}")
        raise _ChainExhausted(last)

    @staticmethod
    def _text(js: dict) -> tuple[str, str]:
        fb = js.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise LLMError(f"запрос заблокирован: {fb.get('blockReason')}", "blocked")
        cand = (js.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
        reason = cand.get("finishReason", "")
        if not text and reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"):
            raise LLMError(f"ответ заблокирован: {reason}", "blocked")
        if not text:
            raise LLMError(f"пустой ответ ({reason})", "bad_json")
        return text, reason

    def _parse_json(self, js: dict) -> dict:
        text, reason = self._text(js)
        try:
            out = parse_json_loose(text)
        except (ValueError, LLMError) as e:
            raise LLMError(f"bad json ({reason}): {str(e)[:160]} | {text[:160]}", "bad_json") from e
        if not isinstance(out, dict):
            raise LLMError("ответ не объект", "bad_json")
        return out

    # ── публичное API ───────────────────────────────────────────
    def chat_json(self, messages: list[dict], max_tokens: int = 2500, temperature: float | None = None, *,
                  schema: dict | None = None, model: str | None = None, fallback_models: list[str] | None = None,
                  thinking: str | None = "low") -> dict:
        """Текстовый запрос → JSON. messages в формате OpenAI (system/user, text и image_url data:)."""
        system, parts = _openai_to_gemini(messages)
        chars = sum(len(x.get("text", "")) for x in parts) + len(system or "")
        media = sum(len(x.get("inlineData", {}).get("data", "")) * 3 // 4 for x in parts)

        def build(p, m):
            body = {"contents": [{"role": "user", "parts": parts}],
                    "generationConfig": self._gen(m, max_tokens=max_tokens, temperature=temperature, schema=schema,
                                                  thinking=thinking, low_res=False)}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            return body
        return self._run(chain=self.resolve_chain(model, fallback_models), build=build,
                         parse=lambda p, m, js: self._parse_json(js), est=_estimate_tokens(chars, media, max_tokens),
                         what="текст")

    def chat_json_model(self, messages: list[dict], model: str, fallback: bool = True, **kw) -> dict:
        """Запрос к конкретной (обычно сильной) модели; недоступна — по цепочке текстовых моделей."""
        if not fallback:
            return self._run_strict(messages, model, **kw)
        return self.chat_json(messages, model=model, **kw)

    def _run_strict(self, messages, model, **kw):
        saved = self.text_chain
        try:
            self.text_chain = []
            return self.chat_json(messages, model=model, fallback_models=[], **kw)
        finally:
            self.text_chain = saved

    def media_json(self, media: list[tuple[str, bytes]], prompt: str, *, model: str,
                   fallback_models: list[str] | None = None, max_tokens: int = 4000, temperature: float | None = None,
                   fps: float | None = None, low_res: bool = True, schema: dict | None = None,
                   thinking: str | None = None) -> dict:
        """Gemini смотрит/слушает файл(ы) и отвечает JSON (по схеме, если она дана)."""
        if not self.gemini_keys():
            raise LLMError("нет ни одного ключа Gemini для видео/звука", "auth")
        size = sum(len(d) for _, d in media)

        def build(p, m):
            parts = self._media_parts(p, media, fps, m) + [{"text": prompt}]
            return {"contents": [{"role": "user", "parts": parts}],
                    "generationConfig": self._gen(m, max_tokens=max_tokens, temperature=temperature, schema=schema,
                                                  thinking=thinking, low_res=low_res)}
        chain = list(dict.fromkeys([model, *(fallback_models or [])]))
        avail = self.available_models()
        chain = [m for m in chain if m not in self.missing_models and (not avail or m in avail)] or chain
        return self._run(chain=chain, build=build, parse=lambda p, m, js: self._parse_json(js),
                         est=_estimate_tokens(len(prompt), size, max_tokens), what="медиа")

    def transcribe(self, audio: bytes, mime: str, *, language: str = "ru-RU", model: str = TRANSCRIBE_MODEL) -> list[dict]:
        """Облачная расшифровка с таймкодами слов (gemini-3.5-transcribe). → [{"w","s","e"}] или LLMError."""
        def build(p, m):
            cfg = {"wordTimestamp": True}
            if (m, "transcribe_cfg") not in self.unsupported:   # язык подсказываем, если поле принимается
                cfg["languageCodes"] = [language]
            return {"contents": [{"role": "user", "parts": self._media_parts(p, [(mime, audio)], None, m)}],
                    "generationConfig": {"audioTranscriptionConfig": cfg}}

        def parse(p, m, js):
            words = []
            for cand in js.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    at = part.get("audioTranscription") or {}
                    for w in at.get("words") or []:
                        s, e = _secs(w.get("startOffset")), _secs(w.get("endOffset"))
                        txt = str(w.get("word", "")).strip()
                        if txt and s is not None and e is not None:
                            words.append({"w": txt, "s": round(s, 2), "e": round(max(e, s + 0.05), 2)})
            if not words:
                raise LLMError("расшифровка без таймкодов слов", "bad_json")
            words.sort(key=lambda x: x["s"])
            return words
        avail = self.available_models()
        if avail and model not in avail:
            raise LLMError(f"{model} недоступна этому ключу", "model")
        return self._run(chain=[model], build=build, parse=parse, est=len(audio) // 40 + 4000, what="расшифровка")

    # ── Files API (файлы > 90 МБ) ───────────────────────────────
    def _upload_file(self, p: dict, mime: str, data: bytes) -> str:
        try:
            return self._upload_file_raw(p, mime, data)
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001 — сеть/битый ответ → обычная ошибка ИИ, вызывающие ловят LLMError
            raise LLMError(f"Files API: {str(e)[:160]}", "temp") from e

    def _upload_file_raw(self, p: dict, mime: str, data: bytes) -> str:
        key = (p["name"], hashlib.sha1(data).hexdigest())
        with self._lock:
            if key in self._files:
                return self._files[key]
        s = self._session()
        h = {"x-goog-api-key": self._key(p)}
        r = s.post(f"{GEMINI}/upload/v1beta/files", timeout=60, json={"file": {"display_name": f"clip-{key[1][:10]}"}},
                   headers={**h, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                            "X-Goog-Upload-Header-Content-Length": str(len(data)),
                            "X-Goog-Upload-Header-Content-Type": mime})
        url = r.headers.get("x-goog-upload-url")
        if r.status_code != 200 or not url:
            raise LLMError(f"Files API start {r.status_code}: {r.text[:200]}", "temp")
        r = s.post(url, data=data, timeout=900, headers={"Content-Length": str(len(data)), "X-Goog-Upload-Offset": "0",
                                                         "X-Goog-Upload-Command": "upload, finalize"})
        f = (r.json() if r.status_code == 200 else {}).get("file") or {}
        if not f.get("uri"):
            raise LLMError(f"Files API upload {r.status_code}: {r.text[:200]}", "temp")
        name, t0 = f.get("name"), time.time()
        while f.get("state") == "PROCESSING" and time.time() - t0 < 600:
            time.sleep(5)
            f = s.get(f"{GEMINI}/v1beta/{name}", headers=h, timeout=30).json()
        if f.get("state") == "FAILED":
            raise LLMError("Files API: файл не обработан", "too_large")
        with self._lock:
            self._files[key] = f["uri"]
        return f["uri"]

    # ── учёт трат ───────────────────────────────────────────────
    def totals(self) -> dict[str, list[int]]:
        with self._lock:
            return {k: list(v) for k, v in self.usage.items()}

    def delta(self, before: dict[str, list[int]]) -> dict:
        """Сколько ушло с момента снимка before: запросы, токены и оценка стоимости в USD."""
        out, cost = {}, 0.0
        for name, (c1, i1, o1) in self.totals().items():
            c0, i0, o0 = before.get(name, [0, 0, 0])
            dc, di, do = c1 - c0, i1 - i0, o1 - o0
            if not dc:
                continue
            model = name.split(":")[-1]
            pin, pout = MODEL_PRICES.get(model, (0.75, 3.75))
            cost += di / 1e6 * pin + do / 1e6 * pout
            out[name] = {"calls": dc, "in": di, "out": do}
        return {"by_model": out, "usd": round(cost, 4)}


class _ChainExhausted(Exception):
    def __init__(self, last):
        super().__init__(str(last))
        self.last = last


class _Paused(LLMError):
    def __init__(self, msg: str, kind: str, pause: float):
        super().__init__(msg, kind)
        self.pause = pause


def _secs(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):  # {"seconds": "1", "nanos": 500000000}
        return float(v.get("seconds", 0) or 0) + float(v.get("nanos", 0) or 0) / 1e9
    m = re.match(r"^\s*([\d.]+)\s*s?\s*$", str(v))
    return float(m[1]) if m else None


def _openai_to_gemini(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """[{"role","content"}] (OpenAI-формат) → (systemInstruction, parts одного user-хода)."""
    system, parts = [], []
    for m in messages:
        c = m.get("content")
        items = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
        if m.get("role") == "system":
            system += [x.get("text", "") for x in items if x.get("type") == "text"]
            continue
        for x in items:
            if x.get("type") == "image_url":
                url = (x.get("image_url") or {}).get("url", "")
                mm = re.match(r"data:([\w/+.-]+);base64,(.*)$", url, re.S)
                if mm:
                    parts.append({"inlineData": {"mimeType": mm[1], "data": mm[2]}})
            elif x.get("text"):
                parts.append({"text": x["text"]})
    if not parts or "text" not in parts[-1]:
        parts.append({"text": "Ответь строго JSON по инструкции."})
    return ("\n\n".join(s for s in system if s) or None), parts


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError(f"ИИ вернул не JSON: {text[:200]}", "bad_json")
