"""Twitch: официальный Helix API (бесплатный ключ приложения) + скачивание кусков VOD."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .util import log, run

HELIX = "https://api.twitch.tv/helix"


def parse_duration(s: str) -> int:
    """'3h2m10s' -> 10930"""
    total = 0
    for num, unit in re.findall(r"(\d+)([hms])", s or ""):
        total += int(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


class Twitch:
    def __init__(self, client_id: str, client_secret: str):
        self.cid, self.secret = client_id, client_secret
        self._token: str | None = None

    def _auth(self) -> str:
        if not self._token:
            r = requests.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": self.cid, "client_secret": self.secret, "grant_type": "client_credentials"}, timeout=30)
            r.raise_for_status()
            self._token = r.json()["access_token"]
        return self._token

    def get(self, path: str, **params) -> dict:
        for attempt in range(5):
            r = requests.get(HELIX + path, params=params, timeout=30,
                             headers={"Client-Id": self.cid, "Authorization": f"Bearer {self._auth()}"})
            if r.status_code == 401:
                self._token = None
                continue
            if r.status_code in (429, 500, 502, 503):
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def user(self, login: str) -> dict:
        data = self.get("/users", login=login).get("data", [])
        if not data:
            raise SystemExit(f"Twitch-пользователь '{login}' не найден — проверь twitch_login в config.yaml")
        return data[0]

    def live_stream(self, user_id: str) -> dict | None:
        data = self.get("/streams", user_id=user_id).get("data", [])
        return data[0] if data else None

    def archives(self, user_id: str, first: int = 5) -> list[dict]:
        vods = self.get("/videos", user_id=user_id, type="archive", first=first).get("data", [])
        for v in vods:
            v["duration_sec"] = parse_duration(v.get("duration", ""))
        return vods

    def clips(self, broadcaster_id: str, started_at: str, ended_at: str, limit: int = 300) -> list[dict]:
        """Клипы, которые сделали зрители. vod_offset = где в VOD этот момент."""
        out, cursor = [], None
        while len(out) < limit:
            params = dict(broadcaster_id=broadcaster_id, started_at=started_at, ended_at=ended_at, first=100)
            if cursor:
                params["after"] = cursor
            js = self.get("/clips", **params)
            out += js.get("data", [])
            cursor = (js.get("pagination") or {}).get("cursor")
            if not cursor:
                break
        return out


# ── скачивание ──────────────────────────────────────────────────
def _section(start: float, end: float) -> str:
    return f"*{max(0, start):.2f}-{end:.2f}"


def download_audio(vod_id: str, start: float, end: float, out: Path) -> Path:
    """Только звук куска VOD (дёшево: ~70 МБ/час). Если audio-only нет — берём самое лёгкое видео."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    run(["yt-dlp", "-q", "--no-warnings", "--no-part", "-f", "Audio_Only/audio_only/bestaudio/worst",
         "--download-sections", _section(start, end), "--force-keyframes-at-cuts", "-o", tmpl,
         f"https://www.twitch.tv/videos/{vod_id}"], timeout=3600)
    got = sorted(out.parent.glob(out.stem + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    if not got:
        raise RuntimeError("yt-dlp ничего не скачал")
    return got[0]


def download_video(vod_id: str, start: float, end: float, out: Path, max_height: int = 1080) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    fmt = f"best[height<={max_height}][fps<=60]/best[height<={max_height}]/best"
    run(["yt-dlp", "-q", "--no-warnings", "--no-part", "-f", fmt, "--download-sections", _section(start, end),
         "--force-keyframes-at-cuts", "--merge-output-format", "mp4", "-o", tmpl, f"https://www.twitch.tv/videos/{vod_id}"], timeout=1800)
    got = [p for p in out.parent.glob(out.stem + ".*") if p.suffix in (".mp4", ".ts", ".mkv")]
    if not got:
        raise RuntimeError("yt-dlp не скачал видео")
    return got[0]


# ── чат ─────────────────────────────────────────────────────────
def download_chat(vod_id: str, start: float, end: float, out: Path, cli: str = "TwitchDownloaderCLI") -> list[dict]:
    """Возвращает [{t: секунда_VOD, user, text, emotes}] . Если чат не скачался — пустой список (не падаем)."""
    try:
        run([cli, "chatdownload", "--id", vod_id, "-b", str(int(start)), "-e", str(int(end) + 30),
             "-o", str(out)], timeout=1800)
        js = json.loads(out.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — чат опционален
        log(f"⚠️ чат не скачался: {str(e)[:300]}")
        return []
    msgs = []
    for c in js.get("comments", []):
        m = c.get("message") or {}
        emotes = [f.get("text", "") for f in (m.get("fragments") or []) if f.get("emoticon")]
        msgs.append({
            "t": float(c.get("content_offset_seconds", 0)),
            "user": (c.get("commenter") or {}).get("display_name", ""),
            "text": m.get("body", ""),
            "emotes": emotes,
        })
    log(f"чат: {len(msgs)} сообщений")
    return msgs
