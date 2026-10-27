"""Мозг отбора: несколько независимых «голов», которые спорят, прежде чем клип выйдет.

  1. РАЗВЕДЧИК  — Gemini слушает ВЕСЬ кусок стрима (звук + таблица реакций чата) и отмечает моменты,
                  которые сигналы чата/громкости могли пропустить (истории, тихие панчлайны).
  2. ОТБОРЩИК   — по тексту (Whisper, слова со временем) честно оценивает каждого кандидата 1–10
                  по жёсткой шкале. Слабое отсекается сразу, чтобы не тратить видео-проход.
  3. РЕЖИССЁР   — Gemini СМОТРИТ финалиста (видео + звук): есть ли момент на самом деле, нет ли лагов
                  и зависаний, где точно начать и закончить, какие паузы вырезать, какой заголовок правдив.
  4. КРИТИК     — отдельная модель без «авторской любви»: совпадает ли заголовок с тем, что происходит,
                  понятно ли без контекста, не выдуман ли смысл. Не согласен — клип не выходит.

Оценки откалиброваны по исходу (что будет с роликом), а не «по ощущениям», и у каждой головы
свой ответ в журнале клипа — в дашборде видно, кто и почему его пропустил или зарезал.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import schemas
from .llm import LLM, LLMError
from .transcribe import words_to_timed_text
from .util import fmt_hms, log

# ── общая шкала ────────────────────────────────────────────────────
SCALE = """ШКАЛА ОЦЕНКИ (по тому, что будет с роликом в ленте у незнакомого человека):
 1–2  ничего не происходит: езда, тишина, чтение экрана, фоновая болтовня, технические паузы.
 3–4  обычный разговор: есть тема, но нет пика; без контекста стрима непонятно или скучно; свайпнут.
 5–6  нормально, но проходняк: понятная тема или лёгкая улыбка, нет сильного хука или развязки. НЕ публикуем.
 7    хороший клип: понятен без контекста, цепляет в первые 2 секунды, есть развязка (смех, удивление,
      конфликт, сильное мнение, неожиданный поворот). Досматривают.
 8    сильный: настоящая эмоция или очень смешная фраза или неожиданное событие; хочется написать коммент или переслать.
 9    редкость: один из лучших моментов недели, реально вирусный потенциал.
 10   раз в месяц.
Калибровка: в ЧАСЕ стрима обычно 0–2 момента на 7+, часто ни одного. 8+ — пара раз в неделю. Средний кандидат — 3–5.
Завышение хуже занижения: слабый ролик тянет вниз весь аккаунт. Сомневаешься между двумя оценками — ставь меньшую."""

STYLE_RULES = """Заголовок (хук) поверх видео: 2–6 слов, до 30 символов, по-русски, разговорно, как у живого клипера 18–25 лет.
Описывает то, что РЕАЛЬНО видно и слышно в ролике, но не спойлерит развязку. Без эмодзи, без мата,
без слов «шок», «невероятно», «вы не поверите», «эпично», «до конца». Не выдумывай события, людей, суммы и места,
которых нет в ролике. Если не уверен, что происходит, — пиши проще и точнее, а не ярче."""

CATS = "funny, conflict, money, america, customer, road, emotional, chat, story, other"

RISK = """risk — {"level":0..3,"flags":[...]}: phone_driving (телефон в руке за рулём), dangerous_driving, heavy_profanity
(мат почти в каждой фразе), insult_group, violence, private_info (адрес, номер телефона, номер машины крупно),
minor (ребёнок в кадре), sexual, drugs_alcohol, music (громкая чужая музыка). 0 чисто … 3 не публиковать."""


# ── 1. разведчик: весь кусок целиком ───────────────────────────────
SCOUT = """Ты — опытный клипер. Перед тобой звук {dur_min} минут записи IRL-стрима (начало аудио = 00:00).
О стримере: {persona}
Аудитория: {audience}

Ниже — активность чата по минутам (сообщений / смех / шок) и самые реакционные сообщения. Чат пишет с задержкой ~5–15 с.
{chat}

