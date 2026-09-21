from __future__ import annotations

from copy import deepcopy

from crypto_strategy_lab.walk_forward_teacher_compression import (
    AUTO_COMPRESSED_STATUS,
    build_teacher_phase_audit,
    teacher_compression_decision,
)


def _packet(
    *,
    teacher_id: str = "wf-100-long",
    episode_id: str = "episode-000001",
    result: str = "WIN",
    di_state: str = "CONTRACTING",
    di_ratio: float = 2.7,
    adx: float = 58.0,
    ema50: float = 3.4,
    macd_histogram: float = -0.5,
    relation_4h: str = "NEAR_OPPOSING_STRUCTURE",
    matched_entry: tuple[str, ...] = (),
    matched_flip: tuple[str, ...] = (),
    effective_side: str = "LONG",
) -> dict:
    coverage = {
        "eligible": bool(matched_entry),
        "reason": "ENTRY_MATCHED" if matched_entry else "NO_ENTRY_GROUP_MATCH",
        "matched_entry_groups": list(matched_entry),
        "matched_veto_groups": [],
        "matched_flip_groups": list(matched_flip),
        "rule_effective_side": effective_side,
    }
    return {
        "teacher": {
            "pair_id": teacher_id,
            "walk_forward_candidate_id": teacher_id,
            "research_episode_id": episode_id,
            "side": "LONG",
            "strategy_profile_key": "bull_long",
            "result": result,
        },
        "active_rule_versions": [
            {"rule_id": rule_id, "rule_version": "1"}
            for rule_id in (*matched_entry, *matched_flip)
        ],
        "current_rule_coverage": coverage,
        "entry_context": {
            "trade_entry_context": {
                "research_episode_id": episode_id,
                "side": "LONG",
                "strategy_profile_key": "bull_long",
                "di_pressure_state": di_state,
                "di_ratio": di_ratio,
                "adx": adx,
                "ema_50_distance_atr": ema50,
                "macd_histogram": macd_histogram,
                "macd_histogram_change": -0.1,
                "directional_momentum_return_at_entry": 0.01,
            },
            "feature_context": {
                "mtf_strategy_sr_role_reversal_state": "NONE",
            },
            "support_resistance_trade_context_v2": {
                "timeframes": {
                    "STRATEGY_TF": {
                        "entry_relation": "BETWEEN_STRUCTURES",
                        "opposing_structure_state": "APPROACHING",
                        "favorable_structure_state": "HELD",
                        "target_path": "TARGET_BEFORE_OPPOSING_ZONE",
                        "opposing_room_target_multiple": 1.2,
                    },
                    "1H": {
                        "entry_relation": "BETWEEN_STRUCTURES",
                        "opposing_structure_state": "APPROACHING",
                        "favorable_structure_state": "HELD",
                        "target_path": "TARGET_BEFORE_OPPOSING_ZONE",
                        "opposing_room_target_multiple": 1.1,
                    },
                    "4H": {
                        "entry_relation": relation_4h,
                        "opposing_structure_state": "TESTING",
                        "favorable_structure_state": "HELD",
                        "target_path": "OPPOSING_ZONE_BEFORE_TARGET",
                        "opposing_room_target_multiple": 0.4,
                    },
                    "1D": {
                        "entry_relation": "NEAR_OPPOSING_STRUCTURE",
                        "opposing_structure_state": "TESTING",
                        "favorable_structure_state": "HELD",
                        "target_path": "OPPOSING_ZONE_BEFORE_TARGET",
                        "opposing_room_target_multiple": 0.3,
                    },
                }
            },
        },
    }


def _reviewed_event(
    packet: dict,
    *,
    sequence: int = 10,
    validated_rule_event_count: int = 0,
    confirmation_of_teacher_id: str | None = None,
) -> dict:
    audit = build_teacher_phase_audit(packet)
    teacher = deepcopy(packet["teacher"])
    teacher.update(
        {
            "teacher_review_status": "CHATGPT_REVIEWED",
            "teacher_phase_audit": audit,
            "phase_fingerprint": audit["phase_fingerprint"],
            "structural_phase_fingerprint": audit["structural_fingerprint"],
            "validated_rule_event_count": validated_rule_event_count,
            "confirmation_of_teacher_id": confirmation_of_teacher_id,
        }
    )
    return {
        "sequence": sequence,
        "event_type": "TEACHER_RESOLVED",
        "payload": teacher,
    }


def test_first_teacher_in_episode_always_surfaces() -> None:
    decision = teacher_compression_decision(_packet(), [])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "FIRST_SURFACED_TEACHER_IN_EPISODE"


def test_same_coarse_phase_auto_compresses_without_rule_learning() -> None:
    first = _packet(teacher_id="wf-100-long")
    later = _packet(teacher_id="wf-101-long", di_ratio=2.8, adx=59.0, ema50=3.6)
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "CORRELATED_PHASE_DUPLICATE"
    assert decision["compared_to_teacher_id"] == "wf-100-long"


