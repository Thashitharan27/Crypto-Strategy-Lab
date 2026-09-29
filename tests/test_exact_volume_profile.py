import json

import numpy as np
import pandas as pd

from crypto_strategy_lab.exact_volume_profile import exact_profile_frame


def _aggregate(minutes=80):
    starts = pd.date_range("2026-01-01", periods=minutes, freq="1min", tz="UTC")
    payload = []
    for i, _ in enumerate(starts):
        price = 100.0 + 0.02 * i
        payload.append(json.dumps([[price, 2.0, 1.2, 0.8]], separators=(",", ":")))
    return pd.DataFrame({
        "period_start": starts,
        "period_end": starts + pd.Timedelta(minutes=1),
        "available_at": starts + pd.Timedelta(minutes=1),
        "volume_at_price_json": payload,
    })


def _strategy(minutes=80):
    starts = pd.date_range("2026-01-01", periods=minutes, freq="1min", tz="UTC")
    close = 100.0 + 0.02 * np.arange(minutes)
    return pd.DataFrame({
        "period_start": starts,
        "available_at": starts + pd.Timedelta(minutes=1),
        "open": close - 0.02,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
    })


def test_exact_aggtrade_profile_emits_strategy_context_after_warmup():
    out = exact_profile_frame(
        _aggregate(),
        _strategy(),
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )
    row = out.iloc[-1]
    assert row["vp_exact_strategy_position"] in {
        "ABOVE_VAH", "INSIDE_VALUE", "BELOW_VAL"
    }
    assert np.isfinite(row["vp_exact_strategy_poc_distance_atr"])
    assert np.isfinite(row["vp_exact_strategy_hvn_distance_atr"])
    assert 0.0 <= row["vp_exact_strategy_hvn_strength"] <= 1.0


def test_future_volume_at_price_cannot_change_past_profile():
    aggregate = _aggregate()
    strategy = _strategy()
    before = exact_profile_frame(
        aggregate,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    changed = aggregate.copy()
    cutoff = 50
    changed.loc[cutoff:, "volume_at_price_json"] = json.dumps(
        [[500.0, 1_000_000.0, 1_000_000.0, 0.0]],
        separators=(",", ":"),
    )
    after = exact_profile_frame(
        changed,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    columns = [
        "vp_exact_strategy_poc_distance_atr",
        "vp_exact_strategy_hvn_distance_atr",
        "vp_exact_strategy_hvn_strength",
        "vp_exact_strategy_accumulation_score",
    ]
    pd.testing.assert_frame_equal(
        before.loc[: cutoff - 1, columns],
        after.loc[: cutoff - 1, columns],
    )
