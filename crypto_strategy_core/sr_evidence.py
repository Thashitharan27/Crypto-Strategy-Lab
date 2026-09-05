"""Causal support/resistance context series shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .candles import atr
from .higher_timeframe_sr import HigherTimeframeSRDetector, resample_ohlc_for_sr
from .support_resistance import SRContext, SupportResistanceDetector


@dataclass(frozen=True)
class SupportResistanceSeries:
    long: tuple[SRContext, ...]
    short: tuple[SRContext, ...]
    completed_candle_time: tuple[pd.Timestamp | None, ...]
    effective_minutes: int


def support_resistance_context_series(
    timestamps: Sequence[object],
    available_at: Sequence[object],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    atr_values: Sequence[float],
    *,
    strategy_minutes: int,
    parameters: Mapping[str, object] | None = None,
) -> SupportResistanceSeries:
    """Return CSL-equivalent LONG/SHORT S/R contexts for every decision row."""
    params = dict(parameters or {})
    size = len(close)
    if not (
        len(timestamps)
        == len(available_at)
        == len(open_)
        == len(high)
        == len(low)
        == len(atr_values)
        == size
    ):
        raise ValueError("support/resistance inputs must have equal lengths")
    if isinstance(strategy_minutes, bool) or not isinstance(strategy_minutes, int) or strategy_minutes <= 0:
        raise ValueError("strategy_minutes must be a positive integer")

    source_times = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True))
    decision_times = pd.DatetimeIndex(pd.to_datetime(list(available_at), utc=True))
    if size and (
        not source_times.is_monotonic_increasing
        or not decision_times.is_monotonic_increasing
    ):
        raise ValueError("support/resistance timestamps must be chronological")
    if bool((decision_times < source_times).any()):
        raise ValueError("support/resistance availability precedes source candle")

    configured_minutes = int(params.get("sr_timeframe_minutes", 0) or 0)
    effective_minutes = configured_minutes or strategy_minutes
    if effective_minutes < strategy_minutes or effective_minutes % strategy_minutes:
        raise ValueError(
            "S/R timeframe must be the strategy timeframe or an integer multiple"
        )

    atr_period = int(params.get("atr_period", 14))
    if atr_period <= 0:
        raise ValueError("S/R ATR period must be positive")
    detector_config = {
        "pivot_left": int(params.get("sr_pivot_left", 5)),
        "pivot_right": int(params.get("sr_pivot_right", 5)),
        "lookback_bars": int(params.get("sr_lookback_bars", 200)),
        "zone_width_atr": float(params.get("sr_zone_width_atr", 0.5)),
        "near_distance_atr": float(params.get("sr_near_distance_atr", 0.75)),
        "enable_hold_confirmation": bool(
            params.get("enable_sr_hold_confirmation", False)
        ),
        "hold_confirmation_bars": int(params.get("sr_hold_confirmation_bars", 3)),
        "hold_confirmation_atr": float(params.get("sr_hold_confirmation_atr", 0.25)),
        "break_tolerance_atr": float(params.get("sr_break_tolerance_atr", 0.25)),
        "break_basis": str(params.get("sr_break_basis", "CLOSE")).upper(),
    }

    open_values = np.asarray(open_, dtype=float)
    high_values = np.asarray(high, dtype=float)
    low_values = np.asarray(low, dtype=float)
    close_values = np.asarray(close, dtype=float)
    atr_array = np.asarray(atr_values, dtype=float)

    long_contexts: list[SRContext] = []
    short_contexts: list[SRContext] = []
    completed: list[pd.Timestamp | None] = []

    if effective_minutes == strategy_minutes:
        detector = SupportResistanceDetector(**detector_config)
        for index in range(size):
            long_contexts.append(
                detector.analyze_price_location(
                    index,
                    open_values,
                    high_values,
                    low_values,
                    close_values,
                    atr_array,
                    "LONG",
                )
            )
            short_contexts.append(
                detector.analyze_price_location(
                    index,
                    open_values,
                    high_values,
                    low_values,
                    close_values,
                    atr_array,
                    "SHORT",
                )
            )
            completed.append(pd.Timestamp(decision_times[index]))
    else:
        legacy = pd.DataFrame(
            {
                "timestamp": source_times,
                "open": open_values,
                "high": high_values,
                "low": low_values,
                "close": close_values,
            }
        )
        htf = resample_ohlc_for_sr(
            legacy,
            strategy_minutes,
            effective_minutes,
        )
        htf_open = htf["open"].to_numpy(float)
        htf_high = htf["high"].to_numpy(float)
        htf_low = htf["low"].to_numpy(float)
        htf_close = htf["close"].to_numpy(float)
        htf_atr = np.asarray(
            atr(
                htf_high,
                htf_low,
                htf_close,
                atr_period,
            ),
            dtype=float,
        )
        htf_end = pd.DatetimeIndex(pd.to_datetime(htf["end_time"], utc=True))
        htf_end_ns = htf_end.asi8
        detector = HigherTimeframeSRDetector(**detector_config)
        for index in range(size):
            available_ns = pd.Timestamp(decision_times[index]).value
            htf_index = int(
                np.searchsorted(htf_end_ns, available_ns, side="right") - 1
            )
            if htf_index < 0:
                long_contexts.append(detector._default_context())
                short_contexts.append(detector._default_context())
                completed.append(None)
                continue
            long_contexts.append(
                detector.analyze_external_price(
                    htf_index,
                    htf_open,
                    htf_high,
                    htf_low,
                    htf_close,
                    htf_atr,
                    "LONG",
                    float(close_values[index]),
                )
            )
            short_contexts.append(
                detector.analyze_external_price(
                    htf_index,
                    htf_open,
                    htf_high,
                    htf_low,
                    htf_close,
                    htf_atr,
                    "SHORT",
                    float(close_values[index]),
                )
            )
            completed.append(pd.Timestamp(htf_end[htf_index]))

    return SupportResistanceSeries(
        tuple(long_contexts),
        tuple(short_contexts),
        tuple(completed),
        effective_minutes,
    )
