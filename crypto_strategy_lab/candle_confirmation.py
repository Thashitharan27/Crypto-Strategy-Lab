"""Reusable, causal directional-candle confirmation across signal strategies."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CandleConfirmationPlan:
    """Signal-independent candle confirmation configuration (ANY selected pattern)."""

    enabled: bool = False
    strong_close: bool = True
    engulfing: bool = True
    wick_rejection: bool = True
    star: bool = True

    @classmethod
    def from_config(cls, config, prefix: str):
        return cls(
            enabled=bool(getattr(config, f"{prefix}_candle_confirmation_enabled", False)),
            strong_close=bool(getattr(config, f"{prefix}_candle_strong_close", True)),
            engulfing=bool(getattr(config, f"{prefix}_candle_engulfing", True)),
            wick_rejection=bool(getattr(config, f"{prefix}_candle_wick_rejection", True)),
            star=bool(getattr(config, f"{prefix}_candle_star", True)),
        )


def evaluate_candle_confirmation(candles, i, direction, plan: CandleConfirmationPlan, *, reason_prefix="SHARED"):
    """Evaluate a reusable plan against closed bars, independently of the signal."""

    prefix = reason_prefix.upper()
    if not plan.enabled:
        return True, f"{prefix}_CANDLE_CONFIRMATION_DISABLED"
    if not 0 <= i < len(candles.close):
        return False, f"{prefix}_CANDLE_CONFIRMATION_UNAVAILABLE"
    if direction not in {"LONG", "SHORT"}:
        return False, f"{prefix}_CANDLE_CONFIRMATION_DIRECTION_UNAVAILABLE"

    def bar(j):
        if j < 0:
            return None
        o, h, l, c = (float(a[j]) for a in (candles.open, candles.high, candles.low, candles.close))
        if not all(np.isfinite(v) for v in (o, h, l, c)) or h <= l or h < max(o, c) or l > min(o, c):
            return None
        return o, h, l, c

    current = bar(i)
    if current is None:
        return False, f"{prefix}_CANDLE_CONFIRMATION_UNAVAILABLE"
    o, h, l, c = current
    span = h - l
    body = abs(c - o)
    bullish = direction == "LONG"
    matches = []

    if plan.strong_close:
        if (c > o and c >= h - span / 3 if bullish else c < o and c <= l + span / 3):
            matches.append("STRONG_CLOSE")

    previous = bar(i - 1) if i >= 1 else None
    if previous is not None:
        po, ph, pl, pc = previous
        if plan.engulfing:
            if (pc < po and c > o and o <= pc and c >= po if bullish
                else pc > po and c < o and o >= pc and c <= po):
                matches.append("ENGULFING")

        if plan.wick_rejection:
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)
            # Require directional close and a rejection wick >= 2x body.
            if (c > o and lower_wick >= 2 * body and upper_wick <= body
                if bullish else c < o and upper_wick >= 2 * body and lower_wick <= body):
                matches.append("WICK_REJECTION")

    # A wick-rejection candle can be the first bar in the series.
    elif plan.wick_rejection:
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        if (c > o and lower_wick >= 2 * body and upper_wick <= body
            if bullish else c < o and upper_wick >= 2 * body and lower_wick <= body):
            matches.append("WICK_REJECTION")

    older = bar(i - 2) if i >= 2 else None
    if plan.star and older and previous:
        ao, ah, al, ac = older
        bo, bh, bl, bc = previous
        first_body = abs(ac - ao)
        middle_body = abs(bc - bo)
        midpoint = (ao + ac) / 2
        # Crypto trades 24/7: don't require gaps between candle bodies.
        # Require initial directional displacement, small middle body,
        # and a third candle recovering past the first body's midpoint.
        if first_body > 0 and middle_body <= 0.5 * first_body:
            if (ac < ao and c > o and c > midpoint and c > max(bo, bc)
                if bullish else ac > ao and c < o and c < midpoint and c < min(bo, bc)):
                matches.append("STAR")

    if matches:
        return True, f"{prefix}_CANDLE_{matches[0]}_CONFIRMED"
    return False, f"{prefix}_CANDLE_NO_SELECTED_PATTERN"


def candle_confirmation_check(self, i, direction, prefix):
    """Legacy strategy adapter backed by the shared, signal-independent plan."""
    plan = CandleConfirmationPlan.from_config(self.config, prefix)
    return evaluate_candle_confirmation(
        self, i, direction, plan, reason_prefix=prefix,
    )
