"""Validated atomic review writers for causal walk-forward research.

This facade preflights proposed ENTRY/VETO/FLIP mutations through the Strategy
Builder compiler, then commits the review marker and all rule events in one
atomic batch. Invalid rules therefore leave the experiment sequence/hash
unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl
from crypto_strategy_lab.walk_forward_orchestrator import (
    DEFAULT_AUTONOMOUS_SCAN_SLICES,
    advance_walk_forward,
    continue_walk_forward_autonomous,
    _decorate_teacher_loss_packet,
)
from crypto_strategy_lab.walk_forward_rule_validation import (
    append_events_atomic,
    preflight_rule_events,
    rule_event_schema,
    _verified_prefix,
)
from crypto_strategy_lab.walk_forward_research_policy import (
    decorate_review_packet,
    validate_loss_methodology,
    validate_periodic_methodology,
    validate_teacher_methodology,
)


def _canonical_rule_specs(
    canonical: list[dict[str, Any]],
    operation_id: str,
    effective_from: str,
) -> list[dict[str, Any]]:
    return [
        {
            "event_type": item["event_type"],
            "payload": deepcopy(item["payload"]),
            "operation_id": _impl._operation(operation_id, f"rule-{index}"),
            "effective_market_time": effective_from,
            "source": "CHATGPT_RESEARCH",
        }
        for index, item in enumerate(canonical, 1)
    ]


def _with_rule_schema(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") not in {
        "TEACHER_REVIEW_REQUIRED",
        "TEACHER_LOSS_REVIEW_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
        "PERIODIC_REVIEW_REQUIRED",
        "BOOTSTRAP_RESEARCH_REQUIRED",
    }:
        return result
    updated = deepcopy(result)
    updated.setdefault("rule_event_schema", rule_event_schema())
    return decorate_review_packet(updated)


def _advance_after_batch(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    operation_id: str,
    batch: dict[str, Any],
    review_interval_months: int,
    autonomous_mode: bool = False,
    max_scan_slices: int = DEFAULT_AUTONOMOUS_SCAN_SLICES,
) -> dict[str, Any]:
    sequence = int(batch["sequence"])
    state_hash = str(batch["state_hash"])
    if bool(batch.get("idempotent_replay")):
        current = _impl._store(control).read(experiment_id, recent_events=0)
        sequence = int(current["sequence"])
        state_hash = str(current["state_hash"])
    if autonomous_mode:
        return _with_rule_schema(
            continue_walk_forward_autonomous(
                control,
                reports,
                experiment_id=experiment_id,
                operation_id=_impl._operation(operation_id, "autonomous"),
                expected_sequence=sequence,
                expected_state_hash=state_hash,
                review_interval_months=review_interval_months,
                max_scan_slices=max_scan_slices,
            )
        )
    return _with_rule_schema(
        advance_walk_forward(
            control,
            reports,
            experiment_id=experiment_id,
            operation_id=_impl._operation(operation_id, "advance"),
            expected_sequence=sequence,
            expected_state_hash=state_hash,
            review_interval_months=review_interval_months,
        )
    )


def record_walk_forward_review(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    review_type: str,
    decision: str,
    notes: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    candidate_id: str | None = None,
    rule_events: list[dict[str, Any]] | None = None,
    loss_diagnosis: str | None = None,
    failure_mechanism: str | None = None,
    periodic_rule_action: str | None = None,
    periodic_rationale: str | None = None,
    auto_advance: bool = True,
    review_interval_months: int = 3,
    autonomous_mode: bool = False,
    max_scan_slices: int = DEFAULT_AUTONOMOUS_SCAN_SLICES,
) -> dict[str, Any]:
    """Validate first, then atomically record a bootstrap/loss/periodic review and rules."""
    store = _impl._store(control)
    readback, _all_events, events = _verified_prefix(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    kind = str(review_type).strip().upper()
    if kind not in {"BOOTSTRAP", "LOSS", "PERIODIC", "QUARTERLY"}:
        raise ValueError("review_type must be BOOTSTRAP, LOSS, or PERIODIC/QUARTERLY")
    text = str(notes).strip()
    if not str(decision).strip():
        raise ValueError("decision cannot be empty")
    definition = (readback.get("manifest") or {}).get("definition") or {}
    phase = str(((readback.get("derived_state") or {}).get("phase") or "")).upper()
    if kind == "BOOTSTRAP":
        protocol = definition.get("research_protocol") or {}
        if phase != "BOOTSTRAP_RESEARCH":
            raise ValueError("BOOTSTRAP review is only valid during BOOTSTRAP_RESEARCH")
        if str(protocol.get("mode", "")).upper() != "BOOTSTRAP_THEN_WF":
            raise ValueError("BOOTSTRAP review requires BOOTSTRAP_THEN_WF protocol")
        raw_start = protocol.get("walk_forward_start")
        if raw_start in (None, ""):
            raise ValueError("bootstrap protocol has no walk_forward_start")
        effective = _impl._utc_timestamp(raw_start, "research_protocol.walk_forward_start")
    else:
        effective = _impl._max_event_time(events)
        if effective is None:
            raise ValueError("review requires an established market-time cursor")
    subject = str(candidate_id or "").strip()
    if kind == "LOSS":
        pending = _impl._unreviewed_loss(events)
        if pending is None:
            raise ValueError("there is no unresolved loss review")
        pending_id = str((pending.get("payload") or {}).get("candidate_id", ""))
        if not subject:
            subject = pending_id
        if subject != pending_id:
            raise ValueError(f"loss review must resolve pending candidate {pending_id}")

    effective_iso = effective.isoformat()
    allowed = (
        {"VETO_LEARNED", "ENTRY_REFINED", "FLIP_LEARNED"}
        if kind == "LOSS"
        else set(_impl.RULE_EVENT_TYPES)
    )
    evidence_source = "BOOTSTRAP" if kind == "BOOTSTRAP" else "PROSPECTIVE_WF"
    preflight = preflight_rule_events(
        control,
        reports,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        rule_events=list(rule_events or []),
        evidence_source=evidence_source,
        effective_from=effective_iso,
        default_reason=text,
        allowed_types=allowed,
    )
    canonical = list(preflight["canonical_rule_events"])
    if kind == "LOSS":
        methodology = validate_loss_methodology(
            canonical,
            loss_diagnosis=loss_diagnosis,
            failure_mechanism=failure_mechanism,
        )
    elif kind == "BOOTSTRAP":
        if not any(item.get("event_type") == "ENTRY_LEARNED" for item in canonical):
            raise ValueError("BOOTSTRAP review must freeze at least one ENTRY_LEARNED base rule")
        methodology = {
            "bootstrap_methodology_contract": "bootstrap_base_rule_method_v1",
            "bootstrap_rule_count": len(canonical),
            "bootstrap_walk_forward_start": effective_iso,
        }
    else:
        methodology = validate_periodic_methodology(
            canonical,
            periodic_rule_action=periodic_rule_action,
            periodic_rationale=periodic_rationale,
        )
    payload = {
        "review_type": "PERIODIC" if kind == "QUARTERLY" else kind,
        "candidate_id": subject or None,
        "decision": str(decision).strip().upper(),
        "notes": text,
        "reviewed_state_hash": str(expected_state_hash),
        "validated_rule_event_count": len(canonical),
        "rule_event_schema_contract": preflight["rule_event_schema"]["contract"],
        **methodology,
    }
    specs = [
        {
            "event_type": "REVIEW_COMPLETED",
            "payload": payload,
            "operation_id": _impl._operation(operation_id, "review"),
            "effective_market_time": effective_iso,
            "source": "CHATGPT_BOOTSTRAP_RESEARCH" if kind == "BOOTSTRAP" else "CHATGPT_RESEARCH",
        },
        *_canonical_rule_specs(canonical, operation_id, effective_iso),
    ]
    if kind == "BOOTSTRAP":
        specs.append(
            {
                "event_type": "PHASE_CHANGED",
                "payload": {
                    "phase": "RESEARCH_WF",
                    "reason": "bootstrap base rules frozen at walk_forward_start",
                },
                "operation_id": _impl._operation(operation_id, "phase-research-wf"),
                "effective_market_time": effective_iso,
                "source": "CHATGPT_BOOTSTRAP_RESEARCH",
            }
        )
    batch = append_events_atomic(
        store,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        specs=specs,
    )
    if not auto_advance:
        return {
            "contract": _impl.ORCHESTRATOR_CONTRACT,
            "status": "REVIEW_RECORDED",
            "experiment_id": experiment_id,
            "sequence": batch["sequence"],
            "state_hash": batch["state_hash"],
            "canonical_rule_events": canonical,
            "rule_event_schema": preflight["rule_event_schema"],
            "atomic_batch": True,
            "idempotent_replay": bool(batch.get("idempotent_replay")),
        }
    return _advance_after_batch(
        control,
        reports,
        experiment_id=experiment_id,
        operation_id=operation_id,
        batch=batch,
        review_interval_months=review_interval_months,
        autonomous_mode=autonomous_mode,
        max_scan_slices=max_scan_slices,
    )


def record_walk_forward_teacher_review(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    teacher_pair_id: str,
    decision: str,
    notes: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    rule_events: list[dict[str, Any]] | None = None,
    setup_thesis: str | None = None,
    entry_family: str | None = None,
    auto_advance: bool = True,
    review_interval_months: int = 3,
    autonomous_mode: bool = False,
    max_scan_slices: int = DEFAULT_AUTONOMOUS_SCAN_SLICES,
) -> dict[str, Any]:
    """Atomically record a teacher winner ENTRY review or enabled 1R loss FLIP review."""
    store = _impl._store(control)
    readback, _all_events, events = _verified_prefix(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", ""))
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    # _impl._next_teacher is the policy-aware selector installed by the candidate
    # facade. Existing direct callers remain winner-only; MCP can explicitly
    # enable 1R teacher-loss chronology for the duration of this operation.
    teacher = _impl._next_teacher(manifest, run_dir, events)
    if teacher is None:
        raise ValueError("there is no unresolved teacher trade")
    boundary, resolution_time = teacher
    if str(boundary.get("pair_id")) != str(teacher_pair_id):
        raise ValueError(
            f"next teacher is pair {boundary.get('pair_id')}, not {teacher_pair_id}"
        )

    teacher_result = str(boundary.get("result", "WIN")).upper()
    decision_value = str(decision).strip().upper()
    notes_text = str(notes).strip()
    effective_iso = resolution_time.isoformat()

    if teacher_result == "LOSS":
        if decision_value not in {"NO_CHANGE", "FLIP_EVIDENCE", "FLIP_LEARNED"}:
            raise ValueError(
                "teacher loss decision must be NO_CHANGE, FLIP_EVIDENCE, or FLIP_LEARNED"
            )
        allowed_types = {"FLIP_LEARNED"}
    else:
        allowed_types = {"ENTRY_LEARNED", "ENTRY_REFINED"}

    preflight = preflight_rule_events(
        control,
        reports,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        rule_events=list(rule_events or []),
        evidence_source="TEACHER",
        effective_from=effective_iso,
        default_reason=notes_text,
        allowed_types=allowed_types,
    )
    canonical = list(preflight["canonical_rule_events"])
    methodology = validate_teacher_methodology(
        canonical,
        teacher_result=teacher_result,
        setup_thesis=setup_thesis,
        entry_family=entry_family,
    )

    if teacher_result == "LOSS":
        if decision_value in {"NO_CHANGE", "FLIP_EVIDENCE"} and canonical:
            raise ValueError(
                f"{decision_value} records evidence only and cannot activate a FLIP rule"
            )
        if decision_value == "FLIP_LEARNED":
            if not canonical:
                raise ValueError("FLIP_LEARNED requires at least one FLIP_LEARNED rule event")
            base_packet = _impl._teacher_review_packet(
                control,
                reports,
                experiment_id=experiment_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
                teacher_boundary=boundary,
            )
            checked = _decorate_teacher_loss_packet(
                control, reports, experiment_id, base_packet
            )
            if not bool(checked.get("flip_activation_allowed")):
                raise ValueError(
                    "teacher loss cannot activate FLIP: opposite-side immutable 1R outcome is not a verified WIN"
                )

    teacher_payload = {
        **deepcopy(boundary),
        "result": teacher_result,
        "review_decision": decision_value,
        "notes": notes_text,
        "validated_rule_event_count": len(canonical),
        "rule_event_schema_contract": preflight["rule_event_schema"]["contract"],
        **methodology,
    }
    specs = [
        {
            "event_type": "TEACHER_RESOLVED",
            "payload": teacher_payload,
            "operation_id": _impl._operation(operation_id, "teacher"),
            "effective_market_time": effective_iso,
            "source": "CHATGPT_RESEARCH",
        },
        *_canonical_rule_specs(canonical, operation_id, effective_iso),
    ]
    batch = append_events_atomic(
        store,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        specs=specs,
    )
    if not auto_advance:
        return {
            "contract": _impl.ORCHESTRATOR_CONTRACT,
            "status": "TEACHER_REVIEW_RECORDED",
            "experiment_id": experiment_id,
            "sequence": batch["sequence"],
            "state_hash": batch["state_hash"],
            "teacher_result": teacher_result,
            "canonical_rule_events": canonical,
            "rule_event_schema": preflight["rule_event_schema"],
            "atomic_batch": True,
            "idempotent_replay": bool(batch.get("idempotent_replay")),
        }
    return _advance_after_batch(
        control,
        reports,
        experiment_id=experiment_id,
        operation_id=operation_id,
        batch=batch,
        review_interval_months=review_interval_months,
        autonomous_mode=autonomous_mode,
        max_scan_slices=max_scan_slices,
    )
