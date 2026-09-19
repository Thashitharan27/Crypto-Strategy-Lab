import json

import pytest

from crypto_strategy_lab.ai_decision import (
    AI_DECISION_JSON_SCHEMA,
    AIDecisionCache,
    OPENAI_DECISION_MODE,
    decision_cache_key,
    validate_ai_decision,
)
from crypto_strategy_lab.ai_snapshot_enrichment import enrich_ai_snapshot
from crypto_strategy_lab.strategy_rule_model import (
    DIRECTION_MODES,
    MARKET_PERMISSIONS,
    compile_profiles,
    decompile_rules,
    infer_direction_mode,
)


def _raw(**overrides):
    value = {
        "long_confidence": 72,
        "short_confidence": 28,
        "selected_side": "LONG",
        "conflict_level": "MODERATE",
        "key_long_factors": ["SUPPORT_HELD", "POSITIVE_TAKER_FLOW"],
        "key_short_factors": ["DI_PRESSURE_CONTRACTING"],
        "summary": "Long evidence outweighs the short case.",
    }
    value.update(overrides)
    return value


def test_forced_side_contract_derives_selected_confidence_and_gap():
    decision = validate_ai_decision(_raw())
    assert decision.selected_side == "LONG"
    assert decision.selected_confidence == 72
    assert decision.decision_strength == 44


def test_forced_side_contract_rejects_non_100_total():
    with pytest.raises(ValueError, match="total 100"):
        validate_ai_decision(_raw(short_confidence=20))


def test_forced_side_contract_rejects_50_50_tie():
    with pytest.raises(ValueError, match="50/50"):
        validate_ai_decision(
            _raw(long_confidence=50, short_confidence=50)
        )


def test_forced_side_contract_rejects_side_that_does_not_match_score():
    with pytest.raises(ValueError, match="higher confidence"):
        validate_ai_decision(_raw(selected_side="SHORT"))


def test_schema_has_no_abstain_or_no_trade_choice():
    assert AI_DECISION_JSON_SCHEMA["properties"]["selected_side"]["enum"] == [
        "LONG",
        "SHORT",
    ]


def test_openai_decision_is_a_first_class_signal_mode():
    assert OPENAI_DECISION_MODE in DIRECTION_MODES
    strategy, _execution = compile_profiles(
        direction_mode=OPENAI_DECISION_MODE,
        market_permissions=MARKET_PERMISSIONS,
    )
    assert infer_direction_mode(strategy) == OPENAI_DECISION_MODE
    assert decompile_rules(strategy) == {
        "REQUIRED": (),
        "VETO": (),
        "FLIP": (),
    }
    for profile in strategy.values():
        marker = profile.entry_rules[0]
        assert marker["_strategy_direction_mode"] == OPENAI_DECISION_MODE
        assert marker["_strategy_builtin_rule"] == "OPENAI_DIRECTION_SIGNAL"
        assert marker["action"] == "REJECT"
        assert marker["condition"] == "OUTSIDE"


def test_gui_exposes_openai_signal_label():
    from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS

    assert DIRECTION_LABELS[OPENAI_DECISION_MODE] == "AI Decision — OpenAI"


def test_control_workspace_exposes_openai_signal_label_without_gui_dependency():
    from crypto_strategy_lab.control_rule_workspace import SIGNAL_STRATEGIES

    assert SIGNAL_STRATEGIES[OPENAI_DECISION_MODE] == "AI Decision — OpenAI"


