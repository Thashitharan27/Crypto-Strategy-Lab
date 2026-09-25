"""Causal 9/20 EMA pullback scalping signal and structural micro-swing stop."""
from __future__ import annotations

import numpy as np
import pandas as pd

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
            if self._ema_920_cross_plan():
                return "LONG" if self._ema_20_100_cross(i, upwards=True) else None
            return self._ema_920_direction(i)
        return super()._selected_direction(i)

    def _ema_920_cross_plan(self):
        return getattr(self.config, "ema_920_trade_plan", "PULLBACK_1R") == "EMA_20_100_CROSS"

    def _ema_20_100_cross(self, i, *, upwards):
        if i < 100:
            return False
        current_20, previous_20 = float(self.ema_20_values[i]), float(self.ema_20_values[i - 1])
        current_100, previous_100 = float(self.ema_100_values[i]), float(self.ema_100_values[i - 1])
        if not all(np.isfinite(v) for v in (current_20, previous_20, current_100, previous_100)):
            return False
        return (previous_20 <= previous_100 and current_20 > current_100) if upwards else (
            previous_20 >= previous_100 and current_20 < current_100
        )

    def _scan_pair_exit(self, pair, i):
        # At the open of candle i, only the completed candle i-1 is known.
        if (getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE
                and self._ema_920_cross_plan()
                and self._ema_20_100_cross(i - 1, upwards=False)):
            for pos in pair.positions():
                if not pos.is_open or pos.side != Side.LONG:
                    continue
                opening = float(self.open[i])
                # A protective stop gapped through at the open takes precedence.
                stopped = opening <= pos.sl
                self._close_position(
                    pos, i, opening * (1 - self.config.slippage),
                    ExitReason.SL if stopped else ExitReason.EMA_20_100_CROSS,
                    ExitSource.STRATEGY_OPEN, self.times[i],
                )
            return
        return super()._scan_pair_exit(pair, i)

    def _should_enter(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:
            if self._selected_direction(i) is None:
                return False
        return super()._should_enter(i)

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

    def _sr_stop_plan(self, i: int, execution_i: int | None = None):
        if getattr(self, "signal_strategy_mode", "DI") == EMA_920_MODE:
            return self._ema_920_micro_swing_stop_plan(i, execution_i)
        return super()._sr_stop_plan(i, execution_i)

    def _annotate_sr_stop(self, positions, plan):
        super()._annotate_sr_stop(positions, plan)
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
        return row

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        before = len(self.active_pairs)
        result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        if getattr(self, "signal_strategy_mode", "DI") != EMA_920_MODE or len(self.active_pairs) <= before:
            return result
        pair = self.active_pairs[-1]
        for pos in pair.positions():
            if self._ema_920_cross_plan():
                # The crossover is the profit exit; keep the protective swing stop.
                pos.tp = np.nan
                pos.ema_920_fixed_target_r = None
                continue
            side_sign = 1.0 if str(getattr(pos.side, "value", pos.side)).upper() == "LONG" else -1.0
            pos.tp = float(pos.entry_price) + side_sign * float(pos.risk)
            if getattr(pos, "partial_tp_enabled", False):
                pos.tp2_price = pos.tp
            pos.ema_920_fixed_target_r = 1.0
        return result
