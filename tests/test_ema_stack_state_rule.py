import numpy as np

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.rule_strategy_builder import (
    EVIDENCE_GROUPS,
    EVIDENCE_LABELS,
    _evidence_menu_paths,
)
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    MARKET_PERMISSIONS,
    compile_profiles,
    is_categorical_evidence,
    new_rule,
    rule_operator_options,
    rule_value_options,
)


def test_ema_stack_state_is_registered_and_exposed_in_builder():
    assert "EMA_STACK_STATE" in RULE_INDICATORS
    assert EVIDENCE_LABELS["EMA_STACK_STATE"] == "EMA Stack State (50 / 100 / 200)"
    trend_group = dict(EVIDENCE_GROUPS)["Trend & Volatility"]
    assert "EMA_STACK_STATE" in trend_group
    assert _evidence_menu_paths()["EMA_STACK_STATE"] == ("Trend & Volatility",)


def test_ema_stack_state_is_categorical_with_clear_values():
    assert is_categorical_evidence("EMA_STACK_STATE")
    assert rule_operator_options("EMA_STACK_STATE") == ("IS", "IS_NOT")
    assert rule_value_options("EMA_STACK_STATE") == (
        "BULLISH_STACK",
        "BEARISH_STACK",
        "MIXED",
    )
    assert CATEGORICAL_VALUE_CODES["EMA_STACK_STATE"] == {
        "BULLISH_STACK": 1.0,
        "BEARISH_STACK": 2.0,
        "MIXED": 3.0,
    }


def test_required_bullish_ema_stack_compiles_to_entry_requirement():
    rule = new_rule(
        kind="REQUIRED",
        evidence="EMA_STACK_STATE",
        regime="BULL",
        side="LONG",
    )
    rule["value"] = "BULLISH_STACK"

    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(rule,),
    )
    compiled = strategy["bull_long"].entry_rules[0]

    assert compiled["indicator"] == "EMA_STACK_STATE"
    assert compiled["condition"] == "OUTSIDE"
    assert compiled["minimum"] == 1.0
    assert compiled["maximum"] == 1.0
    assert compiled["_builder_kind"] == "REQUIRED"


def test_ema_stack_state_runtime_uses_strict_50_100_200_ordering():
    engine = object.__new__(BacktestEngine)
    engine.ema_50_values = np.array([110.0, 90.0, 100.0, np.nan])
    engine.ema_100_values = np.array([105.0, 100.0, 100.0, 95.0])
    engine.ema_200_values = np.array([100.0, 110.0, 99.0, 90.0])

    assert engine._strategy_profile_rule_value(
        0, "LONG", None, "EMA_STACK_STATE"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "SHORT", None, "EMA_STACK_STATE"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        1, "LONG", None, "EMA_STACK_STATE"
    ) == 2.0
    assert engine._strategy_profile_rule_value(
        2, "LONG", None, "EMA_STACK_STATE"
    ) == 3.0
    assert np.isnan(
        engine._strategy_profile_rule_value(3, "LONG", None, "EMA_STACK_STATE")
    )
