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


def test_ai_snapshot_keeps_higher_timeframe_sr_independent_and_adds_structure():
    class Engine:
        def _prepared_research_raw_value(self, _i, feature_name, column):
            values = {
                (
                    "support_resistance_1h",
                    "sr_1h_long_support_state",
                ): "SUPPORT_HELD",
                (
                    "support_resistance_1h",
                    "sr_1h_long_room_in_direction_atr",
                ): 3.4,
                (
                    "support_resistance_1h",
                    "sr_1h_short_resistance_state",
                ): "RESISTANCE_TESTING",
                (
                    "support_resistance_4h",
                    "sr_4h_long_support_state",
                ): "APPROACHING_SUPPORT",
                (
                    "support_resistance_1d",
                    "sr_1d_short_resistance_state",
                ): "RESISTANCE_HELD",
            }
            return values.get((feature_name, column))

        def _market_structure_snapshot(self, _i):
            return {
                "market_structure_direction": "LONG",
                "market_structure_reason": "HIGHER_HIGH_AND_HIGHER_LOW",
                "market_structure_breakout_confirmed_by_close": True,
            }

    enriched = enrich_ai_snapshot(Engine(), 0, {"market_regime": "BULL"})
    htf = enriched["higher_timeframe_support_resistance"]

    assert htf["1h"]["long"]["support_state"] == "SUPPORT_HELD"
    assert htf["1h"]["long"]["room_in_direction_atr"] == 3.4
    assert htf["1h"]["short"]["resistance_state"] == "RESISTANCE_TESTING"
    assert htf["4h"]["long"]["support_state"] == "APPROACHING_SUPPORT"
    assert htf["1d"]["short"]["resistance_state"] == "RESISTANCE_HELD"
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
