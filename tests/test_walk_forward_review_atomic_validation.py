from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl
from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.walk_forward_materialization import materialize_walk_forward_strategy
from crypto_strategy_lab.walk_forward_review_facade import (
    record_walk_forward_review,
    record_walk_forward_teacher_review,
)
from crypto_strategy_lab.walk_forward_rule_validation import append_events_atomic, rule_event_schema


EXPERIMENT_ID = "BTCUSDT_15M_WF_RULE_PREFLIGHT_TEST"
REFERENCE_RUN = "BTCUSDT_15m_rule_preflight_reference"


class FakeReports:
    def __init__(self, run_dir: Path, manifest: dict):
        self.run_dir = run_dir
        self.manifest = manifest

    def get_run_manifest(self, run: str) -> dict:
        if run != REFERENCE_RUN:
            raise ValueError(f"unknown run: {run}")
        return self.manifest

    def resolve_run(self, run: str) -> Path:
        if run != REFERENCE_RUN:
            raise ValueError(f"unknown run: {run}")
        return self.run_dir


def _config() -> dict:
    config = ResearchRunConfig().to_dict()
    config["data"]["strategy_timeframe_minutes"] = 15
    config["data"]["intrabar_timeframe_minutes"] = 1
    config["data"]["use_intrabar_data"] = True
    config["features"]["market_regime_method"] = "ASSET_RETURN"
    return config


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "15m",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 2.0},
        "take_profit": {"type": "R", "multiple": 3.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": REFERENCE_RUN,
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def _environment(
    tmp_path: Path,
    *,
    monthly_batch: bool = False,
    weekly_batch: bool = False,
):
    project = tmp_path / "project"
    output = tmp_path / "output"
    run_dir = output / REFERENCE_RUN
    project.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": REFERENCE_RUN,
        "request": {"symbol": "BTCUSDT"},
        "config": _config(),
        "artifacts": {},
        "research": {"strategy_research_sampling": {"mode": "WALK_FORWARD"}},
    }
    control = SimpleNamespace(project_root=project, output_root=output)
    reports = FakeReports(run_dir, manifest)
    store = CausalExperimentStore(project / "walk_forward_experiments")
    definition = _definition()
    if monthly_batch:
        definition["rule_update_policy"] = {
            "mode": "MONTHLY_BATCH_OOS",
            "interval_months": 1,
            "freeze_between_reviews": True,
        }
    elif weekly_batch:
        definition["rule_update_policy"] = {
            "mode": "WEEKLY_BATCH_OOS",
            "interval_weeks": 1,
            "freeze_between_reviews": True,
        }
    head = store.create(EXPERIMENT_ID, definition, "create:rule-preflight")
    return control, reports, store, head


def _invalid_di_ratio_rule() -> list[dict]:
    return [
        {
            "event_type": "ENTRY_LEARNED",
            "payload": {
                "rule_id": "ENTRY_001",
                "rule_version": "1",
                "profile": "bull_long",
                "conditions": [
                    {"feature": "di_ratio", "op": "GTE", "value": 1.25}
                ],
            },
        }
    ]


def _canonical_di_ratio_rule() -> list[dict]:
    return [
        {
            "event_type": "ENTRY_LEARNED",
            "payload": {
                "rule_id": "ENTRY_001",
                "rule_version": "1",
                "profile": "bull_long",
                "conditions": [
                    {
                        "indicator": "DIRECTIONAL_DI_RATIO",
                        "condition": "GTE",
                        "value": 1.25,
                    }
                ],
            },
        }
    ]


