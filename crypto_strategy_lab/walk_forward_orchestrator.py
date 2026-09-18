"""Causal walk-forward orchestrator compatibility and bounded-scan facade.

The implementation lives in ``walk_forward_orchestrator_impl``. This facade
preserves the existing APIs while adding narrow protections and accelerated
workflow behavior:

* older captured candidates may resolve their immutable ``reference_run`` from
  the experiment definition at the outcome firewall;
* accelerated scans are capped to a small row budget per MCP request and persist
  an exact causal scan cursor when that budget is exhausted without a candidate;
* MCP judgment semantics separate the executable ``strategy_action`` determined
  by ENTRY/VETO/FLIP rules from ChatGPT's independent ``chatgpt_view``;
* resolved teacher losses from immutable 1.0R profiles are surfaced as FLIP
  review packets without ever touching walk-forward equity.

For new MCP decisions, ChatGPT's view is research evidence only. It never changes
the side used for TP/SL outcome lookup or walk-forward equity unless an active
causal FLIP rule already changed the candidate's strategy action.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl
from crypto_strategy_lab.walk_forward_candidate_engine import SCAN_CHECKPOINT_TYPE
from crypto_strategy_lab.walk_forward_teacher_learning import TEACHER_LOSS_FLIP_MODE


ACCELERATED_SCAN_ROWS = 4096
AUTONOMOUS_ORCHESTRATOR_CONTRACT = "causal_walk_forward_autonomous_v1"
DEFAULT_AUTONOMOUS_SCAN_SLICES = 4
MAX_AUTONOMOUS_SCAN_SLICES = 16
AUTONOMOUS_JUDGMENT_STATUSES = frozenset({
    "CANDIDATE_DECISION_REQUIRED",
    "TEACHER_REVIEW_REQUIRED",
    "TEACHER_LOSS_REVIEW_REQUIRED",
    "LOSS_REVIEW_REQUIRED",
    "PERIODIC_REVIEW_REQUIRED",
})
_AUTONOMOUS_DETERMINISTIC_CONTINUE_STATUSES = frozenset({
    "SCAN_CHECKPOINTED",
    "TRANSITION_LIMIT_REACHED",
})
_AUTONOMOUS_TERMINAL_STATUSES = frozenset({
    "NO_MORE_ACTION_IN_SCAN",
})
_ORIGINAL_ADVANCE_WALK_FORWARD = _impl.advance_walk_forward
_ORIGINAL_BUILD_LOSS_REVIEW_PACKET = _impl.build_loss_review_packet


def _candidate_strategy_action(candidate: dict[str, Any]) -> str:
    side = str(
        candidate.get("strategy_action")
        or candidate.get("rule_effective_side")
        or candidate.get("source_side")
        or ""
    ).strip().upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("captured candidate has no valid executable strategy_action")
    return side


def _decorate_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return candidate
    updated = deepcopy(candidate)
    side = str(
        updated.get("strategy_action")
        or updated.get("rule_effective_side")
        or updated.get("source_side")
        or ""
    ).strip().upper()
    if side in {"LONG", "SHORT"}:
        updated["strategy_action"] = side
    return updated


def _decision_research_fields(
    control: Any,
    experiment_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    capture = (_impl._candidate_capture(events, candidate_id).get("payload") or {})
    frozen_event = _impl._event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    frozen = (frozen_event or {}).get("payload") or {}
    strategy_action = str(
        frozen.get("strategy_action")
        or capture.get("strategy_action")
        or capture.get("rule_effective_side")
        or frozen.get("final_action")
        or capture.get("source_side")
        or ""
    ).strip().upper()
    chatgpt_view = str(
        frozen.get("chatgpt_view")
        or frozen.get("final_action")
        or ""
    ).strip().upper()
    confidence = frozen.get("chatgpt_confidence_pct", frozen.get("confidence_pct"))
    reasoning = frozen.get("chatgpt_reasoning", frozen.get("reasoning"))
    result: dict[str, Any] = {
        "strategy_action": strategy_action or None,
        "chatgpt_view": chatgpt_view or None,
        "chatgpt_confidence_pct": confidence,
        "chatgpt_reasoning": reasoning,
    }
    if strategy_action in {"LONG", "SHORT"} and chatgpt_view in {"LONG", "SHORT"}:
        result["chatgpt_agrees_with_strategy"] = chatgpt_view == strategy_action
    return result


def _reveal_frozen_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Legacy reveal path with immutable-definition reference-run fallback.

    This keeps direct pre-existing API behavior stable. New MCP decisions use
    ``_reveal_strategy_action_candidate`` below, which always reveals the
    executable strategy action rather than ChatGPT's independent view.
    """
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

    readback = store.read(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(
        candidate.get("reference_run") or definition.get("reference_run") or ""
    ).strip()
    if not reference_run:
        raise ValueError(
            "captured candidate and immutable experiment definition have no reference_run"
        )

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


def _reveal_strategy_action_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Reveal only the strategy's executable side after ChatGPT view is frozen."""
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    reveal_op = _impl._operation(operation_id, "reveal")
    existing_op = store._find_operation(events, reveal_op)
    if existing_op is not None:
        payload = deepcopy(existing_op.get("payload") or {})
        return {
            "contract": _impl.OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": existing_op["sequence"],
            "state_hash": existing_op["resulting_state_hash"],
            "candidate_id": candidate_id,
            "strategy_action": payload.get("strategy_action") or payload.get("final_action"),
            "chatgpt_view": payload.get("chatgpt_view"),
            "outcome": payload.get("outcome"),
            "idempotent_replay": True,
        }

    state = store._candidate_state(events, candidate_id)
    if state == "OUTCOME_REVEALED":
        revealed = _impl._event_for_candidate(events, "OUTCOME_REVEALED", candidate_id)
        assert revealed is not None
        payload = deepcopy(revealed.get("payload") or {})
        return {
            "contract": _impl.OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": revealed["sequence"],
            "state_hash": revealed["resulting_state_hash"],
            "candidate_id": candidate_id,
            "strategy_action": payload.get("strategy_action") or payload.get("final_action"),
            "chatgpt_view": payload.get("chatgpt_view"),
            "outcome": payload.get("outcome"),
            "idempotent_replay": True,
        }
    if state != "DECISION_FROZEN":
        raise ValueError("outcome can only be read after the ChatGPT view is durably frozen")

    capture_event = _impl._candidate_capture(events, candidate_id)
    candidate = capture_event.get("payload") or {}
    strategy_action = _candidate_strategy_action(candidate)
    frozen_event = _impl._event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    assert frozen_event is not None
    frozen = frozen_event.get("payload") or {}
    chatgpt_view = str(
        frozen.get("chatgpt_view") or frozen.get("final_action") or ""
    ).strip().upper()

    readback = store.read(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(
        candidate.get("reference_run") or definition.get("reference_run") or ""
    ).strip()
    if not reference_run:
        raise ValueError(
            "captured candidate and immutable experiment definition have no reference_run"
        )

    # OUTCOME FIREWALL: the outcome-bearing EVE artifact is opened only after
    # DECISION_FROZEN is durable, but the lookup side is always strategy_action.
    outcome = _impl._outcome_row_after_decision(
        reports, reference_run, candidate, strategy_action
    )
    exit_time = outcome.get("exit_time")
    appended = store.append_event(
        experiment_id,
        "OUTCOME_REVEALED",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate.get("candidate_token"),
            "final_action": strategy_action,
            "strategy_action": strategy_action,
            "chatgpt_view": chatgpt_view or None,
            "chatgpt_agrees_with_strategy": (
                chatgpt_view == strategy_action
                if chatgpt_view in {"LONG", "SHORT"}
                else None
            ),
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
        "strategy_action": strategy_action,
        "chatgpt_view": chatgpt_view or None,
        "outcome": outcome,
        "idempotent_replay": False,
    }


def freeze_and_reveal_walk_forward_view(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    candidate_token: str,
    confidence_pct: int,
    reasoning: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    chatgpt_view: str | None = None,
    final_action: str | None = None,
) -> dict[str, Any]:
    """Freeze ChatGPT's independent view without changing strategy execution.

    ``final_action`` is accepted only as a legacy MCP argument name and is
    interpreted as ``chatgpt_view``. The executable side is derived solely from
    the captured candidate's ENTRY/VETO/FLIP evaluation.
    """
    if chatgpt_view is not None and final_action is not None:
        if str(chatgpt_view).strip().upper() != str(final_action).strip().upper():
            raise ValueError("chatgpt_view and legacy final_action disagree")
    view_input = chatgpt_view if chatgpt_view is not None else final_action
    if view_input is None:
        raise ValueError("chatgpt_view must be LONG or SHORT")

    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    freeze_op = _impl._operation(operation_id, "freeze")
    candidate = (_impl._candidate_capture(events, candidate_id).get("payload") or {})
    strategy_action = _candidate_strategy_action(candidate)
    view, confidence, text = _impl._validate_decision_inputs(
        candidate, candidate_token, str(view_input), confidence_pct, reasoning
    )

    existing_freeze = store._find_operation(events, freeze_op)
    if existing_freeze is not None:
        payload = existing_freeze.get("payload") or {}
        stored_strategy = str(
            payload.get("strategy_action") or payload.get("final_action") or ""
        ).upper()
        stored_view = str(
            payload.get("chatgpt_view") or payload.get("final_action") or ""
        ).upper()
        stored_confidence = payload.get(
            "chatgpt_confidence_pct", payload.get("confidence_pct")
        )
        stored_reasoning = payload.get("chatgpt_reasoning", payload.get("reasoning"))
        if (
            stored_strategy != strategy_action
            or stored_view != view
            or stored_confidence != confidence
            or stored_reasoning != text
        ):
            raise ValueError("operation_id already froze a different walk-forward view")
        return _reveal_strategy_action_candidate(
            control,
            reports,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            operation_id=operation_id,
        )

    store, readback, events = _impl._verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    candidate = (_impl._candidate_capture(events, candidate_id).get("payload") or {})
    strategy_action = _candidate_strategy_action(candidate)
    view, confidence, text = _impl._validate_decision_inputs(
        candidate, candidate_token, str(view_input), confidence_pct, reasoning
    )
    if store._candidate_state(events, candidate_id) != "ENTRY_CONTEXT_CAPTURED":
        raise ValueError("candidate is not waiting for a ChatGPT view")

    store.append_event(
        experiment_id,
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate_token,
            # Legacy executable alias retained for old settlement/history code.
            "final_action": strategy_action,
            "strategy_action": strategy_action,
            "chatgpt_view": view,
            "chatgpt_confidence_pct": confidence,
            "chatgpt_reasoning": text,
            # Legacy research aliases retained for review packet compatibility.
            "confidence_pct": confidence,
            "reasoning": text,
            "chatgpt_agrees_with_strategy": view == strategy_action,
            "state_hash_at_decision": str(expected_state_hash),
            "feature_hash": candidate.get("feature_hash"),
            "strategy_snapshot_sha256": candidate.get("strategy_snapshot_sha256"),
        },
        freeze_op,
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=str(
            candidate.get("decision_available_at") or candidate.get("entry_time")
        ),
        source="CHATGPT_FROZEN_VIEW",
    )
    return _reveal_strategy_action_candidate(
        control,
        reports,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        operation_id=operation_id,
    )


def submit_walk_forward_view(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    candidate_token: str,
    confidence_pct: int,
    reasoning: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    chatgpt_view: str | None = None,
    final_action: str | None = None,
    auto_advance: bool = True,
    review_interval_months: int = 3,
) -> dict[str, Any]:
    """Record ChatGPT's view, settle strategy_action, then continue."""
    revealed = freeze_and_reveal_walk_forward_view(
        control,
        reports,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        candidate_token=candidate_token,
        chatgpt_view=chatgpt_view,
        final_action=final_action,
        confidence_pct=confidence_pct,
        reasoning=reasoning,
        operation_id=operation_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
    )
    settled = _impl.resolve_walk_forward_trade(
        control,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        operation_id=_impl._operation(operation_id, "settlement"),
        expected_sequence=int(revealed["sequence"]),
        expected_state_hash=str(revealed["state_hash"]),
    )
    research = _decision_research_fields(control, experiment_id, candidate_id)
    settlement = deepcopy(settled.get("settlement") or {})
    settlement.update({
        key: value for key, value in research.items()
        if key in {"strategy_action", "chatgpt_view", "chatgpt_agrees_with_strategy"}
    })

    if str(settlement.get("result")) == "LOSS":
        packet = _ORIGINAL_BUILD_LOSS_REVIEW_PACKET(
            control, experiment_id=experiment_id, candidate_id=candidate_id
        )
        packet.update(
            sequence=settled["sequence"],
            state_hash=settled["state_hash"],
            settlement=settlement,
            **research,
        )
        return packet
    if not auto_advance:
        return {
            "contract": _impl.ORCHESTRATOR_CONTRACT,
            "status": "TRADE_SETTLED",
            "experiment_id": experiment_id,
            "sequence": settled["sequence"],
            "state_hash": settled["state_hash"],
            "settlement": settlement,
            **research,
        }
    return advance_walk_forward(
        control,
        reports,
        experiment_id=experiment_id,
        operation_id=_impl._operation(operation_id, "advance"),
        expected_sequence=int(settled["sequence"]),
        expected_state_hash=str(settled["state_hash"]),
        review_interval_months=review_interval_months,
    )


# Keep the legacy reveal compatibility patch for direct old API calls.
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


def _teacher_loss_evidence(
    control: Any,
    experiment_id: str,
    profile: str,
) -> list[dict[str, Any]]:
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("result", "")).upper() != "LOSS":
            continue
        if profile and str(payload.get("strategy_profile_key", "")).lower() != profile:
            continue
        rows.append({
            "pair_id": payload.get("pair_id"),
            "side": payload.get("side"),
            "strategy_profile_key": payload.get("strategy_profile_key"),
            "pair_net_r": payload.get("pair_net_r"),
            "review_decision": payload.get("review_decision"),
            "resolution_time": payload.get("resolution_time") or event.get("effective_market_time"),
            "notes": payload.get("notes"),
        })
    return rows[-20:]


