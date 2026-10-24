"""Единая модель клипа.

Клип = один момент стрима. У него:
  targets[platform] — своя версия под площадку (файл, хук, тексты, вариант монтажа);
  posts[platform]   — что с публикацией на этой площадке (аккаунт, id, ссылка, статус).
Один клип выходит на площадке максимум один раз (на одном аккаунте) — дублей нет.
"""
from __future__ import annotations

from .util import now_utc, parse_iso

PLATFORMS = ("tiktok", "youtube", "instagram")
DONE = ("posted", "inbox", "processing")


def normalize(c: dict) -> dict:
    """Старый формат (один TikTok) → новый."""
    if "targets" not in c:
        t = {"asset": c.get("asset"), "hook": c.get("overlay"), "caption": c.get("caption", ""),
             "hashtags": c.get("hashtags") or [], "comment": c.get("comment"), "variant": c.get("variant") or {},
             "duration": c.get("duration")}
        c["targets"] = {"tiktok": t} if c.get("asset") else {}
        c["posts"] = {}
        if c.get("account") and c.get("status") in DONE + ("failed",):
            c["posts"]["tiktok"] = {"account": c["account"], "status": c["status"], "posted_at": c.get("posted_at"),
                                    "video_id": c.get("tiktok_id"), "url": c.get("share_url"),
                                    "publish_id": c.get("publish_id"), "reason": c.get("post_reason"),
                                    "error": c.get("error")}
    c.setdefault("posts", {})
    c.setdefault("targets", {})
    return c


def pending_for(c: dict, platform: str) -> bool:
    t = c.get("targets", {}).get(platform)
    p = c.get("posts", {}).get(platform)
    return bool(t and t.get("asset") and t.get("status", "ready") == "ready" and (not p or p.get("status") == "retry"))


def age_hours(c: dict) -> float:
    return (now_utc() - parse_iso(c["created_at"])).total_seconds() / 3600


def overall(c: dict) -> str:
    st = [p.get("status") for p in c.get("posts", {}).values()]
    if any(s == "posted" for s in st):
        return "posted"
    if any(s == "processing" for s in st):
        return "processing"
    if c.get("status") in ("broken", "skipped", "expired"):
        return c["status"]
    if any(t.get("status", "ready") == "ready" for t in c.get("targets", {}).values()):
        return "ready"
    if any(s == "failed" for s in st):
        return "failed"
    if any(s in ("retry", "inbox") for s in st):  # inbox тоже retry в дашборде
        return "retry"
    return c.get("status") or "ready"


def first_post(c: dict) -> tuple[str, dict] | None:
    done = [(k, p) for k, p in c.get("posts", {}).items() if p.get("posted_at") and p.get("status") in DONE]
    return min(done, key=lambda kp: kp[1]["posted_at"]) if done else None
