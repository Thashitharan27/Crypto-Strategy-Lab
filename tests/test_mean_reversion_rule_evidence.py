from types import SimpleNamespace

import numpy as np
import pytest

from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import (
    compile_profiles,
    new_rule,
    rule_operator_options,
    rule_value_options,
    uses_mean_reversion_rules,
)
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS


MR_EVIDENCE = {
    "MR_TRADE_STRETCH_ATR",
    "MR_DISTANCE_ATR",
    "MR_MOTION",
    "MR_BB_ZSCORE",
    "MR_BB_LOCATION",
    "MR_SIGNAL",
    "MR_TRADE_ALIGNMENT",
    "MR_STRENGTH",
    "MR_STATE",
    "MR_DISTANCE_CHANGE_ATR",
}


def _engine():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.config = SimpleNamespace(enable_mean_reversion_analysis=True)
    engine.mean_reversion_distance_atr = np.array([1.25])
    engine.mean_reversion_distance_change_atr = np.array([-0.20])
    engine.mean_reversion_motion = np.array(["TOWARD_MEAN"], dtype=object)
    engine.mean_reversion_bb_zscore = np.array([2.10])
    engine.mean_reversion_bb_location = np.array(["ABOVE_UPPER_BAND"], dtype=object)
    engine.mean_reversion_signal = np.array(["STRONG_SHORT"], dtype=object)
    engine.mean_reversion_strength_label = np.array(["STRONG"], dtype=object)
    engine.mean_reversion_state = np.array(["ABOVE_MEAN"], dtype=object)
    return engine


def test_mean_reversion_rule_evidence_is_registered_in_shared_contract():
    assert MR_EVIDENCE <= set(RULE_INDICATORS)


def test_mean_reversion_numeric_and_categorical_rule_shapes():
    assert rule_operator_options("MR_TRADE_STRETCH_ATR") == (
        "GT", "GTE", "LT", "LTE", "BETWEEN", "OUTSIDE"
    )
    assert rule_operator_options("MR_MOTION") == ("IS", "IS_NOT")
    assert rule_value_options("MR_MOTION") == (
        "TOWARD_MEAN", "AWAY_FROM_MEAN", "FLAT"
    )
    assert "FAVORS_REVERSION" in rule_value_options("MR_TRADE_ALIGNMENT")


def test_prepared_mean_reversion_values_feed_rules_without_recalculation():
    engine = _engine()
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_DISTANCE_ATR"
    ) == pytest.approx(1.25)
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_DISTANCE_CHANGE_ATR"
    ) == pytest.approx(-0.20)
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_BB_ZSCORE"
    ) == pytest.approx(2.10)
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_MOTION"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_BB_LOCATION"
    ) == 5.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_SIGNAL"
    ) == 2.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_STRENGTH"
    ) == 4.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_STATE"
    ) == 4.0


def test_trade_stretch_is_direction_normalized():
    engine = _engine()
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_TRADE_STRETCH_ATR"
    ) == pytest.approx(1.25)
    assert engine._strategy_profile_rule_value(
        0, "SHORT", profile, "MR_TRADE_STRETCH_ATR"
    ) == pytest.approx(-1.25)


def test_trade_alignment_is_relative_to_candidate_direction():
    engine = _engine()
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "SHORT", profile, "MR_TRADE_ALIGNMENT"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "MR_TRADE_ALIGNMENT"
    ) == 2.0


def test_mean_reversion_rules_compile_and_are_detected_as_dependencies():
    rule = new_rule(kind="VETO", evidence="MR_TRADE_ALIGNMENT")
    rule.update(operator="IS", value="AGAINST_REVERSION", regime="BULL", side="LONG")

    assert uses_mean_reversion_rules((rule,))
    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        veto_rules=(rule,),
    )
    native = profiles["bull_long"].entry_rules[0]
    assert native["indicator"] == "MR_TRADE_ALIGNMENT"
    assert native["condition"] == "INSIDE"
    assert native["minimum"] == native["maximum"] == 2.0


def test_disabled_mean_reversion_returns_missing_rule_evidence():
    engine = _engine()
    engine.config.enable_mean_reversion_analysis = False
    value = engine._prepared_mean_reversion_value(0, "LONG", "MR_DISTANCE_ATR")
    assert np.isnan(value)
