"""Trade-relative support/resistance semantics shared by rules and walk-forward.

Raw S/R geometry remains timeframe-native. This module translates it into
trade-facing evidence without labeling a setup "good" or "bad".

The calculation is deliberately causal:
- structure comes from already-prepared completed-candle S/R context;
- strategy ATR is known at the decision candle;
- stop/target distance uses the configured profile contract and the current
  risk-distance unit, never a future fill price.
"""
from __future__ import annotations

from typing import Any, Mapping

import math


SR_TRADE_CATEGORICAL_INDICATORS = frozenset(
    {
        "SR_ENTRY_RELATION",
        "SR_FAVORABLE_STRUCTURE_STATE",
        "SR_OPPOSING_STRUCTURE_STATE",
        "SR_FAVORABLE_HELD",
        "SR_OPPOSING_HELD",
        "SR_TARGET_PATH",
    }
)

SR_TRADE_NUMERIC_INDICATORS = frozenset(
    {
        "SR_FAVORABLE_DISTANCE_NATIVE_ATR",
        "SR_OPPOSING_DISTANCE_NATIVE_ATR",
        "SR_FAVORABLE_DISTANCE_STRATEGY_ATR",
        "SR_OPPOSING_DISTANCE_STRATEGY_ATR",
        "SR_OPPOSING_ROOM_R",
        "SR_OPPOSING_ROOM_TARGET_MULTIPLE",
        "SR_FAVORABLE_REJECTION_NATIVE_ATR",
        "SR_OPPOSING_REJECTION_NATIVE_ATR",
        "SR_FAVORABLE_TEST_COUNT",
        "SR_OPPOSING_TEST_COUNT",
        "SR_BARS_SINCE_FAVORABLE_TEST",
        "SR_BARS_SINCE_OPPOSING_TEST",
    }
)

SR_TRADE_RULE_INDICATORS = frozenset(
    (*SR_TRADE_CATEGORICAL_INDICATORS, *SR_TRADE_NUMERIC_INDICATORS)
)

ENTRY_RELATION_VALUES = (
    "INSIDE_FAVORABLE_ZONE",
    "NEAR_FAVORABLE_STRUCTURE",
    "BETWEEN_STRUCTURES",
    "NEAR_OPPOSING_STRUCTURE",
    "INSIDE_OPPOSING_ZONE",
    "SQUEEZED_BETWEEN_STRUCTURES",
    "FAVORABLE_STRUCTURE_ONLY",
    "OPPOSING_STRUCTURE_ONLY",
    "NO_STRUCTURE",
)

GENERIC_STRUCTURE_STATE_VALUES = (
    "NO_STRUCTURE",
    "APPROACHING",
    "TESTING",
    "HELD",
    "BROKEN",
)

TARGET_PATH_VALUES = (
    "TARGET_BEFORE_OPPOSING_ZONE",
    "TARGET_INSIDE_OPPOSING_ZONE",
    "OPPOSING_ZONE_BEFORE_TARGET",
    "ALREADY_AT_OPPOSING_STRUCTURE",
    "NO_OPPOSING_STRUCTURE",
)

RAW_SR_FIELDS = (
    "nearest_support_price",
    "nearest_support_distance_atr",
    "nearest_support_distance_price",
    "nearest_resistance_price",
    "nearest_resistance_distance_atr",
    "nearest_resistance_distance_price",
    "near_support",
    "near_resistance",
    "inside_support_zone",
    "inside_resistance_zone",
    "support_state",
    "resistance_state",
    "support_held",
    "resistance_held",
    "support_rejection_atr",
    "resistance_rejection_atr",
    "support_test_count",
    "resistance_test_count",
    "bars_since_support_test",
    "bars_since_resistance_test",
    "support_zone_low",
    "support_zone_high",
    "resistance_zone_low",
    "resistance_zone_high",
)


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() in {"TRUE", "1", "YES", "ON"}
    return bool(value)


def _generic_state(raw: Any) -> str:
    text = str(getattr(raw, "value", raw) or "").upper()
    if text.startswith("NO_"):
        return "NO_STRUCTURE"
    if "APPROACHING" in text:
        return "APPROACHING"
    if "TESTING" in text:
        return "TESTING"
    if "HELD" in text:
        return "HELD"
    if "BROKEN" in text:
        return "BROKEN"
    return "NO_STRUCTURE"


