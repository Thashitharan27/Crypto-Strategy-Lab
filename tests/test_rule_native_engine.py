from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)


def _engine():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.di_pressure_spread_change = np.array([5.0, -3.0])
    engine.long_directional_di_change = np.array([6.0, -4.0])
    engine.long_opposing_di_change = np.array([-2.0, 3.0])
    engine.long_di_pressure_state = np.array(["EXPANDING", "CONTRACTING"], dtype=object)
    engine.short_directional_di_change = np.array([-2.0, 3.0])
    engine.short_opposing_di_change = np.array([6.0, -4.0])
    engine.short_di_pressure_state = np.array(["CONTRACTING", "EXPANDING"], dtype=object)
    return engine


def test_pressure_state_rule_value_uses_direction_specific_prepared_state():
    engine = _engine()
    profile = SimpleNamespace()
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "DI_PRESSURE_STATE"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "SHORT", profile, "DI_PRESSURE_STATE"
    ) == 2.0


def test_numeric_pressure_rule_values_use_prepared_causal_arrays():
    engine = _engine()
    profile = SimpleNamespace()
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "DI_SPREAD_CHANGE"
    ) == 5.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "DIRECTIONAL_DI_CHANGE"
    ) == 6.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "OPPOSING_DI_CHANGE"
    ) == -2.0


def test_global_pressure_allow_list_is_retired_in_current_native_runtime():
    engine = _engine()
    assert engine._di_pressure_filter_result(0) == (True, None)
