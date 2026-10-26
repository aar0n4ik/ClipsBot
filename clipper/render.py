"""Фирменный шаблон клипа 1080×1920. Одинаковая сетка в каждом ролике, меняется только содержимое.

Сетка снята с реального экрана TikTok (лента, 1080×1920 в координатах видео):
  0–240      верхние вкладки TikTok             — пусто
  250–480    ЗАГОЛОВОК-ХУК (1–2 строки, крупно, фиолетовый с белой обводкой)
  490–1300   ВИДЕО 4:3 (кроп 16:9 по центру: лицо крупнее, оверлеи стрима по краям отрезаются)
  1345–1450  СУБТИТРЫ (одна строка, всегда тут, текущее слово фиолетовое)
  1480–1560  ЛОГОТИП + ALBERT1MILLION (снизу по центру)
  1650+      ник, подпись и музыка TikTok        — пусто
  справа x>925 при y>1000 — кнопки лайк/коммент/репост — всё центральное держим в x 160…920
Фон — то же видео, размытое и затемнённое.
"""
from __future__ import annotations

import base64
import os
import re
from functools import lru_cache
from pathlib import Path

from .config import FONTS_DIR
from .util import ffprobe_json, run

W, H = 1080, 1920
TITLE_TOP, TITLE_MAX_W, TITLE_SIZES = 228, 880, (92, 85, 77, 72, 66)
VS_RE = re.compile(r"^(.+?)\s+vs\.?\s+(.+)$", re.I)
VS_SIZES = (80, 74, 68, 62)  # три строки (A / VS / B) должны уместиться над панелью
PANEL_Y, PANEL_H = 480, 960
SUB_CENTER, SUB_SIZE, SUB_MAX_W = 1312, 78, 760
BRAND_CENTER, BRAND_LOGO, BRAND_TEXT = 1512, 100, 58
BRAND_MAX_W = 700
NOTE_Y = PANEL_Y + 44
UI_BOTTOM = 1650          # отсюда начинается подпись TikTok
RIGHT_COL_X = 925         # кнопки справа (ниже y≈1000)

