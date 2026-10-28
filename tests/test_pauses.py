"""Паузы в пару секунд — обычная речь: режем только по-настоящему мёртвый воздух (дольше trim_gap_seconds)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipper.cuts import drop_short_pauses, speech_runs  # noqa: E402


def W(s, e):
    return {"w": "x", "s": s, "e": e}


def test_two_second_pause_stays():
    words = [W(0.0, 1.0), W(3.2, 4.0), W(6.0, 7.0)]          # паузы 2.2 и 2.0 с
    assert speech_runs(words, 0.0, 7.5, max_gap=4.0) == [(0.0, 7.25)]


def test_long_dead_air_is_cut():
    words = [W(0.0, 1.0), W(7.0, 8.0)]                       # пауза 6 с
    runs = speech_runs(words, 0.0, 8.5, max_gap=4.0)
    assert len(runs) == 2 and runs[0][1] < 2.0 and runs[1][0] > 6.0


def test_ai_cut_of_short_silence_is_dropped():
    words = [W(0.0, 1.0), W(3.5, 4.5)]
    assert drop_short_pauses([(1.2, 3.3)], words, 4.0) == []   # 2.1 с тишины, слов внутри нет


def test_ai_cut_with_words_or_long_silence_is_kept():
    words = [W(0.0, 1.0), W(2.0, 3.0), W(9.0, 10.0)]
    cuts = [(1.9, 3.1), (3.2, 8.9)]                           # со словами / 5.7 с тишины
    assert drop_short_pauses(cuts, words, 4.0) == cuts
