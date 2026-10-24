"""Публикация. Каждый час для каждого аккаунта каждой площадки решаем: постить сейчас или нет, и что.

Порядок решения (каждое «почему» пишется в пост и видно в дашборде):
  1. Аккаунт на паузе / в режиме «пауза» по здоровью → нет.
  2. Лимит на сутки (разгон нового аккаунта → потолок, подобранный по данным → ограничения режима здоровья).
  3. Пауза между постами.
  4. Горячий клип (8+, сделан пока идёт эфир) → сразу, свежесть важнее идеального часа.
  5. Лучшие часы сегодня (кривая аудитории, переученная на фактических просмотрах этой площадки).
  6. Клипов больше, чем успеем выложить до их протухания → в любой не ночной час.
Выбор клипа: оценка ИИ × свежесть × успех темы по факту × «проверен на другой площадке»
с штрафами за повтор темы/хука/того же отрезка стрима и с потолком на безопасность контента.
"""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

from . import health, learn, releases
from .clips import age_hours, normalize, pending_for
from .config import WORK_DIR
from .platforms import accounts as list_accounts
from .platforms import client
from .platforms.base import PlatformError
from .store import Store
from .util import log, now_iso, now_utc, parse_iso

MAX_AGE_H = {"tiktok": 72, "youtube": 168, "instagram": 120}
# ошибка на уровне аккаунта: ролик не сгорает, аккаунт отдыхает (часы)
ACCOUNT_COOLDOWN_H = {"rate": 1, "quota": 6, "spam": 24, "blocked": 24, "auth": 168}


def pick_threshold(ranked: list, remaining: int) -> int:
    """Сколько сейчас качества, а сколько количества.

    Хороших (7+) хватает на сутки — берём только их. Очередь большая, хороших мало — берём от 6.
    Очередь пустая — берём от 5. Клипы ниже 5 не публикуем никогда.
    """
    strong = sum(1 for _, c, _ in ranked if int(c.get("score", 0)) >= 7)
    if remaining and strong >= remaining:
        return 7
    if len(ranked) >= 2 * max(1, remaining):
        return 6
    return 5


def plan_hours(now_local: dt.datetime, remaining: int, weights: list[float], quiet: set[int], gap_h: float,
               last_post_local: dt.datetime | None) -> list[int]:
    hours = [h for h in range(now_local.hour, 24) if h not in quiet]
    chosen: list[int] = []
    last_h = (last_post_local.hour + last_post_local.minute / 60
              if last_post_local and last_post_local.date() == now_local.date() else None)
    for h in sorted(hours, key=lambda x: -weights[x]):
        if len(chosen) >= remaining:
            break
        if last_h is not None and h + 0.1 - last_h < gap_h:
            continue
        if all(abs(h - c) >= gap_h for c in chosen):
            chosen.append(h)
    return sorted(chosen)


def _proven_boost(c: dict, platform: str, stats: dict) -> tuple[float, str | None]:
    """Если клип уже вышел на другой площадке и там набирает быстрее нормы — поднимаем его здесь."""
    best = 0.0
    why = None
    for plat, post in (c.get("posts") or {}).items():
        if plat == platform or not post.get("video_id"):
            continue
        a = (stats.get("accounts") or {}).get(post.get("account"), {})
        v = (a.get("videos") or {}).get(str(post["video_id"]))
        sig = (health.account_signals(list((a.get("videos") or {}).values()), now_utc().timestamp())
               if v else {})
        base = sig.get("early_baseline")
        x = health.views_at_age(v, 2) if v else None
        if x is not None and base:
            k = math.log1p(x) - math.log1p(base)
            if k > best:
                best, why = k, f"на {plat} набирает в {math.expm1(k) + 1:.1f}× быстрее нормы"
    return min(best, 1.5), why


