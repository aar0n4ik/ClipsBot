"""v5: ИИ-движок (нативный Gemini), загрузчик HLS, слияние состояния, параллельный релиз, защита от дублей.
python tests/test_v5.py"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ["no_proxy"] = os.environ["NO_PROXY"] + ",127.0.0.1,localhost"

from clipper.config import load_config  # noqa: E402
from clipper.store import Store  # noqa: E402

CFG = load_config(ROOT / "config.yaml")


def _store():
    return Store(Path(tempfile.mkdtemp()))


# ── мини-сервер: отвечает по сценарию, записывает запросы ──────
class Server:
    def __init__(self, handler_fn, static_dir: Path | None = None):
        self.requests, self.fn, self.static = [], handler_fn, static_dir
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                srv.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
                if srv.static is not None and self.command == "GET":
                    p = srv.static / self.path.lstrip("/").split("?")[0]
                    if p.is_file():
                        data = p.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                code, headers, out = srv.fn(self.command, self.path, dict(self.headers), body)
                out = out if isinstance(out, bytes) else json.dumps(out).encode()
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            do_GET = do_POST = do_PUT = _do

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def _gemini_ok(obj):
    return {"candidates": [{"content": {"parts": [{"text": "thinking…", "thought": True}, {"text": json.dumps(obj)}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 30}}


def _llm(server_url, n_keys=2):
    import clipper.llm as L
    L.GEMINI = server_url
    for i in range(n_keys):
        os.environ[f"TEST_GEMINI_{i}"] = f"key{i}"
    return L.LLM([{"name": f"k{i}", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                   "model": "gemini-3.8-flash", "key_env": f"TEST_GEMINI_{i}", "tpm": 10 ** 9} for i in range(n_keys)])


# ── ИИ-движок ───────────────────────────────────────────────────
def test_llm_schema_no_temperature_thinking_and_usage():
    def fn(method, path, headers, body):
        if path.startswith("/v1beta/models?") or path == "/v1beta/models":
            return 200, {}, {"models": [{"name": "models/gemini-3.8-flash"}, {"name": "models/gemini-4-argon"}]}
        return 200, {}, _gemini_ok({"ok": True, "problems": []})
    srv = Server(fn)
    try:
        llm = _llm(srv.url)
        from clipper import schemas
        out = llm.chat_json([{"role": "system", "content": "sys"}, {"role": "user", "content": "привет"}],
                            temperature=0.2, schema=schemas.REVIEW, thinking="low")
        assert out == {"ok": True, "problems": []}
        req = [r for r in srv.requests if ":generateContent" in r["path"]][-1]
        body = json.loads(req["body"])
        gen = body["generationConfig"]
        assert "temperature" not in gen, gen                                  # Gemini 3+: без temperature
        assert gen["thinkingConfig"] == {"thinkingLevel": "low"} and gen["responseJsonSchema"]["type"] == "object"
        assert body["systemInstruction"]["parts"][0]["text"] == "sys"
        assert req["headers"].get("x-goog-api-key") in ("key0", "key1")
        d = llm.delta({})
        assert sum(x["calls"] for x in d["by_model"].values()) == 1 and d["usd"] > 0
    finally:
        srv.close()


def test_llm_falls_back_schema_then_rate_limit_then_model():
    state = {"n": 0}

    def fn(method, path, headers, body):
        if "/v1beta/models" in path and "generateContent" not in path:
            return 200, {}, {"models": [{"name": "models/gemini-3.8-flash"}, {"name": "models/gemini-3.6-flash"},
                                        {"name": "models/gemini-4-argon"}]}
        js = json.loads(body)
        gen = js["generationConfig"]
        if "gemini-4-argon" in path:
            return 404, {}, {"error": {"code": 404, "status": "NOT_FOUND", "message": "models/gemini-4-argon is not found"}}
        if "responseJsonSchema" in gen:
            return 400, {}, {"error": {"code": 400, "message": 'Invalid JSON payload received. Unknown name "responseJsonSchema"'}}
        state["n"] += 1
        if state["n"] == 1:
            return 429, {}, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                                       "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}}
        assert gen["responseSchema"]["type"] == "OBJECT"                     # старое поле, OpenAPI-типы
        return 200, {}, _gemini_ok({"agree": True, "action": "wait", "clip": None, "reason": "ok"})
    srv = Server(fn)
    try:
        llm = _llm(srv.url)
        from clipper import schemas
        out = llm.chat_json_model([{"role": "user", "content": "реши"}], "gemini-4-argon", schema=schemas.PRODUCER_CRITIC)
        assert out["action"] == "wait"
        assert "gemini-4-argon" in llm.missing_models                         # больше не дёргаем
        assert ("gemini-3.8-flash", "jsonschema") in llm.unsupported
        assert any(v > 0 for v in llm.cool.values())                          # ключ с 429 на паузе по RetryInfo
    finally:
        srv.close()


def test_llm_daily_quota_is_per_model_not_per_key():
    def fn(method, path, headers, body):
        if "generateContent" not in path:
            return 200, {}, {"models": [{"name": "models/gemini-3.8-flash"}, {"name": "models/gemini-4-argon"}]}
        if "gemini-4-argon" in path and headers.get("x-goog-api-key") == "key0":
            return 429, {}, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                       "message": "Quota exceeded for metric generate_requests_per_model_per_day, GenerateRequestsPerDayPerProjectPerModel"}}
        return 200, {}, _gemini_ok({"x": 1})
    srv = Server(fn)
    try:
        llm = _llm(srv.url)
        for _ in range(3):
            assert llm.chat_json([{"role": "user", "content": "a"}], model="gemini-4-argon") == {"x": 1}
        assert ("k0", "gemini-4-argon") in llm.dead and ("k0", "gemini-3.8-flash") not in llm.dead
        assert llm.chat_json([{"role": "user", "content": "b"}]) == {"x": 1}   # flash на том же ключе жив
    finally:
        srv.close()


def test_llm_transcribe_parses_word_timestamps_and_media():
    def fn(method, path, headers, body):
        if "generateContent" not in path:
            return 200, {}, {"models": [{"name": "models/gemini-3.5-transcribe"}, {"name": "models/gemini-3.8-flash"}]}
        js = json.loads(body)
        if "transcribe" in path:
            assert js["generationConfig"]["audioTranscriptionConfig"]["wordTimestamp"] is True
            assert js["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "audio/wav"
            return 200, {}, {"candidates": [{"content": {"parts": [{"audioTranscription": {"words": [
                {"word": "привет", "startOffset": "0.100s", "endOffset": "0.400s"},
                {"word": "мир", "startOffset": {"seconds": "1", "nanos": 0}, "endOffset": "1.3s"}]}}]}}]}
        assert js["contents"][0]["parts"][0]["videoMetadata"] == {"fps": 2}
        assert js["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"
        return 200, {}, _gemini_ok({"verdict": "post"})
    srv = Server(fn)
    try:
        llm = _llm(srv.url)
        w = llm.transcribe(b"RIFF" + b"\0" * 2000, "audio/wav")
        assert w == [{"w": "привет", "s": 0.1, "e": 0.4}, {"w": "мир", "s": 1.0, "e": 1.3}], w
        assert llm.media_json([("video/mp4", b"x" * 5000)], "смотри", model="gemini-3.8-flash", fps=2) == {"verdict": "post"}
    finally:
        srv.close()


def test_transcriber_cloud_first_whisper_fallback():
    from clipper.transcribe import Transcriber, plausible

    class FakeLLM:
        def transcribe(self, data, mime, language="ru-RU"):
            if data == b"bad":
                raise RuntimeError("облако упало")
            if data == b"weird":
                return [{"w": "x", "s": 50.0, "e": 50.1}]                   # за пределами окна
            return [{"w": "ок", "s": 0.2, "e": 0.5}]
    d = Path(tempfile.mkdtemp())
    items = []
    for name in ("good", "bad", "weird"):
        (d / f"{name}.wav").write_bytes(name.encode())
        items.append((d / f"{name}.wav", 10.0))
    t = Transcriber(llm=FakeLLM())
    t._whisper = lambda wav: [{"w": "whisper", "s": 0.0, "e": 0.3}]
    out = t.words_many(items)
    assert out[0][0]["w"] == "ок" and out[1][0]["w"] == "whisper" and out[2][0]["w"] == "whisper", out
    assert t.used.get("gemini") == 1
    assert not plausible([], 5) and plausible([{"w": "a", "s": 0, "e": 0.2}], 5)


# ── HLS-загрузчик ───────────────────────────────────────────────
def _beeps_hls(d: Path, fmp4: bool):
    seg = ["-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4", "-hls_segment_filename", str(d / "s%03d.m4s")] \
        if fmp4 else ["-hls_segment_filename", str(d / "s%03d.ts")]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(lt(mod(t\\,10)\\,0.2)\\,sin(2*PI*1000*t)\\,0)':s=48000:d=40",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=40", "-c:a", "aac", "-c:v", "libx264",
                    "-preset", "ultrafast", "-g", "60", "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod", *seg,
                    str(d / "p.m3u8")], check=True)


def test_hls_fetch_is_sample_accurate_ts_and_fmp4():
    import numpy as np

    from clipper import twitch
    from clipper.audio import load_wav
    from clipper.util import ffprobe_json
    for fmp4 in (False, True):
        d = Path(tempfile.mkdtemp())
        _beeps_hls(d, fmp4)
        srv = Server(lambda *a: (404, {}, b""), static_dir=d)
        try:
            twitch._FORMATS["vv"] = (9e18, [
                {"id": "Audio_Only", "url": f"{srv.url}/p.m3u8", "height": 0, "fps": 0, "vcodec": "none", "acodec": "mp4a"},
                {"id": "720p60", "url": f"{srv.url}/p.m3u8", "height": 720, "fps": 60, "vcodec": "avc1", "acodec": "mp4a"},
                {"id": "160p", "url": f"{srv.url}/p.m3u8", "height": 160, "fps": 30, "vcodec": "avc1", "acodec": "mp4a"}])
            a = twitch.download_audio("vv", 13.3, 35.0, d / "out" / "audio.m4a")
            x = load_wav(a)
            on = np.flatnonzero(np.diff((np.abs(x) > 0.3).astype(int)) == 1) / 16000
            assert abs(len(x) / 16000 - 21.7) < 0.1, len(x) / 16000                  # ничего не потеряно в конце
            assert abs(on[0] - 6.7) < 0.05, on[:2]                                     # бип 20 с → 6.7 с в куске
            v = twitch.download_video("vv", 13.3, 25.0, d / "out" / "c0_low.mp4", max_height=480)
            assert v.name == "c0_low.mp4" and abs(float(ffprobe_json(v)["format"]["duration"]) - 11.7) < 0.1
            assert not list((d / "out").glob("*.raw*"))                                # мусор убран
        finally:
            srv.close()
    fm = [{"id": "1080p60", "height": 1080, "fps": 60, "vcodec": "hev1"}, {"id": "1080p60a", "height": 1080, "fps": 60, "vcodec": "avc1"},
          {"id": "480p", "height": 480, "fps": 30, "vcodec": "avc1"}, {"id": "Audio_Only", "height": 0, "fps": 0, "vcodec": "none"}]
    assert twitch.pick_format(fm)["id"] == "1080p60a"                                    # H.264 предпочтительнее
    assert twitch.pick_format(fm, max_height=480)["id"] == "480p"
    assert twitch.pick_format(fm, audio_only=True)["id"] == "Audio_Only"
    init, segs = twitch.parse_m3u8('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:2.5,\na.m4s\n#EXTINF:2.0,\nb.m4s\n', "http://h/x/p.m3u8")
    assert init == "http://h/x/init.mp4" and segs == [(0.0, 2.5, "http://h/x/a.m4s"), (2.5, 2.0, "http://h/x/b.m4s")]


# ── состояние: трёхстороннее слияние ────────────────────────────
def test_merge3_keeps_foreign_changes():
    from clipper.store import merge3
    base = json.dumps({"watch": {"level": "ok"}, "post": {"level": "ok"}, "old": 1}).encode()
    theirs = json.dumps({"watch": {"level": "error", "msg": "x"}, "post": {"level": "ok"}, "old": 1}).encode()
    ours = json.dumps({"watch": {"level": "ok"}, "post": {"level": "warn"}}).encode()
    m = json.loads(merge3(base, ours, theirs))
    assert m == {"watch": {"level": "error", "msg": "x"}, "post": {"level": "warn"}}, m      # чужое сохранено, наше применено
    assert merge3(None, b"[1]", b"[2]") == b"[1]" and merge3(b"[0]", b"[1]", b"[2]") == b"[1]"
    assert json.loads(merge3(None, b'{"a": 1}', b'{"b": 2}')) == {"a": 1, "b": 2}           # оба создали файл одновременно


def _git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_two_workflows_do_not_clobber_each_other():
    """Как в жизни: watch и process одновременно пишут status/system.json в ветку data."""
    from clipper import health
    tmp = Path(tempfile.mkdtemp())
    bare = tmp / "remote.git"
    _git("init", "-q", "--bare", str(bare))
    seed = tmp / "seed"
    _git("init", "-q", str(seed))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git("config", k, v, cwd=seed)
    (seed / "README.md").write_text("x")
    _git("checkout", "-q", "-b", "data", cwd=seed)
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "init", cwd=seed)
    _git("push", "-q", f"file://{bare}", "data", cwd=seed)
    stores = []
    for name in ("a", "b"):
        w = tmp / name
        _git("clone", "-q", "--branch", "data", f"file://{bare}", str(w))
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            _git("config", k, v, cwd=w)
        stores.append(Store(w))
    a, b = stores
    health.report(a, "watch", "ok", "эфир идёт")
    health.report(b, "process", "error", "кусок упал")              # b прочитал файл ДО того, как a запушил
    a.sync("watch")
    b.sync("process")
    a.sync("noop")
    _git("fetch", "-q", "origin", "data", cwd=tmp / "a")
    final = json.loads(_git("show", "FETCH_HEAD:status/system.json", cwd=tmp / "a"))
    assert set(final) == {"watch", "process"}, final                # в v4 одна из записей терялась
    # сжатие истории: один коммит, содержимое то же
    assert a.squash_history()
    _git("fetch", "-q", "origin", "data", cwd=tmp / "b")
    assert _git("rev-list", "--count", "FETCH_HEAD", cwd=tmp / "b").strip() == "1"
    assert json.loads(_git("show", "FETCH_HEAD:status/system.json", cwd=tmp / "b")) == final
    health.report(b, "stats", "ok", "после сжатия")                  # пишущий после сжатия не ломается
    b.sync("after squash")


def test_status_sync_is_throttled():
    st = _store()
    calls = []
    st.on_sync.append(lambda s: calls.append(1))
    st.set_status("process", state="running", stage="a", progress=10)
    st.set_status("process", state="running", stage="b", progress=20)    # в пределах 45 с — без синка
    st.set_status("process", state="idle", stage="готово", progress=None)  # финальный — всегда
    assert len(calls) == 2, calls


# ── конвейер: дубли ─────────────────────────────────────────────
def test_overlapping_moment_is_a_duplicate():
    import clipper.pipeline as P
    st = _store()
    st.write_json("queue/v_100.json", {"id": "v_100", "vod_id": "v", "vod_time": 100.0, "span": 30.0, "duration": 24.0})
    assert P.overlapping_clip(st, "v", 110, 140) == "v_100"
    assert P.overlapping_clip(st, "v", 135, 170) is None                  # краешек — это другой момент
    assert P.overlapping_clip(st, "other", 100, 130) is None
    pl = {"c": {"ctx_start": 1000.0}, "s": 1.0, "e": 21.0}
    assert P.source_range(pl) == (999.0, 1022.5) and P.clip_key({"id": "v"}, pl) == "v_1001"


# ── публикация: маркер «выкладываю», параллельный релиз ─────────
def test_release_parallel_and_crash_safe():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _iso, _monkey, _post_env
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        _post_env(m, now)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"]["planner"] = False
        st = _store()
        seen = []
        orig = FakeClient.publish

        def publish(self, path, target, cfg_, clip):
            seen.append(json.loads(st.path(f"queue/{clip['id']}.json").read_text())["posts"][self.acc["platform"]]["status"])
            if self.acc["platform"] == "youtube":
                from clipper.platforms.base import PlatformError
                raise PlatformError("uploadLimitExceeded", "quota")
            return orig(self, path, target, cfg_, clip)
        m(FakeClient, "publish", publish)
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=2)))
        hung = _clip("h", 8, now - dt.timedelta(hours=10), vod_time=7000)
        hung["posts"] = {"tiktok": {"account": "tt_main", "status": "uploading", "started_at": _iso(now - dt.timedelta(hours=5))}}
        st.write_json("queue/h.json", hung)
        P.cmd_post(cfg, st)
        assert seen and all(s == "uploading" for s in seen), seen          # маркер записан ДО загрузки
        q = st.read_json("queue/a.json")
        assert q["posts"]["tiktok"]["status"] == "inbox" and q["posts"]["instagram"]["status"] == "posted"
        assert q["posts"]["youtube"]["status"] == "retry"                   # сбой аккаунта — клип ждёт
        h = st.read_json("queue/h.json")["posts"]["tiktok"]
        assert h["status"] == "retry" and "прервалась" in h["error"]        # TikTok-черновик: сверить нельзя — перезалить
    finally:
        undo()


def test_youtube_resumable_upload_resumes_from_offset():
    from clipper.platforms.youtube import YouTube, _next_offset
    got = bytearray()
    state = {"puts": 0}

    def fn(method, path, headers, body):
        cr = headers.get("Content-Range", "")
        if cr.startswith("bytes */"):
            return 308, {"Range": f"bytes=0-{len(got) - 1}"} if got else {}, b""
        state["puts"] += 1
        if state["puts"] == 2:                                             # второй кусок «оборвался»
            return 503, {}, b"oops"
        start = int(cr.split()[1].split("-")[0])
        assert start == len(got), (start, len(got))
        got.extend(body)
        total = int(cr.split("/")[1])
        if len(got) >= total:
            return 200, {}, {"id": "vid123"}
        return 308, {"Range": f"bytes=0-{len(got) - 1}"}, b""
    srv = Server(fn)
    try:
        data = os.urandom(600 * 1024)
        f = Path(tempfile.mkdtemp()) / "v.mp4"
        f.write_bytes(data)
        yt = YouTube.__new__(YouTube)
        import clipper.platforms.youtube as Y
        sleep = Y.time.sleep
        Y.time.sleep = lambda s: None
        try:
            res = yt._upload(srv.url + "/upload", f, len(data), chunk=256 * 1024)
        finally:
            Y.time.sleep = sleep
        assert res == {"id": "vid123"} and bytes(got) == data
        assert _next_offset("bytes=0-99") == 100 and _next_offset(None) == 0
    finally:
        srv.close()


def test_process_chunk_end_to_end_parallel():
    """Весь кусок: звук/чат параллельно → разведчик → расшифровка разом → отборщик → режиссёр → монтаж → очередь."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import DIRECTOR_OK, _monkey, _patch_pipeline, _words
    import clipper.pipeline as P
    from clipper import schemas

    class LLM2:
        def __init__(self):
            self.calls = []

        def media_json(self, media, prompt, **kw):
            self.calls.append(kw.get("schema"))
            if kw.get("schema") is schemas.SCOUT:
                return {"moments": [{"at": "01:40", "end": "02:05", "guess": 8, "what": "штраф за парковку"}]}
            return DIRECTOR_OK

        def chat_json(self, messages, **kw):
            self.calls.append(kw.get("schema"))
            if kw.get("schema") is schemas.PICKER:
                text = " ".join(p.get("text", "") for m in messages for p in (m["content"] if isinstance(m["content"], list) else []))
                import re
                return {"clips": [{"id": i, "keep": True, "score": 8, "start": 3.0, "end": 28.0, "category": "money",
                                   "risk": {"level": 0, "flags": []}, "why": "штраф"} for i in re.findall(r"id=(c\d+)", text)]}
            return {"ok": True, "title_matches": True, "makes_sense": True}

        def totals(self):
            return {}

        def delta(self, before):
            return {"by_model": {}, "usd": 0.01}

    class Tr:
        used = {}

        def words_many(self, items):
            self.used = {"gemini": len(items)}
            return [_words() for _ in items]

    class Tw:
        def clips(self, *a):
            return []
    m, undo = _monkey()
    try:
        d = Path(tempfile.mkdtemp())
        _patch_pipeline(m, d)
        m(P, "WORK_DIR", d / "work")

        def fake_audio(vid, start, end, out):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={end - start}",
                            "-c:a", "aac", str(out.with_suffix(".m4a"))], check=True)
            return out.with_suffix(".m4a")
        m(P, "download_audio", fake_audio)
        m(P, "download_chat", lambda *a, **k: [])
        st = _store()
        vod = {"id": "v9", "title": "t", "created_at": "2026-10-25T00:00:00Z", "duration_sec": 300}
        llm = LLM2()
        P.process_chunk(CFG, st, Tw(), llm, Tr(), {"user_id": "1"}, vod, 0, 300, True)
        q = st.list_json("queue")
        assert len(q) == 1 and q[0]["score"] == 8 and q[0]["span"] > q[0]["duration"], q
        ch = st.read_json("status/funnel.json")["chunks"][-1]
        assert ch["scout"] == 1 and ch["made"] == 1 and ch["asr"] == {"gemini": 1}, ch
        assert all(s in llm.calls for s in (schemas.SCOUT, schemas.PICKER, schemas.DIRECTOR, schemas.CRITIC))
        assert st.read_json("vods.json")["v9"]["processed_until"] == 300
    finally:
        undo()


