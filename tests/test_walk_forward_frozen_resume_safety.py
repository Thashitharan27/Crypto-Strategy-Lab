from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

import pytest

from crypto_strategy_lab import walk_forward_orchestrator as orchestrator
from crypto_strategy_lab.walk_forward_resume_safety import (
    install_resume_safety,
    json_safe_value,
)


def _legacy_test_module():
    path = Path(__file__).with_name("test_walk_forward_orchestrator.py")
    spec = importlib.util.spec_from_file_location("wf_resume_test_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _freeze_new_schema(store, helpers, candidate, *, view="SHORT", confidence=61, reasoning="Frozen research view."):
    captured = candidate["candidate"]
    strategy_action = str(
        captured.get("strategy_action")
        or captured.get("rule_effective_side")
        or captured.get("source_side")
    ).upper()
    return store.append_event(
        helpers.EXPERIMENT_ID,
        "DECISION_FROZEN",
        {
            "candidate_id": captured["candidate_id"],
            "candidate_token": captured["candidate_token"],
            "final_action": strategy_action,
            "strategy_action": strategy_action,
            "chatgpt_view": view,
            "chatgpt_confidence_pct": confidence,
            "chatgpt_reasoning": reasoning,
            "confidence_pct": confidence,
            "reasoning": reasoning,
            "chatgpt_agrees_with_strategy": view == strategy_action,
            "state_hash_at_decision": candidate["state_hash"],
            "feature_hash": captured.get("feature_hash"),
            "strategy_snapshot_sha256": captured.get("strategy_snapshot_sha256"),
        },
        "decision:partial:freeze",
        candidate["sequence"],
        candidate["state_hash"],
        effective_market_time=str(
            captured.get("decision_available_at") or captured.get("entry_time")
        ),
        source="CHATGPT_FROZEN_VIEW",
    )


def test_json_safe_value_handles_duckdb_decimal_and_datetime_scalars():
    safe = json_safe_value(
        {
            "pair_net_pnl": Decimal("12.345"),
            "fees": Decimal("0.125"),
            "exit_time": datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
            "nan_value": float("nan"),
        }
    )
    assert safe["pair_net_pnl"] == pytest.approx(12.345)
    assert safe["fees"] == pytest.approx(0.125)
    assert safe["exit_time"] == "2026-01-02T03:04:00+00:00"
    assert safe["nan_value"] is None
    json.dumps(safe, allow_nan=False)


def test_dedicated_reveal_resumes_matching_decision_frozen_without_second_freeze(tmp_path):
    install_resume_safety()
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(tmp_path, include_short=False)
    candidate = helpers._capture(control, reports, head)
    captured = candidate["candidate"]
    assert captured["rule_effective_side"] == "LONG"

    frozen = _freeze_new_schema(
        store,
        helpers,
        candidate,
        view="SHORT",
        confidence=61,
        reasoning="Independent view prefers short before outcome reveal.",
    )
    assert store.read(helpers.EXPERIMENT_ID)["derived_state"]["candidate_states"][captured["candidate_id"]] == "DECISION_FROZEN"

    revealed = orchestrator.freeze_and_reveal_walk_forward_view(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        candidate_token=captured["candidate_token"],
        final_action="SHORT",
        confidence_pct=61,
        reasoning="Independent view prefers short before outcome reveal.",
        operation_id="decision:resume-reveal",
        expected_sequence=frozen["sequence"],
        expected_state_hash=frozen["state_hash"],
    )

    assert revealed["strategy_action"] == "LONG"
    assert revealed["chatgpt_view"] == "SHORT"
    assert revealed["outcome"]["research_sample_id"] == "10-LONG-e1"
    assert revealed["outcome"]["net_r"] == -1.0
    assert revealed["sequence"] == frozen["sequence"] + 1

    events = store.read(helpers.EXPERIMENT_ID, recent_events=50)["recent_events"]
    assert sum(event["event_type"] == "DECISION_FROZEN" for event in events) == 1
    assert sum(event["event_type"] == "OUTCOME_REVEALED" for event in events) == 1


def test_mismatched_resume_cannot_replace_frozen_chatgpt_view(tmp_path):
    install_resume_safety()
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(tmp_path, include_short=False)
    candidate = helpers._capture(control, reports, head)
    captured = candidate["candidate"]
    frozen = _freeze_new_schema(
        store,
        helpers,
        candidate,
        view="SHORT",
        confidence=61,
        reasoning="Original frozen reasoning.",
    )

    with pytest.raises(ValueError, match="already-frozen"):
        orchestrator.freeze_and_reveal_walk_forward_view(
            control,
            reports,
            experiment_id=helpers.EXPERIMENT_ID,
            candidate_id=captured["candidate_id"],
            candidate_token=captured["candidate_token"],
            final_action="LONG",
            confidence_pct=70,
            reasoning="Attempt to replace the frozen view.",
            operation_id="decision:bad-resume",
            expected_sequence=frozen["sequence"],
            expected_state_hash=frozen["state_hash"],
        )

    after = store.read(helpers.EXPERIMENT_ID, recent_events=50)
    assert after["sequence"] == frozen["sequence"]
    assert after["state_hash"] == frozen["state_hash"]
    assert not any(event["event_type"] == "OUTCOME_REVEALED" for event in after["recent_events"])


def test_mcp_facade_installs_resume_safe_reveal():
    from mcp_server import control_server
    from mcp_server import control_server_impl

    assert control_server_impl._freeze_and_reveal_walk_forward_candidate is orchestrator.freeze_and_reveal_walk_forward_view
    assert control_server_impl._submit_walk_forward_decision is orchestrator.submit_walk_forward_view
