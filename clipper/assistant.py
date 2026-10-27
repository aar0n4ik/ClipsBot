"""Помощник в дашборде: отвечает на вопросы владельца и вносит мелкие правки.

Как это работает. Репозиторий публичный, поэтому переписка лежит в `control/chat.enc`
на ветке data и зашифрована паролем дашборда — тем же, которым шифруется `data.enc`.
Браузер дописывает вопрос и запускает воркфлоу «6 · Assist»; здесь мы расшифровываем файл,
собираем настоящее состояние бота (настройки, деньги, очередь, журнал решений, здоровье),
спрашиваем ту же модель Gemini, что отбирает клипы, и дописываем ответ обратно.

Что помощнику разрешено менять — закрытый список (`ACTIONS`). Всё остальное он объясняет
словами. Крупные просьбы (добавить функцию, переделать сайт, переписать код) он не берёт:
граница нарисована и в промпте, и в коде — действия не из списка просто отбрасываются,
а владельцу приходит честный ответ, что такую работу лучше отдать полноценной модели
с доступом к репозиторию.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

from . import decisions, schemas, settings as S
from .crypto import decrypt_json, encrypt_json
from .llm import LLM, LLMError
from .store import Store
from .util import log, now_iso, now_utc

CHAT = "control/chat.enc"
LEDGER = "ledger.enc"
KEEP_MSGS = 60
MAX_PER_RUN = 3          # сколько вопросов разбираем за один запуск
MAX_CHANGES = 4          # сколько правок за один ответ — помощник не перекраивает настройки оптом

MONEY_FIELDS = {"rate_per_1000": (0.0, 1000.0), "payout_min": (0.0, 100000.0)}
CURRENCIES = ("USD", "EUR", "RUB", "UAH")

# ── что помощнику разрешено делать ──────────────────────────────
ACTIONS = ("set_setting", "set_money", "set_switch", "pause_account", "resume_account",
           "retry_clip", "post_now", "cancel_clip", "freeze_learning", "unfreeze_learning")

ANSWER = schemas.obj({
    "reply": schemas.S,
    "scope": {"type": "string", "enum": ["answer", "small_change", "too_big"]},
    "changes": {"type": "array", "items": schemas.obj(
        {"action": {"type": "string", "enum": list(ACTIONS)}, "key": schemas.S, "value": schemas.S, "why": schemas.S},
        ["action"])},
}, ["reply", "scope"])

SYSTEM = """Ты — помощник внутри дашборда бота, который сам нарезает стримы Twitch в вертикальные
клипы и выкладывает их в TikTok, YouTube Shorts и Instagram Reels. С тобой разговаривает владелец
бота. Отвечай по-русски, коротко и по делу, без вступлений и без markdown-разметки.

Тебе дают НАСТОЯЩЕЕ состояние бота в поле «данные». Отвечай только по нему. Если чего-то в данных
нет — так и скажи, не выдумывай числа, названия клипов и причины.

Ты можешь сам внести МЕЛКУЮ правку — перечисли её в changes и поставь scope=small_change.
Разрешено ровно это и ничего больше:
  set_setting      key = ключ из списка настроек, value = новое значение (бот сам зажмёт в границы)
  set_money        key = rate_per_1000 | payout_min | currency, value = новое значение
  set_switch       key = process | post | stats, value = "stop" | "run"
  pause_account    key = id аккаунта, value = на сколько суток (по умолчанию 3)
  resume_account   key = id аккаунта
  retry_clip       key = id клипа (повторить упавшую выкладку)
  post_now         key = id клипа (выложить ближайшим запуском)
  cancel_clip      key = id клипа (не выкладывать)
  freeze_learning / unfreeze_learning — без key

Правки делай, только если владелец прямо о них попросил. Вопрос «почему так?» — это вопрос,
а не просьба поменять: scope=answer, changes пустой. В ответе назови старое и новое значение
своими словами, одной фразой.

