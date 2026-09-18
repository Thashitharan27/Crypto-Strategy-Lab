from __future__ import annotations

import pytest

from crypto_strategy_lab import walk_forward_orchestrator as orchestrator


def _checkpoint(sequence: int, state_hash: str, rows: int = 4096) -> dict:
    return {
        "contract": "causal_walk_forward_orchestrator_v1",
        "status": "SCAN_CHECKPOINTED",
        "experiment_id": "BTCUSDT_15M_WF_TEST",
        "sequence": sequence,
        "state_hash": state_hash,
        "scan": {
            "rows_scanned": rows,
            "scan_cursor": {
                "entry_time": f"2025-01-{sequence:02d}T00:00:00+00:00",
                "research_signal_index": sequence,
                "side": "LONG",
            },
        },
        "outcome_exposed": False,
    }


def test_autonomous_loop_consumes_scan_checkpoints_until_judgment(monkeypatch):
    responses = [
        _checkpoint(2, "h2"),
        _checkpoint(3, "h3"),
        {
            "contract": "causal_walk_forward_orchestrator_v1",
            "status": "CANDIDATE_DECISION_REQUIRED",
            "experiment_id": "BTCUSDT_15M_WF_TEST",
            "sequence": 4,
            "state_hash": "h4",
            "candidate_id": "42-long",
            "candidate_token": "token",
            "candidate": {"candidate_id": "42-long"},
            "scan": {"rows_scanned": 12},
            "outcome_exposed": False,
        },
    ]
    observed = []

    def fake_advance(*args, **kwargs):
        observed.append(
            (
                kwargs["expected_sequence"],
                kwargs["expected_state_hash"],
                kwargs["operation_id"],
            )
        )
        return responses.pop(0)

    monkeypatch.setattr(orchestrator, "advance_walk_forward", fake_advance)

    result = orchestrator.continue_walk_forward_autonomous(
        None,
        None,
        experiment_id="BTCUSDT_15M_WF_TEST",
        operation_id="auto:test",
        expected_sequence=1,
        expected_state_hash="h1",
        max_scan_slices=4,
    )

    assert result["status"] == "CANDIDATE_DECISION_REQUIRED"
    assert result["autonomous_contract"] == orchestrator.AUTONOMOUS_ORCHESTRATOR_CONTRACT
    assert result["autonomous"]["continue_without_user"] is True
    assert result["autonomous"]["assistant_judgment_required"] is True
    assert result["autonomous"]["user_input_required"] is False
    assert result["autonomous"]["suppress_routine_user_snapshot"] is True
    assert result["autonomous"]["scan_checkpoints"] == 2
    assert result["autonomous"]["rows_scanned"] == 8204
    assert [item[:2] for item in observed] == [(1, "h1"), (2, "h2"), (3, "h3")]
    assert len({item[2] for item in observed}) == 3


def test_autonomous_loop_returns_compact_continue_at_request_budget(monkeypatch):
    responses = [_checkpoint(2, "h2"), _checkpoint(3, "h3")]

    monkeypatch.setattr(
        orchestrator,
        "advance_walk_forward",
        lambda *args, **kwargs: responses.pop(0),
    )

    result = orchestrator.continue_walk_forward_autonomous(
        None,
        None,
        experiment_id="BTCUSDT_15M_WF_TEST",
        operation_id="auto:budget",
        expected_sequence=1,
        expected_state_hash="h1",
        max_scan_slices=2,
    )

    assert result["status"] == "AUTONOMOUS_CONTINUE"
    assert result["sequence"] == 3
    assert result["state_hash"] == "h3"
    assert result["next_required_event"] == "CONTINUE_WALK_FORWARD_AUTONOMOUS"
    assert result["autonomous"]["continue_without_user"] is True
    assert result["autonomous"]["assistant_judgment_required"] is False
    assert result["autonomous"]["stop_reason"] == "MCP_REQUEST_BUDGET"
    assert result["autonomous"]["scan_checkpoints"] == 2
    assert result["autonomous"]["rows_scanned"] == 8192


def test_autonomous_loop_marks_terminal_state_without_requesting_user(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "advance_walk_forward",
        lambda *args, **kwargs: {
            "contract": "causal_walk_forward_orchestrator_v1",
            "status": "NO_MORE_ACTION_IN_SCAN",
            "experiment_id": "BTCUSDT_15M_WF_TEST",
            "sequence": 5,
            "state_hash": "h5",
            "scan": {"rows_scanned": 17},
        },
    )

    result = orchestrator.continue_walk_forward_autonomous(
        None,
        None,
        experiment_id="BTCUSDT_15M_WF_TEST",
        operation_id="auto:end",
        expected_sequence=4,
        expected_state_hash="h4",
    )

    assert result["status"] == "NO_MORE_ACTION_IN_SCAN"
    assert result["autonomous"]["continue_without_user"] is False
    assert result["autonomous"]["assistant_judgment_required"] is False
    assert result["autonomous"]["user_input_required"] is False
    assert result["autonomous"]["stop_reason"] == "NO_MORE_CAUSAL_ACTION"


def test_autonomous_loop_does_not_guess_unknown_status(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "advance_walk_forward",
        lambda *args, **kwargs: {
            "contract": "causal_walk_forward_orchestrator_v1",
            "status": "NEW_UNRECOGNIZED_BOUNDARY",
            "experiment_id": "BTCUSDT_15M_WF_TEST",
            "sequence": 8,
            "state_hash": "h8",
        },
    )

    result = orchestrator.continue_walk_forward_autonomous(
        None,
        None,
        experiment_id="BTCUSDT_15M_WF_TEST",
        operation_id="auto:unknown",
        expected_sequence=7,
        expected_state_hash="h7",
    )

    assert result["autonomous"]["continue_without_user"] is False
    assert result["autonomous"]["user_input_required"] is False
    assert result["autonomous"]["stop_reason"].startswith("INSPECTION_REQUIRED:")


@pytest.mark.parametrize("value", [0, 17, True, 1.5])
def test_autonomous_scan_slice_budget_is_bounded(value):
    with pytest.raises(ValueError, match="max_scan_slices"):
        orchestrator.continue_walk_forward_autonomous(
            None,
            None,
            experiment_id="BTCUSDT_15M_WF_TEST",
            operation_id="auto:bad-budget",
            expected_sequence=1,
            expected_state_hash="h1",
            max_scan_slices=value,
        )
