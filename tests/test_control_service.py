import json
from pathlib import Path
import sys

import pytest

from crypto_strategy_lab.control_service import (
    BacktestControlService,
    CANCELLED,
    COMPLETED,
    DRAFT,
    RUNNING,
)
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


class FakeProcess:
    def __init__(self, returncode=None):
        self.pid = 4242
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
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
        json.dumps(ResearchRunConfig().to_dict()),
        encoding="utf-8",
    )
    calls = []

    def factory(command, **kwargs):
        process = FakeProcess()
        calls.append((command, kwargs, process))
        return process

    service = BacktestControlService(
        project_root=project,
        raw_root=raw,
        cache_root=cache,
        output_root=output,
        config_root=configs,
        runner_script=runner,
        process_factory=factory,
    )
    service._test_calls = calls
    return service


def test_config_loading_is_confined_and_native_v3_only(control: BacktestControlService):
    assert control.list_configs() == ["base.json"]
    loaded = control.load_config("base.json")
    assert loaded["config"]["config_version"] == 3
    with pytest.raises(ValueError, match="relative path"):
        control.load_config("../secret.json")
    with pytest.raises(ValueError, match=".json"):
        control.load_config("base.txt")


def test_create_patch_filter_validate_and_start_uses_fixed_runner(control: BacktestControlService):
    draft = control.create_run(
        symbol="BTC/USDT",
        start="2025-01-01",
        end="2025-02-01",
        config_name="base.json",
        strategy_timeframe="1h",
        intrabar_timeframe="1m",
        run_name="AI controlled test",
    )
    assert draft["status"] == DRAFT
    run_id = draft["run_id"]
    assert draft["request"]["symbol"] == "BTCUSDT"
    assert draft["config"]["data"]["strategy_timeframe_minutes"] == 60
    assert draft["config"]["reporting"]["output_dir"] == str(control.output_root)

    updated = control.set_run_settings(
        run_id,
        {"strategy": {"entry_interval": 2}},
    )
    assert updated["config"]["strategy"]["entry_interval"] == 2

    filtered = control.set_filter_groups(
        run_id,
        "bull_long",
        [
            {
                "action": "REJECT",
                "indicator": "ADX",
                "condition": "INSIDE",
                "minimum": 0.0,
                "maximum": 20.0,
            }
        ],
    )
    assert filtered["preview"]["profiles"]["bull_long"]["entry_rule_count"] == 1

    validation = control.validate_run(run_id)
    assert validation["ready"] is True
    assert validation["validation_token"].startswith("v1:")

    started = control.start_run(run_id, validation["validation_token"])
    assert started["status"] == RUNNING
    command, kwargs, process = control._test_calls[-1]
    assert command[0] == sys.executable
    assert command[1] == str(control.runner_script)
    assert "--result-json" in command
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(control.project_root)
    assert process.pid == 4242

    with pytest.raises(ValueError, match="only DRAFT"):
        control.set_run_settings(run_id, {"strategy": {"entry_interval": 3}})


def test_validation_token_is_invalidated_by_any_draft_change(control: BacktestControlService):
    run_id = control.create_run(
        symbol="BTCUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )["run_id"]
    token = control.validate_run(run_id)["validation_token"]
    control.set_run_settings(run_id, {"execution": {"maker_fee": 0.0}})
    with pytest.raises(ValueError, match="validate_run again"):
        control.start_run(run_id, token)


def test_reporting_output_dir_cannot_be_redirected(control: BacktestControlService):
    run_id = control.create_run(
        symbol="BTCUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )["run_id"]
    with pytest.raises(ValueError, match="controlled"):
        control.set_run_settings(
            run_id,
            {"reporting": {"output_dir": "C:/somewhere-else"}},
        )


def test_running_job_can_be_cancelled(control: BacktestControlService):
    run_id = control.create_run(
        symbol="BTCUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )["run_id"]
    token = control.validate_run(run_id)["validation_token"]
    control.start_run(run_id, token)
    process = control._test_calls[-1][2]

    cancelled = control.cancel_run(run_id)
    assert cancelled["status"] == CANCELLED
    assert process.terminated is True


def test_successful_process_reads_machine_result(control: BacktestControlService):
    run_id = control.create_run(
        symbol="ETHUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )["run_id"]
    token = control.validate_run(run_id)["validation_token"]
    control.start_run(run_id, token)
    job = control._job(run_id)
    job.result_path.write_text(
        json.dumps(
            {
                "run_dir": str(control.output_root / "ETHUSDT_15m_test"),
                "trade_rows": 12,
                "prepared_cache_hit": True,
                "prepared_cache_key": "abc",
            }
        ),
        encoding="utf-8",
    )
    control._test_calls[-1][2].returncode = 0

    status = control.get_run_status(run_id)
    assert status["status"] == COMPLETED
    assert status["result"]["trade_rows"] == 12


def test_max_concurrency_defaults_to_one(control: BacktestControlService):
    first = control.create_run(
        symbol="BTCUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )
    second = control.create_run(
        symbol="ETHUSDT",
        start="2025-01-01",
        end="2025-02-01",
    )
    control.start_run(first["run_id"], control.validate_run(first["run_id"])["validation_token"])
    token = control.validate_run(second["run_id"])["validation_token"]
    with pytest.raises(ValueError, match="Maximum concurrent"):
        control.start_run(second["run_id"], token)
