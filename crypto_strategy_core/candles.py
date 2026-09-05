"""Deterministic completed-candle evidence shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import pandas as pd


def _positive_period(period: int, label: str) -> int:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return period


def true_range(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
) -> list[float]:
    high_values = np.asarray(high, dtype=float)
    low_values = np.asarray(low, dtype=float)
    close_values = np.asarray(close, dtype=float)
    if not (len(high_values) == len(low_values) == len(close_values)):
        raise ValueError("high, low and close must have equal lengths")
    if len(close_values) == 0:
        return []
    previous_close = np.empty_like(close_values, dtype=float)
    previous_close[0] = close_values[0]
    previous_close[1:] = close_values[:-1]
    result = np.maximum.reduce(
        (
            high_values - low_values,
            np.abs(high_values - previous_close),
            np.abs(low_values - previous_close),
        )
    )
    return result.tolist()


def wilder_rma(values: Sequence[float], period: int) -> list[float]:
    """CSL ATR-style Wilder RMA seeded from the first period."""
    period = _positive_period(period, "period")
    source = np.asarray(values, dtype=float)
    output = np.full(source.shape, np.nan, dtype=float)
    if len(source) < period:
        return output.tolist()
    seed_values = source[:period]
    seed = (
        float(np.mean(seed_values[~np.isnan(seed_values)]))
        if np.isfinite(seed_values).any()
        else np.nan
    )
    output[period - 1] = seed
    alpha = 1.0 / period
    for index in range(period, len(source)):
        output[index] = output[index - 1] + alpha * (
            source[index] - output[index - 1]
        )
    return output.tolist()


def atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> list[float]:
    return wilder_rma(true_range(high, low, close), period)


def bollinger_bands(
    close: Sequence[float],
    period: int = 20,
    stddevs: float = 2.0,
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Return CSL/TradingView population-stddev Bollinger values."""
    period = _positive_period(period, "Bollinger period")
    deviations = float(stddevs)
    if not np.isfinite(deviations) or deviations <= 0:
        raise ValueError("Bollinger stddevs must be positive and finite")
    series = pd.Series([float(value) for value in close], dtype="float64")
    middle = series.rolling(period, min_periods=period).mean().to_numpy(float)
    std = series.rolling(period, min_periods=period).std(ddof=0).to_numpy(float)
    upper = middle + deviations * std
    lower = middle - deviations * std
    width = np.divide(
        upper - lower,
        middle,
        out=np.full_like(middle, np.nan),
        where=np.isfinite(middle) & (middle != 0),
    )
    return (
        middle.tolist(),
        upper.tolist(),
        lower.tolist(),
        width.tolist(),
        (width * 100.0).tolist(),
    )


def close_location(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
) -> list[float]:
    high_values = np.asarray(high, dtype=float)
    low_values = np.asarray(low, dtype=float)
    close_values = np.asarray(close, dtype=float)
    if not (len(high_values) == len(low_values) == len(close_values)):
        raise ValueError("high, low and close must have equal lengths")
    candle_range = high_values - low_values
    result = np.divide(
        close_values - low_values,
        candle_range,
        out=np.full(len(close_values), np.nan, dtype=float),
        where=np.isfinite(candle_range) & (candle_range != 0),
    )
    return result.tolist()


def utc_session_vwap(
    timestamps: Sequence[datetime],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
) -> list[float]:
    times = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True))
    high_values = np.asarray(high, dtype=float)
    low_values = np.asarray(low, dtype=float)
    close_values = np.asarray(close, dtype=float)
    volume_values = np.asarray(volume, dtype=float)
    size = len(times)
    if not (
        size
        == len(high_values)
        == len(low_values)
        == len(close_values)
        == len(volume_values)
    ):
        raise ValueError("timestamps and OHLCV inputs must have equal lengths")
    typical = (high_values + low_values + close_values) / 3.0
    sessions = pd.Series(times).dt.floor("D")
    cumulative_weighted = (
        pd.Series(typical * volume_values).groupby(sessions).cumsum().to_numpy(float)
    )
    cumulative_volume = (
        pd.Series(volume_values).groupby(sessions).cumsum().to_numpy(float)
    )
    result = np.divide(
        cumulative_weighted,
        cumulative_volume,
        out=np.full(size, np.nan, dtype=float),
        where=cumulative_volume > 0,
    )
    return result.tolist()