def test_summary_markdown():
    from clipper.__main__ import summary
    st = _store()
    st.write_json("status/funnel.json", {"chunks": [{"chunk": "0:00:00–1:00:00", "peaks": 6, "made": 2, "usd": 0.12}],
                                         "rejected": [{"stage": "видео", "score": 6, "reason": "скучно"}]})
    md = summary(st, "process")
    assert "| 0:00:00–1:00:00 | 6 |" in md and "скучно" in md


def test_stale_object_written_after_sync_does_not_revert_foreign_change():
    """Ревью: модуль прочитал файл, потом был sync (другого файла), потом он пишет — чужая правка не откатывается."""
    from clipper.store import Store
    tmp = Path(tempfile.mkdtemp())
    bare = tmp / "r.git"
    _git("init", "-q", "--bare", str(bare))
    seed = tmp / "seed"
    _git("init", "-q", str(seed))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git("config", k, v, cwd=seed)
    (seed / "queue").mkdir()
    (seed / "queue" / "x.json").write_text(json.dumps({"note": "orig", "posts": {}}))
    _git("checkout", "-q", "-b", "data", cwd=seed)
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "init", cwd=seed)
    _git("push", "-q", f"file://{bare}", "data", cwd=seed)
    st = []
    for n in ("a", "b"):
        _git("clone", "-q", "--branch", "data", f"file://{bare}", str(tmp / n))
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            _git("config", k, v, cwd=tmp / n)
        st.append(Store(tmp / n))
    a, b = st
    x = a.read_json("queue/x.json")                         # A прочитал
    b.write_json("queue/x.json", {**b.read_json("queue/x.json"), "note": "changed by B"})
    b.sync("B")
    a.write_json("status/other.json", {"k": 1})
    a.sync("A other")                                       # синк другого файла посередине
    x["posts"]["tiktok"] = {"status": "uploading"}
    a.write_json("queue/x.json", x)                         # A пишет устаревший объект
    a.sync("A x")
    _git("fetch", "-q", "origin", "data", cwd=tmp / "b")
    final = json.loads(_git("show", "FETCH_HEAD:queue/x.json", cwd=tmp / "b"))
    assert final == {"note": "changed by B", "posts": {"tiktok": {"status": "uploading"}}}, final


