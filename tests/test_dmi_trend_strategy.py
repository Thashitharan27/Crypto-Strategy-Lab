import numpy as np

from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    decompile_rules,
    infer_direction_mode,
    new_rule,
    normalize_rule,
)


def test_dmi_trend_adds_fixed_baseline_confirmations_without_changing_permissions():
    strategy, _execution = compile_profiles(
        direction_mode="DMI_TREND",
        market_permissions=MARKET_PERMISSIONS,
    )

    for profile in strategy.values():
        assert profile.enabled is True
        assert [rule["indicator"] for rule in profile.entry_rules] == [
            "ADX",
            "ADX_CHANGE",
            "DI_PRESSURE_STATE",
        ]
        adx, adx_change, pressure = profile.entry_rules
        assert adx["condition"] == "OUTSIDE"
        assert adx["minimum"] == 20.0
        assert adx_change["condition"] == "OUTSIDE"
        assert adx_change["minimum"] == 0.0
        assert pressure["condition"] == "OUTSIDE"
        assert pressure["minimum"] == pressure["maximum"] == 1.0
        assert all(rule["_builder_kind"] == "REQUIRED" for rule in profile.entry_rules)

    assert infer_direction_mode(strategy) == "DMI_TREND"
    assert decompile_rules(strategy) == {
        "REQUIRED": (),
        "VETO": (),
        "FLIP": (),
    }


def test_dmi_trend_keeps_user_rules_separate_and_appends_them_after_baseline():
    user_rule = new_rule(kind="REQUIRED", evidence="DI_SPREAD")
    user_rule.update(operator="GTE", value=25.0, regime="BULL", side="LONG")

    strategy, _execution = compile_profiles(
        direction_mode="DMI_TREND",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(user_rule,),
    )

    bull_long = strategy["bull_long"].entry_rules
    assert [rule["indicator"] for rule in bull_long] == [
        "ADX",
        "ADX_CHANGE",
        "DI_PRESSURE_STATE",
        "DI_SPREAD",
    ]
    assert [rule["indicator"] for rule in strategy["bull_short"].entry_rules] == [
        "ADX",
        "ADX_CHANGE",
        "DI_PRESSURE_STATE",
    ]
    recovered = decompile_rules(strategy)
    assert recovered["REQUIRED"] == (normalize_rule(user_rule),)


def test_raw_di_direction_remains_the_unfiltered_control_group():
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
    )
    assert all(profile.entry_rules == () for profile in strategy.values())
    assert infer_direction_mode(strategy) == "DI"


def test_adx_change_rule_value_is_one_completed_bar_difference():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.adx_values = np.array([19.5, 20.0, 21.25], dtype=float)

    assert np.isnan(
        engine._strategy_profile_rule_value(0, "LONG", None, "ADX_CHANGE")
    )
    assert engine._strategy_profile_rule_value(1, "LONG", None, "ADX_CHANGE") == 0.5
    assert engine._strategy_profile_rule_value(2, "SHORT", None, "ADX_CHANGE") == 1.25


def test_macd_pullback_persists_as_a_signal_strategy_without_hardcoded_ema_filter():
    strategy, _execution = compile_profiles(
        direction_mode="MACD_PULLBACK",
        market_permissions=MARKET_PERMISSIONS,
    )

    for profile in strategy.values():
        assert profile.enabled is True
        assert len(profile.entry_rules) == 1
        marker = profile.entry_rules[0]
        assert marker["indicator"] == "MACD_HISTOGRAM"
        assert marker["condition"] == "OUTSIDE"
        assert marker["_builder_kind"] == "REQUIRED"
        assert marker["_strategy_direction_mode"] == "MACD_PULLBACK"

    assert infer_direction_mode(strategy) == "MACD_PULLBACK"
    assert decompile_rules(strategy) == {
        "REQUIRED": (),
        "VETO": (),
        "FLIP": (),
    }


def test_macd_pullback_direction_requires_fresh_cross_on_pullback_side_of_zero():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.signal_strategy_mode = "MACD_PULLBACK"
    engine.macd_line_values = np.array([-0.4, -0.2, 0.3, 0.2], dtype=float)
    engine.macd_cross_state = np.array(
        ["NONE", "BULLISH", "BEARISH", "NONE"], dtype=object
    )

    assert engine._selected_direction(0) is None
    assert engine._selected_direction(1) == "LONG"
    assert engine._selected_direction(2) == "SHORT"
    assert engine._selected_direction(3) is None


def test_macd_pullback_rejects_crosses_on_wrong_side_of_zero():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.signal_strategy_mode = "MACD_PULLBACK"
    engine.macd_line_values = np.array([0.2, -0.2], dtype=float)
    engine.macd_cross_state = np.array(["BULLISH", "BEARISH"], dtype=object)

    assert engine._selected_direction(0) is None
    assert engine._selected_direction(1) is None


def test_macd_and_ema_rule_evidence_is_reusable_outside_macd_signal_strategy():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.close = np.array([100.0, 102.0], dtype=float)
    engine.atr_values = np.array([2.0, 2.0], dtype=float)
    engine.ema_50_values = np.array([99.0, 100.0], dtype=float)
    engine.ema_100_values = np.array([98.0, 99.0], dtype=float)
    engine.ema_200_values = np.array([97.0, 98.0], dtype=float)
    engine.macd_line_values = np.array([-1.0, 0.5], dtype=float)
    engine.macd_signal_values = np.array([-0.8, 0.2], dtype=float)
    engine.macd_histogram_values = np.array([-0.2, 0.3], dtype=float)
    engine.macd_histogram_change_values = np.array([np.nan, 0.5], dtype=float)
    engine.macd_cross_state = np.array(["NONE", "BULLISH"], dtype=object)
    engine.macd_zero_state = np.array(["BELOW_ZERO", "ABOVE_ZERO"], dtype=object)

    assert engine._strategy_profile_rule_value(
        1, "LONG", None, "EMA_200_DISTANCE_ATR"
    ) == 2.0
    assert engine._strategy_profile_rule_value(
        1, "LONG", None, "MACD_HISTOGRAM_CHANGE"
    ) == 0.5
    assert engine._strategy_profile_rule_value(
        1, "LONG", None, "MACD_CROSS_STATE"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "SHORT", None, "MACD_ZERO_STATE"
    ) == 2.0
