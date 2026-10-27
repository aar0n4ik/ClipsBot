"""v4: мозг отбора (разведчик/режиссёр/критик), монтаж одним файлом, релизы на все площадки, настройки и выключатели.
python tests/test_v4.py"""
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipper.config import load_config  # noqa: E402
from clipper.store import Store  # noqa: E402

CFG = load_config(ROOT / "config.yaml")


def _store():
    return Store(Path(tempfile.mkdtemp()))


def _iso(t):
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _video(path: Path, dur: float, freeze_from: float | None = None):
    """Синтетический «стрим»: двигающаяся картинка + тон. freeze_from — с этой секунды картинка замирает (лаг)."""
    vdur = dur if freeze_from is None else max(0.3, min(dur, freeze_from))
    vf = ["-vf", f"tpad=stop_mode=clone:stop_duration={dur - vdur:.2f}"] if vdur < dur else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={vdur:.2f}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur:.2f}"] + vf
                   + ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", f"{dur:.2f}", str(path)], check=True)
    return path


# ── настройки и выключатели ─────────────────────────────────────
def test_settings_clamped_and_applied():
    from clipper import settings
    st = _store()
    st.write_json(settings.SETTINGS, {"values": {"posting.daily_max": 99, "quality.post_min": "8", "ai.video_model": "evil",
                                                 "quality.reserve_target": 99, "platforms.instagram": False,
                                                 "junk.key": 1}})
    cfg = json.loads(json.dumps(CFG))
    v = settings.apply(cfg, st)
    assert v["posting.daily_max"] == 12 and cfg["posting"]["daily_max"] == 12      # зажато в границы
    assert cfg["quality"]["post_min"] == 8
    assert cfg["ai"]["video_model"] == "gemini-4-argon"                             # мусор → по умолчанию
    assert cfg["quality"]["reserve_target"] == 60                                  # зажато в границы
    assert "instagram" not in cfg["platforms"] and "tiktok" in cfg["platforms"]
    assert "junk.key" not in v
    st.write_json(settings.SWITCHES, {"post": True, "note": "тест"})
    assert settings.stopped(st, "post") and not settings.stopped(st, "process")


# ── мозг: мелкие кирпичи ───────────────────────────────────────
def test_brain_helpers():
    from clipper import brain
    assert brain._ts("1:02:03") == 3723 and brain._ts("12:05") == 725 and brain._ts(42) == 42.0 and brain._ts("x") is None
    assert brain.leaked("Клиент открыл дверь, а там…") and not brain.leaked("Забыл оплатить парковку")
    segs = brain.apply_cuts([(0.0, 10.0), (12.0, 20.0)], [(3.0, 5.0), (11.0, 13.0), (19.8, 25)])
    assert segs == [(0.0, 3.0), (5.0, 10.0), (13.0, 19.8)], segs
    from clipper.signals import PATTERNS
    msgs = [{"t": 100 + i, "text": "АХАХАХ кек", "emotes": []} for i in range(20)] + [{"t": 400, "text": "норм", "emotes": []}]
    dg = brain.chat_digest(msgs, 0, 600, PATTERNS)
    assert "1:" not in dg.split("\n")[0] and "0:01" in dg and "АХАХАХ" in dg


def test_freeze_detects_lag():
    from clipper import brain
    with tempfile.TemporaryDirectory() as d:
        ok = _video(Path(d) / "ok.mp4", 8)
        bad = _video(Path(d) / "bad.mp4", 8, freeze_from=2.0)
        r1, r2 = brain.freeze_report(ok), brain.freeze_report(bad)
        assert r1["frozen_frac"] < 0.1, r1
        assert r2["frozen_frac"] > 0.5, r2


def test_static_camera_never_moves():
    from clipper import framing
    with tempfile.TemporaryDirectory() as d:
        v = _video(Path(d) / "v.mp4", 6)
        keys = framing.static_crop(v, 0, 6, 0.6)
        assert len(keys) == 1 and keys[0][1] == 0.5


