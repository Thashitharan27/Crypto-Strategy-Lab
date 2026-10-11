"""Causal Fibonacci impulse quality regression."""
import json
import numpy as np
from crypto_strategy_lab.fib_retracement import fibonacci_retracement_arrays


def test_impulse_quality_diagnostics_penalize_single_candle_spike():
    close = np.array([10., 9., 8., 9., 9.2, 9.3, 17., 16., 15., 14., 13.])
    open_ = np.r_[close[0], close[:-1]]
    result = fibonacci_retracement_arrays(
        open_, close + 0.2, close - 0.2, close, np.ones(len(close)),
        pivot_strength=1, dominant_lookback_bars=32,
    )
    rows = [json.loads(value) for value in result["_FIB_CANDIDATE_INVENTORY_JSON"]]
    longs = [candidate for row in rows for candidate in row if candidate["direction"] == "LONG"]
    assert longs
    assert all(0 <= c["impulse_efficiency"] <= 1 for c in longs)
    assert all(0 <= c["impulse_largest_candle_share"] <= 1 for c in longs)
    assert all(0.55 <= c["impulse_quality_multiplier"] <= 1 for c in longs)
    assert any(c["impulse_largest_candle_share"] > 0.60
               and c["impulse_quality_multiplier"] < 1 for c in longs)