Задача: найти моменты, из которых выйдет СИЛЬНЫЙ короткий ролик 10–60 с для TikTok / Shorts / Reels.
Ищи: смешные фразы и ситуации, конфликты, неожиданные события, деньги/чаевые/цены, странных клиентов и прохожих,
истории с развязкой, сильные эмоции, острые мнения, реакции на донаты с сутью.
Не отмечай: обычные разговоры, чтение донатов без сути, езду, тишину, «ща погодите», внутренние шутки.
{scale}
Верни только то, что тянет на 7+ по шкале (обычно 0–2 момента на час звука; лучше меньше, но точнее).
Время — где начинается САМ момент (не реакция чата), в формате MM:SS или H:MM:SS от начала аудио.
Ответ строго JSON: {{"moments":[{{"at":"MM:SS","end":"MM:SS","guess":7,"what":"что происходит, 1 фраза"}}]}}"""


def _ts(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*(?:(\d+):)?(\d{1,3}):(\d{2})(?:\.\d+)?\s*$", str(v or ""))
    if not m:
        return None
    h, mm, ss = int(m[1] or 0), int(m[2]), int(m[3])
    return h * 3600 + mm * 60 + ss


def chat_digest(msgs: list[dict], chunk_start: float, length: int, patterns) -> str:
    """Компактная сводка чата по минутам + реакционные сообщения горячих минут."""
    if not msgs:
        return "(чат недоступен)"
    mins: dict[int, dict] = {}
    for m in msgs:
        i = int((m["t"] - chunk_start) // 60)
        if not 0 <= i <= length // 60:
            continue
        d = mins.setdefault(i, {"n": 0, "laugh": 0, "shock": 0, "top": []})
        d["n"] += 1
        full = (m.get("text") or "") + " " + " ".join(m.get("emotes") or [])
        hits = [name for name, _, rx in patterns if rx.search(full)]
        d["laugh"] += "laugh" in hits
        d["shock"] += "shock" in hits
        if hits and len(d["top"]) < 3 and len(m.get("text", "")) > 2:
            d["top"].append(m["text"][:60])
    if not mins:
        return "(чат пустой)"
    avg = sum(d["n"] for d in mins.values()) / max(1, len(mins))
    lines = []
    for i in sorted(mins):
        d = mins[i]
        hot = d["n"] >= 1.8 * avg or d["laugh"] >= 4 or d["shock"] >= 4
        line = f"{i // 60}:{i % 60:02d} — {d['n']}/{d['laugh']}/{d['shock']}"
        if hot and d["top"]:
            line += " · " + " | ".join(d["top"])
        lines.append(line)
    return "\n".join(lines)


def export_audio_parts(src: Path, length: float, out_dir: Path, part_min: int = 60) -> list[tuple[float, Path]]:
    """Звук куска → лёгкие куски по ≤60 мин (моно 16 кГц, opus ~12 кбит/с), чтобы влезть inline в Gemini."""
    parts = []
    t = 0.0
    k = 0
    while t < length - 5:
        dur = min(part_min * 60, length - t)
        out = out_dir / f"scout_{k}.ogg"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
                            "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "12k", "-application", "voip", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            out = out.with_suffix(".mp3")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
                            "-ac", "1", "-ar", "16000", "-b:a", "16k", str(out)], capture_output=True)
        if out.exists() and out.stat().st_size > 1000:
            parts.append((t, out))
        t += dur
        k += 1
    return parts


def scout(llm: LLM, cfg: dict, audio: Path, length: float, msgs: list[dict], chunk_start: float, work: Path,
          patterns) -> list[dict]:
    """Моменты от разведчика: [{"abs": секунда VOD, "end_abs", "guess", "what"}]."""
    st = cfg["streamer"]
    out = []
    model = (cfg.get("ai") or {}).get("scout_model", "gemini-3.8-flash")

    def listen(item):
        t0, part = item
        dur = min(3600.0, length - t0)
        sub = [m for m in msgs if chunk_start + t0 <= m["t"] < chunk_start + t0 + dur]
        prompt = SCOUT.format(dur_min=int(dur // 60), persona=st["persona"].strip(), audience=st.get("audience", "").strip(),
                              chat=chat_digest(sub, chunk_start + t0, int(dur), patterns), scale=SCALE)
        mime = "audio/ogg" if part.suffix == ".ogg" else "audio/mp3"
        try:
            return t0, dur, llm.media_json([(mime, part.read_bytes())], prompt, model=model,
                                           fallback_models=["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"],
                                           max_tokens=8000, low_res=False, schema=schemas.SCOUT, thinking="medium")
        except LLMError as e:
            log(f"разведчик: часть {fmt_hms(t0)} пропущена ({str(e)[:140]})")
            return t0, dur, {}
    from concurrent.futures import ThreadPoolExecutor
    parts = export_audio_parts(audio, length, work)
    with ThreadPoolExecutor(max_workers=max(1, len(parts))) as ex:   # части часа слушаются одновременно
        results = list(ex.map(listen, parts))
    for t0, dur, js in results:
        for m in js.get("moments") or []:
            a = _ts(m.get("at"))
            if a is None or not 0 <= a <= dur + 5:
                continue
            b = _ts(m.get("end"))
            out.append({"abs": chunk_start + t0 + a, "end_abs": chunk_start + t0 + b if b and b > a else None,
                        "guess": int(m.get("guess") or 0), "what": str(m.get("what", ""))[:200]})
    log(f"разведчик: {len(out)} момент(ов) по всему звуку")
    return out


# ── 2. отборщик по тексту ──────────────────────────────────────────
PICKER = """Ты — строгий отборщик в команде клиперов IRL-стримов (TikTok, YouTube Shorts, Instagram Reels).
О стримере: {persona}
Аудитория: {audience}
{hints}
Для КАЖДОГО кандидата есть транскрипт (секунды от начала окна), реакция чата, клипы зрителей и, иногда, заметка разведчика.
Реши честно: есть ли тут законченный момент, понятный человеку, который никогда не видел стрим?
{scale}
Поля:
• keep — true только если тянет на 7+.
• score 1–10 по шкале; подоценки 0–10: hook (первые 2 с), payoff (развязка), clarity (понятно без контекста), emotion, rewatch.
• start / end — секунды от начала окна: start прямо с действия или первой фразы, которая цепляет (без «короче», «ну вот»,
  приветствий и долгой подводки); end — через 0.5–1.5 с после панчлайна или реакции.
  {length}
