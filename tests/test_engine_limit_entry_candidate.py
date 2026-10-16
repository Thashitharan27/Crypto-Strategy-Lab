"""Engine integration tests for causal limit-order candidates."""
from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.entry_plan import EntryIntent, EntryPlan, EntryTiming, schedule_entry


def test_engine_limit_candidate_uses_engine_bars_and_expiry():
    engine = SimpleNamespace(
        times=np.arange(4),
        open=np.array([100., 102., 98., 102.]),
        low=np.array([99., 97., 97., 101.]),
        high=np.array([103., 104., 103., 104.]),
    )
    order = schedule_entry(
        EntryIntent("LONG", 0, limit_price=100),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=2),
    )
    assert BacktestEngine._limit_entry_candidate(engine, order, 0) is None
    candidate = BacktestEngine._limit_entry_candidate(engine, order, 1)
    assert candidate is not None
    assert candidate.execution_index == 1
    assert candidate.price == 100
    assert BacktestEngine._limit_entry_candidate(engine, order, 2).price == 98
    assert BacktestEngine._limit_entry_candidate(engine, order, 3) is None
    assert BacktestEngine._limit_entry_candidate(engine, order, 4) is None


def test_limit_candidate_short_side_gap_open_and_expiry_are_causal():
    engine = SimpleNamespace(
        times=np.arange(5),
        open=np.array([100., 98., 104., 102., 105.]),
        low=np.array([99., 97., 101., 101., 104.]),
        high=np.array([103., 99., 105., 103., 106.]),
    )
    order = schedule_entry(
        EntryIntent("SHORT", 0, limit_price=103),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=3),
    )
    # No fill can occur on the signal candle, even if its range touches.
    assert BacktestEngine._limit_entry_candidate(engine, order, 0) is None
    assert BacktestEngine._limit_entry_candidate(engine, order, 1) is None
    touched = BacktestEngine._limit_entry_candidate(engine, order, 2)
    assert (touched.price, touched.execution_index) == (104., 2)
    assert BacktestEngine._limit_entry_candidate(engine, order, 3).price == 103.
    assert BacktestEngine._limit_entry_candidate(engine, order, 4) is None


def test_limit_candidate_invalid_candle_never_fabricates_a_price():
    engine = SimpleNamespace(
        times=np.arange(4),
        open=np.array([100., float("nan"), 100., 100.]),
        low=np.array([99., 99., 101., 99.]),
        high=np.array([101., 101., 102., float("inf")]),
    )
    long_order = schedule_entry(EntryIntent("LONG", 0, limit_price=100), EntryPlan(EntryTiming.LIMIT_LEVEL))
    short_order = schedule_entry(EntryIntent("SHORT", 0, limit_price=100), EntryPlan(EntryTiming.LIMIT_LEVEL))
    for order in (long_order, short_order):
        for candle in (1, 2, 3):
            assert BacktestEngine._limit_entry_candidate(engine, order, candle) is None
