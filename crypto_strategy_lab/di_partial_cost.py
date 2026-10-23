"""DI partial-profit preset and the minimum price risk needed to cover costs."""
from __future__ import annotations

import math


def validate_di_partial(profile):
    if not profile.di_partial_1r_enabled:
        return
    if not math.isfinite(profile.di_partial_1r_close_pct) or not 0 < profile.di_partial_1r_close_pct < 100:
        raise ValueError("DI 1R partial percentage must be between 0 and 100")
    if not math.isfinite(profile.reward_risk_ratio) or profile.reward_risk_ratio <= 1:
        raise ValueError("DI 1R partial requires a final target above 1R")
    if any((profile.partial_profit_enabled, profile.partial_stop_enabled,
            profile.break_even_enabled, profile.trailing_enabled,
            profile.r_step_trailing_enabled, profile.atr_checkpoint_tp_extension_enabled)):
        raise ValueError("DI 1R partial owns partial-profit and protection settings; disable other partial/BE/trailing modes")
    if profile.di_partial_cost_atr_enabled and profile.position_sizing_stop_override_enabled:
        raise ValueError("DI cost-cover ATR sizing requires sizing from the actual adjusted stop")


def minimum_cost_cover_distance(entry, sign, fraction, entry_fee, exit_fee, slippage):
    """Solve partial-at-1R + remainder-at-entry net P&L = 0 per original unit.

    Entry is the simulator's actual (already slipped) fill. Both the partial
    market exit and hypothetical BE stop receive adverse exit slippage.
    Future funding, exchange tick sizes and stop gaps are outside this estimate.
    """
    values = (entry, fraction, entry_fee, exit_fee, slippage)
    if not all(math.isfinite(float(v)) for v in values) or entry <= 0 or not 0 < fraction < 1 or sign not in (-1, 1):
        raise ValueError("Invalid DI cost-cover inputs")
    if min(entry_fee, exit_fee, slippage) < 0 or max(entry_fee, exit_fee, slippage) >= 1:
        raise ValueError("DI cost-cover fees and slippage must be in [0, 1)")
    exit_factor = 1-sign*slippage
    distance = entry * (slippage+exit_factor*exit_fee+entry_fee) / (fraction*exit_factor*(1-sign*exit_fee))
    if distance >= entry:
        raise ValueError("DI cost-cover distance would put a stop or target at or below zero")
    return distance


def validate_di_partial_risk_mode(profile, risk_mode, entry_rules=(), target_mode="FIXED_R"):
    markers = {r.get("_strategy_direction_mode") for r in entry_rules if r.get("_strategy_direction_mode")}
    if markers and "DI" not in markers:
        return
    if getattr(profile, "enabled", True) and profile.di_partial_1r_enabled:
        if target_mode != "FIXED_R":
            raise ValueError("DI 1R partial requires the fixed reward/risk target policy")
        if profile.di_partial_cost_atr_enabled and str(getattr(risk_mode, "value", risk_mode)) != "ATR":
            raise ValueError("DI cost-cover adjustment requires ATR risk mode")
