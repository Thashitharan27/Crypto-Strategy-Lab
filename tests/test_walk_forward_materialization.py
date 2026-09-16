from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.rule_control_service import RuleAwareBacktestControlService
from crypto_strategy_lab.walk_forward_materialization import (
    create_run_from_walk_forward_experiment,
    materialize_walk_forward_strategy,
)


class FakeProcess:
    pid = 4242

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0


class FakeReports:
    def __init__(self, manifest):
        self.manifest = manifest

    def get_run_manifest(self, run):
        if run not in {self.manifest["run_id"], "BTCUSDT_1d_reference"}:
            raise ValueError(f"unknown completed run: {run}")
        return self.manifest


def _control(tmp_path: Path) -> RuleAwareBacktestControlService:
    project = tmp_path / "project"
    raw = tmp_path / "market"
    cache = tmp_path / "cache"
    output = tmp_path / "output"
    configs = project / "config" / "data_lake"
    tools = project / "tools"
    raw.mkdir()
    configs.mkdir(parents=True)
    tools.mkdir(parents=True)
    runner = tools / "data_lake_run.py"
    runner.write_text("# fixed test runner\n", encoding="utf-8")
    return RuleAwareBacktestControlService(
        project_root=project,
        raw_root=raw,
        cache_root=cache,
        output_root=output,
        config_root=configs,
        runner_script=runner,
        process_factory=lambda *args, **kwargs: FakeProcess(),
    )


def _reference_config() -> dict:
    config = ResearchRunConfig().to_dict()
    config["data"]["strategy_timeframe_minutes"] = 1440
    config["data"]["intrabar_timeframe_minutes"] = 1
    config["data"]["use_intrabar_data"] = True
    config["features"]["market_regime_method"] = "ASSET_RETURN"
    config["features"]["enable_support_resistance_analysis"] = True
    config["features"]["sr_zone_width_atr"] = 0.61
    config["execution"]["initial_equity"] = 2500.0
    config["execution"]["risk_per_leg"] = 0.01
    config["execution"]["maker_fee"] = 0.00017
    config["execution"]["taker_fee"] = 0.00043
    config["execution"]["slippage"] = 0.00031
    for profile in config["execution"]["profiles"].values():
        profile["stop_loss_multiple"] = 1.0
        profile["reward_risk_ratio"] = 1.0
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
        "reference_run": "BTCUSDT_1d_reference",
        "initial_equity": 2500.0,
        "risk_pct": 1.0,
    }


def _setup(tmp_path: Path):
    control = _control(tmp_path)
    config = _reference_config()
    reports = FakeReports(
        {
            "run_id": "BTCUSDT_1d_reference",
            "request": {"symbol": "BTCUSDT"},
            "config": config,
        }
    )
    store = CausalExperimentStore(control.project_root / "walk_forward_experiments")
    head = store.create(
        "BTCUSDT_1D_WF_TEST",
        _definition(),
        "create:test",
    )
    return control, reports, store, head


def _append(store, head, event_type, payload, operation_id):
    return store.append_event(
        "BTCUSDT_1D_WF_TEST",
        event_type,
        payload,
        operation_id,
        head["sequence"],
        head["state_hash"],
    )


def test_materialization_uses_latest_rule_versions_and_preserves_reference_config(tmp_path):
    control, reports, store, head = _setup(tmp_path)
    head = _append(
        store,
        head,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_001",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "teacher structure",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 20}],
        },
        "rule:entry1:v1",
    )
    head = _append(
        store,
        head,
        "ENTRY_REFINED",
        {
            "rule_id": "ENTRY_001",
            "rule_version": "2",
            "supersedes_version": "1",
            "effective_from": "2025-02-01T00:00:00Z",
            "reason": "prospective refinement",
            "evidence_source": "PROSPECTIVE_WF",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        },
        "rule:entry1:v2",
    )
    head = _append(
        store,
        head,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_002",
            "rule_version": "1",
            "effective_from": "2025-03-01T00:00:00Z",
            "reason": "second teacher family",
            "evidence_source": "TEACHER",
            "profile": "sideways_long",
            "conditions": [{"indicator": "RSI", "condition": "LTE", "value": 45}],
        },
        "rule:entry2:v1",
    )
    head = _append(
        store,
        head,
        "VETO_LEARNED",
        {
            "rule_id": "VETO_001",
            "rule_version": "1",
            "effective_from": "2025-03-15T00:00:00Z",
            "reason": "prospective failure mode",
            "evidence_source": "PROSPECTIVE_WF",
            "profile": "bull_long",
            "conditions": [{"indicator": "RSI", "condition": "GTE", "value": 80}],
        },
        "rule:veto1:v1",
    )

    snapshot = materialize_walk_forward_strategy(
        control,
        reports,
        experiment_id="BTCUSDT_1D_WF_TEST",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
        include_config=True,
    )

    assert snapshot["rule_counts"] == {"ENTRY": 2, "VETO": 1, "FLIP": 0}
    versions = {(row["rule_id"], row["rule_version"]) for row in snapshot["active_rule_versions"]}
    assert ("ENTRY_001", "1") not in versions
    assert ("ENTRY_001", "2") in versions
    assert snapshot["enabled_profiles"] == ["bull_long", "sideways_long"]

    config = snapshot["materialized_config"]
    assert config["features"]["enable_support_resistance_analysis"] is True
    assert config["features"]["sr_zone_width_atr"] == 0.61
    assert config["execution"]["maker_fee"] == 0.00017
    assert config["execution"]["taker_fee"] == 0.00043
    assert config["execution"]["slippage"] == 0.00031
    assert config["strategy"]["profiles"]["bull_long"]["enabled"] is True
    assert config["strategy"]["profiles"]["sideways_long"]["enabled"] is True
    assert config["strategy"]["profiles"]["bear_long"]["enabled"] is False
    assert config["strategy"]["profiles"]["bull_short"]["enabled"] is False

    workspace = control.get_strategy_capabilities()
    assert "ADX" in workspace["indicators"]
    from crypto_strategy_lab.control_rule_workspace import RuleWorkspace

    compiled = RuleWorkspace(config)
    bull_entries = compiled.list_groups("bull_long", "ENTRY")["groups"]
    assert len(bull_entries) == 1
    assert bull_entries[0]["id"] == "ENTRY_001"
    assert bull_entries[0]["conditions"][0]["value"] == 30.0
    bull_vetoes = compiled.list_groups("bull_long", "VETO")["groups"]
    assert bull_vetoes[0]["id"] == "VETO_001"