def test_llm_generic_400_does_not_poison_model():
    seen = []

    def fn(method, path, headers, body):
        if "generateContent" not in path:
            return 200, {}, {"models": [{"name": "models/gemini-3.8-flash"}]}
        js = json.loads(body)
        seen.append("responseJsonSchema" in js["generationConfig"])
        if len(seen) == 1:
            return 400, {}, {"error": {"code": 400, "message": "Request contains an invalid argument."}}
        if len(seen) == 3:
            return 200, {}, b"<html>not json</html>"
        return 200, {}, _gemini_ok({"ok": True})
    srv = Server(fn)
    try:
        llm = _llm(srv.url, n_keys=1)
        from clipper import schemas
        assert llm.chat_json([{"role": "user", "content": "a"}], schema=schemas.REVIEW) == {"ok": True}
        assert seen == [True, False] and not llm.unsupported                # повтор «голым», но без последствий
        assert llm.chat_json([{"role": "user", "content": "b"}], schema=schemas.REVIEW) == {"ok": True}
        assert seen[2:] == [True, True]                                       # схема снова на месте; не-JSON → LLMError → повтор
    finally:
        srv.close()


# ── v6: синхрон «все или ничего», расписание, перенос, без таймеров ──
def _sync_env(m, now):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import _post_env
    _post_env(m, now)
    cfg = json.loads(json.dumps(CFG))
    cfg["ai"]["planner"] = False
    return cfg


