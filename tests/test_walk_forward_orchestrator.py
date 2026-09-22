from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.run_manifest import file_sha256
from crypto_strategy_lab.walk_forward_candidate_engine import get_next_walk_forward_candidate
from crypto_strategy_lab.walk_forward_orchestrator import (
    _batch_review_evidence,
    advance_walk_forward,
    freeze_and_reveal_walk_forward_candidate,
    record_walk_forward_review,
    record_walk_forward_teacher_review,
    resolve_walk_forward_trade,
    submit_walk_forward_decision,
)


EXPERIMENT_ID = "BTCUSDT_1D_WF_ORCH_TEST"
REFERENCE_RUN = "BTCUSDT_1d_reference"


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
    config["data"]["strategy_timeframe_minutes"] = 1440
    config["data"]["intrabar_timeframe_minutes"] = 1
    config["data"]["use_intrabar_data"] = True
    config["features"]["market_regime_method"] = "ASSET_RETURN"
    config["execution"]["risk_per_leg"] = 0.01
    for values in config["execution"]["profiles"].values():
        values["stop_loss_multiple"] = 1.0
        values["reward_risk_ratio"] = 1.0
    return config


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "1d",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 1.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": REFERENCE_RUN,
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def _catalog(path: Path, run_dir: Path) -> dict:
    return {
        "path": str(path.relative_to(run_dir)).replace("\\", "/"),
        "sha256": file_sha256(path),
        "format": "parquet",
    }


def _samples(include_short: bool = False) -> pd.DataFrame:
    rows = [
        {
            "research_sample_id": "10-LONG-e1",
            "research_signal_index": 10,
            "research_sampling_mode": "WALK_FORWARD",
            "walk_forward_candidate_id": "wf-10-long",
            "walk_forward_candidate_source": True,
            "walk_forward_counterfactual": False,
            "walk_forward_source_side": "LONG",
            "walk_forward_source_profile_key": "bull_long",
            "strategy_profile_key": "bull_long",
            "side": "LONG",
            "entry_time": "2025-01-02T00:00:00Z",
            "signal_available_at": "2025-01-02T00:00:00Z",
            "signal_close_price": 100.0,
            "ema_50": 95.0,
            "ema_100": 90.0,
            "ema_200": 80.0,
            "rsi": 45.0,
            "pair_net_r": -1.0,
            "pair_net_pnl": -10.0,
            "exit_time": "2025-01-02T12:00:00Z",
        },
        {
            "research_sample_id": "11-LONG-e1",
            "research_signal_index": 11,
            "research_sampling_mode": "WALK_FORWARD",
            "walk_forward_candidate_id": "wf-11-long",
            "walk_forward_candidate_source": True,
            "walk_forward_counterfactual": False,
            "walk_forward_source_side": "LONG",
            "walk_forward_source_profile_key": "bull_long",
            "strategy_profile_key": "bull_long",
            "side": "LONG",
            "entry_time": "2025-01-03T00:00:00Z",
            "signal_available_at": "2025-01-03T00:00:00Z",
            "signal_close_price": 110.0,
            "ema_50": 100.0,
            "ema_100": 90.0,
            "ema_200": 80.0,
            "rsi": 50.0,
            "pair_net_r": 0.987,
            "pair_net_pnl": 9.87,
            "exit_time": "2025-01-03T12:00:00Z",
        },
    ]
    if include_short:
        rows.append(
            {
                "research_sample_id": "10-SHORT-e2",
                "research_signal_index": 10,
                "research_sampling_mode": "WALK_FORWARD",
                "walk_forward_candidate_id": "wf-10-long",
                "walk_forward_candidate_source": False,
                "walk_forward_counterfactual": True,
                "walk_forward_source_side": "LONG",
                "walk_forward_source_profile_key": "bull_long",
                "strategy_profile_key": "bull_short",
                "side": "SHORT",
                "entry_time": "2025-01-02T00:00:00Z",
                "signal_available_at": "2025-01-02T00:00:00Z",
                "signal_close_price": 100.0,
                "ema_50": 95.0,
                "ema_100": 90.0,
                "ema_200": 80.0,
                "rsi": 45.0,
                "pair_net_r": 0.95,
                "pair_net_pnl": 9.5,
                "exit_time": "2025-01-02T10:00:00Z",
            }
        )
    return pd.DataFrame(rows)


