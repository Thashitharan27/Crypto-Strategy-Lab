from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab import walk_forward_rule_analytics as analytics


EXPERIMENT_ID = "WF_RULE_ANALYTICS_TEST"


class _Control:
    def __init__(self, project_root: Path):
        self.project_root = project_root


class _Reports:
    def __init__(self, run_dir: Path, manifest: dict):
        self.run_dir = run_dir
        self.manifest = manifest

    def get_run_manifest(self, run: str) -> dict:
        assert run == "REFERENCE_RUN"
        return self.manifest

    def resolve_run(self, run: str) -> Path:
        assert run == "REFERENCE_RUN"
        return self.run_dir


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "15m",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "atr_multiple": 1},
        "take_profit": {"type": "FIXED_R", "reward_risk_ratio": 1},
        "regime_method": "ASSET_RETURN",
        "risk_model": {
            "type": "percent_equity",
            "initial_equity": 1000.0,
            "risk_per_trade": 0.01,
        },
        "reference_run": "REFERENCE_RUN",
        "reference_provenance": {
            "period_start": "2020-01-01T00:00:00+00:00",
            "period_end": "2020-12-31T00:00:00+00:00",
        },
    }


def _append_rule(
    store: CausalExperimentStore,
    head: dict,
    *,
    event_type: str,
    rule_id: str,
    version: str,
    effective_from: str,
    profile: str = "bull_long",
    threshold: float = 20.0,
    supersedes: str | None = None,
) -> dict:
    payload = {
        "rule_id": rule_id,
        "rule_version": version,
        "profile": profile,
        "conditions": [
            {
                "indicator": "ADX",
                "condition": "GTE",
                "value": threshold,
            }
        ],
        "effective_from": effective_from,
        "reason": "test rule",
        "evidence_source": "PROSPECTIVE_WF",
    }
    if supersedes is not None:
        payload["supersedes_version"] = supersedes
    return store.append_event(
        EXPERIMENT_ID,
        event_type,
        payload,
        f"{rule_id}:{version}",
        head["sequence"],
        head["state_hash"],
        effective_market_time=effective_from,
    )


def _append_trade(
    store: CausalExperimentStore,
    head: dict,
    *,
    candidate_id: str,
    entry_time: str,
    resolved_time: str,
    net_r: float,
    matched_entries: list[str],
    matched_flips: list[str] | None = None,
) -> dict:
    captured = store.append_event(
        EXPERIMENT_ID,
        "CANDIDATE_CONTEXT_CAPTURED",
        {
            "candidate_id": candidate_id,
            "feature_hash": f"hash-{candidate_id}",
            "strategy_profile_key": "bull_long",
            "source_side": "LONG",
            "rule_effective_side": "SHORT" if matched_flips else "LONG",
            "entry_time": entry_time,
            "decision_available_at": entry_time,
            "matched_entry_groups": matched_entries,
            "matched_veto_groups": [],
            "matched_flip_groups": matched_flips or [],
        },
        f"{candidate_id}:capture",
        head["sequence"],
        head["state_hash"],
        effective_market_time=entry_time,
    )
    frozen = store.append_event(
        EXPERIMENT_ID,
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "final_action": "SHORT" if matched_flips else "LONG",
            "state_hash_at_decision": captured["state_hash"],
        },
        f"{candidate_id}:freeze",
        captured["sequence"],
        captured["state_hash"],
        effective_market_time=entry_time,
    )
    revealed = store.append_event(
        EXPERIMENT_ID,
        "OUTCOME_REVEALED",
        {
            "candidate_id": candidate_id,
            "outcome": {
                "net_r": net_r,
                "pair_net_r": net_r,
                "exit_time": resolved_time,
            },
        },
        f"{candidate_id}:reveal",
        frozen["sequence"],
        frozen["state_hash"],
        effective_market_time=resolved_time,
    )
    return store.append_event(
        EXPERIMENT_ID,
        "TRADE_RESOLVED",
        {
            "candidate_id": candidate_id,
            "ledger": "RESEARCH",
            "result": "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN"),
            "net_r": net_r,
            "equity_before": 1000.0,
            "equity_after": 1000.0 + 10.0 * net_r,
        },
        f"{candidate_id}:resolve",
        revealed["sequence"],
        revealed["state_hash"],
        effective_market_time=resolved_time,
    )