• category — одно из: {cats}.
• {risk}
• shelf — срок годности момента: "now" — привязан к событию и через неделю будет непонятен или неинтересен;
  "weeks" — актуален пару месяцев (разговор о том, что происходит сейчас в жизни стримера);
  "forever" — время не важно, зайдёт и через год (шутка, конфликт, история, реакция).
  Если сомневаешься — "forever": такой момент бот положит в запас и выложит, когда будет выгодно.
• why — коротко и конкретно: что за момент и почему зайдёт или нет.
{learned}
Ответ строго JSON:
{{"clips":[{{"id":"…","keep":false,"score":4,"hook":4,"payoff":3,"clarity":6,"emotion":3,"rewatch":2,"start":3.2,"end":27.5,"category":"other","shelf":"forever","risk":{{"level":0,"flags":[]}},"why":"…"}}]}}
Верни объект для каждого кандидата."""


# ── 3. режиссёр: смотрит видео ─────────────────────────────────────
DIRECTOR = """Ты — режиссёр монтажа коротких роликов из IRL-стрима. Перед тобой фрагмент записи ({dur:.0f} с, начало видео = 0.0).
О стримере: {persona}
Транскрипт фрагмента (секунды от начала видео):
{transcript}
Реакция чата (время от начала видео): {chat}
Предварительная оценка по тексту: {pre_score}/10 — «{pre_why}».
Технический анализ кадров: {tech}

СМОТРИ И СЛУШАЙ видео целиком и реши как профессионал, стоит ли это публиковать.
1. Есть ли тут реальный момент (а не обычные слова)? Что именно видно и слышно? Совпадает ли картинка с речью?
2. Технически: лаги (картинка замирает или дёргается, а звук идёт), рассыпание кадра, чёрный экран, буферизация,
   рассинхрон звука, оверлеи закрывают главное. Если лаги заметны в главной части — это reject.
3. Где точно начать (первая секунда должна цеплять), где закончить (сразу после развязки/реакции, без хвоста).
   {length}
