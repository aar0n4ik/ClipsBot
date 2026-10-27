"""python -m clipper <команда>

  watch            — проверить Twitch, при необходимости запустить нарезку (каждые 10 мин)
  process          — нарезать готовые куски записи
  post [--force]   — опубликовать, если пора (каждый час, все площадки)
  stats            — просмотры со всех площадок + здоровье + обучение (каждый час)
  doctor           — токены, секреты, чистка файлов (раз в сутки)
  auth --platform tiktok|youtube|instagram --account ID --code XXX — подключить аккаунт
  fail --job NAME  — записать в дашборд, что запуск упал (вызывается из workflow при ошибке)
  dashboard        — пересобрать data.enc
  diagnose         — проверить каждую площадку и сказать, что не так и что делать
  summary --job X  — короткий отчёт запуска в Markdown (для страницы запуска GitHub Actions)
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import unquote

from . import dashboard_data, health
from .config import load_config
from .store import Store
from .util import log, now_iso


def main():
    ap = argparse.ArgumentParser(prog="clipper")
    ap.add_argument("cmd", choices=["watch", "process", "post", "stats", "doctor", "auth", "fail", "dashboard",
                                    "diagnose", "summary"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--account", default="")
    ap.add_argument("--platform", default="")
    ap.add_argument("--code", default="")
    ap.add_argument("--job", default="")
    a = ap.parse_args()

    cfg = load_config()
    store = Store()
    if a.cmd == "summary":
        print(summary(store, a.job))
        return
    from . import settings
    settings.apply(cfg, store)          # настройки из дашборда поверх config.yaml
    dashboard_data.install(store, cfg)
    sw = settings.switches(store)
    gate = {"watch": "process", "process": "process", "post": "post", "stats": "stats"}.get(a.cmd)
    if gate and sw.get(gate):
        log(f"⏹ «{a.cmd}» остановлен из дашборда ({sw.get('note') or 'без комментария'}) — ничего не делаю")
        health.report(store, a.cmd, "paused", "остановлено вручную из дашборда")
        store.sync(f"{a.cmd}: остановлено вручную")
        return

    if a.cmd == "watch":
        from .pipeline import cmd_watch
        cmd_watch(cfg, store)
    elif a.cmd == "process":
        from .pipeline import cmd_process
        cmd_process(cfg, store)
    elif a.cmd == "post":
        from .poster import cmd_post
        cmd_post(cfg, store, force=a.force)
    elif a.cmd == "stats":
        from .stats import cmd_stats
        cmd_stats(cfg, store)
    elif a.cmd == "doctor":
        from .stats import cmd_doctor
        cmd_doctor(cfg, store)
    elif a.cmd == "auth":
        auth(cfg, store, a)
    elif a.cmd == "fail":
        health.report(store, a.job or "unknown", "error",
                      f"запуск «{a.job}» упал — открой лог по ссылке. Следующий запуск по расписанию попробует снова")
        store.sync(f"fail: {a.job}")
    elif a.cmd == "diagnose":
        from .diagnose import run_all
        run_all(store, cfg)
    elif a.cmd == "dashboard":
        store.write_json("status/watch.json", (store.read_json("status/watch.json", {}) or {}) | {"rebuilt_at": now_iso()})
        store.sync("dashboard rebuild")


def summary(store: Store, job: str) -> str:
    """Отчёт для вкладки Summary запуска: что сделано и почему — без похода в дашборд."""
    out = [f"### clipper · {job}"]
    sysd = store.read_json("status/system.json", {}) or {}
    if job == "process":
        f = store.read_json("status/funnel.json", {}) or {}
        out.append("| кусок | пики | разведчик | кандидаты | прошли текст | видео | взяты | ИИ $ | речь |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for ch in (f.get("chunks") or [])[-6:]:
            out.append(f"| {ch.get('chunk')} | {ch.get('peaks', 0)} | {ch.get('scout', 0)} | {ch.get('candidates', 0)} | "
                       f"{ch.get('text_pass', 0)} | {ch.get('video_pass', 0)}/{ch.get('video_checked', 0)} | "
                       f"**{ch.get('made', 0)}** | {ch.get('usd', 0)} | {ch.get('asr') or ''} |")
        rej = (f.get("rejected") or [])[-8:]
        if rej:
            out.append("\n**Последние отказы:**")
            out += [f"- `{r.get('stage')}` {r.get('score') or ''} — {r.get('reason')}" for r in rej]
    elif job == "post":
        last = (store.read_json("status/brain.json", {}) or {}).get("last") or {}
        out.append(f"**{last.get('action', '—')}** {last.get('clip') or ''} — {last.get('reason', '')} _({last.get('by', '')})_")
        if last.get("released"):
            out.append("Выложено: " + ", ".join(last["released"]))
    for k in (job, "ai", "render") if job != "post" else (job,):
        x = sysd.get(k)
        if x:
            out.append(f"- **{k}**: {x.get('level')} — {x.get('msg')}")
    return "\n".join(out)


def auth(cfg, store: Store, a):
    from .platforms import accounts, client, exchange, load_tokens, save_tokens
    code = unquote(a.code.strip())
    if "code=" in code:  # вставили всю ссылку целиком
        code = unquote(code.split("code=", 1)[1].split("&", 1)[0])
    code = code.split("#_")[0]  # Instagram добавляет «#_» в конец кода
    acc = next((x for x in accounts(cfg, enabled_only=False) if x["id"] == a.account), None)
    if not acc:
        raise SystemExit(f"Аккаунта «{a.account}» нет в config.yaml → accounts")
    plat = a.platform or acc["platform"]
    if plat != acc["platform"]:
        raise SystemExit(f"Аккаунт {acc['id']} в config.yaml описан как {acc['platform']}, а подключают {plat}")
    tok = exchange(plat, code, os.environ["OAUTH_REDIRECT_URI"])
    tokens = load_tokens(store)
    tokens[acc["id"]] = tok
    save_tokens(store, tokens)
    cl = client(store, acc)
    try:
        cl.tokens[acc["id"]]["user"] = cl.whoami()
        cl.save()
    except Exception as e:  # noqa: BLE001
        log(f"профиль не получен: {e}")
    st = store.read_json("status/tokens.json", {}) or {}
    st[acc["id"]] = {"platform": plat, **cl.token_status(), "last_ok": now_iso(), "connected_at": now_iso()}
    store.write_json("status/tokens.json", st)
    health.report(store, f"auth:{acc['id']}", "ok", f"{acc['id']} ({plat}) подключён")
    store.sync(f"{plat}: подключён {acc['id']}")
    log(f"✅ Аккаунт {acc['id']} ({plat}) подключён")


if __name__ == "__main__":
    main()
