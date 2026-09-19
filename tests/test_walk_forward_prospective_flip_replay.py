from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from crypto_strategy_lab.walk_forward_candidate_engine import get_next_walk_forward_candidate
from mcp_server import control_server


def _legacy_test_module():
    path = Path(__file__).with_name("test_walk_forward_orchestrator.py")
    spec = importlib.util.spec_from_file_location("wf_flip_replay_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_incomplete_paired_flip_fails_closed_without_replay(
    tmp_path, monkeypatch
):
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(
        tmp_path, include_short=False
    )
    head = store.append_event(
        helpers.EXPERIMENT_ID,
        "FLIP_LEARNED",
        {
            "rule_id": "FLIP_004",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "test active flip",
            "evidence_source": "PROSPECTIVE_WF",
            "profile": "bull_long",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        },
        "rule:flip:004",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00Z",
    )
    candidate = get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        operation_id="candidate:prospective-flip",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    captured = candidate["candidate"]
    assert captured["source_side"] == "LONG"
    assert captured["rule_effective_side"] == "SHORT"
    assert captured["matched_flip_groups"] == ["FLIP_004"]

    reasoning = "Active causal FLIP controls execution; frozen view also prefers short."
    frozen = store.append_event(
        helpers.EXPERIMENT_ID,
        "DECISION_FROZEN",
        {
            "candidate_id": captured["candidate_id"],
            "candidate_token": captured["candidate_token"],
            "final_action": "SHORT",
            "strategy_action": "SHORT",
            "chatgpt_view": "SHORT",
            "chatgpt_confidence_pct": 66,
            "chatgpt_reasoning": reasoning,
            "confidence_pct": 66,
            "reasoning": reasoning,
            "chatgpt_agrees_with_strategy": True,
            "state_hash_at_decision": candidate["state_hash"],
            "feature_hash": captured.get("feature_hash"),
            "strategy_snapshot_sha256": captured.get("strategy_snapshot_sha256"),
        },
        "decision:prospective-flip:freeze",
        candidate["sequence"],
        candidate["state_hash"],
        effective_market_time=captured["decision_available_at"],
        source="CHATGPT_FROZEN_VIEW",
    )

    def should_not_replay(*args, **kwargs):
        raise AssertionError("paired WALK_FORWARD integrity failures must not replay 1m")

    monkeypatch.setattr(
        control_server, "_replay_flipped_candidate_one_r", should_not_replay
    )

    with pytest.raises(ValueError, match="paired Walk Forward outcome"):
        control_server._impl._submit_walk_forward_decision(
            control,
            reports,
            experiment_id=helpers.EXPERIMENT_ID,
            candidate_id=captured["candidate_id"],
            candidate_token=captured["candidate_token"],
            chatgpt_view="SHORT",
            confidence_pct=66,
            reasoning=reasoning,
            operation_id="decision:prospective-flip:resume",
            expected_sequence=frozen["sequence"],
            expected_state_hash=frozen["state_hash"],
            auto_advance=False,
        )

    readback = store.read(helpers.EXPERIMENT_ID, recent_events=100)
    assert (
        readback["derived_state"]["candidate_states"][captured["candidate_id"]]
        == "DECISION_FROZEN"
    )
    revealed_events = [
        event
        for event in readback["recent_events"]
        if event["event_type"] == "OUTCOME_REVEALED"
    ]
    assert revealed_events == []