def _context() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strategy_index": 9,
                "strategy_candle_open_time": "2025-01-01T00:00:00Z",
                "decision_available_at": "2025-01-01T00:00:00Z",
                "adx": 20.0,
                "plus_di": 25.0,
                "minus_di": 15.0,
                "close": 99.0,
                "atr": 5.0,
                "atr_pct": 0.05,
                "session_vwap": 98.0,
                "close_location": 0.7,
                "mean_reversion_state": "NEAR_MEAN",
            },
            {
                "strategy_index": 10,
                "strategy_candle_open_time": "2025-01-02T00:00:00Z",
                "decision_available_at": "2025-01-02T00:00:00Z",
                "adx": 35.0,
                "plus_di": 28.0,
                "minus_di": 14.0,
                "close": 100.0,
                "atr": 5.0,
                "atr_pct": 0.05,
                "session_vwap": 99.0,
                "close_location": 0.7,
                "mean_reversion_state": "NEAR_MEAN",
            },
            {
                "strategy_index": 11,
                "strategy_candle_open_time": "2025-01-03T00:00:00Z",
                "decision_available_at": "2025-01-03T00:00:00Z",
                "adx": 40.0,
                "plus_di": 30.0,
                "minus_di": 15.0,
                "close": 110.0,
                "atr": 5.0,
                "atr_pct": 0.045,
                "session_vwap": 108.0,
                "close_location": 0.8,
                "mean_reversion_state": "ABOVE_MEAN",
            },
        ]
    )


def _write_reference(
    tmp_path: Path,
    *,
    include_short: bool = False,
    teachers: pd.DataFrame | None = None,
    monthly_batch: bool = False,
    weekly_batch: bool = False,
    initial_entry: bool = True,
):
    project = tmp_path / "project"
    output = tmp_path / "output"
    run_dir = output / REFERENCE_RUN
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    project.mkdir(parents=True)
    samples_path = artifacts / "research_sampling_trades.parquet"
    context_path = artifacts / "feature_context.parquet"
    if monthly_batch or weekly_batch:
        # Keep batch-mode end-to-end regression tests independent of
        # pandas' optional pyarrow/fastparquet extras used by older fixtures.
        with duckdb.connect(":memory:") as connection:
            samples_frame = _samples(include_short=include_short)
            context_frame = _context()
            connection.register("samples_frame", samples_frame)
            connection.register("context_frame", context_frame)
            connection.execute(
                f"COPY samples_frame TO '{samples_path.as_posix()}' (FORMAT PARQUET)"
            )
            connection.execute(
                f"COPY context_frame TO '{context_path.as_posix()}' (FORMAT PARQUET)"
            )
    else:
        _samples(include_short=include_short).to_parquet(samples_path, index=False)
        _context().to_parquet(context_path, index=False)
    artifact_map = {
        "research_sampling_trades": _catalog(samples_path, run_dir),
        "feature_context": _catalog(context_path, run_dir),
    }
    if teachers is not None:
        trades_path = artifacts / "trades.parquet"
        teachers.to_parquet(trades_path, index=False)
        artifact_map["trades"] = _catalog(trades_path, run_dir)
    manifest = {
        "run_id": REFERENCE_RUN,
        "request": {"symbol": "BTCUSDT"},
        "config": _config(),
        "artifacts": artifact_map,
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
    head = store.create(EXPERIMENT_ID, definition, "create:orch")
    if initial_entry:
        head = store.append_event(
            EXPERIMENT_ID,
            "ENTRY_LEARNED",
            {
                "rule_id": "ENTRY_001",
                "rule_version": "1",
                "effective_from": "2025-01-01T00:00:00Z",
                "reason": "test entry",
                "evidence_source": "TEACHER",
                "profile": "bull_long",
                "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 30}],
            },
            "rule:entry",
            head["sequence"],
            head["state_hash"],
            effective_market_time="2025-01-01T00:00:00Z",
        )
    return control, reports, store, head


def _capture(control, reports, head):
    return get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="candidate:1",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )


def test_freeze_happens_before_outcome_and_settlement_uses_current_equity(tmp_path):
    control, reports, store, head = _write_reference(tmp_path)
    candidate = _capture(control, reports, head)
    revealed = freeze_and_reveal_walk_forward_candidate(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        candidate_id=candidate["candidate"]["candidate_id"],
        candidate_token=candidate["candidate"]["candidate_token"],
        final_action="LONG",
        confidence_pct=72,
        reasoning="Trend and directional pressure support long.",
        operation_id="decision:1",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
    )
    events = store.read(EXPERIMENT_ID, recent_events=50)["recent_events"]
    freeze = next(e for e in events if e["event_type"] == "DECISION_FROZEN")
    reveal = next(e for e in events if e["event_type"] == "OUTCOME_REVEALED")
    assert freeze["sequence"] < reveal["sequence"]
    assert revealed["outcome"]["net_r"] == -1.0

    settled = resolve_walk_forward_trade(
        control,
        experiment_id=EXPERIMENT_ID,
        candidate_id=candidate["candidate"]["candidate_id"],
        operation_id="settle:1",
        expected_sequence=revealed["sequence"],
        expected_state_hash=revealed["state_hash"],
    )
    assert settled["settlement"]["risk_amount"] == 10.0
    assert settled["settlement"]["net_pnl"] == -10.0
    assert settled["settlement"]["equity_after"] == 990.0
    assert store.read(EXPERIMENT_ID)["derived_state"]["ledgers"]["RESEARCH"]["equity"] == 990.0


def test_missing_opposite_side_outcome_leaves_decision_frozen(tmp_path):
    control, reports, store, head = _write_reference(tmp_path, include_short=False)
    candidate = _capture(control, reports, head)
    with pytest.raises(ValueError, match="decision remains frozen"):
        freeze_and_reveal_walk_forward_candidate(
            control,
            reports,
            experiment_id=EXPERIMENT_ID,
            candidate_id=candidate["candidate"]["candidate_id"],
            candidate_token=candidate["candidate"]["candidate_token"],
            final_action="SHORT",
            confidence_pct=60,
            reasoning="Short evidence dominates.",
            operation_id="decision:opposite",
            expected_sequence=candidate["sequence"],
            expected_state_hash=candidate["state_hash"],
        )
    state = store.read(EXPERIMENT_ID)["derived_state"]["candidate_states"][candidate["candidate"]["candidate_id"]]
    assert state == "DECISION_FROZEN"
    events = store.read(EXPERIMENT_ID, recent_events=50)["recent_events"]
    assert any(e["event_type"] == "DECISION_FROZEN" for e in events)
    assert not any(e["event_type"] == "OUTCOME_REVEALED" for e in events)


def test_advance_stops_at_first_periodic_boundary_before_candidate_capture(tmp_path):
    control, reports, store, head = _write_reference(tmp_path)
    reports.manifest["request"]["start"] = "2024-10-02T00:00:00Z"

    result = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:first-periodic",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )

    assert result["status"] == "PERIODIC_REVIEW_REQUIRED"
    assert result["research_policy"]["contract"] == "causal_walk_forward_entry_veto_flip_method_v2"
    assert result["methodology_prompt"]["primary_goal"] == "SIMPLIFY_CONSOLIDATE_AND_DIAGNOSE"
    assert result["periodic_review_summary"]["read_only"] is True
    assert result["periodic_review_summary"]["experiment_id"] == EXPERIMENT_ID
    assert result["review_anchor_source"] == "REFERENCE_PERIOD_START"
    assert result["review_due_time"] == "2025-01-02T00:00:00+00:00"
    events = store.read(EXPERIMENT_ID, recent_events=10)["recent_events"]
    assert events[-1]["event_type"] == "CHECKPOINT_CREATED"
    assert events[-1]["payload"]["checkpoint_type"] == "PERIODIC_REVIEW_BOUNDARY_V1"
    assert not any(
        event["event_type"] == "CANDIDATE_CONTEXT_CAPTURED" for event in events
    )


