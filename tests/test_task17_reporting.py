"""Blocking contract tests for Task-17 manifest primitives."""
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.run_manifest import (
    RUN_MANIFEST_CONTRACT, RUN_MANIFEST_VERSION, RunArtifactError,
    canonical_sha256, config_hashes, load_completed_manifest,
    selected_source_snapshot,
)


def test_hash_scopes_exclude_reporting_and_separate_strategy_execution():
    base = ResearchRunConfig()
    first = config_hashes(base, "1m")
    changed_report = ResearchRunConfig(reporting=type(base.reporting)(run_name="presentation"))
    second = config_hashes(changed_report, "1m")
    assert first["strategy_hash"] == second["strategy_hash"]
    assert first["execution_hash"] == second["execution_hash"]

    changed_execution = ResearchRunConfig(
        execution=type(base.execution)(taker_fee=base.execution.taker_fee + .001)
    )
    execution = config_hashes(changed_execution, "1m")
    assert execution["strategy_hash"] == first["strategy_hash"]
    assert execution["execution_hash"] != first["execution_hash"]


def test_selected_snapshot_is_deterministic_and_sensitive_to_contributors():
    class Record:
        exchange = "binance"; market = "futures_um"; dataset = "klines"
        symbol = "BTCUSDT"; interval = "1m"; frequency = "monthly"
        period_start = None; period_end = None; size_bytes = 10; mtime_ns = 20
        fingerprint = "one"

    rows, digest = selected_source_snapshot([Record(), Record()])
    assert len(rows) == 1
    assert selected_source_snapshot([Record()])[1] == digest
    Record.fingerprint = "two"
    assert selected_source_snapshot([Record()])[1] != digest


def test_incomplete_or_wrong_contract_manifest_is_not_completed(tmp_path: Path):
    with pytest.raises(RunArtifactError):
        load_completed_manifest(tmp_path)
    (tmp_path / "run_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunArtifactError):
        load_completed_manifest(tmp_path)
    assert RUN_MANIFEST_CONTRACT == "crypto_strategy_lab_run_v1"
    assert RUN_MANIFEST_VERSION == 1
    assert len(canonical_sha256({"stable": True})) == 64
