"""Публикация v6: ОДИН клип → ВСЕ площадки сразу. Все три или ни одной. Дневной лимит заполняется лучшим.

Правила (их не нарушает никто — ни ИИ, ни скрипт):
  1. Синхрон «все или ничего». Новый релиз уходит, только когда КАЖДАЯ включённая площадка готова принять ролик:
     токен живой, лимиты площадки в норме (предпроверка перед загрузкой). Площадка отдыхает после ошибки —
     ждут все, сколько бы это ни длилось. Никаких таймеров «через 2–3–12 часов пропускаем».
  2. Если в момент релиза одна площадка всё-таки не приняла ролик, новых релизов нет, пока её не дотянем:
     число роликов на площадках не расходится. (Черновик TikTok считается выложенным.)
  3. Клип не пропадает со временем. Очередь — общий список лучших моментов; в каждый слот уходит лучший
     из неё (оценка, свежесть, тема). Не влезло сегодня — уйдёт завтра, топ-момент не теряется.
  4. Дневной лимит «чётко»: в начале дня строится расписание из N слотов в лучшие часы аудитории.
     Слот наступил — выкладываю лучший клип. Клипа не было — слот ждёт, пока появится (в тот же день).
     Сильный клип с идущего эфира может занять следующий слот раньше времени. Волна — +1 слот.
  5. ИИ-продюсер выбирает, КАКОЙ клип поставить в слот (из лучших), но не решает, выкладывать ли:
     количество и время задаёт расписание.
"""
from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from . import health, learn, releases, reserve, schemas
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
RELEASED = ("posted", "inbox", "inbox_stale", "processing", "uploading")


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


def day_slots(n: int, weights: list[float], quiet: set[int], gap_h: float, fixed: list[int] | None = None,
              not_before: int = 0) -> list[int]:
    """Часы слотов на сутки: лучшие по активности аудитории, не ближе gap_h друг к другу.
    fixed — уже прошедшие слоты (их не двигаем); новые — не раньше часа not_before."""
    chosen = list(fixed or [])
    for g in (gap_h, max(1.0, gap_h / 2), 1.0):        # не влезает с паузой — ужимаем паузу, но лимит не теряем
        for h in sorted((h for h in range(not_before, 24) if h not in quiet), key=lambda x: -weights[x]):
            if len(chosen) >= n:
                break
            if h not in chosen and all(abs(h - c) >= g for c in chosen):
                chosen.append(h)
    return sorted(chosen)[:max(n, len(fixed or []))]


def rank(pool: list[dict], policy: dict, recent: list[dict]) -> list[tuple[float, dict, list[str]]]:
    """Лучший первым. Клип не сгорает: возраст лишь слегка снижает приоритет (−0.12 балла в сутки),
    поэтому вчерашняя «девятка» обходит сегодняшнюю «семёрку», а свежак с эфира получает бонус."""
    out = []
    cats = [r.get("category") for r in recent[:10]]
    for c in pool:
        age = age_hours(c)
        why = []
        key = float(c.get("score", 0)) - 0.12 * age / 24 + 0.1 * float(c.get("signal", 0) or 0) ** 0.5
        b = learn.category_boost(policy, "all", c.get("category", "other"))
        if b:
            key += 2.0 * b
            why.append(f"тема {'заходит' if b > 0 else 'заходит хуже'} ({learn._pct(b)})")
        if c.get("live_when_made") and age <= 3:
            key += 0.5
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


def partial_plats(c: dict, active: dict) -> list[str]:
    """Клип вышел на части площадок, а на этих загрузка в момент релиза не удалась (статус retry) — дотянуть.
    Площадки, которых не было в релизе (пауза/отключена), сюда не попадают: их цели помечены skipped_sync."""
    posts = c.get("posts") or {}
    if not any(p.get("status") in RELEASED for p in posts.values()):
        return []
    return [p for p in active if (posts.get(p) or {}).get("status") == "retry" and pending_for(c, p)]


