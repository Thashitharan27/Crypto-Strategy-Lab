"""TradingView-style ATR using shared strategy-core semantics."""
from __future__ import annotations

import numpy as np

from crypto_strategy_core.candles import (
    atr as _shared_atr,
    true_range as _shared_true_range,
    wilder_rma as _shared_wilder_rma,
)


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    return np.asarray(_shared_true_range(high, low, close), dtype=float)


def rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder RMA seeded with the first full-period SMA, matching TradingView."""
    return np.asarray(_shared_wilder_rma(values, period), dtype=float)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    return np.asarray(_shared_atr(high, low, close, period), dtype=float)
