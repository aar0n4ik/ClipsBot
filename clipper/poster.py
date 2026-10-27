"""Публикация: ОДИН клип → ВСЕ площадки одновременно («релиз»), когда это выгодно.

Как решается «постить ли сейчас и что» (каждый час):
  1. Жёсткие правила (их не может нарушить никто, ни ИИ, ни скрипт): выключатель в дашборде, ночь аудитории,
     пауза между релизами, максимум в сутки, ошибки площадки (лимит/спам/вход) — площадка отдыхает.
  2. Пул: только клипы с финальной оценкой ≥ порога (после просмотра видео ИИ), свежие (≤ 36 ч, 9+ — до 72 ч),
     без высокого риска. Слабых клипов «для количества» нет вообще: нечего выложить — бот ждёт.
  3. ИИ-продюсер получает всю картину (очередь, что уже вышло, как заходят последние ролики, сколько слотов
     и активных часов осталось) и решает: выкладывать сейчас или ждать, и какой клип. Второй ИИ-критик проверяет
     решение. Если ИИ недоступен — то же самое делает детерминированный план.
  4. Волна: если свежий ролик набирает в разы быстрее нормы, это НЕ повод молчать (каждый ролик площадки
     оценивают отдельно, а новые зрители идут в профиль) — наоборот, разрешается +1 релиз в сутки.

Что убрано и почему: «остывание» по медиане просмотров. Оно сравнивало новые ролики со старыми (майскими)
и резало частоту на здоровом канале. Площадки не наказывают за частоту при нормальном качестве; падение
просмотров на маленьком канале — это шум и качество роликов, а не «бан». Режем только по сигналам самой
площадки (ошибки спама/лимитов) — их бот видит напрямую.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from . import health, learn, releases, schemas
from .clips import age_hours, normalize, pending_for
from .config import WORK_DIR
from .platforms import accounts as list_accounts
from .platforms import client
from .platforms.base import PlatformError
from .store import Store
from .util import log, now_utc, parse_iso


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

BRAIN = "status/brain.json"
ACCOUNT_COOLDOWN_H = {"rate": 1, "quota": 6, "spam": 24, "blocked": 24, "auth": 168}
UPLOAD_STALE_H = 3      # «выкладываю» дольше этого — раннер умер посреди публикации
# Синхрон: один клип = один релиз сразу везде, одинаковое число роликов на каждой площадке.
SYNC_WAIT_H = 3         # площадка отдыхает не дольше этого — релиз ЖДЁТ её (лучше чуть позже, но везде вместе)
SYNC_REPAIR_H = 2       # площадка не приняла ролик в момент релиза — дотягиваем её не позже чем через столько часов,
                        # дальше клип на ней пропускается навсегда (никаких «догонялок» через полдня)


# ── вспомогательное ─────────────────────────────────────────────
def _local(now: dt.datetime, tz: str) -> dt.datetime:
    return now.astimezone(ZoneInfo(tz))


def posted_today(a: dict, today: str) -> tuple[int, int]:
    """(опубликовано, отправлено в черновики) за сегодня по времени аудитории."""
    by = a.get("count_by_day", {}) or {}
    dr = a.get("drafts_by_day", {}) or {}
    total = int(by.get(today, 0))
    drafts = int(dr.get(today, 0))
    return max(0, total - drafts), drafts


def plan_hours(now_local: dt.datetime, remaining: int, weights: list[float], quiet: set[int], gap_h: float,
               last_post_local: dt.datetime | None) -> list[int]:
    hours = [h for h in range(now_local.hour, 24) if h not in quiet]
    chosen: list[int] = []
    last_h = (last_post_local.hour + last_post_local.minute / 60
              if last_post_local and last_post_local.date() == now_local.date() else None)
    for h in sorted(hours, key=lambda x: -weights[x]):
        if len(chosen) >= remaining:
            break
        if last_h is not None and h + 0.1 - last_h < gap_h:
            continue
        if all(abs(h - c) >= gap_h for c in chosen):
            chosen.append(h)
    return sorted(chosen)


def max_age(c: dict, posting: dict) -> float:
    base = float(posting.get("max_age_hours", 36))
    return max(base, 72.0) if int(c.get("score", 0)) >= 9 else base


def rank(pool: list[dict], policy: dict, recent: list[dict]) -> list[tuple[float, dict, list[str]]]:
    out = []
    cats = [r.get("category") for r in recent[:10]]
    for c in pool:
        age = age_hours(c)
        why = []
        key = float(c.get("score", 0)) * (0.85 ** (age / 24)) + 0.1 * float(c.get("signal", 0) or 0) ** 0.5
        b = learn.category_boost(policy, "all", c.get("category", "other"))
        if b:
            key += 2.0 * b
            why.append(f"тема {'заходит' if b > 0 else 'заходит хуже'} ({learn._pct(b)})")
        if c.get("live_when_made") and age <= 3:
            key += 0.6
            why.append("свежак с эфира")
        if recent:
            if recent[0].get("category") == c.get("category"):
                key -= 0.6
            share = cats.count(c.get("category")) / max(1, len(cats))
            if share > 0.4 and b <= 0.2:
                key -= 1.2 * (share - 0.4) * 5
            if any(r.get("vod_id") == c.get("vod_id") and abs(float(r.get("vod_time") or -1e9) - float(c.get("vod_time") or 0)) < 600
                   for r in recent[:2]):
                key -= 0.6
        out.append((round(key, 3), c, why))
    out.sort(key=lambda x: -x[0])
    return out


def momentum(stats: dict, now_ts: float) -> dict:
    """Волна: свежий ролик (1–12 ч) набирает ≥3× быстрее обычного для аккаунта."""
    out = {}
    for acc, A in (stats.get("accounts") or {}).items():
        vids = list((A.get("videos") or {}).values())
        sig = health.account_signals(vids, now_ts)
        base = sig.get("early_baseline") or 0
        best = None
        for v in vids:
            ct = v.get("create_time") or 0
            age_h = (now_ts - ct) / 3600
            if not 1 <= age_h <= 12 or not base:
                continue
            x = health.views_at_age(v, min(2, age_h)) or v.get("views", 0)
            ratio = (x + 1) / (base + 1)
            if ratio >= 3 and (not best or ratio > best["ratio"]):
                best = {"video": v.get("id"), "title": (v.get("title") or "")[:60], "ratio": round(ratio, 1), "views": v.get("views", 0)}
        if best:
            out[acc] = best
    return out


def first_release_at(c: dict) -> dt.datetime | None:
    """Когда клип впервые ушёл хоть на одну площадку (None — ещё никуда)."""
    ts = [p.get("posted_at") or p.get("started_at") for p in (c.get("posts") or {}).values()
          if p.get("status") in ("posted", "inbox", "inbox_stale", "processing", "uploading")]
    ts = [parse_iso(t) for t in ts if t]
    return min(ts) if ts else None


def mark_sync_skip(c: dict, plat: str, why: str):
    t = (c.get("targets") or {}).get(plat)
    if t and t.get("status", "ready") == "ready":
        t["status"] = "skipped_sync"
        t["skip_reason"] = why
        if (c.get("posts") or {}).get(plat, {}).get("status") == "retry":
            c["posts"][plat]["status"] = "skipped_sync"


def maybe_delete_asset(c: dict, name: str | None):
    """Файл общий для всех площадок: удаляем, только когда он больше никому не нужен."""
    if not name:
        return
    if any(t.get("asset") == name and pending_for(c, p) for p, t in c.get("targets", {}).items()):
        return
    releases.delete(name)


def full_caption(t: dict, posting: dict) -> str:
    tags = list(dict.fromkeys((t.get("hashtags") or []) + (posting.get("fixed_hashtags") or [])))
    return (t.get("caption", "").strip() + "\n\n" + " ".join(tags)).strip()


# ── мозг: продюсер + критик ─────────────────────────────────────
PRODUCER = """Ты — продюсер каналов с нарезками стримера (TikTok, YouTube Shorts, Instagram Reels; одно и то же видео
выходит на всех площадках одновременно). Цель — максимальный рост: просмотры, подписчики, охват, без вреда аккаунтам.
Сейчас {now_local} по времени аудитории ({tz}). Ночь аудитории: {quiet}.

