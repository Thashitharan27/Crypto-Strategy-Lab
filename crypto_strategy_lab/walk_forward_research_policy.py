"""Versioned methodology contract for causal walk-forward rule learning.

This module turns research lessons into machine-visible review requirements.  It
does not decide whether a rule should exist and never mutates experiment state.
Instead it:

* decorates teacher/loss/periodic judgment packets with the active methodology;
* validates the structured diagnosis attached to any rule-authoring review;
* keeps NO_CHANGE cheap so the workflow is never forced to invent a rule.

The contract is intentionally independent of chat memory.  A future ChatGPT
session receives the same requirements from MCP review packets and rule-writing
calls reject incompatible/missing methodology fields.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


RESEARCH_POLICY_CONTRACT = "causal_walk_forward_entry_veto_method_v1"

LOSS_DIAGNOSES = frozenset({
    "ENTRY_TOO_BROAD",
    "EXCEPTIONAL_CONTRADICTION",
    "DIRECTION_THESIS_WRONG",
    "NO_CLEAR_CAUSAL_LESSON",
})

ENTRY_FAMILIES = frozenset({
    "CONTINUATION",
    "PULLBACK",
    "BREAKOUT",
    "REVERSAL",
    "RANGE_REVERSION",
})

PERIODIC_RULE_ACTIONS = frozenset({
    "CONSOLIDATE_OR_REFINE",
    "STRUCTURAL_NEW_RULE",
    "RETIRE_OR_PROMOTE",
})


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def research_policy_schema() -> dict[str, Any]:
    """Return the versioned methodology that every review packet advertises."""
    return {
        "contract": RESEARCH_POLICY_CONTRACT,
        "principles": [
            "ENTRY describes the positive reusable reason a trade deserves to exist.",
            "VETO describes a specific exceptional contradiction that invalidates an otherwise-valid ENTRY.",
            "A repeated version of the same contradiction is evidence to refine/consolidate the ENTRY before adding another VETO.",
            "A teacher winner is evidence, not an automatic ENTRY rule; NO_CHANGE is valid when the thesis is not reusable.",
            "A prospective loss is evidence, not an automatic VETO; NO_CHANGE is preferred when no distinct causal mechanism is supported.",
            "For multi-R targets, room to opposing higher-timeframe support/resistance is an ENTRY-quality dimension, not something momentum can automatically override.",
            "BREAKOUT logic must remain distinguishable from normal CONTINUATION/PULLBACK logic so a successful breakout does not weaken room requirements elsewhere.",
            "Periodic reviews are primarily for simplification, consolidation, regime-level diagnosis, and evidence sufficiency—not for accumulating micro-rules.",
            "ChatGPT disagreement is diagnostic evidence only; any rule must encode the concrete structural reason for the disagreement.",
        ],
        "loss_review": {
            "diagnoses": sorted(LOSS_DIAGNOSES),
            "requirements_when_authoring_rules": {
                "loss_diagnosis": "required",
                "failure_mechanism": "required, concrete, reusable, and causal",
            },
            "compatibility": {
                "ENTRY_REFINED": "ENTRY_TOO_BROAD",
                "VETO_LEARNED": "EXCEPTIONAL_CONTRADICTION",
                "FLIP_LEARNED": "DIRECTION_THESIS_WRONG",
                "NO_CLEAR_CAUSAL_LESSON": "must not author a rule",
            },
            "sequence": [
                "First decide whether the original ENTRY definition is too broad.",
                "If not, decide whether a specific exceptional contradiction invalidated an otherwise-good ENTRY.",
                "If neither is supported, record NO_CHANGE.",
                "Before adding a VETO, compare the mechanism with prior losses of the matched ENTRY; repeated mechanism favors ENTRY refinement/consolidation.",
            ],
        },
        "teacher_winner_review": {
            "entry_families": sorted(ENTRY_FAMILIES),
            "requirements_when_authoring_entry": {
                "setup_thesis": "required positive reusable setup thesis",
                "entry_family": "required",
            },
            "rule": (
                "Winning is insufficient by itself. Learn/refine ENTRY only when "
                "the teacher winner expresses a reusable positive setup structure."
            ),
        },
        "periodic_review": {
            "rule_actions": sorted(PERIODIC_RULE_ACTIONS),
            "requirements_when_authoring_rules": {
                "periodic_rule_action": "required",
                "periodic_rationale": "required",
            },
            "questions": [
                "Are ENTRY definitions becoming too permissive?",
                "Are VETOs accumulating around the same failure mechanism?",
                "Should repeated VETO mechanisms be consolidated into an ENTRY refinement?",
                "Are ENTRY/VETO families redundant or heavily overlapping?",
                "Are VETOs avoiding more losses than wins?",
                "Are rule-version results improving or deteriorating?",
                "Is evidence mature enough to change a rule, or is the sample still weak?",
                "Does performance reflect a regime change or recent noise?",
            ],
        },
    }


def decorate_review_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Attach methodology and targeted prompts to one judgment packet."""
    if not isinstance(packet, dict):
        return packet
    status = _upper(packet.get("status"))
    if status not in {
        "TEACHER_REVIEW_REQUIRED",
        "TEACHER_LOSS_REVIEW_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
        "PERIODIC_REVIEW_REQUIRED",
        "BOOTSTRAP_RESEARCH_REQUIRED",
    }:
        return packet

    updated = deepcopy(packet)
    updated["research_policy"] = research_policy_schema()

    if status == "BOOTSTRAP_RESEARCH_REQUIRED":
        updated["methodology_prompt"] = {
            "primary_goal": "FREEZE_STABLE_REUSABLE_BASE_RULES",
            "bootstrap_is_in_sample": True,
            "bootstrap_equity_counts_as_wf": False,
            "prefer": [
                "coherent trading thesis",
                "adequate sample size",
                "multiple regimes where available",
                "stable threshold neighborhoods",
                "simple reusable ENTRY/VETO families",
            ],
            "avoid": [
                "maximizing bootstrap win rate",
                "single-trade rules",
                "isolated optimum thresholds",
                "forcing unsupported profile coverage",
            ],
            "completion": "record one BOOTSTRAP review with at least one ENTRY_LEARNED base rule",
        }

    elif status == "LOSS_REVIEW_REQUIRED":
        group_stats = (
            ((updated.get("causal_history") or {}).get("entry_group_stats") or {})
            if isinstance(updated.get("causal_history"), dict)
            else {}
        )
        repeated = []
        for group_id, stats in group_stats.items():
            if not isinstance(stats, dict):
                continue
            prior_losses = int(stats.get("losses") or 0)
            if prior_losses >= 1:
                repeated.append({
                    "entry_group": str(group_id),
                    "prior_losses_before_current_loss": prior_losses,
                    "instruction": (
                        "Compare the current failure mechanism with these prior losses. "
                        "If the same mechanism repeats, prefer ENTRY refinement/consolidation "
                        "over another narrow VETO."
                    ),
                })
        updated["methodology_prompt"] = {
            "required_first_classification": "loss_diagnosis",
            "repeat_failure_attention": repeated,
            "default_when_unclear": "NO_CHANGE",
        }

    elif status == "TEACHER_REVIEW_REQUIRED":
        updated["methodology_prompt"] = {
            "required_before_entry_learning": ["setup_thesis", "entry_family"],
            "default_when_thesis_is_not_reusable": "NO_CHANGE",
            "separate_breakout_logic": True,
        }

    elif status == "TEACHER_LOSS_REVIEW_REQUIRED":
        updated["methodology_prompt"] = {
            "teacher_loss_rule": (
                "Do not infer a FLIP from the loss alone. Opposite-side immutable "
                "evidence must independently verify the alternative."
            )
        }

    elif status == "PERIODIC_REVIEW_REQUIRED":
        updated["methodology_prompt"] = {
            "primary_goal": "SIMPLIFY_CONSOLIDATE_AND_DIAGNOSE",
            "avoid": "MICRO_RULE_ACCUMULATION",
            "required_before_rule_authoring": [
                "periodic_rule_action",
                "periodic_rationale",
            ],
        }

    return updated


