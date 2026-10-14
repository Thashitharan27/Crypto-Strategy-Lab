"""Signal-independent stop and target planning.

This module describes requested prices; the simulator owns fill timing,
intrabar event ordering, fees and position sizing.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class StopMethod(str, Enum):
    FIXED_R = "FIXED_R"
    ATR = "ATR"
    STRUCTURE = "STRUCTURE"


class TargetMethod(str, Enum):
    FIXED_R = "FIXED_R"
    STRUCTURE = "STRUCTURE"


@dataclass(frozen=True)
class ExitPlan:
    stop_method: StopMethod = StopMethod.ATR
    target_method: TargetMethod = TargetMethod.FIXED_R
    stop_atr_multiple: float = 1.0
    reward_risk_multiple: float = 2.0

    def __post_init__(self):
        if not isfinite(self.stop_atr_multiple) or self.stop_atr_multiple <= 0:
            raise ValueError("stop_atr_multiple must be positive and finite")
        if not isfinite(self.reward_risk_multiple) or self.reward_risk_multiple <= 0:
            raise ValueError("reward_risk_multiple must be positive and finite")


@dataclass(frozen=True)
class ExitLevels:
    stop: float
    target: float
    risk_per_unit: float


def resolve_exit_levels(
    *,
    direction: str,
    entry_price: float,
    plan: ExitPlan,
    atr: float | None = None,
    reference_risk: float | None = None,
    structure_stop: float | None = None,
    structure_target: float | None = None,
) -> ExitLevels:
    """Calculate requested levels from known inputs, without reading future bars."""
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if not isfinite(entry_price) or entry_price <= 0:
        raise ValueError("entry_price must be positive and finite")
    sign = 1 if direction == "LONG" else -1
    if plan.stop_method == StopMethod.ATR:
        if atr is None or not isfinite(atr) or atr <= 0:
            raise ValueError("ATR stop requires positive finite atr")
        risk = atr * plan.stop_atr_multiple
        stop = entry_price - sign * risk
    elif plan.stop_method == StopMethod.FIXED_R:
        if reference_risk is None or not isfinite(reference_risk) or reference_risk <= 0:
            raise ValueError("FIXED_R stop requires positive finite reference_risk")
        risk = reference_risk
        stop = entry_price - sign * risk
    elif plan.stop_method == StopMethod.STRUCTURE:
        if structure_stop is None or not isfinite(structure_stop):
            raise ValueError("STRUCTURE stop requires a finite level")
        stop = structure_stop
        risk = sign * (entry_price - stop)
    else:
        raise ValueError("unsupported stop method")
    if not isfinite(stop) or stop <= 0 or risk <= 0:
        raise ValueError("stop must be positive and on the loss side of entry")
    if plan.target_method == TargetMethod.FIXED_R:
        target = entry_price + sign * risk * plan.reward_risk_multiple
    elif plan.target_method == TargetMethod.STRUCTURE:
        if structure_target is None or not isfinite(structure_target):
            raise ValueError("STRUCTURE target requires a finite level")
        target = structure_target
    else:
        raise ValueError("unsupported target method")
    if not isfinite(target) or target <= 0 or sign * (target - entry_price) <= 0:
        raise ValueError("target must be positive and on the profit side of entry")
    return ExitLevels(stop=stop, target=target, risk_per_unit=risk)
