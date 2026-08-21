from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.data.legacy_bridge import canonical_to_legacy_ohlcv, compare_ohlcv_frames


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
