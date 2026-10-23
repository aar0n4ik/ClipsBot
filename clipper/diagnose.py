"""Диагностика по каждой площадке: что не так и что с этим делать.

Запускается вручную (python -m clipper diagnose) и автоматически, когда публикация упала.
Каждая проверка — отдельно: токен, доступ к аккаунту, лимиты, доступность видео по ссылке.
Результат — понятные строки в дашборде, а не один общий «ошибка».
"""
from __future__ import annotations

from . import health
from .platforms import accounts as list_accounts
from .platforms import client
from .platforms.base import PlatformError
from .releases import public_url
from .store import Store
from .util import log, now_iso

ADVICE = {
    "blocked": "Площадка блокирует публикации этого аккаунта или приложения (код 200 «API access blocked»). "
               "Обычно это ограничение приложения или аккаунта на стороне площадки: проверьте в консоли разработчика "
               "статус приложения и права, и что аккаунт профессиональный (Creator/Business для Instagram). "
               "Бот поставил аккаунт на паузу на 24 ч и не будет жечь клипы.",
    "auth": "Токен истёк или отозван. Подключите аккаунт заново: Actions → «0 · Connect account».",
    "spam": "Площадка считает аккаунт спамящим. Пауза 24 ч. Лимит в сутки уже снижен до 4.",
    "rate": "Слишком много запросов. Бот подождёт и повторит сам.",
    "quota": "Суточный лимит публикаций площадки почти исчерпан. Продолжим завтра.",
    "content": "Площадка не приняла сам файл. Текст ошибки ниже — по нему видно, что именно не понравилось.",
    "temp": "Временный сбой на стороне площадки. Бот повторит попытку сам.",
}


def advice_for(platform: str, kind: str, message: str) -> str:
    base = ADVICE.get(kind, ADVICE["temp"])
    if platform == "tiktok" and "unaudited" in message:
        base = ("Приложение TikTok ещё не прошло аудит: публикация только в черновики или приватно. "
                "Это ограничение TikTok, а не ошибка бота.")
    return f"{base}\nТекст площадки: {message[:300]}"


def _check(name: str, fn) -> dict:
    try:
        ok, detail = fn()
        return {"check": name, "ok": bool(ok), "detail": detail}
    except PlatformError as e:
        return {"check": name, "ok": False, "detail": f"{e} [{e.kind}]", "kind": e.kind}
    except Exception as e:  # noqa: BLE001
        return {"check": name, "ok": False, "detail": f"{type(e).__name__}: {str(e)[:200]}"}


def diagnose_account(store: Store, cfg: dict, acc: dict) -> dict:
    plat = acc["platform"]
    cl = client(store, acc)
    checks = []
    checks.append(_check("подключён", lambda: (cl.connected(), "аккаунт подключён" if cl.connected()
                                               else "не подключён: Actions → «0 · Connect account»")))
    if not cl.connected():
        return {"account": acc["id"], "platform": plat, "checks": checks, "advice": ADVICE["auth"]}
    def _token():
        cl.refresh()  # бросит PlatformError, если токен не обновился
        return True, "токен действует"

    def _profile():
        me = cl.whoami()
        return bool(me), f"профиль: {str(me)[:120]}" if me else "профиль пустой"

    checks.append(_check("токен", _token))
    checks.append(_check("профиль", _profile))
    if plat == "tiktok":
        checks.append(_check("creator_info (право публиковать)", lambda: (
            bool(cl._post("/v2/post/publish/creator_info/query/")), "TikTok разрешает публикацию")))
    elif plat == "instagram":
        uid = cl.uid()
        checks.append(_check("лимит публикаций", lambda: (
            cl._call("GET", f"{uid}/content_publishing_limit", fields="quota_usage,config") is not None,
            "лимит получен")))
        checks.append(_check("тип аккаунта", lambda: (
            cl._call("GET", uid, fields="account_type").get("account_type") in ("BUSINESS", "MEDIA_CREATOR"),
            f"тип: {cl._call('GET', uid, fields='account_type').get('account_type')} "
            "(для публикации нужен Business или Creator)")))
    # можно ли площадке скачать видео по ссылке (Instagram забирает файл сам)
    asset = next(((c.get("targets") or {}).get(plat, {}).get("asset") for c in store.list_json("queue")
                  if (c.get("targets") or {}).get(plat, {}).get("asset")), None)
    if asset:
        url = public_url(asset)
        checks.append(_check("видео доступно по ссылке", lambda: (
            _head_ok(url), f"ссылка отвечает: {url[:80]}")))
    failed = [c for c in checks if not c["ok"]]
    advice = "Всё в порядке." if not failed else (
        advice_for(plat, failed[0].get("kind", "temp"), failed[0]["detail"]))
    return {"account": acc["id"], "platform": plat, "checks": checks, "advice": advice, "at": now_iso()}


def _head_ok(url: str) -> bool:
    import requests
    r = requests.head(url, timeout=20, allow_redirects=True)
    return r.status_code == 200


def run_all(store: Store, cfg: dict, write: bool = True) -> list[dict]:
    out = []
    for acc in list_accounts(cfg):
        res = diagnose_account(store, cfg, acc)
        out.append(res)
        line = "; ".join(f"{c['check']}: {'✅' if c['ok'] else '❌'} {c['detail'][:120]}" for c in res["checks"])
        log(f"🔎 {acc['id']} ({acc['platform']}): {line}")
        if write and res["advice"] != "Всё в порядке.":
            health.report(store, f"diag:{acc['id']}", "warn", res["advice"].split("\n")[0][:300])
    if write:
        store.write_json("status/diagnostics.json", {"at": now_iso(), "accounts": out})
        store.sync("диагностика площадок")
    return out
