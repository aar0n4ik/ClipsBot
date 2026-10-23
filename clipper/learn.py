"""Обучение на реальных результатах.

Как не обмануться маленькой выборкой:
  1. Сравниваем ролики в одном возрасте: просмотры через 48 ч (не «сколько сейчас»).
  2. Логарифм: один вирусный ролик на 300k не перевешивает 30 обычных.
  3. Относительно нормы аккаунта: остаток = log(просмотры) − скользящая медиана 15 прошлых роликов.
     Так рост/спад канала в целом не путается с эффектом хука или темы.
  4. Байесовское сжатие: пока роликов мало, оценка прижата к нулю («как обычно»).
     Площадка → общая оценка → ноль: если на YouTube данных мало, берём общий опыт.
  5. Изменение поведения — только при уверенности ≥ 85 % и n ≥ 8, не чаще раза в 3 дня на параметр,
     каждое изменение пишется в журнал и может быть откачено (вручную или автоматически).
  6. Исследование не выключается: каждый вариант получает минимум 10 % клипов (Томпсон-сэмплинг).
"""
from __future__ import annotations

import datetime as dt
import math
import random
from zoneinfo import ZoneInfo

import numpy as np

from . import decisions
from .clips import normalize
from .health import views_at_age
from .store import Store
from .util import log, now_iso, now_utc, parse_iso

FILE = "policy.json"
PRIOR_SD = 0.25
DEFAULT_NOISE = 0.8
MIN_N, CONF, MIN_DAYS_BETWEEN = 8, 0.85, 3

ARMS = {"hook_style": ["tease", "conflict", "number", "quote"], "cold_open": [True, False],
        "subtitles": ["ru", "both"], "progress_bar": [False, True]}
HOOK_DIMS = ("hook_style", "cold_open")
# стартовая кривая активности русскоязычной аудитории (часы по МСК)
PRIOR_HOURS = [0.25, 0.15, 0.08, 0.05, 0.05, 0.08, 0.2, 0.45, 0.6, 0.55, 0.5, 0.55,
               0.7, 0.75, 0.65, 0.6, 0.65, 0.75, 0.9, 1.0, 1.0, 0.95, 0.8, 0.5]
PLATFORM_MAX_CAP = {"tiktok": 12, "youtube": 10, "instagram": 8}
HUMAN = {"hook_style": "стиль хука", "cold_open": "панчлайн в начале", "subtitles": "англ. субтитры",
         "progress_bar": "полоса прогресса", "category": "тема", "length": "длина"}
VAL = {"tease": "недосказанность", "conflict": "конфликт", "number": "цифра", "quote": "цитата",
       True: "да", False: "нет", "ru": "только RU", "both": "RU + EN", "short": "до 20 с", "mid": "20–35 с",
       "long": "35+ с"}


# ── политика ────────────────────────────────────────────────────
def default_policy(cfg: dict) -> dict:
    return {"version": 1, "updated_at": None, "frozen": False, "pins": {}, "paused": {},
            "arms": {}, "boosts": {}, "hours": {}, "caps": {}, "warmup": {}, "hints": {}, "last_change": {}}


def load(store: Store, cfg: dict) -> dict:
    p = store.read_json(FILE) or default_policy(cfg)
    for k, v in default_policy(cfg).items():
        p.setdefault(k, v)
    return p


def save(store: Store, p: dict):
    p["updated_at"] = now_iso()
    store.write_json(FILE, p)


def pin(policy: dict, path: str, value, days: float = 14):
    policy.setdefault("pins", {})[path] = {"value": value,
                                           "until": (now_utc() + dt.timedelta(days=days)).isoformat()}
    _set(policy, path, value)


def _get(policy: dict, path: str, default=None):
    if path in (policy.get("pins") or {}):
        return policy["pins"][path]["value"]
    cur = policy
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _set(policy: dict, path: str, value):
    keys = path.split(".")
    cur = policy
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def get(policy: dict, path: str, default=None):
    return _get(policy, path, default)


