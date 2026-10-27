"""Состояние живёт в отдельной ветке `data` (смонтирована в ./state).

Почему так: бесплатно, история изменений, и коммиты в `data` не пересобирают сайт.

v5: несколько воркфлоу (watch, process, post, stats, doctor) пишут одновременно, и часть файлов у них
общая (status/system.json, status/live.json, status/health.json…). В v4 sync() накладывал СВОЙ файл
целиком поверх свежей ветки — и молча затирал то, что за это время записал другой воркфлоу.
Теперь sync() делает трёхстороннее слияние JSON: берёт разницу «как было, когда я прочитал → как стало
у меня» и применяет только её к свежей версии из ветки. Чужие изменения в других ключах сохраняются.

Плюс:
  • потокобезопасность (конвейер работает параллельно);
  • статусы прогресса синхронизируются не чаще раза в 45 с — меньше коммитов и быстрее работа;
  • squash_history() — ветка data периодически сжимается в один коммит, репозиторий не пухнет годами.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .config import STATE_DIR
from .util import log, now_iso

_MISSING = object()
STATUS_SYNC_EVERY = 45.0


# ── трёхстороннее слияние JSON ─────────────────────────────────
def json_diff(base, ours):
    """Патч «base → ours». Словари — по ключам (рекурсивно); всё остальное — целиком.
    Удалённый ключ помечается _MISSING."""
    if isinstance(base, dict) and isinstance(ours, dict):
        patch = {}
        for k in ours:
            if k not in base:
                patch[k] = ours[k]
            elif base[k] != ours[k]:
                sub = json_diff(base[k], ours[k])
                patch[k] = sub
        for k in base:
            if k not in ours:
                patch[k] = _MISSING
        return _Patch(patch)
    return ours


class _Patch(dict):
    """Патч словаря (отличаем от обычного значения-словаря)."""


def json_apply(target, patch):
    if not isinstance(patch, _Patch):
        return patch
    out = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is _MISSING:
            out.pop(k, None)
        elif isinstance(v, _Patch):
            out[k] = json_apply(out.get(k), v)
        else:
            out[k] = v
    return out


def merge3(base_b: bytes | None, ours_b: bytes, theirs_b: bytes | None) -> bytes:
    """Слить наш JSON с чужими изменениями. Не JSON / не словари / нет базы → наш вариант целиком."""
    if theirs_b is None or base_b == theirs_b:
        return ours_b
    try:
        # файла не было, когда мы начали, а кто-то создал его параллельно: база — пустой словарь
        base = json.loads(base_b) if base_b is not None else {}
        ours, theirs = json.loads(ours_b), json.loads(theirs_b)
    except (ValueError, TypeError):
        return ours_b
    if not (isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict)):
        return ours_b
    merged = json_apply(theirs, json_diff(base, ours))
    return json.dumps(merged, ensure_ascii=False, indent=1).encode("utf-8")


class Store:
    def __init__(self, root: Path = STATE_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.pending: dict[str, bytes | None] = {}
        self.base: dict[str, bytes | None] = {}     # версия файла, от которой мы считали свои изменения
        self.on_sync: list[Callable[["Store"], None]] = []
        self.is_git = (self.root / ".git").exists()
        self.lock = threading.RLock()
        self._last_status_sync = 0.0

    # ── чтение/запись ───────────────────────────────────────────
    def path(self, rel: str) -> Path:
        return self.root / rel

    def _disk(self, rel: str) -> bytes | None:
        p = self.path(rel)
        return p.read_bytes() if p.exists() else None

    def read_bytes(self, rel: str) -> bytes | None:
        with self.lock:
            data = self._disk(rel)
            if rel not in self.pending:      # своё незасинканное не делаем «базой»
                self.base[rel] = data
            return data

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
        with self.lock:
            if rel not in self.base:
                self.base[rel] = self._disk(rel)
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)                       # атомарно: обрыв посреди записи не оставит битый файл
            self.pending[rel] = data

    def write_json(self, rel: str, obj):
        self.write_bytes(rel, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))

    def update_json(self, rel: str, fn, default=None):
        """Атомарно (между потоками) прочитать → изменить → записать. fn(obj) меняет на месте или возвращает новый."""
        with self.lock:
            obj = self.read_json(rel, default)
            res = fn(obj)
            self.write_json(rel, obj if res is None else res)
            return obj if res is None else res

    def delete(self, rel: str):
        with self.lock:
            if rel not in self.base:
                self.base[rel] = self._disk(rel)
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
                except (json.JSONDecodeError, OSError):
                    pass
        return out

    def set_status(self, component: str, sync: bool = True, **fields):
        """Статус прогресса. Синхронизация не чаще раза в STATUS_SYNC_EVERY секунд (кроме финальных)."""
        with self.lock:
            st = self.read_json(f"status/{component}.json", {}) or {}
            st.update(fields)
            st["updated_at"] = now_iso()
            self.write_json(f"status/{component}.json", st)
        final = fields.get("state") in ("idle", "error") or fields.get("progress") is None
        if sync and (final or time.time() - self._last_status_sync >= STATUS_SYNC_EVERY):
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
                continue
            theirs = p.read_bytes() if p.exists() else None
            merged = merge3(self.base.get(rel), data, theirs) if rel.endswith(".json") else data
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(merged)

    def sync(self, message: str, attempts: int = 10):
        with self.lock:
            self._last_status_sync = time.time()
            if not self.pending:
                return
            if not self.is_git:  # локальный режим (тесты)
                for hook in self.on_sync:
                    hook(self)
                self._synced()
                return
            for i in range(attempts):
                try:
                    self._git("fetch", "--depth=1", "origin", "data")
                    self._git("reset", "--hard", "FETCH_HEAD")
                    self._apply_pending()
                    for hook in self.on_sync:
                        hook(self)
                    for junk in self.root.rglob("*.tmp"):   # недописанные файлы прошлого упавшего запуска
                        junk.unlink(missing_ok=True)
                    self._git("add", "-A")
                    if not self._git("status", "--porcelain").stdout.strip():
                        self._synced()
                        return
                    self._git("commit", "-q", "-m", message[:200])
                    if self._git("push", "-q", "origin", "HEAD:data", check=False).returncode == 0:
                        self._synced()
                        return
                except RuntimeError as e:
                    log(f"sync попытка {i + 1}: {e}")
                time.sleep(min(30, 1.5 * 2 ** min(i, 4)) + (hash((message, i)) % 1000) / 1000)
            raise RuntimeError("Не удалось сохранить состояние в ветку data")

    def _synced(self):
        """После синка: база записанных нами файлов — то, что мы записали (наш объект в памяти от неё и идёт).
        Базы прочитанных, но не записанных файлов НЕ трогаем: если модуль держит объект, прочитанный до синка,
        и запишет его позже, разница посчитается от того, что он реально читал, — чужие правки не откатятся."""
        for rel, data in self.pending.items():
            self.base[rel] = data
        self.pending.clear()

    def squash_history(self) -> bool:
        """Сжать ветку data в один коммит (история не нужна боту, а репозиторий растёт от каждого sync).
        --force-with-lease: если кто-то успел запушить — ничего не трогаем, попробуем в следующий раз."""
        if not self.is_git:
            return False
        with self.lock:
            try:
                self._git("fetch", "--depth=1", "origin", "data")
                self._git("reset", "--hard", "FETCH_HEAD")
                head = self._git("rev-parse", "HEAD").stdout.strip()
                tree = self._git("rev-parse", "HEAD^{tree}").stdout.strip()
                root = self._git("commit-tree", tree, "-m", f"state snapshot {now_iso()}").stdout.strip()
                r = self._git("push", "-q", f"--force-with-lease=data:{head}", "origin", f"{root}:data", check=False)
                if r.returncode != 0:
                    log(f"сжатие истории отложено: {r.stderr.strip()[:200]}")
                    return False
                self._git("reset", "--hard", root)
                log("🗜 ветка data сжата в один коммит")
                return True
            except RuntimeError as e:
                log(f"сжатие истории не удалось: {e}")
                return False