def test_rule_summary_is_version_aware_and_overlap_safe(tmp_path):
    control = _Control(tmp_path)
    store = CausalExperimentStore(tmp_path / "walk_forward_experiments")
    head = store.create(EXPERIMENT_ID, _definition(), "create")

    head = _append_rule(
        store,
        head,
        event_type="ENTRY_LEARNED",
        rule_id="ENTRY_001",
        version="1",
        effective_from="2020-01-01T00:00:00+00:00",
    )
    head = _append_trade(
        store,
        head,
        candidate_id="trade-a",
        entry_time="2020-01-10T00:00:00+00:00",
        resolved_time="2020-01-11T00:00:00+00:00",
        net_r=1.0,
        matched_entries=["ENTRY_001"],
    )
    head = _append_rule(
        store,
        head,
        event_type="ENTRY_REFINED",
        rule_id="ENTRY_001",
        version="2",
        supersedes="1",
        effective_from="2020-02-01T00:00:00+00:00",
        threshold=25.0,
    )
    head = _append_rule(
        store,
        head,
        event_type="ENTRY_LEARNED",
        rule_id="ENTRY_002",
        version="1",
        effective_from="2020-02-01T00:00:00+00:00",
        threshold=10.0,
    )
    head = _append_trade(
        store,
        head,
        candidate_id="trade-b",
        entry_time="2020-02-10T00:00:00+00:00",
        resolved_time="2020-02-11T00:00:00+00:00",
        net_r=-1.0,
        matched_entries=["ENTRY_001", "ENTRY_002"],
    )

    result = analytics.summarize_walk_forward_rule_performance(
        control,
        reports=None,
        experiment_id=EXPERIMENT_ID,
        family="ENTRY",
        include_veto_effectiveness=False,
    )

    assert result["read_only"] is True
    assert result["sequence"] == head["sequence"]
    versions = {row["rule_ref"]: row for row in result["rule_versions"]}
    assert versions["ENTRY_001@1"]["lifecycle_status"] == "SUPERSEDED"
    assert versions["ENTRY_001@1"]["performance"]["lifetime"]["wins"] == 1
    assert versions["ENTRY_001@2"]["lifecycle_status"] == "ACTIVE"
    assert versions["ENTRY_001@2"]["performance"]["lifetime"]["losses"] == 1
    assert versions["ENTRY_002@1"]["performance"]["lifetime"]["losses"] == 1

    family = next(row for row in result["rule_families"] if row["rule_id"] == "ENTRY_001")
    assert family["performance"]["lifetime"]["trades"] == 2
    assert family["performance"]["lifetime"]["net_r"] == pytest.approx(0.0)

    overlap = result["entry_overlap"]["per_rule"]
    assert overlap["ENTRY_001@1"]["rule_only_trades"] == 1
    assert overlap["ENTRY_001@2"]["shared_trades"] == 1
    assert overlap["ENTRY_002@1"]["shared_trades"] == 1
    assert result["entry_overlap"]["unique_selected_trades"] == 2

    attribution = {row["candidate_id"]: row for row in result["trade_attribution"]}
    assert attribution["trade-a"]["matched_entries"] == ["ENTRY_001@1"]
    assert attribution["trade-b"]["matched_entries"] == ["ENTRY_001@2", "ENTRY_002@1"]


def test_veto_effectiveness_replays_only_causally_blocked_idle_opportunities(tmp_path, monkeypatch):
    control = _Control(tmp_path)
    store = CausalExperimentStore(tmp_path / "walk_forward_experiments")
    head = store.create(EXPERIMENT_ID, _definition(), "create")
    head = _append_rule(
        store,
        head,
        event_type="ENTRY_LEARNED",
        rule_id="ENTRY_001",
        version="1",
        effective_from="2020-01-01T00:00:00+00:00",
        threshold=20.0,
    )
    head = _append_rule(
        store,
        head,
        event_type="VETO_LEARNED",
        rule_id="VETO_001",
        version="1",
        effective_from="2020-01-01T00:00:01+00:00",
        threshold=30.0,
    )
    head = store.append_event(
        EXPERIMENT_ID,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "TEST_CURSOR"},
        "cursor",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2020-01-03T00:00:00+00:00",
    )

    run_dir = tmp_path / "reference"
    run_dir.mkdir()
    samples_path = run_dir / "research_sampling_trades.parquet"
    context_path = run_dir / "feature_context.parquet"
    pd.DataFrame(
        [
            {
                "research_signal_index": 1,
                "research_sample_id": "sample-1",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2020-01-02T00:00:00+00:00",
                "pair_net_r": -1.0,
            },
            {
                "research_signal_index": 2,
                "research_sample_id": "sample-2",
                "strategy_profile_key": "bull_long",
                "side": "LONG",
                "entry_time": "2020-01-02T01:00:00+00:00",
                "pair_net_r": 3.0,
            },
        ]
    ).to_parquet(samples_path, index=False)
    pd.DataFrame(
        [
            {
                "strategy_index": 1,
                "decision_available_at": "2020-01-02T00:00:00+00:00",
                "adx": 35.0,
            },
            {
                "strategy_index": 2,
                "decision_available_at": "2020-01-02T01:00:00+00:00",
                "adx": 40.0,
            },
        ]
    ).to_parquet(context_path, index=False)

    manifest = {
        "research": {"strategy_research_sampling": {"mode": "EVERY_VIABLE_ENTRY"}},
        "config": {
            "strategy": {"profiles": {"bull_long": {"enabled": True}}},
            "features": {},
            "data": {},
        },
    }
    reports = _Reports(run_dir, manifest)

    def fake_artifact(_manifest, _run_dir, name):
        return samples_path if name == "research_sampling_trades" else context_path

    monkeypatch.setattr(analytics.candidate_impl, "_artifact", fake_artifact)

    result = analytics.summarize_walk_forward_rule_performance(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        family="VETO",
        include_overlap=True,
        include_veto_effectiveness=True,
    )

    veto = result["veto_effectiveness"][0]
    lifetime = veto["effectiveness"]["lifetime"]
    assert lifetime["blocked_opportunities"] == 2
    assert lifetime["losses_avoided"] == 1
    assert lifetime["wins_blocked"] == 1
    assert lifetime["veto_precision_pct"] == 50.0
    assert lifetime["hypothetical_net_r"] == pytest.approx(2.0)
    assert lifetime["net_r_saved"] == pytest.approx(-2.0)
    assert result["veto_replay"]["blocked_opportunities_unique"] == 2
    assert result["veto_overlap"]["unique_selected_blocked_opportunities"] == 2


