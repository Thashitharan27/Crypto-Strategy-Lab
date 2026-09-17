from __future__ import annotations

import importlib.util
from pathlib import Path

from crypto_strategy_lab.walk_forward_candidate_engine import get_next_walk_forward_candidate
from mcp_server import control_server


def _legacy_test_module():
    path = Path(__file__).with_name("test_walk_forward_orchestrator.py")
    spec = importlib.util.spec_from_file_location("wf_flip_replay_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_active_flip_resumes_with_immutable_replay_without_refreeze(
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

    observed = {}

    def replay(control_arg, reports_arg, *, reference_run, candidate, strategy_action):
        observed["reference_run"] = reference_run
        observed["candidate_id"] = candidate["candidate_id"]
        observed["strategy_action"] = strategy_action
        return {
            "result": "WIN",
            "net_r": 0.99,
            "gross_r": 1.0,
            "fee_r": 0.01,
            "side": "SHORT",
            "exit_time": "2025-01-02T04:00:00+00:00",
            "exit_reason": "TP",
            "source": "IMMUTABLE_1M_INTRABAR_REPLAY",
            "replay_reason": "ACTIVE_CAUSAL_FLIP_WITHOUT_UNIQUE_OPPOSITE_EVE",
        }

    monkeypatch.setattr(control_server, "_replay_flipped_candidate_one_r", replay)

    result = control_server._impl._submit_walk_forward_decision(
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

    assert observed == {
        "reference_run": helpers.REFERENCE_RUN,
        "candidate_id": captured["candidate_id"],
        "strategy_action": "SHORT",
    }
    assert result["status"] == "TRADE_SETTLED"
    assert result["strategy_action"] == "SHORT"
    assert result["chatgpt_view"] == "SHORT"
    assert result["settlement"]["final_action"] == "SHORT"
    assert result["settlement"]["net_r"] == 0.99
    assert result["settlement"]["equity_after"] == 1009.9

    events = store.read(helpers.EXPERIMENT_ID, recent_events=100)["recent_events"]
    frozen_events = [event for event in events if event["event_type"] == "DECISION_FROZEN"]
    revealed_events = [event for event in events if event["event_type"] == "OUTCOME_REVEALED"]
    assert len(frozen_events) == 1
    assert frozen_events[0]["payload"]["chatgpt_confidence_pct"] == 66
    assert frozen_events[0]["payload"]["chatgpt_view"] == "SHORT"
    assert len(revealed_events) == 1
    assert revealed_events[0]["payload"]["strategy_action"] == "SHORT"
    assert revealed_events[0]["payload"]["outcome"]["source"] == "IMMUTABLE_1M_INTRABAR_REPLAY"