Факты, на которые опирайся:
• Каждый ролик площадка оценивает отдельно по удержанию первых показов. Частота сама по себе не штрафуется;
  больше хороших роликов = больше шансов на выстрел. Слабые ролики тянут вниз удержание и доверие к аккаунту.
• Стабильность (каждый день, похожие часы) важнее рывков. Пик активности аудитории — вечер.
• Свежесть важна: клип с эфира, пока стример в эфире или только закончил, работает лучше вчерашнего.
• Если свежий ролик на волне (набирает в разы быстрее нормы) — люди идут в профиль, новый сильный ролик это подхватит.
• Не ставь подряд два ролика одной темы или с одного места стрима.

Жёсткие ограничения уже применены: в списке только клипы, которые МОЖНО выложить прямо сейчас.
Состояние:
{state}

Реши: выкладывать сейчас (post) или ждать (wait), и какой клип. Если ждёшь — объясни, чего именно ждёшь
(лучший час, более сильный клип с идущего эфира, паузу между роликами), и помни: слоты, не использованные сегодня,
сгорают, а клипы старше {max_age} ч выбрасываются. Думай как человек, который отвечает за рост канала.
Ответ строго JSON: {{"action":"post|wait","clip":"id или null","reason":"2–3 предложения по-русски"}}"""

CRITIC = """Ты — второй продюсер, проверяешь решение коллеги перед публикацией. Будь конкретен, без вежливости.
Состояние:
{state}
Решение коллеги: {proposal}
Согласен? Если нет — дай своё решение. Ответ строго JSON:
{{"agree":true,"action":"post|wait","clip":"id или null","reason":"1–2 предложения"}}"""


def _state_text(ctx: dict) -> str:
    return json.dumps(ctx, ensure_ascii=False, indent=0)[:9000]


def think(cfg: dict, ctx: dict, fallback: dict) -> dict:
    """ИИ-продюсер + ИИ-критик. Возвращает {"action","clip","reason","thoughts":[...]}. Сбой — fallback."""
    ai = cfg.get("ai") or {}
    if not ai.get("planner", True):
        return {**fallback, "by": "план"}
    try:
        from .llm import LLM
        llm = LLM(cfg["llm"]["providers"], text_chain=[ai["text_model"]] if ai.get("text_model") else None)
    except SystemExit:
        return {**fallback, "by": "план (нет ключей ИИ)"}
    model = ai.get("planner_model", "gemini-4-argon")
    posting = cfg["posting"]
    state = _state_text(ctx)
    try:
        prop = llm.chat_json_model([{"role": "user", "content": PRODUCER.format(
            now_local=ctx["now_local"], tz=posting["timezone"], quiet=", ".join(f"{h}:00" for h in posting.get("quiet_hours", [])),
            state=state, max_age=posting.get("max_age_hours", 36))}], model, max_tokens=1500,
            schema=schemas.PRODUCER, thinking="medium")
        crit = llm.chat_json([{"role": "user", "content": CRITIC.format(state=state, proposal=json.dumps(prop, ensure_ascii=False))}],
                             max_tokens=1000, schema=schemas.PRODUCER_CRITIC, thinking="low")
    except Exception as e:  # noqa: BLE001
        log(f"продюсер недоступен: {str(e)[:160]} — решаю по плану")
        return {**fallback, "by": "план (ИИ недоступен)"}
    final = prop if crit.get("agree", True) else crit
    return {"action": str(final.get("action", "wait")).lower(), "clip": final.get("clip"),
            "reason": str(final.get("reason", ""))[:400], "by": "ИИ-продюсер" + ("" if crit.get("agree", True) else " (поправил критик)"),
            "thoughts": [{"who": "продюсер", **{k: prop.get(k) for k in ("action", "clip", "reason")}},
                         {"who": "критик", **{k: crit.get(k) for k in ("agree", "action", "clip", "reason")}}]}


def deterministic(ctx: dict, ranked: list, hot: dict | None, plan: list[int], now_local: dt.datetime) -> dict:
    if not ranked:
        return {"action": "wait", "clip": None, "reason": "нет клипов нужного качества — ничего слабого не выкладываю"}
    if hot:
        return {"action": "post", "clip": hot["id"], "reason": "сильный клип с идущего эфира — свежесть важнее часа"}
    best = ranked[0][1]
    if now_local.hour in plan:
        return {"action": "post", "clip": best["id"], "reason": f"лучший час по плану ({now_local.hour}:00)"}
    soon_expire = [c for _, c, _ in ranked if c["_left_h"] <= 3]
    if soon_expire:
        return {"action": "post", "clip": soon_expire[0]["id"], "reason": "клип скоро устареет, а слот свободен"}
    if ctx["slots_left"] >= max(1, ctx["active_hours_left"]):
        return {"action": "post", "clip": best["id"], "reason": "слотов осталось столько же, сколько активных часов"}
    return {"action": "wait", "clip": None, "reason": f"жду лучший час: план {', '.join(f'{h}:00' for h in plan) or '—'}"}


# ── главный цикл ────────────────────────────────────────────────
def cmd_post(cfg: dict, store: Store, force: bool = False):
    posting = cfg["posting"]
    policy = learn.load(store, cfg)
    from . import decisions
    if decisions.apply_commands(store, policy):
        learn.save(store, policy)
    pstate = store.read_json("status/post.json", {}) or {}
    accs = pstate.setdefault("accounts", {})
    stats = store.read_json("stats.json", {}) or {}
    now = now_utc()
    tz = posting["timezone"]
    local = _local(now, tz)
    today = local.date().isoformat()
    queue = [normalize(c) for c in store.list_json("queue")]
    enabled = cfg.get("platforms") or {"tiktok": 1, "youtube": 1, "instagram": 1}
    errors: list[str] = []

    # 0) публикации, прерванные на середине (раннер умер после загрузки, но до записи результата):
    #    не повторяем сами — иначе возможен дубль на площадке. Stats свяжет ролик, если он всё-таки вышел.
    for c in queue:
        hung = [pl for pl, p in c["posts"].items() if p.get("status") == "uploading" and p.get("started_at")
                and (now - parse_iso(p["started_at"])).total_seconds() > UPLOAD_STALE_H * 3600]
        for pl in hung:
            c["posts"][pl].update(status="failed", error="публикация прервалась на середине — проверь, вышел ли ролик "
                                                         "на площадке; если нет, нажми «Повторить»")
        if hung:
            store.write_json(f"queue/{c['id']}.json", c)

    # 1) протухшие клипы: «на завтра не оставляем» (кроме 9+)
    for c in queue:
        changed = False
        for plat, t in c["targets"].items():
            if pending_for(c, plat) and age_hours(c) > max_age(c, posting):
                t["status"] = "expired"
                changed = True
        if changed:
            maybe_delete_asset(c, c.get("asset") or next((t.get("asset") for t in c["targets"].values()), None))
            store.write_json(f"queue/{c['id']}.json", c)

    # 2) какие площадки сейчас могут принять релиз
    ready: dict[str, dict] = {}
    active: dict[str, dict] = {}            # подключена, включена, не на ручной паузе
    resting: dict[str, dt.datetime] = {}    # площадка → до когда отдыхает (ошибка лимита/спама/входа)
    clients = {}
    daymax = int(posting.get("daily_max", 4))
    for acc in list_accounts(cfg):
        plat = acc["platform"]
        a = accs.setdefault(acc["id"], {"platform": plat})
        cl = client(store, acc)
        a["connected"] = cl.connected()
        pub, drafts = posted_today(a, today)
        a["today"] = {"published": pub, "drafts": drafts, "max": daymax}
        if not cl.connected():
            a["state"] = "не подключён"
            continue
        if plat not in enabled:
            a["state"] = "выключена в настройках"
            continue
        for c in queue:  # TikTok может досчитывать публикацию
            p = c["posts"].get(plat)
            if p and p.get("account") == acc["id"] and p.get("status") == "processing":
                try:
                    cl.check(p)
                    store.write_json(f"queue/{c['id']}.json", c)
                except PlatformError as e:
                    log(f"проверка публикации {c['id']}: {e}")
        paused = (policy.get("paused") or {}).get(acc["id"])
        if paused and parse_iso(paused) > now:
            a["state"] = "пауза (вручную)"   # решение владельца: остальные площадки не ждут
            continue
        active[plat] = acc
        cd = a.get("cooldown_until")
        if cd and parse_iso(cd) > now:
            a["state"] = f"отдыхает до {cd[11:16]} UTC: {a.get('cooldown_reason', '')[:120]}"
            resting[plat] = parse_iso(cd)
            continue
        a["state"] = "готова"
        ready[plat] = acc
        clients[plat] = cl

    # 3) счётчики релизов (общие для всех площадок)
    rs = pstate.setdefault("releases", {})
    by_day = {k: v for k, v in (rs.get("by_day") or {}).items() if k >= (local.date() - dt.timedelta(days=14)).isoformat()}
    rel_today = int(by_day.get(today, 0))
    last_rel = parse_iso(rs["last_at"]) if rs.get("last_at") else None
    since_min = (now - last_rel).total_seconds() / 60 if last_rel else 1e9
    gap = int(posting.get("min_gap_minutes", 90))
    quiet = set(posting.get("quiet_hours", [2, 3, 4, 5, 6]))
    waves = momentum(stats, now.timestamp())
    cap = min(int(posting.get("hard_max", 8)), daymax + (1 if waves else 0))
    slots_left = max(0, cap - rel_today)
    active_left = len([h for h in range(local.hour, 24) if h not in quiet])
    weights = learn.get(policy, "hours.youtube") or learn.get(policy, "hours.tiktok") or learn.PRIOR_HOURS
    plan = plan_hours(local, slots_left, weights, quiet, gap / 60, last_rel.astimezone(ZoneInfo(tz)) if last_rel else None)

    # 4) пул: что можно выложить прямо сейчас хотя бы на одну готовую площадку
    post_min = int((cfg.get("quality") or {}).get("post_min", 7))
    pool = []
    for c in queue:
        if c.get("status") in ("broken", "skipped", "expired"):
            continue
        plats = [p for p in ready if pending_for(c, p)]
        if not plats:
            continue
        released_at = first_release_at(c)
        posted_elsewhere = released_at is not None
        if posted_elsewhere and (now - released_at).total_seconds() > SYNC_REPAIR_H * 3600 and not c.get("force_post"):
            for p in plats:   # окно синхрона прошло: на этой площадке клип не выходит вообще, счёт остаётся равным
                mark_sync_skip(c, p, "релиз на других площадках был больше 2 ч назад — не выкладываю вразнобой")
            maybe_delete_asset(c, (c["targets"].get(plats[0]) or {}).get("asset"))
            store.write_json(f"queue/{c['id']}.json", c)
            continue
        if int(c.get("score", 0)) < post_min and not c.get("force_post"):
            continue
        if int((c.get("risk") or {}).get("level", 0)) >= 3:
            continue
        c["_plats"] = plats
        c["_left_h"] = round(max_age(c, posting) - age_hours(c), 1)
        c["_catchup"] = posted_elsewhere
        pool.append(c)
    recent = rs.get("recent", [])
    ranked = rank(pool, policy, recent)
    catchup = [c for _, c, _ in ranked if c["_catchup"]]
    # площадка отдыхает недолго → новый релиз ждёт её, чтобы ролик вышел везде одновременно
    soon = {p: t for p, t in resting.items() if (t - now).total_seconds() <= SYNC_WAIT_H * 3600}
    forced = next((c for c in pool if c.get("force_post")), None)
    hot = next((c for _, c, _ in ranked if c.get("live_when_made") and int(c.get("score", 0)) >= int(posting.get("hot_score", 8))
                and age_hours(c) <= 3 and posting.get("hot_now", True)), None)

    blocked = None
    if not ready:
        blocked = "ни одна площадка сейчас не готова"
    elif soon and not forced and not catchup:
        blocked = ("жду " + ", ".join(f"{p} (отдыхает до {t.astimezone(ZoneInfo(tz)):%H:%M})" for p, t in soon.items())
                   + " — новый клип выйдет на всех площадках одновременно")
    elif local.hour in quiet and not forced:
        blocked = f"ночь аудитории ({local.hour}:00 по {tz})"
    elif slots_left <= 0 and not forced and not catchup:
        blocked = f"сегодня уже {rel_today} релиз(ов) из {cap}"
    elif since_min < gap and not forced and not catchup:
        blocked = f"после прошлого релиза прошло {int(since_min)} мин из {gap}"

    ctx = {"now_local": local.strftime("%Y-%m-%d %H:%M"), "releases_today": rel_today, "daily_max": cap,
           "slots_left": slots_left, "active_hours_left": active_left,
           "minutes_since_last_release": None if since_min > 1e8 else int(since_min),
           "best_hours_plan": plan, "live_now": bool((store.read_json("status/live.json", {}) or {}).get("is_live")),
           "waves": waves, "platforms_ready": sorted(ready),
           "last_releases": [{"hook": r.get("hook"), "category": r.get("category"), "at": r.get("at"), "views": r.get("views")}
                             for r in recent[:5]],
           "queue": [{"id": c["id"], "score": c.get("score"), "rank": k, "category": c.get("category"),
                      "hook": c.get("overlay"), "what": (c.get("what") or c.get("why") or "")[:160],
                      "age_h": round(age_hours(c), 1), "expires_in_h": c["_left_h"], "from_live": bool(c.get("live_when_made")),
                      "duration": c.get("duration"), "platforms": c["_plats"]} for k, c, _ in ranked[:8]]}
    decision: dict
    if force and ranked:
        decision = {"action": "post", "clip": ranked[0][1]["id"], "reason": "ручной запуск «выложить сейчас»", "by": "владелец"}
    elif forced:
        decision = {"action": "post", "clip": forced["id"], "reason": "владелец нажал «Выложить сейчас»", "by": "владелец"}
    elif catchup and not blocked:
        decision = {"action": "post", "clip": catchup[0]["id"], "by": "синхрон",
                    "reason": f"дотягиваю {', '.join(catchup[0]['_plats'])}: релиз вышел на других площадках, эта не успела"}
    elif blocked:
        decision = {"action": "wait", "clip": None, "reason": blocked, "by": "правила"}
    else:
        fb = deterministic(ctx, ranked, hot, plan, local)
        decision = think(cfg, ctx, fb) if ranked else {**fb, "by": "план"}
        if decision.get("action") == "post" and decision.get("clip") not in {c["id"] for c in pool}:
            decision = {**fb, "by": "план (ИИ выбрал недоступный клип)"}
    log(f"решение: {decision['action']} {decision.get('clip') or ''} — {decision.get('reason')} [{decision.get('by')}]")

    # 5) релиз: один клип на все готовые площадки подряд
    released = []
    if decision["action"] == "post" and decision.get("clip"):
        clip = next(c for c in pool if c["id"] == decision["clip"])
        plats = list(clip["_plats"])
        was_catchup = bool(clip["_catchup"])   # починка опоздавшей площадки — не новый релиз, лимит дня не тратит
        if not was_catchup:
            for p in resting:   # отдыхает долго (лимит на сутки, бан, вход) — этот клип на ней не выйдет вообще
                if p not in plats and pending_for(clip, p):
                    mark_sync_skip(clip, p, f"{p} была недоступна в момент релиза")
        # маркер «выкладываю» сохраняется ДО загрузки: умрёт раннер посреди — следующий запуск не сделает дубль
        for plat in plats:
            clip["posts"][plat] = {**(clip["posts"].get(plat) or {}), "account": ready[plat]["id"], "status": "uploading",
                                   "started_at": _iso(now)}
        store.write_json(f"queue/{clip['id']}.json", {k: v for k, v in clip.items() if not k.startswith("_")})
        store.sync(f"post: выкладываю {clip['id']} → {', '.join(plats)}")
        files = {}
        for asset in dict.fromkeys(clip["targets"][p].get("asset") for p in plats):
            try:
                files[asset] = releases.download(asset, WORK_DIR / "post")
            except Exception as e:  # noqa: BLE001 — например, файл пропал из релиза
                files[asset] = e

        def one(plat):
            acc = ready[plat]
            return _publish_one(cfg, store, clients[plat], acc, accs[acc["id"]], clip, plat, decision, now, today, errors,
                                files.get(clip["targets"][plat].get("asset")))
        with ThreadPoolExecutor(max_workers=len(plats) or 1) as ex:   # релиз во все площадки в одну минуту
            oks = list(ex.map(one, plats))
        released = [p for p, ok in zip(plats, oks) if ok]
        for asset in dict.fromkeys(clip["targets"][p].get("asset") for p in released
                                   if clip["posts"][p].get("status") in ("posted", "inbox")):
            maybe_delete_asset(clip, asset)   # файл общий: удаляется, только когда никому больше не нужен
        clip.pop("force_post", None)
        for k in ("_plats", "_left_h", "_catchup"):
            clip.pop(k, None)
        store.write_json(f"queue/{clip['id']}.json", clip)
        if released:
            first_release = not was_catchup and not any(r.get("clip") == clip["id"] for r in recent)
            if first_release:
                by_day[today] = by_day.get(today, 0) + 1
                rs.update(last_at=_iso(now), recent=[{"clip": clip["id"], "category": clip.get("category"),
                                                      "vod_id": clip.get("vod_id"), "vod_time": clip.get("vod_time"),
                                                      "hook": clip.get("overlay"), "at": _iso(now),
                                                      "platforms": released}] + recent[:29])
    rs["by_day"] = by_day
    nxt = (now.replace(minute=7, second=0, microsecond=0) + dt.timedelta(hours=1))
    pstate.update(timezone=tz, updated_at=_iso(now), next_check=nxt.isoformat(),
                  plan={"today": [f"{h:02d}:07" for h in plan], "slots_left": max(0, cap - int(by_day.get(today, 0))),
                        "cap": cap, "releases_today": int(by_day.get(today, 0)), "waves": waves,
                        "up_next": [{"id": c["id"], "hook": c.get("overlay"), "score": c.get("score"),
                                     "expires_in_h": c.get("_left_h"), "platforms": c.get("_plats")} for _, c, _ in ranked[:5]
                                    if c["id"] != decision.get("clip")]})
    store.write_json("status/post.json", pstate)
    br = store.read_json(BRAIN, {}) or {}
    feed = br.get("feed", [])
    feed.append({"at": _iso(now), "local": ctx["now_local"], **{k: decision.get(k) for k in ("action", "clip", "reason", "by")},
                 "thoughts": decision.get("thoughts") or [], "released": released, "pool": len(pool)})
    br.update(feed=feed[-120:], last=feed[-1], context=ctx)
    store.write_json(BRAIN, br)
    health.report(store, "post", "warn" if errors else "ok", "; ".join(errors) if errors else
                  (f"выложено: {', '.join(released)}" if released else f"жду: {decision.get('reason', '')[:160]}"))
    store.sync("post" + (f": {decision.get('clip')} → {', '.join(released)}" if released else ""))


def _publish_one(cfg, store: Store, cl, acc: dict, a: dict, clip: dict, plat: str, decision: dict, now: dt.datetime,
                 today: str, errors: list, path=None) -> bool:
    posting = cfg["posting"]
    t = clip["targets"][plat]
    log(f"{acc['id']}: публикую {clip['id']} «{t.get('hook')}»")
    try:
        if isinstance(path, Exception):
            raise path
        if path is None:
            path = releases.download(t["asset"], WORK_DIR / "post")
        res = cl.publish(path, {**t, "caption_full": full_caption(t, posting)}, cfg, clip)
    except PlatformError as e:
        log(f"❌ {acc['id']}: {e}")
        health.note_platform_error(store, acc["id"], e.kind)
        from .diagnose import advice_for
        a["diagnosis"] = advice_for(plat, e.kind, str(e))
        a.update(last_error=f"{e} [{e.kind}]"[:300], last_error_at=_iso(now))
        errors.append(f"{acc['id']}: {e}")
        if e.kind in ACCOUNT_COOLDOWN_H:  # беда аккаунта, а не ролика: ролик ждёт, попытки не тратятся
            hrs = ACCOUNT_COOLDOWN_H[e.kind]
            a.update(cooldown_until=(now + dt.timedelta(hours=hrs)).isoformat(), cooldown_reason=str(e)[:160])
            clip["posts"][plat] = {**(clip["posts"].get(plat) or {}), "account": acc["id"], "status": "retry",
                                   "error": str(e)[:300], "last_try": _iso(now)}
            return False
        post = clip["posts"].get(plat) or {"tries": 0}
        post.update(account=acc["id"], error=str(e)[:300], last_try=_iso(now), tries=post.get("tries", 0) + 1)
        post["status"] = "failed" if e.kind == "content" or post["tries"] >= 3 else "retry"
        if post["status"] == "failed":
            t["status"] = "failed"
        clip["posts"][plat] = post
        return False
    except Exception as e:  # noqa: BLE001 — например, файл пропал из релиза
        log(f"❌ {acc['id']}: {e}")
        t["status"] = "failed"
        clip["posts"][plat] = {"account": acc["id"], "status": "failed", "error": str(e)[:300], "last_try": _iso(now)}
        errors.append(f"{acc['id']}: {e}")
        return False
    clip["posts"][plat] = {**res, "account": acc["id"], "posted_at": _iso(now), "reason": decision.get("reason"),
                           "by": decision.get("by")}
    t["status"] = "used"
    cbd = {k: v for k, v in a.get("count_by_day", {}).items() if k >= (now - dt.timedelta(days=14)).date().isoformat()}
    cbd[today] = cbd.get(today, 0) + 1
    a["count_by_day"] = cbd
    if res.get("status") == "inbox":
        dbd = {k: v for k, v in a.get("drafts_by_day", {}).items() if k >= (now - dt.timedelta(days=14)).date().isoformat()}
        dbd[today] = dbd.get(today, 0) + 1
        a["drafts_by_day"] = dbd
    a.update(last_post_at=_iso(now), last_clip=clip["id"], last_error=None, diagnosis=None)
    log(f"✅ {acc['id']}: {res.get('status')} {res.get('url') or ''}")
    return True

