import numpy as np
import pytest

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.rule_strategy_builder import (
    EVIDENCE_GROUPS,
    EVIDENCE_LABELS,
    _evidence_menu_paths,
)
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    MARKET_PERMISSIONS,
    compile_profiles,
    is_categorical_evidence,
    new_rule,
    rule_operator_options,
    rule_value_options,
)


def test_price_vs_ema_stack_is_available_as_categorical_builder_evidence():
    indicator = "PRICE_VS_EMA_STACK"
    assert indicator in RULE_INDICATORS
    assert EVIDENCE_LABELS[indicator] == "Price vs EMA Stack (50 / 100 / 200)"
    assert indicator in dict(EVIDENCE_GROUPS)["Trend & Volatility"]
    assert _evidence_menu_paths()[indicator] == ("Trend & Volatility",)
    assert is_categorical_evidence(indicator)
    assert rule_operator_options(indicator) == ("IS", "IS_NOT")
    assert rule_value_options(indicator) == (
        "ABOVE_ALL_EMAS", "AMONG_EMAS", "BELOW_ALL_EMAS"
    )
    assert CATEGORICAL_VALUE_CODES[indicator] == {
        "ABOVE_ALL_EMAS": 1.0, "AMONG_EMAS": 2.0, "BELOW_ALL_EMAS": 3.0
    }


@pytest.mark.parametrize("state,code", [
    ("ABOVE_ALL_EMAS", 1.0),
    ("AMONG_EMAS", 2.0),
    ("BELOW_ALL_EMAS", 3.0),
])
def test_required_price_location_compiles_to_categorical_reject_rule(state, code):
    rule = new_rule(kind="REQUIRED", evidence="PRICE_VS_EMA_STACK", regime="BULL", side="LONG")
    rule["value"] = state
    strategy, _ = compile_profiles(
        direction_mode="DI", market_permissions=MARKET_PERMISSIONS, required_rules=(rule,)
    )
    compiled = strategy["bull_long"].entry_rules[0]
    assert compiled["indicator"] == "PRICE_VS_EMA_STACK"
    assert compiled["condition"] == "OUTSIDE"
    assert compiled["minimum"] == compiled["maximum"] == code
    assert compiled["_builder_kind"] == "REQUIRED"


@pytest.mark.parametrize("engine_class", [
    BacktestEngine, RuleAwareDataLakeProductionBacktestEngine
])
def test_price_location_uses_signal_close_and_all_three_emas_in_any_order(engine_class):
    engine = object.__new__(engine_class)
    engine.close = np.array([111, 97, 92, 89, 105, 110, 90, 95, 100, np.nan, 96], dtype=float)
    engine.ema_50_values = np.array([100, 100, 90, 100, 90, 110, 90, 100, 100, 100, np.nan], dtype=float)
    engine.ema_100_values = np.array([95, 95, 110, 95, 110, 95, 95, 95, 100, 95, 95], dtype=float)
    engine.ema_200_values = np.array([90, 90, 100, 90, 100, 90, 100, 90, 100, 90, 90], dtype=float)
    expected = [1, 2, 2, 3, 2, np.nan, np.nan, 2, np.nan, np.nan, np.nan]
    for i, code in enumerate(expected):
        result = engine._strategy_profile_rule_value(i, "LONG", None, "PRICE_VS_EMA_STACK")
        if np.isnan(code):
            assert np.isnan(result)
        else:
            assert result == code
            assert engine._strategy_profile_rule_value(
                i, "SHORT", None, "PRICE_VS_EMA_STACK"
            ) == code