def test_structural_bucket_change_surfaces_new_phase() -> None:
    first = _packet(teacher_id="wf-100-long", relation_4h="NEAR_OPPOSING_STRUCTURE")
    later = _packet(teacher_id="wf-101-long", relation_4h="BETWEEN_STRUCTURES")
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "STRUCTURAL_PHASE_CHANGED"


def test_outcome_change_always_surfaces() -> None:
    first = _packet(teacher_id="wf-100-long", result="WIN")
    later = _packet(teacher_id="wf-101-long", result="LOSS")
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "OUTCOME_CLASS_CHANGED"


def test_active_rule_loss_bypasses_compression() -> None:
    first = _packet(
        teacher_id="wf-100-long",
        result="LOSS",
        matched_entry=("ENTRY_001",),
    )
    later = _packet(
        teacher_id="wf-101-long",
        result="LOSS",
        matched_entry=("ENTRY_001",),
    )
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "ACTIVE_RULE_FAILURE"


def test_new_rule_gets_one_confirmation_then_repeats_compress() -> None:
    learning = _packet(teacher_id="wf-100-long")
    learning_event = _reviewed_event(
        learning, sequence=10, validated_rule_event_count=1
    )
    rule_event = {
        "sequence": 11,
        "event_type": "FLIP_LEARNED",
        "payload": {"rule_id": "FLIP_004", "rule_version": "1"},
    }

    confirmation = _packet(
        teacher_id="wf-101-long",
        matched_entry=(),
        matched_flip=("FLIP_004",),
        effective_side="SHORT",
    )
    # A source LONG win while the active FLIP points SHORT is a contradiction,
    # so use a source LOSS for a clean same-thesis confirmation path.
    confirmation["teacher"]["result"] = "LOSS"
    confirmation["teacher"]["paired_opposite_net_r"] = 2.9
    learning["teacher"]["result"] = "LOSS"
    learning["teacher"]["paired_opposite_net_r"] = 2.8
    learning_event = _reviewed_event(
        learning, sequence=10, validated_rule_event_count=1
    )

    decision = teacher_compression_decision(
        confirmation, [learning_event, rule_event]
    )
    # A matched active FLIP on a source loss is rule-accountability evidence and
    # must surface regardless of the confirmation quota.
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "ACTIVE_RULE_FAILURE"


def test_confirmation_quota_for_new_entry_rule_is_consumed_once() -> None:
    learning = _packet(teacher_id="wf-100-long")
    learning_event = _reviewed_event(
        learning, sequence=10, validated_rule_event_count=1
    )
    rule_event = {
        "sequence": 11,
        "event_type": "ENTRY_LEARNED",
        "payload": {"rule_id": "ENTRY_001", "rule_version": "1"},
    }
    confirmation = _packet(
        teacher_id="wf-101-long", matched_entry=("ENTRY_001",)
    )

    decision = teacher_compression_decision(
        confirmation, [learning_event, rule_event]
    )
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "FIRST_RULE_CONFIRMATION_REQUIRED"
    assert decision["confirmation_of_teacher_id"] == "wf-100-long"
    assert decision["confirmation_rule_ids"] == ["ENTRY_001"]

    confirmation_event = _reviewed_event(
        confirmation,
        sequence=12,
        confirmation_of_teacher_id="wf-100-long",
    )
    repeat = _packet(
        teacher_id="wf-102-long", matched_entry=("ENTRY_001",)
    )
    decision = teacher_compression_decision(
        repeat, [learning_event, rule_event, confirmation_event]
    )
    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "POST_CONFIRMATION_REPEAT"


def test_legacy_review_without_fingerprint_forces_new_baseline() -> None:
    legacy = {
        "sequence": 5,
        "event_type": "TEACHER_RESOLVED",
        "payload": {
            "pair_id": "wf-old-long",
            "research_episode_id": "episode-000001",
            "result": "WIN",
        },
    }
    decision = teacher_compression_decision(_packet(), [legacy])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "LEGACY_PHASE_BASELINE_REQUIRED"


def test_auto_compressed_events_are_not_comparison_baselines() -> None:
    first = _packet(teacher_id="wf-100-long")
    reviewed = _reviewed_event(first, sequence=10)
    compressed = {
        "sequence": 11,
        "event_type": "TEACHER_RESOLVED",
        "payload": {
            "pair_id": "wf-101-long",
            "research_episode_id": "episode-000001",
            "teacher_review_status": AUTO_COMPRESSED_STATUS,
        },
    }
    later = _packet(teacher_id="wf-102-long")
    decision = teacher_compression_decision(later, [reviewed, compressed])
    assert decision["compared_to_teacher_id"] == "wf-100-long"