def _decorate_teacher_loss_packet(
    control: Any,
    reports: Any,
    experiment_id: str,
    updated: dict[str, Any],
) -> dict[str, Any]:
    teacher = updated.get("teacher")
    if not isinstance(teacher, dict):
        return updated
    if str(teacher.get("teacher_learning_mode", "")) != TEACHER_LOSS_FLIP_MODE:
        return updated

    teacher["result"] = "LOSS"
    updated["status"] = "TEACHER_LOSS_REVIEW_REQUIRED"
    updated["review_rule"] = (
        "This resolved 1:1 teacher loss is FLIP evidence only. Teacher evidence never changes "
        "walk-forward equity. Use NO_CHANGE or FLIP_EVIDENCE unless repeated prior causal "
        "evidence and a verified opposite-side 1R win justify FLIP_LEARNED."
    )

    side = str(teacher.get("side", "")).upper()
    profile = str(teacher.get("strategy_profile_key", "")).lower()
    updated["prior_teacher_loss_evidence"] = _teacher_loss_evidence(
        control, experiment_id, profile
    )
    updated["prior_teacher_loss_evidence_count"] = len(
        updated["prior_teacher_loss_evidence"]
    )

    entry_context = updated.get("entry_context") or {}
    trade_context = entry_context.get("trade_entry_context") or {}
    signal_index = trade_context.get("research_signal_index")
    if side not in {"LONG", "SHORT"} or signal_index in (None, ""):
        updated["opposite_side_outcome"] = {
            "available": False,
            "reason": "teacher entry context did not expose a unique research signal identity",
        }
        updated["flip_activation_allowed"] = False
        return updated

    store = _impl._store(control)
    readback = store.read(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", "")).strip()
    opposite = "SHORT" if side == "LONG" else "LONG"
    candidate = {
        "research_signal_index": int(signal_index),
        "source_side": side,
        "reference_sample_id": trade_context.get("research_sample_id"),
        "strategy_profile_key": profile,
        "entry_time": teacher.get("entry_time") or trade_context.get("entry_time"),
    }
    try:
        outcome = _impl._outcome_row_after_decision(
            reports, reference_run, candidate, opposite
        )
    except ValueError as exc:
        updated["opposite_side_outcome"] = {
            "available": False,
            "side": opposite,
            "reason": str(exc),
        }
        updated["flip_activation_allowed"] = False
        return updated

    updated["opposite_side_outcome"] = {
        "available": True,
        "side": opposite,
        "outcome": outcome,
    }
    updated["flip_activation_allowed"] = str(outcome.get("result", "")).upper() == "WIN"
    return updated


def _decorate_advance_result(
    control: Any,
    reports: Any,
    experiment_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    updated = deepcopy(result)
    candidate = _decorate_candidate(updated.get("candidate"))
    if candidate is not None:
        updated["candidate"] = candidate
        if isinstance(candidate, dict) and candidate.get("strategy_action"):
            updated["strategy_action"] = candidate["strategy_action"]
    candidate_id = str(updated.get("candidate_id") or "").strip()
    if updated.get("status") == "LOSS_REVIEW_REQUIRED" and candidate_id:
        updated.update(_decision_research_fields(control, experiment_id, candidate_id))
    return _decorate_teacher_loss_packet(control, reports, experiment_id, updated)


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
        return _decorate_advance_result(control, reports, experiment_id, result)

    scan = dict(result.get("scan") or {})
    cursor = scan.get("scan_cursor")
    if not isinstance(cursor, dict):
        return _decorate_advance_result(control, reports, experiment_id, result)

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


def _autonomous_metadata(
    *,
    continue_without_user: bool,
    assistant_judgment_required: bool,
    stop_reason: str,
    scan_slices: int,
    scan_checkpoints: int,
    rows_scanned: int,
    user_input_required: bool = False,
) -> dict[str, Any]:
    return {
        "mode": "AUTONOMOUS_RESEARCH",
        "continue_without_user": bool(continue_without_user),
        "assistant_judgment_required": bool(assistant_judgment_required),
        "user_input_required": bool(user_input_required),
        "suppress_routine_user_snapshot": bool(continue_without_user),
        "authoritative_state_persisted": True,
        "safe_to_resume_from_sequence_hash": True,
        "stop_reason": str(stop_reason),
        "scan_slices": int(scan_slices),
        "scan_checkpoints": int(scan_checkpoints),
        "rows_scanned": int(rows_scanned),
    }


def continue_walk_forward_autonomous(
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
    max_scan_slices: int = DEFAULT_AUTONOMOUS_SCAN_SLICES,
) -> dict[str, Any]:
    """Collapse routine deterministic checkpoints until judgment or a safe request budget.

    This function never invents ChatGPT judgment. It only consumes deterministic
    continuation states such as bounded scan checkpoints. Judgment packets are
    returned intact so ChatGPT can reason over them, persist the decision, and
    immediately call this action again without requiring user input.
    """
    if isinstance(max_scan_slices, bool) or not isinstance(max_scan_slices, int):
        raise ValueError("max_scan_slices must be an integer")
    if not 1 <= max_scan_slices <= MAX_AUTONOMOUS_SCAN_SLICES:
        raise ValueError(
            f"max_scan_slices must be between 1 and {MAX_AUTONOMOUS_SCAN_SLICES}"
        )

    sequence = int(expected_sequence)
    state_hash = str(expected_state_hash)
    total_rows = 0
    checkpoints = 0
    deterministic_slices = 0
    last_scan: dict[str, Any] | None = None

    for slice_index in range(max_scan_slices):
        result = advance_walk_forward(
            control,
            reports,
            experiment_id=experiment_id,
            operation_id=_impl._operation(
                operation_id, f"autonomous-slice-{slice_index + 1}"
            ),
            expected_sequence=sequence,
            expected_state_hash=state_hash,
            review_interval_months=review_interval_months,
            max_scan_rows=max_scan_rows,
            max_transitions=max_transitions,
        )
        status = str(result.get("status") or "")
        sequence = int(result.get("sequence", sequence))
        state_hash = str(result.get("state_hash", state_hash))
        scan = result.get("scan")
        if isinstance(scan, dict):
            last_scan = deepcopy(scan)
            total_rows += int(scan.get("rows_scanned") or 0)

        if status in AUTONOMOUS_JUDGMENT_STATUSES:
            updated = deepcopy(result)
            updated["autonomous_contract"] = AUTONOMOUS_ORCHESTRATOR_CONTRACT
            updated["autonomous"] = _autonomous_metadata(
                continue_without_user=True,
                assistant_judgment_required=True,
                stop_reason="ASSISTANT_JUDGMENT_REQUIRED",
                scan_slices=deterministic_slices + 1,
                scan_checkpoints=checkpoints,
                rows_scanned=total_rows,
            )
            return updated

        if status in _AUTONOMOUS_TERMINAL_STATUSES:
            updated = deepcopy(result)
            updated["autonomous_contract"] = AUTONOMOUS_ORCHESTRATOR_CONTRACT
            updated["autonomous"] = _autonomous_metadata(
                continue_without_user=False,
                assistant_judgment_required=False,
                stop_reason="NO_MORE_CAUSAL_ACTION",
                scan_slices=deterministic_slices + 1,
                scan_checkpoints=checkpoints,
                rows_scanned=total_rows,
            )
            return updated

        if status in _AUTONOMOUS_DETERMINISTIC_CONTINUE_STATUSES:
            deterministic_slices += 1
            if status == "SCAN_CHECKPOINTED":
                checkpoints += 1
            continue

        updated = deepcopy(result)
        updated["autonomous_contract"] = AUTONOMOUS_ORCHESTRATOR_CONTRACT
        updated["autonomous"] = _autonomous_metadata(
            continue_without_user=False,
            assistant_judgment_required=False,
            stop_reason=f"INSPECTION_REQUIRED:{status or 'UNKNOWN'}",
            scan_slices=deterministic_slices + 1,
            scan_checkpoints=checkpoints,
            rows_scanned=total_rows,
        )
        return updated

    return {
        "contract": AUTONOMOUS_ORCHESTRATOR_CONTRACT,
        "status": "AUTONOMOUS_CONTINUE",
        "experiment_id": experiment_id,
        "sequence": sequence,
        "state_hash": state_hash,
        "scan": last_scan,
        "autonomous": _autonomous_metadata(
            continue_without_user=True,
            assistant_judgment_required=False,
            stop_reason="MCP_REQUEST_BUDGET",
            scan_slices=deterministic_slices,
            scan_checkpoints=checkpoints,
            rows_scanned=total_rows,
        ),
        "next_required_event": "CONTINUE_WALK_FORWARD_AUTONOMOUS",
        "outcome_exposed": False,
    }


# Internal auto-advance paths in the implementation resolve this global at call
# time. Point them at the bounded facade too, so teacher reviews, wins and
# periodic reviews cannot fall back to an unbounded 250k-row request.
_impl.advance_walk_forward = advance_walk_forward
