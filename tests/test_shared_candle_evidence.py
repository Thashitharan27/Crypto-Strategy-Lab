from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_core.candles import (
    atr,
    bollinger_bands,
    causal_trailing_return,
    close_location,
    directional_pressure_features,
    directional_rule_evidence,
    utc_session_vwap,
)
from crypto_strategy_lab.atr import atr as csl_atr
from crypto_strategy_lab.features.market_regime import causal_trailing_return as csl_momentum
from crypto_strategy_lab.indicators import bollinger_bands as csl_bollinger


def _reference_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    previous = np.empty_like(close)
    previous[0] = close[0]
    previous[1:] = close[:-1]
    tr = np.maximum.reduce((high - low, np.abs(high - previous), np.abs(low - previous)))
    output = np.full(len(close), np.nan)
    seed = float(np.mean(tr[:period]))
    output[period - 1] = seed
    alpha = 1.0 / period
    for index in range(period, len(close)):
        output[index] = output[index - 1] + alpha * (tr[index] - output[index - 1])
    return output


def test_shared_atr_and_bollinger_preserve_csl_formulas() -> None:
    close = np.array([100 + i * 0.7 + (i % 3) * 0.2 for i in range(40)], dtype=float)
    high = close + np.array([1.0 + (i % 2) * 0.3 for i in range(40)])
    low = close - np.array([0.8 + (i % 4) * 0.1 for i in range(40)])
    expected_atr = _reference_atr(high, low, close, 14)

    np.testing.assert_allclose(
        np.asarray(atr(high, low, close, 14)),
        expected_atr,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_allclose(csl_atr(high, low, close, 14), expected_atr, rtol=0.0, atol=0.0, equal_nan=True)

    source = pd.Series(close)
    middle = source.rolling(20, min_periods=20).mean().to_numpy(float)
    std = source.rolling(20, min_periods=20).std(ddof=0).to_numpy(float)
    upper, lower = middle + 2.0 * std, middle - 2.0 * std
    width = np.divide(upper - lower, middle, out=np.full_like(middle, np.nan), where=np.isfinite(middle) & (middle != 0))
    expected = (middle, upper, lower, width, width * 100.0)

    for actual, reference in zip(bollinger_bands(close, 20, 2.0), expected):
        np.testing.assert_allclose(np.asarray(actual), reference, rtol=0.0, atol=0.0, equal_nan=True)
    for actual, reference in zip(csl_bollinger(close, 20, 2.0), expected):
        np.testing.assert_allclose(actual, reference, rtol=0.0, atol=0.0, equal_nan=True)


def test_shared_momentum_vwap_and_close_location_preserve_causal_csl_semantics() -> None:
    times = pd.date_range("2026-01-01T18:00:00Z", periods=20, freq="2h")
    close = np.array([100.0 + i for i in range(len(times))])
    high, low = close + 2.0, close - 1.0
    volume = np.array([10.0 + (i % 5) for i in range(len(times))])

    expected_momentum = np.full(len(times), np.nan)
    targets = times - pd.Timedelta(hours=7)
    prior = np.searchsorted(times.asi8, targets.asi8, side="right") - 1
    valid = prior >= 0
    expected_momentum[valid] = close[valid] / close[prior[valid]] - 1.0

    shared_momentum = np.asarray(causal_trailing_return(times, close, hours=7))
    np.testing.assert_allclose(shared_momentum, expected_momentum, rtol=0.0, atol=0.0, equal_nan=True)
    np.testing.assert_allclose(
        csl_momentum(times, close, pd.Timedelta(hours=7)),
        expected_momentum,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )

    typical = (high + low + close) / 3.0
    sessions = pd.Series(times).dt.floor("D")
    cumulative_weighted = pd.Series(typical * volume).groupby(sessions).cumsum().to_numpy(float)
    cumulative_volume = pd.Series(volume).groupby(sessions).cumsum().to_numpy(float)
    expected_vwap = cumulative_weighted / cumulative_volume
    np.testing.assert_allclose(
        np.asarray(utc_session_vwap(times, high, low, close, volume)),
        expected_vwap,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        np.asarray(close_location(high, low, close)),
        (close - low) / (high - low),
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )


def test_shared_directional_pressure_matches_csl_pressure_contract() -> None:
    plus = np.array([20.0, 21.0, 19.0, 25.0, 27.0, 24.0, 30.0])
    minus = np.array([18.0, 17.0, 20.0, 16.0, 15.0, 18.0, 14.0])
    lookback = 3
    pressure = directional_pressure_features(plus, minus, lookback)

    plus_change = plus - np.concatenate([np.full(lookback, np.nan), plus[:-lookback]])
    minus_change = minus - np.concatenate([np.full(lookback, np.nan), minus[:-lookback]])
    spread = np.abs(plus - minus)
    spread_change = spread - np.concatenate([np.full(lookback, np.nan), spread[:-lookback]])

    np.testing.assert_allclose(pressure["plus_di_change"], plus_change, equal_nan=True)
    np.testing.assert_allclose(pressure["minus_di_change"], minus_change, equal_nan=True)
    np.testing.assert_allclose(pressure["di_pressure_spread_change"], spread_change, equal_nan=True)

    evidence = directional_rule_evidence(
        plus,
        minus,
        index=6,
        lookback=lookback,
        side="LONG",
    )
    assert evidence["DIRECTIONAL_DI"] == plus[6]
    assert evidence["DIRECTIONAL_DI_CHANGE"] == plus_change[6]
    assert evidence["OPPOSING_DI_CHANGE"] == minus_change[6]
    assert evidence["DI_SPREAD_CHANGE"] == spread_change[6]
    assert evidence["DI_PRESSURE_STATE"] == "EXPANDING"


def test_shared_candle_evidence_does_not_let_future_rows_change_past_values() -> None:
    times = pd.date_range("2026-01-01", periods=32, freq="1h")
    close = np.linspace(100.0, 131.0, len(times))
    high, low = close + 2.0, close - 1.0
    volume = np.linspace(10.0, 20.0, len(times))
    cutoff = 23

    baseline = np.asarray(causal_trailing_return(times, close, hours=6))
    baseline_vwap = np.asarray(utc_session_vwap(times, high, low, close, volume))

    changed_close = close.copy()
    changed_high = high.copy()
    changed_low = low.copy()
    changed_volume = volume.copy()
    changed_close[cutoff + 1 :] *= 5.0
    changed_high[cutoff + 1 :] *= 5.0
    changed_low[cutoff + 1 :] *= 5.0
    changed_volume[cutoff + 1 :] *= 10.0

    changed_momentum = np.asarray(causal_trailing_return(times, changed_close, hours=6))
    changed_vwap = np.asarray(utc_session_vwap(times, changed_high, changed_low, changed_close, changed_volume))

    np.testing.assert_allclose(changed_momentum[: cutoff + 1], baseline[: cutoff + 1], equal_nan=True)
    np.testing.assert_allclose(changed_vwap[: cutoff + 1], baseline_vwap[: cutoff + 1], equal_nan=True)