def validate_loss_methodology(
    canonical_rule_events: Iterable[dict[str, Any]],
    *,
    loss_diagnosis: str | None,
    failure_mechanism: str | None,
) -> dict[str, Any]:
    """Validate rule-writing methodology for a prospective WF loss review."""
    canonical = list(canonical_rule_events)
    diagnosis = _upper(loss_diagnosis)
    mechanism = _clean(failure_mechanism)

    if diagnosis and diagnosis not in LOSS_DIAGNOSES:
        raise ValueError(
            "loss_diagnosis must be one of: " + ", ".join(sorted(LOSS_DIAGNOSES))
        )
    if not diagnosis:
        raise ValueError(
            "every prospective loss review requires loss_diagnosis; use "
            "NO_CLEAR_CAUSAL_LESSON when no repeatable mechanism is supported"
        )
    if diagnosis != "NO_CLEAR_CAUSAL_LESSON" and not mechanism:
        raise ValueError(
            "a specific loss_diagnosis requires a concrete failure_mechanism"
        )
    if not canonical:
        return {
            "research_policy_contract": RESEARCH_POLICY_CONTRACT,
            "loss_diagnosis": diagnosis,
            "failure_mechanism": mechanism or None,
        }

    if diagnosis == "NO_CLEAR_CAUSAL_LESSON":
        raise ValueError(
            "NO_CLEAR_CAUSAL_LESSON cannot author a rule; record NO_CHANGE instead"
        )

    event_types = {_upper(item.get("event_type")) for item in canonical}
    if "ENTRY_REFINED" in event_types and diagnosis != "ENTRY_TOO_BROAD":
        raise ValueError(
            "ENTRY_REFINED from a loss requires loss_diagnosis=ENTRY_TOO_BROAD"
        )
    if "VETO_LEARNED" in event_types and diagnosis != "EXCEPTIONAL_CONTRADICTION":
        raise ValueError(
            "VETO_LEARNED from a loss requires loss_diagnosis=EXCEPTIONAL_CONTRADICTION"
        )
    if "FLIP_LEARNED" in event_types and diagnosis != "DIRECTION_THESIS_WRONG":
        raise ValueError(
            "FLIP_LEARNED from a loss requires loss_diagnosis=DIRECTION_THESIS_WRONG"
        )

    incompatible = {
        "ENTRY_REFINED": "ENTRY_TOO_BROAD",
        "VETO_LEARNED": "EXCEPTIONAL_CONTRADICTION",
        "FLIP_LEARNED": "DIRECTION_THESIS_WRONG",
    }
    required = {incompatible[event] for event in event_types if event in incompatible}
    if len(required) > 1:
        raise ValueError(
            "one loss review cannot mix rule types that require conflicting causal diagnoses"
        )

    return {
        "research_policy_contract": RESEARCH_POLICY_CONTRACT,
        "loss_diagnosis": diagnosis,
        "failure_mechanism": mechanism,
    }


