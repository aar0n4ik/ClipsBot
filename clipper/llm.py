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

    def sees_images(self) -> bool:
        """Есть ли живой провайдер, который принимает картинки (иначе кадры качать незачем)."""
        return any(p.get("vision", True) and p["name"] not in self.dead for p in self.providers)

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
                    log(f"⚠️ {p['name']}: ошибка ({msg[:120]}), попытка {attempt+1}/3")
                    time.sleep(4 * (attempt + 1))
        raise LLMError(f"Все ИИ-провайдеры недоступны: {last_err}")

    def _call(self, p: dict, messages, max_tokens, temperature) -> dict:
        url = p["base_url"].rstrip("/") + "/chat/completions"
        vision = bool(p.get("vision", True))
        messages = [{**m, "content": prepare_content(m.get("content"), vision)} for m in messages]
        body = {"model": p["model"], "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "response_format": {"type": "json_object"}, **(p.get("extra") or {})}
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


def prepare_content(content, vision: bool):
    """Текстовые модели (Groq gpt-oss, Llama) принимают content только строкой: список частей даёт
    400 «messages[1].content must be a string». Если картинок нет или модель их не видит — склеиваем в строку."""
    if not isinstance(content, list):
        return content
    texts = [str(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text"]
    has_img = any(isinstance(x, dict) and x.get("type") == "image_url" for x in content)
    if vision and has_img:
        return content
    return "\n".join(t for t in texts if t)


def _salvage_truncated(text: str) -> str | None:
    """ИИ оборвал ответ на лимите токенов: оставляем полностью готовые элементы массива и закрываем скобки."""
    stack, in_str, esc, good = [], False, False, None
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if stack and stack[-1] == "[":
                good = (i + 1, list(stack))
    if not good:
        return None
    pos, st = good
    return text[:pos] + "".join("]" if c == "[" else "}" for c in reversed(st))


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    fixed = _salvage_truncated(text[text.find("{"):] if "{" in text else text)
    if fixed:
        try:
            js = json.loads(fixed)
            if isinstance(js, dict):
                log("⚠️ ответ ИИ оборван — взял только полностью готовые элементы")
                return js
        except json.JSONDecodeError:
            pass
    raise LLMError(f"ИИ вернул не JSON: {text[:200]}")
