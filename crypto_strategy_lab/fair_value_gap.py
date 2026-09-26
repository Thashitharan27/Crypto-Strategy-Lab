"""Causal three-candle fair value gap first-revisit signal."""
from __future__ import annotations

import numpy as np
import pandas as pd


FVG_MODE = "FAIR_VALUE_GAP"
FVG_RULE_INDICATORS = frozenset({"FVG_GAP_SIZE_ATR", "FVG_AGE_BARS", "FVG_REVISIT_DEPTH_PCT"})
FVG_STOP_BUFFER_ATR = 0.05
FVG_TARGET_BUFFER_ATR = 0.05


def first_revisit_context(high, low, close, atr=None):
    """Signal on the first completed candle touching a previously formed gap.

    A bullish gap is (high[i-2], low[i]); a bearish gap is
    (high[i], low[i-2]). Formation and revisit cannot share a candle.
    The first touch consumes the gap even if the revisit candle fails to
    confirm, preventing repeated attempts on the same zone.
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    if high.shape != low.shape or high.shape != close.shape:
        raise ValueError("FVG candle arrays must have equal lengths")
    atr = np.full(len(close), np.nan) if atr is None else np.asarray(atr, dtype=float)
    if atr.shape != close.shape:
        raise ValueError("FVG ATR array must match candle lengths")
    result = np.full(len(close), None, dtype=object)
    stop_boundaries = {side: np.full(len(close), np.nan) for side in ("LONG", "SHORT")}
    target_boundaries = {side: np.full(len(close), np.nan) for side in ("LONG", "SHORT")}
    features = {
        side: {key: np.full(len(close), np.nan) for key in FVG_RULE_INDICATORS}
        for side in ("LONG", "SHORT")
    }
    bullish = []
    bearish = []
    for i in range(len(close)):
        if not all(np.isfinite(v) for v in (high[i], low[i], close[i])):
            bullish.clear()
            bearish.clear()
            continue
        long_touch = False
        short_touch = False
        next_bullish = []
        for bottom, top, formed, extreme in bullish:
            extreme = max(extreme, high[i])
            if low[i] <= top and high[i] >= bottom:
                if np.isnan(features["LONG"]["FVG_AGE_BARS"][i]):
                    features["LONG"]["FVG_AGE_BARS"][i] = i - formed
                    features["LONG"]["FVG_REVISIT_DEPTH_PCT"][i] = min(
                        1.0, max(0.0, (top - low[i]) / (top - bottom))
                    )
                    if np.isfinite(atr[formed]) and atr[formed] > 0:
                        features["LONG"]["FVG_GAP_SIZE_ATR"][i] = (top - bottom) / atr[formed]
                if close[i] > top and not long_touch:
                    stop_boundaries["LONG"][i] = bottom
                    target_boundaries["LONG"][i] = extreme
                    long_touch = True
            else:
                next_bullish.append((bottom, top, formed, extreme))
        next_bearish = []
        for bottom, top, formed, extreme in bearish:
            extreme = min(extreme, low[i])
            if high[i] >= bottom and low[i] <= top:
                if np.isnan(features["SHORT"]["FVG_AGE_BARS"][i]):
                    features["SHORT"]["FVG_AGE_BARS"][i] = i - formed
                    features["SHORT"]["FVG_REVISIT_DEPTH_PCT"][i] = min(
                        1.0, max(0.0, (high[i] - bottom) / (top - bottom))
                    )
                    if np.isfinite(atr[formed]) and atr[formed] > 0:
                        features["SHORT"]["FVG_GAP_SIZE_ATR"][i] = (top - bottom) / atr[formed]
                if close[i] < bottom and not short_touch:
                    stop_boundaries["SHORT"][i] = top
                    target_boundaries["SHORT"][i] = extreme
                    short_touch = True
            else:
                next_bearish.append((bottom, top, formed, extreme))
        bullish, bearish = next_bullish, next_bearish
        if long_touch != short_touch:
            result[i] = "LONG" if long_touch else "SHORT"
        if i >= 2 and np.isfinite(high[i - 2]) and np.isfinite(low[i - 2]):
            if low[i] > high[i - 2]:
                bullish.append((high[i - 2], low[i], i, high[i]))
            if high[i] < low[i - 2]:
                bearish.append((high[i], low[i - 2], i, low[i]))
    return result, features, stop_boundaries, target_boundaries


def first_revisit_signals(high, low, close):
    """Return only the signal array for simple callers."""
    return first_revisit_context(high, low, close)[0]


class FairValueGapMixin:
    def _fvg_confirmation_enabled(self):
        return bool(
            getattr(self.config, "fvg_confirmation_enabled", False)
            and getattr(self, "signal_strategy_mode", "DI") == FVG_MODE
        )

    def _fvg_expected_entry_price(self, i, execution_i, direction):
        raw = getattr(self, "_pending_fvg_confirmation_price", None)
        if raw is None:
            return float(self._expected_entry_price(i, execution_i, direction))
        raw = float(raw)
        return raw * (1.0 + self.config.slippage) if direction == "LONG" else raw * (1.0 - self.config.slippage)

    def _fvg_confirmation_candle(self, execution_i):
        data = getattr(self, "intrabar_data", None)
        if data is None:
            return None
        minutes = int(getattr(self.config, "fvg_confirmation_minutes", 15))
        intrabar_minutes = int(getattr(self.config, "intrabar_timeframe_minutes", 1))
        if minutes <= 0 or intrabar_minutes <= 0 or minutes % intrabar_minutes:
            return None
        start = pd.Timestamp(self.times[execution_i])
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
        end = start + pd.Timedelta(minutes=minutes)
        expected = minutes // intrabar_minutes

        if hasattr(data, "timestamp") and not isinstance(data, pd.DataFrame):
            timestamps = pd.DatetimeIndex(pd.to_datetime(data.timestamp, utc=True))
            left = int(timestamps.searchsorted(start, side="left"))
            right = int(timestamps.searchsorted(end, side="left"))
            if right - left != expected or left >= len(timestamps):
                return None
            expected_times = pd.date_range(
                start, periods=expected, freq=f"{intrabar_minutes}min", tz="UTC"
            )
            if not timestamps[left:right].equals(expected_times):
                return None
            closes = getattr(data, "close", None)
            if closes is None:
                return None
            opening = float(data.open[left])
            closing = float(closes[right - 1])
        else:
            frame = data
            if "timestamp" not in frame or "close" not in frame:
                return None
            timestamps = pd.to_datetime(frame["timestamp"], utc=True)
            mask = (timestamps >= start) & (timestamps < end)
            window = frame.loc[mask]
            if len(window) != expected:
                return None
            actual_times = pd.DatetimeIndex(pd.to_datetime(window["timestamp"], utc=True))
            expected_times = pd.date_range(
                start, periods=expected, freq=f"{intrabar_minutes}min", tz="UTC"
            )
            if not actual_times.equals(expected_times):
                return None
            opening = float(window.iloc[0]["open"])
            closing = float(window.iloc[-1]["close"])
        if not np.isfinite(opening) or not np.isfinite(closing):
            return None
        return {
            "open": opening,
            "close": closing,
            "confirmed_at": end,
            "minutes": minutes,
        }

    def _entry_decision(self, i, active_at_candle_start=False):
        if (
            self._fvg_confirmation_enabled()
            and not self.config.enable_daily_entry_schedule
        ):
            if i + 1 >= len(self.times) or not self._should_enter(i):
                return None
            return {
                "execution_index": i + 1,
                "indicator_index": i,
                "scheduled_timestamp": pd.Timestamp(self.times[i + 1]),
                "actual_entry_timestamp": None,
                "entry_schedule_status": "FVG_INTRABAR_CONFIRMATION_PENDING",
                "fill_price_source": "FVG_INTRABAR_CONFIRMATION",
                "defer_to_next_open": True,
                "fvg_confirmation": True,
            }
        return super()._entry_decision(i, active_at_candle_start)

    def _execute_pending_next_open_entry(self, i, active_at_candle_start=False):
        decision = getattr(self, "pending_next_open_entry", None)
        if not decision or not decision.get("fvg_confirmation"):
            return super()._execute_pending_next_open_entry(i, active_at_candle_start)
        if int(decision.get("execution_index", -1)) != i:
            return
        self.pending_next_open_entry = None
        indicator_i = int(decision["indicator_index"])
        if active_at_candle_start or len(self.active_pairs) >= self.config.max_active_pairs:
            self._record_skipped_signal(indicator_i, "FVG_CONFIRMATION_ACTIVE_TRADE")
            return

        direction = self._selected_direction(indicator_i)
        candle = self._fvg_confirmation_candle(i)
        if candle is None:
            self._record_skipped_signal(indicator_i, "FVG_CONFIRMATION_DATA_UNAVAILABLE")
            return
        confirmed = (
            candle["close"] > candle["open"]
            if direction == "LONG"
            else candle["close"] < candle["open"]
            if direction == "SHORT"
            else False
        )
        if not confirmed:
            self._record_skipped_signal(indicator_i, "FVG_CONFIRMATION_DIRECTION_MISMATCH")
            return

        decision.update(
            actual_entry_timestamp=candle["confirmed_at"],
            entry_schedule_status="FVG_INTRABAR_CONFIRMED",
            fill_price=float(candle["close"]),
            fvg_confirmation_open=float(candle["open"]),
            fvg_confirmation_close=float(candle["close"]),
            fvg_confirmation_minutes=int(candle["minutes"]),
        )
        self._pending_fvg_confirmation_price = float(candle["close"])
        try:
            passed, reason = self._entry_filter_result(indicator_i, i)
            if not passed:
                self._record_skipped_signal(indicator_i, reason)
                return
            before = len(self.active_pairs)
            self._open_pair(i, passed, reason, decision)
            if len(self.active_pairs) > before:
                pair = self.active_pairs[-1]
                if pair.position.is_open:
                    self._scan_pair_exit(pair, i)
        finally:
            self._pending_fvg_confirmation_price = None

    def _configure_signal_features(self):
        super()._configure_signal_features()
        if any(
            str(rule.get("_strategy_direction_mode", "")).upper() == FVG_MODE
            or str(rule.get("indicator", "")).upper() in FVG_RULE_INDICATORS
            for profile in self.config.strategy_profiles.values()
            for rule in getattr(profile, "entry_rules", ())
        ):
            (self.fvg_first_revisit, self.fvg_rule_features,
             self.fvg_stop_boundaries, self.fvg_target_boundaries) = first_revisit_context(
                self.high, self.low, self.close, self.atr_values
            )

    def _infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                if str(rule.get("_strategy_direction_mode", "")).upper() == FVG_MODE:
                    return FVG_MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == FVG_MODE:
            return self.fvg_first_revisit[i]
        return super()._selected_direction(i)

    def _should_enter(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == FVG_MODE:
            if self._selected_direction(i) is None:
                return False
        return super()._should_enter(i)

    def _sr_stop_plan(self, i, execution_i=None):
        if getattr(self, "signal_strategy_mode", "DI") != FVG_MODE:
            return super()._sr_stop_plan(i, execution_i)
        direction = self._effective_trade_direction(i)
        if direction not in {"LONG", "SHORT"}:
            return {"passed": False, "applied": False, "reason": "FVG_NO_DIRECTION", "distance": None}
        boundary = float(self.fvg_stop_boundaries[direction][i])
        atr = float(self.atr_values[i])
        if not np.isfinite(boundary) or not np.isfinite(atr) or atr <= 0:
            return {"passed": False, "applied": False, "reason": "FVG_STOP_UNAVAILABLE", "distance": None}
        stop = boundary - FVG_STOP_BUFFER_ATR * atr if direction == "LONG" else boundary + FVG_STOP_BUFFER_ATR * atr
        if execution_i is not None and execution_i > i:
            confirmation_price = getattr(self, "_pending_fvg_confirmation_price", None)
            opening = float(confirmation_price) if confirmation_price is not None else float(self.open[execution_i])
            gap_through = opening <= stop if direction == "LONG" else opening >= stop
            if gap_through:
                return {"passed": False, "applied": False, "reason": "FVG_ENTRY_GAPPED_THROUGH_STOP", "distance": None}
        entry = self._fvg_expected_entry_price(i, execution_i, direction)
        distance = entry - stop if direction == "LONG" else stop - entry
        if not np.isfinite(distance) or distance <= 0:
            return {"passed": False, "applied": False, "reason": "FVG_STOP_ON_WRONG_SIDE", "distance": None}
        return {
            "passed": True, "applied": True, "reason": "FVG_BOX_STOP",
            "distance": distance, "distance_atr": distance / atr,
            "level_price": boundary, "boundary_price": boundary, "stop_price": stop,
            "timeframe_minutes": int(self.config.strategy_timeframe_minutes),
        }

    def _annotate_sr_stop(self, positions, plan):
        super()._annotate_sr_stop(positions, plan)
        for pos in positions:
            pos.fvg_stop_applied = plan.get("reason") == "FVG_BOX_STOP"
            pos.fvg_stop_boundary_price = plan.get("boundary_price", np.nan) if pos.fvg_stop_applied else np.nan
            pos.fvg_stop_price = plan.get("stop_price", np.nan) if pos.fvg_stop_applied else np.nan

    def _fvg_target_plan(self, i, execution_i=None):
        direction = self._effective_trade_direction(i)
        stop_plan = self._sr_stop_plan(i, execution_i)
        if direction not in {"LONG", "SHORT"} or not stop_plan.get("applied"):
            return {"passed": False, "reason": "FVG_TARGET_UNAVAILABLE"}
        level = float(self.fvg_target_boundaries[direction][i])
        atr = float(self.atr_values[i])
        entry = self._fvg_expected_entry_price(i, execution_i, direction)
        risk = float(stop_plan["distance"])
        target_buffer_atr = float(
            getattr(self.config, "fvg_target_buffer_atr", FVG_TARGET_BUFFER_ATR)
        )
        target_limit = (
            level - target_buffer_atr * atr
            if direction == "LONG"
            else level + target_buffer_atr * atr
        )
        room = target_limit - entry if direction == "LONG" else entry - target_limit
        available_r = room / risk if risk > 0 else np.nan
        profile = self._profile_context(i)[3]
        target_r = float(profile.reward_risk_ratio)
        if (
            not np.isfinite(available_r) or not np.isfinite(target_r) or target_r <= 0
            or available_r + 1e-12 < target_r
        ):
            return {
                "passed": False, "reason": "FVG_TARGET_INSUFFICIENT_ROOM",
                "target_r": target_r, "available_r": available_r,
                "level_price": level, "limit_price": target_limit,
            }
        return {
            "passed": True, "reason": "FVG_CONFIGURED_R_TARGET",
            "target_r": target_r, "available_r": available_r,
            "level_price": level, "limit_price": target_limit,
        }

    def _entry_filter_result(self, i, execution_i=None):
        passed, reason = super()._entry_filter_result(i, execution_i)
        if not passed or getattr(self, "signal_strategy_mode", "DI") != FVG_MODE:
            return passed, reason
        target = self._fvg_target_plan(i, execution_i)
        if not target["passed"]:
            return False, str(target["reason"])
        return True, reason

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="Strategy profile passed", schedule=None):
        indicator_i = schedule["indicator_index"] if schedule else i
        target = self._fvg_target_plan(indicator_i, i) if getattr(self, "signal_strategy_mode", "DI") == FVG_MODE else None
        before = len(self.active_pairs)
        result = super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        if len(self.active_pairs) > before and schedule and schedule.get("fvg_confirmation"):
            pair = self.active_pairs[-1]
            pair.fvg_confirmation_open = schedule.get("fvg_confirmation_open", np.nan)
            pair.fvg_confirmation_close = schedule.get("fvg_confirmation_close", np.nan)
            pair.fvg_confirmation_minutes = schedule.get("fvg_confirmation_minutes", np.nan)
            pair.fvg_confirmation_time = schedule.get("actual_entry_timestamp")
        if target and target.get("passed") and len(self.active_pairs) > before:
            for pos in self.active_pairs[-1].positions():
                direction = "LONG" if str(getattr(pos.side, "value", pos.side)).upper() == "LONG" else "SHORT"
                sign = 1.0 if direction == "LONG" else -1.0
                target_r = float(target["target_r"])
                pos.tp = float(pos.entry_price) + sign * target_r * float(pos.risk)
                if getattr(pos, "partial_tp_enabled", False):
                    pos.tp2_price = pos.tp
                pos.fvg_target_r = target_r
                pos.fvg_target_available_r = float(target["available_r"])
                pos.fvg_target_level_price = float(target["level_price"])
                pos.fvg_target_limit_price = float(target["limit_price"])
        return result

    def _build_result_row(self, pair, row_kind, positions):
        row = super()._build_result_row(pair, row_kind, positions)
        pos = positions[0] if positions else None
        row["fvg_stop_applied"] = bool(getattr(pos, "fvg_stop_applied", False))
        row["fvg_stop_boundary_price"] = getattr(pos, "fvg_stop_boundary_price", np.nan)
        row["fvg_stop_price"] = getattr(pos, "fvg_stop_price", np.nan)
        row["fvg_target_r"] = getattr(pos, "fvg_target_r", np.nan)
        row["fvg_target_available_r"] = getattr(pos, "fvg_target_available_r", np.nan)
        row["fvg_target_level_price"] = getattr(pos, "fvg_target_level_price", np.nan)
        row["fvg_target_limit_price"] = getattr(pos, "fvg_target_limit_price", np.nan)
        row["fvg_confirmation_open"] = getattr(pair, "fvg_confirmation_open", np.nan)
        row["fvg_confirmation_close"] = getattr(pair, "fvg_confirmation_close", np.nan)
        row["fvg_confirmation_minutes"] = getattr(pair, "fvg_confirmation_minutes", np.nan)
        row["fvg_confirmation_time"] = getattr(pair, "fvg_confirmation_time", None)
        return row

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator in FVG_RULE_INDICATORS:
            if direction not in {"LONG", "SHORT"}:
                return np.nan
            if not hasattr(self, "fvg_rule_features"):
                return np.nan
            return float(self.fvg_rule_features[direction][indicator][i])
        return super()._strategy_profile_rule_value(i, direction, profile, indicator)