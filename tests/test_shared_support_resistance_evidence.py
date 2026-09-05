from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_core.candles import atr
from crypto_strategy_core.support_resistance_evidence import (
    support_resistance_evidence_series,
)


def _series(count: int = 80):
    times = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="1h")
    decisions = times + pd.Timedelta(hours=1)
    base = 100.0 + np.sin(np.arange(count) / 3.0) * 8.0 + np.arange(count) * 0.05
    open_ = base + np.sin(np.arange(count) / 2.0) * 0.3
    close = base + np.cos(np.arange(count) / 2.0) * 0.3
    high = np.maximum(open_, close) + 1.2
    low = np.minimum(open_, close) - 1.2
    atr_values = np.asarray(atr(high, low, close, 14), dtype=float)
    return times, decisions, open_, high, low, close, atr_values


def test_shared_sr_same_timeframe_is_future_mutation_invariant() -> None:
    times, decisions, open_, high, low, close, atr_values = _series()
    baseline = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        pivot_left=3,
        pivot_right=3,
        lookback_bars=40,
    )
    cutoff = 50
    changed_open = open_.copy()
    changed_high = high.copy()
    changed_low = low.copy()
    changed_close = close.copy()
    changed_open[cutoff + 1 :] *= 4.0
    changed_high[cutoff + 1 :] *= 4.0
    changed_low[cutoff + 1 :] *= 4.0
    changed_close[cutoff + 1 :] *= 4.0
    changed_atr = np.asarray(atr(changed_high, changed_low, changed_close, 14), dtype=float)
    mutated = support_resistance_evidence_series(
        times,
        decisions,
        changed_open, changed_high, changed_low, changed_close, changed_atr,
        strategy_minutes=60,
        pivot_left=3,
        pivot_right=3,
        lookback_bars=40,
    )
    fields = (
        "long_near_support",
        "long_near_resistance",
        "long_support_state",
        "long_resistance_state",
        "long_trade_location_rating",
        "long_room_in_direction_atr",
        "short_trade_location_rating",
    )
    for index in range(cutoff + 1):
        for field in fields:
            left = baseline[index][field]
            right = mutated[index][field]
            if isinstance(left, float) and np.isnan(left):
                assert isinstance(right, float) and np.isnan(right)
            else:
                assert left == right


def test_shared_sr_higher_timeframe_never_uses_incomplete_bar() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(96)
    rows = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        sr_timeframe_minutes=240,
        atr_period=14,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=30,
    )
    assert len(rows) == len(times)
    for decision_time, row in zip(decisions, rows):
        completed = row["sr_completed_candle_time"]
        if pd.isna(completed):
            continue
        assert pd.Timestamp(completed) <= decision_time


def test_shared_sr_resampling_uses_candle_open_not_decision_close() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(16)
    rows = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        sr_timeframe_minutes=240,
        pivot_left=1,
        pivot_right=1,
        lookback_bars=10,
    )
    # The first complete 4h candle opened at 00:00 and closes at 04:00.
    assert pd.Timestamp(rows[3]["sr_completed_candle_time"]) == pd.Timestamp(
        "2026-01-01T04:00:00Z"
    )


def test_shared_sr_requires_chronological_strategy_rows() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(20)
    reverse_times = times[::-1]
    reverse_decisions = decisions[::-1]
    try:
        support_resistance_evidence_series(
            reverse_times,
            reverse_decisions,
            open_[::-1], high[::-1], low[::-1], close[::-1], atr_values[::-1],
            strategy_minutes=60,
        )
    except ValueError as exc:
        assert "chronological" in str(exc)
    else:
        raise AssertionError("descending S/R timestamps must fail closed")
