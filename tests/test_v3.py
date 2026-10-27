"""Тесты обучения, ранней тревоги, планировщика, звука, логотипа и шаблона: python tests/test_v3.py"""
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipper.config import load_config  # noqa: E402

CFG = load_config(ROOT / "config.yaml")


def _store():
    from clipper.store import Store
    return Store(Path(tempfile.mkdtemp()))


def _iso(t):
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fake_history(store, n_posts, effect, dims_fn, seed=1, platform="tiktok", acc="tt"):
    """Смоделированный аккаунт: n роликов; у стиля хука «number» — множитель effect к просмотрам."""
    rng = np.random.default_rng(seed)
    now = dt.datetime.now(dt.timezone.utc)
    vids = {}
    for i in range(n_posts):
        t = now - dt.timedelta(hours=60 + (n_posts - i) * 7)
        var = dims_fn(i)
        mult = effect if var.get("hook_style") == "number" else 1.0
        v48 = float(np.exp(rng.normal(np.log(1500), 0.6)) * mult)
        ct = int(t.timestamp())
        vids[str(i)] = {"id": str(i), "create_time": ct, "views": int(v48 * 1.2), "ts": [[ct + 48 * 3600, v48]],
                        "history": {}}
        store.write_json(f"queue/c{i}.json", {
            "id": f"c{i}", "created_at": _iso(t), "category": "funny", "score": 6,
            "targets": {platform: {"variant": var, "duration": 25}},
            "posts": {platform: {"account": acc, "video_id": str(i), "status": "posted", "posted_at": _iso(t)}}})
    store.write_json("stats.json", {"accounts": {acc: {"platform": platform, "videos": vids}}})


def test_learning_ignores_noise_on_small_data():
    from clipper import learn
    st = _store()
    styles = ["tease", "conflict", "number", "quote"]
    _fake_history(st, 10, 1.0, lambda i: {"hook_style": styles[i % 4]})
    cfg = {**CFG, "accounts": [{"id": "tt", "platform": "tiktok"}]}
    learn.update(st, cfg)
    pol = learn.update(st, cfg)
    shares = learn.get(pol, "arms.tiktok.hook_style")
    assert all(abs(v - 0.25) < 1e-6 for v in shares.values()), shares   # по 10 роликам ничего не меняем
    assert not [d for d in (st.read_json("decisions.json", []) or []) if d["kind"] == "arms"]


def test_learning_finds_real_effect_logs_and_reverts():
    from clipper import learn
    st = _store()
    styles = ["tease", "conflict", "number", "quote"]
    _fake_history(st, 120, 2.5, lambda i: {"hook_style": styles[i % 4]}, seed=3)
    cfg = {**CFG, "accounts": [{"id": "tt", "platform": "tiktok"}]}
    learn.update(st, cfg)                       # первый проход: стартовые доли
    pol = learn.update(st, cfg)                 # второй: изменение с записью в журнал
    shares = learn.get(pol, "arms.tiktok.hook_style")
    assert shares["number"] > 0.5 and min(shares.values()) >= 0.099, shares   # победитель, но исследование живо
    dec = [d for d in st.read_json("decisions.json") if d["kind"] == "arms"]
    assert dec and "цифра" in dec[-1]["summary"] and dec[-1]["reversible"]
    st.write_json("control/commands.json", [{"id": "x1", "cmd": "revert", "decision": dec[-1]["id"]}])
    pol = learn.update(st, cfg)
    assert learn.get(pol, "arms.tiktok.hook_style") == dec[-1]["before"]
    assert "arms.tiktok.hook_style" in pol["pins"]
    assert any(d["kind"] == "revert" for d in st.read_json("decisions.json"))
    assert "x1" in st.read_json("control/done.json")