def test_veto_busy_interval_starts_at_capture_and_closes_on_invalidation():
    events = [
        {
            "event_type": "CANDIDATE_CONTEXT_CAPTURED",
            "effective_market_time": "2020-01-02T00:00:00+00:00",
            "payload": {
                "candidate_id": "candidate-x",
                "entry_time": "2020-01-02T00:00:00+00:00",
                "decision_available_at": "2020-01-02T00:15:00+00:00",
            },
        },
        {
            "event_type": "FEATURE_CONTEXT_INVALID",
            "effective_market_time": "2020-01-02T00:05:00+00:00",
            "payload": {"candidate_id": "candidate-x"},
        },
    ]

    starts, ends = analytics._open_trade_intervals(
        events, pd.Timestamp("2020-01-03T00:00:00Z")
    )

    assert starts == [pd.Timestamp("2020-01-02T00:00:00Z")]
    assert ends == [pd.Timestamp("2020-01-02T00:05:00Z")]
    assert analytics._inside_interval(
        pd.Timestamp("2020-01-02T00:03:00Z"), starts, ends
    )
    assert not analytics._inside_interval(
        pd.Timestamp("2020-01-02T00:06:00Z"), starts, ends
    )


def test_periodic_summary_compares_equal_length_recent_periods_without_mutation(tmp_path):
    control = _Control(tmp_path)
    store = CausalExperimentStore(tmp_path / "walk_forward_experiments")
    head = store.create(EXPERIMENT_ID, _definition(), "create")
    head = _append_rule(
        store,
        head,
        event_type="ENTRY_LEARNED",
        rule_id="ENTRY_001",
        version="1",
        effective_from="2020-01-01T00:00:00+00:00",
    )
    head = _append_trade(
        store,
        head,
        candidate_id="jan",
        entry_time="2020-01-10T00:00:00+00:00",
        resolved_time="2020-01-11T00:00:00+00:00",
        net_r=-1.0,
        matched_entries=["ENTRY_001"],
    )
    head = _append_trade(
        store,
        head,
        candidate_id="feb",
        entry_time="2020-02-10T00:00:00+00:00",
        resolved_time="2020-02-11T00:00:00+00:00",
        net_r=1.0,
        matched_entries=["ENTRY_001"],
    )
    before = store.read(EXPERIMENT_ID, recent_events=0)

    result = analytics.summarize_walk_forward_periodic_review(
        control,
        reports=None,
        experiment_id=EXPERIMENT_ID,
        review_interval_months=1,
        include_veto_effectiveness=False,
    )

    after = store.read(EXPERIMENT_ID, recent_events=0)
    assert result["read_only"] is True
    assert result["periods"]["current"]["performance"]["wins"] == 1
    assert result["periods"]["previous"]["performance"]["losses"] == 1
    assert result["overall_direction"] == "IMPROVING_AVERAGE_R"
    assert before["sequence"] == after["sequence"] == head["sequence"]
    assert before["state_hash"] == after["state_hash"]
