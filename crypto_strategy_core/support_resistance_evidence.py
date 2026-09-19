"""Shared causal support/resistance evidence for research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any

import numpy as np
import pandas as pd

from .candles import atr as shared_atr
from .higher_timeframe_sr import resample_ohlc_for_sr
from .research_support_resistance import (
    ResearchHigherTimeframeSRDetector,
    ResearchSupportResistanceDetector,
)
from .support_resistance import (
    SRContext,
    _positive_integral,
)

SR_CONTEXT_FIELDS = (
    "nearest_support_price", "nearest_support_bar_index",
    "nearest_support_distance_atr", "nearest_support_distance_price",
    "nearest_resistance_price", "nearest_resistance_bar_index",
    "nearest_resistance_distance_atr", "nearest_resistance_distance_price",
    "price_location", "trade_location_rating", "near_support", "near_resistance",
    "inside_support_zone", "inside_resistance_zone", "room_in_direction_atr",
    "structure_conflict",
    "support_state", "resistance_state", "support_tested", "resistance_tested",
    "support_held", "resistance_held", "support_rejection_atr",
    "resistance_rejection_atr", "support_test_count", "resistance_test_count",
    "bars_since_support_test", "bars_since_resistance_test",
    "support_last_test_index", "resistance_last_test_index", "confirmation_rating",
    "support_zone_low", "support_zone_high", "resistance_zone_low",
    "resistance_zone_high",
    "support_last_break_index", "resistance_last_break_index",
    "support_broken_zone_low", "support_broken_zone_high",
    "resistance_broken_zone_low", "resistance_broken_zone_high",
)


def _primitive(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _flatten(prefix: str, context: SRContext) -> dict[str, object]:
    return {
        f"{prefix}_{field}": _primitive(getattr(context, field))
        for field in SR_CONTEXT_FIELDS
    }


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _zone_inventory(
    detector,
    *,
    index: int,
    high: np.ndarray,
    low: np.ndarray,
    current_price: float,
    current_atr: float,
) -> list[dict[str, object]]:
    """Return every active merged zone already known at the supplied index.

    This is diagnostic/persistence evidence only. Strategy decisions continue to
    use the existing nearest support/resistance context.
    """
    if index < 0 or not np.isfinite(current_atr) or current_atr <= 0:
        return []
    supports = detector._find_support_levels(high, low, index, current_atr)
    resistances = detector._find_resistance_levels(high, low, index, current_atr)
    nearest_support = detector._nearest_level(supports, current_price, below=True)
    nearest_resistance = detector._nearest_level(
        resistances, current_price, below=False
    )
    nearest_keys = {
        "SUPPORT": detector._zone_key(nearest_support)
        if nearest_support is not None
        else None,
        "RESISTANCE": detector._zone_key(nearest_resistance)
        if nearest_resistance is not None
        else None,
    }

    result: list[dict[str, object]] = []
    for support, levels in ((True, supports), (False, resistances)):
        structure = "SUPPORT" if support else "RESISTANCE"
        for level in levels:
            metrics = detector._interaction_metrics(level, index, support)
            distance_price, distance_atr = detector._calculate_distance(
                current_price, level, current_atr
            )
            key = detector._zone_key(level)
            sources = tuple(int(value) for value in key[1])
            low_value = float(level.zone_bottom)
            high_value = float(level.zone_top)
            result.append(
                {
                    "zone_id": f"{structure}:" + ",".join(map(str, sources)),
                    "structure": structure,
                    "zone_low": low_value,
                    "zone_high": high_value,
                    "anchor_price": float(level.price),
                    "pivot_bar_index": int(level.bar_index),
                    "confirmed_at_index": (
                        int(level.confirmed_at_index)
                        if level.confirmed_at_index is not None
                        else None
                    ),
                    "source_bar_indices": list(sources),
                    "source_count": len(sources),
                    "touch_count": int(level.touch_count),
                    "validation_rejection_atr": _finite_or_none(
                        level.validation_rejection_atr
                    ),
                    "state": str(metrics["state"]),
                    "tested": bool(metrics["tested"]),
                    "held": bool(metrics["held"]),
                    "rejection_atr": _finite_or_none(metrics["rejection_atr"]),
                    "test_count": int(metrics["test_count"]),
                    "bars_since_test": (
                        int(metrics["bars_since_test"])
                        if metrics["bars_since_test"] is not None
                        else None
                    ),
                    "last_test_index": (
                        int(metrics["last_test_index"])
                        if metrics["last_test_index"] is not None
                        else None
                    ),
                    "distance_price": _finite_or_none(distance_price),
                    "distance_atr": _finite_or_none(distance_atr),
                    "near": bool(
                        np.isfinite(distance_atr)
                        and distance_atr <= detector.near_distance_atr
                    ),
                    "inside": bool(low_value <= current_price <= high_value),
                    "nearest": key == nearest_keys[structure],
                }
            )
    result.sort(
        key=lambda item: (
            0 if item["structure"] == "SUPPORT" else 1,
            float(item["zone_low"]),
            str(item["zone_id"]),
        )
    )
    return result


def _inventory_json(rows: list[dict[str, object]]) -> str:
    return json.dumps(rows, separators=(",", ":"), sort_keys=True)


def support_resistance_evidence_series(
    candle_times: Sequence[object],
    decision_times: Sequence[object],
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
    zone_width_atr: float = 0.15,
    zone_padding_atr: float = 0.10,
    max_cluster_span_atr: float = 0.50,
    min_rejection_atr: float = 0.50,
    near_distance_atr: float = 0.50,
    enable_hold_confirmation: bool = True,
    hold_confirmation_bars: int = 3,
    hold_confirmation_atr: float = 0.25,
    break_tolerance_atr: float = 0.25,
    break_basis: str = "CLOSE",
    include_zone_inventory: bool = False,
) -> list[dict[str, object]]:
    """Return CSL-compatible LONG/SHORT S/R context for each strategy candle.

    ``candle_times`` are strategy-candle open timestamps used for exact resampling.
    ``decision_times`` are the causal availability timestamps used to decide which
    completed higher-timeframe candle is visible at each strategy decision.
    """
    candles = pd.DatetimeIndex(pd.to_datetime(list(candle_times), utc=True))
    decisions = pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True))
    arrays = [
        np.asarray(values, dtype=float)
        for values in (opens, highs, lows, closes, atr_values)
    ]
    size = len(candles)
    if len(decisions) != size or any(len(values) != size for values in arrays):
        raise ValueError(
            "S/R candle times, decision times, OHLC and ATR inputs must have equal lengths"
        )
    if size and (not candles.is_monotonic_increasing or not decisions.is_monotonic_increasing):
        raise ValueError("S/R candle and decision timestamps must be chronological")
    if bool(np.any(decisions.asi8 < candles.asi8)):
        raise ValueError("S/R decision time cannot precede its strategy candle")
    strategy_minutes = _positive_integral(strategy_minutes, "strategy_minutes")
    atr_period = _positive_integral(atr_period, "atr_period")
    if sr_timeframe_minutes:
        effective_minutes = _positive_integral(
            sr_timeframe_minutes, "sr_timeframe_minutes"
        )
    else:
        effective_minutes = strategy_minutes
    if effective_minutes < strategy_minutes or effective_minutes % strategy_minutes:
        raise ValueError(
            "S/R timeframe must be the strategy timeframe or an integer multiple"
        )

    open_, high, low, close, atr_source = arrays
    config = dict(
        pivot_left=int(pivot_left),
        pivot_right=int(pivot_right),
        lookback_bars=int(lookback_bars),
        zone_width_atr=float(zone_width_atr),
        zone_padding_atr=float(zone_padding_atr),
        max_cluster_span_atr=float(max_cluster_span_atr),
        min_rejection_atr=float(min_rejection_atr),
        near_distance_atr=float(near_distance_atr),
        enable_hold_confirmation=bool(enable_hold_confirmation),
        hold_confirmation_bars=int(hold_confirmation_bars),
        hold_confirmation_atr=float(hold_confirmation_atr),
        break_tolerance_atr=float(break_tolerance_atr),
        break_basis=str(break_basis).upper(),
    )
    rows: list[dict[str, object]] = []

    if effective_minutes == strategy_minutes:
        detector = ResearchSupportResistanceDetector(**config)
        for index in range(size):
            long_context = detector.analyze_price_location(
                index, open_, high, low, close, atr_source, "LONG"
            )
            short_context = detector.analyze_price_location(
                index, open_, high, low, close, atr_source, "SHORT"
            )
            row: dict[str, object] = {
                "sr_completed_candle_time": decisions[index]
            }
            row.update(_flatten("long", long_context))
            row.update(_flatten("short", short_context))
            if include_zone_inventory:
                row["zone_inventory_json"] = _inventory_json(
                    _zone_inventory(
                        detector,
                        index=index,
                        high=high,
                        low=low,
                        current_price=float(close[index]),
                        current_atr=float(atr_source[index]),
                    )
                )
            rows.append(row)
        return rows

    strategy_frame = pd.DataFrame(
        {
            "timestamp": candles,
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
    htf_atr = np.asarray(
        shared_atr(htf_high, htf_low, htf_close, atr_period), dtype=float
    )
    htf_end = pd.DatetimeIndex(pd.to_datetime(htf["end_time"], utc=True))
    htf_end_ns = htf_end.asi8
    detector = ResearchHigherTimeframeSRDetector(**config)

    for index, decision_time in enumerate(decisions):
        htf_index = int(
            np.searchsorted(htf_end_ns, decision_time.value, side="right") - 1
        )
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
        if include_zone_inventory:
            inventory = (
                _zone_inventory(
                    detector,
                    index=htf_index,
                    high=htf_high,
                    low=htf_low,
                    current_price=float(close[index]),
                    current_atr=float(htf_atr[htf_index]),
                )
                if htf_index >= 0
                else []
            )
            row["zone_inventory_json"] = _inventory_json(inventory)
        rows.append(row)
    return rows