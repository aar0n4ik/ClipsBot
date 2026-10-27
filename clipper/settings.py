"""Настройки из дашборда (ветка data → control/settings.json) и выключатели (control/switches.json).

config.yaml — только стартовые значения. Всё, что владелец меняет в дашборде, лежит в ветке data
и накладывается поверх при каждом запуске. Неизвестные ключи и мусор отбрасываются, числа зажимаются
в безопасные границы, поэтому кривая запись из браузера не может сломать бота.
"""
from __future__ import annotations

from .store import Store

SETTINGS = "control/settings.json"
SWITCHES = "control/switches.json"

# ключ → (по умолчанию, тип/границы, куда в cfg)
SCHEMA = {
    # отбор
    "quality.make_min": (7, (5, 10), "quality.make_min"),          # с какой финальной оценки клип вообще монтируется
    "quality.post_min": (7, (5, 10), "quality.post_min"),          # с какой оценки публикуется
    "quality.max_per_chunk": (2, (1, 10), "quality.max_per_chunk"),  # сколько клипов максимум из куска (1 ч) стрима
    "quality.exceptional": (9, (7, 10), "quality.exceptional"),    # такой момент берём всегда, сверх лимитов
    "ai.scout_audio": (True, bool, "ai.scout_audio"),              # Gemini слушает весь кусок стрима целиком
    "ai.video_review": (True, bool, "ai.video_review"),            # Gemini смотрит каждый финалист
    "ai.video_model": ("gemini-4-argon", ("gemini-4-argon", "gemini-3.8-flash"), "ai.video_model"),
    "ai.planner": (True, bool, "ai.planner"),                      # ИИ-продюсер решает, что и когда выкладывать
    "ai.planner_model": ("gemini-4-argon", ("gemini-4-argon", "gemini-3.8-flash"), "ai.planner_model"),
    "ai.second_opinion": (True, bool, "ai.second_opinion"),
    "ai.proofread": (True, bool, "ai.proofread"),                  # ИИ слушает звук и правит ошибки распознавания        # клип ровно на пороге — второй независимый просмотр
    "transcribe.engine": ("auto", ("auto", "gemini", "whisper"), "transcribe.engine"),  # облако Gemini / локальный Whisper
    # монтаж
    "clips.min_seconds": (10, (6, 30), "clips.min_seconds"),
    "clips.max_seconds": (175, (20, 175), "clips.max_seconds"),  # потолок площадок; ИИ держит коротко
    "clips.trim_silence": (True, bool, "clips.trim_silence"),
    "clips.trim_gap_seconds": (1.2, (0.6, 4.0), "clips.trim_gap_seconds"),
    "clips.follow_subject": (False, bool, "clips.follow_subject"),
    # запас
    "quality.reserve_target": (8, (0, 60), "quality.reserve_target"),   # с этого размера банка планка отбора +1
    "quality.reserve_max": (16, (1, 120), "quality.reserve_max"),       # выше — +2: монтируем только сильнее лежащего
    # публикация
    "posting.daily_max": (4, (0, 12), "posting.daily_max"),        # релизов в сутки в день с эфиром (одинаково на всех площадках)
    "posting.offday_max": (2, (0, 12), "posting.offday_max"),      # в день без эфира — из запаса, но меньше
    "posting.daily_min": (1, (0, 6), "posting.daily_min"),         # если есть хоть что-то достойное — хотя бы столько
    "posting.min_gap_minutes": (180, (20, 600), "posting.min_gap_minutes"),
    "posting.hot_now": (True, bool, "posting.hot_now"),            # сильный клип во время эфира — сразу
    "platforms.tiktok": (True, bool, "platforms.tiktok"),
    "platforms.youtube": (True, bool, "platforms.youtube"),
    "platforms.instagram": (True, bool, "platforms.instagram"),
}

SWITCH_KEYS = ("process", "post", "stats")  # True = остановлено


def _coerce(val, spec, default):
    if spec is bool:
        return bool(val) if isinstance(val, (bool, int)) else default
    if spec == "hours":
        if not isinstance(val, list):
            return default
        return sorted({int(h) for h in val if isinstance(h, (int, float)) and 0 <= int(h) <= 23})
    if isinstance(spec, tuple) and spec and isinstance(spec[0], str):
        return val if val in spec else default
    if isinstance(spec, tuple):
        lo, hi = spec
        try:
            x = float(val)
        except (TypeError, ValueError):
            return default
        x = min(hi, max(lo, x))
        return int(round(x)) if isinstance(default, int) and not isinstance(default, bool) else round(x, 2)
    return default