def test_early_warning_cusum():
    from clipper.health import account_signals
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    rng = np.random.default_rng(5)
    vids = []
    for i in range(30):
        ct = now - (30 - i) * 8 * 3600
        x2 = float(np.exp(rng.normal(np.log(400), 0.3)))
        if i >= 25:
            x2 /= 12   # последние 5 роликов в первые 2 часа почти не показывают
        vids.append({"create_time": ct, "ts": [[ct + 2 * 3600, x2]], "views": x2 * 4})
    sig = account_signals(vids, now)
    assert sig["cusum"] >= 3 and sig["recent_low"] >= 3, sig
    assert account_signals(vids[:24], now)["cusum"] < 3


def test_legacy_clip_normalized():
    from clipper.clips import normalize, overall, pending_for
    c = normalize({"id": "x", "asset": "x.mp4", "overlay": "hi", "caption": "c", "status": "inbox", "account": "main",
                   "tiktok_id": "9", "posted_at": "2026-10-17T10:00:00Z", "created_at": "2026-10-17T09:00:00Z"})
    assert c["posts"]["tiktok"]["video_id"] == "9" and overall(c) == "inbox" and not pending_for(c, "tiktok")


def test_logo_cleanup_removes_fake_checkerboard():
    from PIL import Image, ImageDraw

    from clipper.logo import load_clean_logo
    im = Image.new("RGB", (400, 400), "white")
    d = ImageDraw.Draw(im)
    for y in range(0, 400, 20):
        for x in range(0, 400, 20):
            if (x // 20 + y // 20) % 2:
                d.rectangle([x, y, x + 19, y + 19], fill=(222, 222, 222))
    d.ellipse([50, 50, 350, 350], fill=(145, 70, 255))
    d.rectangle([150, 130, 250, 250], fill="white")
    p = Path(tempfile.mkdtemp()) / "logo.jpg"
    im.save(p, quality=92)
    lg = load_clean_logo(str(p))
    a = np.asarray(lg)[..., 3]
    assert lg.size[0] < 320 and a[0, 0] == 0 and a[a.shape[0] // 2, a.shape[1] // 2] == 255
    assert np.asarray(lg)[a.shape[0] // 2, a.shape[1] // 2][:3].min() > 240   # белое внутри не съели


def test_music_detector_and_muted():
    from clipper.audio import music_score, muted_fraction
    sr = 16000
    t = np.arange(sr * 10) / sr
    rng = np.random.default_rng(0)
    music = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330, 440)) * 0.08
    speech = np.zeros_like(t)
    pos = 0
    while pos < len(t) - sr // 3:
        L = int(sr * rng.uniform(0.08, 0.25))
        tt = np.arange(L) / sr
        f0 = rng.uniform(100, 220)
        speech[pos:pos + L] += sum(np.sin(2 * np.pi * f0 * k * tt) / k for k in range(1, 10)) * np.hanning(L) * 0.2
        pos += L + int(sr * rng.uniform(0.03, 0.35))
    n = rng.normal(0, 0.02, len(t))
    assert music_score((music + n).astype(np.float32))["score"] > 0.6
    assert music_score((speech + n).astype(np.float32))["score"] < 0.3
    m = speech.copy()
    m[sr * 2:sr * 5] = 0
    assert muted_fraction(m.astype(np.float32)) > 0.25


def test_render_template_and_validation():
    from PIL import Image

    from clipper import render as R
    from clipper.qa import validate_render
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / "src.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=16",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=16", "-shortest", "-c:v", "libx264",
                        "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
        words = [{"w": w, "s": 1 + i * 0.45, "e": 1 + i * 0.45 + 0.4}
                 for i, w in enumerate("короче клиент открывает дверь и говорит мне такое что я просто упал на месте".split())]
        out = d / "out" / "clip.mp4"
        out.parent.mkdir()
        title = R.fit_title("Клиент открыл дверь и сказал такое что я упал прямо на пороге", "Клиент выдал такое")
        assert title[1] and len(title[1]) <= 2
        R.render_clip(src, [(5.0, 6.8), (1.0, 9.0)], words, title, CFG, out,
                      notes=[{"t": 2.0, "text": "Заказ на $3"}], variant={"progress_bar": True},
                      pan_keys=[(1.0, 0.35), (3.0, 0.35), (4.2, 0.6)])
        assert validate_render(out, 9.8, "tiktok") == []
        for ch in R.chunk_words(words):
            assert R.text_width(" ".join(R.mask_profanity(x["w"]) for x in ch), R.SUB_SIZE, R.TEXT_ROLE) + 20 <= R.SUB_MAX_W
        b = Image.open(out.parent / "brand.png")
        assert b.width <= R.BRAND_MAX_W + 60 and R.BRAND_CENTER + b.height / 2 < R.UI_BOTTOM
        assert R.mask_profanity("блять") == "б***ь" and R.mask_profanity("привет") == "привет"


def test_pan_is_calm_and_smooth():
    """Камера стоит на месте при коротком скачке и плавно едет при устойчивом уходе в сторону."""
    from clipper.framing import plan_pan, x_expr
    steady = [(i * 0.5, 0.25 if i * 0.5 < 4 else 0.75, 0.2) for i in range(24)]
    keys = plan_pan(steady, 0, 12, 0.6)
    assert len(keys) == 3 and keys[2][1] > keys[0][1] and keys[2][0] - keys[1][0] >= 1.0   # один плавный переезд
    blip = [(i * 0.5, 0.75 if 4 <= i * 0.5 < 5 else 0.25, 0.2) for i in range(24)]
    assert len(plan_pan(blip, 0, 12, 0.6)) == 1                                            # короткий скачок игнорим
    e = x_expr(keys, 0, 0.6)
    assert "," not in e.replace("\\,", "") and "zoompan" not in e                         # запятые экранированы, зумов нет


def test_music_is_kept():
    import tempfile as tf

    import numpy as np
    from clipper.audio import inspect_clip_audio
    sr = 16000
    t = np.arange(sr * 8) / sr
    music = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) * 0.1).astype(np.float32)
    d = Path(tf.mkdtemp())
    wav = d / "a.wav"
    import wave
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((music * 32767).astype("<i2").tobytes())
    res = inspect_clip_audio(wav, 0, 8, d, CFG)
    assert res["action"] == "flag" and res["audio_override"] is None    # помечаем, но звук не трогаем


