"""Журнал решений бота. Любое автоматическое изменение поведения записывается сюда:
что поменялось, было → стало, почему (цифры), можно ли откатить.

Откат: из дашборда (кнопка пишет команду в control/commands.json) или автоматически,
если через неделю после изменения стало хуже. Откаченное значение закрепляется на 14 дней,
чтобы бот не вернул его обратно на следующий же день.
"""
from __future__ import annotations

import datetime as dt
import uuid

from .store import Store
from .util import log, now_iso, now_utc, parse_iso

FILE = "decisions.json"
KEEP = 400


def record(store: Store, kind: str, summary: str, *, path: str | None = None, before=None, after=None,
           evidence: dict | None = None, reversible: bool = True, account: str | None = None,
           platform: str | None = None) -> dict:
    items = store.read_json(FILE, []) or []
    d = {"id": uuid.uuid4().hex[:10], "at": now_iso(), "kind": kind, "summary": summary, "path": path,
         "before": before, "after": after, "evidence": evidence or {}, "reversible": bool(reversible and path),
         "account": account, "platform": platform, "reverted": False}
    items.append(d)
    store.write_json(FILE, items[-KEEP:])
    log(f"📝 решение: {summary}")
    return d


def all_(store: Store) -> list[dict]:
    return store.read_json(FILE, []) or []


def mark_reverted(store: Store, did: str, by: str):
    items = all_(store)
    for d in items:
        if d["id"] == did:
            d.update(reverted=True, reverted_at=now_iso(), reverted_by=by)
    store.write_json(FILE, items)


# ── команды из дашборда ─────────────────────────────────────────
def pending_commands(store: Store) -> list[dict]:
    cmds = store.read_json("control/commands.json", []) or []
    done = set(store.read_json("control/done.json", []) or [])
    return [c for c in cmds if c.get("id") not in done]


def mark_done(store: Store, cid: str, result: str):
    done = store.read_json("control/done.json", []) or []
    done.append(cid)
    store.write_json("control/done.json", done[-1000:])
    res = store.read_json("control/results.json", {}) or {}
    res[cid] = {"at": now_iso(), "result": result}
    store.write_json("control/results.json", dict(list(res.items())[-300:]))


def apply_commands(store: Store, policy: dict) -> bool:
    """Выполняет команды из дашборда. True — политика изменилась."""
    from .learn import pin
    changed = False
    by_id = {d["id"]: d for d in all_(store)}
    for c in pending_commands(store):
        cmd = c.get("cmd")
        if cmd == "revert" and c.get("decision") in by_id:
            d = by_id[c["decision"]]
            if d.get("path") and not d.get("reverted"):
                pin(policy, d["path"], d["before"], days=14)
                mark_reverted(store, d["id"], "вручную")
                record(store, "revert", f"Откат вручную: {d['summary']}", path=d["path"], before=d["after"],
                       after=d["before"], reversible=False)
                changed = True
            mark_done(store, c["id"], "откачено")
        elif cmd in ("freeze", "unfreeze"):
            policy["frozen"] = cmd == "freeze"
            record(store, "freeze", "Обучение поставлено на паузу" if policy["frozen"] else "Обучение снова включено",
                   reversible=False)
            mark_done(store, c["id"], "ок")
            changed = True
        elif cmd in ("pause_account", "resume_account") and c.get("account"):
            pa = policy.setdefault("paused", {})
            if cmd == "pause_account":
                pa[c["account"]] = (now_utc() + dt.timedelta(days=float(c.get("days", 3)))).isoformat()
            else:
                pa.pop(c["account"], None)
            record(store, "pause", f"{c['account']}: публикации {'на паузе' if cmd == 'pause_account' else 'снова идут'} (вручную)",
                   account=c["account"], reversible=False)
            mark_done(store, c["id"], "ок")
            changed = True
        elif cmd == "cancel_clip" and c.get("clip"):
            from .releases import delete as _del_asset
            q = store.read_json(f"queue/{c['clip']}.json")
            if q:
                cancelled = []
                for plat, t in (q.get("targets") or {}).items():
                    if t.get("status", "ready") == "ready" and not (q.get("posts") or {}).get(plat):
                        t["status"] = "skipped"  # до публикации: ролик просто не выкладываем
                        if t.get("asset"):
                            _del_asset(t["asset"])
                        cancelled.append(plat)
                store.write_json(f"queue/{c['clip']}.json", q)
                record(store, "skip", f"Публикация клипа {c['clip']} отменена вручную"
                       + (f" ({', '.join(cancelled)})" if cancelled else " — уже выложено, удалите в приложении"),
                       reversible=False)
            mark_done(store, c["id"], "отменено")
        elif cmd == "retry_clip" and c.get("clip"):
            q = store.read_json(f"queue/{c['clip']}.json")
            if q:
                for p, post in (q.get("posts") or {}).items():
                    if post.get("status") == "failed":
                        post["status"] = "retry"
                for t in (q.get("targets") or {}).values():
                    if t.get("status") == "failed":
                        t["status"] = "ready"
                if q.get("status") == "broken":
                    q["status"] = None
                store.write_json(f"queue/{c['clip']}.json", q)
            mark_done(store, c["id"], "в очереди на повтор")
        else:
            mark_done(store, c["id"], "неизвестная команда")
    return changed


def expired_pins(policy: dict) -> list[str]:
    now = now_utc()
    return [k for k, v in (policy.get("pins") or {}).items() if parse_iso(v["until"]) < now]
