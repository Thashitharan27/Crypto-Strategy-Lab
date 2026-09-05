from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_core.indicators import wilder_rsi
from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_core.timeseries import asof_oi_zscore, rolling_time_zscore
from crypto_strategy_lab.indicators import rsi
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS as CSL_RULE_INDICATORS


def test_shared_rule_contract_is_csl_rule_contract() -> None:
    assert CSL_RULE_INDICATORS is RULE_INDICATORS
    assert "RSI" in RULE_INDICATORS
    assert "OI_ZSCORE_7D" in RULE_INDICATORS
    assert "TAKER_FLOW_PERSISTENCE" in RULE_INDICATORS


def test_shared_rsi_matches_previous_csl_pandas_semantics() -> None:
    close = np.array(
        [100.0, 101.0, 99.5, 102.0, 103.0, 101.0, 104.0, 105.0, 106.0,
         104.5, 107.0, 108.0, 106.5, 109.0, 110.0, 108.0, 111.0, 112.0],
        dtype=float,
    )
    period = 14
    series = pd.Series(close, dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    expected = (100.0 - (100.0 / (1.0 + gain / loss))).to_numpy(float)

    np.testing.assert_allclose(
        np.asarray(wilder_rsi(close, period), dtype=float),
        expected,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        rsi(close, period),
        expected,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )


def test_shared_elapsed_zscore_matches_previous_csl_pandas_semantics() -> None:
    times = pd.date_range("2026-01-01", periods=36, freq="6h", tz="UTC")
    values = np.array(
        [1000.0 + i * 7.0 + (5.0 if i % 4 == 0 else -3.0) for i in range(len(times))],
        dtype=float,
    )
    days = 7.0
    minimum = 20
    reference = pd.Series(values, index=times)
    rolling = reference.rolling(f"{days}D", min_periods=minimum)
    std = rolling.std(ddof=0)
    expected = ((reference - rolling.mean()) / std.where(std > 0)).to_numpy(float)

    actual = np.asarray(
        rolling_time_zscore(
            values,
            times.to_pydatetime(),
            days=days,
            minimum=minimum,
        ),
        dtype=float,
    )
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )


def test_shared_asof_oi_zscore_accepts_unsorted_observations() -> None:
    times = pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC")
    observations = [
        (times[2].to_pydatetime(), 3.0),
        (times[0].to_pydatetime(), 1.0),
        (times[1].to_pydatetime(), 2.0),
    ]
    query = times[1] + pd.Timedelta(hours=12)
    assert asof_oi_zscore(observations, query.to_pydatetime()) == 2.0


def test_shared_asof_oi_zscore_keeps_last_duplicate_timestamp_value() -> None:
    timestamp = pd.Timestamp("2026-01-02T00:00:00Z")
    observations = [
        (timestamp.to_pydatetime(), 9.0),
        (pd.Timestamp("2026-01-01T00:00:00Z").to_pydatetime(), 1.0),
        (timestamp.to_pydatetime(), 2.0),
    ]
    query = timestamp + pd.Timedelta(hours=1)
    assert asof_oi_zscore(observations, query.to_pydatetime()) == 2.0
