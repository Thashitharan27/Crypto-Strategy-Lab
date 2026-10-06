"""Causal Fibonacci retracement reaction signal and reusable rule evidence.

A swing is not usable until the right-side confirmation bars have closed. The
strategy therefore never selects historical pivots with hindsight. Confirmed
pivot legs are ranked as structural candidates over a bounded recent window;
the active Fib remains on the dominant swing until a materially stronger swing
is confirmed, the old swing ages out, or a deep retracement resets the structure.
While an active swing remains valid, a newly confirmed higher high / lower low
extends that same leg from its original anchor even when the anchor is older than
the discovery lookback. A close retracement to 0.618 or deeper ends that extension
privilege so a completed cycle cannot keep dragging an old anchor forward. Once a
confirmed impulse exists, the first successful reaction at 0.382, 0.500, or
0.618 may produce a signal in the impulse direction. All retracement measurements
remain available as generic Entry/Veto evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


FIB_RETRACEMENT_MODE = "FIB_RETRACEMENT"
FIB_RESEARCH_CONTEXT_NAME = "fibonacci_retracement"
FIB_RESEARCH_CONTEXT_VERSION = 5
FIB_PIVOT_STRENGTH = 2
FIB_MINIMUM_IMPULSE_ATR = 2.0
FIB_LEVEL_TOLERANCE_ATR = 0.25
FIB_DOMINANT_LOOKBACK_BARS = 160
FIB_DOMINANT_RECENCY_PENALTY = 0.35
FIB_DOMINANT_REPLACEMENT_RATIO = 1.10
FIB_ACTIVE_STRUCTURE_RESET_DEPTH = 0.618
FIB_LEVELS = (0.236, 0.382, 0.500, 0.618, 0.786)
FIB_SIGNAL_LEVELS = frozenset({0.382, 0.500, 0.618})
FIB_RULE_INDICATORS = frozenset({
    "FIB_RETRACEMENT_DEPTH",
    "FIB_NEAREST_LEVEL",
    "FIB_LEVEL_DISTANCE_ATR",
    "FIB_EMA_50_DISTANCE_ATR",
    "FIB_EMA_100_DISTANCE_ATR",
    "FIB_EMA_200_DISTANCE_ATR",
    "FIB_REACTION_STATE",
    "FIB_REJECTION_ATR",
    "FIB_BARS_SINCE_TEST",
    "FIB_TEST_COUNT",
    "FIB_IMPULSE_ATR",
    "FIB_IMPULSE_BARS",
    "FIB_IMPULSE_DIRECTION",
})



def fib_features_needed(profiles) -> bool:
    """Return whether any strategy profile needs Fib signal or rule evidence."""
    for profile in profiles.values():
        for rule in getattr(profile, "entry_rules", ()):
            if str(rule.get("_strategy_direction_mode", "")).upper() == FIB_RETRACEMENT_MODE:
                return True
            if str(rule.get("indicator", "")).upper() in FIB_RULE_INDICATORS:
                return True
    return False


def _causal_ema(values, period: int) -> np.ndarray:
    """Match the engine's causal EMA convention for Fib/EMA confluence."""
    return (
        pd.Series(np.asarray(values, dtype=float))
        .ewm(span=period, adjust=False, min_periods=period)
        .mean()
        .to_numpy(float)
    )


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
    ema_50_values=None,
    ema_100_values=None,
    ema_200_values=None,
    dominant_lookback_bars: int = FIB_DOMINANT_LOOKBACK_BARS,
    dominant_recency_penalty: float = FIB_DOMINANT_RECENCY_PENALTY,
    dominant_replacement_ratio: float = FIB_DOMINANT_REPLACEMENT_RATIO,
    active_structure_reset_depth: float = FIB_ACTIVE_STRUCTURE_RESET_DEPTH,
) -> dict[str, np.ndarray]:
    """Build causal Fibonacci impulse/retracement evidence arrays."""
    open_prices = np.asarray(open_prices, dtype=float)
    high_prices = np.asarray(high_prices, dtype=float)
    low_prices = np.asarray(low_prices, dtype=float)
    close_prices = np.asarray(close_prices, dtype=float)
    atr_values = np.asarray(atr_values, dtype=float)
    ema_50_values = _causal_ema(close_prices, 50) if ema_50_values is None else np.asarray(ema_50_values, dtype=float)
    ema_100_values = _causal_ema(close_prices, 100) if ema_100_values is None else np.asarray(ema_100_values, dtype=float)
    ema_200_values = _causal_ema(close_prices, 200) if ema_200_values is None else np.asarray(ema_200_values, dtype=float)
    n = len(close_prices)
    if any(len(values) != n for values in (ema_50_values, ema_100_values, ema_200_values)):
        raise ValueError("Fib EMA arrays must match price length")

    depth = np.full(n, np.nan, dtype=float)
    nearest_level = np.full(n, np.nan, dtype=float)
    distance_atr = np.full(n, np.nan, dtype=float)
    fib_ema_50_distance_atr = np.full(n, np.nan, dtype=float)
    fib_ema_100_distance_atr = np.full(n, np.nan, dtype=float)
    fib_ema_200_distance_atr = np.full(n, np.nan, dtype=float)
    reaction_state = np.full(n, "UNKNOWN", dtype=object)
    rejection_atr = np.full(n, np.nan, dtype=float)
    bars_since_test = np.full(n, np.nan, dtype=float)
    test_count = np.zeros(n, dtype=float)
    impulse_atr = np.full(n, np.nan, dtype=float)
    impulse_bars = np.full(n, np.nan, dtype=float)
    impulse_direction = np.full(n, "UNKNOWN", dtype=object)
    signal_direction = np.full(n, None, dtype=object)
    impulse_start_price = np.full(n, np.nan, dtype=float)
    impulse_end_price = np.full(n, np.nan, dtype=float)
    impulse_start_index = np.full(n, np.nan, dtype=float)
    impulse_end_index = np.full(n, np.nan, dtype=float)
    active_level_price = np.full(n, np.nan, dtype=float)

    confirmed_highs: list[int] = []
    confirmed_lows: list[int] = []
    # Candidate tuple: (direction, start_index, end_index, structural_strength_atr).
    # Candidates are created only when the ending pivot is confirmed, so the
    # selector remains causal.  The active leg is sticky: a newer local wiggle
    # cannot replace a meaningful swing unless it is materially stronger, the
    # active swing ages out, or the active retracement has broken.
    structural_candidates: list[tuple[str, int, int, float]] = []
    active_leg: tuple[str, int, int] | None = None
    active_extension_leg: tuple[str, int, int] | None = None
    active_tests = 0
    active_last_test: int | None = None
    active_broken = False
    active_structure_reset = False
    signalled_leg: tuple[str, int, int] | None = None

    dominant_lookback_bars = max(16, int(dominant_lookback_bars))
    dominant_recency_penalty = min(0.95, max(0.0, float(dominant_recency_penalty)))
    dominant_replacement_ratio = max(1.0, float(dominant_replacement_ratio))
    active_structure_reset_depth = min(0.786, max(0.236, float(active_structure_reset_depth)))

    def _candidate_live_score(candidate, now):
        age = max(0, now - candidate[2])
        age_fraction = min(1.0, age / float(dominant_lookback_bars))
        return candidate[3] * (1.0 - dominant_recency_penalty * age_fraction)

    for i in range(n):
        # Once an active leg has retraced deeply enough, treat that move as a
        # completed structural cycle. From that bar onward the old anchor may
        # no longer extend to future extremes and no longer receives sticky
        # replacement protection. This is latched until a new leg is selected.
        if active_leg is not None and i > active_leg[2] and not active_structure_reset:
            active_direction, active_start_i, active_end_i = active_leg
            active_start_price = float(
                low_prices[active_start_i]
                if active_direction == "LONG"
                else high_prices[active_start_i]
            )
            active_end_price = float(
                high_prices[active_end_i]
                if active_direction == "LONG"
                else low_prices[active_end_i]
            )
            active_span = abs(active_end_price - active_start_price)
            if np.isfinite(active_span) and active_span > 0:
                active_retracement = (
                    (active_end_price - float(close_prices[i])) / active_span
                    if active_direction == "LONG"
                    else (float(close_prices[i]) - active_end_price) / active_span
                )
                if active_retracement >= active_structure_reset_depth:
                    active_structure_reset = True

        # A pivot at j only becomes known after pivot_strength bars have closed.
        # The bounded lookback governs discovery of new structural swings, but
        # an already-active, unbroken swing may extend to a newly confirmed
        # higher high / lower low while preserving its original anchor.
        active_extension_leg = None
        j = i - pivot_strength
        if j >= pivot_strength:
            is_high, is_low = _confirmed_pivot(high_prices, low_prices, j, pivot_strength)
            if is_high:
                confirmed_highs.append(j)
                if (
                    active_leg is not None
                    and active_leg[0] == "LONG"
                    and not active_broken
                    and not active_structure_reset
                    and j > active_leg[2]
                    and float(high_prices[j]) > float(high_prices[active_leg[2]])
                ):
                    anchor = active_leg[1]
                    span = float(high_prices[j]) - float(low_prices[anchor])
                    atr_confirm = float(atr_values[i]) if i < len(atr_values) else np.nan
                    if np.isfinite(span) and span > 0 and np.isfinite(atr_confirm) and atr_confirm > 0:
                        extension = ("LONG", anchor, j, span / atr_confirm)
                        structural_candidates.append(extension)
                        active_extension_leg = extension[:3]
                floor = j - dominant_lookback_bars
                prior_lows = [idx for idx in confirmed_lows if floor <= idx < j]
                if prior_lows:
                    lo = min(prior_lows, key=lambda idx: float(low_prices[idx]))
                    span = float(high_prices[j]) - float(low_prices[lo])
                    atr_confirm = float(atr_values[i]) if i < len(atr_values) else np.nan
                    if np.isfinite(span) and span > 0 and np.isfinite(atr_confirm) and atr_confirm > 0:
                        structural_candidates.append(("LONG", lo, j, span / atr_confirm))
            if is_low:
                confirmed_lows.append(j)
                if (
                    active_leg is not None
                    and active_leg[0] == "SHORT"
                    and not active_broken
                    and not active_structure_reset
                    and j > active_leg[2]
                    and float(low_prices[j]) < float(low_prices[active_leg[2]])
                ):
                    anchor = active_leg[1]
                    span = float(high_prices[anchor]) - float(low_prices[j])
                    atr_confirm = float(atr_values[i]) if i < len(atr_values) else np.nan
                    if np.isfinite(span) and span > 0 and np.isfinite(atr_confirm) and atr_confirm > 0:
                        extension = ("SHORT", anchor, j, span / atr_confirm)
                        structural_candidates.append(extension)
                        active_extension_leg = extension[:3]
                floor = j - dominant_lookback_bars
                prior_highs = [idx for idx in confirmed_highs if floor <= idx < j]
                if prior_highs:
                    hi = max(prior_highs, key=lambda idx: float(high_prices[idx]))
                    span = float(high_prices[hi]) - float(low_prices[j])
                    atr_confirm = float(atr_values[i]) if i < len(atr_values) else np.nan
                    if np.isfinite(span) and span > 0 and np.isfinite(atr_confirm) and atr_confirm > 0:
                        structural_candidates.append(("SHORT", hi, j, span / atr_confirm))

            pivot_cutoff = j - dominant_lookback_bars
            confirmed_highs = [idx for idx in confirmed_highs if idx >= pivot_cutoff]
            confirmed_lows = [idx for idx in confirmed_lows if idx >= pivot_cutoff]

        cutoff = i - dominant_lookback_bars
        structural_candidates = [
            candidate for candidate in structural_candidates
            if candidate[2] >= cutoff
        ]
        if not structural_candidates:
            continue

        best = max(
            structural_candidates,
            key=lambda candidate: (
                _candidate_live_score(candidate, i),
                candidate[2],
            ),
        )
        best_leg = best[:3]
        # Extending the same unbroken structural leg is not a competing swing,
        # so it should not be blocked by the 1.10 replacement threshold.
        leg = active_extension_leg or best_leg
        if (
            active_extension_leg is None
            and active_leg is not None
            and active_leg != best_leg
            and not active_structure_reset
        ):
            active_candidate = next(
                (
                    candidate for candidate in structural_candidates
                    if candidate[:3] == active_leg
                ),
                None,
            )
            if active_candidate is not None and not active_broken:
                active_score = _candidate_live_score(active_candidate, i)
                best_score = _candidate_live_score(best, i)
                if best_score < active_score * dominant_replacement_ratio:
                    leg = active_leg

        direction, start_i, end_i = leg
        if leg != active_leg:
            active_leg = leg
            active_tests = 0
            active_last_test = None
            active_broken = False
            active_structure_reset = False

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
        impulse_start_price[i] = start_price
        impulse_end_price[i] = end_price
        impulse_start_index[i] = float(start_i)
        impulse_end_index[i] = float(end_i)

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
        active_level_price[i] = level_price
        distance_atr[i] = abs(float(close_prices[i]) - level_price) / atr_now
        for ema_values, output in (
            (ema_50_values, fib_ema_50_distance_atr),
            (ema_100_values, fib_ema_100_distance_atr),
            (ema_200_values, fib_ema_200_distance_atr),
        ):
            ema_value = float(ema_values[i])
            if np.isfinite(ema_value):
                output[i] = abs(level_price - ema_value) / atr_now

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
        active_broken = state == "BROKEN"
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
        "FIB_EMA_50_DISTANCE_ATR": fib_ema_50_distance_atr,
        "FIB_EMA_100_DISTANCE_ATR": fib_ema_100_distance_atr,
        "FIB_EMA_200_DISTANCE_ATR": fib_ema_200_distance_atr,
        "FIB_REACTION_STATE": reaction_state,
        "FIB_REJECTION_ATR": rejection_atr,
        "FIB_BARS_SINCE_TEST": bars_since_test,
        "FIB_TEST_COUNT": test_count,
        "FIB_IMPULSE_ATR": impulse_atr,
        "FIB_IMPULSE_BARS": impulse_bars,
        "FIB_IMPULSE_DIRECTION": impulse_direction,
        "_FIB_SIGNAL_DIRECTION": signal_direction,
        "_FIB_IMPULSE_START_PRICE": impulse_start_price,
        "_FIB_IMPULSE_END_PRICE": impulse_end_price,
        "_FIB_IMPULSE_START_INDEX": impulse_start_index,
        "_FIB_IMPULSE_END_INDEX": impulse_end_index,
        "_FIB_ACTIVE_LEVEL_PRICE": active_level_price,
    }


