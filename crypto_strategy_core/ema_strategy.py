"""Causal EMA 20/100 strategy decisions shared by research and live runtimes."""
from __future__ import annotations

import math
from collections.abc import Sequence

EMA_CROSS_PLAN_SIDES = {
    "EMA_20_100_CROSS": frozenset({"LONG"}),
    "EMA_20_100_CROSS_SHORT": frozenset({"SHORT"}),
    "EMA_20_100_CROSS_BOTH": frozenset({"LONG", "SHORT"}),
}


def ema_20_100_cross(
    index: int,
    ema_20: Sequence[float],
    ema_100: Sequence[float],
    *,
    upwards: bool,
) -> bool:
    """Compare two completed EMA observations; no lookahead or open candle."""
    if index < 100 or index >= len(ema_20) or index >= len(ema_100):
        return False
    values = (
        float(ema_20[index - 1]), float(ema_20[index]),
        float(ema_100[index - 1]), float(ema_100[index]),
    )
    if not all(math.isfinite(value) for value in values):
        return False
    previous_20, current_20, previous_100, current_100 = values
    if upwards:
        return previous_20 <= previous_100 and current_20 > current_100
    return previous_20 >= previous_100 and current_20 < current_100


def ema_20_100_entry_direction(
    index: int,
    ema_20: Sequence[float],
    ema_100: Sequence[float],
    plan: str,
) -> str | None:
    """Return the permitted cross direction for a completed signal candle."""
    permitted = EMA_CROSS_PLAN_SIDES.get(plan)
    if permitted is None:
        return None
    if "LONG" in permitted and ema_20_100_cross(index, ema_20, ema_100, upwards=True):
        return "LONG"
    if "SHORT" in permitted and ema_20_100_cross(index, ema_20, ema_100, upwards=False):
        return "SHORT"
    return None
