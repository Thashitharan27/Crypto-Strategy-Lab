from types import SimpleNamespace

import numpy as np

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS, EVIDENCE_LABELS
from crypto_strategy_lab.mtf_sr_reaction import (
    MTF_SR_REACTION_MODE,
    MtfSrReactionMixin,
    candle_evidence_arrays,
    mtf_sr_reaction_timeframe_plan,
)
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    infer_direction_mode,
    mtf_sr_reaction_preset_rules,
    new_rule,
    normalize_rule,
)
from crypto_strategy_lab.walk_forward_candidate_engine_impl import _evidence


def test_mtf_sr_reaction_is_first_class_authoring_option():
    strategy, _execution = compile_profiles(
        direction_mode=MTF_SR_REACTION_MODE,
        market_permissions=MARKET_PERMISSIONS,
    )
    assert infer_direction_mode(strategy) == MTF_SR_REACTION_MODE
    assert all(
        any(
            rule.get("_strategy_direction_mode") == MTF_SR_REACTION_MODE
            for rule in profile.entry_rules
        )
        for profile in strategy.values()
    )
    assert (
        DIRECTION_LABELS[MTF_SR_REACTION_MODE]
        == "MTF S/R Reaction — Adaptive HTF / Entry TF"
    )


def test_mtf_price_action_evidence_is_exposed_with_rule_timeframes():
    expected = {
        "CANDLE_BODY_ATR",
        "CANDLE_RANGE_ATR",
        "BODY_TO_RANGE_RATIO",
        "LOWER_WICK_RATIO",
        "UPPER_WICK_RATIO",
        "RANGE_CONTRACTION_RATIO",
        "BODY_CONTRACTION_RATIO",
        "CANDLE_CLOSE_LOCATION",
        "BULLISH_ENGULFING",
        "BEARISH_ENGULFING",
        "BULLISH_PIN_BAR",
        "BEARISH_PIN_BAR",
        "BULLISH_REVERSAL_TRIGGER",
        "BEARISH_REVERSAL_TRIGGER",
        "SR_APPROACH_MOMENTUM_STATE",
        "SR_ROLE_REVERSAL_STATE",
        "SR_ZONE_PENETRATION_ATR",
        "SR_ZONE_REJECTION_ATR",
        "SR_BREAKOUT_BODY_ATR",
        "SR_BREAKOUT_CLOSE_BEYOND_ZONE_ATR",
    }
    assert expected <= set(RULE_INDICATORS)
    assert expected <= set(EVIDENCE_LABELS)

    rule = new_rule(kind="REQUIRED", evidence="CANDLE_BODY_ATR")
    assert rule["sr_timeframe_minutes"] == 0
    rule["sr_timeframe_minutes"] = 60
    normalized = normalize_rule(rule, expected_kind="REQUIRED")
    assert normalized["sr_timeframe_minutes"] == 60


def test_mtf_sr_timeframe_plan_adapts_to_strategy_timeframe():
    assert mtf_sr_reaction_timeframe_plan(15) == {
        "strategy_minutes": 15,
        "structure_minutes": 240,
        "approach_minutes": 60,
    }
    assert mtf_sr_reaction_timeframe_plan(60) == {
        "strategy_minutes": 60,
        "structure_minutes": 240,
        "approach_minutes": 60,
    }
    assert mtf_sr_reaction_timeframe_plan(240) == {
        "strategy_minutes": 240,
        "structure_minutes": 1440,
        "approach_minutes": 240,
    }


def test_mtf_sr_timeframe_plan_rejects_only_unsupported_hierarchy():
    import pytest

    with pytest.raises(ValueError, match="divides evenly into 1h"):
        mtf_sr_reaction_timeframe_plan(45)
    with pytest.raises(ValueError, match="below 1d"):
        mtf_sr_reaction_timeframe_plan(1440)


def _rules_by_evidence(rules, evidence):
    return [rule for rule in rules if rule["evidence"] == evidence]


