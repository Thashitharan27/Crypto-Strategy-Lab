from __future__ import annotations

import importlib.util
from pathlib import Path

from crypto_strategy_lab import walk_forward_orchestrator as orchestrator
from crypto_strategy_lab.walk_forward_candidate_engine import get_next_walk_forward_candidate


def _legacy_test_module():
    path = Path(__file__).with_name("test_walk_forward_orchestrator.py")
    spec = importlib.util.spec_from_file_location("wf_legacy_test_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chatgpt_disagreement_never_replaces_strategy_trade(tmp_path):
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(
        tmp_path, include_short=False
    )
    candidate = helpers._capture(control, reports, head)
    captured = candidate["candidate"]
    assert captured["source_side"] == "LONG"
    assert captured["rule_effective_side"] == "LONG"

    # The actual MCP tool still exposes final_action as a legacy wire name.
    # Under the corrected semantics it is ChatGPT's research-only view.
    result = orchestrator.submit_walk_forward_view(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        candidate_token=captured["candidate_token"],
        final_action="SHORT",
        confidence_pct=64,
        reasoning="Independent view prefers short, but no causal FLIP is active.",
        operation_id="decision:view-disagrees",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
        auto_advance=False,
    )

    assert result["status"] == "TRADE_SETTLED"
    assert result["strategy_action"] == "LONG"
    assert result["chatgpt_view"] == "SHORT"
    assert result["chatgpt_agrees_with_strategy"] is False
    assert result["settlement"]["final_action"] == "LONG"
    assert result["settlement"]["strategy_action"] == "LONG"
    assert result["settlement"]["chatgpt_view"] == "SHORT"
    assert result["settlement"]["net_r"] == -1.0
    assert result["settlement"]["equity_after"] == 990.0

    events = store.read(helpers.EXPERIMENT_ID, recent_events=50)["recent_events"]
    frozen = next(event for event in events if event["event_type"] == "DECISION_FROZEN")
    revealed = next(event for event in events if event["event_type"] == "OUTCOME_REVEALED")
    frozen_payload = frozen["payload"]
    assert frozen_payload["strategy_action"] == "LONG"
    assert frozen_payload["chatgpt_view"] == "SHORT"
    assert frozen_payload["chatgpt_confidence_pct"] == 64
    assert frozen_payload["final_action"] == "LONG"
    assert frozen_payload["chatgpt_agrees_with_strategy"] is False
    assert revealed["payload"]["strategy_action"] == "LONG"
    assert revealed["payload"]["chatgpt_view"] == "SHORT"
    assert revealed["payload"]["outcome"]["research_sample_id"] == "10-LONG-e1"


def test_active_flip_rule_controls_strategy_action_even_when_chatgpt_disagrees(tmp_path):
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(
        tmp_path, include_short=True
    )
    head = store.append_event(
        helpers.EXPERIMENT_ID,
        "FLIP_LEARNED",
        {
            "rule_id": "FLIP_001",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "test causal flip",
            "evidence_source": "PROSPECTIVE_WF",
            "profile": "bull_long",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        },
        "rule:flip",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00Z",
    )
    candidate = get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        operation_id="candidate:flip",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    captured = candidate["candidate"]
    assert captured["source_side"] == "LONG"
    assert captured["rule_effective_side"] == "SHORT"
    assert captured["matched_flip_groups"] == ["FLIP_001"]

    result = orchestrator.submit_walk_forward_view(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        candidate_token=captured["candidate_token"],
        chatgpt_view="LONG",
        confidence_pct=61,
        reasoning="Independent view prefers long, but the causal FLIP controls execution.",
        operation_id="decision:flip-executes",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
        auto_advance=False,
    )

    assert result["strategy_action"] == "SHORT"
    assert result["chatgpt_view"] == "LONG"
    assert result["chatgpt_agrees_with_strategy"] is False
    assert result["settlement"]["final_action"] == "SHORT"
    assert result["settlement"]["net_r"] == 0.95
    assert result["settlement"]["equity_after"] == 1009.5


def test_mcp_facade_routes_legacy_final_action_as_chatgpt_view():
    from mcp_server import control_server
    from mcp_server import control_server_impl

    assert (
        control_server_impl._submit_walk_forward_decision
        is orchestrator.submit_walk_forward_view
    )
    assert (
        control_server_impl._freeze_and_reveal_walk_forward_candidate
        is orchestrator.freeze_and_reveal_walk_forward_view
    )
    assert control_server._ORIGINAL_ADVANCE_WALK_FORWARD is orchestrator.advance_walk_forward