def planned_trade_distances(profile: Any, risk_unit: Any) -> tuple[float | None, float | None]:
    """Return the configured 1R stop distance and final planned target distance."""
    unit = _finite(risk_unit)
    if unit is None or unit <= 0 or profile is None:
        return None, None

    partial_stop = bool(getattr(profile, "partial_stop_enabled", False))
    stop_multiple = (
        _finite(getattr(profile, "sl2_r", None))
        if partial_stop
        else _finite(getattr(profile, "stop_loss_multiple", None))
    )
    if stop_multiple is None or stop_multiple <= 0:
        return None, None
    stop_distance = unit * stop_multiple

    if bool(getattr(profile, "r_step_trailing_enabled", False)):
        maximum_r = _finite(getattr(profile, "r_step_maximum_r", None))
        if maximum_r is not None and maximum_r > 0:
            return stop_distance, unit * maximum_r

    if bool(getattr(profile, "partial_profit_enabled", False)):
        tp2_r = _finite(getattr(profile, "tp2_r", None))
        if tp2_r is None or tp2_r <= 0:
            return stop_distance, None
        return stop_distance, stop_distance * tp2_r

    reward_risk = _finite(getattr(profile, "reward_risk_ratio", None))
    if reward_risk is None or reward_risk <= 0:
        return stop_distance, None
    return stop_distance, stop_distance * reward_risk


def _side_fields(direction: str) -> tuple[str, str]:
    side = str(direction).upper()
    if side == "LONG":
        return "support", "resistance"
    if side == "SHORT":
        return "resistance", "support"
    raise ValueError("direction must be LONG or SHORT")


def _field(raw: Mapping[str, Any], structure: str, suffix: str) -> Any:
    return raw.get(f"{structure}_{suffix}")


def _inside(raw: Mapping[str, Any], structure: str) -> bool:
    return _boolean(raw.get(f"inside_{structure}_zone"))


def _structure_exists(raw: Mapping[str, Any], structure: str) -> bool:
    low = _finite(_field(raw, structure, "zone_low"))
    high = _finite(_field(raw, structure, "zone_high"))
    price = _finite(raw.get(f"nearest_{structure}_price"))
    return (low is not None and high is not None) or price is not None


def _entry_relation(raw: Mapping[str, Any], favorable: str, opposing: str) -> str:
    favorable_inside = _inside(raw, favorable)
    opposing_inside = _inside(raw, opposing)
    favorable_near = _boolean(raw.get(f"near_{favorable}"))
    opposing_near = _boolean(raw.get(f"near_{opposing}"))
    favorable_exists = _structure_exists(raw, favorable)
    opposing_exists = _structure_exists(raw, opposing)

    if (favorable_inside and opposing_inside) or (favorable_near and opposing_near):
        return "SQUEEZED_BETWEEN_STRUCTURES"
    if favorable_inside:
        return "INSIDE_FAVORABLE_ZONE"
    if opposing_inside:
        return "INSIDE_OPPOSING_ZONE"
    if favorable_near:
        return "NEAR_FAVORABLE_STRUCTURE"
    if opposing_near:
        return "NEAR_OPPOSING_STRUCTURE"
    if favorable_exists and opposing_exists:
        return "BETWEEN_STRUCTURES"
    if favorable_exists:
        return "FAVORABLE_STRUCTURE_ONLY"
    if opposing_exists:
        return "OPPOSING_STRUCTURE_ONLY"
    return "NO_STRUCTURE"


