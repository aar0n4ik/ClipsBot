"""Каждый час: просмотры со всех площадок → история (по дням и почасовые снимки первых 3 суток),
связка «ролик на площадке ↔ клип бота», здоровье аккаунтов, пересчёт политики обучения."""
from __future__ import annotations

import re
import time

from . import health, learn
from .clips import normalize
from .platforms import accounts as list_accounts
from .platforms import client
from .platforms.base import PlatformError
from .store import Store
from .util import local_date, log, now_iso, now_utc, parse_iso


def _norm(s: str) -> str:
    return re.sub(r"[^\wа-яё]+", " ", (s or "").lower()).strip()


def _thin_ts(ts: list, create_time: int) -> list:
    """Почасовые снимки первые 72 ч, дальше — один в сутки."""
    keep, last_day = [], None
    for t, v in sorted(ts):
        if t - create_time <= 72 * 3600:
            keep.append([t, v])
        else:
            d = int(t // 86400)
            if d != last_day:
                keep.append([t, v])
                last_day = d
            else:
                keep[-1] = [t, v]
    return keep[-200:]


def merge_videos(A: dict, vids: list[dict], tz: str, now_ts: int):
    today = local_date(now_utc(), tz)
    for v in vids:
        rec = A["videos"].setdefault(str(v["id"]), {"history": {}, "ts": []})
        hist, ts = rec.get("history", {}), rec.get("ts", [])
        rec.update({k: val for k, val in v.items() if k not in ("history", "ts")})
        hist[today] = max(v.get("views", 0), hist.get(today, 0))
        ts.append([now_ts, v.get("views", 0)])
        rec["history"], rec["ts"] = hist, _thin_ts(ts, v.get("create_time") or now_ts)


LIST_SAFE_MAX = 150  # если список короче — он полный, по нему можно судить об удалениях
GONE_AFTER_MIN = 30  # видео пропало из полного списка дольше этого — считаем, что удалили сами


def prune_deleted(A: dict, owner: dict[str, str], platform: str, paid_keys: set[str], now_ts: float) -> list[str]:
    """Удалённые вручную видео убираем из статистики целиком.

    Исключение: TikTok-клип, за который уже заплатили, остаётся только с просмотрами (для выплат).
    owner: video_id → id клипа в очереди. Возвращает id клипов, у которых публикацию сняли.
    """
    removed_clips = []
    for vid in list(A["videos"]):
        rec = A["videos"][vid]
        if not rec.get("deleted_at"):
            continue
        if now_ts - parse_iso(rec["deleted_at"]).timestamp() < GONE_AFTER_MIN * 60:
            continue  # может быть сбой API — подождём подтверждения
        cid = owner.get(str(vid))
        if platform == "tiktok" and cid and cid in paid_keys:
            A["videos"][vid] = {"paid_only": True, "clip_id": cid, "views": rec.get("views", 0),
                                "history": rec.get("history", {})}
        else:
            del A["videos"][vid]
        if cid:
            removed_clips.append(cid)
    return removed_clips


def mark_deleted(A: dict, seen: set[str], ts: str):
    """Видео, которого нет в полном списке площадки, помечаем удалённым. Вернулось — снимаем пометку."""
    for vid, rec in A["videos"].items():
        if vid in seen:
            rec.pop("deleted_at", None)
        else:
            rec.setdefault("deleted_at", ts)


def link_clips(store: Store, acc_id: str, platform: str, A: dict, queue: list[dict]):
    """TikTok в режиме «черновики» не возвращает id ролика — находим его по тексту описания."""
    claimed = {str(p.get("video_id")) for c in queue for p in c["posts"].values() if p.get("video_id")}
    for c in queue:
        p = c["posts"].get(platform)
        if not p or p.get("account") != acc_id or p.get("video_id") or p.get("status") not in ("inbox", "posted", "processing"):
            continue
        key = _norm((c["targets"].get(platform) or {}).get("caption", ""))[:40]
        posted = int(parse_iso(p["posted_at"]).timestamp()) if p.get("posted_at") else 0
        hit = None
        for vid, v in A["videos"].items():
            if vid in claimed or not key:
                continue
            if key in _norm(v.get("description", "")) and (v.get("create_time") or 0) >= posted - 3600:
                hit = vid
                break
        if not hit and platform == "tiktok" and p.get("status") == "inbox":
            # черновик опубликовали с другим текстом: ищем по длине ролика и времени (после отправки, в пределах 3 суток)
            dur = float((c["targets"].get(platform) or {}).get("duration") or c.get("duration") or 0)
            best = None
            for vid, v in A["videos"].items():
                ct = v.get("create_time") or 0
                if vid in claimed or not dur or not v.get("duration") or not posted <= ct <= posted + 3 * 86400:
                    continue
                if abs(float(v["duration"]) - dur) <= 1.6 and (best is None or ct < best[1]):
                    best = (vid, ct)
            hit = best[0] if best else None
        if hit:
            v = A["videos"][hit]
            p.update(video_id=hit, status="posted", url=v.get("url"), published_at=v.get("create_time"))
            claimed.add(hit)
            store.write_json(f"queue/{c['id']}.json", c)
            log(f"связал клип {c['id']} ↔ {platform} {hit}")
        if p.get("status") == "inbox" and posted and time.time() - posted > 3 * 86400 and not p.get("video_id"):
            p["status"] = "inbox_stale"  # черновик так и не опубликовали
            store.write_json(f"queue/{c['id']}.json", c)


def cmd_stats(cfg: dict, store: Store):
    stats = store.read_json("stats.json", {"accounts": {}}) or {"accounts": {}}
    tz = cfg.get("timezone", "UTC")
    queue = [normalize(c) for c in store.list_json("queue")]
    tokens = {}
    problems = []
    now_ts = int(time.time())
    for acc in list_accounts(cfg):
        cl = client(store, acc)
        tokens[acc["id"]] = {"platform": acc["platform"], **cl.token_status()}
        if not cl.connected():
            continue
        try:
            cl.refresh()
            vids = cl.list_videos()
        except PlatformError as e:
            log(f"⚠️ {acc['id']}: {e}")
            tokens[acc["id"]].update(error=str(e)[:200], kind=e.kind)
            problems.append(f"{acc['id']}: {e}")
            continue
        A = stats["accounts"].setdefault(acc["id"], {"videos": {}})
        A["platform"] = acc["platform"]
        merge_videos(A, vids, tz, now_ts)
        if len(vids) < LIST_SAFE_MAX:
            mark_deleted(A, {str(v["id"]) for v in vids}, now_iso())
        else:
            log(f"{acc['id']}: видео больше {LIST_SAFE_MAX}, проверку удалений пропускаю")
        A["updated_at"] = now_iso()
        link_clips(store, acc["id"], acc["platform"], A, queue)
        tokens[acc["id"]]["last_ok"] = now_iso()
        log(f"{acc['id']}: {len(vids)} видео, всего {sum(x.get('views', 0) for x in A['videos'].values()):,} просмотров")
    paid_keys = {line.get("g") for p in ((cfg.get("money") or {}).get("payouts") or [])
                 for line in (p.get("lines") or []) if line.get("g")}
    for acc in list_accounts(cfg):
        A = stats["accounts"].get(acc["id"])
        if not A:
            continue
        owner = {str(p.get("video_id")): c["id"] for c in queue for pl2, p in c["posts"].items()
                 if p.get("video_id") and pl2 == acc["platform"]}
        for cid in prune_deleted(A, owner, acc["platform"], paid_keys, now_ts):
            c = store.read_json(f"queue/{cid}.json", None)
            if c and c.get("posts", {}).get(acc["platform"]):
                c["posts"][acc["platform"]]["status"] = "removed_by_user"
                store.write_json(f"queue/{cid}.json", c)
                log(f"🗑 {acc['id']}: видео удалено в приложении — убрал из статистики ({cid})")
    stats["updated_at"] = now_iso()
    store.write_json("stats.json", stats)
    store.write_json("status/tokens.json", {**(store.read_json("status/tokens.json", {}) or {}), **tokens})
    health.update_accounts(store, stats, cfg)
    try:
        learn.update(store, cfg)
    except Exception as e:  # noqa: BLE001 — обучение не должно ломать сбор статистики
        log(f"⚠️ обучение: {e}")
        problems.append(f"обучение: {e}")
    health.report(store, "stats", "warn" if problems else "ok", "; ".join(problems) or "статистика собрана")
    store.sync("stats")


def cmd_doctor(cfg: dict, store: Store):
    """Раз в сутки: токены (продление, сроки), секреты, место в релизе, «осиротевшие» файлы."""
    import os

    from . import releases
    issues, warns = [], []
    need = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "DASHBOARD_PASSWORD", "TOKEN_KEY"]
    for n in need:
        if not os.environ.get(n):
            issues.append(f"не задан секрет {n}")
    plat_secrets = {"tiktok": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"], "youtube": ["YT_CLIENT_ID", "YT_CLIENT_SECRET"],
                    "instagram": ["IG_CLIENT_ID", "IG_CLIENT_SECRET"]}
    tokens = store.read_json("status/tokens.json", {}) or {}
    for acc in list_accounts(cfg):
        cl = client(store, acc)
        st = {"platform": acc["platform"], **cl.token_status()}
        if not cl.connected():
            tokens[acc["id"]] = st
            continue
        for s in plat_secrets[acc["platform"]]:
            if not os.environ.get(s):
                issues.append(f"{acc['id']}: не задан секрет {s}")
        try:
            cl.refresh(force=acc["platform"] != "tiktok")
            who = cl.whoami()
            t = cl.tokens[acc["id"]]
            if who:
                t["user"] = {**(t.get("user") or {}), **who}
                cl.save()
            st = {"platform": acc["platform"], **cl.token_status(), "last_ok": now_iso()}
            left = {"tiktok": st.get("refresh_expires_at_days"), "instagram": st.get("expires_at_days")}.get(acc["platform"])
            if left is not None and left < 14:
                warns.append(f"{acc['id']}: доступ истекает через {left} дн. — переподключи аккаунт")
        except PlatformError as e:
            st.update(error=str(e)[:200], kind=e.kind)
            (issues if e.kind == "auth" else warns).append(f"{acc['id']}: {e}")
        tokens[acc["id"]] = st
    store.write_json("status/tokens.json", tokens)
    # проверка аккаунта прошла → пауза после «blocked/auth» больше не нужна, не ждём сутки
    ps = store.read_json("status/post.json", {}) or {}
    cleared = []
    for acc in list_accounts(cfg):
        a = (ps.get("accounts") or {}).get(acc["id"])
        ok = acc["id"] in tokens and not tokens[acc["id"]].get("error") and tokens[acc["id"]].get("last_ok")
        if a and ok and a.get("cooldown_until") and str(a.get("last_error", "")).endswith(("[blocked]", "[auth]")):
            for k in ("cooldown_until", "cooldown_reason", "last_error", "last_error_at", "diagnosis"):
                a.pop(k, None)
            a["plan"] = {"mode": "пауза снята: проверка аккаунта прошла"}
            cleared.append(acc["id"])
    if cleared:
        store.write_json("status/post.json", ps)
        log(f"▶️ пауза снята после успешной проверки: {', '.join(cleared)}")
    # файлы в релизе, которые уже не нужны (клип опубликован/устарел/сломан)
    try:
        assets = releases.list_assets()
        live = {t.get("asset") for c in (normalize(x) for x in store.list_json("queue"))
                for t in c["targets"].values() if t.get("status", "ready") == "ready"}
        stale = [a for a in assets if a.get("name") not in live and a.get("name", "").endswith(".mp4")]
        for a in stale:
            releases.delete(a["name"])
        size = sum(a.get("size", 0) for a in assets if a not in stale)
        store.write_json("status/storage.json", {"assets": len(assets) - len(stale), "bytes": size, "cleaned": len(stale),
                                                 "at": now_iso()})
    except Exception as e:  # noqa: BLE001
        warns.append(f"релиз: {e}")
    level = "error" if issues else "warn" if warns else "ok"
    health.report(store, "doctor", level, "; ".join(issues + warns) or "всё проверено, проблем нет")
    store.sync("doctor")