def rank(queue: list[dict], platform: str, policy: dict, recent: list[dict], limits: dict, stats: dict,
         posting: dict) -> list[tuple[float, dict, list[str]]]:
    out = []
    max_age = float((posting.get(platform) or {}).get("max_age_hours", MAX_AGE_H.get(platform, 72)))
    min_score = limits.get("min_score", 0)
    max_risk = limits.get("max_risk", 3)
    cats = [r.get("category") for r in recent[:10]]
    for c in queue:
        if not pending_for(c, platform) or c.get("status") in ("broken", "skipped", "expired"):
            continue
        age = age_hours(c)
        if age > max_age or c.get("score", 0) < min_score or (c.get("risk") or {}).get("level", 0) > max_risk:
            continue
        why = []
        key = c.get("score", 0) * (0.82 ** (age / 24)) + 0.15 * float(c.get("signal", 0)) ** 0.5
        b = learn.category_boost(policy, platform, c.get("category", "other"))
        if b:
            key += 2.5 * b
            why.append(f"тема {'заходит' if b > 0 else 'заходит хуже'} ({learn._pct(b)})")
        pb, pwhy = _proven_boost(c, platform, stats)
        if pb > 0:
            key += 2.0 * pb
            why.append(pwhy)
        if recent:
            if recent[0].get("category") == c.get("category"):
                key -= 0.8
            share = cats.count(c.get("category")) / max(1, len(cats))
            if share > 0.4 and b <= 0.2:
                key -= 1.5 * (share - 0.4) * 5
            if recent[0].get("hook_style") and recent[0].get("hook_style") == ((c["targets"].get(platform) or {}).get("variant") or {}).get("hook_style"):
                key -= 0.3
            if any(r.get("vod_id") == c.get("vod_id") and abs(float(r.get("vod_time", -1e9)) - float(c.get("vod_time", 0))) < 600
                   for r in recent[:2]):
                key -= 0.7
        out.append((key, c, why))
    out.sort(key=lambda x: -x[0])
    return out


def is_hot(c: dict, posting: dict) -> bool:
    return c.get("score", 0) >= int(posting.get("hot_score", 8)) and c.get("live_when_made") and age_hours(c) <= 4