def causal_trailing_return(
    timestamps: Sequence[datetime],
    close: Sequence[float],
    *,
    hours: float,
) -> list[float]:
    """Close return against the latest candle at or before time-lookback."""
    lookback = float(hours)
    if not np.isfinite(lookback) or lookback <= 0:
        raise ValueError("momentum lookback hours must be positive and finite")
    times = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True))
    values = np.asarray(close, dtype=float)
    if len(times) != len(values):
        raise ValueError("timestamps and close values must have equal lengths")
    if len(times) and not times.is_monotonic_increasing:
        raise ValueError("momentum timestamps must be chronological")
    result = np.full(len(times), np.nan, dtype=float)
    targets = times - pd.Timedelta(hours=lookback)
    prior = np.searchsorted(times.asi8, targets.asi8, side="right") - 1
    valid = prior >= 0
    result[valid] = values[valid] / values[prior[valid]] - 1.0
    return result.tolist()


def directional_pressure_features(
    plus_di: Sequence[float],
    minus_di: Sequence[float],
    lookback: int,
) -> dict[str, list[float] | list[str]]:
    """Return the CSL DI-pressure change/state arrays for both directions."""
    lookback = _positive_period(lookback, "DI pressure lookback")
    plus = np.asarray(plus_di, dtype=float)
    minus = np.asarray(minus_di, dtype=float)
    if len(plus) != len(minus):
        raise ValueError("plus_di and minus_di must have equal lengths")

    def lag(values: np.ndarray) -> np.ndarray:
        output = np.full(len(values), np.nan, dtype=float)
        if lookback < len(values):
            output[lookback:] = values[:-lookback]
        return output

    plus_change = plus - lag(plus)
    minus_change = minus - lag(minus)
    spread = np.abs(plus - minus)
    spread_change = spread - lag(spread)

    def state(directional: np.ndarray, opposing: np.ndarray) -> list[str]:
        output = np.full(len(directional), "UNKNOWN", dtype=object)
        finite = np.isfinite(directional) & np.isfinite(opposing)
        output[finite] = "MIXED"
        output[finite & (directional > 0) & (opposing < 0)] = "EXPANDING"
        output[finite & (directional < 0) & (opposing > 0)] = "CONTRACTING"
        return [str(value) for value in output.tolist()]

    return {
        "plus_di_change": plus_change.tolist(),
        "minus_di_change": minus_change.tolist(),
        "di_pressure_spread_change": spread_change.tolist(),
        "long_directional_di_change": plus_change.tolist(),
        "long_opposing_di_change": minus_change.tolist(),
        "long_di_pressure_state": state(plus_change, minus_change),
        "short_directional_di_change": minus_change.tolist(),
        "short_opposing_di_change": plus_change.tolist(),
        "short_di_pressure_state": state(minus_change, plus_change),
    }


def directional_rule_evidence(
    plus_di: Sequence[float],
    minus_di: Sequence[float],
    *,
    index: int,
    lookback: int,
    side: str,
) -> dict[str, float | str]:
    """Return current shared DI evidence for one LONG/SHORT decision."""
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if index < 0 or index >= len(plus_di) or len(plus_di) != len(minus_di):
        raise ValueError("directional evidence index is out of range")
    features = directional_pressure_features(plus_di, minus_di, lookback)
    plus = float(plus_di[index])
    minus = float(minus_di[index])
    directional = plus if side == "LONG" else minus
    directional_change = (
        features["long_directional_di_change"][index]
        if side == "LONG"
        else features["short_directional_di_change"][index]
    )
    opposing_change = (
        features["long_opposing_di_change"][index]
        if side == "LONG"
        else features["short_opposing_di_change"][index]
    )
    state = (
        features["long_di_pressure_state"][index]
        if side == "LONG"
        else features["short_di_pressure_state"][index]
    )
    return {
        "DIRECTIONAL_DI": directional,
        "DI_SPREAD_CHANGE": float(features["di_pressure_spread_change"][index]),
        "DIRECTIONAL_DI_CHANGE": float(directional_change),
        "OPPOSING_DI_CHANGE": float(opposing_change),
        "DI_PRESSURE_STATE": str(state),
    }