def test_submit_loss_returns_review_and_review_then_advances(tmp_path):
    control, reports, store, head = _write_reference(tmp_path)
    first = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:1",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    assert first["status"] == "CANDIDATE_DECISION_REQUIRED"
    loss = submit_walk_forward_decision(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        candidate_id=first["candidate_id"],
        candidate_token=first["candidate_token"],
        final_action="LONG",
        confidence_pct=70,
        reasoning="Valid long setup.",
        operation_id="decision:loss",
        expected_sequence=first["sequence"],
        expected_state_hash=first["state_hash"],
    )
    assert loss["status"] == "LOSS_REVIEW_REQUIRED"
    assert loss["research_policy"]["contract"] == "causal_walk_forward_entry_veto_flip_method_v2"
    assert loss["methodology_prompt"]["required_first_classification"] == "loss_diagnosis"
    assert loss["settlement"]["equity_after"] == 990.0

    next_point = record_walk_forward_review(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        review_type="LOSS",
        candidate_id=first["candidate_id"],
        decision="KEEP_LOSS",
        notes="Valid setup; no repeatable veto mechanism.",
        loss_diagnosis="NO_CLEAR_CAUSAL_LESSON",
        operation_id="review:loss",
        expected_sequence=loss["sequence"],
        expected_state_hash=loss["state_hash"],
        auto_advance=True,
    )
    assert next_point["status"] == "CANDIDATE_DECISION_REQUIRED"
    assert next_point["candidate"]["research_signal_index"] == 11
    assert store.read(EXPERIMENT_ID)["derived_state"]["ledgers"]["RESEARCH"]["equity"] == 990.0


def test_monthly_batch_auto_executes_loss_without_mid_month_review(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path, monthly_batch=True
    )

    result = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:monthly-batch",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        max_transitions=20,
    )

    assert result["status"] not in {
        "CANDIDATE_DECISION_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
        "TEACHER_REVIEW_REQUIRED",
        "TEACHER_LOSS_REVIEW_REQUIRED",
    }
    events = store.read(EXPERIMENT_ID, recent_events=100)["recent_events"]
    first_freeze = next(
        event for event in events if event["event_type"] == "DECISION_FROZEN"
    )
    assert first_freeze["source"] == "DETERMINISTIC_MONTHLY_BATCH_OOS"
    assert first_freeze["payload"]["decision_mode"] == "MONTHLY_BATCH_OOS"
    assert first_freeze["payload"]["chatgpt_view"] is None
    assert any(
        event["event_type"] == "TRADE_RESOLVED"
        and float((event.get("payload") or {}).get("net_r", 0.0)) < 0
        for event in events
    )
    assert not any(
        event["event_type"] == "REVIEW_COMPLETED"
        and str((event.get("payload") or {}).get("review_type", "")).upper()
        == "LOSS"
        for event in events
    )



def test_weekly_batch_evidence_uses_scheduled_boundary_not_late_cursor(tmp_path):
    control, reports, _store, _head = _write_reference(
        tmp_path, weekly_batch=True
    )
    evidence = _batch_review_evidence(
        control,
        reports,
        EXPERIMENT_ID,
        {
            "rule_update_policy": {"mode": "WEEKLY_BATCH_OOS"},
            "review_anchor_time": "2025-01-01T00:00:00+00:00",
            "review_due_time": "2025-01-08T00:00:00+00:00",
            "current_market_cursor": "2025-01-21T13:25:00+00:00",
        },
    )

    assert evidence["window"] == {
        "start_exclusive": "2025-01-01T00:00:00+00:00",
        "end_inclusive": "2025-01-08T00:00:00+00:00",
    }


def test_weekly_batch_auto_executes_without_mid_week_review(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path, weekly_batch=True
    )

    result = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:weekly-batch",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        max_transitions=20,
    )

    assert result["status"] not in {
        "CANDIDATE_DECISION_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
        "TEACHER_REVIEW_REQUIRED",
        "TEACHER_LOSS_REVIEW_REQUIRED",
    }
    events = store.read(EXPERIMENT_ID, recent_events=100)["recent_events"]
    first_freeze = next(
        event for event in events if event["event_type"] == "DECISION_FROZEN"
    )
    assert first_freeze["source"] == "DETERMINISTIC_WEEKLY_BATCH_OOS"
    assert first_freeze["payload"]["decision_mode"] == "WEEKLY_BATCH_OOS"
    assert first_freeze["payload"]["chatgpt_view"] is None
    assert not any(
        event["event_type"] == "REVIEW_COMPLETED"
        and str((event.get("payload") or {}).get("review_type", "")).upper()
        == "LOSS"
        for event in events
    )