def test_release_waits_for_any_resting_platform_no_timers():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _iso, _monkey
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        cfg = _sync_env(m, now)
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=1)))
        st.write_json("status/post.json", {"accounts": {"ig_main": {"platform": "instagram",
                                           "cooldown_until": _iso(now + dt.timedelta(hours=30)), "cooldown_reason": "бан"}}})
        P.cmd_post(cfg, st)
        assert not FakeClient.published                                         # даже долгий отдых — ждут все
        assert "всех площадках сразу" in st.read_json(P.BRAIN)["last"]["reason"]
        assert st.read_json("queue/a.json")["targets"]["instagram"]["status"] == "ready"   # ничего не пропущено
    finally:
        undo()


def test_preflight_failure_means_nothing_goes_out():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _monkey
    import clipper.poster as P
    from clipper.platforms.base import PlatformError
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        cfg = _sync_env(m, now)

        def pre(self):
            if self.acc["platform"] == "youtube":
                raise PlatformError("token revoked", "auth")
        FakeClient.preflight = pre
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=1)))
        P.cmd_post(cfg, st)
        assert not FakeClient.published                                         # одна не готова — не выходит никуда
        assert "проверку" in st.read_json(P.BRAIN)["last"]["reason"]
        assert st.read_json("status/post.json")["accounts"]["yt_main"]["cooldown_until"]
    finally:
        FakeClient.__dict__.get("preflight") and delattr(FakeClient, "preflight")
        undo()