def test_mtf_sr_starter_preset_adapts_for_15m():
    rules = mtf_sr_reaction_preset_rules(15)
    groups = {}
    for rule in rules:
        groups.setdefault(rule["group_id"], []).append(rule)

    assert len(groups) == 4
    assert len(rules) == 16
    names = {items[0]["group_name"] for items in groups.values()}
    assert names == {
        "4H Favorable Structure Bounce — Long",
        "4H Break + Retest — Long",
        "4H Favorable Structure Bounce — Short",
        "4H Break + Retest — Short",
    }
    assert all(
        rule["sr_timeframe_minutes"] == 240
        for rule in _rules_by_evidence(rules, "SR_ENTRY_RELATION")
    )
    assert all(
        rule["sr_timeframe_minutes"] == 60
        for rule in _rules_by_evidence(rules, "SR_APPROACH_MOMENTUM_STATE")
    )
    assert all(
        rule["sr_timeframe_minutes"] == 0
        for rule in rules
        if rule["evidence"] in {
            "BULLISH_REVERSAL_TRIGGER",
            "BEARISH_REVERSAL_TRIGGER",
        }
    )


def test_mtf_sr_starter_preset_collapses_approach_to_strategy_tf_for_1h():
    rules = mtf_sr_reaction_preset_rules(60)

    assert all(
        rule["sr_timeframe_minutes"] == 240
        for rule in rules
        if rule["evidence"] in {
            "SR_ENTRY_RELATION",
            "SR_ROLE_REVERSAL_STATE",
            "SR_TARGET_PATH",
        }
    )
    assert all(
        rule["sr_timeframe_minutes"] == 0
        for rule in _rules_by_evidence(rules, "SR_APPROACH_MOMENTUM_STATE")
    )
    assert {rule["group_name"] for rule in rules} == {
        "4H Favorable Structure Bounce — Long",
        "4H Break + Retest — Long",
        "4H Favorable Structure Bounce — Short",
        "4H Break + Retest — Short",
    }


def test_mtf_sr_starter_preset_uses_daily_structure_for_4h_strategy():
    rules = mtf_sr_reaction_preset_rules(240)

    assert all(
        rule["sr_timeframe_minutes"] == 1440
        for rule in rules
        if rule["evidence"] in {
            "SR_ENTRY_RELATION",
            "SR_ROLE_REVERSAL_STATE",
            "SR_TARGET_PATH",
        }
    )
    assert all(
        rule["sr_timeframe_minutes"] == 0
        for rule in _rules_by_evidence(rules, "SR_APPROACH_MOMENTUM_STATE")
    )
    assert {rule["group_name"] for rule in rules} == {
        "1D Favorable Structure Bounce — Long",
        "1D Break + Retest — Long",
        "1D Favorable Structure Bounce — Short",
        "1D Break + Retest — Short",
    }




def test_one_hour_runtime_feature_setup_no_longer_raises_old_entry_tf_error():
    class Base:
        def _configure_signal_features(self):
            return None

    class Engine(MtfSrReactionMixin, Base):
        pass

    engine = Engine.__new__(Engine)
    engine.config = SimpleNamespace(
        strategy_timeframe_minutes=60,
        atr_period=14,
        strategy_profiles={
            "bull_long": SimpleNamespace(
                entry_rules=(
                    {"_strategy_direction_mode": MTF_SR_REACTION_MODE},
                )
            )
        },
    )
    periods = 96
    engine.times = np.array(
        np.datetime64("2026-01-01T00:00")
        + np.arange(periods) * np.timedelta64(1, "h")
    )
    engine.open = np.linspace(100.0, 120.0, periods)
    engine.close = engine.open + 0.25
    engine.high = engine.close + 0.5
    engine.low = engine.open - 0.5
    engine.atr_values = np.full(periods, 2.0)

    engine._configure_signal_features()

    assert 60 in engine.mtf_price_action
    assert 240 in engine.mtf_price_action
    assert 1440 in engine.mtf_price_action


