"""Causal multi-timeframe S/R reaction signal and price-action evidence.

The strategy uses completed 4h S/R structure to locate opportunities, completed 1h
candles for approach/retest momentum evidence, and the completed strategy candle
(typically 15m) for the execution trigger. Higher-timeframe candle evidence is
aligned by candle *end* time, so a partially formed HTF candle is never visible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_lab.atr import atr
from crypto_strategy_lab.higher_timeframe_sr import resample_ohlc_for_sr


MTF_SR_REACTION_MODE = "MTF_SR_REACTION"

PRICE_ACTION_RULE_INDICATORS = frozenset({
    "CANDLE_BODY_ATR",
    "CANDLE_RANGE_ATR",
    "BODY_TO_RANGE_RATIO",
    "LOWER_WICK_RATIO",
    "UPPER_WICK_RATIO",
    "RANGE_CONTRACTION_RATIO",
    "BODY_CONTRACTION_RATIO",
    "CANDLE_CLOSE_LOCATION",
    "BULLISH_ENGULFING",
    "BEARISH_ENGULFING",
    "BULLISH_PIN_BAR",
    "BEARISH_PIN_BAR",
    "BULLISH_REVERSAL_TRIGGER",
    "BEARISH_REVERSAL_TRIGGER",
})

MTF_SR_DERIVED_RULE_INDICATORS = frozenset({
    "SR_APPROACH_MOMENTUM_STATE",
    "SR_ROLE_REVERSAL_STATE",
    "SR_ZONE_PENETRATION_ATR",
    "SR_ZONE_REJECTION_ATR",
    "SR_BREAKOUT_BODY_ATR",
    "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR",
})

MTF_SR_REACTION_RULE_INDICATORS = frozenset(
    (*PRICE_ACTION_RULE_INDICATORS, *MTF_SR_DERIVED_RULE_INDICATORS)
)


def mtf_sr_reaction_timeframe_plan(strategy_minutes: int) -> dict[str, int]:
    """Return the causal structure/approach hierarchy for the strategy timeframe.

    The highest prepared S/R context is 1D, so the strategy timeframe itself must
    stay below 1D. Lower-timeframe strategies retain the original 4H/1H/entry
    hierarchy, while 1H+ strategies collapse approach evidence onto Strategy TF.
    """
    strategy = int(strategy_minutes)
    if strategy <= 0:
        raise ValueError("strategy timeframe must be positive")

    if strategy < 60:
        if 60 % strategy:
            raise ValueError(
                "MTF_SR_REACTION below 1h requires a strategy timeframe that divides evenly into 1h"
            )
        return {
            "strategy_minutes": strategy,
            "structure_minutes": 240,
            "approach_minutes": 60,
        }

    if strategy < 240:
        if 240 % strategy:
            raise ValueError(
                "MTF_SR_REACTION from 1h to below 4h requires a strategy timeframe that divides evenly into 4h"
            )
        return {
            "strategy_minutes": strategy,
            "structure_minutes": 240,
            "approach_minutes": strategy,
        }

    if strategy < 1440:
        if 1440 % strategy:
            raise ValueError(
                "MTF_SR_REACTION from 4h to below 1d requires a strategy timeframe that divides evenly into 1d"
            )
        return {
            "strategy_minutes": strategy,
            "structure_minutes": 1440,
            "approach_minutes": strategy,
        }

    raise ValueError(
        "MTF_SR_REACTION requires a strategy timeframe below 1d because 1d is the highest prepared structure context"
    )

_NUMERIC_CANDLE_FIELDS = {
    "CANDLE_BODY_ATR": "body_atr",
    "CANDLE_RANGE_ATR": "range_atr",
    "BODY_TO_RANGE_RATIO": "body_to_range_ratio",
    "LOWER_WICK_RATIO": "lower_wick_ratio",
    "UPPER_WICK_RATIO": "upper_wick_ratio",
    "RANGE_CONTRACTION_RATIO": "range_contraction_ratio",
    "BODY_CONTRACTION_RATIO": "body_contraction_ratio",
    "CANDLE_CLOSE_LOCATION": "close_location",
}
_BOOLEAN_CANDLE_FIELDS = {
    "BULLISH_ENGULFING": "bullish_engulfing",
    "BEARISH_ENGULFING": "bearish_engulfing",
    "BULLISH_PIN_BAR": "bullish_pin_bar",
    "BEARISH_PIN_BAR": "bearish_pin_bar",
    "BULLISH_REVERSAL_TRIGGER": "bullish_reversal_trigger",
    "BEARISH_REVERSAL_TRIGGER": "bearish_reversal_trigger",
}
_SR_CONTEXTS = {
    0: ("support_resistance_strategy", "sr_strategy"),
    60: ("support_resistance_1h", "sr_1h"),
    240: ("support_resistance_4h", "sr_4h"),
    1440: ("support_resistance_1d", "sr_1d"),
}
_ROLE_STATES = (
    "NONE",
    "BREAKOUT_CONFIRMED",
    "RETEST_APPROACHING",
    "RETESTING_FROM_BREAK_SIDE",
    "RETEST_HELD",
    "RETEST_FAILED",
)


def _safe_divide(numerator, denominator):
    numerator = np.asarray(numerator, dtype=float)
    denominator = np.asarray(denominator, dtype=float)
    return np.divide(
        numerator,
        denominator,
        out=np.full(len(numerator), np.nan, dtype=float),
        where=np.isfinite(denominator) & (denominator != 0),
    )


def candle_evidence_arrays(
    open_prices,
    high_prices,
    low_prices,
    close_prices,
    atr_values,
) -> dict[str, np.ndarray]:
    """Return causal one-candle / previous-candle evidence arrays."""
    open_prices = np.asarray(open_prices, dtype=float)
    high_prices = np.asarray(high_prices, dtype=float)
    low_prices = np.asarray(low_prices, dtype=float)
    close_prices = np.asarray(close_prices, dtype=float)
    atr_values = np.asarray(atr_values, dtype=float)

    candle_range = high_prices - low_prices
    body = np.abs(close_prices - open_prices)
    upper_wick = high_prices - np.maximum(open_prices, close_prices)
    lower_wick = np.minimum(open_prices, close_prices) - low_prices

    body_atr = _safe_divide(body, atr_values)
    range_atr = _safe_divide(candle_range, atr_values)
    body_to_range = _safe_divide(body, candle_range)
    upper_wick_ratio = _safe_divide(upper_wick, candle_range)
    lower_wick_ratio = _safe_divide(lower_wick, candle_range)
    close_location = _safe_divide(close_prices - low_prices, candle_range)

    previous_range = np.roll(candle_range, 1)
    previous_body = np.roll(body, 1)
    previous_open = np.roll(open_prices, 1)
    previous_close = np.roll(close_prices, 1)
    previous_range[0] = np.nan
    previous_body[0] = np.nan
    previous_open[0] = np.nan
    previous_close[0] = np.nan

    range_contraction = _safe_divide(candle_range, previous_range)
    body_contraction = _safe_divide(body, previous_body)

    current_bull = close_prices > open_prices
    current_bear = close_prices < open_prices
    previous_bull = previous_close > previous_open
    previous_bear = previous_close < previous_open

    bullish_engulfing = (
        current_bull
        & previous_bear
        & np.isfinite(previous_open)
        & (open_prices <= previous_close)
        & (close_prices >= previous_open)
    )
    bearish_engulfing = (
        current_bear
        & previous_bull
        & np.isfinite(previous_open)
        & (open_prices >= previous_close)
        & (close_prices <= previous_open)
    )

    # Deliberately simple, researchable pin-bar definition. The body must be
    # compact, the rejection wick must dominate the range, and the close must
    # finish back in the rejection direction.
    bullish_pin = (
        np.isfinite(body_to_range)
        & (body_to_range <= 0.35)
        & (lower_wick_ratio >= 0.50)
        & (close_location >= 0.60)
    )
    bearish_pin = (
        np.isfinite(body_to_range)
        & (body_to_range <= 0.35)
        & (upper_wick_ratio >= 0.50)
        & (close_location <= 0.40)
    )

    return {
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "atr": atr_values,
        "body_atr": body_atr,
        "range_atr": range_atr,
        "body_to_range_ratio": body_to_range,
        "lower_wick_ratio": lower_wick_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "range_contraction_ratio": range_contraction,
        "body_contraction_ratio": body_contraction,
        "close_location": close_location,
        "bullish_engulfing": bullish_engulfing.astype(bool),
        "bearish_engulfing": bearish_engulfing.astype(bool),
        "bullish_pin_bar": bullish_pin.astype(bool),
        "bearish_pin_bar": bearish_pin.astype(bool),
        "bullish_reversal_trigger": (bullish_engulfing | bullish_pin).astype(bool),
        "bearish_reversal_trigger": (bearish_engulfing | bearish_pin).astype(bool),
    }


class MtfSrReactionMixin:
    """Add MTF S/R reaction direction selection and reusable candle evidence."""

    mtf_sr_role_break_tolerance_atr = 0.25
    mtf_sr_retest_near_atr = 1.0
    mtf_sr_retest_max_target_bars = 12

    def _mtf_sr_features_needed(self) -> bool:
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                mode = str(rule.get("_strategy_direction_mode", "")).upper()
                if mode == MTF_SR_REACTION_MODE:
                    return True
                if str(rule.get("indicator", "")).upper() in MTF_SR_REACTION_RULE_INDICATORS:
                    return True
        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_mtf_sr_reaction_context()

    def _configure_signal_features(self):
        super()._configure_signal_features()
        self.mtf_price_action: dict[int, dict[str, np.ndarray]] = {}
        self.mtf_role_reversal: dict[tuple[int, str], np.ndarray] = {}
        if not self._mtf_sr_features_needed():
            return

        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        mode_enabled = any(
            str(rule.get("_strategy_direction_mode", "")).upper() == MTF_SR_REACTION_MODE
            for profile in self.config.strategy_profiles.values()
            for rule in getattr(profile, "entry_rules", ())
        )
        if mode_enabled:
            mtf_sr_reaction_timeframe_plan(strategy_minutes)
        strategy = candle_evidence_arrays(
            self.open, self.high, self.low, self.close, self.atr_values
        )
        self.mtf_price_action[strategy_minutes] = strategy

        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(self.times, utc=True),
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
            }
        )
        decision_times = (
            pd.to_datetime(self.times, utc=True)
            + pd.Timedelta(minutes=strategy_minutes)
        ).to_numpy(dtype="datetime64[ns]")

        for target_minutes in (60, 240, 1440):
            if target_minutes <= strategy_minutes or target_minutes % strategy_minutes:
                continue
            htf = resample_ohlc_for_sr(frame, strategy_minutes, target_minutes)
            if htf.empty:
                continue
            htf_atr = atr(
                htf["high"].to_numpy(float),
                htf["low"].to_numpy(float),
                htf["close"].to_numpy(float),
                int(self.config.atr_period),
            )
            raw = candle_evidence_arrays(
                htf["open"].to_numpy(float),
                htf["high"].to_numpy(float),
                htf["low"].to_numpy(float),
                htf["close"].to_numpy(float),
                htf_atr,
            )
            end_times = pd.to_datetime(htf["end_time"], utc=True).to_numpy(
                dtype="datetime64[ns]"
            )
            indices = np.searchsorted(end_times, decision_times, side="right") - 1
            aligned: dict[str, np.ndarray] = {}
            valid = indices >= 0
            for name, values in raw.items():
                values = np.asarray(values)
                if values.dtype == bool:
                    # Missing completed HTF candles are unavailable evidence, not False.
                    target = np.full(len(self.close), None, dtype=object)
                else:
                    target = np.full(len(self.close), np.nan, dtype=float)
                target[valid] = values[indices[valid]]
                aligned[name] = target
            self.mtf_price_action[target_minutes] = aligned

    def _infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                mode = str(rule.get("_strategy_direction_mode", "")).upper()
                if mode == MTF_SR_REACTION_MODE:
                    return MTF_SR_REACTION_MODE
        return super()._infer_signal_strategy_mode()

    def _resolve_mtf_minutes(self, timeframe_minutes) -> int:
        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        try:
            requested = int(timeframe_minutes or 0)
        except (TypeError, ValueError, OverflowError):
            requested = 0
        return strategy_minutes if requested == 0 else requested

    def _mtf_sr_raw(self, i: int, direction: str, field: str, timeframe_minutes: int):
        """Read one independently prepared causal S/R field."""
        if direction not in {"LONG", "SHORT"}:
            return None
        requested = self._resolve_mtf_minutes(timeframe_minutes)
        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        context_key = 0 if requested == strategy_minutes else requested
        block = _SR_CONTEXTS.get(context_key)
        if block is None or not hasattr(self, "_prepared_research_raw_value"):
            return None
        feature_name, prefix = block
        raw = self._prepared_research_raw_value(
            i, feature_name, f"{prefix}_{direction.lower()}_{field}"
        )
        if raw is None and context_key == 0 and hasattr(self, "_prepared_sr_context"):
            context = self._prepared_sr_context(i, direction)
            return getattr(context, field, None) if context is not None else None
        return raw

    @staticmethod
    def _finite(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    @staticmethod
    def _text(value) -> str:
        if value is None or value is pd.NA:
            return ""
        try:
            if bool(pd.isna(value)):
                return ""
        except (TypeError, ValueError):
            pass
        return str(getattr(value, "value", value)).strip().upper()

    @staticmethod
    def _truth(value) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if value is None or value is pd.NA:
            return False
        text = str(getattr(value, "value", value)).strip().upper()
        return text in {"TRUE", "1", "YES"}

    def _approach_momentum_state(
        self, i: int, direction: str, timeframe_minutes: int
    ) -> str:
        requested = self._resolve_mtf_minutes(timeframe_minutes)
        values = self.mtf_price_action.get(requested)
        if values is None or i < 0 or i >= len(self.close):
            return "UNKNOWN"
        range_ratio = self._finite(values["range_contraction_ratio"][i])
        body_ratio = self._finite(values["body_contraction_ratio"][i])
        body_to_range = self._finite(values["body_to_range_ratio"][i])
        lower_wick = self._finite(values["lower_wick_ratio"][i])
        upper_wick = self._finite(values["upper_wick_ratio"][i])
        open_ = self._finite(values["open"][i])
        close = self._finite(values["close"][i])
        if None in {range_ratio, body_ratio, body_to_range, lower_wick, upper_wick, open_, close}:
            return "UNKNOWN"

        rejection_wick = lower_wick if direction == "LONG" else upper_wick
        adverse_impulse = (
            close < open_ if direction == "LONG" else close > open_
        )
        if rejection_wick >= 0.35 or (range_ratio <= 0.85 and body_ratio <= 0.85):
            return "DECELERATING"
        if adverse_impulse and body_to_range >= 0.60 and range_ratio >= 1.15:
            return "IMPULSIVE"
        return "NEUTRAL"

    def _configure_mtf_sr_reaction_context(self) -> None:
        self.mtf_role_reversal = getattr(self, "mtf_role_reversal", {})
        if not self._mtf_sr_features_needed():
            return
        if not bool(getattr(self.config, "enable_support_resistance_analysis", False)):
            return
        if not hasattr(self, "research_features"):
            return

        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        for requested in sorted(self.mtf_price_action):
            context_key = 0 if requested == strategy_minutes else requested
            if context_key not in _SR_CONTEXTS:
                continue
            max_age = max(
                1,
                int(
                    self.mtf_sr_retest_max_target_bars
                    * requested
                    / strategy_minutes
                ),
            )
            for direction in ("LONG", "SHORT"):
                states = np.full(len(self.close), "NONE", dtype=object)
                active_low = active_high = None
                active_age = 0
                previous_structure_state = ""
                last_zone_low = last_zone_high = None

                structure_field = (
                    "resistance_state" if direction == "LONG" else "support_state"
                )
                zone_low_field = (
                    "resistance_zone_low" if direction == "LONG" else "support_zone_low"
                )
                zone_high_field = (
                    "resistance_zone_high" if direction == "LONG" else "support_zone_high"
                )
                broken_name = (
                    "RESISTANCE_BROKEN" if direction == "LONG" else "SUPPORT_BROKEN"
                )

                for i in range(len(self.close)):
                    structure_state = self._text(
                        self._mtf_sr_raw(i, direction, structure_field, requested)
                    )
                    zone_low = self._finite(
                        self._mtf_sr_raw(i, direction, zone_low_field, requested)
                    )
                    zone_high = self._finite(
                        self._mtf_sr_raw(i, direction, zone_high_field, requested)
                    )
                    if zone_low is not None and zone_high is not None:
                        last_zone_low, last_zone_high = zone_low, zone_high

                    just_broke = (
                        structure_state == broken_name
                        and previous_structure_state != broken_name
                        and last_zone_low is not None
                        and last_zone_high is not None
                    )
                    if just_broke:
                        active_low, active_high = last_zone_low, last_zone_high
                        active_age = 0
                        states[i] = "BREAKOUT_CONFIRMED"

                    if active_low is not None and active_high is not None:
                        active_age += 1
                        atr_value = self._finite(self.atr_values[i])
                        close = self._finite(self.close[i])
                        low = self._finite(self.low[i])
                        high = self._finite(self.high[i])
                        if (
                            atr_value is None
                            or atr_value <= 0
                            or close is None
                            or low is None
                            or high is None
                        ):
                            states[i] = "NONE"
                        elif active_age > max_age:
                            active_low = active_high = None
                            states[i] = "NONE"
                        elif direction == "LONG":
                            failure = active_low - self.mtf_sr_role_break_tolerance_atr * atr_value
                            if close < failure:
                                states[i] = "RETEST_FAILED"
                                active_low = active_high = None
                            elif low <= active_high and close > active_high:
                                states[i] = "RETEST_HELD"
                            elif low <= active_high and close >= active_low:
                                states[i] = "RETESTING_FROM_BREAK_SIDE"
                            elif close > active_high and (close - active_high) / atr_value <= self.mtf_sr_retest_near_atr:
                                states[i] = "RETEST_APPROACHING"
                            elif not just_broke:
                                states[i] = "BREAKOUT_CONFIRMED"
                        else:
                            failure = active_high + self.mtf_sr_role_break_tolerance_atr * atr_value
                            if close > failure:
                                states[i] = "RETEST_FAILED"
                                active_low = active_high = None
                            elif high >= active_low and close < active_low:
                                states[i] = "RETEST_HELD"
                            elif high >= active_low and close <= active_high:
                                states[i] = "RETESTING_FROM_BREAK_SIDE"
                            elif close < active_low and (active_low - close) / atr_value <= self.mtf_sr_retest_near_atr:
                                states[i] = "RETEST_APPROACHING"
                            elif not just_broke:
                                states[i] = "BREAKOUT_CONFIRMED"

                    previous_structure_state = structure_state

                self.mtf_role_reversal[(requested, direction)] = states

    def _mtf_price_action_value(
        self,
        i: int,
        direction: str,
        indicator: str,
        timeframe_minutes=0,
    ):
        requested = self._resolve_mtf_minutes(timeframe_minutes)
        values = self.mtf_price_action.get(requested)
        if values is None or i < 0 or i >= len(self.close):
            return None
        indicator = str(indicator).upper()

        if indicator in _NUMERIC_CANDLE_FIELDS:
            return values[_NUMERIC_CANDLE_FIELDS[indicator]][i]
        if indicator in _BOOLEAN_CANDLE_FIELDS:
            raw = values[_BOOLEAN_CANDLE_FIELDS[indicator]][i]
            if raw is None or raw is pd.NA:
                return None
            try:
                if bool(pd.isna(raw)):
                    return None
            except (TypeError, ValueError):
                pass
            return bool(raw)
        if indicator == "SR_APPROACH_MOMENTUM_STATE":
            return self._approach_momentum_state(i, direction, requested)
        if indicator == "SR_ROLE_REVERSAL_STATE":
            role = self.mtf_role_reversal.get((requested, direction))
            return role[i] if role is not None else "NONE"

        atr_value = self._finite(values["atr"][i])
        open_ = self._finite(values["open"][i])
        high = self._finite(values["high"][i])
        low = self._finite(values["low"][i])
        close = self._finite(values["close"][i])
        if None in {atr_value, open_, high, low, close} or atr_value <= 0:
            return np.nan

        if direction == "LONG":
            favorable_low = self._finite(
                self._mtf_sr_raw(i, direction, "support_zone_low", requested)
            )
            favorable_high = self._finite(
                self._mtf_sr_raw(i, direction, "support_zone_high", requested)
            )
            opposing_boundary = self._finite(
                self._mtf_sr_raw(i, direction, "resistance_zone_high", requested)
            )
            if indicator == "SR_ZONE_PENETRATION_ATR":
                if favorable_low is None or favorable_high is None:
                    return np.nan
                return max(0.0, favorable_high - low) / atr_value
            if indicator == "SR_ZONE_REJECTION_ATR":
                if favorable_high is None or low > favorable_high:
                    return 0.0
                return max(0.0, close - low) / atr_value
            beyond = (
                close - opposing_boundary
                if opposing_boundary is not None
                else np.nan
            )
        else:
            favorable_low = self._finite(
                self._mtf_sr_raw(i, direction, "resistance_zone_low", requested)
            )
            favorable_high = self._finite(
                self._mtf_sr_raw(i, direction, "resistance_zone_high", requested)
            )
            opposing_boundary = self._finite(
                self._mtf_sr_raw(i, direction, "support_zone_low", requested)
            )
            if indicator == "SR_ZONE_PENETRATION_ATR":
                if favorable_low is None or favorable_high is None:
                    return np.nan
                return max(0.0, high - favorable_low) / atr_value
            if indicator == "SR_ZONE_REJECTION_ATR":
                if favorable_low is None or high < favorable_low:
                    return 0.0
                return max(0.0, high - close) / atr_value
            beyond = (
                opposing_boundary - close
                if opposing_boundary is not None
                else np.nan
            )

        if indicator == "SR_BREAKOUT_BODY_ATR":
            if not np.isfinite(beyond) or beyond <= 0:
                return 0.0
            return abs(close - open_) / atr_value
        if indicator == "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR":
            if not np.isfinite(beyond):
                return np.nan
            return max(0.0, beyond) / atr_value
        raise KeyError(indicator)

    def _mtf_sr_signal_direction(self, i: int):
        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        plan = mtf_sr_reaction_timeframe_plan(strategy_minutes)
        structure_minutes = int(plan["structure_minutes"])
        if (
            structure_minutes not in self.mtf_price_action
            or strategy_minutes not in self.mtf_price_action
        ):
            return None

        bullish = bool(
            self._mtf_price_action_value(
                i, "LONG", "BULLISH_REVERSAL_TRIGGER", strategy_minutes
            )
        )
        bearish = bool(
            self._mtf_price_action_value(
                i, "SHORT", "BEARISH_REVERSAL_TRIGGER", strategy_minutes
            )
        )
        long_state = self._text(
            self._mtf_sr_raw(i, "LONG", "support_state", structure_minutes)
        )
        short_state = self._text(
            self._mtf_sr_raw(i, "SHORT", "resistance_state", structure_minutes)
        )
        long_location = (
            long_state in {"SUPPORT_TESTING", "SUPPORT_HELD"}
            or self._truth(
                self._mtf_sr_raw(i, "LONG", "near_support", structure_minutes)
            )
            or self._truth(
                self._mtf_sr_raw(
                    i, "LONG", "inside_support_zone", structure_minutes
                )
            )
        )
        short_location = (
            short_state in {"RESISTANCE_TESTING", "RESISTANCE_HELD"}
            or self._truth(
                self._mtf_sr_raw(i, "SHORT", "near_resistance", structure_minutes)
            )
            or self._truth(
                self._mtf_sr_raw(
                    i, "SHORT", "inside_resistance_zone", structure_minutes
                )
            )
        )
        long_role = self._text(
            self._mtf_price_action_value(
                i, "LONG", "SR_ROLE_REVERSAL_STATE", structure_minutes
            )
        )
        short_role = self._text(
            self._mtf_price_action_value(
                i, "SHORT", "SR_ROLE_REVERSAL_STATE", structure_minutes
            )
        )
        valid_retests = {"RETESTING_FROM_BREAK_SIDE", "RETEST_HELD"}

        long_candidate = bullish and (
            long_location or long_role in valid_retests
        )
        short_candidate = bearish and (
            short_location or short_role in valid_retests
        )
        if long_candidate == short_candidate:
            return None
        return "LONG" if long_candidate else "SHORT"

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == MTF_SR_REACTION_MODE:
            return self._mtf_sr_signal_direction(i)
        return super()._selected_direction(i)

    def _should_enter(self, i):
        if getattr(self, "signal_strategy_mode", "DI") == MTF_SR_REACTION_MODE:
            if self._selected_direction(i) is None:
                return False
        return super()._should_enter(i)

    @staticmethod
    def _mtf_label(minutes: int, strategy_minutes: int) -> str:
        if minutes == strategy_minutes:
            return "strategy"
        if minutes == 1440:
            return "1d"
        if minutes % 60 == 0:
            return f"{minutes // 60}h"
        return f"{minutes}m"

    def _build_result_row(self, p, row_kind, positions):
        row = super()._build_result_row(p, row_kind, positions)
        if not self.mtf_price_action:
            return row
        try:
            stamp = pd.Timestamp(p.strategy_candle_open_time)
            if stamp.tzinfo is not None:
                stamp = stamp.tz_convert("UTC").tz_localize(None)
            i = int(
                np.searchsorted(
                    self.times,
                    np.datetime64(stamp.to_datetime64(), "ns"),
                    side="right",
                )
                - 1
            )
        except Exception:
            return row
        if i < 0 or i >= len(self.close):
            return row

        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        for minutes, values in self.mtf_price_action.items():
            label = self._mtf_label(minutes, strategy_minutes)
            for indicator, field in _NUMERIC_CANDLE_FIELDS.items():
                row[f"mtf_{label}_{field}"] = values[field][i]
            for indicator, field in _BOOLEAN_CANDLE_FIELDS.items():
                raw = values[field][i]
                row[f"mtf_{label}_{field}"] = (
                    np.nan if raw is None or raw is pd.NA else bool(raw)
                )
            for direction in ("LONG", "SHORT"):
                prefix = f"mtf_{label}_{direction.lower()}"
                row[f"{prefix}_sr_approach_momentum_state"] = (
                    self._approach_momentum_state(i, direction, minutes)
                )
                role = self.mtf_role_reversal.get((minutes, direction))
                row[f"{prefix}_sr_role_reversal_state"] = (
                    role[i] if role is not None else "NONE"
                )
                for indicator, field in (
                    ("SR_ZONE_PENETRATION_ATR", "sr_zone_penetration_atr"),
                    ("SR_ZONE_REJECTION_ATR", "sr_zone_rejection_atr"),
                    ("SR_BREAKOUT_BODY_ATR", "sr_breakout_body_atr"),
                    (
                        "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR",
                        "sr_breakout_close_beyond_zone_atr",
                    ),
                ):
                    row[f"{prefix}_{field}"] = self._mtf_price_action_value(
                        i, direction, indicator, minutes
                    )
        return row
