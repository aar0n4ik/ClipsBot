"""Twitch: официальный Helix API (бесплатный ключ приложения) + скачивание кусков VOD."""
from __future__ import annotations

import json
import random
import re
import threading
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


# ── скачивание: свой HLS-загрузчик ──────────────────────────────
# Почему не просто yt-dlp: он читает HLS через ffmpeg последовательно, кусок за куском. Здесь сегменты
# качаются параллельно (×8–16), склеиваются локально и режутся точно по секунде. Поддерживаются
# и классические .ts-плейлисты, и fMP4 (#EXT-X-MAP — так Twitch отдаёт HEVC/AV1 записи «Enhanced
# Broadcasting»; v4 на них падал). Любой сбой → запасной путь через yt-dlp, как раньше.
_FORMATS: dict[str, tuple[float, list[dict]]] = {}
_FMT_TTL = 20 * 60
_local = threading.local()


def _http() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 (clipper)"
    return s


def _section(start: float, end: float) -> str:
    return f"*{max(0, start):.2f}-{end:.2f}"


def vod_formats(vod_id: str) -> list[dict]:
    """HLS-варианты записи (ссылки на плейлисты) через yt-dlp -J. Кэш на 20 минут — ссылки подписаны."""
    hit = _FORMATS.get(vod_id)
    if hit and time.time() - hit[0] < _FMT_TTL:
        return hit[1]
    js = json.loads(run(["yt-dlp", "-J", "--no-warnings", f"https://www.twitch.tv/videos/{vod_id}"],
                        timeout=300, quiet=True).stdout)
    out = []
    for f in js.get("formats") or []:
        if "m3u8" not in str(f.get("protocol", "")) or not f.get("url"):
            continue
        out.append({"id": str(f.get("format_id", "")), "url": f["url"], "height": f.get("height") or 0,
                    "fps": f.get("fps") or 0, "vcodec": str(f.get("vcodec") or ""), "acodec": str(f.get("acodec") or "")})
    if not out:
        raise RuntimeError("yt-dlp не вернул HLS-варианты записи")
    _FORMATS[vod_id] = (time.time(), out)
    return out


def pick_format(formats: list[dict], audio_only: bool = False, max_height: int | None = None) -> dict:
    if audio_only:
        aud = [f for f in formats if f["vcodec"] in ("none", "") and f["id"].lower().startswith("audio")] or \
              [f for f in formats if f["vcodec"] == "none"]
        if aud:
            return aud[0]
        return min((f for f in formats if f["height"]), key=lambda f: f["height"])  # нет отдельного звука — самое лёгкое видео
    vids = [f for f in formats if f["height"] and f["vcodec"] != "none"]
    if max_height:
        vids = [f for f in vids if f["height"] <= max_height] or sorted(vids, key=lambda f: f["height"])[:1]
    if not vids:
        raise RuntimeError("нет видео-вариантов записи")
    avc = lambda f: 1 if (f["vcodec"].startswith("avc") or f["vcodec"] in ("", "h264")) else 0  # H.264 декодируется быстрее
    return max(vids, key=lambda f: (f["height"], min(f["fps"] or 30, 60), avc(f)))


def parse_m3u8(text: str, base: str) -> tuple[str | None, list[tuple[float, float, str]]]:
    """→ (init-сегмент fMP4 или None, [(начало, длина, url)])."""
    if "#EXT-X-BYTERANGE" in text:
        raise RuntimeError("плейлист с BYTERANGE — отдаю yt-dlp")
    init, segs, pos, dur = None, [], 0.0, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m and init is None:
                init = urljoin(base, m.group(1))
        elif line.startswith("#EXTINF:"):
            dur = float(line[len("#EXTINF:"):].split(",")[0])
        elif line and not line.startswith("#") and dur is not None:
            segs.append((pos, dur, urljoin(base, line)))
            pos += dur
            dur = None
    return init, segs


