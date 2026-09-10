"""Optional support/resistance-aware stop and take-profit logic.

Fixed-distance stops and fixed-R targets remain the default. Structural execution
is opt-in and consumes only causal S/R evidence already available at the entry
decision.
"""
from __future__ import annotations

import numpy as np

from crypto_strategy_lab.enhanced_engine import EnhancedBacktestEngine
from crypto_strategy_lab.trade import Side


_SR_CONTEXTS = {
    0: ("support_resistance_strategy", "sr_strategy"),
    60: ("support_resistance_1h", "sr_1h"),
    240: ("support_resistance_4h", "sr_4h"),
    1440: ("support_resistance_1d", "sr_1d"),
}


class SRDynamicTPBacktestEngine(EnhancedBacktestEngine):
    """Optional structural S/R stop plus S/R-aware target policies."""

    def _effective_trade_direction(self, i: int) -> str | None:
        context = self._profile_context(i)
        if context is None:
            return None
        _regime, direction, _key, profile = context
        profile_filter_flip = bool(
            profile.entry_rules
            and self._strategy_profile_rule_group_match(
                i, direction, profile, "FLIP", profile.flip_rule_match_mode
            )
        )
        if profile.flip_direction or profile_filter_flip:
            return "SHORT" if direction == "LONG" else "LONG"
        return direction

    @staticmethod
    def _opposing_level_field(direction: str) -> str:
        return "nearest_resistance_price" if direction == "LONG" else "nearest_support_price"

    @staticmethod
    def _structural_stop_fields(direction: str) -> tuple[str, str]:
        if direction == "LONG":
            return "support_zone_low", "nearest_support_price"
        return "resistance_zone_high", "nearest_resistance_price"

    def _expected_entry_price(self, indicator_i: int, execution_i: int | None, direction: str) -> float:
        if self.config.enable_daily_entry_schedule and execution_i is not None:
            raw = float(self.open[execution_i])
        else:
            raw = float(self.close[indicator_i])
        if direction == "LONG":
            return raw * (1.0 + self.config.slippage)
        return raw * (1.0 - self.config.slippage)

    @staticmethod
    def _finite_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def _primary_sr_value(self, i: int, direction: str, field: str):
        context = self._analyze_support_resistance(i, direction)
        if context is None:
            return None
        return self._finite_float(getattr(context, field, None))

    def _sr_value_for_timeframe(self, i: int, direction: str, field: str, timeframe_minutes: int):
        """Read one independent causal S/R context without combining timeframes."""
        requested = int(timeframe_minutes)
        if requested == -1:
            return self._primary_sr_value(i, direction, field)

        block_info = _SR_CONTEXTS.get(requested)
        if block_info is not None and hasattr(self, "_prepared_research_raw_value"):
            feature_name, prefix = block_info
            column = f"{prefix}_{direction.lower()}_{field}"
            raw = self._prepared_research_raw_value(i, feature_name, column)
            value = self._finite_float(raw)
            if value is not None:
                return value

        strategy_minutes = int(getattr(self.config, "strategy_timeframe_minutes", 0) or 0)
        primary_minutes = int(getattr(self.config, "sr_timeframe_minutes", 0) or strategy_minutes)
        effective_requested = strategy_minutes if requested == 0 else requested
        if effective_requested == primary_minutes:
            return self._primary_sr_value(i, direction, field)
        return None

    def _sr_stop_plan(self, i: int, execution_i: int | None = None) -> dict[str, object]:
        mode = getattr(getattr(self.config, "risk_mode", None), "value", getattr(self.config, "risk_mode", ""))
        if str(mode).upper() != "SR_STRUCTURE":
            return {"passed": True, "applied": False, "reason": "NON_STRUCTURAL_STOP", "distance": None}

        direction = self._effective_trade_direction(i)
        if direction not in ("LONG", "SHORT"):
            return {"passed": True, "applied": False, "reason": "NO_DIRECTION", "distance": None}

        timeframe = int(getattr(self.config, "sr_stop_timeframe_minutes", 0))
        boundary_field, fallback_field = self._structural_stop_fields(direction)
        boundary = self._sr_value_for_timeframe(i, direction, boundary_field, timeframe)
        level = self._sr_value_for_timeframe(i, direction, fallback_field, timeframe)
        if boundary is None:
            boundary = level

        policy = str(getattr(self.config, "sr_stop_no_level_policy", "USE_ATR_STOP")).upper()
        if boundary is None:
            if policy == "REJECT_TRADE":
                return {"passed": False, "applied": False, "reason": "SR_STOP_NO_VALID_LEVEL", "distance": None}
            return {"passed": True, "applied": False, "reason": "NO_LEVEL_USE_ATR_STOP", "distance": None}

        entry = self._expected_entry_price(i, execution_i, direction)
        atr_value = self._finite_float(self.atr_values[i])
        if atr_value is None or atr_value <= 0:
            return {"passed": False, "applied": False, "reason": "SR_STOP_ATR_UNAVAILABLE", "distance": None}

        # A structural stop must sit beyond the outer edge of the relevant zone.
        # The buffer is intentionally measured in strategy ATR so it remains
        # comparable across independently selected S/R timeframes.
        buffer_price = atr_value * float(getattr(self.config, "sr_stop_buffer_atr", 0.25))
        stop_price = boundary - buffer_price if direction == "LONG" else boundary + buffer_price
        distance = entry - stop_price if direction == "LONG" else stop_price - entry
        if not np.isfinite(distance) or distance <= 0:
            if policy == "REJECT_TRADE":
                return {"passed": False, "applied": False, "reason": "SR_STOP_LEVEL_ON_WRONG_SIDE", "distance": None}
            return {"passed": True, "applied": False, "reason": "INVALID_LEVEL_USE_ATR_STOP", "distance": None}

        distance_atr = distance / atr_value
        maximum_atr = float(getattr(self.config, "sr_stop_maximum_atr", 3.0))
        if distance_atr > maximum_atr:
            return {
                "passed": False,
                "applied": False,
                "reason": "SR_STOP_TOO_WIDE",
                "distance": distance,
                "distance_atr": distance_atr,
                "level_price": level,
                "boundary_price": boundary,
                "stop_price": stop_price,
                "timeframe_minutes": timeframe,
            }

        return {
            "passed": True,
            "applied": True,
            "reason": "SR_STRUCTURAL_STOP",
            "distance": distance,
            "distance_atr": distance_atr,
            "level_price": level,
            "boundary_price": boundary,
            "stop_price": stop_price,
            "timeframe_minutes": timeframe,
        }

    def _effective_stop_distance_for_filter(self, i: int, execution_i: int | None, profile) -> tuple[bool, str | None, float | None]:
        plan = self._sr_stop_plan(i, execution_i)
        if not bool(plan["passed"]):
            return False, str(plan["reason"]), None
        if bool(plan.get("applied")):
            return True, None, float(plan["distance"])

        r_unit = float(self.risk[i])
        stop_mult = float(profile.sl2_r if profile.partial_stop_enabled else profile.stop_loss_multiple)
        stop_distance = r_unit * stop_mult
        if not np.isfinite(stop_distance) or stop_distance <= 0:
            return True, None, None
        return True, None, stop_distance

    def _sr_tp_filter_result(self, i: int, execution_i: int | None = None):
        mode = str(getattr(self.config, "sr_take_profit_mode", "FIXED_R")).upper()
        if mode == "FIXED_R":
            return True, None

        context = self._profile_context(i)
        direction = self._effective_trade_direction(i)
        if context is None or direction not in ("LONG", "SHORT"):
            return True, None
        _regime, _original_direction, _key, profile = context

        timeframe = int(getattr(self.config, "sr_take_profit_timeframe_minutes", -1))
        level_price = self._sr_value_for_timeframe(
            i, direction, self._opposing_level_field(direction), timeframe
        )
        if level_price is None:
            policy = str(getattr(self.config, "sr_take_profit_no_level_policy", "USE_FIXED_TP")).upper()
            if policy == "REJECT_TRADE":
                return False, "SR_TP_NO_OPPOSING_LEVEL"
            return True, None

        stop_passed, stop_reason, stop_distance = self._effective_stop_distance_for_filter(
            i, execution_i, profile
        )
        if not stop_passed:
            return False, stop_reason
        if stop_distance is None:
            return True, None

        entry = self._expected_entry_price(i, execution_i, direction)
        room_price = level_price - entry if direction == "LONG" else entry - level_price
        available_r = room_price / stop_distance
        buffer_r = float(getattr(self.config, "sr_take_profit_buffer_r", 0.20))
        maximum_r = float(getattr(self.config, "sr_take_profit_maximum_r", 3.0))
        minimum_r = float(getattr(self.config, "sr_take_profit_minimum_r", 1.5))
        target_r = min(maximum_r, available_r - buffer_r)
        if not np.isfinite(target_r) or target_r < minimum_r:
            return False, "SR_TP_INSUFFICIENT_ROOM"
        return True, None

    def _entry_filter_result(self, i, execution_i=None):
        passed, reason = super()._entry_filter_result(i, execution_i)
        if not passed:
            return passed, reason

        stop_plan = self._sr_stop_plan(i, execution_i)
        if not bool(stop_plan["passed"]):
            return False, str(stop_plan["reason"])

        tp_passed, tp_reason = self._sr_tp_filter_result(i, execution_i)
        if not tp_passed:
            return False, tp_reason
        return True, reason

    def _annotate_sr_stop(self, positions, plan: dict[str, object]) -> None:
        mode = getattr(getattr(self.config, "risk_mode", None), "value", getattr(self.config, "risk_mode", ""))
        for pos in positions:
            pos.sr_stop_mode = str(mode)
            pos.sr_stop_applied = bool(plan.get("applied", False))
            pos.sr_stop_reason = str(plan.get("reason", ""))
            pos.sr_stop_timeframe_minutes = int(plan.get("timeframe_minutes", getattr(self.config, "sr_stop_timeframe_minutes", 0)))
            pos.sr_stop_level_price = plan.get("level_price", np.nan)
            pos.sr_stop_boundary_price = plan.get("boundary_price", np.nan)
            pos.sr_stop_price = plan.get("stop_price", pos.sl)
            pos.sr_stop_distance_atr = plan.get("distance_atr", np.nan)

    def _apply_sr_take_profit(self, indicator_i: int, pair) -> None:
        mode = str(getattr(self.config, "sr_take_profit_mode", "FIXED_R")).upper()
        positions = pair.positions()
        if not positions:
            return

        for pos in positions:
            direction = "LONG" if pos.side == Side.LONG else "SHORT"
            pos.sr_take_profit_mode = mode
            pos.sr_take_profit_applied = False
            pos.sr_take_profit_reason = "FIXED_R_BASELINE"
            pos.sr_take_profit_timeframe_minutes = int(
                getattr(self.config, "sr_take_profit_timeframe_minutes", -1)
            )
            pos.sr_take_profit_level_price = np.nan
            pos.sr_take_profit_available_r = np.nan
            pos.sr_take_profit_target_r = abs(float(pos.tp) - float(pos.entry_price)) / float(pos.risk)

            if mode == "FIXED_R":
                continue

            level_price = self._sr_value_for_timeframe(
                indicator_i,
                direction,
                self._opposing_level_field(direction),
                pos.sr_take_profit_timeframe_minutes,
            )
            if level_price is None:
                pos.sr_take_profit_reason = "NO_LEVEL_USE_FIXED_TP"
                continue

            risk_distance = float(pos.risk)
            if not np.isfinite(risk_distance) or risk_distance <= 0:
                pos.sr_take_profit_reason = "INVALID_RISK_USE_FIXED_TP"
                continue

            room_price = (
                level_price - float(pos.entry_price)
                if direction == "LONG"
                else float(pos.entry_price) - level_price
            )
            available_r = room_price / risk_distance
            buffer_r = float(getattr(self.config, "sr_take_profit_buffer_r", 0.20))
            maximum_r = float(getattr(self.config, "sr_take_profit_maximum_r", 3.0))
            minimum_r = float(getattr(self.config, "sr_take_profit_minimum_r", 1.5))
            existing_r = abs(float(pos.tp) - float(pos.entry_price)) / risk_distance
            room_target_r = min(maximum_r, available_r - buffer_r)
            target_r = min(existing_r, room_target_r) if mode == "SR_CAPPED_R" else room_target_r

            pos.sr_take_profit_level_price = level_price
            pos.sr_take_profit_available_r = available_r
            pos.sr_take_profit_target_r = target_r
            if not np.isfinite(target_r) or target_r < minimum_r:
                # The pre-entry filter normally catches this. Preserve the original
                # target if execution slippage makes the post-fill geometry invalid.
                pos.sr_take_profit_reason = "POST_ENTRY_ROOM_BELOW_MIN_USE_FIXED_TP"
                continue

            side_sign = 1.0 if direction == "LONG" else -1.0
            pos.tp = float(pos.entry_price) + side_sign * target_r * risk_distance
            if getattr(pos, "partial_tp_enabled", False):
                pos.tp2_price = pos.tp
            pos.sr_take_profit_applied = abs(target_r - existing_r) > 1e-12
            if mode == "SR_CAPPED_R":
                pos.sr_take_profit_reason = (
                    "SR_CAPPED" if target_r < existing_r - 1e-12 else "FIXED_TARGET_INSIDE_SR_ROOM"
                )
            else:
                pos.sr_take_profit_reason = "SR_LEVEL_TARGET"

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        indicator_i = schedule["indicator_index"] if schedule else i
        stop_plan = self._sr_stop_plan(indicator_i, i)
        if not bool(stop_plan["passed"]):
            return None

        original_risk = float(self.risk[indicator_i])
        substituted = False
        if bool(stop_plan.get("applied")):
            context = self._profile_context(indicator_i)
            if context is None:
                return None
            _regime, _direction, _key, profile = context
            stop_mult = float(profile.sl2_r if profile.partial_stop_enabled else profile.stop_loss_multiple)
            if not np.isfinite(stop_mult) or stop_mult <= 0:
                return None
            self.risk[indicator_i] = float(stop_plan["distance"]) / stop_mult
            substituted = True

        before = len(self.active_pairs)
        try:
            result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        finally:
            if substituted:
                self.risk[indicator_i] = original_risk

        if len(self.active_pairs) > before:
            pair = self.active_pairs[-1]
            self._annotate_sr_stop(pair.positions(), stop_plan)
            self._apply_sr_take_profit(indicator_i, pair)
        return result

    def _build_result_row(self, p, row_kind, positions):
        row = super()._build_result_row(p, row_kind, positions)
        pos = positions[0] if positions else None

        row["sr_stop_mode"] = getattr(
            pos,
            "sr_stop_mode",
            str(getattr(getattr(self.config, "risk_mode", None), "value", getattr(self.config, "risk_mode", ""))),
        ) if pos is not None else ""
        row["sr_stop_applied"] = bool(getattr(pos, "sr_stop_applied", False)) if pos is not None else False
        row["sr_stop_reason"] = getattr(pos, "sr_stop_reason", "") if pos is not None else ""
        row["sr_stop_timeframe_minutes"] = int(
            getattr(pos, "sr_stop_timeframe_minutes", getattr(self.config, "sr_stop_timeframe_minutes", 0))
        ) if pos is not None else int(getattr(self.config, "sr_stop_timeframe_minutes", 0))
        row["sr_stop_level_price"] = getattr(pos, "sr_stop_level_price", np.nan) if pos is not None else np.nan
        row["sr_stop_boundary_price"] = getattr(pos, "sr_stop_boundary_price", np.nan) if pos is not None else np.nan
        row["sr_stop_price"] = getattr(pos, "sr_stop_price", np.nan) if pos is not None else np.nan
        row["sr_stop_distance_atr"] = getattr(pos, "sr_stop_distance_atr", np.nan) if pos is not None else np.nan
        row["sr_stop_buffer_atr"] = float(getattr(self.config, "sr_stop_buffer_atr", 0.25))
        row["sr_stop_maximum_atr"] = float(getattr(self.config, "sr_stop_maximum_atr", 3.0))
        row["sr_stop_no_level_policy"] = str(getattr(self.config, "sr_stop_no_level_policy", "USE_ATR_STOP"))

        row["sr_take_profit_mode"] = getattr(pos, "sr_take_profit_mode", str(getattr(self.config, "sr_take_profit_mode", "FIXED_R")))
        row["sr_take_profit_applied"] = bool(getattr(pos, "sr_take_profit_applied", False)) if pos is not None else False
        row["sr_take_profit_reason"] = getattr(pos, "sr_take_profit_reason", "") if pos is not None else ""
        row["sr_take_profit_timeframe_minutes"] = int(
            getattr(pos, "sr_take_profit_timeframe_minutes", getattr(self.config, "sr_take_profit_timeframe_minutes", -1))
        ) if pos is not None else int(getattr(self.config, "sr_take_profit_timeframe_minutes", -1))
        row["sr_take_profit_level_price"] = getattr(pos, "sr_take_profit_level_price", np.nan) if pos is not None else np.nan
        row["sr_take_profit_available_r"] = getattr(pos, "sr_take_profit_available_r", np.nan) if pos is not None else np.nan
        row["sr_take_profit_target_r"] = getattr(pos, "sr_take_profit_target_r", np.nan) if pos is not None else np.nan
        row["sr_take_profit_maximum_r"] = float(getattr(self.config, "sr_take_profit_maximum_r", 3.0))
        row["sr_take_profit_minimum_r"] = float(getattr(self.config, "sr_take_profit_minimum_r", 1.5))
        row["sr_take_profit_buffer_r"] = float(getattr(self.config, "sr_take_profit_buffer_r", 0.20))
        row["sr_take_profit_no_level_policy"] = str(getattr(self.config, "sr_take_profit_no_level_policy", "USE_FIXED_TP"))
        return row