def test_periodic_review_can_atomically_retire_active_rule(tmp_path):
    control, reports, store, head = _environment(tmp_path)
    head = store.append_event(
        EXPERIMENT_ID,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_001",
            "rule_version": "1",
            "effective_from": "2020-06-01T00:00:00+00:00",
            "reason": "initial reusable entry",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
            "conditions": [
                {
                    "indicator": "DIRECTIONAL_DI_RATIO",
                    "condition": "GTE",
                    "value": 1.25,
                }
            ],
        },
        "rule:entry:before-retire",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2020-06-01T00:00:00+00:00",
        source="CHATGPT_RESEARCH",
    )
    head = store.append_event(
        EXPERIMENT_ID,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "TEST_PERIODIC_BOUNDARY"},
        "checkpoint:before-retire",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2020-07-01T00:00:00+00:00",
        source="DETERMINISTIC_ORCHESTRATOR",
    )

    recorded = record_walk_forward_review(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        review_type="PERIODIC",
        decision="RETIRE_STALE_RULE",
        notes="The completed review no longer supports this entry family.",
        operation_id="periodic:retire-entry-001",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        rule_events=[
            {
                "event_type": "RULE_RETIRED",
                "payload": {
                    "rule_id": "ENTRY_001",
                    "rule_version": "1",
                },
            }
        ],
        periodic_rule_action="RETIRE_OR_PROMOTE",
        periodic_rationale=(
            "The rule is stale and should not remain active in the next frozen period."
        ),
        auto_advance=False,
    )

    readback = store.read(EXPERIMENT_ID, recent_events=20)
    assert [event["event_type"] for event in readback["recent_events"]][-2:] == [
        "REVIEW_COMPLETED",
        "RULE_RETIRED",
    ]
    retired = readback["recent_events"][-1]["payload"]
    assert retired["rule_id"] == "ENTRY_001"
    assert retired["rule_version"] == "1"

    snapshot = materialize_walk_forward_strategy(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        expected_sequence=recorded["sequence"],
        expected_state_hash=recorded["state_hash"],
    )
    assert snapshot["active_rule_versions"] == []


def test_weekly_batch_review_records_scheduled_boundary_not_late_market_cursor(tmp_path):
    control, reports, store, _ = _environment(tmp_path)
    reports.manifest["request"]["start"] = "2025-01-01T00:00:00Z"

    experiment_id = "BTCUSDT_15M_WF_WEEKLY_BOUNDARY_TEST"
    definition = _definition()
    definition["periodic_review_policy"] = {
        "enabled": True,
        "interval_months": 3,
        "initial_anchor": "REFERENCE_PERIOD_START",
    }
    definition["rule_update_policy"] = {
        "mode": "WEEKLY_BATCH_OOS",
        "interval_weeks": 1,
        "freeze_between_reviews": True,
    }
    head = store.create(experiment_id, definition, "create:weekly-boundary")
    head = store.append_event(
        experiment_id,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "LATE_WAIT_UNTIL_CLOSED_RESOLUTION_CURSOR"},
        "cursor:late-weekly-review",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-08T23:20:00Z",
        source="DETERMINISTIC_ORCHESTRATOR",
    )

    recorded = record_walk_forward_review(
        control,
        reports,
        experiment_id=experiment_id,
        review_type="PERIODIC",
        decision="NO_CHANGE",
        notes="Completed week had no reusable new rule.",
        operation_id="weekly:review:jan8",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        auto_advance=False,
    )

    readback = store.read(experiment_id, recent_events=20)
    review = next(
        event
        for event in readback["recent_events"]
        if event["event_type"] == "REVIEW_COMPLETED"
    )
    assert review["effective_market_time"] == "2025-01-08T00:00:00+00:00"
    assert review["payload"]["scheduled_review_due_time"] == "2025-01-08T00:00:00+00:00"
    assert review["payload"]["review_observed_market_cursor"] == "2025-01-08T23:20:00+00:00"

    # The late processing time must not shift the cadence. The next due boundary
    # remains Jan 15 00:00, exactly seven days after the scheduled Jan 8 review.
    head = store.append_event(
        experiment_id,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "NEXT_WEEK_CURSOR"},
        "cursor:next-week",
        recorded["sequence"],
        recorded["state_hash"],
        effective_market_time="2025-01-15T01:00:00Z",
        source="DETERMINISTIC_ORCHESTRATOR",
    )
    events = _impl._events(store, experiment_id)
    current_definition = store.read(experiment_id, recent_events=0)["manifest"]["definition"]
    initial_anchor = _impl._initial_periodic_review_anchor(
        reports, current_definition, events
    )
    due = _impl._review_due(
        current_definition,
        events,
        3,
        initial_anchor=initial_anchor,
    )
    assert due is not None
    assert due["review_anchor_time"] == "2025-01-08T00:00:00+00:00"
    assert due["review_due_time"] == "2025-01-15T00:00:00+00:00"


