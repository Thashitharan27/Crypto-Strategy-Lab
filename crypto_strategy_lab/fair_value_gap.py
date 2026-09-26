"""Causal three-candle fair value gap first-revisit signal."""
from __future__ import annotations

import numpy as np


FVG_MODE = "FAIR_VALUE_GAP"
FVG_RULE_INDICATORS = frozenset({"FVG_GAP_SIZE_ATR", "FVG_AGE_BARS", "FVG_REVISIT_DEPTH_PCT"})


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
        for bottom, top, formed in bullish:
            if low[i] <= top and high[i] >= bottom:
                if np.isnan(features["LONG"]["FVG_AGE_BARS"][i]):
                    features["LONG"]["FVG_AGE_BARS"][i] = i - formed
                    features["LONG"]["FVG_REVISIT_DEPTH_PCT"][i] = min(
                        1.0, max(0.0, (top - low[i]) / (top - bottom))
                    )
                    if np.isfinite(atr[formed]) and atr[formed] > 0:
                        features["LONG"]["FVG_GAP_SIZE_ATR"][i] = (top - bottom) / atr[formed]
                long_touch |= close[i] > top
            else:
                next_bullish.append((bottom, top, formed))
        next_bearish = []
        for bottom, top, formed in bearish:
            if high[i] >= bottom and low[i] <= top:
                if np.isnan(features["SHORT"]["FVG_AGE_BARS"][i]):
                    features["SHORT"]["FVG_AGE_BARS"][i] = i - formed
                    features["SHORT"]["FVG_REVISIT_DEPTH_PCT"][i] = min(
                        1.0, max(0.0, (high[i] - bottom) / (top - bottom))
                    )
                    if np.isfinite(atr[formed]) and atr[formed] > 0:
                        features["SHORT"]["FVG_GAP_SIZE_ATR"][i] = (top - bottom) / atr[formed]
                short_touch |= close[i] < bottom
            else:
                next_bearish.append((bottom, top, formed))
        bullish, bearish = next_bullish, next_bearish
        if long_touch != short_touch:
            result[i] = "LONG" if long_touch else "SHORT"
        if i >= 2 and np.isfinite(high[i - 2]) and np.isfinite(low[i - 2]):
            if low[i] > high[i - 2]:
                bullish.append((high[i - 2], low[i], i))
            if high[i] < low[i - 2]:
                bearish.append((high[i], low[i - 2], i))
    return result, features


def first_revisit_signals(high, low, close):
    """Return only the signal array for simple callers."""
    return first_revisit_context(high, low, close)[0]


class FairValueGapMixin:
    def _configure_signal_features(self):
        super()._configure_signal_features()
        if any(
            str(rule.get("_strategy_direction_mode", "")).upper() == FVG_MODE
            or str(rule.get("indicator", "")).upper() in FVG_RULE_INDICATORS
            for profile in self.config.strategy_profiles.values()
            for rule in getattr(profile, "entry_rules", ())
        ):
            self.fvg_first_revisit, self.fvg_rule_features = first_revisit_context(
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

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator in FVG_RULE_INDICATORS:
            if direction not in {"LONG", "SHORT"}:
                return np.nan
            if not hasattr(self, "fvg_rule_features"):
                return np.nan
            return float(self.fvg_rule_features[direction][indicator][i])
        return super()._strategy_profile_rule_value(i, direction, profile, indicator)