def skip_absent(c: dict, plats: list[str]) -> None:
    """Площадки без релиза (пауза владельца, отключена, выключена) этот клип не получат никогда —
    иначе после возвращения площадка начала бы выкладывать всё старьё по одному в час."""
    for p, t in (c.get("targets") or {}).items():
        if p not in plats and t.get("status", "ready") == "ready" and not (c.get("posts") or {}).get(p):
            t["status"] = "skipped_sync"


def reconcile_upload(c: dict, plat: str, cl) -> str:
    """Маркер «выкладываю» остался от упавшего раннера (публикации идут строго по одной, таймаут 40 мин).
    Проверяем на площадке: ролик вышел → posted; не нашли → retry (перезалить безопасно).
    TikTok-черновики не видны в API — перезаливаем: лишний черновик безвреден."""
    import re as _re
    post = c["posts"][plat]
    if plat == "tiktok" or not hasattr(cl, "list_videos"):
        post.update(status="retry", error="загрузка прервалась — перезалью")
        return "retry"
    t = (c.get("targets") or {}).get(plat) or {}
    norm = lambda x: _re.sub(r"[^\wа-яё]+", " ", (x or "").lower()).strip()
    key = norm(t.get("caption") or t.get("title"))[:40]
    started = parse_iso(post["started_at"]).timestamp() - 3600 if post.get("started_at") else 0
    for v in cl.list_videos():
        hay = norm(v.get("description", "")) + " " + norm(v.get("title", ""))
        if key and key in hay and (v.get("create_time") or 0) >= started:
            post.update(status="posted", video_id=str(v["id"]), url=v.get("url"), posted_at=post.get("started_at"))
            return "posted"
    post.update(status="retry", error="загрузка прервалась, ролика на площадке нет — перезалью")
    return "retry"


def ensure_targets(c: dict, active: dict) -> bool:
    """Площадку подключили после монтажа клипа — видео то же самое, нужна только версия текстов для неё."""
    targets = c.get("targets") or {}
    base = next((t for t in targets.values() if t.get("asset") and t.get("status", "ready") == "ready"), None)
    if not base or any(p.get("status") in RELEASED for p in (c.get("posts") or {}).values()):
        return False
    added = False
    for plat in active:
        if plat not in targets:
            hook = base.get("hook") or c.get("overlay") or ""
            targets[plat] = {**{k: v for k, v in base.items() if k not in ("title", "description", "tags")},
                             "caption": base.get("caption") or hook, "title": base.get("title") or hook,
                             "description": base.get("description", ""), "tags": base.get("tags") or [], "status": "ready"}
            added = True
    c["targets"] = targets
    return added


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


# ── мозг: продюсер выбирает клип для слота ──────────────────────
PRODUCER = """Ты — продюсер каналов с нарезками стримера (TikTok, YouTube Shorts, Instagram Reels; одно и то же видео
выходит на всех площадках одновременно). Цель — максимальный рост: просмотры, подписчики, охват.
Сейчас {now_local} по времени аудитории ({tz}). Наступил слот публикации — ролик выходит СЕЙЧАС. Выбери, какой.

Опирайся на:
• Каждый ролик площадка оценивает отдельно по удержанию первых показов: ставь самый сильный момент.
• Свежесть важна: клип с идущего или только что закончившегося эфира работает лучше вчерашнего при близкой силе.
• Не ставь подряд два ролика одной темы или с одного места стрима.
• Невыбранные клипы не пропадают — уйдут в следующие слоты.
Состояние (очередь уже отсортирована по силе):
{state}
Ответ строго JSON: {{"action":"post","clip":"id","reason":"1–2 предложения по-русски","reason_en":"тот же текст по-английски"}}"""

CRITIC = """Ты — второй продюсер, проверяешь выбор коллеги: какой клип выходит в этот слот. Будь конкретен.
Состояние:
{state}
Выбор коллеги: {proposal}
Согласен? Если нет — назови клип лучше. Ответ строго JSON:
{{"agree":true,"action":"post","clip":"id","reason":"1–2 предложения по-русски","reason_en":"тот же текст по-английски"}}"""