def test_monthly_batch_blocks_mid_month_teacher_and_loss_review_writes(tmp_path):
    control, reports, store, head = _environment(tmp_path, monthly_batch=True)

    with pytest.raises(ValueError, match="defers all teacher-driven rule changes"):
        record_walk_forward_teacher_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            teacher_pair_id="1",
            decision="NO_CHANGE",
            notes="Must wait for the monthly batch boundary.",
            operation_id="monthly:teacher:blocked",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            auto_advance=False,
        )

    with pytest.raises(ValueError, match="mid-month loss reviews"):
        record_walk_forward_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            review_type="LOSS",
            decision="NO_CHANGE",
            notes="Must wait for the monthly batch boundary.",
            operation_id="monthly:loss:blocked",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            loss_diagnosis="NO_CLEAR_CAUSAL_LESSON",
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=10)
    assert unchanged["sequence"] == head["sequence"]
    assert [event["event_type"] for event in unchanged["recent_events"]] == [
        "WF_CREATED"
    ]


def test_weekly_batch_blocks_mid_week_teacher_and_loss_review_writes(tmp_path):
    control, reports, store, head = _environment(tmp_path, weekly_batch=True)

    with pytest.raises(ValueError, match="defers all teacher-driven rule changes"):
        record_walk_forward_teacher_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            teacher_pair_id="1",
            decision="NO_CHANGE",
            notes="Must wait for the weekly batch boundary.",
            operation_id="weekly:teacher:blocked",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            auto_advance=False,
        )

    with pytest.raises(ValueError, match="mid-week loss reviews"):
        record_walk_forward_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            review_type="LOSS",
            decision="NO_CHANGE",
            notes="Must wait for the weekly batch boundary.",
            operation_id="weekly:loss:blocked",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            loss_diagnosis="NO_CLEAR_CAUSAL_LESSON",
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=10)
    assert unchanged["sequence"] == head["sequence"]
    assert [event["event_type"] for event in unchanged["recent_events"]] == [
        "WF_CREATED"
    ]


def test_teacher_review_rejects_uncompilable_rule_without_chain_mutation(
    tmp_path, monkeypatch
):
    control, reports, store, head = _environment(tmp_path)
    from crypto_strategy_lab import walk_forward_review_facade as facade

    boundary = {
        "pair_id": 2,
        "side": "LONG",
        "strategy_profile_key": "bull_long",
        "entry_time": "2020-06-02T00:00:00Z",
        "exit_time": "2020-06-02T03:00:00Z",
    }
    monkeypatch.setattr(
        facade._impl,
        "_next_teacher",
        lambda manifest, run_dir, events: (
            boundary,
            pd.Timestamp("2020-06-02T03:00:00Z"),
        ),
    )

    with pytest.raises(ValueError, match="unsupported strategy indicator: di_ratio"):
        record_walk_forward_teacher_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            teacher_pair_id="2",
            decision="LEARN_ENTRY",
            notes="Directional dominance supports the long teacher winner.",
            operation_id="teacher:2:invalid",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            rule_events=_invalid_di_ratio_rule(),
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=20)
    assert unchanged["sequence"] == head["sequence"] == 1
    assert unchanged["state_hash"] == head["state_hash"]
    assert [event["event_type"] for event in unchanged["recent_events"]] == ["WF_CREATED"]

    recorded = record_walk_forward_teacher_review(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        teacher_pair_id="2",
        decision="LEARN_ENTRY",
        notes="Directional dominance supports the long teacher winner.",
        operation_id="teacher:2:valid",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        rule_events=_canonical_di_ratio_rule(),
        setup_thesis="Bull continuation with reusable directional DI dominance.",
        entry_family="CONTINUATION",
        auto_advance=False,
    )
    assert recorded["atomic_batch"] is True
    assert recorded["sequence"] == 3
    assert recorded["rule_event_schema"]["contract"] == "causal_walk_forward_rule_event_schema_v1"

    readback = store.read(EXPERIMENT_ID, recent_events=20)
    assert [event["event_type"] for event in readback["recent_events"]] == [
        "WF_CREATED",
        "TEACHER_RESOLVED",
        "ENTRY_LEARNED",
    ]
    teacher_review = readback["recent_events"][-2]["payload"]
    assert teacher_review["research_policy_contract"] == "causal_walk_forward_entry_veto_flip_method_v2"
    assert teacher_review["entry_family"] == "CONTINUATION"
    assert "directional DI dominance" in teacher_review["setup_thesis"]

    learned = readback["recent_events"][-1]["payload"]
    assert learned["conditions"][0]["indicator"] == "DIRECTIONAL_DI_RATIO"
    assert learned["conditions"][0]["condition"] == "GTE"

    snapshot = materialize_walk_forward_strategy(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        expected_sequence=recorded["sequence"],
        expected_state_hash=recorded["state_hash"],
    )
    assert snapshot["active_rule_versions"] == [
        {
            "rule_id": "ENTRY_001",
            "rule_version": "1",
            "family": "ENTRY",
            "profile": "bull_long",
            "deployment_status": "RESEARCH_ONLY",
            "learned_sequence": 3,
        }
    ]


