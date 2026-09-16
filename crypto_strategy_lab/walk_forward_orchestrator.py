"""Causal walk-forward orchestrator with a narrow existing-experiment resume fallback.

The implementation lives in ``walk_forward_orchestrator_impl``.  This facade
keeps its API unchanged and only teaches the outcome reveal boundary to use the
immutable experiment definition's ``reference_run`` when an older captured
candidate did not persist that field.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl


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

    # Narrow compatibility fallback for the existing experiment.  The
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
    if _name.startswith("__") or _name == "_reveal_frozen_candidate":
        continue
    globals()[_name] = getattr(_impl, _name)

del _name
