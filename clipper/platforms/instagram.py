"""Instagram Reels: Instagram API with Instagram Login (graph.instagram.com).

Нужен профессиональный аккаунт Instagram (Business/Creator). Лимит — 100 постов через API за 24 ч.
Видео забирается Instagram по публичной ссылке (у нас — файл в GitHub Release публичного репозитория).
Токен живёт 60 дней и продлевается ботом автоматически (раз в сутки проверка, продление за 20 дней до конца).
Метрики Reels: views, reach, shares, saved, ig_reels_avg_watch_time, reels_skip_rate (доля пропусков в первые 3 с).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..releases import public_url
from .base import Platform, PlatformError, http

GRAPH = "https://graph.instagram.com"
SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights"
METRICS = ["views", "reach", "shares", "saved", "ig_reels_avg_watch_time", "reels_skip_rate"]


def exchange_code(code: str, redirect_uri: str) -> dict:
    r = http("POST", "https://api.instagram.com/oauth/access_token", data={
        "client_id": os.environ["IG_CLIENT_ID"], "client_secret": os.environ["IG_CLIENT_SECRET"],
        "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code}, timeout=30)
    js = r.json()
    if "access_token" not in js:
        raise PlatformError(f"OAuth Instagram: {js}", "auth")
    r2 = http("GET", f"{GRAPH}/access_token", params={"grant_type": "ig_exchange_token",
                                                     "client_secret": os.environ["IG_CLIENT_SECRET"],
                                                     "access_token": js["access_token"]}, timeout=30)
    long = r2.json()
    if "access_token" not in long:
        raise PlatformError(f"Instagram long-lived token: {long}", "auth")
    now = int(time.time())
    return {"platform": "instagram", "access_token": long["access_token"], "user_id": str(js.get("user_id")),
            "expires_at": now + int(long.get("expires_in", 5184000)), "issued_at": now}


class Instagram(Platform):
    name, label = "instagram", "Instagram Reels"

    def refresh(self, force: bool = False):
        t = self.tok
        left = t["expires_at"] - time.time()
        if left <= 0:
            raise PlatformError("токен Instagram истёк — подключи аккаунт заново", "auth")
        if force or (left < 20 * 86400 and time.time() - t.get("issued_at", 0) > 86400):
            r = http("GET", f"{GRAPH}/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": t["access_token"]}, timeout=30)
            js = r.json()
            if "access_token" in js:
                t.update(access_token=js["access_token"], expires_at=int(time.time()) + int(js.get("expires_in", 5184000)),
                         issued_at=int(time.time()))
                self.save()

    def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.tok["access_token"]
        r = http(method, f"{GRAPH}/{path.lstrip('/')}", params=params if method == "GET" else None,
                 data=params if method == "POST" else None, timeout=60)
        js = r.json()
        if "error" in js:
            e = js["error"]
            code = e.get("code")
            kind = "auth" if code in (190, 102) else "rate" if code in (4, 17, 32, 613) else \
                "quota" if code == 9 else "content" if code in (100, 352, 2207026) else \
                "blocked" if (code == 200 or "blocked" in str(e.get("message", "")).lower()) else "temp"
            raise PlatformError(f"Instagram: {e.get('message')} ({code}/{e.get('error_subcode')})", kind)
        return js

    def uid(self) -> str:
        return self.tok.get("user_id") or self._call("GET", "me", fields="user_id")["user_id"]

    def whoami(self) -> dict:
        js = self._call("GET", "me", fields="user_id,username")
        return {"display_name": "@" + js.get("username", ""), "username": js.get("username"), "user_id": js.get("user_id")}

    def preflight(self):
        self.refresh()
        limit = self._call("GET", f"{self.uid()}/content_publishing_limit", fields="quota_usage,config")
        if ((limit.get("data") or [{}])[0]).get("quota_usage", 0) >= 95:
            raise PlatformError("лимит публикаций Instagram на сутки почти исчерпан", "quota")

    def publish(self, path: Path, target: dict, cfg: dict, clip: dict) -> dict:
        uid = self.uid()
        limit = self._call("GET", f"{uid}/content_publishing_limit", fields="quota_usage,config")
        used = ((limit.get("data") or [{}])[0]).get("quota_usage", 0)
        if used >= 95:
            raise PlatformError("лимит публикаций Instagram на сутки почти исчерпан", "quota")
        url = public_url(target["asset"])
        cont = self._call("POST", f"{uid}/media", media_type="REELS", video_url=url,
                          caption=target.get("caption_full") or target.get("caption", ""), share_to_feed="true",
                          thumb_offset=str(int(target.get("cover_ms", 600))))
        cid = cont["id"]
        t0 = time.time()
        while time.time() - t0 < 600:
            st = self._call("GET", cid, fields="status_code,status")
            if st.get("status_code") == "FINISHED":
                break
            if st.get("status_code") in ("ERROR", "EXPIRED"):
                raise PlatformError(f"Instagram не принял видео: {st.get('status')}", "content")
            time.sleep(15)
        else:
            raise PlatformError("Instagram обрабатывает видео слишком долго", "temp")
        pub = self._call("POST", f"{uid}/media_publish", creation_id=cid)
        mid = pub["id"]
        link = self._call("GET", mid, fields="permalink").get("permalink")
        return {"status": "posted", "video_id": mid, "url": link, "privacy": "public"}

    def list_videos(self) -> list[dict]:
        uid = self.uid()
        out, after = [], None
        for _ in range(4):
            params = {"fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,thumbnail_url",
                      "limit": 50}
            if after:
                params["after"] = after
            js = self._call("GET", f"{uid}/media", **params)
            for m in js.get("data", []):
                if m.get("media_product_type") != "REELS":
                    continue
                import datetime as dt
                ts = int(dt.datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").timestamp())
                v = {"id": m["id"], "title": (m.get("caption") or "")[:120], "description": (m.get("caption") or "")[:400],
                     "create_time": ts, "url": m.get("permalink"), "cover": m.get("thumbnail_url"),
                     "views": 0, "likes": int(m.get("like_count") or 0), "comments": int(m.get("comments_count") or 0),
                     "shares": 0}
                if time.time() - ts < 45 * 86400:
                    self._insights(v)
                out.append(v)
            after = ((js.get("paging") or {}).get("cursors") or {}).get("after")
            if not after or not (js.get("paging") or {}).get("next"):
                break
        return out

    def _insights(self, v: dict):
        for metrics in (METRICS, METRICS[:4]):  # «в разработке» метрики иногда недоступны — пробуем без них
            try:
                js = self._call("GET", f"{v['id']}/insights", metric=",".join(metrics))
                break
            except PlatformError:
                js = None
        for row in (js or {}).get("data", []):
            val = (row.get("values") or [{}])[0].get("value")
            name = row.get("name")
            if name == "views":
                v["views"] = int(val or 0)
            elif name == "shares":
                v["shares"] = int(val or 0)
            elif name == "saved":
                v["saves"] = int(val or 0)
            elif name == "reach":
                v["reach"] = int(val or 0)
            elif name == "ig_reels_avg_watch_time":
                v["avg_view_sec"] = round((val or 0) / 1000, 2)
            elif name == "reels_skip_rate":
                v["skip_rate"] = val
