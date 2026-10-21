"""Один клиент на любые OpenAI-совместимые бесплатные API (GitHub Models, Gemini).
Если провайдер упёрся в лимит/ошибку — тихо переключаемся на следующий."""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .util import log


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, providers: list[dict]):
        self.providers = [p for p in providers if os.environ.get(p.get("key_env", ""), "")]
        if not self.providers:
            raise SystemExit("Нет ни одного ключа для ИИ (GITHUB_TOKEN или GEMINI_API_KEY)")
        self.dead: set[str] = set()

    def chat_json(self, messages: list[dict], max_tokens: int = 2500, temperature: float = 0.6) -> dict:
        last_err = None
        for p in self.providers:
            if p["name"] in self.dead:
                continue
            for attempt in range(3):
                try:
                    return self._call(p, messages, max_tokens, temperature)
                except LLMError as e:
                    last_err = e
                    msg = str(e)
                    if "429" in msg or "quota" in msg.lower() or "RateLimit" in msg:
                        if attempt == 0 and "per minute" in msg.lower():
                            time.sleep(20)
                            continue
                        log(f"⚠️ {p['name']}: лимит, переключаюсь")
                        self.dead.add(p["name"])
                        break
                    if "413" in msg or "too large" in msg.lower() or "tokens_limit" in msg:
                        log(f"⚠️ {p['name']}: запрос слишком большой, пробую следующего")
                        break
                    time.sleep(4 * (attempt + 1))
        raise LLMError(f"Все ИИ-провайдеры недоступны: {last_err}")

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
            text = r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"bad response: {r.text[:400]}") from e
        return parse_json_loose(text)


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
