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
    PERIODIC_RULE_EVENT_TYPES,
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
from crypto_strategy_lab.walk_forward_teacher_compression import (
    CHATGPT_REVIEWED_STATUS,
    TEACHER_COMPRESSION_CONTRACT,
    teacher_compression_decision,
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
        current = _impl._store(control).read_fast(experiment_id, recent_events=0)
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
    batch_mode = _impl._batch_oos_mode(definition)
    batch_oos = batch_mode is not None
    batch_due = None
    if batch_oos and kind == "LOSS":
        period_name = "week" if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE else "month"
        boundary_name = "week-end" if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE else "month-end"
        raise ValueError(
            f"{batch_mode} defers prospective losses to the {boundary_name} batch "
            f"review; mid-{period_name} loss reviews and rule mutations are not allowed"
        )
    if batch_oos and kind in {"PERIODIC", "QUARTERLY"}:
        initial_anchor = _impl._initial_periodic_review_anchor(
            reports, definition, events
        )
        batch_due = _impl._review_due(
            definition,
            events,
            int(review_interval_months),
            initial_anchor=initial_anchor,
        )
        if batch_due is None:
            boundary_name = "week-end" if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE else "month-end"
            raise ValueError(
                f"{batch_mode} rules are frozen until the next {boundary_name} "
                "review boundary; a periodic review cannot be recorded yet"
            )
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
    elif batch_due is not None and kind in {"PERIODIC", "QUARTERLY"}:
        effective = _impl._utc_timestamp(
            batch_due["review_due_time"], "batch OOS scheduled review boundary"
        )
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
    if kind == "LOSS":
        allowed = {"VETO_LEARNED", "ENTRY_REFINED", "FLIP_LEARNED"}
    elif kind in {"PERIODIC", "QUARTERLY"}:
        allowed = set(PERIODIC_RULE_EVENT_TYPES)
    else:
        allowed = set(_impl.RULE_EVENT_TYPES)
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
    if batch_due is not None:
        payload["scheduled_review_due_time"] = str(batch_due["review_due_time"])
        payload["review_observed_market_cursor"] = str(
            batch_due.get("current_market_cursor") or batch_due["review_due_time"]
        )
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
        review_interval_months=_impl._effective_review_interval(
            definition, review_interval_months
        ),
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
    """Atomically record a teacher winner ENTRY review or paired-loss FLIP review."""
    store = _impl._store(control)
    readback, _all_events, events = _verified_prefix(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    definition = (readback.get("manifest") or {}).get("definition") or {}
    batch_mode = _impl._batch_oos_mode(definition)
    if batch_mode is not None:
        boundary_name = "week-end" if batch_mode == _impl.WEEKLY_BATCH_OOS_MODE else "month-end"
        raise ValueError(
            f"{batch_mode} records teacher observations automatically and "
            f"defers all teacher-driven rule changes to the {boundary_name} batch review"
        )
    reference_run = str(definition.get("reference_run", ""))
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    reference_artifacts = manifest.get("artifacts") or {}
    teacher_phase_context_available = (
        "research_sampling_trades" in reference_artifacts
        and "feature_context" in reference_artifacts
    )
    protocol = definition.get("research_protocol") or {}
    minimum_entry_time = (
        protocol.get("walk_forward_start")
        if str(protocol.get("mode", "")).upper() == "BOOTSTRAP_THEN_WF"
        else None
    )
    teacher = (
        _impl._next_teacher(
            manifest,
            run_dir,
            events,
            minimum_entry_time=minimum_entry_time,
        )
        if minimum_entry_time is not None
        else _impl._next_teacher(manifest, run_dir, events)
    )
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

    base_phase_packet: dict[str, Any] | None = None
    checked_loss_packet: dict[str, Any] | None = None
    if teacher_result == "LOSS":
        if decision_value not in {"NO_CHANGE", "FLIP_EVIDENCE", "FLIP_LEARNED"}:
            raise ValueError(
                "teacher loss decision must be NO_CHANGE, FLIP_EVIDENCE, or FLIP_LEARNED"
            )
        base_phase_packet = _impl._teacher_review_packet(
            control,
            reports,
            experiment_id=experiment_id,
            expected_sequence=expected_sequence,
            expected_state_hash=expected_state_hash,
            teacher_boundary=boundary,
        )
        checked_loss_packet = _decorate_teacher_loss_packet(
            control, reports, experiment_id, deepcopy(base_phase_packet)
        )
        if bool(checked_loss_packet.get("inspection_required")) or str(
            checked_loss_packet.get("status", "")
        ).upper() == "TEACHER_FLIP_VALIDATION_INCONSISTENCY":
            inconsistency = checked_loss_packet.get("validation_inconsistency") or {}
            code = str(inconsistency.get("code") or "VALIDATION_INCONSISTENCY")
            reason = str(inconsistency.get("reason") or "paired outcome could not be verified")
            raise ValueError(
                f"teacher loss review blocked by {code}: {reason}; "
                "inspect immutable paired evidence before recording any research decision"
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

    if base_phase_packet is None and teacher_phase_context_available:
        base_phase_packet = _impl._teacher_review_packet(
            control,
            reports,
            experiment_id=experiment_id,
            expected_sequence=expected_sequence,
            expected_state_hash=expected_state_hash,
            teacher_boundary=boundary,
        )
    if base_phase_packet is None:
        # Compatibility path for legacy/minimal reference runs that can still
        # record a valid teacher review but do not expose the immutable context
        # required for deterministic phase compression. Persist no usable phase
        # fingerprint so this review can never silently become a compression
        # baseline; a later fully-audited teacher will surface once.
        phase_decision = {
            "action": "SURFACE",
            "reason": "PHASE_CONTEXT_UNAVAILABLE",
            "audit": {},
            "compared_to_teacher_id": None,
            "confirmation_of_teacher_id": None,
            "confirmation_rule_ids": [],
            "confirmation_rule_versions": [],
            "episode_review_count": 0,
            "episode_review_budget": None,
        }
    else:
        phase_decision = teacher_compression_decision(base_phase_packet, events)
    phase_audit = deepcopy(phase_decision.get("audit") or {})

    if teacher_result == "LOSS":
        if decision_value in {"NO_CHANGE", "FLIP_EVIDENCE"} and canonical:
            raise ValueError(
                f"{decision_value} records evidence only and cannot activate a FLIP rule"
            )
        if decision_value == "FLIP_LEARNED":
            if not canonical:
                raise ValueError("FLIP_LEARNED requires at least one FLIP_LEARNED rule event")
            checked = checked_loss_packet or {}
            if not bool(checked.get("flip_activation_allowed")):
                validation = (
                    (checked.get("opposite_side_outcome") or {}).get("validation_code")
                    or "NOT_VERIFIED"
                )
                raise ValueError(
                    "teacher loss cannot activate FLIP: the immutable paired opposite-side "
                    f"outcome is not a verified WIN ({validation})"
                )

    teacher_payload = {
        **deepcopy(boundary),
        "result": teacher_result,
        "review_decision": decision_value,
        "teacher_review_status": CHATGPT_REVIEWED_STATUS,
        "review_surface_reason": phase_decision.get("reason"),
        "compression_contract": TEACHER_COMPRESSION_CONTRACT,
        "compared_to_teacher_id": phase_decision.get("compared_to_teacher_id"),
        "confirmation_of_teacher_id": phase_decision.get(
            "confirmation_of_teacher_id"
        ),
        "confirmation_rule_ids": list(
            phase_decision.get("confirmation_rule_ids") or []
        ),
        "confirmation_rule_versions": list(
            phase_decision.get("confirmation_rule_versions") or []
        ),
        "episode_review_count": phase_decision.get("episode_review_count"),
        "episode_review_budget": phase_decision.get("episode_review_budget"),
        "teacher_phase_audit": phase_audit,
        "phase_fingerprint": phase_audit.get("phase_fingerprint"),
        "actionability_fingerprint": phase_audit.get("actionability_fingerprint"),
        "structural_phase_fingerprint": phase_audit.get(
            "structural_fingerprint"
        ),
        "active_rule_matches": list(
            phase_audit.get("active_rule_matches") or []
        ),
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
        review_interval_months=_impl._effective_review_interval(
            definition, review_interval_months
        ),
        autonomous_mode=autonomous_mode,
        max_scan_slices=max_scan_slices,
    )