def validate_teacher_methodology(
    canonical_rule_events: Iterable[dict[str, Any]],
    *,
    teacher_result: str,
    setup_thesis: str | None,
    entry_family: str | None,
) -> dict[str, Any]:
    """Require a positive reusable thesis before teacher-winner ENTRY learning."""
    canonical = list(canonical_rule_events)
    result = _upper(teacher_result)
    thesis = _clean(setup_thesis)
    family = _upper(entry_family)

    if family and family not in ENTRY_FAMILIES:
        raise ValueError(
            "entry_family must be one of: " + ", ".join(sorted(ENTRY_FAMILIES))
        )

    has_entry_rule = any(
        _upper(item.get("event_type")) in {"ENTRY_LEARNED", "ENTRY_REFINED"}
        for item in canonical
    )
    if result == "WIN" and has_entry_rule:
        if not thesis:
            raise ValueError(
                "teacher-winner ENTRY learning requires setup_thesis; winning alone is insufficient"
            )
        if not family:
            raise ValueError(
                "teacher-winner ENTRY learning requires entry_family"
            )

    return {
        "research_policy_contract": RESEARCH_POLICY_CONTRACT,
        "setup_thesis": thesis or None,
        "entry_family": family or None,
    }


def validate_periodic_methodology(
    canonical_rule_events: Iterable[dict[str, Any]],
    *,
    periodic_rule_action: str | None,
    periodic_rationale: str | None,
) -> dict[str, Any]:
    """Require strategic intent before a periodic review authors rules."""
    canonical = list(canonical_rule_events)
    action = _upper(periodic_rule_action)
    rationale = _clean(periodic_rationale)

    if action and action not in PERIODIC_RULE_ACTIONS:
        raise ValueError(
            "periodic_rule_action must be one of: "
            + ", ".join(sorted(PERIODIC_RULE_ACTIONS))
        )

    if canonical:
        if not action:
            raise ValueError(
                "periodic rule-authoring requires periodic_rule_action"
            )
        if not rationale:
            raise ValueError(
                "periodic rule-authoring requires periodic_rationale"
            )

    return {
        "research_policy_contract": RESEARCH_POLICY_CONTRACT,
        "periodic_rule_action": action or None,
        "periodic_rationale": rationale or None,
    }
