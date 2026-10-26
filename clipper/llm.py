"""Один клиент на любые OpenAI-совместимые API (Groq, Gemini и т.п.).

Что делает:
- при лимите в минуту ЖДЁТ, а не отключает провайдера до конца запуска;
- отключает провайдера только при исчерпанной дневной квоте;
- заранее оценивает размер запроса и не шлёт то, что гарантированно не влезет в лимит tpm;
- пишет в лог, какие провайдеры реально активны (провайдер без ключа тихо пропускается).
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .util import log


class LLMError(RuntimeError):
    pass


# $ за 1M токенов (вход, выход) — для оценки трат в журнале
MODEL_PRICES = {"gemini-4-argon": (2.0, 10.0), "gemini-3.8-flash": (0.75, 3.75), "gemini-3.6-flash": (0.5, 3.0),
                "gemini-3.5-flash-lite": (0.3, 2.5)}


def _retry_after(msg: str, default: float) -> float:
    """Groq пишет «try again in 45ms», «try again in 1m30.5s», «try again in 2.5s»."""
    m = re.search(r"try again in\s+(\d+)m([\d.]+)s", msg)
    if m:
        return float(m[1]) * 60 + float(m[2])
    m = re.search(r"try again in\s+([\d.]+)ms", msg)
    if m:
        return float(m[1]) / 1000
    m = re.search(r"try again in\s+([\d.]+)s", msg)
    if m:
        return float(m[1])
    return default


def _estimate_tokens(messages: list[dict], max_tokens: int) -> int:
    """Грубая оценка с запасом: текст ~2 символа на токен, картинка ~800 токенов."""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c) // 2
            continue
        for part in c or []:
            if part.get("type") == "image_url":
                n += 800
            else:
                n += len(part.get("text", "")) // 2
    return n + max_tokens


class LLM:
    def __init__(self, providers: list[dict]):
        active = [p for p in providers if os.environ.get(p.get("key_env", ""), "")]
        skipped = [p["name"] for p in providers if p not in active]
        self.providers = active
        if not self.providers:
            raise SystemExit("Нет ни одного ключа для ИИ (GROQ_API_KEY или GEMINI_API_KEY в Secrets)")
        self.dead: set[str] = set()          # дневная квота исчерпана — до конца запуска
        self.cool: dict[str, float] = {}     # имя -> время, до которого ключ на паузе (таймаут, 503, минутный лимит)
        self._rr = 0                         # порядок ключей по кругу: нагрузка уходит на все ключи по очереди
        self.usage: dict[str, list[int]] = {}  # имя -> [запросы, токены входа, токены выхода]
        self._sent: dict[str, list[tuple[float, int]]] = {}  # имя -> [(время, токены)] за последнюю минуту
        msg = "ИИ-провайдеры: " + ", ".join(p["name"] for p in self.providers)
        if skipped:
            msg += f" (без ключа пропущены: {', '.join(skipped)})"
        log(msg)

    def _available(self, skip: set[str]) -> list[dict]:
        """Ключи, которые можно сейчас дёрнуть, в порядке по кругу. Если все на паузе — ждём, пока какой-то оттает."""
        while True:
            names = [p for p in self.providers if p["name"] not in self.dead and p["name"] not in skip]
            if not names:
                return []
            now = time.time()
            ready = [p for p in names if self.cool.get(p["name"], 0) <= now]
            if ready:
                k = self._rr % len(ready)
                self._rr += 1
                return ready[k:] + ready[:k]
            wait = min(max(1.0, min(self.cool[p["name"]] for p in names) - now), 150.0)
            log(f"⏳ все ключи ИИ на паузе, жду {wait:.0f} с")
            time.sleep(wait)

    def chat_json(self, messages: list[dict], max_tokens: int = 2500, temperature: float = 0.6) -> dict:
        """Сразу переходим на следующий ключ при любой ошибке: таймаут, 503, минутный лимит, слишком большой запрос.
        Ключ, который подвёл, ставим на паузу, и он снова вступает в круг, когда пауза кончится."""
        last_err, skip = None, set()
        for _ in range(len(self.providers) * 4):
            order = self._available(skip)
            if not order:
                break
            p = order[0]
            name = p["name"]
            est = _estimate_tokens(messages, max_tokens)
            try:
                self._wait_for_budget(p, est)
                self._sent.setdefault(name, []).append((time.time(), est))
                return self._call(p, messages, max_tokens, temperature)
            except LLMError as e:
                last_err = e
                msg = str(e)
                low = msg.lower()
                if "больше лимита" in low or "413" in msg or "too large" in low or "tokens_limit" in low:
                    log(f"⚠️ {name}: запрос не влезает в лимит, беру другой ключ")
                    skip.add(name)
                    continue
                if re.search(r"per ?day|perday|\btpd\b|daily", low) and ("429" in msg or "quota" in low or "rate" in low):
                    log(f"⚠️ {name}: дневная квота исчерпана, отключаю до конца запуска")
                    self.dead.add(name)
                    continue
                if "429" in msg or "rate limit" in low or "ratelimit" in low or "quota" in low:
                    pause, why = max(5.0, min(_retry_after(msg, 60.0), 120.0)), "лимит в минуту"
                elif "timed out" in low or "timeout" in low:
                    pause, why = 150.0, "таймаут"
                elif any(code in msg for code in ("500", "502", "503", "504")) or "high demand" in low:
                    pause, why = 120.0, "сервер перегружен"
                elif "network" in low:
                    pause, why = 60.0, "сетевая ошибка"
                else:
                    pause, why = 45.0, "ошибка ответа"
                self.cool[name] = time.time() + pause
                log(f"↪ {name}: {why}, пауза {pause:.0f} с, пробую другой ключ")
                skip.add(name)
        raise LLMError(f"Все ИИ-провайдеры недоступны: {last_err}")

    def _wait_for_budget(self, p: dict, est: int) -> None:
        tpm = p.get("tpm")
        if not tpm:
            return
        if est > tpm:
            raise LLMError(f"запрос ~{est} токенов больше лимита {p['name']} ({tpm} в минуту)")
        now = time.time()
        window = [(t, n) for t, n in self._sent.get(p["name"], []) if now - t < 60]
        self._sent[p["name"]] = window
        if sum(n for _, n in window) + est <= tpm:
            return
        oldest = min(t for t, _ in window)
        wait = max(1.0, 60 - (now - oldest))
        log(f"⏳ {p['name']}: жду {wait:.0f} с, чтобы не превысить {tpm} токенов в минуту")
        time.sleep(wait)

    def _call(self, p: dict, messages, max_tokens, temperature) -> dict:
        url = p["base_url"].rstrip("/") + "/chat/completions"
        body = {"model": p["model"], "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "response_format": {"type": "json_object"}}
        try:
            r = requests.post(url, json=body, timeout=90,
                              headers={"Authorization": f"Bearer {os.environ[p['key_env']]}",
                                       "Content-Type": "application/json"})
        except requests.RequestException as e:
            raise LLMError(f"network {e}") from e
        if r.status_code != 200:
            raise LLMError(f"{r.status_code} {r.text[:400]}")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"bad response: {r.text[:400]}") from e
        u = data.get("usage") or {}
        cur = self.usage.setdefault(p["name"], [0, 0, 0])
        cur[0] += 1
        cur[1] += int(u.get("prompt_tokens", 0) or 0)
        cur[2] += int(u.get("completion_tokens", 0) or 0)
        try:
            return parse_json_loose(text)
        except (ValueError, LLMError) as e:  # битый JSON от модели: это ошибка ответа, идём на другой ключ
            raise LLMError(f"bad json: {str(e)[:200]} | {text[:200]}") from e

    # ── Gemini напрямую: видео и звук (OpenAI-совместимый вход их не принимает) ──
    def gemini_keys(self) -> list[dict]:
        return [p for p in self.providers if "generativelanguage.googleapis.com" in p.get("base_url", "")]

    def media_json(self, media: list[tuple[str, bytes]], prompt: str, *, model: str,
                   fallback_models: list[str] | None = None, max_tokens: int = 4000,
                   temperature: float = 0.3, fps: float | None = None, low_res: bool = True) -> dict:
        """Gemini смотрит/слушает файл(ы) и отвечает JSON.

        media — [(mime, bytes)], inline (до ~20 МБ на запрос). Ключи идут по кругу, как в chat_json.
        Если модель недоступна (нет доступа/биллинга/модель не найдена) — пробуем следующую из fallback_models."""
        import base64
        keys = self.gemini_keys()
        if not keys:
            raise LLMError("нет ни одного ключа Gemini для видео")
        parts = []
        for mime, data in media:
            part = {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}
            if fps and mime.startswith("video/"):
                part["video_metadata"] = {"fps": fps}
            parts.append(part)
        parts.append({"text": prompt})
        gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if low_res:
            gen["mediaResolution"] = "MEDIA_RESOLUTION_LOW"
        est = sum(len(d) for _, d in media) // 40 + len(prompt) // 2 + max_tokens  # грубо: 1 токен ≈ 40 байт видео
        models = [model] + [m for m in (fallback_models or []) if m != model]
        last: Exception | None = None
        for m in models:
            skip: set[str] = set()
            for _ in range(len(keys) * 3):
                order = [p for p in self._available(skip) if p in keys]
                if not order:
                    break
                p = order[0]
                name = f"{p['name']}:{m}"
                try:
                    self._wait_for_budget(p, est)
                    self._sent.setdefault(p["name"], []).append((time.time(), est))
                    return self._gemini_call(p, m, parts, gen)
                except LLMError as e:
                    last = e
                    msg, low = str(e), str(e).lower()
                    if any(x in msg for x in ("404", "NOT_FOUND")) or "not found" in low or "billing" in low \
                            or ("403" in msg and "permission" in low) or "not supported" in low:
                        log(f"⚠️ {m}: модель недоступна ({msg[:120]}), беру запасную")
                        break  # эта модель — дальше по списку моделей
                    if "400" in msg and ("mediaresolution" in low or "video_metadata" in low or "unknown name" in low):
                        gen.pop("mediaResolution", None)
                        for part in parts:
                            part.pop("video_metadata", None)
                        continue
                    if re.search(r"per ?day|perday|daily", low) and ("429" in msg or "quota" in low):
                        self.dead.add(p["name"])
                        continue
                    pause = 60.0 if ("429" in msg or "quota" in low) else 120.0 if any(c in msg for c in ("500", "502", "503", "504")) else 30.0
                    self.cool[p["name"]] = time.time() + pause
                    skip.add(p["name"])
                    log(f"↪ {name}: {msg[:120]} — пауза {pause:.0f} с, другой ключ")
        raise LLMError(f"Gemini (видео) недоступен: {last}")

    def _gemini_call(self, p: dict, model: str, parts: list, gen: dict) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
        try:
            r = requests.post(url, json=body, timeout=300,
                              headers={"x-goog-api-key": os.environ[p["key_env"]], "Content-Type": "application/json"})
        except requests.RequestException as e:
            raise LLMError(f"network {e}") from e
        if r.status_code != 200:
            raise LLMError(f"{r.status_code} {r.text[:400]}")
        try:
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            text = "".join(x.get("text", "") for x in (cand.get("content") or {}).get("parts", []) if not x.get("thought"))
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"bad response: {r.text[:300]}") from e
        if not text:
            raise LLMError(f"пустой ответ ({cand.get('finishReason')})")
        u = data.get("usageMetadata") or {}
        key = f"{p['name']}:{model}"
        cur = self.usage.setdefault(key, [0, 0, 0])
        cur[0] += 1
        cur[1] += int(u.get("promptTokenCount", 0) or 0)
        cur[2] += int(u.get("candidatesTokenCount", 0) or 0) + int(u.get("thoughtsTokenCount", 0) or 0)
        try:
            return parse_json_loose(text)
        except (ValueError, LLMError) as e:
            raise LLMError(f"bad json: {str(e)[:200]} | {text[:200]}") from e

    def chat_json_model(self, messages: list[dict], model: str, fallback: bool = True, **kw) -> dict:
        """Текстовый запрос к конкретной модели Gemini (например, сильной — для решений). Нет доступа — обычный chat_json."""
        saved = self.providers
        try:
            self.providers = [{**p, "model": model, "name": f"{p['name']}@{model}"} for p in self.gemini_keys()] or saved
            return self.chat_json(messages, **kw)
        except LLMError:
            if not fallback:
                raise
        finally:
            self.providers = saved
        return self.chat_json(messages, **kw)

    def totals(self) -> dict[str, list[int]]:
        return {k: list(v) for k, v in self.usage.items()}

    def delta(self, before: dict[str, list[int]]) -> dict:
        """Сколько ушло с момента снимка before: запросы, токены и оценка стоимости в USD."""
        prices = {p["name"]: (float(p.get("price_in", 0) or 0), float(p.get("price_out", 0) or 0))
                  for p in self.providers}
        for name in self.usage:
            if name not in prices:
                model = name.split(":")[-1].split("@")[-1]
                prices[name] = MODEL_PRICES.get(model, (0.75, 3.75))
        out, cost = {}, 0.0
        for name, (c1, i1, o1) in self.usage.items():
            c0, i0, o0 = before.get(name, [0, 0, 0])
            dc, di, do = c1 - c0, i1 - i0, o1 - o0
            if not dc:
                continue
            pin, pout = prices.get(name, (0.0, 0.0))
            cost += di / 1e6 * pin + do / 1e6 * pout
            out[name] = {"calls": dc, "in": di, "out": do}
        return {"by_model": out, "usd": round(cost, 4)}


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError(f"ИИ вернул не JSON: {text[:200]}")
