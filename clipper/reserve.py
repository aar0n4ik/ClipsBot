"""Запас клипов: сколько готового лежит в очереди и до какого числа оно годно.

Зачем. Стрим идёт 5–10 часов, а релизов в сутки — единицы. Если отбирать в каждом часе
одинаково, за день набирается два десятка клипов при лимите в четыре: половина устареет,
не дождавшись слота, а компьютерное время на монтаж потрачено. Поэтому планка плавающая:
запас пуст — берём как обычно, запас полон — берём только то, что сильнее уже готового.

Срок годности ставит отборщик полем shelf:
  now     — момент привязан ко времени, через неделю его уже не выложишь;
  weeks   — актуален пару месяцев;
  forever — время не важно, лежит сколько угодно (так помечено по умолчанию).

Протухший клип не удаляется: ему проставляется status = expired, он остаётся в истории
и виден в дашборде, но в очередь на выкладку больше не попадает.
"""
from __future__ import annotations

import datetime as dt

from .clips import normalize, pending_for
from .store import Store
from .util import log, now_iso, now_utc, parse_iso

SHELF_DAYS = {"now": 7, "weeks": 45, "forever": 0}
DEFAULT_SHELF = "forever"


def shelf_of(v: dict) -> str:
    """Срок годности из ответа отборщика. Старые клипы знали только fresh=true/false."""
    s = str(v.get("shelf") or "").strip().lower()
    if s in SHELF_DAYS:
        return s
    return "now" if v.get("fresh") else DEFAULT_SHELF


def expires_at(shelf: str, created: dt.datetime | None = None) -> str | None:
    """ISO-дата, после которой клип выкладывать уже нет смысла. None — бессрочно."""
    days = SHELF_DAYS.get(shelf, 0)
    if not days:
        return None
    return ((created or now_utc()) + dt.timedelta(days=days)).isoformat()


def is_expired(c: dict, now: dt.datetime | None = None) -> bool:
    exp = c.get("expires_at")
    if not exp:
        return False
    try:
        return parse_iso(exp) <= (now or now_utc())
    except Exception:  # noqa: BLE001 — кривую дату считаем бессрочной, клип не теряем
        return False


def ready_clips(store: Store, now: dt.datetime | None = None) -> list[dict]:
    """Клипы, которые реально могут выйти: смонтированы, никуда не выложены, не протухли."""
    out = []
    for c in (normalize(x) for x in store.list_json("queue")):
        if c.get("status") in ("broken", "skipped", "expired"):
            continue
        if any(p.get("status") in ("posted", "inbox", "processing", "uploading") for p in c["posts"].values()):
            continue
        if is_expired(c, now):
            continue
        if any(pending_for(c, plat) for plat in c.get("targets", {})):
            out.append(c)
    return out


def expire_due(store: Store, now: dt.datetime | None = None) -> list[str]:
    """Помечает протухшие клипы. Возвращает их id."""
    gone = []
    for c in (normalize(x) for x in store.list_json("queue")):
        if c.get("status") in ("broken", "skipped", "expired"):
            continue
        if any(p.get("status") in ("posted", "inbox", "processing", "uploading") for p in c["posts"].values()):
            continue
        if is_expired(c, now):
            c["status"] = "expired"
            c["expired_at"] = now_iso()
            store.write_json(f"queue/{c['id']}.json", c)
            gone.append(c["id"])
    if gone:
        log(f"срок годности вышел у {len(gone)} клип(ов): {', '.join(gone)}")
    return gone


def bank_surcharge(store: Store, quality: dict) -> int:
    """На сколько поднять планку этого куска, потому что готового и так хватает.

    До reserve_target — обычная планка. От target до max — +1 балл. Выше max — +2:
    монтируем только то, что заметно сильнее лежащего в запасе.
    """
    target = int(quality.get("reserve_target", 8))
    hard = int(quality.get("reserve_max", 16))
    try:
        n = len(ready_clips(store))
    except Exception:  # noqa: BLE001 — не смогли прочитать очередь: работаем по обычной планке
        return 0
    if n >= hard:
        return 2
    if n >= target:
        return 1
    return 0
