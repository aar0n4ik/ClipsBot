"""Twitch: официальный Helix API (бесплатный ключ приложения) + скачивание кусков VOD."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

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


def _hls_url(vod_id: str, fmt: str) -> str:
    """Ссылка на медиа-плейлист нужного формата (yt-dlp только получает URL, ничего не качает)."""
    out = run(["yt-dlp", "-g", "-f", fmt, f"https://www.twitch.tv/videos/{vod_id}"], timeout=300).stdout.split()
    urls = [u for u in out if u.startswith("http")]
    if len(urls) != 1:
        raise RuntimeError("формат состоит из нескольких потоков — прямая склейка не поддержана")
    return urls[0]


def hls_fetch(vod_id: str, start: float, end: float, fmt: str, raw: Path, workers: int = 8) -> float:
    """Сегменты HLS качаются параллельно и склеиваются в один .ts без перекодирования.
    ffmpeg-загрузчик читает такой плейлист в темпе эфира (~1x), параллельная загрузка — в сотни раз быстрее.
    Возвращает время VOD (с), с которого начинается файл: это начало первого сегмента, оно может быть раньше `start`."""
    raw.parent.mkdir(parents=True, exist_ok=True)
    url = _hls_url(vod_id, fmt)
    s = requests.Session()
    pl = s.get(url, timeout=30).text
    if "#EXT-X-MAP" in pl:
        raise RuntimeError("fMP4-плейлист: склейка сегментов не поддержана")
    segs, pos, dur, first_start = [], 0.0, None, None
    for line in pl.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            dur = float(line[len("#EXTINF:"):].split(",")[0])
        elif line and not line.startswith("#") and dur is not None:
            if pos + dur > start and pos < end:
                if first_start is None:
                    first_start = pos
                segs.append(urljoin(url, line))
            pos += dur
            dur = None
            if pos >= end:
                break
    if not segs:
        raise RuntimeError(f"в плейлисте нет сегментов для {start:.0f}-{end:.0f} с")

    def fetch(u: str) -> bytes:
        r = None
        for _ in range(3):
            r = s.get(u, timeout=60)
            if r.status_code == 200:
                return r.content
            time.sleep(1)
        raise RuntimeError(f"сегмент не скачался ({r.status_code})")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(fetch, segs))   # порядок сегментов сохраняется
    with open(raw, "wb") as f:
        for p in parts:
            f.write(p)
    return float(first_start)


def download_audio(vod_id: str, start: float, end: float, out: Path) -> Path:
    """Звук куска VOD: параллельные сегменты, потом точная обрезка по времени (atrim, как и в рендере).
    Звук нужен только для анализа и расшифровки, поэтому пережатие в AAC 96k здесь ни на что не влияет."""
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".raw.ts")
    first = hls_fetch(vod_id, start, end, "Audio_Only/audio_only/bestaudio/worst", raw)
    a0 = max(0.0, start - first)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vn",
         "-af", f"atrim=start={a0:.3f}:end={a0 + (end - start):.3f},asetpts=PTS-STARTPTS",
         "-c:a", "aac", "-b:a", "96k", str(out)], timeout=1200)
    raw.unlink(missing_ok=True)
    return out


def video_format(max_height: int | None = None) -> str:
    """Формат видео VOD. Без потолка по высоте берём лучшее, что отдаёт Twitch (исходное качество стрима)."""
    if max_height:
        return f"best[height<={max_height}][fps<=60]/best[height<={max_height}]/best"
    return "best[fps<=60]/best"


def download_video(vod_id: str, start: float, end: float, out: Path, max_height: int | None = None) -> tuple[Path, float]:
    """Видео куска VOD в исходном качестве (без перекодирования). Возвращает (файл, время VOD, с которого он начинается):
    файл может начинаться чуть раньше `start` (с начала сегмента), вызывающий код учитывает это сдвигом.
    Если прямая загрузка сегментов не вышла — запасной путь через yt-dlp (старт точный)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = video_format(max_height)
    try:
        raw = out.with_suffix(".ts")
        first = hls_fetch(vod_id, start, end, fmt, raw)
        return raw, first
    except Exception as e:  # noqa: BLE001
        log(f"прямая загрузка видео не вышла ({str(e)[:140]}), запасной путь через yt-dlp")
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    run(["yt-dlp", "-q", "--no-warnings", "--no-part", "-f", fmt, "--download-sections", _section(start, end),
         "--force-keyframes-at-cuts", "--merge-output-format", "mp4", "-o", tmpl, f"https://www.twitch.tv/videos/{vod_id}"],
        timeout=1800)
    got = [p for p in out.parent.glob(out.stem + ".*") if p.suffix in (".mp4", ".ts", ".mkv")]
    if not got:
        raise RuntimeError("yt-dlp не скачал видео")
    return got[0], max(0.0, start)


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
