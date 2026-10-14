"""Tests for shared stop/target planning, independent of signal engines."""
import pytest

from crypto_strategy_lab.exit_plan import (
    ExitPlan, StopMethod, TargetMethod, resolve_exit_levels,
)


@pytest.mark.parametrize("direction,stop,target", [
    ("LONG", 98.0, 104.0),
    ("SHORT", 102.0, 96.0),
])
def test_atr_stop_and_fixed_r_target(direction, stop, target):
    levels = resolve_exit_levels(
        direction=direction, entry_price=100.0,
        plan=ExitPlan(stop_atr_multiple=2.0, reward_risk_multiple=2.0),
        atr=1.0,
    )
    assert levels.stop == stop
    assert levels.target == target
    assert levels.risk_per_unit == 2.0


def test_structural_stop_and_structural_target():
    levels = resolve_exit_levels(
        direction="LONG", entry_price=100.0,
        plan=ExitPlan(StopMethod.STRUCTURE, TargetMethod.STRUCTURE),
        structure_stop=97.0, structure_target=108.0,
    )
    assert (levels.stop, levels.target, levels.risk_per_unit) == (97.0, 108.0, 3.0)


def test_fixed_reference_risk():
    levels = resolve_exit_levels(
        direction="SHORT", entry_price=100.0,
        plan=ExitPlan(StopMethod.FIXED_R), reference_risk=3.0,
    )
    assert (levels.stop, levels.target) == (103.0, 94.0)


@pytest.mark.parametrize("kwargs", [
    {"direction": "LONG", "entry_price": 100.0, "plan": ExitPlan(), "atr": 0.0},
    {"direction": "LONG", "entry_price": 100.0,
     "plan": ExitPlan(StopMethod.STRUCTURE), "structure_stop": 102.0},
    {"direction": "SHORT", "entry_price": 100.0,
     "plan": ExitPlan(StopMethod.FIXED_R), "reference_risk": 0.0},
    {"direction": "LONG", "entry_price": 100.0,
     "plan": ExitPlan(target_method=TargetMethod.STRUCTURE),
     "atr": 1.0, "structure_target": 99.0},
])
def test_invalid_exit_levels_fail(kwargs):
    with pytest.raises(ValueError):
        resolve_exit_levels(**kwargs)
