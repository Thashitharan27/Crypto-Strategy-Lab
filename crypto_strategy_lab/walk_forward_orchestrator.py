"""Causal walk-forward orchestrator compatibility and bounded-scan facade.

The implementation lives in ``walk_forward_orchestrator_impl``. This facade
preserves the existing APIs while adding two narrow protections:

* older captured candidates may resolve their immutable ``reference_run`` from
  the experiment definition at the outcome firewall;
* accelerated scans are capped to a small row budget per MCP request and persist
  an exact causal scan cursor when that budget is exhausted without a candidate.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl
from crypto_strategy_lab.walk_forward_candidate_engine import SCAN_CHECKPOINT_TYPE


ACCELERATED_SCAN_ROWS = 4096
_ORIGINAL_ADVANCE_WALK_FORWARD = _impl.advance_walk_forward


def _reveal_frozen_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Reveal an already-frozen candidate without requiring a run field on its capture."""
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    reveal_op = _impl._operation(operation_id, "reveal")
    existing_op = store._find_operation(events, reveal_op)
    if existing_op is not None:
        return {
            "contract": _impl.OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": existing_op["sequence"],
            "state_hash": existing_op["resulting_state_hash"],
            "candidate_id": candidate_id,
            "outcome": deepcopy(existing_op.get("payload") or {}).get("outcome"),
            "idempotent_replay": True,
        }

    state = store._candidate_state(events, candidate_id)
    if state == "OUTCOME_REVEALED":
        revealed = _impl._event_for_candidate(events, "OUTCOME_REVEALED", candidate_id)
        assert revealed is not None
        return {
            "contract": _impl.OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": revealed["sequence"],
            "state_hash": revealed["resulting_state_hash"],
            "candidate_id": candidate_id,
            "outcome": deepcopy(revealed.get("payload") or {}).get("outcome"),
            "idempotent_replay": True,
        }
    if state != "DECISION_FROZEN":
        raise ValueError("outcome can only be read after the decision is durably frozen")

    capture_event = _impl._candidate_capture(events, candidate_id)
    candidate = capture_event.get("payload") or {}
    frozen_event = _impl._event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    assert frozen_event is not None
    frozen = frozen_event.get("payload") or {}
    frozen_side = str(frozen.get("final_action", "")).upper()

    # Narrow compatibility fallback for the existing experiment. The
    # experiment definition is immutable, so this does not rewrite or reinterpret
    # any historical candidate event.
    readback = store.read(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(
        candidate.get("reference_run") or definition.get("reference_run") or ""
    ).strip()
    if not reference_run:
        raise ValueError(
            "captured candidate and immutable experiment definition have no reference_run"
        )

    # OUTCOME FIREWALL: this remains the first access to the outcome-bearing
    # artifact, after DECISION_FROZEN is already durable.
    outcome = _impl._outcome_row_after_decision(
        reports, reference_run, candidate, frozen_side
    )
    exit_time = outcome.get("exit_time")
    appended = store.append_event(
        experiment_id,
        "OUTCOME_REVEALED",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate.get("candidate_token"),
            "final_action": frozen_side,
            "outcome_contract": _impl.OUTCOME_CONTRACT,
            "outcome": outcome,
        },
        reveal_op,
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=(
            str(exit_time) if exit_time else str(candidate.get("entry_time"))
        ),
        source="DETERMINISTIC_OUTCOME_FIREWALL",
    )
    return {
        "contract": _impl.OUTCOME_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": appended["sequence"],
        "state_hash": appended["state_hash"],
        "candidate_id": candidate_id,
        "outcome": outcome,
        "idempotent_replay": False,
    }


# The implementation's public functions resolve this module-global at runtime,
# so patching it once preserves the existing API while keeping the change narrow.
_impl._reveal_frozen_candidate = _reveal_frozen_candidate

# Preserve the original module surface, including private helpers used by tests.
for _name in dir(_impl):
    if _name.startswith("__") or _name in {
        "_reveal_frozen_candidate",
        "advance_walk_forward",
    }:
        continue
    globals()[_name] = getattr(_impl, _name)

del _name


def advance_walk_forward(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    review_interval_months: int = 3,
    max_scan_rows: int = 250000,
    max_transitions: int = 20,
) -> dict[str, Any]:
    """Advance one bounded deterministic slice, checkpointing long no-match scans.

    No historical opportunity is skipped: the checkpoint stores the exact
    ``(entry_time, research_signal_index, side)`` sort key and the candidate
    engine resumes strictly after that key on the next call. Teacher boundaries,
    rule mutations, reviews and trades invalidate an older cursor automatically.
    """
    if isinstance(max_scan_rows, bool) or not isinstance(max_scan_rows, int):
        raise ValueError("max_scan_rows must be an integer")
    if max_scan_rows < 1:
        raise ValueError("max_scan_rows must be positive")

    bounded_rows = min(int(max_scan_rows), ACCELERATED_SCAN_ROWS)
    result = _ORIGINAL_ADVANCE_WALK_FORWARD(
        control,
        reports,
        experiment_id=experiment_id,
        operation_id=operation_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        review_interval_months=review_interval_months,
        max_scan_rows=bounded_rows,
        max_transitions=max_transitions,
    )
    if result.get("status") != "NO_MORE_ACTION_IN_SCAN":
        return result

    scan = dict(result.get("scan") or {})
    cursor = scan.get("scan_cursor")
    if not isinstance(cursor, dict):
        # No rows were scanned, so there is nothing useful to checkpoint. This is
        # the true end-of-scan behavior from the existing orchestrator.
        return result

    required = ("entry_time", "research_signal_index", "side")
    if any(cursor.get(name) in (None, "") for name in required):
        raise ValueError("candidate scan returned an incomplete resumable cursor")

    store = _impl._store(control)
    checkpoint = store.append_event(
        experiment_id,
        "CHECKPOINT_CREATED",
        {
            "checkpoint_type": SCAN_CHECKPOINT_TYPE,
            "entry_time": str(cursor["entry_time"]),
            "research_signal_index": int(cursor["research_signal_index"]),
            "side": str(cursor["side"]).upper(),
            "rows_scanned": int(scan.get("rows_scanned", 0)),
            "bounded_scan_rows": bounded_rows,
            "teacher_pending": bool(scan.get("teacher_pending", False)),
            "reason": "bounded accelerated candidate scan completed without a judgment point",
        },
        _impl._operation(
            operation_id,
            f"scan-checkpoint-{int(result['sequence'])}",
        ),
        int(result["sequence"]),
        str(result["state_hash"]),
        effective_market_time=str(cursor["entry_time"]),
        source="DETERMINISTIC_CANDIDATE_ENGINE",
    )
    return {
        "contract": result.get("contract", _impl.ORCHESTRATOR_CONTRACT),
        "status": "SCAN_CHECKPOINTED",
        "experiment_id": experiment_id,
        "sequence": checkpoint["sequence"],
        "state_hash": checkpoint["state_hash"],
        "scan": scan,
        "scan_checkpoint": deepcopy(checkpoint.get("event") or {}).get("payload"),
        "next_required_event": "ADVANCE_WALK_FORWARD",
        "outcome_exposed": False,
    }


# Internal auto-advance paths in the implementation resolve this global at call
# time. Point them at the bounded facade too, so teacher reviews, wins and
# periodic reviews cannot fall back to an unbounded 250k-row request.
_impl.advance_walk_forward = advance_walk_forward
