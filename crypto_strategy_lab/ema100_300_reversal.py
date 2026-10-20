"""Completed-candle EMA100-low / EMA300-high reversal with a fixed 1R exit."""
from dataclasses import replace

import numpy as np
import pandas as pd

from crypto_strategy_lab.engine import _signal_ema

MODE = "EMA_100_300_REVERSAL"


def reversal_directions(open_, close, ema100, ema300):
    open_, close, ema100, ema300 = [np.asarray(a, dtype=float) for a in (open_, close, ema100, ema300)]
    if any(a.ndim != 1 or len(a) != len(close) for a in (open_, close, ema100, ema300)):
        raise ValueError("EMA reversal inputs must align")
    directions = np.full(len(close), None, dtype=object)
    for i in range(2, len(close)):
        if not (np.isfinite(open_[i-2:i+1]).all() and np.isfinite(close[i-2:i+1]).all()
                and np.isfinite(ema100[i]) and np.isfinite(ema300[i])):
            continue
        green = close[i-2:i+1] > open_[i-2:i+1]
        red = close[i-2:i+1] < open_[i-2:i+1]
        if green[0] and red[1] and red[2] and ema300[i] > ema100[i]:
            directions[i] = "SHORT"
        elif red[0] and green[1] and green[2] and ema300[i] < ema100[i]:
            directions[i] = "LONG"
    return directions


class Ema100300ReversalMixin:
    def _configure_signal_features(self):
        super()._configure_signal_features()
        if not any(rule.get("_strategy_direction_mode") == MODE
                   for p in self.config.strategy_profiles.values() for rule in getattr(p, "entry_rules", ())):
            return
        self.ema100_low_values = _signal_ema(self.low, 100)
        self.ema300_high_values = _signal_ema(self.high, 300)
        self.ema100_300_directions = reversal_directions(
            self.open, self.close, self.ema100_low_values, self.ema300_high_values,
        )
        stamps = pd.DatetimeIndex(self.times)
        expected = pd.Timedelta(minutes=2*self.config.strategy_timeframe_minutes)
        for i in range(2, len(stamps)):
            if stamps[i]-stamps[i-2] != expected:
                self.ema100_300_directions[i] = None

    def _infer_signal_strategy_mode(self):
        if any(rule.get("_strategy_direction_mode") == MODE
               for p in self.config.strategy_profiles.values() for rule in getattr(p, "entry_rules", ())):
            return MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", None) == MODE:
            return self.ema100_300_directions[i]
        return super()._selected_direction(i)

    def _should_enter(self, i):
        if getattr(self, "signal_strategy_mode", None) == MODE:
            return self._selected_direction(i) in {"LONG", "SHORT"}
        return super()._should_enter(i)

    def _profile_context(self, i):
        context = super()._profile_context(i)
        if getattr(self, "signal_strategy_mode", None) != MODE or context is None:
            return context
        # This preset owns its fixed 1R geometry, including position sizing.
        profile = replace(context[3], reward_risk_ratio=1., stop_loss_multiple=1.,
                          position_sizing_stop_override_enabled=False,
                          partial_profit_enabled=False, partial_stop_enabled=False,
                          trailing_enabled=False, break_even_enabled=False,
                          r_step_trailing_enabled=False, atr_checkpoint_tp_extension_enabled=False,
                          timeout_enabled=False)
        return (*context[:3], profile)

    def _entry_decision(self, i, active_at_candle_start=False):
        if getattr(self, "signal_strategy_mode", None) != MODE:
            return super()._entry_decision(i, active_at_candle_start)
        if i+1 >= len(self.times) or not self._should_enter(i):
            return None
        if pd.Timestamp(self.times[i+1])-pd.Timestamp(self.times[i]) != pd.Timedelta(minutes=self.config.strategy_timeframe_minutes):
            return None
        return {"execution_index": i+1, "indicator_index": i,
                "scheduled_timestamp": pd.Timestamp(self.times[i+1]),
                "actual_entry_timestamp": None, "entry_schedule_status": "NEXT_CANDLE_OPEN",
                "fill_price_source": "NEXT_CANDLE_OPEN", "defer_to_next_open": True}

    def _sr_stop_plan(self, i, execution_i=None):
        if getattr(self, "signal_strategy_mode", None) != MODE:
            return super()._sr_stop_plan(i, execution_i)
        side = self._effective_trade_direction(i)
        entry = float(self._expected_entry_price(i, execution_i, side))
        target = float(self.ema100_low_values[i])
        distance = target-entry if side == "LONG" else entry-target
        order = (self.ema300_high_values[i] < target if side == "LONG"
                 else self.ema300_high_values[i] > target)
        if side not in {"LONG", "SHORT"} or not order or not np.isfinite(distance) or distance <= 0:
            return {"passed": False, "applied": False, "reason": "EMA100_TARGET_WRONG_SIDE", "distance": None}
        slow = float(self.ema300_high_values[i])
        outside = entry > max(target, slow) if side == "SHORT" else entry < min(target, slow)
        if not outside:
            return {"passed": False, "applied": False,
                    "reason": "EMA100_300_ENTRY_POSITION_REJECTED", "distance": None}
        minimum = float(getattr(self.config, "ema_reversal_min_gap_atr", 0.5))
        atr = float(self.atr_values[i])
        if minimum > 0 and (not np.isfinite(atr) or atr <= 0 or abs(target-slow) < minimum*atr):
            return {"passed": False, "applied": False,
                    "reason": "EMA100_300_GAP_TOO_SMALL", "distance": None}
        return {"passed": True, "applied": True, "reason": "EMA100_EQUAL_DISTANCE_STOP",
                "distance": distance, "stop_price": 2*entry-target,
                "level_price": target, "boundary_price": 2*entry-target,
                "distance_atr": distance/self.atr_values[i] if self.atr_values[i] > 0 else np.nan,
                "timeframe_minutes": self.config.strategy_timeframe_minutes}

    def _apply_sr_take_profit(self, i, pair):
        if getattr(self, "signal_strategy_mode", None) != MODE:
            return super()._apply_sr_take_profit(i, pair)
        for pos in pair.positions():
            pos.tp = float(self.ema100_low_values[i])

    def _sr_tp_filter_result(self, i, execution_i=None):
        if getattr(self, "signal_strategy_mode", None) == MODE:
            return True, None
        return super()._sr_tp_filter_result(i, execution_i)

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        before = len(self.active_pairs)
        result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        if getattr(self, "signal_strategy_mode", None) == MODE and len(self.active_pairs) > before:
            j = schedule["indicator_index"] if schedule else i
            pair = self.active_pairs[-1]
            pair.ema100_low = float(self.ema100_low_values[j])
            pair.ema300_high = float(self.ema300_high_values[j])
        return result

    def _build_result_row(self, pair, row_kind, positions):
        row = super()._build_result_row(pair, row_kind, positions)
        if getattr(self, "signal_strategy_mode", None) == MODE:
            row["ema100_low"] = getattr(pair, "ema100_low", np.nan)
            row["ema300_high"] = getattr(pair, "ema300_high", np.nan)
            row["ema_reversal_target_r"] = 1.
            row["ema_reversal_entry_position_rule"] = "SHORT_ABOVE_BOTH_LONG_BELOW_BOTH_V1"
        return row