def _state_text(ctx: dict) -> str:
    return json.dumps(ctx, ensure_ascii=False, indent=0)[:9000]


def think(cfg: dict, ctx: dict, fallback: dict) -> dict:
    """ИИ-продюсер + ИИ-критик выбирают клип для слота. Сбой или выдумка — fallback (лучший по рангу)."""
    ai = cfg.get("ai") or {}
    if not ai.get("planner", True):
        return {**fallback, "by": "план"}
    try:
        from .llm import LLM
        llm = LLM(cfg["llm"]["providers"], text_chain=[ai["text_model"]] if ai.get("text_model") else None)
    except SystemExit:
        return {**fallback, "by": "план (нет ключей ИИ)"}
    model = ai.get("planner_model", "gemini-4-argon")
    state = _state_text(ctx)
    try:
        prop = llm.chat_json_model([{"role": "user", "content": PRODUCER.format(
            now_local=ctx["now_local"], tz=cfg["posting"]["timezone"], state=state)}], model, max_tokens=1200,
            schema=schemas.PRODUCER, thinking="medium")
        crit = llm.chat_json([{"role": "user", "content": CRITIC.format(state=state, proposal=json.dumps(prop, ensure_ascii=False))}],
                             max_tokens=800, schema=schemas.PRODUCER_CRITIC, thinking="low")
    except Exception as e:  # noqa: BLE001
        log(f"продюсер недоступен: {str(e)[:160]} — беру лучший по рангу")
        return {**fallback, "by": "план (ИИ недоступен)"}
    final = prop if crit.get("agree", True) else crit
    return {"action": "post", "clip": final.get("clip") or fallback.get("clip"),
            "reason": str(final.get("reason", ""))[:400], "reason_en": str(final.get("reason_en", ""))[:400], "by": "ИИ-продюсер" + ("" if crit.get("agree", True) else " (поправил критик)"),
            "thoughts": [{"who": "продюсер", **{k: prop.get(k) for k in ("action", "clip", "reason", "reason_en")}},
                         {"who": "критик", **{k: crit.get(k) for k in ("agree", "action", "clip", "reason", "reason_en")}}]}


def preflight(cl) -> None:
    """Проверить площадку ДО загрузки (токен, лимиты). Бросает PlatformError — тогда не выходит никуда."""
    fn = getattr(cl, "preflight", None)
    if fn:
        fn()


def _cooldown(store: Store, a: dict, acc: dict, e: PlatformError, now: dt.datetime):
    health.note_platform_error(store, acc["id"], e.kind)
    from .diagnose import advice_for
    a["diagnosis"] = advice_for(acc["platform"], e.kind, str(e))
    a.update(last_error=f"{e} [{e.kind}]"[:300], last_error_at=_iso(now))
    hrs = ACCOUNT_COOLDOWN_H.get(e.kind, 0.25)
    a.update(cooldown_until=(now + dt.timedelta(hours=hrs)).isoformat(), cooldown_reason=str(e)[:160])


