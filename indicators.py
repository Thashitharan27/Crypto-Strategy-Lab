"""15-minute strategy-candle indicator calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd


def bollinger_bands(close: np.ndarray, period: int = 20, stddevs: float = 2.0):
    s = pd.Series(close, dtype="float64")
    middle = s.rolling(period, min_periods=period).mean().to_numpy(float)
    # TradingView's Bollinger Bands use population standard deviation.
    std = s.rolling(period, min_periods=period).std(ddof=0).to_numpy(float)
    upper = middle + stddevs * std
    lower = middle - stddevs * std
    width = np.divide(upper - lower, middle, out=np.full_like(middle, np.nan), where=np.isfinite(middle) & (middle != 0))
    return middle, upper, lower, width, width * 100.0


def lag(values: np.ndarray, bars: int) -> np.ndarray:
    out = np.full(len(values), np.nan, float)
    if bars < len(values):
        out[bars:] = values[:-bars]
    return out
