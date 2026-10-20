"""Загрузка конфига + пути. Всё, что можно переопределить, берётся из env."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
WORK_DIR = Path(os.environ.get("WORK_DIR", ROOT / "work"))
FONTS_DIR = Path(os.environ.get("FONTS_DIR", ROOT / "fonts"))

DEFAULT_MONEY = {"rate_per_1000": 1.0, "currency": "USD", "payout_min": 20, "payouts": []}


def load_config(path: Path | None = None) -> dict:
    path = path or Path(os.environ.get("CLIPPER_CONFIG", ROOT / "config.yaml"))
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["money"] = load_money(cfg.get("money"))
    return cfg


def load_money(fallback: dict | None = None) -> dict:
    """Ставка и выплаты лежат в непубличной переменной репозитория MONEY_CONFIG (YAML или JSON)."""
    money = dict(DEFAULT_MONEY)
    if fallback:
        money.update(fallback)
    raw = os.environ.get("MONEY_CONFIG", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            money.update(parsed)
    money["payouts"] = money.get("payouts") or []
    return money


def env(name: str, required: bool = True, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise SystemExit(f"Не задан секрет/переменная окружения {name}")
    return val
