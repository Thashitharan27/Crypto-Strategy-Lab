"""Deterministic indicator primitives shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def wilder_rsi(close: Sequence[float], period: int = 14) -> list[float]:
    """Return CSL-compatible Wilder RSI using pandas EWM semantics."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("RSI period must be a positive integer")
    series = pd.Series([float(value) for value in close], dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    rs = gain / loss
    return (100.0 - (100.0 / (1.0 + rs))).to_numpy(float).tolist()