# ── выбор варианта для нового клипа ─────────────────────────────
def choose_variant(policy: dict, platform: str, cfg: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    enabled = (cfg.get("learning") or {}).get("arms", list(ARMS))
    out = {}
    for dim in enabled:
        vals = ARMS.get(dim)
        if not vals:
            continue
        shares = _get(policy, f"arms.{platform}.{dim}") or {str(v): 1 / len(vals) for v in vals}
        keys = [str(v) for v in vals]
        w = [max(0.0, float(shares.get(k, 0))) for k in keys]
        s = sum(w) or 1
        pick = rng.choices(vals, weights=[x / s for x in w])[0]
        out[dim] = pick
    return out


def category_boost(policy: dict, platform: str, category: str) -> float:
    b = _get(policy, f"boosts.{platform}.category") or _get(policy, "boosts.all.category") or {}
    return float(b.get(category, 0.0))


def length_bucket(sec: float) -> str:
    return "short" if sec < 20 else "mid" if sec <= 35 else "long"


# ── данные ──────────────────────────────────────────────────────
def views48(v: dict) -> float | None:
    if not v.get("create_time"):
        return None
    age_h = (now_utc().timestamp() - v["create_time"]) / 3600
    if age_h < 48:
        return None
    x = views_at_age(v, 48)
    if x is not None:
        return x
    hist = v.get("history") or {}
    if hist:  # старые данные без почасовых снимков: снимок дня «+2»
        day = dt.datetime.fromtimestamp(v["create_time"], dt.timezone.utc).date() + dt.timedelta(days=2)
        keys = sorted(hist)
        cand = [k for k in keys if k <= day.isoformat()]
        if cand:
            return float(hist[cand[-1]])
    return float(v.get("views", 0)) if age_h < 24 * 7 else None


def build_rows(store: Store, cfg: dict) -> list[dict]:
    stats = store.read_json("stats.json", {}) or {}
    tz = ZoneInfo(cfg["posting"].get("timezone", "Europe/Moscow"))
    link = {}
    for c in store.list_json("queue"):
        c = normalize(c)
        for plat, post in c["posts"].items():
            if post.get("video_id"):
                link[(post.get("account"), str(post["video_id"]))] = (c, plat)
    rows = []
    for acc, a in (stats.get("accounts") or {}).items():
        plat = a.get("platform", "tiktok")
        vids = sorted([v for v in (a.get("videos") or {}).values() if v.get("create_time")], key=lambda v: v["create_time"])
        ys, per_day = [], {}
        for v in vids:
            d = dt.datetime.fromtimestamp(v["create_time"], tz).date().isoformat()
            per_day[d] = per_day.get(d, 0) + 1
        for v in vids:
            x = views48(v)
            local = dt.datetime.fromtimestamp(v["create_time"], tz)
            row = {"account": acc, "platform": plat, "id": v["id"], "t": v["create_time"], "hour": local.hour,
                   "day": local.date().isoformat(), "n_day": per_day[local.date().isoformat()],
                   "y": math.log1p(x) if x is not None else None, "views48": x}
            hit = link.get((acc, str(v["id"])))
            if hit:
                c, p = hit
                t = (c.get("targets") or {}).get(p, {})
                var = t.get("variant") or {}
                row.update(clip=c["id"], category=c.get("category"), score=c.get("score"),
                           length=length_bucket(float(t.get("duration") or c.get("duration") or 25)),
                           risk=(c.get("risk") or {}).get("level", 0), **{k: var.get(k) for k in ARMS})
            ret = None
            if v.get("avg_view_pct") is not None:
                ret = ("yt", float(v["avg_view_pct"]))
            elif v.get("skip_rate") is not None:
                ret = ("ig", -float(v["skip_rate"]))
            row["ret"] = ret
            prev = [r for r in ys]
            if len(prev) >= 5 and row["y"] is not None:
                row["base"] = float(np.median(prev[-15:]))
            if row["y"] is not None:
                ys.append(row["y"])
            rows.append(row)
        # для первых роликов норма — медиана всего, что есть (иначе вообще нечего сравнивать)
        allv = [r["y"] for r in rows if r["account"] == acc and r["y"] is not None]
        for r in rows:
            if r["account"] == acc and r["y"] is not None and "base" not in r and len(allv) >= 4:
                r["base"] = float(np.median([y for y in allv if y != r["y"]] or allv))
    for r in rows:
        if r["y"] is not None and "base" in r:
            r["res"] = float(np.clip(r["y"] - r["base"], -2.5, 2.5))
    # удержание: z-оценка внутри площадки → дополнительный сигнал для хуков
    for kind in ("yt", "ig"):
        vals = [r["ret"][1] for r in rows if r.get("ret") and r["ret"][0] == kind]
        if len(vals) >= 6:
            mu, sd = float(np.median(vals)), float(np.std(vals) or 1)
            for r in rows:
                if r.get("ret") and r["ret"][0] == kind:
                    r["ret_z"] = float(np.clip((r["ret"][1] - mu) / sd, -2.5, 2.5)) * 0.4
    return rows


# ── байес ───────────────────────────────────────────────────────
def posterior(values: list[float], noise: float, prior_mean: float = 0.0, prior_sd: float = PRIOR_SD):
    n = len(values)
    prec = 1 / prior_sd ** 2 + n / noise ** 2
    mean = (prior_mean / prior_sd ** 2 + sum(values) / noise ** 2) / prec
    return {"n": n, "mean": round(mean, 4), "sd": round(math.sqrt(1 / prec), 4)}


def p_best(posts: dict[str, dict], draws: int = 4000, seed: int = 7) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    keys = list(posts)
    if not keys:
        return {}
    samples = np.stack([rng.normal(posts[k]["mean"], posts[k]["sd"], draws) for k in keys])
    wins = np.bincount(samples.argmax(0), minlength=len(keys))
    return {k: round(float(w / draws), 3) for k, w in zip(keys, wins)}


def dim_posteriors(rows: list[dict], dim: str, values: list, platform: str | None, noise: float) -> dict:
    def pick(plat):
        out = {}
        for v in values:
            xs = [r["res"] for r in rows if "res" in r and r.get(dim) == v and (plat is None or r["platform"] == plat)]
            if dim in HOOK_DIMS:
                xs += [r["ret_z"] for r in rows if "ret_z" in r and r.get(dim) == v and (plat is None or r["platform"] == plat)]
            out[str(v)] = xs
        return out
    glob = {k: posterior(xs, noise) for k, xs in pick(None).items()}
    if platform is None:
        return glob
    return {k: posterior(xs, noise, prior_mean=glob[k]["mean"], prior_sd=max(PRIOR_SD, glob[k]["sd"]))
            for k, xs in pick(platform).items()}


def shares_from(post: dict, floor: float = 0.10) -> dict:
    pb = p_best(post)
    k = len(pb)
    if not k:
        return {}
    return {key: round(floor + (1 - floor * k) * p, 3) for key, p in pb.items()}


# ── главное: пересчёт политики ──────────────────────────────────
def update(store: Store, cfg: dict) -> dict:
    policy = load(store, cfg)
    if decisions.apply_commands(store, policy):
        save(store, policy)
    for path in decisions.expired_pins(policy):
        policy["pins"].pop(path, None)
    rows = build_rows(store, cfg)
    res = [r["res"] for r in rows if "res" in r]
    noise = max(0.4, float(np.std(res))) if len(res) >= 20 else DEFAULT_NOISE
    policy["stats"] = {"rows": len(rows), "with_residual": len(res), "noise": round(noise, 3)}
    platforms = sorted({r["platform"] for r in rows} | {a.get("platform", "tiktok") for a in cfg["accounts"]})
    if policy.get("frozen"):
        log("обучение на паузе — политика не меняется")
        save(store, policy)
        return policy

    # 1) варианты монтажа
    for plat in platforms:
        for dim, vals in ARMS.items():
            post = dim_posteriors(rows, dim, vals, plat, noise)
            policy.setdefault("evidence", {}).setdefault(plat, {})[dim] = post
            new = shares_from(post)
            path = f"arms.{plat}.{dim}"
            old = _get(policy, path)
            pb = p_best(post)
            best = max(pb, key=pb.get) if pb else None
            if old is None:
                _set(policy, path, {str(v): round(1 / len(vals), 3) for v in vals})
                continue
            if best and pb[best] >= CONF and post[best]["n"] >= MIN_N and abs(new[best] - old.get(best, 0)) >= 0.15:
                _change(store, policy, path, old, new, "arms", plat,
                        f"{_pl(plat)}: {HUMAN[dim]} «{VAL.get(_val(best), best)}» заходит лучше "
                        f"({_pct(post[best]['mean'])} к норме, n={post[best]['n']}, уверенность {int(pb[best] * 100)}%) — "
                        f"его доля {int(old.get(best, 0) * 100)}% → {int(new[best] * 100)}%",
                        {"posterior": post, "p_best": pb})

    # 2) темы и длина → бусты ранжирования и подсказки ИИ
    cats = sorted({r.get("category") for r in rows if r.get("category")})
    for plat in ["all"] + platforms:
        post = dim_posteriors(rows, "category", cats, None if plat == "all" else plat, noise) if cats else {}
        path = f"boosts.{plat}.category"
        old = _get(policy, path) or {}
        new = dict(old)
        notes = []
        for k, p in post.items():
            if p["n"] >= MIN_N and abs(p["mean"]) >= 2 * p["sd"] * 0.5 and abs(p["mean"] - old.get(k, 0)) >= 0.12:
                new[k] = round(float(np.clip(p["mean"], -0.8, 0.8)), 3)
                notes.append(f"«{k}» {_pct(p['mean'])}")
        if notes:
            _change(store, policy, path, old, new, "boost", plat,
                    f"{_pl(plat)}: темы по факту — " + ", ".join(notes) + ". Ранжирование клипов подстроено",
                    {"posterior": post})
    lens = dim_posteriors(rows, "length", ["short", "mid", "long"], None, noise)
    pb = p_best(lens)
    if pb:
        best = max(pb, key=pb.get)
        hint = (f"На этом канале лучше заходят ролики {VAL[best]} ({_pct(lens[best]['mean'])} к норме)"
                if pb[best] >= CONF and lens[best]["n"] >= MIN_N else "")
        if hint != policy["hints"].get("length", ""):
            if hint:
                decisions.record(store, "hint", f"ИИ-отборщику: «{hint}»", path="hints.length",
                                 before=policy["hints"].get("length", ""), after=hint, evidence={"posterior": lens})
            policy["hints"]["length"] = hint

    # 3) часы публикаций
    for plat in platforms:
        buckets = {b: [] for b in range(8)}
        for r in rows:
            if "res" in r and r["platform"] == plat:
                buckets[r["hour"] // 3].append(r["res"])
        bp = {b: posterior(xs, noise) for b, xs in buckets.items()}
        prior = list((cfg["posting"].get("prior_hours") or PRIOR_HOURS))
        new = [round(prior[h] * math.exp(0.8 * bp[h // 3]["mean"]), 3) for h in range(24)]
        m = max(new) or 1
        new = [round(x / m, 3) for x in new]
        path = f"hours.{plat}"
        old = _get(policy, path)
        if old is None:
            _set(policy, path, [round(x / max(prior), 3) for x in prior])
            continue
        top_old = set(sorted(range(24), key=lambda h: -old[h])[:4])
        top_new = set(sorted(range(24), key=lambda h: -new[h])[:4])
        strong = [b for b, p in bp.items() if p["n"] >= MIN_N and abs(p["mean"]) >= p["sd"] * 1.4]
        if top_old != top_new and strong:
            _change(store, policy, path, old, new, "hours", plat,
                    f"{_pl(plat)}: лучшие часы по факту — {', '.join(f'{h:02d}:00' for h in sorted(top_new))} "
                    f"(было {', '.join(f'{h:02d}:00' for h in sorted(top_old))})", {"buckets": bp})

    # 4) разгон новых аккаунтов и потолок постов
    stats = store.read_json("stats.json", {}) or {}
    for acc in cfg["accounts"]:
        _warmup(store, policy, cfg, acc, stats)
        _cap_controller(store, policy, cfg, acc, rows)

    # 5) автооткат решений, после которых стало хуже
    _auto_revert(store, policy, rows)
    save(store, policy)
    return policy


def _pl(p):
    return {"tiktok": "TikTok", "youtube": "Shorts", "instagram": "Reels", "all": "Все площадки"}.get(p, p)


def _val(k):
    return {"True": True, "False": False}.get(k, k)


def _pct(m: float) -> str:
    return f"{'+' if m >= 0 else '−'}{abs(round((math.exp(m) - 1) * 100))}%"


def _change(store, policy, path, old, new, kind, platform, summary, evidence, account=None) -> bool:
    if path in (policy.get("pins") or {}):
        return False
    last = (policy.get("last_change") or {}).get(path)
    if last and now_utc() - parse_iso(last) < dt.timedelta(days=MIN_DAYS_BETWEEN):
        return False
    _set(policy, path, new)
    policy.setdefault("last_change", {})[path] = now_iso()
    decisions.record(store, kind, summary, path=path, before=old, after=new, evidence=evidence,
                     platform=None if platform == "all" else platform, account=account)
    return True


def _warmup(store, policy, cfg, acc, stats):
    aid, plat = acc["id"], acc.get("platform", "tiktok")
    w = policy["warmup"].get(aid)
    vids = list(((stats.get("accounts") or {}).get(aid) or {}).get("videos", {}).values())
    if w is None:
        mode = acc.get("warmup", "auto")
        recent = [v for v in vids if v.get("create_time") and now_utc().timestamp() - v["create_time"] < 30 * 86400]
        need = mode is True or (mode == "auto" and (len(vids) < 15 or len(recent) < 3))
        if not stats.get("accounts", {}).get(aid) and mode == "auto":
            return  # статистики ещё нет (аккаунт не подключён) — решим позже
        policy["warmup"][aid] = w = {"active": bool(need), "started": now_iso(), "reason":
                                     "мало роликов или долго не было активности" if need else "аккаунт живой"}
        if need:
            decisions.record(store, "warmup", f"{aid}: режим разгона — первые дни только сильные безопасные клипы, "
                             f"2→6 постов в день по нарастающей, стабильное время", account=aid, platform=plat,
                             reversible=False)
    if not w.get("active"):
        return
    days = (now_utc() - parse_iso(w["started"])).days
    mature = sorted([v for v in vids if v.get("create_time") and now_utc().timestamp() - v["create_time"] > 48 * 3600],
                    key=lambda v: v["create_time"])
    good = len(mature) >= 5 and all(v.get("views", 0) >= 500 for v in mature[-5:])
    ramp = (cfg["posting"].get("warmup") or {}).get("ramp", [2, 2, 3, 3, 3, 4, 4, 5, 5, 6])
    if days >= len(ramp) or good:
        w["active"] = False
        w["ended"] = now_iso()
        decisions.record(store, "warmup", f"{aid}: разгон завершён ({'5 роликов подряд ≥500 просмотров' if good else 'прошло ' + str(days) + ' дн.'}) "
                         "— дальше потолок постов подбирается по данным", account=aid, platform=plat, reversible=False)


def warmup_state(policy: dict, acc_id: str, cfg: dict) -> dict | None:
    w = (policy.get("warmup") or {}).get(acc_id)
    if not w or not w.get("active"):
        return None
    ramp = (cfg["posting"].get("warmup") or {}).get("ramp", [2, 2, 3, 3, 3, 4, 4, 5, 5, 6])
    day = (now_utc() - parse_iso(w["started"])).days
    return {"day": day + 1, "cap": min(ramp[min(day, len(ramp) - 1)], hard_cap(cfg)),
            "min_score": 7 if day < 5 else 6, "max_risk": 0}


def _cap_controller(store, policy, cfg, acc, rows):
    """Потолок постов в сутки ищется экспериментом: держим уровень ≥ 7 дней, сравниваем суммарные
    просмотры в сутки (в «типичных роликах» аккаунта) и просмотры на ролик. Растёт сумма и не проседает
    каждый ролик — +1 пост. Стало хуже, чем на прошлом уровне, — назад и закрепить на 2 недели."""
    aid, plat = acc["id"], acc.get("platform", "tiktok")
    path = f"caps.{aid}"
    base_cap = int(acc.get("daily_cap") or (cfg["posting"].get(plat) or {}).get("daily_cap") or cfg["posting"].get("daily_cap", 6))
    st = _get(policy, path)
    if st is None:
        _set(policy, path, {"cap": base_cap, "since": now_iso(), "levels": {}})
        return
    if warmup_state(policy, aid, cfg) or f"{path}.cap" in (policy.get("pins") or {}):
        return
    mine = [r for r in rows if r["account"] == aid and r.get("views48") is not None]
    if len(mine) < 20:
        return
    typical = float(np.median([r["views48"] for r in mine[-30:]])) or 1.0
    since = parse_iso(st["since"]).date().isoformat()
    days = {}
    for r in mine:
        if r["day"] >= since:
            d = days.setdefault(r["day"], {"n": 0, "units": 0.0})
            d["n"] += 1
            d["units"] += r["views48"] / typical
    if len(days) < 7:
        return
    cap = st["cap"]
    U = float(np.mean([d["units"] for d in days.values()]))
    per = float(np.mean([d["units"] / d["n"] for d in days.values()]))
    binding = sum(1 for d in days.values() if d["n"] >= cap)
    st["levels"][str(cap)] = {"units_day": round(U, 2), "per_post": round(per, 2), "days": len(days), "at": now_iso()}
    prev = st["levels"].get(str(cap - 1))
    mx = int((cfg["posting"].get(plat) or {}).get("max_cap", PLATFORM_MAX_CAP.get(plat, 10)))
    health = (store.read_json("status/health.json", {}) or {}).get(aid, {}).get("state", "ok")
    if prev and U < 0.9 * prev["units_day"]:
        new = {**st, "cap": cap - 1, "since": now_iso()}
        _change(store, policy, path, st, new, "cap", plat,
                f"{aid}: {cap} постов в сутки дали меньше, чем {cap - 1} ({U:.1f} против {prev['units_day']:.1f} "
                f"«типичных роликов» в день) — возвращаю {cap - 1}", {"levels": st["levels"]}, account=aid)
        pin(policy, f"{path}.cap", cap - 1, days=14)
    elif health == "ok" and binding >= 4 and cap < mx and (not prev or per >= 0.8 * prev["per_post"]):
        new = {**st, "cap": cap + 1, "since": now_iso()}
        _change(store, policy, path, st, new, "cap", plat,
                f"{aid}: на {cap} постах в сутки каждый ролик держит уровень ({per:.2f} типичного), "
                f"клипов хватает — пробую {cap + 1} в сутки", {"levels": st["levels"]}, account=aid)


def hard_cap(cfg: dict) -> int:
    """Жёсткий потолок постов в сутки на аккаунт: ни разгон, ни автоконтроль его не поднимут."""
    return int(cfg["posting"].get("hard_cap", 4))


def daily_cap(policy: dict, acc: dict, cfg: dict) -> int:
    st = _get(policy, f"caps.{acc['id']}") or {}
    pinned = (policy.get("pins") or {}).get(f"caps.{acc['id']}.cap")
    if pinned:
        return min(int(pinned["value"]), hard_cap(cfg))
    plat = acc.get("platform", "tiktok")
    cap = int(st.get("cap") or acc.get("daily_cap") or (cfg["posting"].get(plat) or {}).get("daily_cap")
              or cfg["posting"].get("daily_cap", 4))
    return min(cap, hard_cap(cfg))


def _auto_revert(store, policy, rows):
    for d in decisions.all_(store):
        if d.get("reverted") or not d.get("reversible") or d["kind"] not in ("arms", "boost", "cap", "hours"):
            continue
        age = now_utc() - parse_iso(d["at"])
        if not dt.timedelta(days=7) <= age <= dt.timedelta(days=21):
            continue
        t0 = parse_iso(d["at"]).timestamp()
        scope = [r for r in rows if "res" in r and (not d.get("platform") or r["platform"] == d["platform"])
                 and (not d.get("account") or r["account"] == d["account"])]
        before = [r["res"] for r in scope if t0 - 14 * 86400 <= r["t"] < t0]
        after = [r["res"] for r in scope if r["t"] >= t0]
        if len(after) >= 8 and len(before) >= 8 and np.mean(after) < np.mean(before) - 0.25:
            pin(policy, d["path"], d["before"], days=14)
            decisions.mark_reverted(store, d["id"], "автоматически")
            decisions.record(store, "revert", f"Автооткат: после «{d['summary'][:90]}…» ролики стали набирать меньше "
                             f"({_pct(float(np.mean(after) - np.mean(before)))}) — вернул как было",
                             path=d["path"], before=d["after"], after=d["before"], reversible=False,
                             platform=d.get("platform"), account=d.get("account"))


def learned_examples(store: Store, cfg: dict, k: int = 5) -> dict:
    """Что перевыполнило/недовыполнило норму (а не просто «много просмотров») — для промпта ИИ."""
    rows = [r for r in build_rows(store, cfg) if "res" in r and r.get("clip")]
    if len(rows) < 8:
        return {}
    by_clip = {c["id"]: c for c in (normalize(x) for x in store.list_json("queue"))}
    rows.sort(key=lambda r: -r["res"])

    def ex(r):
        c = by_clip.get(r["clip"], {})
        t = (c.get("targets") or {}).get(r["platform"], {})
        return {"overlay": t.get("hook") or c.get("overlay", ""), "views": int(r["views48"] or 0),
                "category": c.get("category", ""), "vs_norm": _pct(r["res"]), "platform": _pl(r["platform"])}
    return {"top": [ex(r) for r in rows[:k]], "bottom": [ex(r) for r in rows[-min(k, len(rows) // 3):]]}
