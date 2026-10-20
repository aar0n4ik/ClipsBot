"""Готовые mp4 храним как файлы GitHub Release (бесплатно, до 2 ГБ на файл) — не раздуваем git.
После публикации в TikTok файл удаляется."""
from __future__ import annotations

from pathlib import Path

from .util import log, run

TAG = "clips"


def ensure_release():
    r = run(["gh", "release", "view", TAG], check=False, quiet=True)
    if r.returncode != 0:
        run(["gh", "release", "create", TAG, "--title", "Clip storage (auto)", "--prerelease",
             "--notes", "Временное хранилище готовых клипов. Файлы удаляются после публикации."], check=False)


def upload(path: Path) -> str:
    ensure_release()
    run(["gh", "release", "upload", TAG, str(path), "--clobber"], timeout=900)
    return path.name


def download(name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run(["gh", "release", "download", TAG, "-p", name, "-D", str(out_dir), "--clobber"], timeout=900)
    return out_dir / name


def delete(name: str):
    r = run(["gh", "release", "delete-asset", TAG, name, "-y"], check=False, quiet=True)
    if r.returncode != 0:
        log(f"не удалось удалить ассет {name}: {r.stderr[-200:]}")


def public_url(name: str) -> str:
    """Прямая ссылка на файл релиза (Instagram скачивает видео сам). Разворачиваем редирект GitHub,
    чтобы отдать конечный адрес файла; если не вышло — отдаём обычную ссылку."""
    import os

    import requests
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = f"https://github.com/{repo}/releases/download/{TAG}/{name}"
    try:
        r = requests.head(url, allow_redirects=False, timeout=20)
        if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
            return r.headers["Location"]
    except requests.RequestException:
        pass
    return url


def list_assets() -> list[dict]:
    import json
    r = run(["gh", "release", "view", TAG, "--json", "assets"], check=False, quiet=True)
    try:
        return json.loads(r.stdout or "{}").get("assets", [])
    except json.JSONDecodeError:
        return []
