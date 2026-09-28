"""Causal 9/20 EMA pullback scalping signal and structural micro-swing stop."""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_core.ema_strategy import ema_20_100_cross, ema_20_100_entry_direction
from crypto_strategy_lab.engine import _signal_ema
from crypto_strategy_lab.trade import ExitReason, ExitSource, Side


EMA_920_MODE = "EMA_9_20_PULLBACK"
EMA_920_RULE_INDICATORS = frozenset({
    "EMA_9_DISTANCE_ATR",
    "EMA_20_DISTANCE_ATR",
    "EMA_9_20_SPREAD_ATR",
    "EMA_9_SLOPE_ATR",
    "EMA_20_SLOPE_ATR",
    "VOLUME_RATIO_20",
    "VOLUME_CHANGE_PCT",
})


class Ema920PullbackMixin:
    """Add a sparse 9/20 EMA continuation signal without forking the simulator.

    The completed strategy candle is the confirmation candle. The previous
    completed candle must overlap the EMA9/EMA20 band on below-normal volume.
    A trade is then allowed only when trend, candle direction and returning
    volume all agree. Stops use the latest confirmed 2-left/2-right micro swing.
    """

    ema_920_volume_lookback = 20
    ema_920_swing_span = 2
    ema_920_swing_lookback = 20
    ema_920_stop_buffer_atr = 0.05
    ema_920_stop_maximum_atr = 1.50
    ema_100_stop_buffer_atr = 0.05

    def _configure_signal_features(self):
        super()._configure_signal_features()
        self.ema_9_values = _signal_ema(self.close, 9)
        self.ema_20_values = _signal_ema(self.close, 20)
        self.ema_100_values = _signal_ema(self.close, 100)

        if not hasattr(self, "atr_values") or not hasattr(self, "volume"):
            return

        previous_ema9 = np.roll(self.ema_9_values, 1)
        previous_ema20 = np.roll(self.ema_20_values, 1)
        previous_ema9[0] = np.nan
        previous_ema20[0] = np.nan
        atr = np.asarray(self.atr_values, dtype=float)
        valid_atr = np.isfinite(atr) & (atr > 0)
        self.ema_9_slope_atr = np.divide(
            self.ema_9_values - previous_ema9,
            atr,
            out=np.full(len(atr), np.nan, dtype=float),
            where=valid_atr,
        )
        self.ema_20_slope_atr = np.divide(
            self.ema_20_values - previous_ema20,
            atr,
            out=np.full(len(atr), np.nan, dtype=float),
            where=valid_atr,
        )
        self.ema_9_20_spread_atr = np.divide(
            self.ema_9_values - self.ema_20_values,
            atr,
            out=np.full(len(atr), np.nan, dtype=float),
            where=valid_atr,
        )

        volume = np.asarray(self.volume, dtype=float)
        baseline = (
            pd.Series(volume, dtype=float)
            .rolling(self.ema_920_volume_lookback, min_periods=self.ema_920_volume_lookback)
            .mean()
            .shift(1)
            .to_numpy(float)
        )
        self.volume_ratio_20 = np.divide(
            volume,
            baseline,
            out=np.full(len(volume), np.nan, dtype=float),
            where=np.isfinite(baseline) & (baseline > 0),
        )
        previous_volume = np.roll(volume, 1)
        previous_volume[0] = np.nan
        self.volume_change_pct = np.divide(
            volume - previous_volume,
            previous_volume,
            out=np.full(len(volume), np.nan, dtype=float),
            where=np.isfinite(previous_volume) & (previous_volume > 0),
        )

    def _infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                if str(rule.get("_strategy_direction_mode", "")).upper() == EMA_920_MODE:
                    return EMA_920_MODE
        return super()._infer_signal_strategy_mode()

    def _ema_920_direction(self, i: int):
        if i <= self.ema_920_volume_lookback:
            return None
        previous = i - 1
        values = (
            self.ema_9_values[i], self.ema_20_values[i],
            self.ema_9_values[previous], self.ema_20_values[previous],
            self.ema_9_slope_atr[i], self.ema_20_slope_atr[i],
            self.volume_ratio_20[previous], self.volume[i], self.volume[previous],
            self.open[i], self.close[i], self.close[previous],
            self.low[previous], self.high[previous],
        )
        if not all(np.isfinite(float(value)) for value in values):
            return None

        prev_fast = float(self.ema_9_values[previous])
        prev_slow = float(self.ema_20_values[previous])
        band_low = min(prev_fast, prev_slow)
        band_high = max(prev_fast, prev_slow)
        pulled_into_band = (
            float(self.low[previous]) <= band_high
            and float(self.high[previous]) >= band_low
        )
        if not pulled_into_band or float(self.volume_ratio_20[previous]) >= 1.0:
            return None
        if float(self.volume[i]) <= float(self.volume[previous]):
            return None

        fast = float(self.ema_9_values[i])
        slow = float(self.ema_20_values[i])
        close = float(self.close[i])
        open_ = float(self.open[i])
        previous_close = float(self.close[previous])
        fast_slope = float(self.ema_9_slope_atr[i])
        slow_slope = float(self.ema_20_slope_atr[i])

        long_setup = (
            fast > slow
            and fast_slope > 0
            and slow_slope > 0
            and previous_close >= prev_slow
            and close > open_
            and close > fast
        )
        if long_setup:
            return "LONG"

        short_setup = (
            fast < slow
            and fast_slope < 0
            and slow_slope < 0
            and previous_close <= prev_slow
            and close < open_
            and close < fast
        )
        if short_setup:
            return "SHORT"
        return None

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:
            cross_mode = self._ema_920_cross_mode()
            if cross_mode is not None:
                return ema_20_100_entry_direction(
                    i, self.ema_20_values, self.ema_100_values,
                    self.config.ema_920_trade_plan,
                )
            return self._ema_920_direction(i)
        return super()._selected_direction(i)

    def _ema_920_cross_mode(self):
        plan = getattr(self.config, "ema_920_trade_plan", "PULLBACK_1R")
        return {
            "EMA_20_100_CROSS": "LONG",
            "EMA_20_100_CROSS_SHORT": "SHORT",
            "EMA_20_100_CROSS_BOTH": "BOTH",
        }.get(plan)

    def _ema_920_cross_plan(self):
        return self._ema_920_cross_mode() is not None

    def _ema_20_100_cross(self, i, *, upwards):
        return ema_20_100_cross(
            i, self.ema_20_values, self.ema_100_values, upwards=upwards,
        )

    def _scan_pair_exit(self, pair, i):
        if self._close_on_ema_20_100_cross(pair.positions(), i):
            return
        return super()._scan_pair_exit(pair, i)

    def _scan_position_exit(self, pair, position, i):
        # The production Data Lake path advances a Position directly; it does
        # not dispatch through _scan_pair_exit.
        if self._close_on_ema_20_100_cross((position,), i):
            return
        return super()._scan_position_exit(pair, position, i)

    def _close_on_ema_20_100_cross(self, positions, i):
        # At the open of candle i, only the completed candle i-1 is known.
        if (getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE
                or not self._ema_920_cross_plan()
                or i <= 0):
            return False
        bullish_cross = self._ema_20_100_cross(i - 1, upwards=True)
        bearish_cross = self._ema_20_100_cross(i - 1, upwards=False)
        if not bullish_cross and not bearish_cross:
            return False
        closed = False
        opening = float(self.open[i])
        for pos in positions:
            if not pos.is_open:
                continue
            should_close = (
                (pos.side == Side.LONG and bearish_cross)
                or (pos.side == Side.SHORT and bullish_cross)
            )
            if not should_close:
                continue
            # A protective stop gapped through at the open takes precedence.
            stopped = opening <= pos.sl if pos.side == Side.LONG else opening >= pos.sl
            slip = 1 - self.config.slippage if pos.side == Side.LONG else 1 + self.config.slippage
            self._close_position(
                pos, i, opening * slip,
                ExitReason.SL if stopped else ExitReason.EMA_20_100_CROSS,
                ExitSource.STRATEGY_OPEN, self.times[i],
            )
            closed = True
        return closed

    def _entry_filter_result(self, i, execution_i=None):
        passed, reason = super()._entry_filter_result(i, execution_i)
        if not passed or getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE or not self._ema_920_cross_plan():
            return passed, reason
        context = self._profile_context(i)
        if context is None:
            return passed, reason
        _regime, direction, _key, profile = context
        flipped = profile.flip_direction or bool(
            profile.entry_rules and self._strategy_profile_rule_group_match(
                i, direction, profile, "FLIP", profile.flip_rule_match_mode
            )
        )
        return (False, "EMA 20/100 crossover uses native direction; direction FLIP disabled") if flipped else (passed, reason)

    def _should_enter(self, i):
        if getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE:
            return super()._should_enter(i)
        direction = self._selected_direction(i)
        if direction is None:
            return False
        if super()._should_enter(i):
            return True

        # In BOTH mode, an opposite crossover is simultaneously the exit signal
        # for the current position and the entry signal for the reverse side.
        # Allow that signal to be queued even though the old trade is still open
        # until the next candle's open.
        if self._ema_920_cross_mode() != "BOTH" or len(self.active_pairs) != 1:
            return False
        entry_mode = str(getattr(getattr(self.config, "entry_mode", ""), "value",
                                 getattr(self.config, "entry_mode", ""))).upper()
        if entry_mode != "WAIT_UNTIL_CLOSED":
            return False
        if not np.isfinite(self.risk[i]) or self.risk[i] <= 0 or not self._in_trading_window(i):
            return False
        if self.last_timeout_exit_time is not None and self._entry_time(i) <= self.last_timeout_exit_time:
            return False
        positions = [pos for pos in self.active_pairs[0].positions() if pos.is_open]
        if not positions:
            return False
        wanted = Side.LONG if direction == "LONG" else Side.SHORT
        return all(pos.side != wanted for pos in positions)

    def _execute_pending_next_open_entry(self, i, active_at_candle_start=False):
        decision = getattr(self, "pending_next_open_entry", None)
        if (
            decision
            and int(decision.get("execution_index", -1)) == i
            and active_at_candle_start
            and self._ema_920_cross_mode() == "BOTH"
        ):
            indicator_i = int(decision["indicator_index"])
            direction = self._selected_direction(indicator_i)
            wanted = Side.LONG if direction == "LONG" else Side.SHORT if direction == "SHORT" else None
            positions = [
                pos
                for pair in self.active_pairs
                for pos in pair.positions()
                if pos.is_open
            ]
            if wanted is not None and positions and all(pos.side != wanted for pos in positions):
                for pair in list(self.active_pairs):
                    self._close_on_ema_20_100_cross(pair.positions(), i)
                self._collect_closed_pairs()
                active_at_candle_start = bool(self.active_pairs)
        return super()._execute_pending_next_open_entry(i, active_at_candle_start)

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator not in EMA_920_RULE_INDICATORS:
            return super()._strategy_profile_rule_value(i, direction, profile, indicator)

        atr = float(self.atr_values[i])
        if indicator in {"EMA_9_DISTANCE_ATR", "EMA_20_DISTANCE_ATR"}:
            if not np.isfinite(atr) or atr <= 0:
                return np.nan
            mean = self.ema_9_values[i] if indicator == "EMA_9_DISTANCE_ATR" else self.ema_20_values[i]
            if not np.isfinite(mean):
                return np.nan
            return (float(self.close[i]) - float(mean)) / atr
        if indicator == "EMA_9_20_SPREAD_ATR":
            return float(self.ema_9_20_spread_atr[i])
        if indicator == "EMA_9_SLOPE_ATR":
            return float(self.ema_9_slope_atr[i])
        if indicator == "EMA_20_SLOPE_ATR":
            return float(self.ema_20_slope_atr[i])
        if indicator == "VOLUME_RATIO_20":
            return float(self.volume_ratio_20[i])
        if indicator == "VOLUME_CHANGE_PCT":
            return float(self.volume_change_pct[i])
        raise KeyError(indicator)

    def _latest_confirmed_micro_swing(self, i: int, direction: str):
        span = self.ema_920_swing_span
        start = max(span, i - self.ema_920_swing_lookback + 1)
        stop = i - span
        if stop < start:
            return None
        candidate = None
        for j in range(start, stop + 1):
            if direction == "LONG":
                value = float(self.low[j])
                if value < float(np.min(self.low[j - span:j])) and value < float(np.min(self.low[j + 1:j + span + 1])):
                    candidate = (j, value)
            else:
                value = float(self.high[j])
                if value > float(np.max(self.high[j - span:j])) and value > float(np.max(self.high[j + 1:j + span + 1])):
                    candidate = (j, value)
        return candidate

    def _ema_920_micro_swing_stop_plan(self, i: int, execution_i: int | None = None):
        direction = self._effective_trade_direction(i)
        if direction not in {"LONG", "SHORT"}:
            return {"passed": False, "applied": False, "reason": "EMA920_NO_DIRECTION", "distance": None}
        swing = self._latest_confirmed_micro_swing(i, direction)
        if swing is None:
            return {"passed": False, "applied": False, "reason": "EMA920_NO_CONFIRMED_MICRO_SWING", "distance": None}
        swing_i, level = swing
        atr = float(self.atr_values[i])
        if not np.isfinite(atr) or atr <= 0:
            return {"passed": False, "applied": False, "reason": "EMA920_ATR_UNAVAILABLE", "distance": None}
        entry = float(self._expected_entry_price(i, execution_i, direction))
        buffer_price = atr * self.ema_920_stop_buffer_atr
        stop_price = level - buffer_price if direction == "LONG" else level + buffer_price
        if execution_i is not None and execution_i > i:
            raw_open = float(self.open[execution_i])
            gap_through = raw_open <= stop_price if direction == "LONG" else raw_open >= stop_price
            if gap_through:
                return {
                    "passed": False, "applied": False,
                    "reason": "ENTRY_INVALIDATED_GAP_THROUGH_STOP",
                    "distance": None, "level_price": level, "boundary_price": level,
                    "stop_price": stop_price,
                    "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
                    "micro_swing_index": swing_i, "micro_swing": True,
                }
        distance = entry - stop_price if direction == "LONG" else stop_price - entry
        if not np.isfinite(distance) or distance <= 0:
            return {"passed": False, "applied": False, "reason": "EMA920_SWING_ON_WRONG_SIDE", "distance": None}
        distance_atr = distance / atr
        if distance_atr > self.ema_920_stop_maximum_atr:
            return {
                "passed": False, "applied": False, "reason": "EMA920_MICRO_SWING_STOP_TOO_WIDE",
                "distance": distance, "distance_atr": distance_atr,
                "level_price": level, "boundary_price": level, "stop_price": stop_price,
                "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
                "micro_swing_index": swing_i, "micro_swing": True,
            }
        return {
            "passed": True, "applied": True, "reason": "EMA920_MICRO_SWING_STOP",
            "distance": distance, "distance_atr": distance_atr,
            "level_price": level, "boundary_price": level, "stop_price": stop_price,
            "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
            "micro_swing_index": swing_i, "micro_swing": True,
        }

    def _ema_100_cross_stop_plan(self, i: int, execution_i: int | None = None):
        """Anchor the base protective stop to signal-close EMA100, then optionally widen it.

        The base entry-to-EMA100 stop distance is the sizing-R reference.  The
        configurable multiplier changes only the actual protective stop distance,
        so a 2x stop with a 1% sizing budget carries about 2% full-stop exposure.
        """
        direction = self._effective_trade_direction(i)
        if direction not in {"LONG", "SHORT"}:
            return {"passed": False, "applied": False, "reason": "EMA100_NO_DIRECTION", "distance": None}
        level = float(self.ema_100_values[i])
        atr = float(self.atr_values[i])
        if not np.isfinite(level) or not np.isfinite(atr) or atr <= 0:
            return {"passed": False, "applied": False, "reason": "EMA100_STOP_UNAVAILABLE", "distance": None}
        context = self._profile_context(i)
        profile = context[3] if context is not None else None
        multiplier = float(getattr(profile, "ema_cross_stop_multiplier", 1.0))
        if not np.isfinite(multiplier) or multiplier <= 0:
            return {"passed": False, "applied": False, "reason": "EMA100_STOP_MULTIPLIER_INVALID", "distance": None}
        buffer_atr = float(getattr(profile, "ema_cross_stop_buffer_atr", self.ema_100_stop_buffer_atr))
        if not np.isfinite(buffer_atr) or buffer_atr < 0:
            return {"passed": False, "applied": False, "reason": "EMA100_STOP_BUFFER_INVALID", "distance": None}
        buffer_price = buffer_atr * atr
        base_stop_price = level - buffer_price if direction == "LONG" else level + buffer_price
        entry = float(self._expected_entry_price(i, execution_i, direction))
        base_distance = entry - base_stop_price if direction == "LONG" else base_stop_price - entry
        if not np.isfinite(base_distance) or base_distance <= 0:
            return {
                "passed": False, "applied": False, "reason": "ENTRY_INVALIDATED_GAP_THROUGH_STOP",
                "distance": None, "base_distance": None,
                "level_price": level, "boundary_price": level,
                "stop_price": base_stop_price, "base_stop_price": base_stop_price,
                "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
                "ema_100_stop": True,
            }
        distance = base_distance * multiplier
        stop_price = entry - distance if direction == "LONG" else entry + distance
        return {
            "passed": True, "applied": True, "reason": "EMA100_CROSS_STOP",
            "distance": distance, "base_distance": base_distance,
            "distance_atr": distance / atr, "base_distance_atr": base_distance / atr,
            "stop_multiplier": multiplier,
            "level_price": level, "boundary_price": level,
            "stop_price": stop_price, "base_stop_price": base_stop_price,
            "timeframe_minutes": int(getattr(self.config, "strategy_timeframe_minutes", 0)),
            "ema_100_stop": True,
        }

    def _sr_stop_plan(self, i: int, execution_i: int | None = None):
        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:
            if self._ema_920_cross_plan():
                return self._ema_100_cross_stop_plan(i, execution_i)
            return self._ema_920_micro_swing_stop_plan(i, execution_i)
        return super()._sr_stop_plan(i, execution_i)

    def _annotate_sr_stop(self, positions, plan):
        super()._annotate_sr_stop(positions, plan)
        if plan.get("ema_100_stop"):
            for pos in positions:
                pos.ema_100_stop_level = plan.get("level_price", np.nan)
                pos.ema_100_stop_price = plan.get("stop_price", np.nan)
                pos.ema_100_base_stop_price = plan.get("base_stop_price", np.nan)
                pos.ema_100_base_stop_distance = plan.get("base_distance", np.nan)
                pos.ema_100_stop_multiplier = plan.get("stop_multiplier", 1.0)
                pos.ema_100_stop_distance_atr = plan.get("distance_atr", np.nan)
        if not plan.get("micro_swing"):
            return
        for pos in positions:
            pos.micro_swing_stop_applied = bool(plan.get("applied", False))
            pos.micro_swing_index = plan.get("micro_swing_index")
            pos.micro_swing_level_price = plan.get("level_price", np.nan)
            pos.micro_swing_stop_price = plan.get("stop_price", np.nan)
            pos.micro_swing_stop_distance_atr = plan.get("distance_atr", np.nan)

    def _build_result_row(self, p, row_kind, positions):
        row = super()._build_result_row(p, row_kind, positions)
        pos = positions[0] if positions else None
        row["micro_swing_stop_applied"] = bool(getattr(pos, "micro_swing_stop_applied", False)) if pos is not None else False
        row["micro_swing_index"] = getattr(pos, "micro_swing_index", None) if pos is not None else None
        row["micro_swing_level_price"] = getattr(pos, "micro_swing_level_price", np.nan) if pos is not None else np.nan
        row["micro_swing_stop_price"] = getattr(pos, "micro_swing_stop_price", np.nan) if pos is not None else np.nan
        row["micro_swing_stop_distance_atr"] = getattr(pos, "micro_swing_stop_distance_atr", np.nan) if pos is not None else np.nan
        row["ema_100_stop_level"] = getattr(pos, "ema_100_stop_level", np.nan) if pos is not None else np.nan
        row["ema_100_stop_price"] = getattr(pos, "ema_100_stop_price", np.nan) if pos is not None else np.nan
        row["ema_100_base_stop_price"] = getattr(pos, "ema_100_base_stop_price", np.nan) if pos is not None else np.nan
        row["ema_100_base_stop_distance"] = getattr(pos, "ema_100_base_stop_distance", np.nan) if pos is not None else np.nan
        row["ema_100_stop_multiplier"] = getattr(pos, "ema_100_stop_multiplier", np.nan) if pos is not None else np.nan
        row["ema_100_stop_distance_atr"] = getattr(pos, "ema_100_stop_distance_atr", np.nan) if pos is not None else np.nan
        return row

    def _position_sizing_stop_distance(self, profile, risk_unit, actual_stop):
        base_distance = getattr(self, "_ema_cross_sizing_distance", None)
        if self._ema_920_cross_plan() and base_distance is not None:
            base_distance = float(base_distance)
            if np.isfinite(base_distance) and base_distance > 0:
                actual = float(actual_stop)
                sizing_multiple = 1.0
                if bool(getattr(profile, "position_sizing_stop_override_enabled", False)):
                    sizing_multiple = float(
                        getattr(profile, "position_sizing_stop_multiple", 1.0)
                    )
                    if not np.isfinite(sizing_multiple) or sizing_multiple <= 0:
                        raise ValueError(
                            "EMA-cross position-sizing stop multiple must be finite and positive"
                        )
                sizing_distance = base_distance * sizing_multiple
                actual_as_sizing_r = (
                    actual / sizing_distance if np.isfinite(actual) else np.nan
                )
                applied = (
                    bool(getattr(profile, "position_sizing_stop_override_enabled", False))
                    or abs(actual - sizing_distance) > 1e-12
                )
                return sizing_distance, sizing_multiple, applied
        return super()._position_sizing_stop_distance(profile, risk_unit, actual_stop)

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        indicator_i = schedule["indicator_index"] if schedule else i
        self._ema_cross_sizing_distance = None
        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE and self._ema_920_cross_plan():
            plan = self._ema_100_cross_stop_plan(indicator_i, i)
            if bool(plan.get("passed")):
                self._ema_cross_sizing_distance = plan.get("base_distance")

        before = len(self.active_pairs)
        try:
            result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        finally:
            self._ema_cross_sizing_distance = None
        if getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE or len(self.active_pairs) <= before:
            return result
        pair = self.active_pairs[-1]
        context = self._profile_context(indicator_i)
        profile = context[3] if context is not None else None
        for pos in pair.positions():
            if self._ema_920_cross_plan():
                # The opposite crossover is the runner exit.  An optional TP1
                # closes only part of the position and is measured from the
                # original EMA100 sizing-R, not from a widened protective stop.
                pos.tp = np.nan
                pos.ema_920_fixed_target_r = None
                if getattr(pos, "partial_tp_enabled", False):
                    base_distance = float(
                        getattr(pos, "position_sizing_reference_distance", np.nan)
                    )
                    tp1_r = float(getattr(profile, "tp1_r", 1.0))
                    side_sign = 1.0 if str(getattr(pos.side, "value", pos.side)).upper() == "LONG" else -1.0
                    if np.isfinite(base_distance) and base_distance > 0:
                        pos.tp1_price = float(pos.entry_price) + side_sign * tp1_r * base_distance
                    # Disable the legacy fixed TP2. The remaining quantity is a
                    # true runner until the opposite EMA20/100 cross or stop.
                    pos.tp2_price = np.inf if side_sign > 0 else -np.inf
                    pos.tp2_quantity = 0.0
                continue
            side_sign = 1.0 if str(getattr(pos.side, "value", pos.side)).upper() == "LONG" else -1.0
            pos.tp = float(pos.entry_price) + side_sign * float(pos.risk)
            if getattr(pos, "partial_tp_enabled", False):
                pos.tp2_price = pos.tp
            pos.ema_920_fixed_target_r = 1.0
        return result
