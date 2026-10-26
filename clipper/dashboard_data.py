"""Собирает всё для дашборда в один зашифрованный файл data.enc (ветка data).
Открыть его может только тот, кто знает DASHBOARD_PASSWORD."""
from __future__ import annotations

import os

from .clips import normalize, overall, pending_for
from .config import load_money
from .crypto import encrypt_json
from .platforms import LABELS
from .platforms import accounts as list_accounts
from .store import Store
from .util import now_iso

KEEP_CLIPS = 150


def build(store: Store, cfg: dict) -> dict:
    from datetime import datetime, timedelta, timezone

    all_clips = sorted((normalize(c) for c in store.list_json("queue")), key=lambda c: c.get("created_at", ""), reverse=True)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    def _ts(s):
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

    # Что показываем в «Очередь и последние клипы»:
    # Любой клип держим не дольше суток: от последней публикации, а если ничего не выложено — от создания.
    # Ожидание на других площадках на это не влияет.
    filtered = []
    for c in all_clips:
        posts = c.get("posts", {})
        done = [p for p in posts.values() if p.get("status") == "posted" and p.get("posted_at")]
        try:
            ref = max(_ts(p["posted_at"]) for p in done) if done else (_ts(c["created_at"]) if c.get("created_at") else None)
            if ref and ref < day_ago:
                continue
        except ValueError:
            pass
        filtered.append(c)

    queue = filtered[:KEEP_CLIPS]
    stats = store.read_json("stats.json", {}) or {}
    link = {}
    for c in queue:
        for plat, p in c["posts"].items():
            if p.get("video_id"):
                link[(p.get("account"), str(p["video_id"]))] = c
    posts = []
    for acc_id, a in (stats.get("accounts") or {}).items():
        plat = a.get("platform", "tiktok")
        for vid, v in (a.get("videos") or {}).items():
            c = link.get((acc_id, str(vid)))
            posts.append({"id": vid, "platform": plat, "account": acc_id, "title": v.get("title") or v.get("description", ""),
                          "create_time": v.get("create_time"), "url": v.get("url") or v.get("share_url"),
                          "views": v.get("views", 0), "likes": v.get("likes", 0), "comments": v.get("comments", 0),
                          "shares": v.get("shares", 0), "history": v.get("history", {}),
                          "avg_view_pct": v.get("avg_view_pct"), "skip_rate": v.get("skip_rate"),
                          "clip_id": c["id"] if c else None, "category": c.get("category") if c else None,
                          "thumb": c.get("thumb") if c else v.get("cover")})
    clips = []
    for i, c in enumerate(queue[:KEEP_CLIPS]):
        clips.append({
            **{k: c.get(k) for k in ("id", "vod_id", "vod_title", "vod_time", "duration", "score", "category", "why",
                                     "created_at", "signal", "subscores", "risk", "audio", "opening")},
            "overlay": c.get("overlay"), "status": overall(c), "thumb": c.get("thumb") if i < 80 else None,
            "targets": {p: {k: t.get(k) for k in ("hook", "hook_style", "caption", "hashtags", "title", "description",
                                                  "comment", "variant", "status", "duration", "hook_quality", "asset")}
                        for p, t in c["targets"].items()},
            "posts": {p: {k: x.get(k) for k in ("account", "status", "posted_at", "video_id", "url", "reason", "why",
                                                "error", "privacy")} for p, x in c["posts"].items()}})
    vods = store.read_json("vods.json", {}) or {}
    meta = store.read_json("meta.json", {}) or {}
    name = (cfg["streamer"].get("display_name") or "").strip()
    if not name or name == "CHANGE_ME":
        name = meta.get("display_name") or cfg["streamer"].get("twitch_login", "")
    policy = store.read_json("policy.json", {}) or {}
    return {
        "generated_at": now_iso(),
        "title": (cfg.get("dashboard", {}) or {}).get("title") or f"Нарезки {name}",
        "timezone": cfg.get("timezone", "UTC"),
        "streamer": {**meta, "display_name": name},
        "money": load_money(cfg.get("money")),
        "platform_labels": LABELS,
        "accounts": [{"id": a["id"], "name": a.get("name", a["id"]), "platform": a["platform"],
                      "enabled": a.get("enabled", True)} for a in list_accounts(cfg, enabled_only=False)],
        "posting": {"timezone": cfg["posting"].get("timezone"), "quiet_hours": cfg["posting"].get("quiet_hours")},
        "status": {k: store.read_json(f"status/{k}.json", {}) or {}
                   for k in ("live", "process", "post", "watch", "health", "system", "tokens", "storage")},
        "policy": {k: policy.get(k) for k in ("arms", "hours", "caps", "warmup", "hints", "frozen", "paused", "stats",
                                               "evidence", "pins")},
        "decisions": (store.read_json("decisions.json", []) or [])[-150:],
        "commands": {"results": store.read_json("control/results.json", {}) or {}},
        "clips": clips,
        "posts": posts,
        "vods": sorted([{"id": k, **{x: v.get(x) for x in ("title", "created_at", "duration", "processed_until",
                                                           "finished", "clips", "gaps")}} for k, v in vods.items()],
                       key=lambda x: x.get("created_at") or "", reverse=True)[:20],
    }


def install(store: Store, cfg: dict):
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        return

    def hook(s: Store):
        (s.root / "data.enc").write_bytes(encrypt_json(build(s, cfg), pw))

    store.on_sync.append(hook)