Если просят то, чего в списке нет — добавить функцию, переделать сайт или дизайн, переписать код,
поменять логику отбора или монтажа, завести новую площадку, настроить воркфлоу, починить баг —
поставь scope=too_big, changes оставь пустым и ответь честно: такую работу из дашборда не сделать,
её лучше отдать полноценной модели с доступом к репозиторию, там и результат будет лучше.
Скажи в одной-двух фразах, что именно нужно будет сделать в коде, чтобы просьбу было с чем нести.
Не обещай сделать это позже и не делай вид, что уже сделал."""


# ── чтение и запись переписки ───────────────────────────────────
def _password() -> str | None:
    return os.environ.get("DASHBOARD_PASSWORD") or None


def read_chat(store: Store, pw: str) -> dict:
    raw = store.read_bytes(CHAT)
    if not raw:
        return {"v": 1, "msgs": []}
    try:
        obj = decrypt_json(raw, pw)
    except Exception as e:  # пароль сменили или файл побит — не роняем запуск
        log(f"⚠️ переписка не расшифровалась: {type(e).__name__}")
        return {"v": 1, "msgs": []}
    if not isinstance(obj, dict) or not isinstance(obj.get("msgs"), list):
        return {"v": 1, "msgs": []}
    return obj


def write_chat(store: Store, pw: str, chat: dict):
    chat["msgs"] = chat.get("msgs", [])[-KEEP_MSGS:]
    chat["updated_at"] = now_iso()
    store.write_bytes(CHAT, encrypt_json(chat, pw))


def unanswered(chat: dict) -> list[dict]:
    answered = {m.get("reply_to") for m in chat["msgs"] if m.get("role") == "bot"}
    return [m for m in chat["msgs"] if m.get("role") == "user" and m.get("id") not in answered][-MAX_PER_RUN:]


# ── состояние бота для модели ───────────────────────────────────
def _clip_brief(c: dict) -> dict:
    posts = {p: {"статус": x.get("status"), "когда": x.get("posted_at"), "ошибка": (x.get("error") or "")[:120]}
             for p, x in (c.get("posts") or {}).items()}
    return {"id": c.get("id"), "название": c.get("overlay") or c.get("what"), "оценка": c.get("score"),
            "создан": c.get("created_at"), "статус": c.get("status"), "площадки": posts}


def snapshot(store: Store, cfg: dict) -> dict:
    """Настоящее состояние: ровно то, что видит дашборд, только короче."""
    from .clips import normalize, overall
    from .config import load_money
    from .platforms import accounts as list_accounts

    vals = S.load(store, cfg)
    clips = sorted((normalize(c) for c in store.list_json("queue")),
                   key=lambda c: c.get("created_at") or "", reverse=True)
    for c in clips:
        c["status"] = overall(c)
    stats = store.read_json("stats.json", {}) or {}
    views = {}
    for acc in (stats.get("accounts") or {}).values():
        plat = acc.get("platform", "?")
        for v in (acc.get("videos") or {}).values():
            views[plat] = views.get(plat, 0) + int(v.get("views") or 0)
    policy = store.read_json("policy.json", {}) or {}
    money = load_money(cfg.get("money"))
    ledger_settings = {}
    pw = _password()
    raw = store.read_bytes(LEDGER)
    if raw and pw:
        try:
            ledger_settings = (decrypt_json(raw, pw) or {}).get("settings") or {}
        except Exception:
            ledger_settings = {}
    return {
        "сейчас": now_iso(),
        "эфир": store.read_json("status/live.json", {}) or {},
        "нарезка": store.read_json("status/process.json", {}) or {},
        "выкладка": {k: v for k, v in (store.read_json("status/post.json", {}) or {}).items() if k != "history"},
        "здоровье_системы": store.read_json("status/system.json", {}) or {},
        "здоровье_аккаунтов": store.read_json("status/health.json", {}) or {},
        "последние_куски": ((store.read_json("status/funnel.json", {}) or {}).get("chunks") or [])[-5:],
        "аккаунты": [{"id": a["id"], "имя": a.get("name", a["id"]), "площадка": a["platform"],
                      "включён": a.get("enabled", True)} for a in list_accounts(cfg, enabled_only=False)],
        "просмотры_всего_по_площадкам": views,
        "деньги": {**money, **ledger_settings, "пояснение": "ставка за 1000 просмотров лучшей площадки клипа"},
        "настройки": vals,
        "настройки_можно_менять": sorted(S.SCHEMA),
        "выключатели": store.read_json(S.SWITCHES, {}) or {},
        "паузы_площадок": policy.get("paused") or {},
        "обучение_на_паузе": bool(policy.get("frozen")),
        "клипы": [_clip_brief(c) for c in clips[:25]],
        "журнал_решений": [{"когда": d.get("at"), "что": d.get("summary"), "вид": d.get("kind")}
                           for d in (store.read_json("decisions.json", []) or [])[-25:]],
    }


# ── применение правок ───────────────────────────────────────────
def _num(value, lo: float, hi: float):
    x = float(str(value).replace(",", ".").replace("$", "").strip())
    if not lo <= x <= hi:
        raise ValueError(f"вне границ {lo}–{hi}")
    return x


def _parse_setting(key: str, value):
    """Строку от модели приводим к типу ключа; границы потом зажмёт settings.load."""
    default, spec, _ = S.SCHEMA[key]
    raw = str(value).strip()
    if spec is bool:
        low = raw.lower()
        if low in ("true", "1", "да", "вкл", "yes", "on"):
            return True
        if low in ("false", "0", "нет", "выкл", "no", "off"):
            return False
        raise ValueError("нужно да или нет")
    if spec == "hours":
        import re
        hours = sorted({int(x) for x in re.findall(r"\d{1,2}", raw) if 0 <= int(x) <= 23})
        if not hours:
            raise ValueError("не разобрал часы")
        return hours
    if isinstance(spec, tuple) and spec and isinstance(spec[0], str):
        if raw not in spec:
            raise ValueError("допустимо: " + ", ".join(spec))
        return raw
    if isinstance(spec, tuple):
        try:
            x = float(raw.replace(",", ".").replace("$", "").strip())
        except ValueError:
            raise ValueError("нужно число") from None
        # границы не проверяем: settings.load зажмёт в допустимые, и в ответе владелец
        # увидит настоящее новое значение, а не то, что попросила модель
        return int(round(x)) if isinstance(default, int) and not isinstance(default, bool) else round(x, 2)
    raise ValueError("ключ менять нельзя")


def _set_money(store: Store, key: str, value) -> tuple[str, str]:
    pw = _password()
    if not pw:
        raise ValueError("нет пароля дашборда")
    raw = store.read_bytes(LEDGER)
    led = decrypt_json(raw, pw) if raw else {}
    if not isinstance(led, dict):
        led = {}
    cur = dict(led.get("settings") or {})
    if key == "currency":
        new = str(value).strip().upper()
        if new not in CURRENCIES:
            raise ValueError("валюта: " + ", ".join(CURRENCIES))
    else:
        new = _num(value, *MONEY_FIELDS[key])
    before = cur.get(key, "по умолчанию")
    cur[key] = new
    led["settings"] = cur
    led["updated_at"] = now_iso()
    store.write_bytes(LEDGER, encrypt_json(led, pw))
    return str(before), str(new)


def apply_change(store: Store, cfg: dict, ch: dict) -> dict:
    """Одна правка. Возвращает запись для ответа или кидает ValueError с человеческой причиной."""
    action = ch.get("action")
    key = str(ch.get("key") or "").strip()
    value = ch.get("value")
    if action not in ACTIONS:
        raise ValueError("так делать нельзя")

    if action == "set_setting":
        if key not in S.SCHEMA:
            raise ValueError("такой настройки нет")
        new = _parse_setting(key, value)
        raw = store.read_json(S.SETTINGS, {}) or {}
        vals = dict(raw.get("values") if isinstance(raw.get("values"), dict) else raw)
        before = S.load(store, cfg).get(key)
        vals[key] = new
        store.write_json(S.SETTINGS, {"values": vals, "updated_at": now_iso(), "by": "помощник"})
        after = S.load(store, cfg).get(key)
        return {"what": key, "from": before, "to": after}

    if action == "set_money":
        if key not in MONEY_FIELDS and key != "currency":
            raise ValueError("можно менять ставку, порог вывода и валюту")
        before, after = _set_money(store, key, value)
        names = {"rate_per_1000": "ставка за 1000 просмотров", "payout_min": "порог вывода", "currency": "валюта"}
        return {"what": names[key], "from": before, "to": after}

    if action == "set_switch":
        if key not in S.SWITCH_KEYS:
            raise ValueError("выключатели: " + ", ".join(S.SWITCH_KEYS))
        stop = str(value).strip().lower() in ("stop", "стоп", "true", "1", "да", "off")
        sw = dict(store.read_json(S.SWITCHES, {}) or {})
        before = "остановлено" if sw.get(key) else "работает"
        sw[key] = stop
        sw["note"] = "помощник из дашборда"
        sw["updated_at"] = now_iso()
        store.write_json(S.SWITCHES, sw)
        names = {"process": "нарезка", "post": "выкладка", "stats": "статистика"}
        return {"what": names[key], "from": before, "to": "остановлено" if stop else "работает"}

    if action in ("pause_account", "resume_account"):
        from .platforms import accounts as list_accounts
        ids = {a["id"] for a in list_accounts(cfg, enabled_only=False)}
        if key not in ids:
            raise ValueError("нет такого аккаунта: " + (key or "—"))
        policy = store.read_json("policy.json", {}) or {}
        paused = dict(policy.get("paused") or {})
        was = "на паузе" if key in paused else "работает"
        if action == "pause_account":
            try:
                days = min(30.0, max(0.5, float(str(value or 3).replace(",", "."))))
            except ValueError:
                days = 3.0
            paused[key] = (now_utc() + dt.timedelta(days=days)).isoformat()
            now = f"на паузе {days:g} сут."
        else:
            paused.pop(key, None)
            now = "работает"
        policy["paused"] = paused
        store.write_json("policy.json", policy)
        return {"what": "выкладка " + key, "from": was, "to": now}

    if action in ("retry_clip", "post_now", "cancel_clip"):
        if not store.read_json(f"queue/{key}.json"):
            raise ValueError("нет такого клипа: " + (key or "—"))
        cmd = {"retry_clip": "retry_clip", "post_now": "post_now", "cancel_clip": "cancel_clip"}[action]
        cmds = store.read_json("control/commands.json", []) or []
        cmds.append({"id": "as" + uuid.uuid4().hex[:8], "at": now_iso(), "cmd": cmd, "clip": key, "by": "помощник"})
        store.write_json("control/commands.json", cmds[-300:])
        names = {"retry_clip": "повтор выкладки", "post_now": "выложить ближайшим запуском", "cancel_clip": "не выкладывать"}
        return {"what": f"клип {key}", "from": "как было", "to": names[action]}

    # freeze_learning / unfreeze_learning
    want = action == "freeze_learning"
    policy = store.read_json("policy.json", {}) or {}
    was = bool(policy.get("frozen"))
    policy["frozen"] = want
    store.write_json("policy.json", policy)
    return {"what": "обучение", "from": "на паузе" if was else "идёт", "to": "на паузе" if want else "идёт"}


# ── один вопрос ─────────────────────────────────────────────────
def answer_one(llm: LLM, store: Store, cfg: dict, question: str, history: list[dict], state: dict) -> dict:
    hist = "\n".join(f"{'Владелец' if m['role'] == 'user' else 'Ты'}: {m.get('text', '')[:600]}" for m in history[-6:])
    user = (f"данные:\n{json.dumps(state, ensure_ascii=False, default=str)[:60000]}\n\n"
            + (f"прошлый разговор:\n{hist}\n\n" if hist else "")
            + f"вопрос владельца:\n{question}")
    model = (cfg.get("ai") or {}).get("planner_model") or None
    js = llm.chat_json([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                       max_tokens=1800, schema=ANSWER, model=model, thinking="medium")
    reply = str(js.get("reply") or "").strip() or "Не смог ответить."
    scope = js.get("scope") if js.get("scope") in ("answer", "small_change", "too_big") else "answer"
    out = {"text": reply, "kind": "refused" if scope == "too_big" else scope}

    if scope != "small_change":
        return out
    done, failed = [], []
    for ch in (js.get("changes") or [])[:MAX_CHANGES]:
        try:
            done.append(apply_change(store, cfg, ch))
        except Exception as e:
            failed.append(f"{ch.get('action')} {ch.get('key') or ''}: {e}")
    if done:
        out["changed"] = done
        decisions.record(store, "hint", "Помощник из дашборда: "
                         + "; ".join(f"{d['what']} {d['from']} → {d['to']}" for d in done), reversible=False)
    if failed:
        out["text"] = reply.rstrip(".") + ". Но часть не вышла — " + "; ".join(failed) + "."
    if not done:
        out["kind"] = "error" if failed else "answer"
    return out


def run(cfg: dict, store: Store):
    pw = _password()
    if not pw:
        log("нет DASHBOARD_PASSWORD — помощник не работает")
        return
    chat = read_chat(store, pw)
    pending = unanswered(chat)
    if not pending:
        log("новых вопросов нет")
        return
    llm = LLM(cfg["llm"]["providers"], text_chain=[(cfg.get("ai") or {}).get("text_model")]
              if (cfg.get("ai") or {}).get("text_model") else None)
    state = snapshot(store, cfg)
    for q in pending:
        log(f"вопрос: {str(q.get('text'))[:120]}")
        before = [m for m in chat["msgs"] if m is not q]
        try:
            res = answer_one(llm, store, cfg, str(q.get("text") or ""), before, state)
        except LLMError as e:
            res = {"text": f"ИИ сейчас не отвечает ({e}). Спроси ещё раз через несколько минут.", "kind": "error"}
        except Exception as e:  # помощник не должен ронять запуск
            log(f"⚠️ помощник упал: {type(e).__name__}: {e}")
            res = {"text": f"Что-то пошло не так на моей стороне: {type(e).__name__}. Попробуй переформулировать.", "kind": "error"}
        chat["msgs"].append({"id": "b" + uuid.uuid4().hex[:8], "at": now_iso(), "role": "bot",
                             "reply_to": q.get("id"), **res})
        if res.get("changed"):
            state = snapshot(store, cfg)   # следующий вопрос должен видеть уже новые значения
    write_chat(store, pw, chat)
    store.sync("assist: ответы помощника")