def test_teacher_loss_flip_uses_entry_quality_standard_without_repetition_requirement(
    tmp_path, monkeypatch
):
    control, reports, store, head = _environment(tmp_path)
    from crypto_strategy_lab import walk_forward_review_facade as facade

    boundary = {
        "pair_id": 4,
        "side": "LONG",
        "strategy_profile_key": "bull_long",
        "entry_time": "2020-06-04T00:00:00Z",
        "exit_time": "2020-06-04T03:00:00Z",
        "result": "LOSS",
        "pair_net_r": -1.0,
        "teacher_learning_mode": "FLIP_FROM_LOSS_PAIRED",
    }
    monkeypatch.setattr(
        facade._impl,
        "_next_teacher",
        lambda manifest, run_dir, events: (
            boundary,
            pd.Timestamp("2020-06-04T03:00:00Z"),
        ),
    )
    monkeypatch.setattr(
        facade._impl,
        "_teacher_review_packet",
        lambda *args, **kwargs: {
            "status": "TEACHER_LOSS_REVIEW_REQUIRED",
            "teacher": dict(boundary),
            "entry_context": {},
        },
    )
    monkeypatch.setattr(
        facade,
        "_decorate_teacher_loss_packet",
        lambda control, reports, experiment_id, packet: {
            **packet,
            "flip_activation_allowed": True,
            "prior_teacher_loss_evidence_count": 0,
            "opposite_side_outcome": {
                "available": True,
                "side": "SHORT",
                "outcome": {"result": "WIN", "net_r": 2.9},
            },
        },
    )

    flip_rule = _canonical_di_ratio_rule()
    flip_rule[0]["event_type"] = "FLIP_LEARNED"
    flip_rule[0]["payload"]["rule_id"] = "FLIP_001"

    with pytest.raises(ValueError, match="FLIP learning requires setup_thesis"):
        record_walk_forward_teacher_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            teacher_pair_id="4",
            decision="FLIP_LEARNED",
            notes="Opposite side won, but structural thesis is still required.",
            operation_id="teacher:4:flip:missing-thesis",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            rule_events=flip_rule,
            entry_family="REVERSAL",
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=20)
    assert unchanged["sequence"] == head["sequence"]
    assert unchanged["state_hash"] == head["state_hash"]

    recorded = record_walk_forward_teacher_review(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        teacher_pair_id="4",
        decision="FLIP_LEARNED",
        notes=(
            "The opposite SHORT is a reusable reversal setup; DI direction is only "
            "the source proposal."
        ),
        operation_id="teacher:4:flip:valid",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        rule_events=flip_rule,
        setup_thesis=(
            "Reusable bearish reversal structure supports SHORT against the source "
            "LONG DI proposal."
        ),
        entry_family="REVERSAL",
        auto_advance=False,
    )

    assert recorded["atomic_batch"] is True
    assert recorded["sequence"] == 3
    readback = store.read(EXPERIMENT_ID, recent_events=20)
    assert [event["event_type"] for event in readback["recent_events"]] == [
        "WF_CREATED",
        "TEACHER_RESOLVED",
        "FLIP_LEARNED",
    ]
    teacher_review = readback["recent_events"][-2]["payload"]
    assert teacher_review["research_policy_contract"] == (
        "causal_walk_forward_entry_veto_flip_method_v2"
    )
    assert teacher_review["entry_family"] == "REVERSAL"
    assert "Reusable bearish reversal" in teacher_review["setup_thesis"]