# ── главный цикл ────────────────────────────────────────────────
def cmd_post(cfg: dict, store: Store, force: bool = False, reset: bool = False):
    posting = cfg["posting"]
    if reset:    # разовый сброс «на сейчас»: счётчики дня, паузы площадок, интервал между релизами
        from . import limits
        limits.reset_today(store, posting["timezone"])
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
    reserve.expire_due(store, now)
    queue = [normalize(c) for c in store.list_json("queue")]
    enabled = cfg.get("platforms") or {"tiktok": 1, "youtube": 1, "instagram": 1}
    errors: list[str] = []


    # 1) площадки: включённые (active) и готовые прямо сейчас (ready)
    ready: dict[str, dict] = {}
    active: dict[str, dict] = {}
    resting: dict[str, dt.datetime] = {}
    clients = {}
    daymax = int(posting.get("daily_max", 5))
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
            a["state"] = "пауза (вручную) — остальные площадки её не ждут"
            continue
        active[plat] = acc
        clients[plat] = cl
        cd = a.get("cooldown_until")
        if cd and parse_iso(cd) > now:
            a["state"] = f"отдыхает до {cd[11:16]} UTC: {a.get('cooldown_reason', '')[:120]}"
            resting[plat] = parse_iso(cd)
            continue
        a["state"] = "готова"
        ready[plat] = acc

    # 1b) «выкладываю» на старте = прошлый раннер умер посреди загрузки (публикации строго по одной):
    #     сверяем с площадкой сразу — без дублей и без зависших клипов
    for c in queue:
        hung = [pl for pl, p in c["posts"].items() if p.get("status") == "uploading"]
        for pl in hung:
            acc = active.get(pl)
            if not acc:
                continue
            try:
                log(f"{c['id']}: прерванная загрузка на {pl} → {reconcile_upload(c, pl, clients[pl])}")
            except Exception as e:  # noqa: BLE001 — площадка не ответила: проверю в следующий запуск
                log(f"{c['id']}: не смог сверить {pl}: {str(e)[:120]}")
        if hung:
            store.write_json(f"queue/{c['id']}.json", c)

    # 2) расписание дня: N слотов в лучшие часы аудитории (строится раз в день, волна добавляет слот)
    rs = pstate.setdefault("releases", {})
    by_day = {k: v for k, v in (rs.get("by_day") or {}).items() if k >= (local.date() - dt.timedelta(days=14)).isoformat()}
    rel_today = int(by_day.get(today, 0))
    last_rel = parse_iso(rs["last_at"]) if rs.get("last_at") else None
    since_min = (now - last_rel).total_seconds() / 60 if last_rel else 1e9
    gap = int(posting.get("min_gap_minutes", 120))
    quiet: set[int] = set(posting.get("quiet_hours") or [])   # ночных часов больше нет; ключ остался для ручного запрета
    waves = momentum(stats, now.timestamp())
    hard = max(int(posting.get("hard_max", 6)), daymax + 1)     # настройка дашборда главнее потолка из config
    # В день без эфира выкладываем меньше и только из запаса: постоянство важнее объёма,
    # но тратить на пустой день сильные клипы незачем — они дороже в день, когда зритель уже пришёл.
    lv = store.read_json("status/live.json", {}) or {}
    seen = lv.get("started_at") if lv.get("is_live") else lv.get("last_seen_live")
    fresh_material = any(age_hours(c) <= 36 for c in queue if c.get("status") not in ("broken", "skipped", "expired"))
    stream_day = (bool(lv.get("is_live"))
                  or bool(seen and (now - parse_iso(seen)).total_seconds() < 36 * 3600)
                  or fresh_material)
    base = daymax if stream_day else min(daymax, int(posting.get("offday_max", 2)))
    exc = int((cfg.get("quality") or {}).get("exceptional", 9))
    epic = any(int(c.get("score", 0)) >= exc and c.get("status") not in ("broken", "skipped", "expired")
               and not any(p.get("status") in RELEASED for p in c["posts"].values()) for c in queue)
    cap = min(hard, base + (1 if (waves or epic) else 0))   # +1 слот: волна просмотров или суперклип в очереди
    weights = learn.get(policy, "hours.youtube") or learn.get(policy, "hours.tiktok") or learn.PRIOR_HOURS
    sch = pstate.get("schedule") or {}
    if reset:      # все слоты дня считаются наступившими: лимит открыт заново с этой минуты
        sch = {"date": today, "hours": [local.hour] * cap}
    elif sch.get("date") != today:
        sch = {"date": today, "hours": day_slots(cap, weights, quiet, gap / 60)}
    elif len(sch.get("hours") or []) != cap:      # волна или новая настройка: прошедшие слоты не трогаем
        past = [h for h in sch.get("hours") or [] if h <= local.hour]
        sch["hours"] = day_slots(cap, weights, quiet, gap / 60, fixed=past[:cap], not_before=local.hour + 1)
    pstate["schedule"] = sch
    slots_due = sum(1 for h in sch["hours"] if h <= local.hour) - rel_today
    slots_left = max(0, cap - rel_today)

    # 3) очередь: клипы не сгорают; годны — оценка ≥ порога, без высокого риска, ждут на ВСЕХ включённых площадках
    post_min = int((cfg.get("quality") or {}).get("post_min", 7))
    repair, pool = [], []
    for c in queue:
        if c.get("status") in ("broken", "skipped"):
            continue
        if ensure_targets(c, active):
            store.write_json(f"queue/{c['id']}.json", c)
        part = partial_plats(c, active)
        if part:
            c["_plats"] = part
            repair.append(c)
            continue
        if any(p.get("status") in RELEASED for p in c["posts"].values()):
            continue
        plats = [p for p in active if pending_for(c, p)]
        if set(plats) != set(active):   # хоть на одной площадке клип выйти не может — не выходит нигде
            continue
        if int(c.get("score", 0)) < post_min and not c.get("force_post"):
            continue
        if int((c.get("risk") or {}).get("level", 0)) >= 3:
            continue
        c["_plats"] = plats
        pool.append(c)
    recent = rs.get("recent", [])
    ranked = rank(pool, policy, recent)
    forced = max((c for c in pool if c.get("force_post")), key=lambda c: str(c["force_post"]), default=None)   # последний нажатый «Выложить сейчас» — первым
    hot = next((c for _, c, _ in ranked if c.get("live_when_made") and int(c.get("score", 0)) >= int(posting.get("hot_score", 8))
                and age_hours(c) <= 3 and posting.get("hot_now", True)), None)
    not_ready = sorted(set(active) - set(ready))
    wait_txt = ", ".join(f"{p} (отдыхает до {resting[p].astimezone(ZoneInfo(tz)):%H:%M})" for p in not_ready if p in resting)

    ctx = {"now_local": local.strftime("%Y-%m-%d %H:%M"), "releases_today": rel_today, "daily_max": cap,
           "slots_today": [f"{h:02d}:07" for h in sch["hours"]], "slots_left": slots_left,
           "minutes_since_last_release": None if since_min > 1e8 else int(since_min),
           "live_now": bool(lv.get("is_live")), "stream_day": stream_day, "waves": waves,
           "platforms": sorted(active), "last_releases": [{"hook": r.get("hook"), "category": r.get("category"), "at": r.get("at")}
                                                          for r in recent[:5]],
           "queue": [{"id": c["id"], "score": c.get("score"), "rank": k, "category": c.get("category"),
                      "hook": c.get("overlay"), "what": (c.get("what") or c.get("why") or "")[:160],
                      "age_h": round(age_hours(c), 1), "from_live": bool(c.get("live_when_made")),
                      "duration": c.get("duration")} for k, (_, c, _) in enumerate(ranked[:8])]}

    # 4) решение
    decision: dict = {"action": "wait", "clip": None, "by": "правила"}
    if not active:
        decision["reason"] = "ни одна площадка не подключена"
    elif repair:
        c = repair[0]
        miss = [p for p in c["_plats"] if p not in ready]
        if miss:
            decision["reason"] = (f"клип {c['id']} вышел не везде — жду {', '.join(miss)}, чтобы дотянуть; "
                                  "новые клипы не выходят, пока площадки не сравняются")
        else:
            decision = {"action": "post", "clip": c["id"], "by": "синхрон",
                        "reason": f"дотягиваю {', '.join(c['_plats'])}: клип уже вышел на других площадках"}
    elif not_ready:
        decision["reason"] = f"жду {wait_txt or ', '.join(not_ready)} — клип выходит только на всех площадках сразу"
    elif not ranked:
        decision["reason"] = "нет клипов нужного качества — ничего слабого не выкладываю"
    elif force or forced:
        pick = forced or ranked[0][1]
        decision = {"action": "post", "clip": pick["id"], "by": "владелец", "reason": "владелец нажал «Выложить сейчас»"}
    elif slots_left <= 0:
        decision["reason"] = f"сегодня уже {rel_today} релиз(ов) из {cap} — лучшие из очереди уйдут завтра"
    elif since_min < gap - 20:   # запуск по расписанию GitHub опаздывает на минуты — слот из-за этого не теряем
        decision["reason"] = f"после прошлого релиза прошло {int(since_min)} мин из {gap}"
    elif slots_due > 0 or hot:
        fb = {"action": "post", "clip": (hot or ranked[0][1])["id"],
              "reason": "сильный клип с идущего эфира — занимает следующий слот раньше" if hot and slots_due <= 0
              else f"слот {max(h for h in sch['hours'] if h <= local.hour):02d}:07 — лучший клип очереди"}
        decision = think(cfg, ctx, fb) if len(ranked) > 1 and not (hot and slots_due <= 0) else {**fb, "by": "план"}
        if decision.get("clip") not in {c["id"] for c in pool}:
            decision = {**fb, "by": "план (ИИ выбрал недоступный клип)"}
        decision["action"] = "post"
    else:
        nxt = next((h for h in sch["hours"] if h > local.hour), None)
        decision["reason"] = f"следующий слот в {nxt:02d}:07" if nxt is not None else "слоты на сегодня прошли"
    log(f"решение: {decision['action']} {decision.get('clip') or ''} — {decision.get('reason')} [{decision.get('by')}]")

    # 5) релиз: предпроверка всех площадок → маркер → загрузка параллельно
    released = []
    if decision["action"] == "post" and decision.get("clip"):
        clip = next(c for c in repair + pool if c["id"] == decision["clip"])
        plats = list(clip["_plats"])
        is_repair = clip in repair
        bad = []
        for plat in plats:
            try:
                try:
                    preflight(clients[plat])
                except PlatformError:
                    raise
                except Exception as ex:  # noqa: BLE001 — сбой проверки = площадка сейчас не готова
                    raise PlatformError(f"проверка не прошла: {str(ex)[:160]}", "temp") from ex
            except PlatformError as e:
                acc = active[plat]
                _cooldown(store, accs[acc["id"]], acc, e, now)
                errors.append(f"{acc['id']}: {e}")
                bad.append(plat)
        if bad:   # все или ничего: одна площадка не готова — не выходит никуда
            decision = {"action": "wait", "clip": None, "by": "предпроверка",
                        "reason": f"{', '.join(bad)} не прошла проверку перед загрузкой — клип ждёт, не выходит никуда"}
            log(f"решение изменено: {decision['reason']}")
        else:
            released = _release(cfg, store, clip, plats, active, clients, accs, decision, now, today, errors)
            if released and not is_repair:
                by_day[today] = by_day.get(today, 0) + 1
                rs.update(last_at=_iso(now), recent=[{"clip": clip["id"], "category": clip.get("category"),
                                                      "vod_id": clip.get("vod_id"), "vod_time": clip.get("vod_time"),
                                                      "hook": clip.get("overlay"), "at": _iso(now),
                                                      "platforms": released}] + recent[:29])
    rs["by_day"] = by_day
    nxt = (now.replace(minute=7, second=0, microsecond=0) + dt.timedelta(hours=1))
    pstate.update(timezone=tz, updated_at=_iso(now), next_check=nxt.isoformat(),
                  plan={"today": [f"{h:02d}:07" for h in sch["hours"]], "slots_left": max(0, cap - int(by_day.get(today, 0))),
                        "cap": cap, "releases_today": int(by_day.get(today, 0)), "waves": waves, "backlog": len(pool),
                        "up_next": [{"id": c["id"], "hook": c.get("overlay"), "score": c.get("score"),
                                     "age_h": round(age_hours(c), 1), "platforms": c.get("_plats")} for _, c, _ in ranked[:5]
                                    if c["id"] != decision.get("clip")]})
    store.write_json("status/post.json", pstate)
    br = store.read_json(BRAIN, {}) or {}
    feed = br.get("feed", [])
    feed.append({"at": _iso(now), "local": ctx["now_local"], **{k: decision.get(k) for k in ("action", "clip", "reason", "reason_en", "by") if k != "reason_en" or decision.get(k)},
                 "thoughts": decision.get("thoughts") or [], "released": released, "pool": len(pool)})
    br.update(feed=feed[-120:], last=feed[-1], context=ctx)
    store.write_json(BRAIN, br)
    health.report(store, "post", "warn" if errors else "ok", "; ".join(errors) if errors else
                  (f"выложено: {', '.join(released)}" if released else f"жду: {decision.get('reason', '')[:160]}"))
    store.sync("post" + (f": {decision.get('clip')} → {', '.join(released)}" if released else ""))


