"""YouTube Shorts: Data API v3 (загрузка + статистика), Analytics API (удержание).

По документации (2026): videos.insert — 1 единица из отдельной квоты «Video Uploads» (100 загрузок/сутки),
ролики непроверенных проектов НЕ прячутся в приват. Вертикальное видео до 3 минут = Short.
Важно: OAuth-приложение Google в статусе Testing выдаёт refresh-токены на 7 дней —
поэтому в инструкции его переводят в «In production» (непроверенное приложение, для себя это нормально).
"""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from .base import Platform, PlatformError, http

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
          "https://www.googleapis.com/auth/yt-analytics.readonly")


def exchange_code(code: str, redirect_uri: str) -> dict:
    r = http("POST", TOKEN_URL, data={"code": code, "client_id": os.environ["YT_CLIENT_ID"],
                                      "client_secret": os.environ["YT_CLIENT_SECRET"],
                                      "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=30)
    js = r.json()
    if "refresh_token" not in js:
        raise PlatformError(f"OAuth Google: {js} (нужен prompt=consent и access_type=offline)", "auth")
    return {"platform": "youtube", "access_token": js["access_token"], "refresh_token": js["refresh_token"],
            "scope": js.get("scope"), "expires_at": int(time.time()) + int(js.get("expires_in", 3600)) - 120,
            "issued_at": int(time.time())}


class YouTube(Platform):
    name, label = "youtube", "YouTube Shorts"

    def refresh(self, force: bool = False):
        t = self.tok
        if force or time.time() >= t["expires_at"]:
            r = http("POST", TOKEN_URL, data={"client_id": os.environ["YT_CLIENT_ID"],
                                              "client_secret": os.environ["YT_CLIENT_SECRET"],
                                              "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
            js = r.json()
            if "access_token" not in js:
                raise PlatformError(f"Google не обновил токен: {js.get('error')} — подключи YouTube заново "
                                    "(и проверь, что OAuth-приложение в статусе In production)", "auth")
            t.update(access_token=js["access_token"], expires_at=int(time.time()) + int(js.get("expires_in", 3600)) - 120)
            self.save()

    def _h(self) -> dict:
        self.refresh()
        return {"Authorization": f"Bearer {self.tok['access_token']}"}

    def _get(self, url: str, **params) -> dict:
        r = http("GET", url, params=params, headers=self._h(), timeout=60)
        js = r.json()
        if r.status_code != 200:
            reason = ((js.get("error") or {}).get("errors") or [{}])[0].get("reason", "")
            kind = "quota" if "quota" in reason.lower() else "auth" if r.status_code in (401, 403) else "temp"
            raise PlatformError(f"YouTube {r.status_code}: {reason or js}", kind)
        return js

    def whoami(self) -> dict:
        js = self._get(f"{API}/channels", part="snippet,contentDetails", mine="true")
        it = (js.get("items") or [{}])[0]
        return {"display_name": (it.get("snippet") or {}).get("title"), "channel_id": it.get("id"),
                "uploads": ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")}

    def publish(self, path: Path, target: dict, cfg: dict, clip: dict) -> dict:
        ycfg = cfg["posting"].get("youtube") or {}
        meta = {"snippet": {"title": target.get("title", "")[:100], "description": target.get("description", "")[:4900],
                            "tags": (target.get("tags") or [])[:15], "categoryId": str(ycfg.get("category_id", "24")),
                            "defaultLanguage": "ru", "defaultAudioLanguage": "ru"},
                "status": {"privacyStatus": ycfg.get("privacy", "public"), "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": False, "embeddable": True}}
        size = path.stat().st_size
        r = http("POST", UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=meta, timeout=60,
                 headers={**self._h(), "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        if r.status_code != 200 or "Location" not in r.headers:
            js = r.json() if r.content else {}
            reason = ((js.get("error") or {}).get("errors") or [{}])[0].get("reason", r.text[:200])
            kind = "quota" if "quota" in str(reason).lower() or "uploadLimit" in str(reason) else "auth" if r.status_code in (401, 403) else "temp"
            raise PlatformError(f"YouTube init {r.status_code}: {reason}", kind)
        with open(path, "rb") as f:
            up = http("PUT", r.headers["Location"], data=f, timeout=1800,
                      headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
        if up.status_code not in (200, 201):
            raise PlatformError(f"YouTube upload {up.status_code}: {up.text[:200]}", "temp")
        vid = up.json()["id"]
        return {"status": "posted", "video_id": vid, "url": f"https://youtube.com/shorts/{vid}",
                "privacy": meta["status"]["privacyStatus"]}

    def list_videos(self) -> list[dict]:
        me = self.tok.get("user") or {}
        uploads = me.get("uploads") or self.whoami().get("uploads")
        ids, token = [], None
        for _ in range(4):
            js = self._get(f"{API}/playlistItems", part="contentDetails", playlistId=uploads, maxResults=50,
                           **({"pageToken": token} if token else {}))
            ids += [i["contentDetails"]["videoId"] for i in js.get("items", [])]
            token = js.get("nextPageToken")
            if not token:
                break
        out = []
        for i in range(0, len(ids), 50):
            js = self._get(f"{API}/videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
            for v in js.get("items", []):
                st, sn = v.get("statistics", {}), v.get("snippet", {})
                ts = int(dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).timestamp())
                out.append({"id": v["id"], "title": sn.get("title", ""), "description": (sn.get("description") or "")[:400],
                            "create_time": ts, "url": f"https://youtube.com/shorts/{v['id']}",
                            "cover": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url"),
                            "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                            "comments": int(st.get("commentCount", 0)), "shares": 0})
        self._retention(out)
        return out

    def _retention(self, videos: list[dict]):
        """Средний % досмотра — прямой сигнал качества хука/монтажа (данные приходят с задержкой ~2 дня)."""
        mature = [v for v in videos if v["create_time"] < time.time() - 2 * 86400][:200]
        for i in range(0, len(mature), 50):
            chunk = mature[i:i + 50]
            try:
                js = self._get(ANALYTICS, ids="channel==MINE", startDate="2020-01-01",
                               endDate=dt.date.today().isoformat(), metrics="views,averageViewDuration,averageViewPercentage",
                               dimensions="video", filters="video==" + ",".join(v["id"] for v in chunk), maxResults=50)
            except PlatformError:
                return
            cols = [c["name"] for c in js.get("columnHeaders", [])]
            for row in js.get("rows", []) or []:
                rec = dict(zip(cols, row))
                for v in chunk:
                    if v["id"] == rec.get("video"):
                        v["avg_view_pct"] = rec.get("averageViewPercentage")
                        v["avg_view_sec"] = rec.get("averageViewDuration")
