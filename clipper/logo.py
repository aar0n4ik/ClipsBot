"""Логотип для плашки канала.

Частая проблема (она и давала «синюю полоску»): картинка логотипа скачана как JPEG/PNG,
у которого «прозрачность» нарисована шахматкой. Тогда в ролик вставляется серый квадрат.
Здесь фон убирается автоматически:
  • настоящая альфа-маска — используем как есть;
  • иначе ищем фон, связанный с краями картинки (шахматка, белый, однотонный), и вырезаем его;
  • круглые логотипы получают идеально гладкий край (антиалиасинг по окружности).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import ROOT

CANDIDATES = ("logo.png", "logo.webp", "logo.jpg", "logo.jpeg", "twitch.png", "twitch.jpg", "twitch-logo.png")


def find_logo(cfg: dict) -> Path | None:
    br = cfg.get("branding") or {}
    if br.get("logo"):
        p = ROOT / br["logo"]
        if p.exists():
            return p
    d = ROOT / "assets"
    if d.exists():
        for name in CANDIDATES:
            if (d / name).exists():
                return d / name
        imgs = sorted([p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
        if imgs:  # любые картинки: берём самую «квадратную» (круглый значок лучше длинного логотипа)
            def squareness(p):
                try:
                    w, h = Image.open(p).size
                    return abs(1 - w / h)
                except Exception:  # noqa: BLE001
                    return 9
            return min(imgs, key=squareness)
    return None


def _trim(im: Image.Image) -> Image.Image:
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(bbox) if bbox else im


@lru_cache(maxsize=8)
def load_clean_logo(path: str) -> Image.Image:
    from scipy.ndimage import binary_fill_holes, label

    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        a = np.asarray(rgba)[..., 3]
        if (a < 250).mean() > 0.02:  # есть реальная прозрачность
            return _trim(rgba)
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    h, w, _ = rgb.shape
    mx, mn = rgb.max(2), rgb.min(2)
    sat = (mx - mn) / (mx + 1e-3)
    cand = (sat < 0.12) & (mx > 160)  # белый / светло-серый (шахматка)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    for c in np.unique((border // 24).astype(int), axis=0)[:6] * 24 + 12:  # однотонный фон любого цвета
        cand |= np.abs(rgb - c).sum(2) < 54
    lab, _ = label(cand)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    fg = ~np.isin(lab, list(edge))
    fg = binary_fill_holes(fg)
    lab2, n = label(fg)
    if n > 1:
        sizes = np.bincount(lab2.ravel())
        sizes[0] = 0
        fg = lab2 == sizes.argmax()
    ys, xs = np.nonzero(fg)
    if len(xs) < 50:
        return _trim(im.convert("RGBA"))
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    r = ((ys.max() - ys.min()) + (xs.max() - xs.min())) / 4
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(yy - cy, xx - cx)
    if fg.sum() / (np.pi * r * r) > 0.93:  # круглый значок — гладкая окружность
        alpha = np.clip(r - 1.6 - dist + 0.5, 0, 1)
    else:
        from scipy.ndimage import binary_erosion, gaussian_filter
        alpha = np.clip(gaussian_filter(binary_erosion(fg, iterations=1).astype(np.float32), 0.8) * 1.15, 0, 1)
    out = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    return _trim(Image.fromarray(out, "RGBA"))