# ── шрифты: первый найденный по каждой роли ─────────────────────
FONT_ROLES = {
    "display": [("DelaGothicOne-Regular.ttf", "Dela Gothic One"), ("Montserrat-Black.ttf", "Montserrat Black"),
                ("/usr/share/fonts/opentype/inter/Inter-Black.otf", "Inter Black"),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu Sans")],
    "brand": [("Montserrat-BlackItalic.ttf", "Montserrat Black Italic"),
              ("/usr/share/fonts/opentype/inter/Inter-BlackItalic.otf", "Inter Black Italic"),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf", "DejaVu Sans")],
    "note": [("Montserrat-ExtraBold.ttf", "Montserrat ExtraBold"), ("Montserrat-Black.ttf", "Montserrat Black"),
             ("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf", "Inter ExtraBold"),
             ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu Sans")],
}


@lru_cache(maxsize=8)
def font(role: str) -> tuple[Path, str]:
    for file, fam in FONT_ROLES[role]:
        p = Path(file) if file.startswith("/") else FONTS_DIR / file
        if p.exists():
            return p, fam
    raise RuntimeError(f"Нет шрифта для «{role}» — запусти scripts/setup_tools.sh")


@lru_cache(maxsize=64)
def _pil_font(role: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(font(role)[0]), size)


@lru_cache(maxsize=8)
def _ass_k(role: str) -> float:
    asc, desc = _pil_font(role, 1000).getmetrics()
    return 1000 / (asc + desc)  # ASS-кегль = высота строки; PIL — кегль шрифта


def text_width(text: str, ass_size: float, role: str = "display", spacing: float = 0) -> float:
    return _pil_font(role, max(4, round(ass_size * _ass_k(role)))).getlength(text) + spacing * max(0, len(text) - 1)


# ── цвета ───────────────────────────────────────────────────────
def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def ass_color(rgb: tuple[int, int, int], alpha: int = 0) -> str:
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def mix(rgb, other, k):
    return tuple(round(a * (1 - k) + b * k) for a, b in zip(rgb, other))


# ── текст ───────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\", "").replace("{", "(").replace("}", ")")).strip()


def _no_dot(s: str) -> str:
    return re.sub(r"(?<!\.)\.$", "", s)


PROFANITY = re.compile(r"(?i)\b([а-яё]*?)(ху[йеёияюл]|пизд|[её]б[аеёиоуы]|[её]бл|бля|муд[аио]|пид[оа]р|залуп|сук[аи]\b|шлюх|г[ао]вн)([а-яё]*)")


def mask_profanity(word: str) -> str:
    def rep(m):
        whole = m.group(0)
        return whole[0] + "*" * max(1, len(whole) - 2) + (whole[-1] if len(whole) > 2 else "")
    return PROFANITY.sub(rep, word)


def balanced_lines(text: str, size: float, max_w: float, role: str = "display", spacing: float = 0) -> list[str] | None:
    """1 строка, если влезает; иначе 2 строки близкой ширины (без «висящих» предлогов)."""
    if text_width(text, size, role, spacing) <= max_w:
        return [text]
    words, best = text.split(), None
    for i in range(1, len(words)):
        l1, l2 = " ".join(words[:i]), " ".join(words[i:])
        w1, w2 = text_width(l1, size, role, spacing), text_width(l2, size, role, spacing)
        if w1 <= max_w and w2 <= max_w:
            cost = max(w1, w2) + (70 if len(words[i - 1]) <= 2 else 0)
            if best is None or cost < best[0]:
                best = (cost, [l1, l2])
    return best[1] if best else None


def fit_title(*candidates: str) -> tuple[str, list[str], int]:
    """(текст, строки, кегль): первый вариант, который влезает в 2 строки, с самым крупным кеглем.

    «X vs Y» — особый случай: X сверху, VS посередине, Y снизу, всё по центру.
    """
    for c in candidates:
        m = VS_RE.match(_esc(c or ""))
        if m:
            a, b = m.group(1).upper(), m.group(2).upper()
            for size in VS_SIZES:
                if max(text_width(x, size, spacing=1) for x in (a, b)) <= TITLE_MAX_W - 30:
                    return f"{a} VS {b}", [a, "VS", b], size
    for size in TITLE_SIZES:
        for c in candidates:
            c = _esc(c or "").upper()
            if c and (lines := balanced_lines(c, size, TITLE_MAX_W - 30, spacing=1)):
                return c, lines, size
    words = _esc(next((c for c in candidates if c), "")).upper().split()
    size = TITLE_SIZES[-1]
    while words:
        t = " ".join(words) + "…"
        if lines := balanced_lines(t, size, TITLE_MAX_W - 30, spacing=1):
            return t, lines, size
        words.pop()
        while len(words) > 1 and len(words[-1]) <= 2:
            words.pop()
    return "", [], size


def fit_hook(*candidates: str) -> str:  # совместимость со старым кодом
    return fit_title(*candidates)[0]


def chunk_words(words: list[dict], caps: bool = True, max_words: int = 3) -> list[list[dict]]:
    """Куски субтитров: каждый ГАРАНТИРОВАННО в одну строку внутри центральной зоны."""
    show = (lambda s: s.upper()) if caps else (lambda s: s)
    chunks, cur = [], []
    for i, w in enumerate(words):
        gap = w["s"] - words[i - 1]["e"] if i else 0
        cand = " ".join(show(mask_profanity(x["w"])) for x in cur + [w])
        too_wide = text_width(cand, SUB_SIZE * 1.08) + 20 > SUB_MAX_W
        if cur and (len(cur) >= max_words or too_wide or gap > 0.5 or re.search(r"[.!?…]$", cur[-1]["w"])):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _t(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000:d}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def build_ass(words: list[dict], dur: float, title_lines: list[str], title_size: int, cfg: dict,
              notes: list[dict] | None = None, en_lines: list[str] | None = None) -> str:
    cl = cfg["clips"]
    caps = cl.get("subtitle_caps", True)
    purple = _hex((cfg.get("branding") or {}).get("color", "#9146FF"))
    title_fill = mix(purple, (255, 255, 255), 0.12)
    dark = (20, 8, 42)
    P, Wt, Dk = ass_color(purple), ass_color((255, 255, 255)), ass_color(dark)
    disp_f, sub_f, note_f = font("display")[1], font("display")[1], font("note")[1]
    sub_mv = H - SUB_CENTER - SUB_SIZE // 2
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{disp_f},{title_size},{ass_color(title_fill)},&H000000FF,{Dk},&H8C000000,0,0,0,0,100,100,1,0,1,9,5,8,90,90,{TITLE_TOP},1
Style: Sub,{sub_f},{SUB_SIZE},{Wt},&H000000FF,{Dk},&H8C000000,0,0,0,0,100,100,1,0,1,7,3,2,160,160,{sub_mv},1
Style: SubEn,{note_f},44,&H00F4F4F4,&H000000FF,{Dk},&H8C000000,0,0,0,0,100,100,0,0,1,5,2,2,170,170,{sub_mv - 66},1
Style: Note,{note_f},42,{Wt},&H000000FF,{Dk},&H00000000,0,0,0,0,100,100,0,0,1,6,2,8,170,170,{NOTE_Y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if title_lines and cl.get("hook_overlay", True):
        ev.append(f"Dialogue: 4,{_t(0)},{_t(dur)},Title,,0,0,0,,"
                  r"{\fscx70\fscy70\t(0,110,\fscx106\fscy106)\t(110,190,\fscx100\fscy100)}" + r"\N".join(title_lines))
    for n in notes or []:
        s, txt = float(n["t"]), _esc(n.get("text", ""))[:42]
        if txt and 0 <= s < dur - 0.8:
            ev.append(f"Dialogue: 3,{_t(s)},{_t(min(dur, s + 2.6))},Note,,0,0,0,,{{\\fad(120,160)}}{txt}")
    if cl.get("subtitles", "ru") != "none" and words:
        chunks = chunk_words(words, caps)
        hi = r"{\1c" + P + r"\3c" + Wt + r"\fscx108\fscy108}"
        for ci, ch in enumerate(chunks):
            nxt = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else dur
            ch_end = min(nxt, ch[-1]["e"] + 0.3, dur)
            disp = [_esc(w["w"]).upper() if caps else _esc(w["w"]) for w in ch]
            for wi, w in enumerate(ch):
                s = w["s"] if wi else max(0.0, w["s"] - 0.05)
                e = ch[wi + 1]["s"] if wi + 1 < len(ch) else ch_end
                if e > s:
                    parts = [(hi + t + r"{\r}") if j == wi else t for j, t in enumerate(disp)]
                    pop = r"{\fscx82\fscy82\t(0,80,\fscx100\fscy100)}" if wi == 0 else ""
                    ev.append(f"Dialogue: 2,{_t(s)},{_t(e)},Sub,,0,0,0,,{pop}{' '.join(parts)}")
            if en_lines and ci < len(en_lines) and en_lines[ci]:
                en = _esc(en_lines[ci])
                if text_width(en, 44, "note") <= SUB_MAX_W:
                    ev.append(f"Dialogue: 1,{_t(max(0, ch[0]['s'] - 0.05))},{_t(ch_end)},SubEn,,0,0,0,,{en}")
    return head + "\n".join(ev) + "\n"


# ── плашка канала: [логотип] ALBERT1MILLION ─────────────────────
def brand_png(cfg: dict, out: Path) -> Path | None:
    from PIL import Image, ImageDraw, ImageFilter

    from .logo import find_logo, load_clean_logo
    br = cfg.get("branding") or {}
    text = (br.get("name") or "").strip()
    if not text:
        return None
    text = text.upper() if br.get("uppercase", True) else text
    purple = _hex(br.get("color", "#9146FF"))
    S = 3  # суперсэмплинг — ровные края
    size = BRAND_TEXT
    f = _pil_font("brand", size * S)
    while f.getlength(text) / S + BRAND_LOGO + 18 > BRAND_MAX_W and size > 30:
        size -= 2
        f = _pil_font("brand", size * S)
    tw = int(f.getlength(text) / S)
    lp = find_logo(cfg)
    has_logo = lp is not None
    lw = BRAND_LOGO if has_logo else 0
    gap = 16 if has_logo else 0
    width, height = lw + gap + tw + 8, max(BRAND_LOGO, size + 20)
    pad = 24
    img = Image.new("RGBA", ((width + 2 * pad) * S, (height + 2 * pad) * S), (0, 0, 0, 0))
    if has_logo:
        lg = load_clean_logo(str(lp)).copy()
        lg.thumbnail((BRAND_LOGO * S, BRAND_LOGO * S), Image.LANCZOS)
        ring = Image.new("RGBA", (BRAND_LOGO * S + 8 * S, BRAND_LOGO * S + 8 * S), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse([0, 0, ring.width - 1, ring.height - 1], fill=(255, 255, 255, 255))
        ly = pad * S + (height * S - lg.height) // 2  # высота строки = height, логотип по её центру
        if abs(lg.width - lg.height) < 6:  # круглый значок — тонкое белое кольцо отделяет его от фона
            img.alpha_composite(ring, (pad * S - 4 * S + (BRAND_LOGO * S - lg.width) // 2, ly - 4 * S))
        img.alpha_composite(lg, (pad * S + (BRAND_LOGO * S - lg.width) // 2, ly))
    d = ImageDraw.Draw(img)
    bbox = f.getbbox(text)
    y = pad * S + (height * S - (bbox[3] + bbox[1])) // 2
    d.text(((pad + lw + gap) * S, y), text, font=f, fill=(255, 255, 255, 255))
    img = img.resize((width + 2 * pad, height + 2 * pad), Image.LANCZOS)
    a = img.getchannel("A")
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v * 0.75)))
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    base.alpha_composite(shadow, (0, 4))
    base.alpha_composite(img)
    base.save(out)
    return out


# ── видео ───────────────────────────────────────────────────────
def probe(src: Path) -> tuple[int, int, bool]:
    info = ffprobe_json(src)
    w = h = 0
    has_audio = False
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not w:
            w, h = int(s["width"]), int(s["height"])
        if s.get("codec_type") == "audio":
            has_audio = True
    return w, h, has_audio


def map_time(t_src: float, segments: list[tuple[float, float]]) -> float | None:
    off = 0.0
    for a, b in segments:
        if a <= t_src < b:
            return off + t_src - a
        off += b - a
    return None


def words_to_output(words_src: list[dict], segments: list[tuple[float, float]]) -> list[dict]:
    out, off = [], 0.0
    for a, b in segments:
        for w in words_src:
            if a - 0.05 <= w["s"] < b - 0.08:
                out.append({"w": w["w"], "s": round(off + w["s"] - a, 2), "e": round(off + min(w["e"], b) - a, 2)})
        off += b - a
    return out


def render_clip(src: Path, segments: list[tuple[float, float]], words_src: list[dict], title: str | tuple,
                cfg: dict, out: Path, *, punches: list[float] | None = None, notes: list[dict] | None = None,
                variant: dict | None = None, audio_override: Path | None = None,
                en_lines: list[str] | None = None, punch_at: float | None = None,
                pan_keys: list | None = None) -> Path:
    """segments — куски исходника в порядке показа ([холодное открытие], основной);
    words_src, punches — во времени исходника; notes — во времени итогового ролика."""
    variant = variant or {}
    cl = {**cfg["clips"], **{k: v for k, v in variant.items() if k in ("subtitles",)}}
    cfg = {**cfg, "clips": cl}
    sw, sh, has_audio = probe(src)
    dur = sum(b - a for a, b in segments)
    words = words_to_output(words_src, segments)
    if isinstance(title, tuple):
        _, lines, tsize = title
    else:
        _, lines, tsize = fit_title(title) if title else ("", [], TITLE_SIZES[0])

    work = out.parent
    ass = work / (out.stem + ".ass")
    ass.write_text(build_ass(words, dur, lines, tsize, cfg, notes, en_lines), encoding="utf-8")
    badge = brand_png(cfg, work / "brand.png")

    layout = cl.get("layout", "auto")
    if layout == "auto":
        layout = "vertical" if sh > sw * 1.2 else "panel"
    fw, fh, fg_y = (W, H, 0) if layout == "vertical" else (W, PANEL_H, PANEL_Y)
    asp = fw / fh
    crop_frac = min(1.0, (sh * asp) / sw) if sw else 1.0
    keys = pan_keys
    if keys is None and layout == "panel" and crop_frac < 0.98:
        from .framing import static_crop
        keys = static_crop(src, segments[0][0], segments[-1][1], crop_frac) if cl.get("follow_subject", False) else None
    from .framing import x_expr
    fc = []
    audio = has_audio or audio_override is not None
    # каждый кусок — отдельный вход (-ss/-t): ffmpeg не копит кадры одного куска, пока ждёт очереди
    inputs, seg_in = [], []
    for a, b in segments:
        inputs.append({"path": src.resolve(), "ss": a, "t": b - a})
        vi = len(inputs) - 1
        if audio_override:
            inputs.append({"path": audio_override.resolve(), "ss": a, "t": b - a})
            ai = len(inputs) - 1
        else:
            ai = vi if has_audio else None
        seg_in.append((vi, ai))
    n_seg = len(segments)
    for i, (a, b) in enumerate(segments):
        vi, ai = seg_in[i]
        keys_local = [(ta - a, va) for ta, va in keys] if keys else None  # ключи — во времени куска
        xe = x_expr(keys_local, 0.0, crop_frac) if keys_local else "(iw-ow)/2"
        fc.append(f"[{vi}:v]setpts=PTS-STARTPTS,fps=30,"
                  f"crop=w='min(iw\\,ih*{asp:.4f})':h='min(ih\\,iw/{asp:.4f})':x='{xe}':y='(ih-oh)/2',"
                  f"scale={fw}:{fh},setsar=1,format=yuv420p[v{i}]")
        if audio and ai is not None:
            d = b - a
            fade = f",afade=t=in:d=0.025,afade=t=out:st={max(0.0, d - 0.04):.3f}:d=0.04" if n_seg > 1 and d > 0.3 else ""
            fc.append(f"[{ai}:a]asetpts=PTS-STARTPTS{fade}[a{i}]")
    n = len(segments)
    fc.append("".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(n))
              + f"concat=n={n}:v=1:a={1 if audio else 0}[fgc]" + ("[ac]" if audio else ""))
    fc.append("[fgc]split=2[ba][fg]")
    fc.append("[ba]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=16:3,"
              f"scale={W}:{H},eq=brightness=-0.22:saturation=1.1[bg]")
    fc.append(f"[bg][fg]overlay=x=0:y={fg_y}[v0]")
    last = "v0"
    if variant.get("progress_bar") and layout != "vertical":
        purple = (cfg.get("branding") or {}).get("color", "#9146FF").lstrip("#")
        fc.append(f"color=c=0x{purple}:s={W}x8:r=30,format=yuv420p[bar]")
        fc.append(f"[{last}][bar]overlay=x='-w+w*t/{dur:.2f}':y={PANEL_Y + PANEL_H - 8}:shortest=1[vp]")
        last = "vp"
    if badge:
        bidx = len(inputs)
        inputs.append({"path": badge.resolve(), "ss": None, "t": None})
        fc.append(f"[{last}][{bidx}:v]overlay=x=(W-w)/2:y={BRAND_CENTER}-h/2[vb]")
        last = "vb"
    fc.append(f"[{last}]ass={ass.name}:fontsdir={FONTS_DIR.as_posix()},format=yuv420p[vout]")
    if audio:
        fc.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[aout]")

    cmd = ["ffmpeg", "-v", "error", "-y"]
    for inp in inputs:
        if inp["ss"] is not None:
            cmd += ["-ss", f"{inp['ss']:.3f}", "-t", f"{inp['t']:.3f}"]
        cmd += ["-i", inp["path"]]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]"]
    if audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "14M",
            "-bufsize", "28M", "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out.resolve()]
    prev = os.getcwd()
    os.chdir(work)  # ass-фильтр читает файл относительно текущей папки
    try:
        run(cmd, timeout=1800)
    finally:
        os.chdir(prev)
    return out


def thumb_b64(video: Path, at: float = 1.0, width: int = 240) -> str:
    jpg = video.with_suffix(".thumb.jpg")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "7", jpg], quiet=True)
    return "data:image/jpeg;base64," + base64.b64encode(jpg.read_bytes()).decode()


def extract_frames(video: Path, times: list[float], out_dir: Path) -> list[tuple[float, Path]]:
    out = []
    for t in times:
        p = out_dir / f"{video.stem}_{int(t * 10)}.jpg"
        try:
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.2f}", "-i", video, "-frames:v", "1",
                 "-vf", "scale=512:-2", "-q:v", "6", p], quiet=True)
            if p.exists():
                out.append((t, p))
        except RuntimeError:
            pass
    return out
