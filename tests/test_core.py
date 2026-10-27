"""Быстрые проверки без сети: python -m pytest -q  (или python tests/test_core.py)"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipper.config import load_config  # noqa: E402
from clipper.crypto import decrypt_json, encrypt_json  # noqa: E402
from clipper.judge import snap_bounds  # noqa: E402
from clipper.poster import plan_hours  # noqa: E402
from clipper.signals import find_candidates  # noqa: E402

CFG = load_config(ROOT / "config.yaml")


def test_crypto_roundtrip():
    obj = {"привет": [1, 2, 3], "x": "доход $"}
    blob = encrypt_json(obj, "pass123")
    assert decrypt_json(blob, "pass123") == obj


def test_crypto_browser_compatible():
    """Тот же алгоритм, что в дашборде (WebCrypto), должен расшифровать."""
    blob = encrypt_json({"ok": True, "n": 42}, "секрет")
    js = r"""
const env = JSON.parse(require('fs').readFileSync(0,'utf8'));
const b = s => Uint8Array.from(Buffer.from(s,'base64'));
(async () => {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode('секрет'), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({name:'PBKDF2', salt:b(env.salt), iterations:env.iter, hash:'SHA-256'},
     base, {name:'AES-GCM', length:256}, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({name:'AES-GCM', iv:b(env.iv)}, key, b(env.ct));
  process.stdout.write(new TextDecoder().decode(pt));
})();"""
    r = subprocess.run(["node", "-e", js], input=blob.decode(), capture_output=True, text=True)
    assert json.loads(r.stdout) == {"ok": True, "n": 42}, r.stderr


def test_peaks_found_where_chat_and_audio_spike():
    length = 3600
    rng = np.random.default_rng(1)
    audio = 40 + rng.normal(0, 1.5, length).astype(np.float32)
    audio[1200:1206] += 18                      # крик на 20-й минуте
    msgs = [{"t": float(t), "user": "u", "text": "норм", "emotes": []} for t in rng.uniform(0, length, 900)]
    msgs += [{"t": 1209 + i * 0.3, "user": f"u{i}", "text": "АХАХАХАХ KEKW", "emotes": ["KEKW"]} for i in range(40)]
    msgs += [{"t": 2500 + i * 0.4, "user": f"z{i}", "text": "клип", "emotes": []} for i in range(25)]
    clips = [{"vod_offset": 3000, "duration": 30, "view_count": 50, "title": "lol"}]
    cands = find_candidates(CFG, msgs, clips, audio, 0.0)
    peaks = [c["peak_rel"] for c in cands]
    assert any(abs(p - 1203) < 15 for p in peaks), peaks
    assert any(abs(p - 2495) < 20 for p in peaks), peaks
    assert any(abs(p - 3018) < 20 for p in peaks), peaks
    # не берём пересекающиеся моменты повторно
    again = find_candidates(CFG, msgs, clips, audio, 0.0, already=[c["peak_abs"] for c in cands])
    assert not set(peaks) & {c["peak_rel"] for c in again}


def test_snap_bounds_respects_words_and_limits():
    words = [{"w": f"w{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(160)]  # 80 сек речи
    s, e = snap_bounds(words, 10.1, 30.2, 80.0, CFG)
    assert abs(s - (10.0 - 0.25)) < 0.01 and 30 <= e <= 31
    s, e = snap_bounds(words, 0, 79, 80.0, CFG)
    assert e - s <= CFG["clips"]["max_seconds"] + 0.5
    s, e = snap_bounds(words, 20, 22, 80.0, CFG)
    assert e - s >= CFG["clips"]["min_seconds"] - 0.01


def test_plan_hours_respects_gap_quiet_and_weights():
    from clipper.learn import PRIOR_HOURS as PRIOR
    tz = __import__("zoneinfo").ZoneInfo("Europe/Moscow")
    now = dt.datetime(2026, 10, 17, 9, 30, tzinfo=tz)
    plan = plan_hours(now, 4, PRIOR, {2, 3, 4, 5, 6}, 80 / 60, None)
    assert len(plan) == 4 and all(h >= 9 for h in plan)
    assert all(abs(a - b) >= 2 for a in plan for b in plan if a != b)  # пауза ≥ 80 мин при часовой сетке
    assert 19 in plan or 20 in plan                                     # вечер — самый сильный


def test_no_second_lost():
    import tempfile
    from clipper.pipeline import next_chunk
    from clipper.store import Store
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda t: t.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    meta = {"since": iso(now - dt.timedelta(hours=30))}

    def covered(duration_sec, ended_min_ago, live_steps=()):
        """Прогоняем жизнь стрима и проверяем, что обработанные куски покрывают VOD целиком."""
        st = Store(Path(tempfile.mkdtemp()))
        start_t = now - dt.timedelta(seconds=duration_sec, minutes=ended_min_ago)
        vod = {"id": "v", "created_at": iso(start_t)}
        spans = []
        for live_dur in live_steps:  # пока идёт эфир
            v = {**vod, "duration_sec": live_dur}
            while (job := next_chunk(CFG, st, [v], {"started_at": vod["created_at"]}, meta)):
                _, a, b, _ = job
                spans.append((a, b))
                st.write_json("vods.json", {"v": {"processed_until": b}})
        v = {**vod, "duration_sec": duration_sec}
        while (job := next_chunk(CFG, st, [v], None, meta)):
            _, a, b, final = job
            spans.append((a, b))
            st.write_json("vods.json", {"v": {"processed_until": b, "finished": final}})
        pos = 0
        for a, b in sorted(spans):
            assert a <= pos, f"дыра {pos}→{a}"
            pos = max(pos, b)
        return pos, spans

    assert covered(5400, 70)[0] == 5400                            # 1.5 ч, закончился
    assert covered(12600, 70, live_steps=[7500, 9000])[0] == 12600  # 3.5 ч, резался вживую
    assert covered(37, 70)[0] == 37                                 # совсем короткий
    pos, spans = covered(12601, 2, live_steps=[7500])               # только что закончился: хвост ждёт стабилизации
    chunk = int(CFG["processing"]["chunk_minutes"]) * 60
    assert pos < 12601 and 12601 - pos < chunk and pos % 3600 == 0, pos   # целые куски взяты, короткий хвост ждёт
    st = Store(Path(tempfile.mkdtemp()))                            # Twitch удлинил VOD задним числом
    v = {"id": "v", "created_at": iso(now - dt.timedelta(hours=5)), "duration_sec": 4000}
    st.write_json("vods.json", {"v": {"processed_until": 3900, "finished": True}})
    assert next_chunk(CFG, st, [v], None, meta)[1:3] == (4000 - 360, 4000)


def test_humanize_strips_ai_tells():
    from clipper.judge import humanize, humanize_tags
    t = humanize("«Курьер в Америке» — смотрите до конца!!! 😱🔥🔥", 1)
    assert "—" not in t and "«" not in t and "до конца" not in t and t.count("!") <= 1 and len([c for c in t if ord(c) > 0x1F000]) <= 1
    assert humanize_tags(["fyp", "#Доставка в США", "курьер"]) == ["#доставкавсша", "#курьер"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("✅", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("❌", name, repr(e)[:500])
    sys.exit(1 if fails else 0)
