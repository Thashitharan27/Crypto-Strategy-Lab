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
* resolved teacher losses from immutable paired WALK_FORWARD references are
  surfaced as FLIP review packets without ever touching walk-forward equity.

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
from crypto_strategy_lab.walk_forward_research_policy import decorate_review_packet
from crypto_strategy_lab.walk_forward_adaptive_policy import adaptive_weekly_policy
from crypto_strategy_lab.walk_forward_adaptive_weekly import (
    build_adaptive_source_history,
    build_raw_strategy_benchmark,
)


ACCELERATED_SCAN_ROWS = 4096
AUTONOMOUS_ORCHESTRATOR_CONTRACT = "causal_walk_forward_autonomous_v1"
DEFAULT_AUTONOMOUS_SCAN_SLICES = 4
MAX_AUTONOMOUS_SCAN_SLICES = 16
TEACHER_FLIP_VALIDATION_INCONSISTENCY = "TEACHER_FLIP_VALIDATION_INCONSISTENCY"
AUTONOMOUS_JUDGMENT_STATUSES = frozenset({
    "CANDIDATE_DECISION_REQUIRED",
    "TEACHER_REVIEW_REQUIRED",
    "TEACHER_LOSS_REVIEW_REQUIRED",
    "LOSS_REVIEW_REQUIRED",
    "PERIODIC_REVIEW_REQUIRED",
    "BOOTSTRAP_RESEARCH_REQUIRED",
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

_SELF_STALE_HEAD_HANDOFF_LIMIT = 4


def _advance_with_internal_head_handoff(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    review_interval_months: int,
    max_scan_rows: int,
    max_transitions: int,
) -> dict[str, Any]:
    """Resume only when this same request advanced its own causal head.

    This fixes fresh batch ingestion where deterministic sub-steps can commit
    before a later sub-step observes the caller's original head. Foreign tail
    events are never adopted and still raise the normal stale-head error.
    """
    sequence = int(expected_sequence)
    state_hash = str(expected_state_hash)
    prefix = str(operation_id).strip() + ":"

    for _attempt in range(_SELF_STALE_HEAD_HANDOFF_LIMIT):
        try:
            return _ORIGINAL_ADVANCE_WALK_FORWARD(
                control,
                reports,
                experiment_id=experiment_id,
                operation_id=operation_id,
                expected_sequence=sequence,
                expected_state_hash=state_hash,
                review_interval_months=review_interval_months,
                max_scan_rows=max_scan_rows,
                max_transitions=max_transitions,
            )
        except ValueError as exc:
            if "walk-forward experiment changed since it was read" not in str(exc):
                raise
            store = _impl._store(control)
            current = _impl._read_store(store, experiment_id, recent_events=0)
            current_sequence = int(current["sequence"])
            current_hash = str(current["state_hash"])
            if current_sequence <= sequence:
                raise
            tail = [
                event
                for event in _impl._events(store, experiment_id)
                if sequence < int(event.get("sequence", 0)) <= current_sequence
            ]
            if not tail:
                raise
            for event in tail:
                event_operation = str(event.get("operation_id") or "")
                if event_operation != operation_id and not event_operation.startswith(prefix):
                    raise
            sequence = current_sequence
            state_hash = current_hash

    raise ValueError(
        "walk-forward internal head changed repeatedly during one advance request"
    )



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

    readback = _impl._read_store(store, experiment_id, recent_events=0)
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

    readback = _impl._read_store(store, experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(
        candidate.get("reference_run") or definition.get("reference_run") or ""
    ).strip()
    if not reference_run:
        raise ValueError(
            "captured candidate and immutable experiment definition have no reference_run"
        )

    # OUTCOME FIREWALL: the paired LONG/SHORT artifact is opened only after
    # DECISION_FROZEN is durable, and only strategy_action's row is returned.
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


def _assert_chatgpt_view_allowed(
    control: Any, experiment_id: str
) -> None:
    # Test doubles may omit the runtime control object. Real MCP calls always
    # provide it, so monthly-mode enforcement still fails closed in production.
    if control is None:
        return
    readback = _impl._read_store(_impl._store(control), experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    batch_mode = _impl._batch_oos_mode(definition)
    if batch_mode is not None:
        boundary = "week-end" if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE else "month-end"
        raise ValueError(
            f"{batch_mode} does not accept per-trade ChatGPT views; use "
            "advance_walk_forward so the frozen strategy_action executes "
            f"deterministically until the {boundary} batch review"
        )


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
    _assert_chatgpt_view_allowed(control, experiment_id)
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
    autonomous_mode: bool = False,
    max_scan_slices: int = DEFAULT_AUTONOMOUS_SCAN_SLICES,
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

    batch_oos = False
    if control is not None:
        readback = _impl._read_store(_impl._store(control), experiment_id, recent_events=0)
        definition = (readback.get("manifest") or {}).get("definition") or {}
        batch_oos = _impl._batch_oos_enabled(definition)
    if str(settlement.get("result")) == "LOSS" and not batch_oos:
        packet = _ORIGINAL_BUILD_LOSS_REVIEW_PACKET(
            control, experiment_id=experiment_id, candidate_id=candidate_id
        )
        packet.update(
            sequence=settled["sequence"],
            state_hash=settled["state_hash"],
            settlement=settlement,
            **research,
        )
        return decorate_review_packet(packet)
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
    if autonomous_mode:
        return continue_walk_forward_autonomous(
            control,
            reports,
            experiment_id=experiment_id,
            operation_id=_impl._operation(operation_id, "autonomous"),
            expected_sequence=int(settled["sequence"]),
            expected_state_hash=str(settled["state_hash"]),
            review_interval_months=review_interval_months,
            max_scan_slices=max_scan_slices,
        )
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


def _teacher_flip_validation_inconsistency(
    updated: dict[str, Any],
    *,
    code: str,
    reason: str,
    opposite_side: str | None = None,
    trade_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stop teacher learning when immutable pair evidence cannot be reconciled."""
    context = trade_context or {}
    candidate_id = context.get("walk_forward_candidate_id")
    updated["status"] = TEACHER_FLIP_VALIDATION_INCONSISTENCY
    updated["inspection_required"] = True
    updated["flip_activation_allowed"] = False
    updated["validation_inconsistency"] = {
        "code": str(code).strip().upper(),
        "reason": str(reason).strip(),
        "walk_forward_candidate_id": candidate_id,
        "research_signal_index": context.get("research_signal_index"),
        "opposite_side": opposite_side,
    }
    updated["opposite_side_outcome"] = {
        "available": False,
        "side": opposite_side,
        "validation_code": str(code).strip().upper(),
        "reason": str(reason).strip(),
    }
    updated["review_rule"] = (
        "Inspection required. Do not record NO_CHANGE, FLIP_EVIDENCE, or FLIP_LEARNED "
        "while immutable paired outcome identity/validation is inconsistent. "
        "NO_CHANGE is a research judgment, not a data-validation fallback."
    )
    return updated


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
        "This resolved teacher loss is FLIP evidence only. Teacher evidence never changes "
        "walk-forward equity. Treat FLIP with the same structural learning standard as ENTRY: "
        "the immutable paired opposite-side outcome must verify a WIN, and FLIP_LEARNED "
        "requires a positive reusable opposite-side setup thesis and entry family. Repeated "
        "prior examples may strengthen confidence but are not required."
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
    paired_candidate_id = str(
        trade_context.get("walk_forward_candidate_id") or ""
    ).strip()
    if side not in {"LONG", "SHORT"}:
        return _teacher_flip_validation_inconsistency(
            updated,
            code="SIDE_MISMATCH",
            reason="teacher entry context did not expose a valid source side",
            trade_context=trade_context,
        )
    if not paired_candidate_id and signal_index in (None, ""):
        return _teacher_flip_validation_inconsistency(
            updated,
            code="PAIR_IDENTITY_MISSING",
            reason=(
                "teacher entry context exposed neither walk_forward_candidate_id "
                "nor research_signal_index"
            ),
            opposite_side="SHORT" if side == "LONG" else "LONG",
            trade_context=trade_context,
        )

    store = _impl._store(control)
    readback = _impl._read_store(store, experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", "")).strip()
    opposite = "SHORT" if side == "LONG" else "LONG"
    candidate = {
        "source_side": side,
        "reference_sample_id": trade_context.get("research_sample_id"),
        "reference_walk_forward_candidate_id": paired_candidate_id or None,
        "strategy_profile_key": profile,
        "entry_time": teacher.get("entry_time") or trade_context.get("entry_time"),
    }
    if signal_index not in (None, ""):
        candidate["research_signal_index"] = int(signal_index)

    try:
        outcome = _impl._outcome_row_after_decision(
            reports, reference_run, candidate, opposite
        )
    except ValueError as exc:
        message = str(exc)
        code = (
            "PAIR_LOOKUP_MISMATCH"
            if "no unique immutable paired Walk Forward outcome" in message
            else "OPPOSITE_OUTCOME_LOOKUP_ERROR"
        )
        return _teacher_flip_validation_inconsistency(
            updated,
            code=code,
            reason=message,
            opposite_side=opposite,
            trade_context=trade_context,
        )

    actual_side = str(outcome.get("side") or "").upper()
    if actual_side != opposite:
        return _teacher_flip_validation_inconsistency(
            updated,
            code="SIDE_MISMATCH",
            reason=f"paired outcome side {actual_side or '<missing>'} does not match {opposite}",
            opposite_side=opposite,
            trade_context=trade_context,
        )
    actual_pair_id = str(outcome.get("walk_forward_candidate_id") or "").strip()
    if paired_candidate_id and actual_pair_id != paired_candidate_id:
        return _teacher_flip_validation_inconsistency(
            updated,
            code="CANDIDATE_ID_MISMATCH",
            reason=(
                f"paired outcome candidate {actual_pair_id or '<missing>'} does not match "
                f"{paired_candidate_id}"
            ),
            opposite_side=opposite,
            trade_context=trade_context,
        )
    actual_signal = outcome.get("research_signal_index")
    if signal_index not in (None, "") and actual_signal not in (None, ""):
        if int(actual_signal) != int(signal_index):
            return _teacher_flip_validation_inconsistency(
                updated,
                code="SIGNAL_INDEX_MISMATCH",
                reason=(
                    f"paired outcome signal {actual_signal} does not match "
                    f"teacher signal {signal_index}"
                ),
                opposite_side=opposite,
                trade_context=trade_context,
            )

    result = str(outcome.get("result", "")).upper()
    if result not in {"WIN", "LOSS", "BREAKEVEN"}:
        return _teacher_flip_validation_inconsistency(
            updated,
            code="OUTCOME_RESULT_INVALID",
            reason=f"paired outcome result is not recognized: {result or '<missing>'}",
            opposite_side=opposite,
            trade_context=trade_context,
        )

    validation_code = {
        "WIN": "VERIFIED_WIN",
        "LOSS": "OPPOSITE_LOSS",
        "BREAKEVEN": "OPPOSITE_BREAKEVEN",
    }[result]
    updated["opposite_side_outcome"] = {
        "available": True,
        "side": opposite,
        "validation_code": validation_code,
        "outcome": outcome,
    }
    updated["flip_activation_allowed"] = result == "WIN"
    return updated

def _batch_review_evidence(
    control: Any,
    reports: Any,
    experiment_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the completed frozen period for one batch OOS review."""
    rule_update_policy = result.get("rule_update_policy") or {}
    mode = str(rule_update_policy.get("mode", "")).strip().upper()
    if mode not in _impl.BATCH_OOS_MODES:
        raise ValueError("batch review evidence requires a batch OOS mode")
    adaptive_policy = adaptive_weekly_policy(rule_update_policy)
    adaptive_weekly = (
        mode == _impl.WEEKLY_BATCH_OOS_MODE and adaptive_policy is not None
    )
    period_name = "week" if mode == _impl.WEEKLY_BATCH_OOS_MODE else "month"
    boundary_name = "week-end" if mode == _impl.WEEKLY_BATCH_OOS_MODE else "month-end"
    deferred_status = (
        _impl.WEEKLY_BATCH_DEFERRED
        if mode == _impl.WEEKLY_BATCH_OOS_MODE
        else _impl.MONTHLY_BATCH_DEFERRED
    )
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    start_raw = result.get("review_anchor_time")
    # Batch learning is always bounded by the scheduled OOS boundary. The
    # market cursor may be later when WAIT_UNTIL_CLOSED delays when the review
    # can be processed, but post-boundary outcomes belong to a later batch.
    end_raw = result.get("review_due_time") or result.get("current_market_cursor")
    start = (
        _impl._utc_timestamp(start_raw, "batch OOS review anchor")
        if start_raw not in (None, "")
        else None
    )
    end = (
        _impl._utc_timestamp(end_raw, "batch OOS review end")
        if end_raw not in (None, "")
        else None
    )

    def in_window(event: dict[str, Any]) -> bool:
        raw = event.get("effective_market_time")
        if raw in (None, ""):
            return False
        when = _impl._utc_timestamp(raw, "batch OOS event time")
        if start is not None and when <= start:
            return False
        if end is not None and when > end:
            return False
        return True

    captures: dict[str, dict[str, Any]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    teachers: list[dict[str, Any]] = []
    prospective: list[dict[str, Any]] = []

    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if event_type == "CANDIDATE_CONTEXT_CAPTURED" and candidate_id:
            captures[candidate_id] = deepcopy(payload)
            continue
        if event_type == "DECISION_FROZEN" and candidate_id:
            decisions[candidate_id] = deepcopy(payload)
            continue
        if (
            event_type == "TEACHER_RESOLVED"
            and str(payload.get("teacher_review_status") or "").upper()
            == deferred_status
            and in_window(event)
        ):
            teachers.append(
                {
                    "pair_id": payload.get("pair_id"),
                    "walk_forward_candidate_id": payload.get(
                        "walk_forward_candidate_id"
                    ),
                    "research_signal_index": payload.get("research_signal_index"),
                    "side": payload.get("side"),
                    "strategy_profile_key": payload.get("strategy_profile_key"),
                    "entry_time": payload.get("entry_time"),
                    "resolution_time": payload.get("resolution_time")
                    or event.get("effective_market_time"),
                    "result": payload.get("result"),
                    "pair_net_r": payload.get("pair_net_r"),
                    "teacher_learning_mode": payload.get("teacher_learning_mode"),
                    "paired_opposite_side": payload.get("paired_opposite_side"),
                    "paired_opposite_net_r": payload.get("paired_opposite_net_r"),
                    "entry_context": deepcopy(payload.get("batch_entry_context")),
                    "rule_coverage_at_observation": deepcopy(
                        payload.get("batch_current_rule_coverage")
                    ),
                }
            )
            continue
        if (
            event_type == "TRADE_RESOLVED"
            and str(payload.get("ledger", "RESEARCH")).upper() == "RESEARCH"
            and candidate_id
            and in_window(event)
        ):
            capture = captures.get(candidate_id, {})
            decision = decisions.get(candidate_id, {})
            prospective.append(
                {
                    "candidate_id": candidate_id,
                    "entry_time": capture.get("entry_time"),
                    "resolved_time": event.get("effective_market_time"),
                    "strategy_profile_key": capture.get("strategy_profile_key"),
                    "source_side": capture.get("source_side"),
                    "strategy_action": decision.get("strategy_action")
                    or decision.get("final_action")
                    or capture.get("rule_effective_side")
                    or capture.get("source_side"),
                    "matched_entry_groups": list(
                        capture.get("matched_entry_groups") or []
                    ),
                    "matched_veto_groups": list(
                        capture.get("matched_veto_groups") or []
                    ),
                    "matched_flip_groups": list(
                        capture.get("matched_flip_groups") or []
                    ),
                    "result": payload.get("result"),
                    "net_r": payload.get("net_r"),
                    "net_pnl": payload.get("net_pnl"),
                    "equity_before": payload.get("equity_before"),
                    "equity_after": payload.get("equity_after"),
                    "entry_context": deepcopy(capture.get("context")),
                }
            )

    reference_population: dict[str, Any] = {
        "available": False,
        "reason": "reference population summary unavailable",
    }
    adaptive_source_history: dict[str, Any] = {
        "available": False,
        "reason": "adaptive weekly source history disabled",
    }
    raw_strategy_benchmark: dict[str, Any] = {
        "available": False,
        "reason": "raw strategy benchmark disabled",
    }
    try:
        import duckdb

        readback = _impl._read_store(store, experiment_id, recent_events=0)
        definition = (readback.get("manifest") or {}).get("definition") or {}
        reference_run = str(definition.get("reference_run") or "").strip()
        manifest = reports.get_run_manifest(reference_run)
        run_dir = reports.resolve_run(reference_run)
        samples_path = _impl._artifact(
            manifest, run_dir, "research_sampling_trades"
        )
        if start is not None and end is not None:
            with duckdb.connect(":memory:") as connection:
                rows = connection.execute(
                    f"""
                    WITH source_rows AS (
                        SELECT
                            CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                            LOWER(CAST(strategy_profile_key AS VARCHAR)) AS profile,
                            UPPER(CAST(side AS VARCHAR)) AS side,
                            CAST(exit_time AS TIMESTAMPTZ) AS source_exit_time,
                            CAST(pair_net_r AS DOUBLE) AS source_net_r
                        FROM read_parquet('{_impl._quote(samples_path)}')
                        WHERE COALESCE(
                            CAST(walk_forward_candidate_source AS BOOLEAN), FALSE
                        )
                    ),
                    opposite_rows AS (
                        SELECT
                            CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                            CAST(exit_time AS TIMESTAMPTZ) AS opposite_exit_time,
                            CAST(pair_net_r AS DOUBLE) AS opposite_net_r
                        FROM read_parquet('{_impl._quote(samples_path)}')
                        WHERE NOT COALESCE(
                            CAST(walk_forward_candidate_source AS BOOLEAN), FALSE
                        )
                          AND CAST(exit_time AS TIMESTAMPTZ) <= ?
                    )
                    SELECT
                        s.profile,
                        s.side,
                        COUNT(*) AS observations,
                        SUM(CASE WHEN s.source_net_r > 0 THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN s.source_net_r < 0 THEN 1 ELSE 0 END) AS losses,
                        SUM(CASE WHEN s.source_net_r = 0 THEN 1 ELSE 0 END) AS breakevens,
                        SUM(s.source_net_r) AS net_r,
                        SUM(
                            CASE
                                WHEN o.candidate_id IS NOT NULL THEN 1
                                ELSE 0
                            END
                        ) AS opposite_resolved_by_boundary,
                        SUM(
                            CASE
                                WHEN s.source_net_r < 0
                                 AND o.candidate_id IS NOT NULL
                                 AND o.opposite_net_r > 0
                                THEN 1 ELSE 0
                            END
                        ) AS source_loss_opposite_win,
                        SUM(
                            CASE
                                WHEN s.source_net_r < 0
                                 AND o.candidate_id IS NOT NULL
                                 AND o.opposite_net_r <= 0
                                THEN 1 ELSE 0
                            END
                        ) AS source_loss_opposite_nonwin
                    FROM source_rows s
                    LEFT JOIN opposite_rows o USING(candidate_id)
                    WHERE s.source_exit_time > ?
                      AND s.source_exit_time <= ?
                    GROUP BY 1, 2
                    ORDER BY 1, 2
                    """,
                    [
                        end.to_pydatetime(),
                        start.to_pydatetime(),
                        end.to_pydatetime(),
                    ],
                ).fetchall()

            by_profile_side = []
            totals = {
                "observations": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "net_r": 0.0,
                "opposite_resolved_by_boundary": 0,
                "source_loss_opposite_win": 0,
                "source_loss_opposite_nonwin": 0,
            }
            for row in rows:
                item = {
                    "strategy_profile_key": row[0],
                    "side": row[1],
                    "observations": int(row[2] or 0),
                    "wins": int(row[3] or 0),
                    "losses": int(row[4] or 0),
                    "breakevens": int(row[5] or 0),
                    "net_r": float(row[6] or 0.0),
                    "opposite_resolved_by_boundary": int(row[7] or 0),
                    "source_loss_opposite_win": int(row[8] or 0),
                    "source_loss_opposite_nonwin": int(row[9] or 0),
                }
                by_profile_side.append(item)
                for key in totals:
                    totals[key] += item[key]
            totals["win_rate_pct"] = (
                round(100.0 * totals["wins"] / totals["observations"], 2)
                if totals["observations"]
                else None
            )
            reference_population = {
                "available": True,
                "reference_run": reference_run,
                "causal_window_basis": "source outcome resolved in completed batch",
                "opposite_outcome_rule": (
                    "counted only when the opposite row also resolved by the "
                    f"{boundary_name} boundary; later opposite outcomes remain hidden"
                ),
                "overall": totals,
                "by_profile_side": by_profile_side,
            }

    except Exception as exc:
        reference_population = {
            "available": False,
            "reason": str(exc)[:1000],
        }

    if adaptive_weekly and start is not None and end is not None:
        assert adaptive_policy is not None
        try:
            adaptive_source_history = build_adaptive_source_history(
                control,
                reports,
                experiment_id=experiment_id,
                end=end,
                policy=adaptive_policy,
            )
        except Exception as exc:
            adaptive_source_history = {
                "available": False,
                "reason": str(exc)[:1000],
            }
        if bool(adaptive_policy.get("benchmark_raw_strategy", True)):
            try:
                readback = _impl._read_store(store, experiment_id, recent_events=0)
                definition = (readback.get("manifest") or {}).get("definition") or {}
                raw_strategy_benchmark = build_raw_strategy_benchmark(
                    reports,
                    definition=definition,
                    start=start,
                    end=end,
                    adaptive_prospective=prospective,
                )
            except Exception as exc:
                raw_strategy_benchmark = {
                    "available": False,
                    "reason": str(exc)[:1000],
                }


    prospective_values = [
        float(row["net_r"])
        for row in prospective
        if row.get("net_r") is not None
    ]
    frozen_adaptive_summary = {
        "trades": len(prospective_values),
        "wins": sum(value > 0 for value in prospective_values),
        "losses": sum(value < 0 for value in prospective_values),
        "breakevens": sum(value == 0 for value in prospective_values),
        "win_rate_pct": (
            round(
                100.0
                * sum(value > 0 for value in prospective_values)
                / len(prospective_values),
                2,
            )
            if prospective_values
            else None
        ),
        "net_r": round(sum(prospective_values), 10)
        if prospective_values
        else 0.0,
    }
    adaptive_populations = (
        {
            "A_frozen_adaptive_oos": {
                "summary": frozen_adaptive_summary,
                "trades": deepcopy(prospective),
                "purpose": "What the rules frozen for the completed week actually produced.",
            },
            "B_raw_strategy_benchmark": deepcopy(raw_strategy_benchmark),
            "C_teacher_reference_population": deepcopy(reference_population),
        }
        if adaptive_weekly
        else None
    )

    return {
        "mode": mode,
        "cadence": "WEEKLY" if mode == _impl.WEEKLY_BATCH_OOS_MODE else "MONTHLY",
        "window": {
            "start_exclusive": start.isoformat() if start is not None else None,
            "end_inclusive": end.isoformat() if end is not None else None,
        },
        "rules_frozen_during_period": True,
        "teacher_observation_count": len(teachers),
        "prospective_trade_count": len(prospective),
        "reference_population_summary": reference_population,
        "adaptive_weekly": adaptive_weekly,
        "adaptive_policy": (
            deepcopy(adaptive_policy) if adaptive_weekly else None
        ),
        "adaptive_source_history": (
            adaptive_source_history if adaptive_weekly else None
        ),
        "raw_strategy_benchmark": (
            raw_strategy_benchmark if adaptive_weekly else None
        ),
        "adaptive_populations": adaptive_populations,
        "teacher_observations": teachers,
        "prospective_trades": prospective,
        "review_instruction": (
            f"Judge the completed {period_name} as one evidence batch. Do not backdate any "
            "change. ENTRY/VETO/FLIP changes recorded now become active only for "
            f"the next frozen OOS {period_name}; prefer repeated causal structures and "
            "consolidation over single-trade micro-rules. Before authoring new "
            "threshold rules, use the immutable reference run and completed "
            "window for feature-level winner/loss comparison when the aggregate "
            "population shows meaningful sample size. The server must remain "
            "descriptive: it may calculate recent performance, age, contradictions, "
            "regime availability and raw comparison, but it must not search threshold "
            "grids or automatically KEEP/REFINE/RETIRE/REPLACE/FLIP rules."
        ),
    }


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
    updated = _decorate_teacher_loss_packet(control, reports, experiment_id, updated)
    updated = decorate_review_packet(updated)
    if updated.get("status") == "PERIODIC_REVIEW_REQUIRED":
        # Periodic evidence is assembled automatically so a new chat cannot
        # skip the strategic review or rely on memory to request it.
        from crypto_strategy_lab.walk_forward_rule_analytics import (
            summarize_walk_forward_periodic_review,
        )

        updated["periodic_review_summary"] = summarize_walk_forward_periodic_review(
            control,
            reports,
            experiment_id=experiment_id,
            review_interval_months=int(
                updated.get("review_interval_months") or 3
            ),
            include_veto_effectiveness=True,
        )
        batch_mode = str(
            (updated.get("rule_update_policy") or {}).get("mode", "")
        ).upper()
        if batch_mode in _impl.BATCH_OOS_MODES:
            evidence = _batch_review_evidence(
                control, reports, experiment_id, updated
            )
            updated["batch_oos_evidence"] = evidence
            if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE:
                updated["weekly_batch_evidence"] = deepcopy(evidence)
                period_name = "week"
                future_key = "next_week_is_pure_oos"
                frozen_key = "rules_were_frozen_during_completed_week"
                primary_goal = "BATCH_LEARN_FREEZE_NEXT_WEEK"
            else:
                updated["monthly_batch_evidence"] = deepcopy(evidence)
                period_name = "month"
                future_key = "next_month_is_pure_oos"
                frozen_key = "rules_were_frozen_during_completed_month"
                primary_goal = "BATCH_LEARN_FREEZE_NEXT_MONTH"
            updated["methodology_prompt"] = {
                "primary_goal": primary_goal,
                frozen_key: True,
                "no_backdating": True,
                future_key: True,
                "prefer": [
                    "repeated causal structures across the completed batch",
                    "simple reusable ENTRY/VETO/FLIP families",
                    "consolidation or refinement before micro-rules",
                    f"keeping rules unchanged when {period_name}ly evidence is weak",
                ],
                "avoid": [
                    "reacting to one isolated trade",
                    f"using future-{period_name} evidence",
                    f"changing any completed-{period_name} decision",
                ],
            }
    return updated


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
    ``(decision_available_at, entry_time, research_signal_index, side)`` sort
    key and the candidate engine resumes strictly after that key on the next
    call. Teacher boundaries,
    rule mutations, reviews and trades invalidate an older cursor automatically.
    """
    if isinstance(max_scan_rows, bool) or not isinstance(max_scan_rows, int):
        raise ValueError("max_scan_rows must be an integer")
    if max_scan_rows < 1:
        raise ValueError("max_scan_rows must be positive")

    store, readback, events = _impl._verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    phase = str(((readback.get("derived_state") or {}).get("phase") or "")).upper()
    if phase == "BOOTSTRAP_RESEARCH":
        definition = (readback.get("manifest") or {}).get("definition") or {}
        protocol = definition.get("research_protocol") or {}
        return {
            "contract": _impl.ORCHESTRATOR_CONTRACT,
            "status": "BOOTSTRAP_RESEARCH_REQUIRED",
            "experiment_id": experiment_id,
            "sequence": int(expected_sequence),
            "state_hash": str(expected_state_hash),
            "bootstrap_start": protocol.get("bootstrap_start"),
            "walk_forward_start": protocol.get("walk_forward_start"),
            "reference_run": definition.get("reference_run"),
            "review_rule": (
                "Research the bootstrap window in-sample, define stable reusable BASE rules, "
                "then record one BOOTSTRAP review. Bootstrap evidence never changes walk-forward equity."
            ),
            "outcome_exposed": False,
        }

    bounded_rows = min(int(max_scan_rows), ACCELERATED_SCAN_ROWS)
    result = _advance_with_internal_head_handoff(
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

    required = (
        "decision_available_at",
        "entry_time",
        "research_signal_index",
        "side",
    )
    if any(cursor.get(name) in (None, "") for name in required):
        raise ValueError("candidate scan returned an incomplete resumable cursor")

    store = _impl._store(control)
    checkpoint = store.append_event(
        experiment_id,
        "CHECKPOINT_CREATED",
        {
            "checkpoint_type": SCAN_CHECKPOINT_TYPE,
            "decision_available_at": str(cursor["decision_available_at"]),
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
        effective_market_time=str(cursor["decision_available_at"]),
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
        previous_sequence = sequence
        previous_state_hash = state_hash
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
            if sequence == previous_sequence and state_hash == previous_state_hash:
                updated = deepcopy(result)
                updated["autonomous_contract"] = AUTONOMOUS_ORCHESTRATOR_CONTRACT
                updated["autonomous"] = _autonomous_metadata(
                    continue_without_user=False,
                    assistant_judgment_required=False,
                    stop_reason="INSPECTION_REQUIRED:DETERMINISTIC_NO_PROGRESS",
                    scan_slices=deterministic_slices + 1,
                    scan_checkpoints=checkpoints,
                    rows_scanned=total_rows,
                )
                return updated
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