def test_ai_snapshot_uses_trade_relative_sr_v2_and_adds_structure():
    class Profile:
        partial_stop_enabled = False
        stop_loss_multiple = 1.0
        partial_profit_enabled = False
        reward_risk_ratio = 3.0
        r_step_trailing_enabled = False

    class Config:
        market_symbol = "BTCUSDT"
        risk_mode = "ATR"
        sr_take_profit_mode = "FIXED_R"

    class Engine:
        config = Config()
        market_regime_values = ["BULL"]
        risk = [100.0]
        atr_values = [100.0]
        close = [1000.0]

        def _ai_profile(self, _regime, _side):
            return Profile()

        def _prepared_research_raw_value(self, _i, feature_name, column):
            values = {
                ("support_resistance_1h", "sr_1h_long_nearest_support_price"): 800.0,
                ("support_resistance_1h", "sr_1h_long_nearest_support_distance_atr"): 1.0,
                ("support_resistance_1h", "sr_1h_long_nearest_support_distance_price"): 200.0,
                ("support_resistance_1h", "sr_1h_long_nearest_resistance_price"): 1600.0,
                ("support_resistance_1h", "sr_1h_long_nearest_resistance_distance_atr"): 3.0,
                ("support_resistance_1h", "sr_1h_long_nearest_resistance_distance_price"): 600.0,
                ("support_resistance_1h", "sr_1h_long_near_support"): True,
                ("support_resistance_1h", "sr_1h_long_near_resistance"): False,
                ("support_resistance_1h", "sr_1h_long_inside_support_zone"): False,
                ("support_resistance_1h", "sr_1h_long_inside_resistance_zone"): False,
                ("support_resistance_1h", "sr_1h_long_support_state"): "SUPPORT_HELD",
                ("support_resistance_1h", "sr_1h_long_resistance_state"): "APPROACHING_RESISTANCE",
                ("support_resistance_1h", "sr_1h_long_support_held"): True,
                ("support_resistance_1h", "sr_1h_long_resistance_held"): False,
                ("support_resistance_1h", "sr_1h_long_support_zone_low"): 750.0,
                ("support_resistance_1h", "sr_1h_long_support_zone_high"): 850.0,
                ("support_resistance_1h", "sr_1h_long_resistance_zone_low"): 1600.0,
                ("support_resistance_1h", "sr_1h_long_resistance_zone_high"): 1700.0,
                ("support_resistance_4h", "sr_4h_long_nearest_resistance_price"): 1600.0,
                ("support_resistance_4h", "sr_4h_long_nearest_resistance_distance_atr"): 1.0,
                ("support_resistance_4h", "sr_4h_long_nearest_resistance_distance_price"): 600.0,
                ("support_resistance_4h", "sr_4h_long_near_support"): False,
                ("support_resistance_4h", "sr_4h_long_near_resistance"): False,
                ("support_resistance_4h", "sr_4h_long_inside_support_zone"): False,
                ("support_resistance_4h", "sr_4h_long_inside_resistance_zone"): False,
                ("support_resistance_4h", "sr_4h_long_resistance_state"): "APPROACHING_RESISTANCE",
                ("support_resistance_4h", "sr_4h_long_resistance_zone_low"): 1600.0,
                ("support_resistance_4h", "sr_4h_long_resistance_zone_high"): 1700.0,
                ("support_resistance_1d", "sr_1d_short_nearest_support_price"): 400.0,
                ("support_resistance_1d", "sr_1d_short_nearest_support_distance_atr"): 0.5,
                ("support_resistance_1d", "sr_1d_short_nearest_support_distance_price"): 600.0,
                ("support_resistance_1d", "sr_1d_short_nearest_resistance_price"): 1200.0,
                ("support_resistance_1d", "sr_1d_short_nearest_resistance_distance_atr"): 0.2,
                ("support_resistance_1d", "sr_1d_short_nearest_resistance_distance_price"): 200.0,
                ("support_resistance_1d", "sr_1d_short_near_support"): False,
                ("support_resistance_1d", "sr_1d_short_near_resistance"): True,
                ("support_resistance_1d", "sr_1d_short_inside_support_zone"): False,
                ("support_resistance_1d", "sr_1d_short_inside_resistance_zone"): False,
                ("support_resistance_1d", "sr_1d_short_support_state"): "APPROACHING_SUPPORT",
                ("support_resistance_1d", "sr_1d_short_resistance_state"): "RESISTANCE_HELD",
                ("support_resistance_1d", "sr_1d_short_support_zone_low"): 300.0,
                ("support_resistance_1d", "sr_1d_short_support_zone_high"): 400.0,
                ("support_resistance_1d", "sr_1d_short_resistance_zone_low"): 1150.0,
                ("support_resistance_1d", "sr_1d_short_resistance_zone_high"): 1250.0,
            }
            return values.get((feature_name, column))

        def _market_structure_snapshot(self, _i):
            return {
                "market_structure_direction": "LONG",
                "market_structure_reason": "HIGHER_HIGH_AND_HIGHER_LOW",
                "market_structure_breakout_confirmed_by_close": True,
            }

    base_snapshot = {
        "market_regime": "BULL",
        "directional_context": {
            "LONG": {
                "support_resistance": {"trade_location_rating": "GOOD_LOCATION"},
                "trade_contract": {
                    "enabled": False,
                    "reward_risk_ratio": 3.0,
                },
            },
            "SHORT": {
                "support_resistance": {"trade_location_rating": "BAD_LOCATION"},
                "trade_contract": {
                    "enabled": True,
                    "reward_risk_ratio": 3.0,
                },
            },
        },
    }
    enriched = enrich_ai_snapshot(Engine(), 0, base_snapshot)
    sr = enriched["support_resistance_trade_context_v2"]

    assert enriched["symbol"] == "BTCUSDT"
    assert "higher_timeframe_support_resistance" not in enriched
    assert "support_resistance" not in enriched["directional_context"]["LONG"]
    assert "support_resistance" not in enriched["directional_context"]["SHORT"]
    assert "enabled" not in enriched["directional_context"]["LONG"]["trade_contract"]
    assert "enabled" not in enriched["directional_context"]["SHORT"]["trade_contract"]

    long_1h = sr["long"]["timeframes"]["1h"]
    assert long_1h["entry_relation"] == "NEAR_FAVORABLE_STRUCTURE"
    assert long_1h["favorable_structure_state"] == "HELD"
    assert long_1h["opposing_distance_native_atr"] == 3.0
    assert long_1h["opposing_distance_strategy_atr"] == 6.0
    assert long_1h["opposing_room_r"] == 6.0
    assert long_1h["opposing_room_target_multiple"] == 2.0
    assert long_1h["target_path"] == "TARGET_BEFORE_OPPOSING_ZONE"

    long_4h = sr["long"]["timeframes"]["4h"]
    assert long_4h["opposing_distance_native_atr"] == 1.0
    assert long_4h["opposing_distance_strategy_atr"] == 6.0

    short_1d = sr["short"]["timeframes"]["1d"]
    assert short_1d["entry_relation"] == "NEAR_FAVORABLE_STRUCTURE"
    assert short_1d["favorable_structure_state"] == "HELD"
    assert short_1d["opposing_distance_native_atr"] == 0.5
    assert short_1d["opposing_distance_strategy_atr"] == 6.0

    assert enriched["confirmed_market_structure"]["market_structure_direction"] == "LONG"


def test_cache_round_trip_is_snapshot_and_model_specific(tmp_path):
    snapshot = {
        "timestamp": "2024-01-01T00:00:00+00:00",
        "plus_di": 30.0,
        "minus_di": 10.0,
    }
    key, digest = decision_cache_key(
        snapshot,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
    )
    cache = AIDecisionCache(tmp_path / "ai.jsonl")
    decision = validate_ai_decision(
        _raw(),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
        snapshot_hash=digest,
        response_id="resp_test",
    )
    cache.put(key, decision)

    restored = cache.get(
        key,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
        expected_snapshot_hash=digest,
    )
    assert restored is not None
    assert restored.selected_side == "LONG"
    assert restored.decision_strength == 44
    assert restored.cache_hit is True
    assert restored.response_id == "resp_test"

    row = json.loads((tmp_path / "ai.jsonl").read_text(encoding="utf-8"))
    assert row["snapshot_hash"] == digest
    assert "cache_key" in row
