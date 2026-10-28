"""Дневные лимиты: освободить слот, когда владелец удалил видео, и разовый ручный сброс.

Счётчики лежат в status/post.json:
  releases.by_day[день]            — сколько клипов вышло за день (общий лимит релизов)
  accounts[id].count_by_day[день]  — сколько роликов вышло на аккаунт
  accounts[id].drafts_by_day[день] — из них отправлено в черновики TikTok
День — по времени аудитории (posting.timezone).
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from . import decisions
from .store import Store
from .util import log, now_iso, now_utc, parse_iso

LIVE = ("posted", "inbox", "inbox_stale", "processing", "uploading")


def _day(iso: str, tz: str) -> str:
    return parse_iso(iso).astimezone(ZoneInfo(tz)).date().isoformat()


def free_slot(store: Store, clip: dict, acc_id: str, plat: str, was_status: str, tz: str) -> bool:
    """Видео удалено владельцем → минус один выход в тот день, когда оно вышло.

    Клип снимает релиз целиком только если не осталось ни одной живой публикации на других площадках.
    """
    if was_status not in LIVE:
        return False                                    # ролик так и не вышел — считать нечего
    p = (clip.get("posts") or {}).get(plat) or {}
    when = p.get("posted_at")
    if not when:
        return False
    day = _day(when, tz)
    others_live = any(q.get("status") in LIVE for pl, q in (clip.get("posts") or {}).items() if pl != plat)

    def fn(ps):
        a = (ps.get("accounts") or {}).get(acc_id)
        if a is not None:
            for key in ("count_by_day", "drafts_by_day") if was_status == "inbox" else ("count_by_day",):
                by = a.get(key) or {}
                if by.get(day, 0) > 0:
                    by[day] -= 1
                    a[key] = by
        if not others_live:
            by = (ps.setdefault("releases", {})).setdefault("by_day", {})
            if by.get(day, 0) > 0:
                by[day] -= 1
    store.update_json("status/post.json", fn, {})
    log(f"🗑 {acc_id}: удалили видео {clip.get('id')} → лимит за {day} освобождён"
        f"{'' if not others_live else ' (на других площадках клип остался — общий релиз не снят)'}")
    return True


def reset_today(store: Store, tz: str, now: dt.datetime | None = None) -> str:
    """Разовый сброс лимитов «на сейчас»: счётчики сегодняшнего дня, паузы площадок, интервал между релизами."""
    now = now or now_utc()
    today = now.astimezone(ZoneInfo(tz)).date().isoformat()

    def fn(ps):
        rs = ps.setdefault("releases", {})
        rs.setdefault("by_day", {})[today] = 0
        rs.pop("last_at", None)
        for a in (ps.get("accounts") or {}).values():
            for key in ("count_by_day", "drafts_by_day"):
                if isinstance(a.get(key), dict):
                    a[key][today] = 0
            for key in ("cooldown_until", "cooldown_reason", "last_error", "last_error_at", "diagnosis"):
                a.pop(key, None)
        ps["limits_reset_at"] = now_iso()
    store.update_json("status/post.json", fn, {})
    decisions.record(store, "limits", f"Лимиты за {today} сброшены вручную: счётчики, паузы площадок и интервал между релизами",
                     reversible=False)
    log(f"♻️ лимиты за {today} сброшены")
    return today
