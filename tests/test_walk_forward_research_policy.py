from __future__ import annotations

import pytest

from crypto_strategy_lab.walk_forward_research_policy import (
    RESEARCH_POLICY_CONTRACT,
    decorate_review_packet,
    research_policy_schema,
    validate_loss_methodology,
    validate_periodic_methodology,
    validate_teacher_methodology,
)


def _rule(event_type: str) -> dict:
    return {
        "event_type": event_type,
        "payload": {
            "rule_id": "RULE_001",
            "rule_version": "1",
            "profile": "bull_long",
            "conditions": [],
        },
    }


def test_every_loss_review_requires_a_diagnosis_even_for_no_change():
    with pytest.raises(ValueError, match="every prospective loss review requires loss_diagnosis"):
        validate_loss_methodology(
            [],
            loss_diagnosis=None,
            failure_mechanism=None,
        )

    no_change = validate_loss_methodology(
        [],
        loss_diagnosis="NO_CLEAR_CAUSAL_LESSON",
        failure_mechanism=None,
    )
    assert no_change["research_policy_contract"] == RESEARCH_POLICY_CONTRACT
    assert no_change["loss_diagnosis"] == "NO_CLEAR_CAUSAL_LESSON"

    with pytest.raises(ValueError, match="every prospective loss review requires loss_diagnosis"):
        validate_loss_methodology(
            [_rule("VETO_LEARNED")],
            loss_diagnosis=None,
            failure_mechanism="Held 4h resistance removed TP3 room.",
        )


def test_veto_requires_exceptional_contradiction():
    with pytest.raises(ValueError, match="EXCEPTIONAL_CONTRADICTION"):
        validate_loss_methodology(
            [_rule("VETO_LEARNED")],
            loss_diagnosis="ENTRY_TOO_BROAD",
            failure_mechanism="The same room weakness repeated.",
        )

    result = validate_loss_methodology(
        [_rule("VETO_LEARNED")],
        loss_diagnosis="EXCEPTIONAL_CONTRADICTION",
        failure_mechanism=(
            "Otherwise-valid continuation entered a newly held 4h resistance "
            "zone with insufficient room."
        ),
    )
    assert result["loss_diagnosis"] == "EXCEPTIONAL_CONTRADICTION"


def test_entry_refinement_requires_entry_too_broad():
    with pytest.raises(ValueError, match="ENTRY_TOO_BROAD"):
        validate_loss_methodology(
            [_rule("ENTRY_REFINED")],
            loss_diagnosis="EXCEPTIONAL_CONTRADICTION",
            failure_mechanism="Higher-timeframe room was structurally missing.",
        )

    result = validate_loss_methodology(
        [_rule("ENTRY_REFINED")],
        loss_diagnosis="ENTRY_TOO_BROAD",
        failure_mechanism=(
            "Repeated losses show the continuation ENTRY admits trades without "
            "enough opposing higher-timeframe room."
        ),
    )
    assert result["loss_diagnosis"] == "ENTRY_TOO_BROAD"


def test_no_clear_lesson_cannot_write_rule():
    with pytest.raises(ValueError, match="cannot author a rule"):
        validate_loss_methodology(
            [_rule("VETO_LEARNED")],
            loss_diagnosis="NO_CLEAR_CAUSAL_LESSON",
            failure_mechanism="No repeatable structural mechanism.",
        )


def test_teacher_entry_learning_requires_reusable_thesis_and_family():
    with pytest.raises(ValueError, match="setup_thesis"):
        validate_teacher_methodology(
            [_rule("ENTRY_LEARNED")],
            teacher_result="WIN",
            setup_thesis=None,
            entry_family="CONTINUATION",
        )

    with pytest.raises(ValueError, match="entry_family"):
        validate_teacher_methodology(
            [_rule("ENTRY_LEARNED")],
            teacher_result="WIN",
            setup_thesis="Reusable continuation structure.",
            entry_family=None,
        )

    result = validate_teacher_methodology(
        [_rule("ENTRY_LEARNED")],
        teacher_result="WIN",
        setup_thesis=(
            "Bull continuation with DI expansion, flow agreement, and adequate "
            "higher-timeframe room."
        ),
        entry_family="CONTINUATION",
    )
    assert result["entry_family"] == "CONTINUATION"


