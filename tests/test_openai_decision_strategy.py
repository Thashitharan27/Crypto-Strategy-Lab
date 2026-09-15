import json

import pytest

from crypto_strategy_lab.ai_decision import (
    AI_DECISION_JSON_SCHEMA,
    AIDecisionCache,
    decision_cache_key,
    validate_ai_decision,
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