def test_monthly_batch_executes_standalone_flip_without_entry(tmp_path):
    control, reports, store, head = _write_reference(
        tmp_path,
        include_short=True,
        monthly_batch=True,
        initial_entry=False,
    )
    head = store.append_event(
        EXPERIMENT_ID,
        "FLIP_LEARNED",
        {
            "rule_id": "FLIP_001",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "standalone opposite-side setup",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
            "conditions": [
                {
                    "indicator": "MR_STATE",
                    "condition": "EQUALS",
                    "value": "NEAR_MEAN",
                }
            ],
        },
        "rule:flip",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00Z",
    )

    result = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:monthly-flip-only",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        max_transitions=20,
    )

    events = store.read(EXPERIMENT_ID, recent_events=100)["recent_events"]
    capture = next(
        event for event in events if event["event_type"] == "CANDIDATE_CONTEXT_CAPTURED"
    )
    assert capture["payload"]["matched_entry_groups"] == []
    assert capture["payload"]["matched_flip_groups"] == ["FLIP_001"]
    assert capture["payload"]["rule_effective_side"] == "SHORT"

    freeze = next(event for event in events if event["event_type"] == "DECISION_FROZEN")
    assert freeze["payload"]["strategy_action"] == "SHORT"
    entered = next(event for event in events if event["event_type"] == "TRADE_ENTERED")
    resolved = next(event for event in events if event["event_type"] == "TRADE_RESOLVED")
    assert entered["payload"]["final_action"] == "SHORT"
    assert resolved["payload"]["final_action"] == "SHORT"
    assert resolved["payload"]["net_r"] == 0.95
    assert store.read(EXPERIMENT_ID)["derived_state"]["ledgers"]["RESEARCH"]["equity"] == 1009.5
    assert result["status"] not in {
        "CANDIDATE_DECISION_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
    }

def test_submit_can_resolve_exact_opposite_side_when_immutable_sample_exists(tmp_path):
    control, reports, store, head = _write_reference(tmp_path, include_short=True)
    candidate = _capture(control, reports, head)
    result = submit_walk_forward_decision(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        candidate_id=candidate["candidate"]["candidate_id"],
        candidate_token=candidate["candidate"]["candidate_token"],
        final_action="SHORT",
        confidence_pct=65,
        reasoning="Short evidence outweighs the source side.",
        operation_id="decision:short",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
        auto_advance=False,
    )
    assert result["status"] == "TRADE_SETTLED"
    assert result["settlement"]["final_action"] == "SHORT"
    assert result["settlement"]["net_r"] == 0.95
    assert result["settlement"]["equity_after"] == 1009.5


def test_teacher_review_is_a_judgment_boundary_and_never_changes_equity(tmp_path):
    teachers = pd.DataFrame(
        [
            {
                "pair_id": 593,
                "side": "LONG",
                "strategy_profile_key": "bull_long",
                "entry_time": "2025-01-01T12:00:00Z",
                "exit_time": "2025-01-01T18:00:00Z",
                "pair_net_r": 1.0,
            }
        ]
    )
    control, reports, store, head = _write_reference(tmp_path, teachers=teachers)
    due = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:teacher",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    assert due["status"] == "TEACHER_REVIEW_REQUIRED"
    assert due["research_policy"]["contract"] == "causal_walk_forward_entry_veto_flip_method_v2"
    assert due["methodology_prompt"]["separate_breakout_logic"] is True
    assert due["teacher"]["pair_id"] == 593
    equity_before = store.read(EXPERIMENT_ID)["derived_state"]["ledgers"]["RESEARCH"]["equity"]
    recorded = record_walk_forward_teacher_review(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        teacher_pair_id="593",
        decision="NO_NEW_RULE",
        notes="Already covered or insufficient distinct evidence.",
        operation_id="teacher:593",
        expected_sequence=due["sequence"],
        expected_state_hash=due["state_hash"],
        auto_advance=False,
    )
    assert recorded["status"] == "TEACHER_REVIEW_RECORDED"
    equity_after = store.read(EXPERIMENT_ID)["derived_state"]["ledgers"]["RESEARCH"]["equity"]
    assert equity_after == equity_before == 1000.0