def _target_path(
    direction: str,
    raw: Mapping[str, Any],
    opposing: str,
    reference_price: Any,
    target_distance: Any,
) -> str:
    low = _finite(_field(raw, opposing, "zone_low"))
    high = _finite(_field(raw, opposing, "zone_high"))
    price = _finite(reference_price)
    target = _finite(target_distance)
    if low is None or high is None:
        return "NO_OPPOSING_STRUCTURE"
    if _inside(raw, opposing):
        return "ALREADY_AT_OPPOSING_STRUCTURE"
    if price is None or target is None or target <= 0:
        return "NO_OPPOSING_STRUCTURE"

    target_price = price + target if str(direction).upper() == "LONG" else price - target
    if str(direction).upper() == "LONG":
        if target_price < low:
            return "TARGET_BEFORE_OPPOSING_ZONE"
        if target_price <= high:
            return "TARGET_INSIDE_OPPOSING_ZONE"
        return "OPPOSING_ZONE_BEFORE_TARGET"

    if target_price > high:
        return "TARGET_BEFORE_OPPOSING_ZONE"
    if target_price >= low:
        return "TARGET_INSIDE_OPPOSING_ZONE"
    return "OPPOSING_ZONE_BEFORE_TARGET"


def derive_trade_sr_context(
    *,
    direction: str,
    raw: Mapping[str, Any],
    strategy_atr: Any,
    reference_price: Any,
    stop_distance: Any,
    target_distance: Any,
) -> dict[str, Any]:
    """Translate one timeframe-native S/R snapshot into trade-relative evidence."""
    favorable, opposing = _side_fields(direction)

    favorable_native = _finite(raw.get(f"nearest_{favorable}_distance_atr"))
    opposing_native = _finite(raw.get(f"nearest_{opposing}_distance_atr"))
    favorable_price = _finite(raw.get(f"nearest_{favorable}_distance_price"))
    opposing_price = _finite(raw.get(f"nearest_{opposing}_distance_price"))
    strategy_atr_value = _finite(strategy_atr)
    stop = _finite(stop_distance)
    target = _finite(target_distance)

    favorable_strategy = (
        favorable_price / strategy_atr_value
        if favorable_price is not None
        and strategy_atr_value is not None
        and strategy_atr_value > 0
        else None
    )
    opposing_strategy = (
        opposing_price / strategy_atr_value
        if opposing_price is not None
        and strategy_atr_value is not None
        and strategy_atr_value > 0
        else None
    )
    room_r = (
        opposing_price / stop
        if opposing_price is not None and stop is not None and stop > 0
        else None
    )
    room_target = (
        opposing_price / target
        if opposing_price is not None and target is not None and target > 0
        else None
    )

    return {
        "SR_ENTRY_RELATION": _entry_relation(raw, favorable, opposing),
        "SR_FAVORABLE_STRUCTURE_STATE": _generic_state(
            _field(raw, favorable, "state")
        ),
        "SR_OPPOSING_STRUCTURE_STATE": _generic_state(
            _field(raw, opposing, "state")
        ),
        "SR_FAVORABLE_HELD": "TRUE" if _boolean(_field(raw, favorable, "held")) else "FALSE",
        "SR_OPPOSING_HELD": "TRUE" if _boolean(_field(raw, opposing, "held")) else "FALSE",
        "SR_TARGET_PATH": _target_path(
            direction, raw, opposing, reference_price, target_distance
        ),
        "SR_FAVORABLE_DISTANCE_NATIVE_ATR": favorable_native,
        "SR_OPPOSING_DISTANCE_NATIVE_ATR": opposing_native,
        "SR_FAVORABLE_DISTANCE_STRATEGY_ATR": favorable_strategy,
        "SR_OPPOSING_DISTANCE_STRATEGY_ATR": opposing_strategy,
        "SR_OPPOSING_ROOM_R": room_r,
        "SR_OPPOSING_ROOM_TARGET_MULTIPLE": room_target,
        "SR_FAVORABLE_REJECTION_NATIVE_ATR": _finite(
            _field(raw, favorable, "rejection_atr")
        ),
        "SR_OPPOSING_REJECTION_NATIVE_ATR": _finite(
            _field(raw, opposing, "rejection_atr")
        ),
        "SR_FAVORABLE_TEST_COUNT": _finite(_field(raw, favorable, "test_count")),
        "SR_OPPOSING_TEST_COUNT": _finite(_field(raw, opposing, "test_count")),
        "SR_BARS_SINCE_FAVORABLE_TEST": _finite(
            raw.get(f"bars_since_{favorable}_test")
        ),
        "SR_BARS_SINCE_OPPOSING_TEST": _finite(
            raw.get(f"bars_since_{opposing}_test")
        ),
    }