def decide(acc: dict, cfg: dict, policy: dict, a: dict, hstate: dict, queue: list[dict], stats: dict,
           now: dt.datetime) -> tuple[str | None, dict | None, dict]:
    posting = cfg["posting"]
    plat = acc["platform"]
    tz = ZoneInfo(posting["timezone"])
    local = now.astimezone(tz)
    pc = posting.get(plat) or {}
    cap = learn.daily_cap(policy, acc, cfg)
    gap = int(pc.get("min_gap_minutes", posting.get("min_gap_minutes", 80)))
    mode = "потолок подобран по данным" if f"caps.{acc['id']}" in (policy.get("last_change") or {}) else "обычный режим"
    limits = {}
    w = learn.warmup_state(policy, acc["id"], cfg)
    if w:
        cap, mode = min(cap, w["cap"]), f"разгон аккаунта, день {w['day']}"
        limits.update(min_score=w["min_score"], max_risk=w["max_risk"])
    st = hstate.get("state", "ok")
    r = health.restrictions(st)
    if st != "ok" and not (hstate.get("until") and parse_iso(hstate["until"]) < now and st in ("cooldown", "pause")):
        cap = min(cap, r.get("cap", cap))
        gap = max(gap, r.get("gap", gap))
        limits["min_score"] = max(limits.get("min_score", 0), r.get("min_score", 0))
        limits["max_risk"] = min(limits.get("max_risk", 3), r.get("max_risk", 3))
        mode = f"режим «{health.label(st)}»: {hstate.get('reason', '')}"
    paused = (policy.get("paused") or {}).get(acc["id"])
    if paused and parse_iso(paused) > now:
        cap, mode = 0, "пауза (вручную)"
    today = local.date().isoformat()
    posts_today = a.get("count_by_day", {}).get(today, 0)
    last = parse_iso(a["last_post_at"]) if a.get("last_post_at") else None
    since = (now - last).total_seconds() / 60 if last else 1e9
    quiet = set(posting.get("quiet_hours", [2, 3, 4, 5, 6]))
    weights = learn.get(policy, f"hours.{plat}") or learn.PRIOR_HOURS
    remaining = max(0, cap - posts_today)
    plan = plan_hours(local, remaining, weights, quiet, gap / 60, last.astimezone(tz) if last else None)
    if w:  # разгон: одни и те же «лучшие» часы каждый день — стабильность помогает новому аккаунту
        fixed = sorted(sorted(range(24), key=lambda h: -weights[h] if h not in quiet else 9)[:w["cap"]])
        plan = [h for h in fixed if h >= local.hour][:remaining]
    info = {"cap": cap, "gap_min": gap, "mode": mode, "posts_today": posts_today,
            "plan_today": [f"{h:02d}:07" for h in plan], "health": st}
    if remaining <= 0:
        return None, None, info
    recent = a.get("recent", [])
    ranked = rank(queue, plat, policy, recent, limits, stats, posting)
    if not ranked:
        return None, None, info
    thr = pick_threshold(ranked, remaining)
    ranked = [x for x in ranked if int(x[1].get("score", 0)) >= max(thr, limits.get("min_score", 0))]
    info["threshold"] = thr
    if not ranked:
    return None, None, info
    hot = next(((k, c, why) for k, c, why in ranked if is_hot(c, posting)), None)
    if hot and since >= max(45, gap // 2) and local.hour not in quiet and st in ("ok", "watch") and not w: 
        return "горячий клип во время эфира", hot[1], {**info, "why": hot[2]}
    if since < gap:
        return None, None, info
        _, clip, why = ranked[0]
    if local.hour not in quiet:
        return "прошло время между постами", clip, {**info, "why": why}
    return None, None, info

def full_caption(t: dict, posting: dict) -> str:
    tags = list(dict.fromkeys((t.get("hashtags") or []) + (posting.get("fixed_hashtags") or [])))
    return (t.get("caption", "").strip() + "\n\n" + " ".join(tags)).strip()


def cmd_post(cfg: dict, store: Store, force: bool = False):
    posting = cfg["posting"]
    policy = learn.load(store, cfg)
    pstate = store.read_json("status/post.json", {}) or {}
    accs = pstate.setdefault("accounts", {})
    hs = store.read_json("status/health.json", {}) or {}
    stats = store.read_json("stats.json", {}) or {}
    now = now_utc()
    queue = [normalize(c) for c in store.list_json("queue")]
    errors = []

    # обработка «зависших» публикаций и протухших клипов
    for c in queue:
        changed = False
        for plat, t in c["targets"].items():
            mx = float((posting.get(plat) or {}).get("max_age_hours", MAX_AGE_H.get(plat, 72)))
            if pending_for(c, plat) and age_hours(c) > mx:
                t["status"] = "expired"
                if t.get("asset"):
                    releases.delete(t["asset"])
                changed = True
        if changed:
            store.write_json(f"queue/{c['id']}.json", c)

    # очередь раздулась: слабые клипы (меньше 6) снимаем, чтобы не копились и не портили выбор
    from .learn import hard_cap
    for plat in ("tiktok", "youtube", "instagram"):
        pend = [c for c in queue if pending_for(c, plat)]
        if len(pend) > 3 * hard_cap(cfg):
            for c in pend:
                if int(c.get("score", 0)) < 6:
                    t = c["targets"][plat]
                    t["status"] = "skipped"
                    if t.get("asset"):
                        releases.delete(t["asset"])
                    store.write_json(f"queue/{c['id']}.json", c)
    for acc in list_accounts(cfg):
        plat = acc["platform"]
        a = accs.setdefault(acc["id"], {"platform": plat})
        cl = client(store, acc)
        if not cl.connected():
            a.update(connected=False, plan={"mode": "не подключён"})
            continue
        a["connected"] = True
        for c in queue:  # TikTok может досчитывать публикацию — проверим
            p = c["posts"].get(plat)
            if p and p.get("account") == acc["id"] and p.get("status") == "processing":
                try:
                    cl.check(p)
                    store.write_json(f"queue/{c['id']}.json", c)
                except PlatformError as e:
                    log(f"проверка публикации {c['id']}: {e}")
        cd = a.get("cooldown_until")
        if cd and parse_iso(cd) > now:
            a["plan"] = {"mode": f"пауза до {cd[:16]}: {a.get('cooldown_reason', '')}"}
            continue
        reason, clip, info = decide(acc, cfg, policy, a, hs.get(acc["id"], {}), queue, stats, now)
        a["plan"] = info
        if force and not clip:
            ranked = rank(queue, plat, policy, a.get("recent", []), {}, stats, posting)
            if ranked:
                clip, reason = ranked[0][1], "ручной запуск"
        if not clip:
            log(f"{acc['id']}: не сейчас ({info['mode']}, сегодня {info['posts_today']}/{info['cap']}, план {info['plan_today']})")
            continue
        t = clip["targets"][plat]
        log(f"{acc['id']}: постим {clip['id']} «{t.get('hook')}» — {reason}")
        try:
            path = releases.download(t["asset"], WORK_DIR / "post")
            res = cl.publish(path, {**t, "caption_full": full_caption(t, posting)}, cfg, clip)
        except PlatformError as e:
            log(f"❌ {acc['id']}: {e}")
            health.note_platform_error(store, acc["id"], e.kind)
            from .diagnose import advice_for
            a["diagnosis"] = advice_for(plat, e.kind, str(e))  # понятно: что не так и что делать
            if e.kind in ACCOUNT_COOLDOWN_H:  # беда аккаунта, а не ролика: ролик ждёт, попытки не тратятся
                hrs = ACCOUNT_COOLDOWN_H[e.kind]
                a.update(cooldown_until=(now + dt.timedelta(hours=hrs)).isoformat(),
                         cooldown_reason=str(e)[:160], last_error=f"{e} [{e.kind}]"[:300], last_error_at=now_iso())
                clip["posts"][plat] = {**(clip["posts"].get(plat) or {}), "account": acc["id"], "status": "retry",
                                       "error": str(e)[:300], "last_try": now_iso()}
                store.write_json(f"queue/{clip['id']}.json", clip)
                log(f"⏸ {acc['id']}: пауза {hrs} ч ({e.kind}), ролики не сгорают")
                errors.append(f"{acc['id']}: {e}")
                continue
            post = clip["posts"].get(plat) or {"tries": 0}
            post.update(account=acc["id"], error=str(e)[:300], last_try=now_iso(), tries=post.get("tries", 0) + 1)
            if e.kind == "content" or post["tries"] >= 3:
                post["status"] = "failed"
                t["status"] = "failed"
            else:
                post["status"] = "retry"
            clip["posts"][plat] = post
            a.update(last_error=f"{e} [{e.kind}]"[:300], last_error_at=now_iso())
            store.write_json(f"queue/{clip['id']}.json", clip)
            errors.append(f"{acc['id']}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — например, файл пропал из релиза
            log(f"❌ {acc['id']}: {e}")
            t["status"] = "failed"
            clip["posts"][plat] = {"account": acc["id"], "status": "failed", "error": str(e)[:300], "last_try": now_iso()}
            store.write_json(f"queue/{clip['id']}.json", clip)
            errors.append(f"{acc['id']}: {e}")
            continue
        clip["posts"][plat] = {**res, "account": acc["id"], "posted_at": now_iso(), "reason": reason,
                               "why": info.get("why") or []}
        t["status"] = "used"
        if res.get("status") in ("posted", "inbox"):
            releases.delete(t["asset"])
        tz = ZoneInfo(posting["timezone"])
        today = now.astimezone(tz).date().isoformat()
        cbd = {k: v for k, v in a.get("count_by_day", {}).items() if k >= (now - dt.timedelta(days=10)).date().isoformat()}
        cbd[today] = cbd.get(today, 0) + 1
        rec = {"clip": clip["id"], "category": clip.get("category"), "vod_id": clip.get("vod_id"),
               "vod_time": clip.get("vod_time"), "hook_style": (t.get("variant") or {}).get("hook_style")}
        a.update(last_post_at=now_iso(), last_clip=clip["id"], last_error=None, count_by_day=cbd,
                 recent=[rec] + a.get("recent", [])[:19], first_post_at=a.get("first_post_at") or now_iso())
        store.write_json(f"queue/{clip['id']}.json", clip)
        log(f"✅ {acc['id']}: {res.get('status')} {res.get('url') or ''}")

    pstate.update(timezone=posting["timezone"], updated_at=now_iso(),
                  hour_weights={p: learn.get(policy, f"hours.{p}") for p in ("tiktok", "youtube", "instagram")},
                  next_check=(now.replace(minute=7, second=0, microsecond=0) + dt.timedelta(hours=1)).isoformat())
    store.write_json("status/post.json", pstate)
    health.report(store, "post", "warn" if errors else "ok", "; ".join(errors) if errors else "публикации в норме")
    store.sync("post")