def test_role_reversal_tracks_retired_broken_zone_not_new_nearest_structure():
    class Engine(MtfSrReactionMixin):
        pass

    engine = Engine.__new__(Engine)
    engine.config = SimpleNamespace(
        strategy_timeframe_minutes=15,
        enable_support_resistance_analysis=True,
        strategy_profiles={
            "bull_long": SimpleNamespace(
                entry_rules=(
                    {
                        "_strategy_direction_mode": MTF_SR_REACTION_MODE,
                        "indicator": "SR_ROLE_REVERSAL_STATE",
                    },
                )
            )
        },
    )
    size = 6
    engine.close = np.array([99.0, 101.0, 103.0, 102.5, 102.5, 104.0])
    engine.low = np.array([98.5, 100.0, 102.5, 102.3, 101.5, 103.0])
    engine.high = np.array([99.5, 102.0, 103.5, 103.0, 103.0, 104.5])
    engine.atr_values = np.ones(size)
    engine.mtf_price_action = {240: {}}
    engine.research_features = {"support_resistance_4h": object()}
    engine.mtf_role_reversal = {}

    values = {
        "sr_4h_long_resistance_state": np.array(
            ["APPROACHING_RESISTANCE"] * size, dtype=object
        ),
        # The nearest active resistance changes immediately after the break.
        "sr_4h_long_resistance_zone_low": np.array(
            [100.0, 100.0, 110.0, 110.0, 110.0, 110.0]
        ),
        "sr_4h_long_resistance_zone_high": np.array(
            [102.0, 102.0, 112.0, 112.0, 112.0, 112.0]
        ),
        "sr_4h_long_resistance_last_break_index": np.array(
            [np.nan, np.nan, 5.0, 5.0, 5.0, 5.0]
        ),
        "sr_4h_long_resistance_broken_zone_low": np.array(
            [np.nan, np.nan, 100.0, 100.0, 100.0, 100.0]
        ),
        "sr_4h_long_resistance_broken_zone_high": np.array(
            [np.nan, np.nan, 102.0, 102.0, 102.0, 102.0]
        ),
        # SHORT-side fields are absent on purpose; the routine should simply
        # leave that side without a v6 break event.
    }

    def raw_value(i, _feature_name, column):
        series = values.get(column)
        return None if series is None else series[i]

    engine._prepared_research_raw_value = raw_value
    engine._configure_mtf_sr_reaction_context()

    states = engine.mtf_role_reversal[(240, "LONG")]
    assert states[2] == "BREAKOUT_CONFIRMED"
    assert states[3] == "RETEST_APPROACHING"
    assert states[4] == "RETEST_HELD"


def test_candle_evidence_detects_engulfing_and_pin_bar_causally():
    open_ = np.array([10.0, 8.9, 10.0])
    high = np.array([10.2, 10.3, 10.2])
    low = np.array([8.8, 8.7, 9.0])
    close = np.array([9.0, 10.1, 10.1])
    atr = np.ones(3)

    evidence = candle_evidence_arrays(open_, high, low, close, atr)

    assert not evidence["bullish_engulfing"][0]
    assert evidence["bullish_engulfing"][1]
    assert evidence["bullish_pin_bar"][2]
    assert evidence["bullish_reversal_trigger"][1]
    assert evidence["bullish_reversal_trigger"][2]


def test_walk_forward_reads_new_mtf_evidence_by_condition_timeframe():
    config = {
        "data": {"strategy_timeframe_minutes": 15},
        "features": {"sr_timeframe_minutes": 0},
        "strategy": {"profiles": {}},
    }
    row = {
        "mtf_1h_body_atr": 0.42,
        "mtf_4h_long_sr_role_reversal_state": "RETEST_HELD",
        "mtf_strategy_bullish_reversal_trigger": True,
    }

    assert (
        _evidence(
            row,
            "LONG",
            "bull_long",
            {
                "indicator": "CANDLE_BODY_ATR",
                "sr_timeframe_minutes": 60,
            },
            config,
        )
        == 0.42
    )
    assert (
        _evidence(
            row,
            "LONG",
            "bull_long",
            {
                "indicator": "SR_ROLE_REVERSAL_STATE",
                "sr_timeframe_minutes": 240,
            },
            config,
        )
        == "RETEST_HELD"
    )
    from crypto_strategy_lab.walk_forward_candidate_engine_impl import _condition_match

    matched, detail = _condition_match(
        row,
        "LONG",
        "bull_long",
        {
            "indicator": "SR_ROLE_REVERSAL_STATE",
            "condition": "EQUALS",
            "value": "VALID_RETEST",
            "sr_timeframe_minutes": 240,
        },
        config,
    )
    assert matched
    assert detail["availability"] == "AVAILABLE"
    assert (
        _evidence(
            row,
            "LONG",
            "bull_long",
            {
                "indicator": "BULLISH_REVERSAL_TRIGGER",
                "sr_timeframe_minutes": 0,
            },
            config,
        )
        is True
    )