# ── режиссёр → монтаж одним файлом → очередь ───────────────────
class FakeLLM:
    def __init__(self, director: dict, critic: dict):
        self.director, self.critic, self.calls = director, critic, []

    def media_json(self, media, prompt, **kw):
        self.calls.append(("media", kw.get("model")))
        assert media[0][0] == "video/mp4" and len(media[0][1]) > 1000
        return self.director

    def chat_json(self, messages, **kw):
        self.calls.append(("chat", None))
        return self.critic

    def totals(self):
        return {}

    def delta(self, before):
        return {"by_model": {}, "usd": 0.0}


def _words(n=60, step=0.5):
    text = ("короче я забыл оплатить парковку и тут подходит охранник и говорит штраф двести долларов я такой "
            "в смысле двести я тут пять минут стоял").split()
    return [{"w": text[i % len(text)], "s": round(3 + i * step, 2), "e": round(3 + i * step + 0.4, 2)} for i in range(n)]


def _patch_pipeline(monkey, d: Path, freeze_from=None):
    import clipper.pipeline as P
    from clipper import releases

    def fake_download(vod_id, start, end, out, max_height=None):
        return _video(out.with_suffix(".mp4"), round(end - start, 2), None if freeze_from is None else max(0.5, freeze_from - start))
    monkey(P, "download_video", fake_download)
    monkey(releases, "upload", lambda path: path.name)
    monkey(releases, "delete", lambda name: None)


def _monkey():
    saved = []

    def m(obj, name, val):
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, val)

    def undo():
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)
    return m, undo


def _cand():
    return {"id": "c0", "ctx_start": 1000.0, "ctx_dur": 40.0, "peak_in_ctx": 20, "peak_abs": 1020.0, "signal": 2.0,
            "breakdown": {"chat": 1, "keywords": 1, "spam_wave": 0, "audio": 1, "viewer_clips": 0},
            "chat_sample": ["[+2с] u: АХАХ"], "chat_count": 30, "words": _words()}


DIRECTOR_OK = {"verdict": "post", "score": 8, "subscores": {"hook": 8}, "what_happens": "Стример забыл оплатить парковку, охранник выписывает штраф 200 долларов",
               "moment": "реакция на штраф 200 долларов", "technical": {"lag": 0, "issues": []}, "start": 1.0, "end": 26.0,
               "cuts": [[10.0, 12.5]], "standalone": True, "category": "money", "risk": {"level": 0, "flags": []},
               "hooks": [{"style": "tease", "text": "Охранник против курьера"}, {"style": "number", "text": "Штраф $200 за 5 минут"},
                         {"style": "quote", "text": "В смысле двести?"}, {"style": "conflict", "text": "Курьер и парковка"}],
               "pick": 1, "tiktok": {"caption": "штраф за парковку в сша двести долларов", "hashtags": ["#сша", "#парковка"]},
               "youtube": {"title": "Штраф за парковку в США: 200 долларов", "description": "охранник и штраф", "tags": ["сша"]},
               "instagram": {"caption": "а вам выписывали штраф?", "hashtags": ["#сша"]}, "comment": "сколько у вас штраф?"}


def test_director_reject_and_lag_are_recorded():
    import clipper.pipeline as P
    m, undo = _monkey()
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _patch_pipeline(m, d)
            st = _store()
            vod = {"id": "v1", "title": "t", "created_at": "2026-10-25T00:00:00Z"}
            llm = FakeLLM({**DIRECTOR_OK, "verdict": "reject", "reject_reason": "ничего не происходит"}, {"ok": True})
            assert P._review_on_video(CFG, st, llm, vod, _cand(), {"score": 7, "why": "x"}, 3, 30, d) is None
            rej = st.read_json(P.FUNNEL)["rejected"]
            assert rej[-1]["stage"] == "видео" and "ничего не происходит" in rej[-1]["reason"]
            llm2 = FakeLLM({**DIRECTOR_OK, "score": 6}, {"ok": True})
            assert P._review_on_video(CFG, st, llm2, vod, _cand(), {"score": 7}, 3, 30, d) is None   # ниже порога после видео
            assert "оценка 6" in st.read_json(P.FUNNEL)["rejected"][-1]["reason"]
            undo()
            m, undo = _monkey()
            _patch_pipeline(m, d, freeze_from=1004.0)         # запись зависла
            llm3 = FakeLLM(DIRECTOR_OK, {"ok": True})
            assert P._review_on_video(CFG, st, llm3, vod, _cand(), {"score": 8}, 3, 30, d) is None
            assert "лаги" in st.read_json(P.FUNNEL)["rejected"][-1]["reason"] and not llm3.calls      # ИИ даже не тратили
    finally:
        undo()


