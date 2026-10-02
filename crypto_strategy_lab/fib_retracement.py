"""Causal Fibonacci retracement reaction signal and reusable rule evidence.

A swing is not usable until the right-side confirmation bars have closed. The
strategy therefore never selects historical pivots with hindsight. Once a
confirmed impulse exists, the first successful reaction at 0.382, 0.500, or
0.618 may produce a signal in the impulse direction. All retracement measurements
remain available as generic Entry/Veto evidence.
"""
from __future__ import annotations

import numpy as np


FIB_RETRACEMENT_MODE = "FIB_RETRACEMENT"
FIB_LEVELS = (0.236, 0.382, 0.500, 0.618, 0.786)
FIB_SIGNAL_LEVELS = frozenset({0.382, 0.500, 0.618})
FIB_RULE_INDICATORS = frozenset({
    "FIB_RETRACEMENT_DEPTH",
    "FIB_NEAREST_LEVEL",
    "FIB_LEVEL_DISTANCE_ATR",
    "FIB_REACTION_STATE",
    "FIB_REJECTION_ATR",
    "FIB_BARS_SINCE_TEST",
    "FIB_TEST_COUNT",
    "FIB_IMPULSE_ATR",
    "FIB_IMPULSE_BARS",
    "FIB_IMPULSE_DIRECTION",
})


def _confirmed_pivot(high, low, j: int, strength: int) -> tuple[bool, bool]:
    """Return whether j is a confirmed high/low using only closed neighbours."""
    if j < strength or j + strength >= len(high):
        return False, False
    h = float(high[j])
    l = float(low[j])
    left_h = high[j - strength:j]
    right_h = high[j + 1:j + strength + 1]
    left_l = low[j - strength:j]
    right_l = low[j + 1:j + strength + 1]
    is_high = bool(h > np.max(left_h) and h > np.max(right_h))
    is_low = bool(l < np.min(left_l) and l < np.min(right_l))
    return is_high, is_low


def fibonacci_retracement_arrays(
    open_prices,
    high_prices,
    low_prices,
    close_prices,
    atr_values,
    *,
    pivot_strength: int = 2,
    minimum_impulse_atr: float = 2.0,
    level_tolerance_atr: float = 0.25,
) -> dict[str, np.ndarray]:
    """Build causal Fibonacci impulse/retracement evidence arrays."""
    open_prices = np.asarray(open_prices, dtype=float)
    high_prices = np.asarray(high_prices, dtype=float)
    low_prices = np.asarray(low_prices, dtype=float)
    close_prices = np.asarray(close_prices, dtype=float)
    atr_values = np.asarray(atr_values, dtype=float)
    n = len(close_prices)

    depth = np.full(n, np.nan, dtype=float)
    nearest_level = np.full(n, np.nan, dtype=float)
    distance_atr = np.full(n, np.nan, dtype=float)
    reaction_state = np.full(n, "UNKNOWN", dtype=object)
    rejection_atr = np.full(n, np.nan, dtype=float)
    bars_since_test = np.full(n, np.nan, dtype=float)
    test_count = np.zeros(n, dtype=float)
    impulse_atr = np.full(n, np.nan, dtype=float)
    impulse_bars = np.full(n, np.nan, dtype=float)
    impulse_direction = np.full(n, "UNKNOWN", dtype=object)
    signal_direction = np.full(n, None, dtype=object)

    confirmed_highs: list[int] = []
    confirmed_lows: list[int] = []
    active_leg: tuple[str, int, int] | None = None
    active_tests = 0
    active_last_test: int | None = None
    signalled_leg: tuple[str, int, int] | None = None

    for i in range(n):
        # A pivot at j only becomes known after pivot_strength bars have closed.
        j = i - pivot_strength
        if j >= pivot_strength:
            is_high, is_low = _confirmed_pivot(high_prices, low_prices, j, pivot_strength)
            if is_high:
                confirmed_highs.append(j)
            if is_low:
                confirmed_lows.append(j)

        bull_leg = None
        bear_leg = None
        if confirmed_highs and confirmed_lows:
            hi = confirmed_highs[-1]
            prior_lows = [idx for idx in confirmed_lows if idx < hi]
            if prior_lows:
                lo = prior_lows[-1]
                bull_leg = ("LONG", lo, hi)

            lo = confirmed_lows[-1]
            prior_highs = [idx for idx in confirmed_highs if idx < lo]
            if prior_highs:
                hi = prior_highs[-1]
                bear_leg = ("SHORT", hi, lo)

        candidates = [leg for leg in (bull_leg, bear_leg) if leg is not None]
        if not candidates:
            continue
        # Most recently completed confirmed impulse wins.
        leg = max(candidates, key=lambda item: item[2])
        direction, start_i, end_i = leg
        if leg != active_leg:
            active_leg = leg
            active_tests = 0
            active_last_test = None

        start_price = float(low_prices[start_i] if direction == "LONG" else high_prices[start_i])
        end_price = float(high_prices[end_i] if direction == "LONG" else low_prices[end_i])
        span = abs(end_price - start_price)
        atr_now = float(atr_values[i]) if i < len(atr_values) else np.nan
        if not np.isfinite(span) or span <= 0 or not np.isfinite(atr_now) or atr_now <= 0:
            continue

        leg_atr = span / atr_now
        leg_bars = end_i - start_i
        impulse_atr[i] = leg_atr
        impulse_bars[i] = float(leg_bars)
        impulse_direction[i] = direction

        if i <= end_i:
            reaction_state[i] = "APPROACHING"
            continue

        if direction == "LONG":
            retracement = (end_price - float(close_prices[i])) / span
            levels_price = {level: end_price - level * span for level in FIB_LEVELS}
        else:
            retracement = (float(close_prices[i]) - end_price) / span
            levels_price = {level: end_price + level * span for level in FIB_LEVELS}
        depth[i] = retracement

        nearest = min(FIB_LEVELS, key=lambda level: abs(float(close_prices[i]) - levels_price[level]))
        nearest_level[i] = nearest
        level_price = levels_price[nearest]
        distance_atr[i] = abs(float(close_prices[i]) - level_price) / atr_now

        if retracement < FIB_LEVELS[0]:
            state = "APPROACHING"
        elif retracement > FIB_LEVELS[-1]:
            state = "BROKEN"
        elif distance_atr[i] <= level_tolerance_atr:
            state = "TESTING"
        else:
            state = "BETWEEN_LEVELS"

        touched = (
            float(low_prices[i]) <= level_price <= float(high_prices[i])
        )
        held = False
        if touched:
            active_tests += 1
            active_last_test = i
            if direction == "LONG":
                held = float(close_prices[i]) > level_price and float(close_prices[i]) > float(open_prices[i])
                rejection_atr[i] = max(0.0, float(close_prices[i]) - float(low_prices[i])) / atr_now
            else:
                held = float(close_prices[i]) < level_price and float(close_prices[i]) < float(open_prices[i])
                rejection_atr[i] = max(0.0, float(high_prices[i]) - float(close_prices[i])) / atr_now
        if held:
            state = "HELD"

        reaction_state[i] = state
        test_count[i] = float(active_tests)
        if active_last_test is not None:
            bars_since_test[i] = float(i - active_last_test)

        if (
            state == "HELD"
            and nearest in FIB_SIGNAL_LEVELS
            and leg_atr >= minimum_impulse_atr
            and signalled_leg != leg
        ):
            signal_direction[i] = direction
            signalled_leg = leg

    return {
        "FIB_RETRACEMENT_DEPTH": depth,
        "FIB_NEAREST_LEVEL": nearest_level,
        "FIB_LEVEL_DISTANCE_ATR": distance_atr,
        "FIB_REACTION_STATE": reaction_state,
        "FIB_REJECTION_ATR": rejection_atr,
        "FIB_BARS_SINCE_TEST": bars_since_test,
        "FIB_TEST_COUNT": test_count,
        "FIB_IMPULSE_ATR": impulse_atr,
        "FIB_IMPULSE_BARS": impulse_bars,
        "FIB_IMPULSE_DIRECTION": impulse_direction,
        "_FIB_SIGNAL_DIRECTION": signal_direction,
    }