4. Какие куски ВНУТРИ вырезать: долгие паузы и молчание (стример думает, смотрит в телефон, ждёт), «ща-ща-ща»,
   уход в другую тему. Короткие драматические паузы (до 1 с) перед панчлайном оставляй.
{scale}
{style}
Тексты площадок: tiktok — caption до 110 символов, разговорно, в начале поисковые слова по теме, 3–5 нишевых хештегов;
youtube — title до 70 символов с ключевым словом и интригой, description 1–2 предложения, 5–8 tags;
instagram — caption 1–2 строки с вопросом к зрителю, 4–6 хештегов. comment — первый коммент автора, вопрос к зрителям, до 80 символов.
Хуки: 4 варианта в разных стилях — tease (недосказанность), conflict (конфликт/ставки), number (конкретика/цифра из ролика),
quote (дословная фраза из ролика). pick — индекс лучшего. Если в ролике нет цифры — number всё равно опиши конкретикой, без выдуманных чисел.
{risk}
Ответ строго JSON:
{{"verdict":"post|reject","score":7,"subscores":{{"hook":7,"payoff":7,"clarity":8,"emotion":6,"rewatch":5}},
"what_happens":"что видно и слышно, 1–2 предложения, по фактам","moment":"главный момент одной фразой",
"technical":{{"lag":0,"issues":[]}},"start":2.4,"end":31.0,"cuts":[[12.1,15.8]],"standalone":true,
"category":"funny","risk":{{"level":0,"flags":[]}},
"hooks":[{{"style":"tease","text":"…"}},{{"style":"conflict","text":"…"}},{{"style":"number","text":"…"}},{{"style":"quote","text":"…"}}],"pick":0,
"tiktok":{{"caption":"…","hashtags":["#…"]}},"youtube":{{"title":"…","description":"…","tags":["…"]}},
"instagram":{{"caption":"…","hashtags":["#…"]}},"comment":"…","reject_reason":""}}
lag: 0 нет, 1 едва заметно, 2 мешает, 3 смотреть невозможно. Время start/end/cuts — секунды от начала ЭТОГО видео."""


# ── 4. критик ──────────────────────────────────────────────────────
CRITIC = """Ты — независимый редактор, последний контроль перед публикацией. Ты не делал этот ролик и не обязан его любить.
Что происходит в ролике (со слов режиссёра, который смотрел видео): {what}
Главный момент: {moment}
Дословный текст ролика после монтажа:
{transcript}
Заголовок поверх видео: «{hook}»
Название YouTube: «{yt}»
Подпись TikTok: «{tt}»

Проверь строго:
• заголовок и названия описывают то, что реально происходит и говорится (не выдуманы события, люди, суммы, места);
• ролик понятен без контекста стрима, начинается не с середины мысли и не обрывается на полуслове;
• в нём есть смысл и пик, а не пересказ обычного разговора;
• ключевая фраза не выглядит как ошибка распознавания речи.
Если заголовок врёт или мимо — предложи исправленный (2–6 слов, до 30 символов, по фактам), иначе fix_hook пустой.
Ответ строго JSON: {{"ok":true,"title_matches":true,"makes_sense":true,"fix_hook":"","fix_title":"","problems":[]}}"""


BANNED_HOOKS = {"клиент открыл дверь, а там…", "охранник против курьера", "$3 за 40 минут езды", "ты вообще русский?",
                "заказ на $3 через весь город", "смотри, что было"}


def length_rule(cfg: dict) -> str:
    mx = int(float(cfg["clips"].get("max_seconds", 175)))
    return ("Длина — сколько держит внимание, обычно 15–45 с. Длиннее минуты — ТОЛЬКО если почти всё время интересно: "
            "история с интригой, развитие конфликта, нарастание, без провалов; тогда можно до " + str(mx) + " с. "
            "Если в середине пусто (молчание, ожидание, пересказ), а интересный ответ в конце — не растягивай: "
            "вырежи пустое (cuts) или начни ближе к развязке. Сомневаешься — короче.")


LENGTH_CHECK = """Ты — строгий монтажёр коротких роликов. Перед тобой фрагмент ({dur:.0f} с). Коллега хочет выпустить ролик
ДЛИННЕЕ МИНУТЫ: start={start:.1f} end={end:.1f}, вырезы {cuts}. Итоговая длина ≈ {kept:.0f} с.
Транскрипт (секунды от начала видео):
{transcript}
Смотри и слушай. Длинный ролик оправдан, только если зритель не заскучает ни на секунду: каждые 5–10 секунд
что-то происходит, есть интрига или нарастание до развязки. Если есть провисания — сократи: новые start/end
и вырезы пустых кусков (секунды от начала видео), чтобы ролик держал внимание от первой до последней секунды.
Развязку и смысл не теряй. Ответ строго JSON: {{"keep_long":false,"start":0.0,"end":0.0,"cuts":[[0.0,0.0]],"why":"…"}}"""


def check_length(llm: LLM, cfg: dict, preview: Path, words_rel: list[dict], start: float, end: float,
                 cuts: list, dur: float) -> dict:
    """Тщательная проверка ролика длиннее минуты: оправдана ли длина. → {"keep_long", "start", "end", "cuts", "why"}."""
    kept = (end - start) - sum(b - a for a, b in cuts)
    prompt = LENGTH_CHECK.format(dur=dur, start=start, end=end, cuts=cuts or "нет", kept=kept,
                                 transcript=words_to_timed_text(words_rel, every=2.5))
    model = (cfg.get("ai") or {}).get("video_model", "gemini-4-argon")
    return llm.media_json([("video/mp4", preview.read_bytes())], prompt, model=model,
                          fallback_models=["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"],
                          max_tokens=1500, schema=schemas.LENGTH, thinking="high")


def leaked(text: str) -> bool:
    """Модель скопировала пример из старого промпта или пустую заглушку."""
    t = (text or "").strip().lower().rstrip(".!")
    return t in BANNED_HOOKS or len(t) < 4


def freeze_report(video: Path) -> dict:
    """Зависания картинки (лаги записи) и чёрный экран по исходному fps — до того, как тратить ИИ."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(video), "-vf",
                        "freezedetect=n=0.0015:d=0.7,blackdetect=d=0.5:pix_th=0.06", "-an", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    err = r.stderr
    dur_m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    dur = (int(dur_m[1]) * 3600 + int(dur_m[2]) * 60 + float(dur_m[3])) if dur_m else 0.0
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end:\s*([\d.]+)", err)]
    frozen, spans = 0.0, []
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else dur
        frozen += max(0.0, b - a)
        spans.append([round(a, 1), round(b, 1)])
    black = sum(float(x) for x in re.findall(r"black_duration:\s*([\d.]+)", err))
    return {"duration": round(dur, 1), "frozen": round(frozen, 1), "frozen_frac": round(frozen / dur, 3) if dur else 0.0,
            "freezes": spans[:12], "black": round(black, 1)}