def fetch_range(playlist_url: str, start: float, end: float, raw: Path, workers: int = 12) -> tuple[Path, float]:
    """Скачать сегменты, покрывающие [start, end), параллельно. → (файл, сдвиг: где start внутри файла)."""
    text = _http().get(playlist_url, timeout=30).text
    init, segs = parse_m3u8(text, playlist_url)
    need = [(s, d, u) for s, d, u in segs if s + d > start and s < end]
    if not need:
        raise RuntimeError(f"в плейлисте нет сегментов для {start:.0f}-{end:.0f} с")

    def fetch(u: str) -> bytes:
        last = None
        for attempt in range(4):
            try:
                r = _http().get(u, timeout=60)
                if r.status_code == 200 and r.content:
                    return r.content
                last = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last = str(e)[:120]
            time.sleep(0.6 * 2 ** attempt + random.random() * 0.4)
        raise RuntimeError(f"сегмент не скачался ({last})")

    urls = ([init] if init else []) + [u for _, _, u in need]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(fetch, urls))
    raw = raw.parent / (raw.name + (".mp4" if init else ".ts"))   # «x.raw.ts»: не совпадёт с итоговым x.mp4
    raw.parent.mkdir(parents=True, exist_ok=True)
    with open(raw, "wb") as f:
        for p in parts:
            f.write(p)
    return raw, max(0.0, start - need[0][0])


def download_audio(vod_id: str, start: float, end: float, out: Path) -> Path:
    """Звук куска VOD: параллельная загрузка сегментов + точная обрезка без перекодирования."""
    out.parent.mkdir(parents=True, exist_ok=True)
    dst = out.with_suffix(".m4a")
    try:
        f = pick_format(vod_formats(vod_id), audio_only=True)
        raw, lead = fetch_range(f["url"], start, end, out.with_suffix(".raw"))
        # -ss ПОСЛЕ -i: точный рез по сэмплу. «-ss до -i» на склеенном TS сдвигал начало на ~0,2 с и терял
        # ~1 с в конце (так было в v4 — субтитры чуть уезжали относительно речи)
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ss", f"{lead:.3f}", "-t", f"{end - start:.3f}",
                 "-map", "0:a:0", "-c", "copy", str(dst)], timeout=600, check=False)
        if r.returncode != 0:  # кодек не кладётся в m4a как есть — перекодируем звук (дёшево)
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ss", f"{lead:.3f}", "-t", f"{end - start:.3f}",
                 "-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", str(dst)], timeout=900)
        raw.unlink(missing_ok=True)
        return dst
    except Exception as e:  # noqa: BLE001
        log(f"звук: свой загрузчик не справился ({str(e)[:160]}) — yt-dlp")
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    run(["yt-dlp", "-q", "--no-warnings", "--no-part", "-f", "Audio_Only/audio_only/bestaudio/worst",
         "--download-sections", _section(start, end), "-o", tmpl, f"https://www.twitch.tv/videos/{vod_id}"], timeout=3600)
    got = [p for p in out.parent.glob(out.stem + ".*") if p.suffix in (".mp4", ".ts", ".m4a", ".aac", ".mkv")
           and ".raw" not in p.name]
    if not got:
        raise RuntimeError("звук не скачался")
    return got[0]


def download_video(vod_id: str, start: float, end: float, out: Path, max_height: int | None = None) -> Path:
    """Кусок видео, начинающийся РОВНО в start (кадр в кадр): сегменты параллельно → точная перекодировка.
    max_height — лёгкая версия для ИИ; без него — исходное качество записи."""
    out.parent.mkdir(parents=True, exist_ok=True)
    dst = out.with_suffix(".mp4")
    try:
        f = pick_format(vod_formats(vod_id), max_height=max_height)
        raw, lead = fetch_range(f["url"], start, end, out.with_suffix(".raw"))
        crf, preset = ("22", "veryfast") if max_height else ("16", "veryfast")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ss", f"{lead:.3f}", "-t", f"{end - start:.3f}",
             "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(dst)], timeout=1800)
        raw.unlink(missing_ok=True)
        return dst
    except Exception as e:  # noqa: BLE001
        log(f"видео: свой загрузчик не справился ({str(e)[:160]}) — yt-dlp")
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    fmt = (f"best[height<={max_height}][fps<=60]/best[height<={max_height}]/best" if max_height
           else "best[fps<=60]/best")  # без потолка: исходное качество записи
    run(["yt-dlp", "-q", "--no-warnings", "--no-part", "-f", fmt, "--download-sections", _section(start, end),
         "--force-keyframes-at-cuts", "--merge-output-format", "mp4", "-o", tmpl, f"https://www.twitch.tv/videos/{vod_id}"], timeout=1800)
    got = [p for p in out.parent.glob(out.stem + ".*") if p.suffix in (".mp4", ".ts", ".mkv") and ".raw" not in p.name]
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