def test_partial_release_is_repaired_any_time_and_blocks_new_ones():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _iso, _monkey
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        cfg = _sync_env(m, now)
        st = _store()
        a = _clip("a", 8, now - dt.timedelta(days=3))
        a["posts"] = {"tiktok": {"account": "tt_main", "status": "inbox", "posted_at": _iso(now - dt.timedelta(days=2))},
                      "instagram": {"account": "ig_main", "status": "posted", "posted_at": _iso(now - dt.timedelta(days=2))},
                      "youtube": {"account": "yt_main", "status": "retry"}}
        st.write_json("queue/a.json", a)
        st.write_json("queue/b.json", _clip("b", 9, now - dt.timedelta(hours=1), vod_time=5000))
        st.write_json("status/post.json", {"accounts": {"yt_main": {"platform": "youtube",
                                           "cooldown_until": _iso(now + dt.timedelta(hours=5))}}})
        P.cmd_post(cfg, st)
        assert not FakeClient.published and "дотянуть" in st.read_json(P.BRAIN)["last"]["reason"]   # новые ждут
        ps = st.read_json("status/post.json")
        ps["accounts"]["yt_main"].pop("cooldown_until")
        st.write_json("status/post.json", ps)
        P.cmd_post(cfg, st)
        assert FakeClient.published == [("youtube", "a")], FakeClient.published   # дотянули спустя 2 дня
        assert int(st.read_json("status/post.json")["releases"].get("by_day", {}).get("2026-10-25", 0)) == 0   # починка ≠ релиз
        FakeClient.published = []
        P.cmd_post(cfg, st)
        assert sorted(p for p, c in FakeClient.published if c == "b") == ["instagram", "tiktok", "youtube"]
    finally:
        undo()