def test_full_clip_one_file_all_platforms_no_cold_open():
    import clipper.pipeline as P
    from clipper import learn
    m, undo = _monkey()
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _patch_pipeline(m, d)
            st = _store()
            vod = {"id": "v1", "title": "t", "created_at": "2026-10-25T00:00:00Z"}
            llm = FakeLLM(DIRECTOR_OK, {"ok": True, "title_matches": True, "makes_sense": True})
            plan = P._review_on_video(CFG, st, llm, vod, _cand(), {"score": 7, "why": "x"}, 3, 30, d)
            assert plan and plan["score"] == 8 and plan["cuts"], plan
            ok = P.make_clip(CFG, st, llm, learn.default_policy(CFG), vod, plan, ["tiktok", "youtube", "instagram"], d)
            assert ok
            q = st.list_json("queue")[0]
            assets = {t["asset"] for t in q["targets"].values()}
            assert len(assets) == 1 and set(q["targets"]) == {"tiktok", "youtube", "instagram"}   # один файл на всё
            hooks = {t["hook"] for t in q["targets"].values()}
            assert len(hooks) == 1 and "Охранник против курьера" not in hooks                  # пример из промпта не прошёл
            assert q["brain"]["video"]["verdict"] == "post" and q["brain"]["cuts"] >= 1
            assert q["duration"] < 25                                                            # паузы вырезаны
            assert all("cold_open" not in (t.get("variant") or {}) for t in q["targets"].values())
    finally:
        undo()


def test_critic_blocks_lying_title():
    import clipper.pipeline as P
    from clipper import learn
    m, undo = _monkey()
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _patch_pipeline(m, d)
            st = _store()
            vod = {"id": "v1", "title": "t", "created_at": "2026-10-25T00:00:00Z"}
            llm = FakeLLM(DIRECTOR_OK, {"ok": False, "title_matches": False, "makes_sense": True, "fix_hook": "",
                                        "problems": ["в ролике нет грабителя"]})
            plan = P._review_on_video(CFG, st, llm, vod, _cand(), {"score": 7}, 3, 30, d)
            assert not P.make_clip(CFG, st, llm, learn.default_policy(CFG), vod, plan, ["tiktok"], d)
            assert "грабителя" in st.read_json(P.FUNNEL)["rejected"][-1]["reason"]
            llm2 = FakeLLM(DIRECTOR_OK, {"ok": False, "title_matches": False, "makes_sense": True,
                                         "fix_hook": "Штраф за парковку $200"})
            plan = P._review_on_video(CFG, st, llm2, vod, {**_cand(), "id": "c1", "ctx_start": 2000.0}, {"score": 7}, 3, 30, d)
            assert P.make_clip(CFG, st, llm2, learn.default_policy(CFG), vod, plan, ["tiktok"], d)
            assert st.list_json("queue")[0]["overlay"] == "Штраф за парковку $200"
    finally:
        undo()


# ── релизы: одно видео на все площадки одновременно ────────────
class FakeClient:
    published: list = []

    def __init__(self, store, acc):
        self.acc = acc

    def connected(self):
        return True

    def check(self, p):
        return p

    def publish(self, path, target, cfg, clip):
        FakeClient.published.append((self.acc["platform"], clip["id"]))
        if self.acc["platform"] == "tiktok":
            return {"status": "inbox", "publish_id": "p"}
        return {"status": "posted", "video_id": f"{self.acc['platform']}-{clip['id']}", "url": "u"}


def _post_env(m, now):
    import clipper.clips as C
    import clipper.poster as P
    from clipper import releases
    m(P, "now_utc", lambda: now)
    m(C, "now_utc", lambda: now)
    m(P, "client", lambda store, acc: FakeClient(store, acc))
    m(releases, "download", lambda name, out: Path("/dev/null"))
    m(releases, "delete", lambda name: None)
    FakeClient.published = []


def _clip(cid, score, made, vod_time=100, cat="money", live=False):
    t = {"asset": f"{cid}.mp4", "status": "ready", "hook": cid}
    return {"id": cid, "score": score, "created_at": _iso(made), "category": cat, "vod_id": "v", "vod_time": vod_time,
            "overlay": cid, "live_when_made": live, "targets": {p: dict(t) for p in ("tiktok", "youtube", "instagram")}, "posts": {}}