def test_materialization_rejects_stale_chain_head(tmp_path):
    control, reports, store, head = _setup(tmp_path)
    original = dict(head)
    head = _append(
        store,
        head,
        "REVIEW_COMPLETED",
        {"cadence": "MONTHLY", "period": "2025-01"},
        "review:jan",
    )
    assert head["sequence"] > original["sequence"]

    with pytest.raises(ValueError, match="changed since it was read"):
        materialize_walk_forward_strategy(
            control,
            reports,
            experiment_id="BTCUSDT_1D_WF_TEST",
            expected_sequence=original["sequence"],
            expected_state_hash=original["state_hash"],
        )


def test_materialization_fails_closed_when_active_rule_has_no_executable_definition(tmp_path):
    control, reports, store, head = _setup(tmp_path)
    head = _append(
        store,
        head,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_INCOMPLETE",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "legacy metadata only",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
        },
        "rule:incomplete",
    )

    with pytest.raises(ValueError, match="no executable conditions"):
        materialize_walk_forward_strategy(
            control,
            reports,
            experiment_id="BTCUSDT_1D_WF_TEST",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
        )


def test_create_run_from_experiment_creates_draft_snapshot_and_provenance(tmp_path):
    control, reports, store, head = _setup(tmp_path)
    head = _append(
        store,
        head,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_001",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "teacher structure",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 20}],
        },
        "rule:entry1:v1",
    )

    created = create_run_from_walk_forward_experiment(
        control,
        reports,
        experiment_id="BTCUSDT_1D_WF_TEST",
        start="2025-01-01",
        end="2025-06-01",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )

    assert created["status"] == "DRAFT"
    assert "validate_run" in created["next_step"]
    provenance = created["walk_forward_provenance"]
    assert provenance["experiment_sequence"] == head["sequence"]
    assert provenance["experiment_state_hash"] == head["state_hash"]
    assert provenance["rule_counts"] == {"ENTRY": 1, "VETO": 0, "FLIP": 0}

    job = control._job(created["run_id"])
    provenance_path = job.state_dir / "walk_forward_provenance.json"
    assert provenance_path.is_file()
    persisted = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert persisted["snapshot_sha256"] == provenance["snapshot_sha256"]

    snapshot_path = control.project_root / persisted["strategy_snapshot_path"]
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["experiment_id"] == "BTCUSDT_1D_WF_TEST"
    assert snapshot["materialized_config"]["execution"]["maker_fee"] == 0.00017

    readback = control.get_rule_workspace(created["run_id"], "bull_long")
    assert [group["id"] for group in readback["entry_groups"]] == ["ENTRY_001"]
    assert control.get_run_status(created["run_id"])["status"] == "DRAFT"


def test_reference_timeframe_mismatch_is_rejected(tmp_path):
    control, reports, store, head = _setup(tmp_path)
    reports.manifest["config"]["data"]["strategy_timeframe_minutes"] = 240

    with pytest.raises(ValueError, match="strategy timeframe"):
        materialize_walk_forward_strategy(
            control,
            reports,
            experiment_id="BTCUSDT_1D_WF_TEST",
            expected_sequence=head["sequence"],
            expected_state_hash=head["state_hash"],
        )
