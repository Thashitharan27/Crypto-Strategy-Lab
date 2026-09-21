from __future__ import annotations

from copy import deepcopy

from crypto_strategy_lab.walk_forward_orchestrator_impl import (
    _append_auto_compressed_teacher,
)
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
    rule_version: str = "1",
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
            {"rule_id": rule_id, "rule_version": rule_version}
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


def test_same_actionability_auto_compresses_fine_feature_changes() -> None:
    first = _packet(teacher_id="wf-100-long", matched_entry=("ENTRY_001",))
    later = _packet(
        teacher_id="wf-101-long",
        di_ratio=2.8,
        adx=59.0,
        ema50=3.6,
        matched_entry=("ENTRY_001",),
    )
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "RULE_ACTIONABILITY_REPEAT"
    assert decision["compared_to_teacher_id"] == "wf-100-long"


def test_actionability_memory_ignores_intervening_fine_structure() -> None:
    phase_a = _packet(
        teacher_id="wf-100-long",
        relation_4h="NEAR_OPPOSING_STRUCTURE",
        matched_entry=("ENTRY_001",),
    )
    phase_b = _packet(
        teacher_id="wf-101-long",
        relation_4h="BETWEEN_STRUCTURES",
        matched_entry=("ENTRY_001",),
    )
    phase_a_again = _packet(
        teacher_id="wf-102-long",
        relation_4h="NEAR_OPPOSING_STRUCTURE",
        di_ratio=2.8,
        adx=59.0,
        ema50=3.6,
        matched_entry=("ENTRY_001",),
    )

    decision = teacher_compression_decision(
        phase_a_again,
        [
            _reviewed_event(phase_a, sequence=10),
            _reviewed_event(phase_b, sequence=11),
        ],
    )

    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "RULE_ACTIONABILITY_REPEAT"
    assert decision["compared_to_teacher_id"] == "wf-101-long"


def test_minor_structural_bucket_change_does_not_surface() -> None:
    first = _packet(
        teacher_id="wf-100-long",
        relation_4h="NEAR_OPPOSING_STRUCTURE",
        matched_entry=("ENTRY_001",),
    )
    later = _packet(
        teacher_id="wf-101-long",
        relation_4h="BETWEEN_STRUCTURES",
        matched_entry=("ENTRY_001",),
    )
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "RULE_ACTIONABILITY_REPEAT"


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


def test_new_flip_rule_gets_confirmation_when_effective_side_wins() -> None:
    learning = _packet(teacher_id="wf-100-long")
    learning["teacher"]["result"] = "LOSS"
    learning["teacher"]["paired_opposite_net_r"] = 2.8
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
        matched_entry=("ENTRY_001",),
        matched_flip=("FLIP_004",),
        effective_side="SHORT",
    )
    confirmation["teacher"]["result"] = "LOSS"
    confirmation["teacher"]["paired_opposite_net_r"] = 2.9

    decision = teacher_compression_decision(
        confirmation, [learning_event, rule_event]
    )
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "FIRST_RULE_CONFIRMATION_REQUIRED"
    assert decision["confirmation_of_teacher_id"] == "wf-100-long"
    assert decision["confirmation_rule_ids"] == ["FLIP_004"]


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



def test_auto_compressed_teacher_persists_full_audit_metadata() -> None:
    first = _packet(teacher_id="wf-100-long", result="LOSS")
    first["teacher"]["paired_opposite_net_r"] = -1.0
    later = _packet(teacher_id="wf-101-long", result="LOSS", di_ratio=2.8, adx=59.0)
    later["teacher"]["paired_opposite_net_r"] = -1.2
    reviewed = _reviewed_event(first)
    decision = teacher_compression_decision(later, [reviewed])
    assert decision["action"] == "AUTO_COMPRESS"
    later["teacher"]["resolution_time"] = "2025-01-01T04:00:00+00:00"

    class Store:
        def __init__(self):
            self.payload = None
            self.source = None

        def append_event(
            self,
            experiment_id,
            event_type,
            payload,
            operation_id,
            expected_sequence,
            expected_state_hash,
            *,
            effective_market_time,
            source,
        ):
            self.payload = payload
            self.source = source
            assert event_type == "TEACHER_RESOLVED"
            assert effective_market_time == "2025-01-01T04:00:00+00:00"
            return {"sequence": expected_sequence + 1, "state_hash": "b" * 64}

    store = Store()
    recorded = _append_auto_compressed_teacher(
        store,
        experiment_id="BTCUSDT_15M_WF_TEST",
        packet=later,
        decision=decision,
        operation_id="compress-test",
        expected_sequence=20,
        expected_state_hash="a" * 64,
    )

    assert recorded["sequence"] == 21
    assert store.source == "DETERMINISTIC_TEACHER_COMPRESSION"
    assert store.payload["teacher_review_status"] == "AUTO_COMPRESSED"
    assert store.payload["compression_reason"] == "UNRULED_NONACTIONABLE_LOSS"
    assert store.payload["compared_to_teacher_id"] == "wf-100-long"
    assert store.payload["phase_fingerprint"]
    assert store.payload["structural_phase_fingerprint"]
    assert store.payload["active_rule_matches"] == []
    assert store.payload["teacher_phase_audit"]["episode_id"] == "episode-000001"