class FibonacciRetracementMixin:
    """Add causal Fib reaction direction selection and generic rule evidence."""

    fib_pivot_strength = FIB_PIVOT_STRENGTH
    fib_minimum_impulse_atr = FIB_MINIMUM_IMPULSE_ATR
    fib_level_tolerance_atr = FIB_LEVEL_TOLERANCE_ATR
    fib_dominant_lookback_bars = FIB_DOMINANT_LOOKBACK_BARS
    fib_dominant_recency_penalty = FIB_DOMINANT_RECENCY_PENALTY
    fib_dominant_replacement_ratio = FIB_DOMINANT_REPLACEMENT_RATIO
    fib_active_structure_reset_depth = FIB_ACTIVE_STRUCTURE_RESET_DEPTH

    def _fib_features_needed(self) -> bool:
        return fib_features_needed(self.config.strategy_profiles)

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
            ema_50_values=getattr(self, "ema_50_values", None),
            ema_100_values=getattr(self, "ema_100_values", None),
            ema_200_values=getattr(self, "ema_200_values", None),
            dominant_lookback_bars=int(self.fib_dominant_lookback_bars),
            dominant_recency_penalty=float(self.fib_dominant_recency_penalty),
            dominant_replacement_ratio=float(self.fib_dominant_replacement_ratio),
            active_structure_reset_depth=float(self.fib_active_structure_reset_depth),
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


    def _fib_native_plan_values(self, i: int, direction: str):
        values = getattr(self, "fib_retracement", {})
        try:
            nearest = float(values["FIB_NEAREST_LEVEL"][i])
            start = float(values["_FIB_IMPULSE_START_PRICE"][i])
            end = float(values["_FIB_IMPULSE_END_PRICE"][i])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if (
            direction not in {"LONG", "SHORT"}
            or not np.isfinite(nearest)
            or not np.isfinite(start)
            or not np.isfinite(end)
        ):
            return None
        span = abs(end - start)
        if span <= 0:
            return None
        deeper = {
            0.382: 0.500,
            0.500: 0.618,
            0.618: 0.786,
        }.get(round(nearest, 3))
        if deeper is None:
            return None
        stop_boundary = (
            end - deeper * span
            if direction == "LONG"
            else end + deeper * span
        )
        return {
            "nearest_level": nearest,
            "stop_level": deeper,
            "stop_boundary": stop_boundary,
            "target_boundary": end,
            "impulse_start": start,
            "impulse_end": end,
            "impulse_span": span,
        }

    def _sr_stop_plan(self, i: int, execution_i: int | None = None):
        if getattr(self, "signal_strategy_mode", "DI") != FIB_RETRACEMENT_MODE:
            return super()._sr_stop_plan(i, execution_i)
        direction = self._effective_trade_direction(i)
        plan = self._fib_native_plan_values(i, direction)
        atr = float(self.atr_values[i]) if 0 <= i < len(self.atr_values) else np.nan
        if plan is None or not np.isfinite(atr) or atr <= 0:
            return {
                "passed": False,
                "applied": False,
                "reason": "FIB_STOP_UNAVAILABLE",
                "distance": None,
            }
        buffer_price = float(getattr(self.config, "fib_stop_buffer_atr", 0.05)) * atr
        boundary = float(plan["stop_boundary"])
        stop = boundary - buffer_price if direction == "LONG" else boundary + buffer_price
        if execution_i is not None and execution_i > i:
            opening = float(self.open[execution_i])
            gap_through = opening <= stop if direction == "LONG" else opening >= stop
            if gap_through:
                return {
                    "passed": False,
                    "applied": False,
                    "reason": "FIB_ENTRY_GAPPED_THROUGH_STOP",
                    "distance": None,
                }
        entry = float(self._expected_entry_price(i, execution_i, direction))
        distance = entry - stop if direction == "LONG" else stop - entry
        if not np.isfinite(distance) or distance <= 0:
            return {
                "passed": False,
                "applied": False,
                "reason": "FIB_STOP_ON_WRONG_SIDE",
                "distance": None,
            }
        return {
            "passed": True,
            "applied": True,
            "reason": "FIB_NEXT_LEVEL_STOP",
            "distance": distance,
            "distance_atr": distance / atr,
            "level_price": boundary,
            "boundary_price": boundary,
            "stop_price": stop,
            "fib_entry_level": float(plan["nearest_level"]),
            "fib_stop_level": float(plan["stop_level"]),
            "fib_impulse_start_price": float(plan["impulse_start"]),
            "fib_impulse_end_price": float(plan["impulse_end"]),
            "fib_impulse_span": float(plan["impulse_span"]),
            "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
        }

    def _fib_target_plan(self, i: int, execution_i: int | None = None):
        direction = self._effective_trade_direction(i)
        plan = self._fib_native_plan_values(i, direction)
        stop_plan = self._sr_stop_plan(i, execution_i)
        atr = float(self.atr_values[i]) if 0 <= i < len(self.atr_values) else np.nan
        if (
            plan is None
            or direction not in {"LONG", "SHORT"}
            or not stop_plan.get("applied")
            or not np.isfinite(atr)
            or atr <= 0
        ):
            return {"passed": False, "reason": "FIB_TARGET_UNAVAILABLE"}
        buffer_price = float(getattr(self.config, "fib_target_buffer_atr", 0.05)) * atr
        boundary = float(plan["target_boundary"])
        room_target = boundary - buffer_price if direction == "LONG" else boundary + buffer_price
        entry = float(self._expected_entry_price(i, execution_i, direction))
        room = room_target - entry if direction == "LONG" else entry - room_target
        risk = float(stop_plan["distance"])
        available_r = room / risk if risk > 0 else np.nan
        if not np.isfinite(room) or room <= 0:
            return {
                "passed": False,
                "reason": "FIB_TARGET_ON_WRONG_SIDE",
                "level_price": boundary,
                "limit_price": room_target,
                "available_r": available_r,
            }
        minimum_r = float(getattr(self.config, "fib_minimum_target_r", 2.0))
        if not np.isfinite(available_r) or available_r + 1e-12 < minimum_r:
            return {
                "passed": False,
                "reason": "FIB_TARGET_INSUFFICIENT_ROOM",
                "level_price": boundary,
                "limit_price": room_target,
                "available_r": available_r,
                "minimum_r": minimum_r,
            }

        target_mode = str(getattr(self.config, "fib_target_mode", "IMPULSE_EXTREME")).upper()
        if target_mode == "FIXED_R":
            target_r = float(getattr(self.config, "fib_fixed_target_r", 2.0))
            target = entry + target_r * risk if direction == "LONG" else entry - target_r * risk
            reason = "FIB_FIXED_R_TARGET"
        else:
            target_r = available_r
            target = room_target
            reason = "FIB_IMPULSE_EXTREME_TARGET"
        return {
            "passed": True,
            "reason": reason,
            "target_mode": target_mode,
            "target_r": target_r,
            "level_price": boundary,
            "limit_price": target,
            "room_limit_price": room_target,
            "available_r": available_r,
            "minimum_r": minimum_r,
        }

    def _entry_filter_result(self, i, execution_i=None):
        passed, reason = super()._entry_filter_result(i, execution_i)
        if not passed or getattr(self, "signal_strategy_mode", "DI") != FIB_RETRACEMENT_MODE:
            return passed, reason
        target = self._fib_target_plan(i, execution_i)
        if not target["passed"]:
            return False, str(target["reason"])
        return True, reason

    def _open_pair(
        self,
        i,
        entry_filter_passed=True,
        entry_filter_reason="Strategy profile passed",
        schedule=None,
    ):
        indicator_i = schedule["indicator_index"] if schedule else i
        target = (
            self._fib_target_plan(indicator_i, i)
            if getattr(self, "signal_strategy_mode", "DI") == FIB_RETRACEMENT_MODE
            else None
        )
        stop = (
            self._sr_stop_plan(indicator_i, i)
            if getattr(self, "signal_strategy_mode", "DI") == FIB_RETRACEMENT_MODE
            else None
        )
        before = len(self.active_pairs)
        result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        if target and target.get("passed") and len(self.active_pairs) > before:
            for pos in self.active_pairs[-1].positions():
                pos.tp = float(target["limit_price"])
                if getattr(pos, "partial_tp_enabled", False):
                    pos.tp2_price = pos.tp
                pos.fib_target_mode = str(target.get("target_mode", "IMPULSE_EXTREME"))
                pos.fib_target_r = float(target.get("target_r", target["available_r"]))
                pos.fib_target_level_price = float(target["level_price"])
                pos.fib_target_price = float(target["limit_price"])
                pos.fib_target_available_r = float(target["available_r"])
                if stop and stop.get("applied"):
                    pos.fib_stop_boundary_price = float(stop["boundary_price"])
                    pos.fib_stop_price = float(stop["stop_price"])
                    pos.fib_entry_level = float(stop["fib_entry_level"])
                    pos.fib_stop_level = float(stop["fib_stop_level"])
                    pos.fib_impulse_start_price = float(stop["fib_impulse_start_price"])
                    pos.fib_impulse_end_price = float(stop["fib_impulse_end_price"])
                    pos.fib_impulse_span = float(stop["fib_impulse_span"])
                    values = getattr(self, "fib_retracement", {})
                    try:
                        pos.fib_impulse_start_index = int(values["_FIB_IMPULSE_START_INDEX"][indicator_i])
                        pos.fib_impulse_end_index = int(values["_FIB_IMPULSE_END_INDEX"][indicator_i])
                    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                        pass
        return result

    def _build_result_row(self, pair, row_kind, positions):
        row = super()._build_result_row(pair, row_kind, positions)
        pos = positions[0] if positions else None
        row["fib_entry_level"] = getattr(pos, "fib_entry_level", np.nan)
        row["fib_stop_level"] = getattr(pos, "fib_stop_level", np.nan)
        row["fib_stop_boundary_price"] = getattr(pos, "fib_stop_boundary_price", np.nan)
        row["fib_stop_price"] = getattr(pos, "fib_stop_price", np.nan)
        row["fib_impulse_start_price"] = getattr(pos, "fib_impulse_start_price", np.nan)
        row["fib_impulse_end_price"] = getattr(pos, "fib_impulse_end_price", np.nan)
        row["fib_impulse_span"] = getattr(pos, "fib_impulse_span", np.nan)
        row["fib_impulse_start_index"] = getattr(pos, "fib_impulse_start_index", np.nan)
        row["fib_impulse_end_index"] = getattr(pos, "fib_impulse_end_index", np.nan)
        row["fib_target_mode"] = getattr(pos, "fib_target_mode", None)
        row["fib_target_r"] = getattr(pos, "fib_target_r", np.nan)
        row["fib_target_level_price"] = getattr(pos, "fib_target_level_price", np.nan)
        row["fib_target_price"] = getattr(pos, "fib_target_price", np.nan)
        row["fib_target_available_r"] = getattr(pos, "fib_target_available_r", np.nan)
        return row

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