def test_daily_schedule_fills_cap_with_best_and_nothing_expires():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _monkey
    import clipper.clips as C
    import clipper.poster as P
    m, undo = _monkey()
    day = dt.datetime(2026, 10, 25, 7, 7, tzinfo=dt.timezone.utc)                  # 10:07 МСК
    try:
        cfg = _sync_env(m, day)
        cfg["posting"]["daily_max"] = 2
        st = _store()
        for i, sc in enumerate((7, 7, 7)):                                          # с утра — «середнячки»
            st.write_json(f"queue/m{i}.json", _clip(f"m{i}", sc, day - dt.timedelta(hours=1), vod_time=1000 * i, cat=f"c{i}"))
        posted = []
        for h in range(0, 15):
            now = day + dt.timedelta(hours=h)
            m(P, "now_utc", lambda now=now: now)
            m(C, "now_utc", lambda now=now: now)
            if h == 8:                                                              # вечером — топ-момент
                st.write_json("queue/top.json", _clip("top", 9, now, vod_time=50000, cat="money"))
            FakeClient.published = []
            P.cmd_post(cfg, st)
            posted += sorted({c for _, c in FakeClient.published})
        sch = st.read_json("status/post.json")["schedule"]
        assert len(sch["hours"]) == 2 and all(h >= 12 for h in sch["hours"]), sch    # слоты в лучшие часы, а не с утра
        assert "top" in posted and len([x for x in posted if x]) <= 4, posted       # топ не потерялся
        left = [c for c in ("m0", "m1", "m2") if c not in posted]
        assert left and all(st.read_json(f"queue/{c}.json")["targets"]["tiktok"]["status"] == "ready" for c in left)
        assert P.day_slots(5, [1.0] * 24, {2, 3, 4, 5, 6}, 2.0) and len(P.day_slots(5, [1.0] * 24, set(range(0, 21)), 2.0)) == 3
    finally:
        undo()


def test_cadence_migration_respects_user_choice():
    from clipper import settings
    st = _store()
    st.write_json(settings.SETTINGS, {"values": {"posting.daily_max": 4, "posting.min_gap_minutes": 60, "clips.max_seconds": 59}})
    assert settings.migrate(st) == ["v5_cadence", "v6_reserve"]
    v = st.read_json(settings.SETTINGS)["values"]
    # v5 поднял лимит 4→5, v6 опустил обратно 5→4; ручные 60 минут паузы обе миграции не трогают
    assert v["posting.daily_max"] == 4 and v["posting.min_gap_minutes"] == 60 and v["clips.max_seconds"] == 175
    st.write_json(settings.SETTINGS, {"values": {"posting.daily_max": 4}})              # владелец вернул 4 сам
    assert settings.migrate(st) == [] and st.read_json(settings.SETTINGS)["values"]["posting.daily_max"] == 4
    from clipper.brain import length_rule
    assert "только если почти всё время интересно" in length_rule(CFG).lower() or "ТОЛЬКО" in length_rule(CFG)


