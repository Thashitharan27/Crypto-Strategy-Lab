"""Shared next-open scheduling remains compatible with engine decision metadata."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from crypto_strategy_lab.engine import BacktestEngine


def test_next_open_engine_decision_uses_shared_scheduler():
    engine = SimpleNamespace(
        config=SimpleNamespace(enable_daily_entry_schedule=False),
        times=np.array(pd.date_range("2026-01-01", periods=3, freq="h")),
        _entry_timing_mode=lambda: "NEXT_CANDLE_OPEN",
        _should_enter=lambda i: True,
        _selected_direction=lambda i: "SHORT",
    )
    decision = BacktestEngine._entry_decision(engine, 0)
    assert decision["execution_index"] == 1
    assert decision["indicator_index"] == 0
    assert decision["defer_to_next_open"] is True
    assert decision["fill_price_source"] == "NEXT_CANDLE_OPEN"
    assert BacktestEngine._entry_decision(engine, 2) is None


def test_signal_close_engine_decision_uses_shared_scheduler():
    engine = SimpleNamespace(
        config=SimpleNamespace(enable_daily_entry_schedule=False),
        times=np.array(pd.date_range("2026-01-01", periods=3, freq="h")),
        _entry_timing_mode=lambda: "SIGNAL_CLOSE",
        _should_enter=lambda i: i == 1,
        _selected_direction=lambda i: "LONG",
        _entry_time=lambda i: pd.Timestamp("2026-01-01 01:59:59"),
    )
    assert BacktestEngine._entry_decision(engine, 0) is None
    decision = BacktestEngine._entry_decision(engine, 1)
    assert decision["execution_index"] == 1
    assert decision["indicator_index"] == 1
    assert decision["fill_price_source"] == "SIGNAL_CLOSE"
    assert decision["actual_entry_timestamp"] == pd.Timestamp("2026-01-01 01:59:59")
    assert not decision.get("defer_to_next_open", False)
