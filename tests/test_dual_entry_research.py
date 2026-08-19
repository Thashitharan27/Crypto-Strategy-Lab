from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.dual_entry_research import _di_bucket, _first_exit, _pair_result


def _frame(*bars):
    return pd.DataFrame(
        [
            {"timestamp": f"2026-01-01 00:{n:02d}:00+00:00", "high": high, "low": low}
            for n, (high, low) in enumerate(bars)
        ]
    )


def test_di_buckets_match_research_contract():
    assert _di_bucket(0.0) == "0-5"
    assert _di_bucket(4.999) == "0-5"
    assert _di_bucket(5.0) == "5-10"
    assert _di_bucket(29.9) == "25-30"
    assert _di_bucket(30.0) == "30+"


def test_chop_can_close_both_sides_at_tp():
    data = _frame((102.1, 99.0), (101.0, 97.9))
    long_exit = _first_exit("LONG", 100.0, 1.0, 2.0, 5.0, data, "PESSIMISTIC")
    short_exit = _first_exit("SHORT", 100.0, 1.0, 2.0, 5.0, data, "PESSIMISTIC")
    assert long_exit["reason"] == "TP"
    assert short_exit["reason"] == "TP"
    assert _pair_result(long_exit["reason"], short_exit["reason"]) == "DOUBLE_TP"


def test_directional_move_produces_mixed_outcome():
    data = _frame((102.1, 99.0), (105.1, 101.0))
    long_exit = _first_exit("LONG", 100.0, 1.0, 2.0, 5.0, data, "PESSIMISTIC")
    short_exit = _first_exit("SHORT", 100.0, 1.0, 2.0, 5.0, data, "PESSIMISTIC")
    assert long_exit["reason"] == "TP"
    assert short_exit["reason"] == "SL"
    assert _pair_result(long_exit["reason"], short_exit["reason"]) == "LONG_TP_SHORT_SL"


def test_same_bar_tp_sl_respects_pessimistic_policy():
    data = _frame((106.0, 97.0))
    long_exit = _first_exit("LONG", 100.0, 1.0, 2.0, 5.0, data, "PESSIMISTIC")
    assert long_exit["reason"] == "SL"
    assert long_exit["ambiguous"] is True