def test_teacher_loss_validation_inconsistency_cannot_be_recorded_as_no_change(
    tmp_path, monkeypatch
):
    control, reports, store, head = _environment(tmp_path)
    from crypto_strategy_lab import walk_forward_review_facade as facade

    boundary = {
        "pair_id": 4,
        "side": "SHORT",
        "strategy_profile_key": "sideways_short",
        "entry_time": "2020-06-01T00:45:00Z",
        "exit_time": "2020-06-01T01:56:00Z",
        "result": "LOSS",
        "pair_net_r": -1.166,
        "teacher_learning_mode": "FLIP_FROM_LOSS_PAIRED",
    }
    monkeypatch.setattr(
        facade._impl,
        "_next_teacher",
        lambda manifest, run_dir, events: (
            boundary,
            pd.Timestamp("2020-06-01T22:45:00Z"),
        ),
    )
    monkeypatch.setattr(
        facade._impl,
        "_teacher_review_packet",
        lambda *args, **kwargs: {
            "status": "TEACHER_LOSS_REVIEW_REQUIRED",
            "teacher": dict(boundary),
            "entry_context": {},
        },
    )
    monkeypatch.setattr(
        facade,
        "_decorate_teacher_loss_packet",
        lambda control, reports, experiment_id, packet: {
            **packet,
            "status": "TEACHER_FLIP_VALIDATION_INCONSISTENCY",
            "inspection_required": True,
            "flip_activation_allowed": False,
            "validation_inconsistency": {
                "code": "PAIR_LOOKUP_MISMATCH",
                "reason": "raw pair exists but validator lookup did not resolve it",
            },
        },
    )

    with pytest.raises(ValueError, match="PAIR_LOOKUP_MISMATCH"):
        record_walk_forward_teacher_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            teacher_pair_id="4",
            decision="NO_CHANGE",
            notes="Would previously have silently discarded the FLIP evidence.",
            operation_id="teacher:4:inconsistent:no-change",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=20)
    assert unchanged["sequence"] == head["sequence"]
    assert unchanged["state_hash"] == head["state_hash"]
    assert [event["event_type"] for event in unchanged["recent_events"]] == ["WF_CREATED"]


def test_periodic_review_rule_validation_is_atomic(tmp_path):
    control, reports, store, head = _environment(tmp_path)
    cursor = store.append_event(
        EXPERIMENT_ID,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "TEST_CURSOR", "reason": "establish review time"},
        "cursor:1",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2020-07-01T00:00:00Z",
        source="SYSTEM",
    )

    invalid_veto = _invalid_di_ratio_rule()
    invalid_veto[0]["event_type"] = "VETO_LEARNED"
    invalid_veto[0]["payload"]["rule_id"] = "VETO_001"

    with pytest.raises(ValueError, match="unsupported strategy indicator: di_ratio"):
        record_walk_forward_review(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            review_type="PERIODIC",
            decision="REFINE",
            notes="Quarterly review proposed a veto.",
            operation_id="review:q1:invalid",
            expected_sequence=cursor["sequence"],
            expected_state_hash=cursor["state_hash"],
            rule_events=invalid_veto,
            auto_advance=False,
        )

    unchanged = store.read(EXPERIMENT_ID, recent_events=20)
    assert unchanged["sequence"] == cursor["sequence"]
    assert unchanged["state_hash"] == cursor["state_hash"]
    assert not any(
        event["event_type"] == "REVIEW_COMPLETED"
        for event in unchanged["recent_events"]
    )


def test_rule_event_schema_advertises_canonical_builder_shape():
    schema = rule_event_schema()
    example = schema["example"]["payload"]["conditions"][0]
    assert schema["contract"] == "causal_walk_forward_rule_event_schema_v1"
    assert example == {
        "indicator": "DIRECTIONAL_DI_RATIO",
        "condition": "GTE",
        "value": 1.25,
    }
    assert schema["accepted_input_aliases"]["feature"].startswith("indicator")


