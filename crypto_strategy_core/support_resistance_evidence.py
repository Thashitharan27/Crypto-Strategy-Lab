"""Shared causal support/resistance evidence for research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from .candles import atr as shared_atr
from .higher_timeframe_sr import HigherTimeframeSRDetector, resample_ohlc_for_sr
from .support_resistance import SRContext, SupportResistanceDetector

SR_CONTEXT_FIELDS = (
    "nearest_support_price", "nearest_support_bar_index",
    "nearest_support_distance_atr", "nearest_support_distance_price",
    "nearest_resistance_price", "nearest_resistance_bar_index",
    "nearest_resistance_distance_atr", "nearest_resistance_distance_price",
    "price_location", "trade_location_rating", "near_support", "near_resistance",
    "inside_support_zone", "inside_resistance_zone", "room_in_direction_atr",
    "support_state", "resistance_state", "support_tested", "resistance_tested",
    "support_held", "resistance_held", "support_rejection_atr",
    "resistance_rejection_atr", "support_test_count", "resistance_test_count",
    "bars_since_support_test", "bars_since_resistance_test",
    "support_last_test_index", "resistance_last_test_index", "confirmation_rating",
    "support_zone_low", "support_zone_high", "resistance_zone_low",
    "resistance_zone_high",
)


def _primitive(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _flatten(prefix: str, context: SRContext) -> dict[str, object]:
    return {
        f"{prefix}_{field}": _primitive(getattr(context, field))
        for field in SR_CONTEXT_FIELDS
    }


def support_resistance_evidence_series(
    timestamps: Sequence[object],
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    atr_values: Sequence[float],
    *,
    strategy_minutes: int,
    sr_timeframe_minutes: int = 0,
    atr_period: int = 14,
    pivot_left: int = 5,
    pivot_right: int = 5,
    lookback_bars: int = 200,
    zone_width_atr: float = 0.5,
    near_distance_atr: float = 0.75,
    enable_hold_confirmation: bool = False,
    hold_confirmation_bars: int = 3,
    hold_confirmation_atr: float = 0.25,
    break_tolerance_atr: float = 0.25,
    break_basis: str = "CLOSE",
) -> list[dict[str, object]]:
    """Return CSL-compatible LONG/SHORT S/R context for each strategy candle.

    For higher-timeframe S/R, only complete resampled candles whose end time is
    at or before the current strategy decision timestamp are exposed.
    """
    times = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True))
    arrays = [np.asarray(values, dtype=float) for values in (opens, highs, lows, closes, atr_values)]
    size = len(times)
    if any(len(values) != size for values in arrays):
        raise ValueError("S/R timestamps, OHLC and ATR inputs must have equal lengths")
    if size and not times.is_monotonic_increasing:
        raise ValueError("S/R timestamps must be chronological")
    if strategy_minutes <= 0 or atr_period <= 0:
        raise ValueError("S/R strategy timeframe and ATR period must be positive")
    effective_minutes = int(sr_timeframe_minutes or strategy_minutes)
    if effective_minutes < strategy_minutes or effective_minutes % strategy_minutes:
        raise ValueError("S/R timeframe must be the strategy timeframe or an integer multiple")

    open_, high, low, close, atr_source = arrays
    config = dict(
        pivot_left=int(pivot_left),
        pivot_right=int(pivot_right),
        lookback_bars=int(lookback_bars),
        zone_width_atr=float(zone_width_atr),
        near_distance_atr=float(near_distance_atr),
        enable_hold_confirmation=bool(enable_hold_confirmation),
        hold_confirmation_bars=int(hold_confirmation_bars),
        hold_confirmation_atr=float(hold_confirmation_atr),
        break_tolerance_atr=float(break_tolerance_atr),
        break_basis=str(break_basis).upper(),
    )
    rows: list[dict[str, object]] = []

    if effective_minutes == strategy_minutes:
        detector = SupportResistanceDetector(**config)
        for index in range(size):
            long_context = detector.analyze_price_location(
                index, open_, high, low, close, atr_source, "LONG"
            )
            short_context = detector.analyze_price_location(
                index, open_, high, low, close, atr_source, "SHORT"
            )
            row: dict[str, object] = {"sr_completed_candle_time": times[index]}
            row.update(_flatten("long", long_context))
            row.update(_flatten("short", short_context))
            rows.append(row)
        return rows

    strategy_frame = pd.DataFrame(
        {
            "timestamp": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    )
    htf = resample_ohlc_for_sr(strategy_frame, strategy_minutes, effective_minutes)
    htf_open = htf["open"].to_numpy(float)
    htf_high = htf["high"].to_numpy(float)
    htf_low = htf["low"].to_numpy(float)
    htf_close = htf["close"].to_numpy(float)
    htf_atr = np.asarray(shared_atr(htf_high, htf_low, htf_close, atr_period), dtype=float)
    htf_end = pd.DatetimeIndex(pd.to_datetime(htf["end_time"], utc=True))
    htf_end_ns = htf_end.asi8
    detector = HigherTimeframeSRDetector(**config)

    for index, decision_time in enumerate(times):
        htf_index = int(np.searchsorted(htf_end_ns, decision_time.value, side="right") - 1)
        if htf_index < 0:
            long_context = detector._default_context()
            short_context = detector._default_context()
            completed: object = pd.NaT
        else:
            long_context = detector.analyze_external_price(
                htf_index,
                htf_open,
                htf_high,
                htf_low,
                htf_close,
                htf_atr,
                "LONG",
                float(close[index]),
            )
            short_context = detector.analyze_external_price(
                htf_index,
                htf_open,
                htf_high,
                htf_low,
                htf_close,
                htf_atr,
                "SHORT",
                float(close[index]),
            )
            completed = htf_end[htf_index]
        row = {"sr_completed_candle_time": completed}
        row.update(_flatten("long", long_context))
        row.update(_flatten("short", short_context))
        rows.append(row)
    return rows