def test_empty_phase_audit_is_never_used_as_compression_baseline() -> None:
    unaudited = {
        "sequence": 5,
        "event_type": "TEACHER_RESOLVED",
        "payload": {
            "pair_id": "wf-minimal-long",
            "research_episode_id": "episode-000001",
            "result": "WIN",
            "teacher_phase_audit": {},
        },
    }
    decision = teacher_compression_decision(_packet(), [unaudited])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "LEGACY_PHASE_BASELINE_REQUIRED"



def test_open_confirmation_quota_does_not_surface_nonmatching_phase() -> None:
    learning = _packet(teacher_id="wf-100-long")
    learning_event = _reviewed_event(learning, sequence=10)
    rule_event = {
        "sequence": 11,
        "event_type": "ENTRY_LEARNED",
        "payload": {"rule_id": "ENTRY_001", "rule_version": "1"},
    }
    different_phase = _packet(
        teacher_id="wf-101-long",
        relation_4h="BETWEEN_STRUCTURES",
    )

    decision = teacher_compression_decision(
        different_phase,
        [learning_event, rule_event],
    )

    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "UNMATCHED_WINNER"
    assert decision["confirmation_of_teacher_id"] is None
    assert decision["confirmation_rule_ids"] == []


def test_unmatched_winner_always_surfaces() -> None:
    first = _packet(teacher_id="wf-100-long", result="LOSS")
    first["teacher"]["paired_opposite_net_r"] = -1.0
    later = _packet(teacher_id="wf-101-long", result="WIN")
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "UNMATCHED_WINNER"


def test_unruled_loss_loss_auto_compresses_after_baseline() -> None:
    first = _packet(teacher_id="wf-100-long", result="LOSS")
    first["teacher"]["paired_opposite_net_r"] = -1.0
    later = _packet(teacher_id="wf-101-long", result="LOSS")
    later["teacher"]["paired_opposite_net_r"] = -1.2
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "AUTO_COMPRESS"
    assert decision["reason"] == "UNRULED_NONACTIONABLE_LOSS"


def test_paired_flip_opportunity_always_surfaces() -> None:
    first = _packet(teacher_id="wf-100-long", result="LOSS")
    first["teacher"]["paired_opposite_net_r"] = -1.0
    later = _packet(teacher_id="wf-101-long", result="LOSS")
    later["teacher"]["paired_opposite_net_r"] = 2.5
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "PAIRED_FLIP_OPPORTUNITY"


def test_genuine_setup_class_change_surfaces() -> None:
    first = _packet(
        teacher_id="wf-100-long",
        matched_entry=("ENTRY_001",),
        di_state="CONTRACTING",
        adx=58.0,
        ema50=3.4,
        macd_histogram=-0.5,
    )
    later = _packet(
        teacher_id="wf-101-long",
        matched_entry=("ENTRY_001",),
        di_state="EXPANDING",
        di_ratio=2.7,
        adx=35.0,
        ema50=1.0,
        macd_histogram=0.2,
    )
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "SETUP_CLASS_CHANGED"


def test_blocked_entry_winner_surfaces() -> None:
    first = _packet(
        teacher_id="wf-100-long",
        matched_entry=("ENTRY_001",),
    )
    later = _packet(
        teacher_id="wf-101-long",
        matched_entry=("ENTRY_001",),
    )
    later["current_rule_coverage"]["eligible"] = False
    later["current_rule_coverage"]["reason"] = "VETO_MATCHED"
    decision = teacher_compression_decision(later, [_reviewed_event(first)])
    assert decision["action"] == "SURFACE"
    assert decision["reason"] == "RULE_BLOCKED_WINNER"


def test_confirmation_requires_exact_rule_version() -> None:
    learning = _packet(teacher_id="wf-100-long")
    learning_event = _reviewed_event(learning, sequence=10)
    rule_event = {
        "sequence": 11,
        "event_type": "ENTRY_LEARNED",
        "payload": {"rule_id": "ENTRY_001", "rule_version": "1"},
    }
    current = _packet(
        teacher_id="wf-101-long",
        matched_entry=("ENTRY_001",),
        rule_version="2",
    )
    decision = teacher_compression_decision(
        current, [learning_event, rule_event]
    )
    assert decision["reason"] != "FIRST_RULE_CONFIRMATION_REQUIRED"
    assert decision["confirmation_of_teacher_id"] is None
    assert decision["confirmation_rule_ids"] == []
    assert decision["confirmation_rule_versions"] == []