def test_release_goes_to_all_platforms_and_respects_rules():
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)   # 19:07 МСК — вечер
    try:
        _post_env(m, now)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"]["planner"] = False
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=2)))
        st.write_json("queue/weak.json", _clip("weak", 6, now - dt.timedelta(hours=1), vod_time=5000))
        st.write_json("queue/old.json", _clip("old", 8, now - dt.timedelta(hours=40), vod_time=9000))
        P.cmd_post(cfg, st)
        assert sorted(FakeClient.published) == [("instagram", "a"), ("tiktok", "a"), ("youtube", "a")], FakeClient.published
        assert st.read_json("queue/old.json")["targets"]["tiktok"]["status"] == "ready"        # v6: клип не сгорает
        ps = st.read_json("status/post.json")
        assert ps["accounts"]["tt_main"]["today"]["drafts"] == 0                               # счётчик до публикации
        assert ps["releases"]["by_day"]["2026-10-25"] == 1 and len(ps["schedule"]["hours"]) == 4
        # следующий слот: уходит вчерашний сильный клип; слабый не выходит никогда
        FakeClient.published = []
        m(P, "now_utc", lambda: now + dt.timedelta(hours=3))
        import clipper.clips as C
        m(C, "now_utc", lambda: now + dt.timedelta(hours=3))
        P.cmd_post(cfg, st)
        assert sorted(FakeClient.published) == [("instagram", "old"), ("tiktok", "old"), ("youtube", "old")], FakeClient.published
        FakeClient.published = []
        m(P, "now_utc", lambda: now + dt.timedelta(hours=6))
        m(C, "now_utc", lambda: now + dt.timedelta(hours=6))
        P.cmd_post(cfg, st)
        assert not FakeClient.published
        assert "качества" in st.read_json(P.BRAIN)["last"]["reason"]
        tt = st.read_json("status/post.json")["accounts"]["tt_main"]
        assert tt["drafts_by_day"]["2026-10-25"] == 2                                         # TikTok — черновик, честно
    finally:
        undo()


def test_release_gap_quiet_and_stop_switch():
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        _post_env(m, now)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"]["planner"] = False
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=2)))
        st.write_json("queue/b.json", _clip("b", 9, now - dt.timedelta(hours=1), vod_time=4000, cat="funny"))
        P.cmd_post(cfg, st)
        assert {c for _, c in FakeClient.published} == {"b"}                                  # лучший первым
        FakeClient.published = []
        P.cmd_post(cfg, st)                                                                    # через 0 минут
        assert not FakeClient.published and "прошло" in st.read_json(P.BRAIN)["last"]["reason"]
        night = dt.datetime(2026, 10, 25, 1, 7, tzinfo=dt.timezone.utc)                        # 4:07 МСК
        m(P, "now_utc", lambda: night)
        import clipper.clips as C
        m(C, "now_utc", lambda: night)
        st2 = _store()
        st2.write_json("queue/a.json", _clip("a", 8, night - dt.timedelta(hours=1)))
        P.cmd_post(cfg, st2)
        # ночных часов больше нет: решает только расписание, и причина — слот, а не «ночь аудитории»
        last = st2.read_json(P.BRAIN)["last"]
        assert "ночь" not in last["reason"]
        assert FakeClient.published or "слот" in last["reason"], last
    finally:
        undo()


def test_planner_ai_is_bounded_by_rules():
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        _post_env(m, now)
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=2)))
        st.write_json("queue/b.json", _clip("b", 7, now - dt.timedelta(hours=2), vod_time=7000, cat="funny"))
        m(P, "think", lambda cfg, ctx, fb: {"action": "post", "clip": "ghost", "reason": "галлюцинация", "by": "ИИ-продюсер"})
        P.cmd_post(CFG, st)
        assert {c for _, c in FakeClient.published} == {"a"}                                   # выдуманный клип отброшен
        assert "недоступный" in st.read_json(P.BRAIN)["last"]["by"]
    finally:
        undo()


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
                traceback.print_exc(limit=4)
    sys.exit(1 if fails else 0)
