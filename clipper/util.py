from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def local_date(ts: dt.datetime, tz: str) -> str:
    return ts.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def run(cmd: list[str], timeout: int | None = None, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        log("$", " ".join(str(c) for c in cmd)[:300])
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-1500:]
        raise RuntimeError(f"Команда упала ({r.returncode}): {cmd[0]}\n{tail}")
    return r


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def ffprobe_json(path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], quiet=True)
    return json.loads(r.stdout)


def video_dims(path) -> tuple[int, int, float]:
    info = ffprobe_json(path)
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = int(s["width"]), int(s["height"])
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                rot = int(sd.get("rotation", 0) or 0)
            if abs(rot) in (90, 270):
                w, h = h, w
            dur = float(info.get("format", {}).get("duration", 0) or 0)
            return w, h, dur
    raise RuntimeError(f"Нет видеодорожки в {path}")


def fmt_hms(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def die(msg: str):
    log("❌", msg)
    sys.exit(1)