# ── корректор субтитров ─────────────────────────────────────────
def test_glossary_is_a_hint_not_blind_replacement():
    from clipper import proofread as PR
    st = _store()
    PR.learn(st, [("лутка", "лудка")])
    PR.learn(st, [("Лутка,", "лудка")])
    assert PR.hints(st) == ["лутка → лудка (2)"] and "лудка" in PR.terms(st)
    assert not hasattr(PR, "apply_known")                                            # никаких слепых автозамен
    ed = PR.fix_texts({"hooks": [{"style": "quote", "text": "Опять лутка!"}], "youtube": {"title": "Лутка", "tags": ["лутка"]}},
                      {"лутка": "лудка"})
    assert ed["hooks"][0]["text"] == "Опять лудка!" and ed["youtube"]["title"] == "Лудка" and ed["youtube"]["tags"] == ["лудка"]
    words = [{"w": "он", "s": 0, "e": 0.2}, {"w": "сказал", "s": 0.3, "e": 0.6}, {"w": "ю", "s": 0.7, "e": 0.8},
             {"w": "кэнт", "s": 0.9, "e": 1.1}, {"w": "парк", "s": 1.2, "e": 1.5}, {"w": "ок", "s": 1.6, "e": 1.8}]
    t = PR.apply_english(words, {"from": 2, "to": 4, "en": "you can't park here", "ru": "тут нельзя парковаться"})
    assert [w["w"] for w in words] == ["он", "сказал", "you", "can't", "park", "here", "ок"]
    assert t == {"s": 0.7, "e": 1.5, "ru": "тут нельзя парковаться"} and words[2]["lang"] == "en" and words[5]["e"] <= 1.51


def test_proofreader_listens_fixes_and_handles_english():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import DIRECTOR_OK, _cand, _monkey, _patch_pipeline
    import clipper.pipeline as P
    from clipper import learn, schemas

    class L:
        def media_json(self, media, prompt, **kw):
            if kw.get("schema") is schemas.PROOF:
                assert media[0][0] in ("audio/ogg", "audio/mp3") and "0:" in prompt
                import re
                ii = [int(x) for x in re.findall(r"(\d+):охранник", prompt)]
                j = int(re.search(r"(\d+):штраф", prompt).group(1))
                return {"fixes": [{"i": i, "w": "охранница"} for i in ii] + [{"i": 9999, "w": "мусор"}],
                        "english": [{"from": j, "to": j + 1, "en": "fine two hundred", "ru": "штраф двести"}]}
            return {**DIRECTOR_OK, "hooks": [{"style": "tease", "text": "Охранник против меня"}] + DIRECTOR_OK["hooks"][1:]}

        def chat_json(self, messages, **kw):
            return {"ok": True}

        def totals(self):
            return {}
    m, undo = _monkey()
    try:
        d = Path(tempfile.mkdtemp())
        _patch_pipeline(m, d)
        st = _store()
        vod = {"id": "v1", "title": "t", "created_at": "2026-10-25T00:00:00Z"}
        c = _cand()
        plan = P._review_on_video(CFG, st, L(), vod, c, {"score": 7, "why": "x"}, 3, 30, d)
        text = " ".join(w["w"] for w in c["words"])
        assert plan and "охранница" in text and "fine two hundred" in text                 # субтитры исправлены
        assert plan["ed"]["hooks"][0]["text"] == "Охранница против меня"                    # и заголовок тоже
        assert c["trans"] and c["trans"][0]["ru"] == "штраф двести"
        assert st.read_json("glossary.json")["fixes"]["охранник"]["to"] == "охранница"
        assert P.make_clip(CFG, st, L(), learn.default_policy(CFG), vod, plan, ["tiktok"], d)
        ass = next(d.rglob("*.ass")).read_text()
        assert "«штраф двести»" in ass and ",Tr," in ass and "fine two hundred" in ass       # перевод строкой ниже
    finally:
        undo()


def test_long_clip_needs_strict_length_check():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import DIRECTOR_OK, _monkey, _patch_pipeline, _words
    import clipper.pipeline as P
    from clipper import schemas
    calls = []

    class L:
        def media_json(self, media, prompt, **kw):
            calls.append(kw.get("schema"))
            if kw.get("schema") is schemas.LENGTH:
                return {"keep_long": False, "start": 10.0, "end": 45.0, "cuts": [], "why": "середина провисает"}
            if kw.get("schema") is schemas.PROOF:
                return {"fixes": [], "english": []}
            return {**DIRECTOR_OK, "start": 1.0, "end": 85.0, "cuts": []}

        def chat_json(self, messages, **kw):
            return {"ok": True}
    m, undo = _monkey()
    try:
        d = Path(tempfile.mkdtemp())
        _patch_pipeline(m, d)
        st = _store()
        c = {"id": "c9", "ctx_start": 1000.0, "ctx_dur": 100.0, "peak_in_ctx": 50, "peak_abs": 1050.0, "signal": 2.0,
             "breakdown": {"chat": 1, "keywords": 1, "spam_wave": 0, "audio": 1, "viewer_clips": 0},
             "chat_sample": [], "chat_count": 0, "words": _words(190, 0.5)}
        plan = P._review_on_video(CFG, st, L(), {"id": "v2", "title": "t", "created_at": "2026-10-25T00:00:00Z"},
                                  c, {"score": 8, "why": "x"}, 2, 90, d)
        assert schemas.LENGTH in calls and plan and plan["e"] - plan["s"] < 50, plan and (plan["s"], plan["e"])
        assert plan["brain"]["length"]["keep_long"] is False
    finally:
        undo()


