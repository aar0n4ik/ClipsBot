"""Площадки публикации. Аккаунты описаны в config.yaml → accounts (поле platform)."""
from __future__ import annotations

from .base import Platform, PlatformError, load_tokens, save_tokens  # noqa: F401
from .instagram import Instagram
from .tiktok import TikTok
from .youtube import YouTube

REGISTRY = {"tiktok": TikTok, "youtube": YouTube, "instagram": Instagram}
LABELS = {k: v.label for k, v in REGISTRY.items()}


def platform_of(acc: dict) -> str:
    return acc.get("platform", "tiktok")


def client(store, acc: dict) -> Platform:
    return REGISTRY[platform_of(acc)](store, acc)


def accounts(cfg: dict, platform: str | None = None, enabled_only: bool = True) -> list[dict]:
    out = []
    for a in cfg.get("accounts", []):
        if enabled_only and not a.get("enabled", True):
            continue
        if platform and platform_of(a) != platform:
            continue
        out.append({**a, "platform": platform_of(a)})
    return out


def connected_platforms(cfg: dict, store) -> set[str]:
    toks = load_tokens(store) if store.read_bytes("tokens.enc") else {}
    return {platform_of(a) for a in accounts(cfg) if a["id"] in toks}


def exchange(platform: str, code: str, redirect: str) -> dict:
    from . import instagram, tiktok, youtube
    return {"tiktok": tiktok, "youtube": youtube, "instagram": instagram}[platform].exchange_code(code, redirect)
