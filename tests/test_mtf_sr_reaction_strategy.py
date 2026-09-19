from types import SimpleNamespace

import numpy as np

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS, EVIDENCE_LABELS
from crypto_strategy_lab.mtf_sr_reaction import (
    MTF_SR_REACTION_MODE,
    candle_evidence_arrays,
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
        == "MTF S/R Reaction — 4H / 1H / Entry TF"
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


def test_mtf_sr_starter_preset_contains_four_trade_relative_entry_theses():
    rules = mtf_sr_reaction_preset_rules()
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
    assert {items[0]["side"] for items in groups.values()} == {"LONG", "SHORT"}
    assert all(len(items) == 4 for items in groups.values())

    relation_rules = [
        rule for rule in rules if rule["evidence"] == "SR_ENTRY_RELATION"
    ]
    assert len(relation_rules) == 2
    assert all(rule["value"] == "FAVORABLE_ENTRY_AREA" for rule in relation_rules)
    assert all(rule["sr_timeframe_minutes"] == 240 for rule in relation_rules)

    target_rules = [
        rule for rule in rules if rule["evidence"] == "SR_TARGET_PATH"
    ]
    assert len(target_rules) == 4
    assert all(
        rule["value"] == "TARGET_BEFORE_OPPOSING_ZONE"
        for rule in target_rules
    )
    assert all(rule["sr_timeframe_minutes"] == 240 for rule in target_rules)

    assert not any(
        rule["evidence"] in {
            "SR_NEAR_SUPPORT",
            "SR_NEAR_RESISTANCE",
            "SR_ROOM_IN_DIRECTION_ATR",
        }
        for rule in rules
    )

    retest_rules = [
        rule for rule in rules if rule["evidence"] == "SR_ROLE_REVERSAL_STATE"
    ]
    assert len(retest_rules) == 2
    assert all(rule["value"] == "VALID_RETEST" for rule in retest_rules)
    assert all(rule["sr_timeframe_minutes"] == 240 for rule in retest_rules)


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