def test_paused_platform_does_not_dump_old_clips_when_back():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _monkey
    import clipper.clips as C
    import clipper.poster as P
    from clipper import learn
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)
    try:
        cfg = _sync_env(m, now)
        st = _store()
        pol = learn.default_policy(cfg)
        pol["paused"] = {"ig_main": "2026-10-26T00:00:00+00:00"}
        st.write_json("policy.json", pol)
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=1)))
        P.cmd_post(cfg, st)
        assert sorted(p for p, _ in FakeClient.published) == ["tiktok", "youtube"]       # владелец сам поставил паузу
        assert st.read_json("queue/a.json")["targets"]["instagram"]["status"] == "skipped_sync"
        later = now + dt.timedelta(days=1, hours=3)
        m(P, "now_utc", lambda: later)
        m(C, "now_utc", lambda: later)
        FakeClient.published = []
        P.cmd_post(cfg, st)
        assert not any(c == "a" for _, c in FakeClient.published)                        # не перевыкладывает старьё
    finally:
        undo()


def test_hung_upload_reconciled_against_platform():
    import clipper.poster as P
    c = {"id": "x", "targets": {"youtube": {"caption": "Штраф за парковку в США", "asset": "x.mp4", "status": "ready"}},
         "posts": {"youtube": {"status": "uploading", "started_at": "2026-10-25T10:00:00Z"},
                   "tiktok": {"status": "uploading", "started_at": "2026-10-25T10:00:00Z"}}}

    class YT:
        def list_videos(self):
            return [{"id": "v1", "title": "Штраф за парковку в США!", "description": "", "create_time": int(dt.datetime(2026, 10, 25, 10, 5, tzinfo=dt.timezone.utc).timestamp()), "url": "u"}]
    assert P.reconcile_upload(c, "youtube", YT()) == "posted" and c["posts"]["youtube"]["video_id"] == "v1"
    assert P.reconcile_upload(c, "tiktok", object()) == "retry"                      # черновик не виден — перезалить
    YT.list_videos = lambda self: []
    c["posts"]["youtube"] = {"status": "uploading", "started_at": "2026-10-25T10:00:00Z"}
    assert P.reconcile_upload(c, "youtube", YT()) == "retry"


def test_late_runner_does_not_lose_slot_and_long_clips_fit_limits():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v4 import FakeClient, _clip, _iso, _monkey
    import clipper.poster as P
    m, undo = _monkey()
    now = dt.datetime(2026, 10, 25, 16, 9, tzinfo=dt.timezone.utc)
    try:
        cfg = _sync_env(m, now)
        st = _store()
        st.write_json("queue/a.json", _clip("a", 8, now - dt.timedelta(hours=1)))
        st.write_json("status/post.json", {"releases": {"last_at": _iso(now - dt.timedelta(minutes=174))}})
        P.cmd_post(cfg, st)
        assert FakeClient.published, st.read_json(P.BRAIN)["last"]                    # 174 мин из 180 — слот не теряем
    finally:
        undo()
    from clipper.pipeline import cap_kept, kept_len
    e, cuts = cap_kept(0, 90, [(10, 20), (50, 60), (95, 99)], 60)
    assert kept_len(0, e, cuts) == 60 and (95, 99) not in cuts
    import inspect
    from clipper import render
    src = inspect.getsource(render.render_clip)
    assert "0.88 * 95" not in src                      # потолка «под 95 МБ» больше нет: он душил качество
    assert '"-crf", "18"' in src                       # качество задаёт только CRF — одинаковое от начала до конца
    assert "loudnorm" not in src.split("if meas is None")[1].split("else")[1]   # в основном тракте — ровное усиление
    assert render.SUB_MAX_W <= 760                                                    # не под кнопками TikTok


def test_deleted_video_never_comes_back_as_retry():
    """Владелец удалил ролик → removed_by_user на ЛЮБОЙ площадке, и «повтор» снимается."""
    import clipper.stats as S
    from clipper.clips import pending_for
    now = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc).timestamp()
    A = {"videos": {"ig1": {"views": 10, "deleted_at": "2026-10-25T10:00:00Z"}}}
    owner = {"ig1": "c1"}
    assert S.prune_deleted(A, owner, "instagram", set(), now) == ["c1"]
    assert "ig1" not in A["videos"]

    # пост, оставшийся в retry, больше не считается ожидающим публикации
    c = {"targets": {"instagram": {"asset": "a.mp4", "status": "removed_by_user"}},
         "posts": {"instagram": {"status": "removed_by_user"}}}
    assert not pending_for(c, "instagram")

    # а пока он в retry — считается (иначе дотяжка сломается)
    c2 = {"targets": {"instagram": {"asset": "a.mp4", "status": "ready"}},
          "posts": {"instagram": {"status": "retry"}}}
    assert pending_for(c2, "instagram")


def test_link_clips_rescues_retry_post():
    """Ролик на самом деле вышел, но ответ потерялся: связываем и ставим posted, а не льём второй раз."""
    import inspect, clipper.stats as S
    src = inspect.getsource(S.link_clips)
    assert '"retry", "failed"' in src        # retry/failed тоже ищем по тексту подписи


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
                traceback.print_exc(limit=6)
    sys.exit(1 if fails else 0)
