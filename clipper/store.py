"""Состояние живёт в отдельной ветке `data` (смонтирована в ./state).

Почему так: бесплатно, история изменений, и коммиты в `data` не пересобирают сайт.
Несколько воркфлоу пишут одновременно, поэтому sync() делает «пересадку»:
скачать свежую ветку → наложить СВОИ изменённые файлы → пересобрать дашборд → push.
Каждый воркфлоу пишет только свои файлы, поэтому конфликтов нет.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Callable

from .config import STATE_DIR
from .util import log, now_iso


class Store:
    def __init__(self, root: Path = STATE_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.pending: dict[str, bytes | None] = {}
        self.on_sync: list[Callable[["Store"], None]] = []
        self.is_git = (self.root / ".git").exists()

    # ── чтение/запись ───────────────────────────────────────────
    def path(self, rel: str) -> Path:
        return self.root / rel

    def read_bytes(self, rel: str) -> bytes | None:
        p = self.path(rel)
        return p.read_bytes() if p.exists() else None

    def read_json(self, rel: str, default=None):
        b = self.read_bytes(rel)
        if b is None:
            return default
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            log(f"⚠️ битый JSON {rel}, использую значение по умолчанию")
            return default

    def write_bytes(self, rel: str, data: bytes):
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.pending[rel] = data

    def write_json(self, rel: str, obj):
        self.write_bytes(rel, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))

    def delete(self, rel: str):
        p = self.path(rel)
        if p.exists():
            p.unlink()
        self.pending[rel] = None

    def list_json(self, rel_dir: str) -> list[dict]:
        d = self.path(rel_dir)
        out = []
        if d.exists():
            for p in sorted(d.glob("*.json")):
                try:
                    out.append(json.loads(p.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass
        return out

    def set_status(self, component: str, sync: bool = True, **fields):
        st = self.read_json(f"status/{component}.json", {}) or {}
        st.update(fields)
        st["updated_at"] = now_iso()
        self.write_json(f"status/{component}.json", st)
        if sync:
            self.sync(f"status: {component} {fields.get('stage', '')}".strip())

    # ── git ─────────────────────────────────────────────────────
    def _git(self, *args, check=True):
        r = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        return r

    def _apply_pending(self):
        for rel, data in self.pending.items():
            p = self.path(rel)
            if data is None:
                if p.exists():
                    p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)

    def sync(self, message: str, attempts: int = 8):
        if not self.pending:
            return
        if not self.is_git:  # локальный режим (тесты)
            for hook in self.on_sync:
                hook(self)
            self.pending.clear()
            return
        for i in range(attempts):
            try:
                self._git("fetch", "--depth=1", "origin", "data")
                self._git("reset", "--hard", "FETCH_HEAD")
                self._apply_pending()
                for hook in self.on_sync:
                    hook(self)
                self._git("add", "-A")
                if not self._git("status", "--porcelain").stdout.strip():
                    self.pending.clear()
                    return
                self._git("commit", "-q", "-m", message)
                if self._git("push", "-q", "origin", "HEAD:data", check=False).returncode == 0:
                    self.pending.clear()
                    return
            except RuntimeError as e:
                log(f"sync попытка {i + 1}: {e}")
            time.sleep(2 + i * 3)
        raise RuntimeError("Не удалось сохранить состояние в ветку data")