class FibonacciRetracementMixin:
    """Add causal Fib reaction direction selection and generic rule evidence."""

    fib_pivot_strength = 2
    fib_minimum_impulse_atr = 2.0
    fib_level_tolerance_atr = 0.25

    def _fib_features_needed(self) -> bool:
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                if str(rule.get("_strategy_direction_mode", "")).upper() == FIB_RETRACEMENT_MODE:
                    return True
                if str(rule.get("indicator", "")).upper() in FIB_RULE_INDICATORS:
                    return True
        return False

    def _configure_signal_features(self):
        super()._configure_signal_features()
        self.fib_retracement = {}
        if not self._fib_features_needed():
            return
        self.fib_retracement = fibonacci_retracement_arrays(
            self.open,
            self.high,
            self.low,
            self.close,
            self.atr_values,
            pivot_strength=int(self.fib_pivot_strength),
            minimum_impulse_atr=float(self.fib_minimum_impulse_atr),
            level_tolerance_atr=float(self.fib_level_tolerance_atr),
        )

    def _infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                mode = str(rule.get("_strategy_direction_mode", "")).upper()
                if mode == FIB_RETRACEMENT_MODE:
                    return FIB_RETRACEMENT_MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == FIB_RETRACEMENT_MODE:
            values = getattr(self, "fib_retracement", {}).get("_FIB_SIGNAL_DIRECTION")
            if values is None or i < 0 or i >= len(values):
                return None
            value = values[i]
            return value if value in {"LONG", "SHORT"} else None
        return super()._selected_direction(i)

    def _fib_rule_value(self, i: int, direction: str, indicator: str):
        values = getattr(self, "fib_retracement", {}).get(indicator)
        if values is None or i < 0 or i >= len(values):
            return np.nan
        raw = values[i]
        if indicator == "FIB_REACTION_STATE":
            codes = {
                "UNKNOWN": 0.0,
                "APPROACHING": 1.0,
                "TESTING": 2.0,
                "HELD": 3.0,
                "BETWEEN_LEVELS": 4.0,
                "BROKEN": 5.0,
            }
            return codes.get(str(raw).upper(), np.nan)
        if indicator == "FIB_IMPULSE_DIRECTION":
            codes = {"LONG": 1.0, "SHORT": 2.0}
            return codes.get(str(raw).upper(), np.nan)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return np.nan
        return value if np.isfinite(value) else np.nan