def _release(cfg, store: Store, clip: dict, plats: list[str], active: dict, clients: dict, accs: dict, decision: dict,
             now: dt.datetime, today: str, errors: list) -> list[str]:
    # маркер «выкладываю» сохраняется ДО загрузки: умрёт раннер посреди — следующий запуск не сделает дубль
    for plat in plats:
        clip["posts"][plat] = {**(clip["posts"].get(plat) or {}), "account": active[plat]["id"], "status": "uploading",
                               "started_at": _iso(now)}
    skip_absent(clip, list(clip["posts"]))
    store.write_json(f"queue/{clip['id']}.json", {k: v for k, v in clip.items() if not k.startswith("_")})
    store.sync(f"post: выкладываю {clip['id']} → {', '.join(plats)}")
    files = {}
    for asset in dict.fromkeys(clip["targets"][p].get("asset") for p in plats):
        try:
            files[asset] = releases.download(asset, WORK_DIR / "post")
        except Exception as e:  # noqa: BLE001 — например, файл пропал из релиза
            files[asset] = e

    def one(plat):
        acc = active[plat]
        ok = _publish_one(cfg, store, clients[plat], acc, accs[acc["id"]], clip, plat, decision, now, today, errors,
                          files.get(clip["targets"][plat].get("asset")))
        with store.lock:   # результат каждой площадки сохраняется сразу: упадёт раннер — не потеряется
            store.write_json(f"queue/{clip['id']}.json", {k: v for k, v in clip.items() if not k.startswith("_")})
            store.sync(f"post: {clip['id']} → {plat}: {clip['posts'][plat].get('status')}")
        return ok
    with ThreadPoolExecutor(max_workers=len(plats) or 1) as ex:   # релиз во все площадки в одну минуту
        oks = list(ex.map(one, plats))
    released = [p for p, ok in zip(plats, oks) if ok]
    for asset in dict.fromkeys(clip["targets"][p].get("asset") for p in released
                               if clip["posts"][p].get("status") in ("posted", "inbox")):
        maybe_delete_asset(clip, asset)   # файл общий: удаляется, только когда никому больше не нужен
    clip.pop("force_post", None)
    for k in [k for k in clip if k.startswith("_")]:
        clip.pop(k, None)
    store.write_json(f"queue/{clip['id']}.json", clip)
    return released


def _publish_one(cfg, store: Store, cl, acc: dict, a: dict, clip: dict, plat: str, decision: dict, now: dt.datetime,
                 today: str, errors: list, path=None) -> bool:
    """Загрузка идёт параллельно; изменения общего клипа — под замком (их сохраняют соседние потоки)."""
    posting = cfg["posting"]
    t = clip["targets"][plat]
    log(f"{acc['id']}: публикую {clip['id']} «{t.get('hook')}»")
    res, err = None, None
    try:
        if isinstance(path, Exception):
            raise path
        if path is None:
            path = releases.download(t["asset"], WORK_DIR / "post")
        res = cl.publish(path, {**t, "caption_full": full_caption(t, posting)}, cfg, clip)
    except Exception as e:  # noqa: BLE001
        err = e
    with store.lock:
        return _apply_result(store, acc, a, clip, plat, decision, now, today, errors, res, err)


def _apply_result(store: Store, acc: dict, a: dict, clip: dict, plat: str, decision: dict, now: dt.datetime,
                  today: str, errors: list, res, err) -> bool:
    t = clip["targets"][plat]
    try:
        if err is not None:
            raise err
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