def _cfg_get(cfg: dict | None, path: str):
    cur = cfg or {}
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def load(store: Store, cfg: dict | None = None) -> dict:
    """Значения: из дашборда → иначе из config.yaml → иначе встроенные по умолчанию."""
    raw = store.read_json(SETTINGS, {}) or {}
    flat = raw.get("values", raw) if isinstance(raw, dict) else {}
    out = {}
    for k, (default, spec, path) in SCHEMA.items():
        base = _cfg_get(cfg, path)
        if k.startswith("platforms.") and cfg is not None:
            base = bool((cfg.get("platforms") or {}).get(k.split(".")[1], 1))
        base = default if base is None else _coerce(base, spec, default)
        out[k] = _coerce(flat.get(k, base), spec, base)
    return out


def apply(cfg: dict, store: Store) -> dict:
    """Наложить настройки дашборда на cfg (на месте) и вернуть их."""
    vals = load(store, cfg)
    for k, (_, _, path) in SCHEMA.items():
        cur = cfg
        keys = path.split(".")
        for p in keys[:-1]:
            cur = cur.setdefault(p, {})
        cur[keys[-1]] = vals[k]
    cfg["platforms"] = {p: 1 for p in ("tiktok", "youtube", "instagram") if vals[f"platforms.{p}"]}
    cfg["_settings"] = vals
    return vals


# Смена значений по умолчанию для тех, кто их не трогал: если в дашборде стоит СТАРОЕ значение по умолчанию —
# ставим новое и пишем в журнал решений. Выполняется один раз (метка в status/migrations.json).
MIGRATIONS = {
    "v5_cadence": ({"posting.daily_max": (4, 5), "posting.min_gap_minutes": (90, 120), "quality.max_per_chunk": (4, 3),
                    "clips.max_seconds": (59, 175)},
                   "Новый ритм v5: до 5 релизов в сутки (было 4), пауза между релизами 2 ч (было 1,5 ч), "
                   "до 3 клипов из часа стрима (куски стали по 1 ч), длина без жёсткого потолка в минуту — "
                   "ИИ держит коротко, а длинный ролик проходит отдельную проверку. Основание — данные Buffer/vidIQ 2025–2026: "
                   "больше качественных роликов = больше шансов на выстрел без потери охвата каждого"),
    "v6_reserve": ({"posting.daily_max": (5, 4), "posting.min_gap_minutes": (120, 180), "quality.max_per_chunk": (3, 2)},
                   "Ритм v6: 4 релиза в сутки в день с эфиром и 2 в день без эфира (было 5 всегда), пауза между "
                   "релизами 3 ч (было 2 ч), до 2 клипов из часа стрима (было 3). Ночных часов больше нет — "
                   "расписание строится только по активности аудитории. Что не влезло в день, не пропадает: "
                   "лежит в запасе со сроком годности. Основание: TikTok рекомендует 1–4 поста в сутки и паузу "
                   "3–4 часа, чтобы ролики не отбирали друг у друга первый показ; у Shorts жёсткого лимита нет, "
                   "но ровный ритм даёт больше, чем залп"),
}


def migrate(store: Store) -> list[str]:
    from . import decisions
    done = store.read_json("status/migrations.json", []) or []
    raw = store.read_json(SETTINGS, None)
    applied = []
    for name, (changes, why) in MIGRATIONS.items():
        if name in done:
            continue
        if isinstance(raw, dict):
            vals = raw.get("values") if isinstance(raw.get("values"), dict) else raw
            hit = {k: new for k, (old, new) in changes.items() if k in vals and vals[k] == old}
            if hit:
                before = {k: vals[k] for k in hit}
                vals.update(hit)
                store.write_json(SETTINGS, raw)
                decisions.record(store, "settings", why, before=before, after=hit, reversible=False)
        done.append(name)
        applied.append(name)
    if applied:
        store.write_json("status/migrations.json", done)
    return applied


def switches(store: Store) -> dict:
    s = store.read_json(SWITCHES, {}) or {}
    return {k: bool(s.get(k)) for k in SWITCH_KEYS} | {"at": s.get("at"), "note": s.get("note", "")}


def stopped(store: Store, what: str) -> bool:
    return switches(store).get(what, False)