def tech_text(rep: dict) -> str:
    if not rep or not rep.get("duration"):
        return "нет данных"
    parts = [f"замирания картинки {rep['frozen']} с из {rep['duration']} с"]
    if rep.get("freezes"):
        parts.append("где: " + ", ".join(f"{a}–{b} с" for a, b in rep["freezes"][:6]))
    if rep.get("black"):
        parts.append(f"чёрный экран {rep['black']} с")
    return "; ".join(parts)


def preview_clip(src: Path, out: Path) -> Path:
    """Лёгкая версия для Gemini: 360p, 12 к/с, моно-звук — 1.5–4 МБ на минуту, влезает inline."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "scale=-2:360,fps=12",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "31", "-c:a", "aac", "-ac", "1", "-b:a", "48k",
                    "-movflags", "+faststart", str(out)], check=True, capture_output=True, timeout=600)
    return out


def direct(llm: LLM, cfg: dict, preview: Path, words_rel: list[dict], chat_rel: list[str], pre: dict,
           tech: dict) -> dict:
    model = (cfg.get("ai") or {}).get("video_model", "gemini-4-argon")
    prompt = DIRECTOR.format(dur=tech.get("duration") or 0, persona=cfg["streamer"]["persona"].strip(),
                             transcript=words_to_timed_text(words_rel, every=2.5), chat="; ".join(chat_rel[:14]) or "нет",
                             pre_score=pre.get("score", "?"), pre_why=str(pre.get("why", ""))[:200], tech=tech_text(tech),
                             scale=SCALE, style=STYLE_RULES, risk=RISK, length=length_rule(cfg))
    return llm.media_json([("video/mp4", preview.read_bytes())], prompt, model=model,
                          fallback_models=["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest"],
                          max_tokens=6000, schema=schemas.DIRECTOR, thinking="high")


def criticize(llm: LLM, cfg: dict, js: dict, words_final: list[dict], hook: str) -> dict:
    tr = " ".join(w["w"] for w in words_final)[:1800]
    prompt = CRITIC.format(what=js.get("what_happens", "")[:400], moment=js.get("moment", "")[:200], transcript=tr or "(речи нет)",
                           hook=hook, yt=(js.get("youtube") or {}).get("title", ""), tt=(js.get("tiktok") or {}).get("caption", ""))
    try:
        return llm.chat_json([{"role": "user", "content": prompt}], max_tokens=1200, schema=schemas.CRITIC, thinking="low")
    except LLMError as e:
        log(f"критик недоступен: {str(e)[:120]}")
        return {"ok": True, "skipped": True}


def apply_cuts(segs: list[tuple[float, float]], cuts: list[tuple[float, float]], min_piece: float = 0.6) -> list[tuple[float, float]]:
    """Вычесть вырезаемые куски из списка сегментов (всё в одной шкале времени)."""
    out = []
    for a, b in segs:
        pieces = [(a, b)]
        for c0, c1 in sorted(cuts):
            nxt = []
            for x, y in pieces:
                if c1 <= x or c0 >= y:
                    nxt.append((x, y))
                    continue
                if c0 > x:
                    nxt.append((x, c0))
                if c1 < y:
                    nxt.append((c1, y))
            pieces = nxt
        out += [(round(x, 2), round(y, 2)) for x, y in pieces if y - x >= min_piece]
    return out