def test_hook_opening_trim():
    from clipper.qa import plan_opening
    words = [{"w": "ну", "s": 3.0, "e": 3.2}, {"w": "смотри", "s": 3.3, "e": 3.6}] + \
            [{"w": "x", "s": 4 + i * 0.4, "e": 4.3 + i * 0.4} for i in range(40)]
    s, rep = plan_opening(words, 1.0, 25.0, CFG)
    assert abs(s - 2.85) < 0.01 and rep["speech_start"] == 0.15


def test_target_texts_per_platform_differ():
    from clipper.judge import target_texts
    ed = {"hooks": [{"style": "tease", "text": "Клиент открыл дверь, а там…"}, {"style": "number", "text": "$3 за 40 минут"}],
          "pick": 0, "tiktok": {"caption": "доставка в сша — жесть!!!", "hashtags": ["fyp", "доставка"]},
          "youtube": {"title": "Курьер в Америке получил $3", "description": "ночная смена", "tags": ["курьер"]},
          "instagram": {"caption": "а вы бы поехали?", "hashtags": ["#la", "#курьер"]}}
    tt = target_texts(ed, "tiktok", "number", CFG)
    yt = target_texts(ed, "youtube", "tease", CFG)
    assert tt["hook"] == "$3 за 40 минут" and "—" not in tt["caption"] and "#fyp" not in tt["hashtags"]
    assert yt["hook"].startswith("Клиент") and "#shorts" in yt["description"] and "twitch.tv/albert1million" in yt["description"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("✅", name)
            except Exception as e:  # noqa: BLE001
                import traceback
                fails += 1
                print("❌", name, repr(e)[:600])
                traceback.print_exc(limit=3)
    sys.exit(1 if fails else 0)
