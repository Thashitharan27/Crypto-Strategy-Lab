from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.data.legacy_bridge import (
    canonical_to_legacy_ohlcv,
    compare_ohlcv_frames,
    compare_trade_frames,
)


def test_canonical_bridge_matches_current_engine_shape() -> None:
    starts = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="15min")
    canonical = pd.DataFrame(
        {
            "period_start": starts,
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [10.0, 12.0],
        }
    )
    legacy = canonical_to_legacy_ohlcv(canonical, expected_timeframe_minutes=15)
    assert list(legacy.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert legacy.attrs["summary"].detected_timeframe_minutes == 15


def test_parity_detects_exact_and_changed_values() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="1h"),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10.0, 11.0],
        }
    )
    assert compare_ohlcv_frames(frame, frame.copy()).exact
    changed = frame.copy()
    changed.loc[1, "close"] = 2.6
    result = compare_ohlcv_frames(frame, changed)
    assert not result.exact
    assert result.value_mismatches == 1
    assert result.max_abs_diff["close"] > 0


def test_trade_parity_compares_complete_engine_rows() -> None:
    trades = pd.DataFrame(
        {
            "strategy_entry_time": pd.to_datetime(
                ["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"], utc=True
            ),
            "direction": ["LONG", "SHORT"],
            "entry_price": [100.0, 110.0],
            "exit_price": [102.0, 108.0],
            "net_r": [1.0, 0.5],
            "exit_reason": ["TP", "TP"],
        }
    )
    assert compare_trade_frames(trades, trades.copy()).exact

    changed = trades.copy()
    changed.loc[1, "net_r"] = 0.4
    changed.loc[0, "exit_reason"] = "SL"
    result = compare_trade_frames(trades, changed)
    assert not result.exact
    assert result.mismatched_rows == 2
    assert result.column_mismatches["net_r"] == 1
    assert result.column_mismatches["exit_reason"] == 1
    assert result.max_abs_diff["net_r"] > 0


def test_trade_parity_detects_schema_and_row_count_changes() -> None:
    left = pd.DataFrame({"direction": ["LONG"], "net_r": [1.0]})
    right = pd.DataFrame({"direction": ["LONG", "SHORT"], "other": [1, 2]})
    result = compare_trade_frames(left, right)
    assert not result.exact
    assert result.rows_left == 1
    assert result.rows_right == 2
    assert result.columns_only_left == ("net_r",)
    assert result.columns_only_right == ("other",)
    assert result.mismatched_rows == 1
