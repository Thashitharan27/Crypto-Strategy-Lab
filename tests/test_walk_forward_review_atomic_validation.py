from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.walk_forward_materialization import materialize_walk_forward_strategy
from crypto_strategy_lab.walk_forward_review_facade import (
    record_walk_forward_review,
    record_walk_forward_teacher_review,
)
from crypto_strategy_lab.walk_forward_rule_validation import rule_event_schema


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


def _environment(tmp_path: Path):
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
    head = store.create(EXPERIMENT_ID, _definition(), "create:rule-preflight")
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
