"""v6: запас клипов — срок годности, плавающая планка отбора, лимит в день без эфира.
python -m pytest tests/test_reserve.py"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from clipper import reserve  # noqa: E402
from clipper.config import load_config  # noqa: E402
from clipper.store import Store  # noqa: E402

CFG = load_config(ROOT / "config.yaml")
NOW = dt.datetime(2026, 10, 25, 16, 7, tzinfo=dt.timezone.utc)


def _store():
    return Store(Path(tempfile.mkdtemp()))


def _ready(cid: str, created: dt.datetime, expires: dt.datetime | None = None) -> dict:
    return {"id": cid, "created_at": created.isoformat(), "score": 8,
            "expires_at": expires.isoformat() if expires else None,
            "targets": {"tiktok": {"asset": f"{cid}.mp4", "status": "ready"}}, "posts": {}}


def test_shelf_maps_old_and_new_fields():
    assert reserve.shelf_of({"shelf": "weeks"}) == "weeks"
    assert reserve.shelf_of({"shelf": "ЕРУНДА"}) == "forever"       # мусор от модели → бессрочно, клип не теряем
    assert reserve.shelf_of({"fresh": True}) == "now"               # старые клипы знали только fresh
    assert reserve.shelf_of({}) == "forever"


def test_expiry_dates_match_shelf():
    assert reserve.expires_at("forever", NOW) is None
    assert reserve.expires_at("now", NOW)[:10] == "2026-11-01"      # неделя
    assert reserve.expires_at("weeks", NOW)[:10] == "2026-12-09"    # сорок пять дней


def test_expired_clip_leaves_the_queue_but_stays_in_history():
    st = _store()
    st.write_json("queue/fresh.json", _ready("fresh", NOW, NOW + dt.timedelta(days=3)))
    st.write_json("queue/stale.json", _ready("stale", NOW - dt.timedelta(days=30), NOW - dt.timedelta(days=1)))
    st.write_json("queue/ever.json", _ready("ever", NOW - dt.timedelta(days=200)))

    assert {c["id"] for c in reserve.ready_clips(st, NOW)} == {"fresh", "ever"}
    assert reserve.expire_due(st, NOW) == ["stale"]

    gone = st.read_json("queue/stale.json")
    assert gone["status"] == "expired" and gone["expired_at"]       # файл на месте, в очередь больше не попадёт
    assert {c["id"] for c in reserve.ready_clips(st, NOW)} == {"fresh", "ever"}
    assert reserve.expire_due(st, NOW) == []                        # второй раз не списывает


def test_bar_rises_only_when_the_bank_is_full():
    q = {"reserve_target": 3, "reserve_max": 5}
    st = _store()
    assert reserve.bank_surcharge(st, q) == 0                       # пусто — берём по обычной планке
    for i in range(3):
        st.write_json(f"queue/c{i}.json", _ready(f"c{i}", NOW))
    assert reserve.bank_surcharge(st, q) == 1                       # запас набран — планка выше
    for i in range(3, 6):
        st.write_json(f"queue/c{i}.json", _ready(f"c{i}", NOW))
    assert reserve.bank_surcharge(st, q) == 2                       # банк переполнен — только сильнее лежащего


def test_posted_and_expired_clips_do_not_count_as_reserve():
    q = {"reserve_target": 2, "reserve_max": 9}
    st = _store()
    out = _ready("out", NOW)
    out["posts"] = {"tiktok": {"status": "posted"}}
    st.write_json("queue/out.json", out)
    st.write_json("queue/dead.json", _ready("dead", NOW, NOW - dt.timedelta(hours=1)))
    st.write_json("queue/live1.json", _ready("live1", NOW))
    assert {c["id"] for c in reserve.ready_clips(st, NOW)} == {"live1"}
    assert reserve.bank_surcharge(st, q) == 0


def test_day_without_stream_gets_the_smaller_limit():
    from test_v4 import FakeClient, _clip, _monkey, _post_env  # noqa: F401
    import clipper.poster as P
    m, undo = _monkey()
    try:
        _post_env(m, NOW)
        cfg = json.loads(json.dumps(CFG))
        cfg["ai"]["planner"] = False
        cfg["posting"]["daily_max"] = 4
        cfg["posting"]["offday_max"] = 2

        st = _store()                                               # эфир был вчера → обычный лимит
        st.write_json("status/live.json", {"is_live": False, "last_seen_live": (NOW - dt.timedelta(hours=10)).isoformat()})
        st.write_json("queue/a.json", _clip("a", 8, NOW - dt.timedelta(hours=2)))
        P.cmd_post(cfg, st)
        assert len(st.read_json("status/post.json")["schedule"]["hours"]) == 4

        FakeClient.published = []
        st2 = _store()                                              # эфира не было неделю, материал старый
        st2.write_json("status/live.json", {"is_live": False, "last_seen_live": (NOW - dt.timedelta(days=7)).isoformat()})
        st2.write_json("queue/old.json", _clip("old", 8, NOW - dt.timedelta(days=5)))
        P.cmd_post(cfg, st2)
        assert len(st2.read_json("status/post.json")["schedule"]["hours"]) == 2
    finally:
        undo()


def test_night_hours_are_gone_from_the_schedule():
    """Расписание строится только по активности аудитории: запретных часов больше нет."""
    import clipper.poster as P
    assert len(P.day_slots(4, [1.0] * 24, set(), 3.0)) == 4
    assert "quiet_hours" not in CFG["posting"]
