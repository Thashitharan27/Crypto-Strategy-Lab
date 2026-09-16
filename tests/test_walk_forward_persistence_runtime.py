from __future__ import annotations

import json
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.rule_control_service import RuleAwareBacktestControlService


class FakeProcess:
    pid = 4242
    returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0


@pytest.fixture
def control(tmp_path: Path):
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
    (configs / "base.json").write_text(
        json.dumps(ResearchRunConfig().to_dict()), encoding="utf-8"
    )
    return RuleAwareBacktestControlService(
        project_root=project,
        raw_root=raw,
        cache_root=cache,
        output_root=output,
        config_root=configs,
        runner_script=runner,
        process_factory=lambda *args, **kwargs: FakeProcess(),
    )


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "1d",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 1.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": "BTCUSDT_1d_reference",
    }


def test_unified_scope_describes_causal_research_persistence(control):
    info = control.info()
    assert info["scope"] == "BACKTEST_CONTROL_AND_CAUSAL_RESEARCH"
    assert info["safety"]["live_trading"] is False
    assert "structured response" in info["causal_experiments"]["error_contract"]


def test_missing_experiment_returns_structured_error_without_raising(control):
    result = control.read_walk_forward_experiment("DOES_NOT_EXIST")

    assert result["ok"] is False
    assert result["operation"] == "read_walk_forward_experiment"
    assert result["error_type"] == "ValueError"
    assert result["connection_safe"] is True
    assert "does not exist" in result["error"]


def test_store_initialization_failure_is_contained(control, monkeypatch):
    def fail_store():
        raise PermissionError("test write permission denied")

    monkeypatch.setattr(control, "_causal_experiment_store", fail_store)
    result = control.create_walk_forward_experiment(
        "BTCUSDT_1D_TEST",
        _definition(),
        "create:test",
    )

    assert result == {
        "ok": False,
        "operation": "create_walk_forward_experiment",
        "error_type": "PermissionError",
        "error": "test write permission denied",
        "connection_safe": True,
        "instruction": (
            "The persistence operation failed without terminating the MCP process. "
            "Fix the reported local state/path/hash issue, then retry."
        ),
    }


def test_list_store_failure_preserves_list_schema(control, monkeypatch):
    def fail_store():
        raise OSError("test storage unavailable")

    monkeypatch.setattr(control, "_causal_experiment_store", fail_store)
    result = control.list_walk_forward_experiments()

    assert isinstance(result, list)
    assert result[0]["ok"] is False
    assert result[0]["operation"] == "list_walk_forward_experiments"
    assert result[0]["error_type"] == "OSError"


def test_successful_experiment_round_trip_keeps_existing_shape(control):
    created = control.create_walk_forward_experiment(
        "BTCUSDT_1D_TEST",
        _definition(),
        "create:test",
    )
    assert "ok" not in created
    assert created["sequence"] == 1

    readback = control.read_walk_forward_experiment("BTCUSDT_1D_TEST")
    assert "ok" not in readback
    assert readback["state_hash"] == created["state_hash"]
    assert readback["manifest"]["definition"]["symbol"] == "BTCUSDT"


def test_legacy_markdown_state_failure_is_also_contained(control):
    result = control.read_walk_forward_state("MISSING_STATE")
    assert result["ok"] is False
    assert result["operation"] == "read_walk_forward_state"
    assert result["connection_safe"] is True