def test_teacher_breakout_is_explicitly_separate_family():
    result = validate_teacher_methodology(
        [_rule("ENTRY_LEARNED")],
        teacher_result="WIN",
        setup_thesis="Confirmed resistance break with follow-through.",
        entry_family="BREAKOUT",
    )
    assert result["entry_family"] == "BREAKOUT"


def test_teacher_flip_learning_uses_same_reusable_thesis_standard_as_entry():
    with pytest.raises(ValueError, match="FLIP learning requires setup_thesis"):
        validate_teacher_methodology(
            [_rule("FLIP_LEARNED")],
            teacher_result="LOSS",
            setup_thesis=None,
            entry_family="REVERSAL",
        )

    with pytest.raises(ValueError, match="FLIP learning requires entry_family"):
        validate_teacher_methodology(
            [_rule("FLIP_LEARNED")],
            teacher_result="LOSS",
            setup_thesis=(
                "Opposite-side reversal has reusable bearish structure despite the "
                "source DI direction."
            ),
            entry_family=None,
        )

    result = validate_teacher_methodology(
        [_rule("FLIP_LEARNED")],
        teacher_result="LOSS",
        setup_thesis=(
            "Opposite-side reversal has reusable bearish structure despite the "
            "source DI direction."
        ),
        entry_family="REVERSAL",
    )
    assert result["entry_family"] == "REVERSAL"
    assert "Opposite-side reversal" in result["setup_thesis"]


def test_teacher_loss_packet_makes_flip_and_entry_learning_symmetric():
    packet = decorate_review_packet({"status": "TEACHER_LOSS_REVIEW_REQUIRED"})
    prompt = packet["methodology_prompt"]

    assert prompt["required_before_flip_learning"] == ["setup_thesis", "entry_family"]
    assert prompt["default_when_opposite_thesis_is_not_reusable"] == "FLIP_EVIDENCE"
    assert "same structural learning standard as ENTRY" in prompt["teacher_loss_rule"]
    assert "Repetition is not a special prerequisite for FLIP" in prompt["teacher_loss_rule"]


def test_periodic_rule_writing_requires_strategic_action_and_rationale():
    with pytest.raises(ValueError, match="periodic_rule_action"):
        validate_periodic_methodology(
            [_rule("ENTRY_REFINED")],
            periodic_rule_action=None,
            periodic_rationale="Repeated VETOs point to one broad ENTRY weakness.",
        )

    result = validate_periodic_methodology(
        [_rule("ENTRY_REFINED")],
        periodic_rule_action="CONSOLIDATE_OR_REFINE",
        periodic_rationale=(
            "Three related veto mechanisms all describe inadequate 4h/1D room; "
            "consolidate the positive ENTRY requirement instead of adding micro-vetoes."
        ),
    )
    assert result["periodic_rule_action"] == "CONSOLIDATE_OR_REFINE"


def test_review_packet_carries_policy_and_repeat_failure_attention():
    packet = decorate_review_packet(
        {
            "status": "LOSS_REVIEW_REQUIRED",
            "causal_history": {
                "entry_group_stats": {
                    "ENTRY_006": {"trades": 4, "wins": 2, "losses": 2},
                    "ENTRY_032": {"trades": 1, "wins": 1, "losses": 0},
                }
            },
        }
    )
    assert packet["research_policy"]["contract"] == RESEARCH_POLICY_CONTRACT
    attention = packet["methodology_prompt"]["repeat_failure_attention"]
    assert [row["entry_group"] for row in attention] == ["ENTRY_006"]
    assert packet["methodology_prompt"]["default_when_unclear"] == "NO_CHANGE"


def test_policy_schema_prioritizes_entry_refinement_over_veto_accumulation():
    schema = research_policy_schema()
    principles = " ".join(schema["principles"])
    assert "refine/consolidate the ENTRY" in principles
    assert "Periodic reviews are primarily for simplification" in principles
    assert "ENTRY and FLIP use the same structural learning standard" in principles
    flip_policy = schema["teacher_loss_flip_review"]
    assert flip_policy["requirements_when_authoring_flip"]["paired_opposite_outcome"] == (
        "must be causally available and WIN"
    )
    assert "Repeated prior examples may strengthen confidence but are not required" in (
        flip_policy["rule"]
    )
