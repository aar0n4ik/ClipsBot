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
        self.dead: set[str] = set()
        self.usage: dict[str, list[int]] = {}  # имя -> [запросы, токены входа, токены выхода]
        self._sent: dict[str, list[tuple[float, int]]] = {}  # имя -> [(время, токены)] за последнюю минуту
        msg = "ИИ-провайдеры: " + ", ".join(p["name"] for p in self.providers)
        if skipped:
            msg += f" (без ключа пропущены: {', '.join(skipped)})"
        log(msg)

    def chat_json(self, messages: list[dict], max_tokens: int = 2500, temperature: float = 0.6) -> dict:
        last_err = None
        for p in self.providers:
            if p["name"] in self.dead:
                continue
            for attempt in range(4):
                est = _estimate_tokens(messages, max_tokens)
                try:
                    self._wait_for_budget(p, est)
                    self._sent.setdefault(p["name"], []).append((time.time(), est))
                    return self._call(p, messages, max_tokens, temperature)
                except LLMError as e:
                    last_err = e
                    msg = str(e)
                    low = msg.lower()
                    if "413" in msg or "too large" in low or "tokens_limit" in low or "больше лимита" in low:
                        log(f"⚠️ {p['name']}: запрос слишком большой, пробую следующего провайдера")
                        break
                    if "429" in msg or "rate limit" in low or "ratelimit" in low or "quota" in low:
                        if re.search(r"per ?day|perday|\btpd\b|daily", low):
                            log(f"⚠️ {p['name']}: дневная квота исчерпана, отключаю до конца запуска")
                            self.dead.add(p["name"])
                            break
                        wait = max(1.0, min(_retry_after(msg, 65.0), 90.0))
                        log(f"⚠️ {p['name']}: лимит в минуту, жду {wait:.0f} с (попытка {attempt + 1}/4)")
                        time.sleep(wait)
                        continue
                    log(f"⚠️ {p['name']}: ошибка ({msg[:120]}), попытка {attempt + 1}/4")
                    time.sleep(4 * (attempt + 1))
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
            r = requests.post(url, json=body, timeout=180,
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
        return parse_json_loose(text)

    def totals(self) -> dict[str, list[int]]:
        return {k: list(v) for k, v in self.usage.items()}

    def delta(self, before: dict[str, list[int]]) -> dict:
        """Сколько ушло с момента снимка before: запросы, токены и оценка стоимости в USD."""
        prices = {p["name"]: (float(p.get("price_in", 0) or 0), float(p.get("price_out", 0) or 0))
                  for p in self.providers}
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
