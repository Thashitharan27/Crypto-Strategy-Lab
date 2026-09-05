"""15-minute strategy-candle indicator calculations."""
from __future__ import annotations

import numpy as np

from crypto_strategy_core.candles import bollinger_bands as _shared_bollinger_bands
from crypto_strategy_core.indicators import wilder_rsi


def bollinger_bands(close: np.ndarray, period: int = 20, stddevs: float = 2.0):
    values = _shared_bollinger_bands(close, period, stddevs)
    return tuple(np.asarray(value, dtype=float) for value in values)


def lag(values: np.ndarray, bars: int) -> np.ndarray:
    out = np.full(len(values), np.nan, float)
    if bars < len(values):
        out[bars:] = values[:-bars]
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder RSI calculated by the shared research/live strategy core."""
    return np.asarray(wilder_rsi(close, period), dtype=float)
