"""Общий интерфейс площадок + зашифрованное хранилище токенов."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import requests

from ..crypto import decrypt_json, encrypt_json
from ..store import Store
from ..util import log

TOKENS = "tokens.enc"
_TOKENS_LOCK = threading.RLock()   # площадки публикуются параллельно, токены — один общий файл


class PlatformError(RuntimeError):
    """kind: auth (переподключить), rate (лимит, позже), quota, spam (подозрение платформы),
    content (сам ролик не принят), temp (временный сбой)."""

    def __init__(self, msg: str, kind: str = "temp"):
        super().__init__(msg)
        self.kind = kind


def _key() -> str:
    k = os.environ.get("TOKEN_KEY")
    if not k:
        raise SystemExit("Не задан секрет TOKEN_KEY")
    return k


def load_tokens(store: Store) -> dict:
    blob = store.read_bytes(TOKENS)
    return decrypt_json(blob, _key()) if blob else {}


def save_tokens(store: Store, tokens: dict):
    store.write_bytes(TOKENS, encrypt_json(tokens, _key()))


def http(method: str, url: str, *, retries: int = 4, ok=(200, 201), **kw) -> requests.Response:
    """Запрос с повторами на сетевые сбои и 429/5xx (экспоненциальная пауза)."""
    kw.setdefault("timeout", 120)
    if hasattr(kw.get("data"), "read"):   # файл нельзя «перечитать» при повторе — читаем в память один раз
        kw["data"] = kw["data"].read()
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(method, url, **kw)
        except requests.RequestException as e:
            last = e
            time.sleep(3 * 2 ** attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = PlatformError(f"{r.status_code} {r.text[:200]}", "rate" if r.status_code == 429 else "temp")
            wait = int(r.headers.get("Retry-After", 0) or 0) or 5 * 2 ** attempt
            time.sleep(min(wait, 90))
            continue
        return r
    if isinstance(last, PlatformError):
        raise last
    raise PlatformError(f"сеть: {last}", "temp")


class Platform:
    name = "base"
    label = "Платформа"

    def __init__(self, store: Store, acc: dict):
        self.store, self.acc = store, acc
        self.id = acc["id"]
        self.tokens = load_tokens(store)

    # ── токены ──────────────────────────────────────────────────
    def connected(self) -> bool:
        return self.id in self.tokens and self.tokens[self.id].get("platform", self.name) == self.name

    @property
    def tok(self) -> dict:
        if not self.connected():
            raise PlatformError(f"аккаунт {self.id} не подключён", "auth")
        return self.tokens[self.id]

    def save(self):
        with _TOKENS_LOCK:
            fresh = load_tokens(self.store)  # другие аккаунты могли обновиться параллельно
            fresh[self.id] = self.tokens[self.id]
            self.tokens = fresh
            save_tokens(self.store, fresh)

    def token_status(self) -> dict:
        if not self.connected():
            return {"connected": False}
        t = self.tokens[self.id]
        now = time.time()
        st = {"connected": True, "user": (t.get("user") or {}).get("display_name") or (t.get("user") or {}).get("username")}
        for k in ("expires_at", "refresh_expires_at"):
            if t.get(k):
                st[k + "_days"] = round((t[k] - now) / 86400, 1)
        return st

    # ── переопределяется ────────────────────────────────────────
    def refresh(self, force: bool = False):
        pass

    def publish(self, path: Path, target: dict, cfg: dict, clip: dict) -> dict:
        raise NotImplementedError

    def check(self, post: dict) -> dict:
        return post

    def list_videos(self) -> list[dict]:
        raise NotImplementedError

    def whoami(self) -> dict:
        return {}


def log_err(acc: str, e: Exception):
    log(f"❌ {acc}: {e}")
