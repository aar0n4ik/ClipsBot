"""Здоровье: система (что упало, когда, ссылка на лог) и аккаунты (ранняя тревога о просадке охвата).

Ранняя тревога не ждёт, пока упадут итоговые просмотры через 2 дня:
  • скорость: просмотры ролика через ~2 ч после выхода против обычной скорости этого аккаунта;
  • CUSUM: накопленная сумма отставаний — срабатывает на устойчивую просадку, а не на один слабый ролик;
  • «зависшие» ролики: 0 просмотров спустя 3 ч (TikTok держит на проверке);
  • ошибки площадки со словом spam/limit.
Уровни: ok → watch (только сильные и безопасные клипы) → cooldown (меньше постов, длиннее паузы, 48 ч)
→ pause (72 ч тишины, если просадка не уходит). Каждое переключение пишется в журнал решений.
"""
from __future__ import annotations

import datetime as dt
import math
import os

from . import decisions
from .store import Store
from .util import now_iso, now_utc, parse_iso

SYS = "status/system.json"
ACC = "status/health.json"


# ── система ─────────────────────────────────────────────────────
def report(store: Store, component: str, level: str, msg: str, **extra):
    st = store.read_json(SYS, {}) or {}
    prev = st.get(component, {})
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    st[component] = {"level": level, "msg": msg[:400], "at": now_iso(), "run_url": run_url,
                     "since": prev.get("since") if prev.get("level") == level else now_iso(),
                     "fails": (prev.get("fails", 0) + 1) if level == "error" else 0, **extra}
    if level == "ok":
        st[component]["last_ok"] = now_iso()
    elif prev.get("last_ok"):
        st[component]["last_ok"] = prev["last_ok"]
    store.write_json(SYS, st)


# ── ряды просмотров ─────────────────────────────────────────────
def views_at_age(v: dict, hours: float) -> float | None:
    """Просмотры ролика в возрасте N часов (интерполяция по снимкам)."""
    ct = v.get("create_time")
    pts = v.get("ts") or []
    if not ct or not pts:
        return None
    target = ct + hours * 3600
    pts = sorted(pts)
    if pts[-1][0] < target - 1800:
        return None
    prev = (ct, 0)
    for t, val in pts:
        if t >= target:
            if t == prev[0]:
                return float(val)
            k = (target - prev[0]) / (t - prev[0])
            return prev[1] + k * (val - prev[1])
        prev = (t, val)
    return float(pts[-1][1])


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return 0.0 if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def account_signals(videos: list[dict], now_ts: float) -> dict:
    vids = sorted([v for v in videos if v.get("create_time")], key=lambda v: v["create_time"])
    early = [(v, views_at_age(v, 2)) for v in vids]
    early = [(v, x) for v, x in early if x is not None]
    base = [math.log1p(x) for _, x in early[-25:-4]]
    recent = early[-6:]
    mu = _median(base) if len(base) >= 6 else None
    cusum, lows = 0.0, 0
    if mu is not None:
        sd = max(0.5, _median([abs(b - mu) for b in base]) * 1.48)
        for _, x in recent:
            z = (math.log1p(x) - mu) / sd
            cusum = max(0.0, cusum + (-z - 0.5))
            lows += z < -1
    mature = [v for v in vids if now_ts - v["create_time"] > 48 * 3600]
    m5 = _median([v.get("views", 0) for v in mature[-5:]])
    mb = _median([v.get("views", 0) for v in mature[-25:-5]])
    stuck = [v for v in vids if 3 * 3600 < now_ts - v["create_time"] < 30 * 3600 and not v.get("views")]
    return {"early_baseline": round(math.expm1(mu)) if mu is not None else None, "cusum": round(cusum, 2),
            "recent_low": lows, "last5_median": m5, "baseline_median": mb, "stuck": len(stuck),
            "n_early": len(early), "n_mature": len(mature)}


def update_accounts(store: Store, stats: dict, cfg: dict) -> dict:
    """Только наблюдение, без автоматического урезания постов.

    Раньше «остывание» включалось по медиане просмотров и сравнивало новые ролики со старыми (другая эпоха канала),
    из-за чего бот резал частоту на здоровом аккаунте. Теперь режимы такие:
      ok        — всё нормально;
      watch     — информативно: свежие ролики в первые 2 часа заметно отстают от нормы ИЛИ висят с нулём просмотров;
      restricted — площадка сама ругалась на спам/лимит (тогда poster.py ставит паузу этой площадке на 24 ч).
    """
    prev = store.read_json(ACC, {}) or {}
    out = {}
    now = now_utc()
    hc = cfg.get("health") or {}
    for acc, a in (stats.get("accounts") or {}).items():
        vids = [v for v in (a.get("videos") or {}).values() if not v.get("paid_only")]
        # норма — только по роликам последних 30 дней (старые эпохи канала не сравниваем с новой)
        fresh = [v for v in vids if v.get("create_time") and now.timestamp() - v["create_time"] < 30 * 86400]
        sig = account_signals(fresh, now.timestamp())
        old = prev.get(acc, {})
        spam = old.get("spam_errors", 0) >= 2
        early = sig["cusum"] >= float(hc.get("cusum_alarm", 3.0)) and sig["recent_low"] >= 3
        if spam:
            state, reason = "restricted", "площадка ругается на частоту постов — пауза этой площадке"
        elif early:
            state, reason = "watch", f"последние ролики в первые 2 часа отстают от нормы (≈{sig['early_baseline']} просм.) — смотрим на качество"
        elif sig["stuck"] >= 2:
            state, reason = "watch", f"{sig['stuck']} свежих ролика без просмотров — возможно, на проверке у площадки"
        else:
            state, reason = "ok", "всё в норме"
        h = {**sig, "state": state, "reason": reason, "until": None, "checked_at": now_iso(),
             "since": old.get("since") if old.get("state") == state else now_iso(),
             "spam_errors": old.get("spam_errors", 0) if state != "ok" else 0}
        if state != old.get("state", "ok") and state != "ok" or (old.get("state") not in (None, "ok", state)):
            decisions.record(store, "health", f"{acc}: «{label(old.get('state', 'ok'))}» → «{label(state)}». {reason}",
                             before=old.get("state", "ok"), after=state, evidence=sig, reversible=False, account=acc)
        out[acc] = h
    for acc, old in prev.items():
        out.setdefault(acc, old)
    store.write_json(ACC, out)
    return out


def note_platform_error(store: Store, acc: str, kind: str):
    if kind != "spam":
        return
    h = store.read_json(ACC, {}) or {}
    a = h.setdefault(acc, {})
    a["spam_errors"] = a.get("spam_errors", 0) + 1
    store.write_json(ACC, h)


def label(state: str) -> str:
    return {"ok": "норма", "watch": "присмотреться", "restricted": "ограничение площадки", "cooldown": "остывание",
            "pause": "пауза"}.get(state, state)


def restrictions(state: str) -> dict:
    """Как меняется поведение публикаций в каждом режиме."""
    return {"ok": {}, "watch": {"min_score": 7, "max_risk": 1},
            "cooldown": {"cap": 2, "gap": 240, "min_score": 7, "max_risk": 0},
            "pause": {"cap": 0}}.get(state, {})