def test_mcp_facade_routes_reviews_through_validated_atomic_writers():
    import mcp_server.control_server as control_server
    from crypto_strategy_lab import walk_forward_review_facade as facade

    assert control_server._impl._record_walk_forward_review is facade.record_walk_forward_review
    assert (
        control_server._impl._record_walk_forward_teacher_review
        is facade.record_walk_forward_teacher_review
    )


def test_bootstrap_review_freezes_base_rules_and_transitions_atomically(tmp_path):
    control, reports, store, _cold_head = _environment(tmp_path)
    bootstrap_id = "BTCUSDT_15M_WF_BOOTSTRAP_TEST"
    definition = _definition()
    definition["research_protocol"] = {
        "mode": "BOOTSTRAP_THEN_WF",
        "bootstrap_start": "2020-06-01T00:00:00Z",
        "walk_forward_start": "2022-06-01T00:00:00Z",
    }
    head = store.create(bootstrap_id, definition, "create:bootstrap-rule-preflight")

    assert head["phase"] == "BOOTSTRAP_RESEARCH"

    recorded = record_walk_forward_review(
        control,
        reports,
        experiment_id=bootstrap_id,
        review_type="BOOTSTRAP",
        decision="BASE_RULES_FROZEN",
        notes=(
            "Bootstrap research selected a stable directional-DI continuation family; "
            "bootstrap results are training evidence only."
        ),
        operation_id="review:bootstrap:freeze",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        rule_events=_canonical_di_ratio_rule(),
        auto_advance=False,
    )

    assert recorded["atomic_batch"] is True
    assert recorded["sequence"] == 4

    readback = store.read(bootstrap_id, recent_events=20)
    assert readback["derived_state"]["phase"] == "RESEARCH_WF"
    assert [event["event_type"] for event in readback["recent_events"]] == [
        "WF_CREATED",
        "REVIEW_COMPLETED",
        "ENTRY_LEARNED",
        "PHASE_CHANGED",
    ]

    review = readback["recent_events"][1]
    learned = readback["recent_events"][2]
    phase = readback["recent_events"][3]
    cutoff = "2022-06-01T00:00:00+00:00"

    assert review["payload"]["review_type"] == "BOOTSTRAP"
    assert review["payload"]["bootstrap_methodology_contract"] == "bootstrap_base_rule_method_v1"
    assert review["effective_market_time"] == cutoff
    assert learned["payload"]["evidence_source"] == "BOOTSTRAP"
    assert learned["payload"]["effective_from"] == cutoff
    assert learned["effective_market_time"] == cutoff
    assert phase["payload"]["phase"] == "RESEARCH_WF"
    assert phase["effective_market_time"] == cutoff
    assert not any(event["event_type"] == "TRADE_RESOLVED" for event in readback["recent_events"])


def test_atomic_review_batch_appends_only_new_bytes_and_keeps_chain_valid(tmp_path):
    _control, _reports, store, head = _environment(tmp_path)
    events_path = (
        tmp_path
        / "project"
        / "walk_forward_experiments"
        / EXPERIMENT_ID
        / "events.jsonl"
    )
    before = events_path.read_bytes()

    batch = append_events_atomic(
        store,
        experiment_id=EXPERIMENT_ID,
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        specs=[
            {
                "event_type": "REVIEW_COMPLETED",
                "payload": {
                    "review_type": "PERIODIC",
                    "decision": "NO_CHANGE",
                    "notes": "append-only regression",
                },
                "operation_id": "review:append-only-regression",
                "effective_market_time": "2020-06-07T00:00:00+00:00",
                "source": "CHATGPT_RESEARCH",
            }
        ],
    )

    after = events_path.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)
    assert batch["fast_index_status"] == "CURRENT"

    audited = store.read(EXPERIMENT_ID, recent_events=10)
    assert audited["sequence"] == batch["sequence"]
    assert audited["state_hash"] == batch["state_hash"]
    assert audited["recent_events"][-1]["operation_id"] == "review:append-only-regression"
