from __future__ import annotations

import inspect
import logging
from pathlib import Path
import threading

import pytest

from mcp_server.tool_diagnostics import (
    DIAGNOSTICS_CONTRACT,
    ToolDiagnostics,
    _git_head,
)


class FakeServer:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(func):
            self.tools[func.__name__] = func
            return func

        return register


def _diagnostics(tmp_path: Path) -> ToolDiagnostics:
    return ToolDiagnostics(
        project_root=tmp_path,
        logger=logging.getLogger("test.mcp.diagnostics"),
        recent_limit=10,
    )


def test_instrumentation_preserves_signature_and_records_sequence_hash_movement(tmp_path):
    diagnostics = _diagnostics(tmp_path)
    server = FakeServer()
    tool = diagnostics.instrument(server)

    @tool()
    def advance(
        experiment_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        reasoning: str,
    ) -> dict:
        return {
            "sequence": expected_sequence + 2,
            "state_hash": "after-hash-abcdef",
            "status": "CANDIDATE_DECISION_REQUIRED",
        }

    assert list(inspect.signature(advance).parameters) == [
        "experiment_id",
        "operation_id",
        "expected_sequence",
        "expected_state_hash",
        "reasoning",
    ]

    result = advance(
        "EXP_1",
        "op-123",
        3,
        "before-hash-abcdef",
        "sensitive reasoning must not be logged",
    )
    assert result["sequence"] == 5

    health = diagnostics.health(tool_count=1, recent_calls=10)
    call = health["diagnostics"]["recent_calls"][-1]
    assert call["tool"] == "advance"
    assert call["experiment_id"] == "EXP_1"
    assert call["operation_id"] == "op-123"
    assert call["expected_sequence"] == 3
    assert call["expected_state_hash"] == "before-hash-abcdef"
    assert call["result_sequence"] == 5
    assert call["result_state_hash"] == "after-hash-abcdef"
    assert call["result_status"] == "CANDIDATE_DECISION_REQUIRED"
    assert call["success"] is True
    assert "reasoning" not in call
    assert "sensitive" not in str(call)


def test_returned_connection_safe_error_is_recorded_as_failed_call(tmp_path):
    diagnostics = _diagnostics(tmp_path)
    server = FakeServer()
    tool = diagnostics.instrument(server)

    @tool()
    def action(experiment_id: str) -> dict:
        return {
            "ok": False,
            "error_type": "TimeoutError",
            "error": "local operation failed",
            "connection_safe": True,
        }

    result = action("EXP_2")
    assert result["ok"] is False

    call = diagnostics.health(tool_count=1, recent_calls=1)["diagnostics"][
        "recent_calls"
    ][0]
    assert call["success"] is False
    assert call["error_type"] == "TimeoutError"
    assert call["error"] == "local operation failed"


def test_raised_exception_is_recorded_then_propagated(tmp_path):
    diagnostics = _diagnostics(tmp_path)
    server = FakeServer()
    tool = diagnostics.instrument(server)

    @tool()
    def action(run_id: str) -> dict:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        action("run-1")

    call = diagnostics.health(tool_count=1, recent_calls=1)["diagnostics"][
        "recent_calls"
    ][0]
    assert call["success"] is False
    assert call["error_type"] == "RuntimeError"
    assert call["run_id"] == "run-1"


def test_health_exposes_in_flight_call_until_local_function_returns(tmp_path):
    diagnostics = _diagnostics(tmp_path)
    server = FakeServer()
    tool = diagnostics.instrument(server)
    started = threading.Event()
    release = threading.Event()

    @tool()
    def slow_action(experiment_id: str, operation_id: str) -> dict:
        started.set()
        assert release.wait(timeout=5)
        return {
            "sequence": 9,
            "state_hash": "finished-hash",
            "status": "DONE",
        }

    thread = threading.Thread(
        target=slow_action,
        args=("EXP_3", "slow-op"),
        daemon=True,
    )
    thread.start()
    assert started.wait(timeout=2)

    health = diagnostics.health(tool_count=1, recent_calls=10)
    assert health["diagnostics"]["in_flight_count"] == 1
    active = health["diagnostics"]["in_flight"][0]
    assert active["tool"] == "slow_action"
    assert active["experiment_id"] == "EXP_3"
    assert active["operation_id"] == "slow-op"
    assert active["still_running"] is True

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    health = diagnostics.health(tool_count=1, recent_calls=10)
    assert health["diagnostics"]["in_flight_count"] == 0
    completed = health["diagnostics"]["recent_calls"][-1]
    assert completed["tool"] == "slow_action"
    assert completed["result_sequence"] == 9
    assert completed["success"] is True


def test_health_is_bounded_and_read_only_metadata(tmp_path):
    diagnostics = _diagnostics(tmp_path)
    health = diagnostics.health(tool_count=42, recent_calls=0)
    assert health["contract"] == DIAGNOSTICS_CONTRACT
    assert health["ok"] is True
    assert health["tool_count"] == 42
    assert health["diagnostics"]["recent_calls"] == []
    assert health["diagnostics"]["in_flight"] == []

    with pytest.raises(ValueError, match="between 0 and 50"):
        diagnostics.health(tool_count=42, recent_calls=51)


def test_git_head_reads_loose_ref_without_spawning_git(tmp_path):
    git_dir = tmp_path / ".git"
    ref = git_dir / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    ref.write_text("1234567890abcdef\n", encoding="utf-8")

    assert _git_head(tmp_path) == "1234567890abcdef"
