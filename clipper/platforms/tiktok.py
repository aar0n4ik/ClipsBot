"""TikTok: Content Posting API (inbox/direct, чанки), Display API (статистика), OAuth.
Неаудированное приложение: direct-посты приватные. Лимит ~15 постов/сутки через API на аккаунт."""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from ..util import log
from .base import Platform, PlatformError, http

API = "https://open.tiktokapis.com"
SCOPES = "user.info.basic,video.publish,video.upload,video.list"
CHUNK = 10_000_000


def _oauth(data: dict) -> dict:
    r = http("POST", f"{API}/v2/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"], **data},
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    js = r.json()
    if r.status_code != 200 or "access_token" not in js:
        raise PlatformError(f"OAuth TikTok: {js}", "auth")
    now = int(time.time())
    return {"platform": "tiktok", "access_token": js["access_token"], "refresh_token": js["refresh_token"],
            "open_id": js.get("open_id"), "scope": js.get("scope"),
            "expires_at": now + int(js.get("expires_in", 86400)) - 300,
            "refresh_expires_at": now + int(js.get("refresh_expires_in", 31536000))}


def exchange_code(code: str, redirect_uri: str) -> dict:
    return _oauth({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})


class TikTok(Platform):
    name, label = "tiktok", "TikTok"

    def refresh(self, force: bool = False):
        t = self.tok
        if force or time.time() >= t["expires_at"]:
            new = _oauth({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
            new["user"] = t.get("user")
            self.tokens[self.id] = new
            self.save()

    def access(self) -> str:
        self.refresh()
        return self.tok["access_token"]

    def _post(self, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        r = http("POST", API + path, json=body or {}, params=params, timeout=60, headers={
            "Authorization": f"Bearer {self.access()}", "Content-Type": "application/json; charset=UTF-8"})
        js = r.json() if r.content else {}
        err = js.get("error") or {}
        code = err.get("code")
        if code in (None, "", "ok"):
            return js.get("data", {})
        kind = {"access_token_invalid": "auth", "scope_not_authorized": "auth", "rate_limit_exceeded": "rate",
                "spam_risk_too_many_posts": "spam", "spam_risk_user_banned_from_posting": "spam",
                "spam_risk_too_many_pending_share": "rate", "reached_active_user_cap": "quota",
                "unaudited_client_can_only_post_to_private_accounts": "content",
                "url_ownership_unverified": "auth", "privacy_level_option_mismatch": "content"}.get(code, "temp")
        raise PlatformError(f"TikTok {path}: {code} — {err.get('message')}", kind)

    def whoami(self) -> dict:
        r = http("GET", f"{API}/v2/user/info/", params={"fields": "open_id,display_name,avatar_url"},
                 headers={"Authorization": f"Bearer {self.access()}"}, timeout=30)
        return (r.json().get("data") or {}).get("user", {})

    def _upload(self, url: str, path: Path, size: int, chunk: int, total: int):
        with open(path, "rb") as f:
            for i in range(total):
                start = i * chunk
                end = size - 1 if i == total - 1 else start + chunk - 1
                f.seek(start)
                data = f.read(end - start + 1)
                r = http("PUT", url, data=data, timeout=600, ok=(200, 201, 206), headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end}/{size}"})
                if r.status_code not in (200, 201, 206):
                    raise PlatformError(f"TikTok upload {r.status_code}: {r.text[:200]}", "temp")

    def publish(self, path: Path, target: dict, cfg: dict, clip: dict) -> dict:
        posting = cfg["posting"]
        mode = (posting.get("tiktok") or {}).get("mode", posting.get("mode", "inbox"))
        size = path.stat().st_size
        if size <= 64 * 1024 * 1024:
            chunk, total = size, 1
        else:
            chunk, total = CHUNK, math.floor(size / CHUNK)
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}
        caption = target.get("caption_full") or target.get("caption", "")
        if mode == "direct":
            info = self._post("/v2/post/publish/creator_info/query/")
            if info.get("max_video_post_duration_sec") and clip.get("duration", 0) > info["max_video_post_duration_sec"]:
                raise PlatformError("ролик длиннее, чем разрешено аккаунту", "content")
            opts = info.get("privacy_level_options") or ["SELF_ONLY"]
            privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else opts[0]
            post_info = {"title": caption[:2200], "privacy_level": privacy,
                         "disable_duet": bool(posting.get("disable_duet") or info.get("duet_disabled")),
                         "disable_stitch": bool(posting.get("disable_stitch") or info.get("stitch_disabled")),
                         "disable_comment": bool(posting.get("disable_comment") or info.get("comment_disabled")),
                         "video_cover_timestamp_ms": int(target.get("cover_ms", 600)),
                         "brand_content_toggle": False, "brand_organic_toggle": False, "is_aigc": False}
            try:
                data = self._post("/v2/post/publish/video/init/", {"post_info": post_info, "source_info": source})
            except PlatformError as e:
                if "unaudited" not in str(e) or privacy == "SELF_ONLY":
                    raise
                log("⚠️ приложение TikTok ещё без аудита — публикую приватно")
                post_info["privacy_level"] = privacy = "SELF_ONLY"
                data = self._post("/v2/post/publish/video/init/", {"post_info": post_info, "source_info": source})
        else:
            privacy = "DRAFT"
            data = self._post("/v2/post/publish/inbox/video/init/", {"source_info": source})
        self._upload(data["upload_url"], path, size, chunk, total)
        st = self.wait(data["publish_id"])
        s = st.get("status")
        out = {"publish_id": data["publish_id"], "privacy": privacy}
        if s == "FAILED":
            raise PlatformError(f"TikTok отклонил: {st.get('fail_reason')}", "content")
        if s in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            ids = st.get("publicaly_available_post_id") or []
            out.update(status="posted" if mode == "direct" else "inbox", video_id=str(ids[0]) if ids else None)
        else:
            out["status"] = "processing"
        return out

    def wait(self, publish_id: str, timeout: int = 300) -> dict:
        t0, last = time.time(), {}
        while time.time() - t0 < timeout:
            last = self._post("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
            if last.get("status") in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"):
                return last
            time.sleep(8)
        return last

    def check(self, post: dict) -> dict:
        if post.get("status") == "processing" and post.get("publish_id"):
            st = self._post("/v2/post/publish/status/fetch/", {"publish_id": post["publish_id"]})
            if st.get("status") == "FAILED":
                post.update(status="failed", error=st.get("fail_reason"))
            elif st.get("status") in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                ids = st.get("publicaly_available_post_id") or []
                post.update(status="posted" if ids else "inbox", video_id=str(ids[0]) if ids else post.get("video_id"))
        return post

    def list_videos(self) -> list[dict]:
        fields = ("id,title,video_description,create_time,share_url,cover_image_url,duration,"
                  "view_count,like_count,comment_count,share_count")
        out, cursor = [], None
        for _ in range(15):
            body = {"max_count": 20}
            if cursor:
                body["cursor"] = cursor
            data = self._post("/v2/video/list/", body, params={"fields": fields})
            for v in data.get("videos", []):
                out.append({"id": str(v["id"]), "title": v.get("title") or (v.get("video_description") or "")[:120],
                            "description": (v.get("video_description") or "")[:400], "create_time": v.get("create_time"),
                            "url": v.get("share_url"), "cover": v.get("cover_image_url"), "duration": v.get("duration"),
                            "views": int(v.get("view_count") or 0), "likes": int(v.get("like_count") or 0),
                            "comments": int(v.get("comment_count") or 0), "shares": int(v.get("share_count") or 0)})
            if not data.get("has_more"):
                break
            cursor = data.get("cursor")
        return out
