"""Causal minute-bar timestamps for potential limit fills."""
from types import SimpleNamespace

import pandas as pd

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.entry_plan import EntryIntent, EntryPlan, EntryTiming, schedule_entry


def test_first_intrabar_limit_touch_uses_first_minute_and_respects_signal_bar():
    start = pd.Timestamp("2026-01-01 00:00:00")
    bars = pd.DataFrame([
        {"timestamp": start + pd.Timedelta(minutes=5), "open": 102., "low": 101., "high": 103.},
        {"timestamp": start + pd.Timedelta(minutes=6), "open": 101., "low": 99., "high": 103.},
        {"timestamp": start + pd.Timedelta(minutes=7), "open": 99., "low": 98., "high": 102.},
    ])
    engine = SimpleNamespace(
        config=SimpleNamespace(use_intrabar_data=True),
        times=[start, start + pd.Timedelta(minutes=15)],
        entry_delta=pd.Timedelta(minutes=15),
        intrabar_data=bars,
        _has_missing_intrabar=lambda sub, first, last: False,
    )
    order = schedule_entry(EntryIntent("LONG", 0, limit_price=100), EntryPlan(EntryTiming.LIMIT_LEVEL))
    assert BacktestEngine._first_intrabar_limit_touch(engine, order, 0) is None
    # First eligible strategy candle starts at minute 15; no eligible intrabar rows.
    assert BacktestEngine._first_intrabar_limit_touch(engine, order, 1) is None
    engine.times = [start - pd.Timedelta(minutes=15), start]
    assert BacktestEngine._first_intrabar_limit_touch(engine, order, 1) == (
        start + pd.Timedelta(minutes=6), 100.
    )


def test_first_intrabar_limit_touch_fails_closed_on_gaps():
    t = pd.Timestamp("2026-01-01")
    engine = SimpleNamespace(
        config=SimpleNamespace(use_intrabar_data=True),
        times=[t - pd.Timedelta(minutes=15), t],
        entry_delta=pd.Timedelta(minutes=15),
        intrabar_data=pd.DataFrame([{"timestamp": t, "open": 100., "low": 98., "high": 102.}]),
        _has_missing_intrabar=lambda sub, first, last: True,
    )
    order = schedule_entry(EntryIntent("SHORT", 0, limit_price=101), EntryPlan(EntryTiming.LIMIT_LEVEL))
    assert BacktestEngine._first_intrabar_limit_touch(engine, order, 1) is None
