import json
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.rule_control_service import RuleAwareBacktestControlService


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


def _group(group_id="learned_veto"):
    return {
        "id": group_id,
        "name": "Learned MR veto",
        "enabled": True,
        "match_mode": "ALL",
        "conditions": [
            {"indicator": "MR_STATE", "condition": "EQUALS", "value": "ABOVE_MEAN"},
            {"indicator": "MR_MOTION", "condition": "EQUALS", "value": "AWAY_FROM_MEAN"},
        ],
    }


def test_rule_mutation_invalidates_validation_and_readback_is_exact(control):
    run_id = control.create_run(
        symbol="BTCUSDT",
        start="2025-01-01",
        end="2025-02-01",
        config_name="base.json",
    )["run_id"]
    token = control.validate_run(run_id)["validation_token"]

    changed = control.add_rule_group(run_id, "bull_long", "VETO", _group())
    assert changed["validation_invalidated"] is True
    assert changed["changed"]["id"] == "learned_veto"
    assert changed["readback"]["groups"][0]["conditions"][0]["value"] == "ABOVE_MEAN"

    workspace = control.get_rule_workspace(run_id, "bull_long")
    assert [group["id"] for group in workspace["veto_groups"]] == ["learned_veto"]
    assert workspace["veto_groups"][0]["conditions"][1]["value"] == "AWAY_FROM_MEAN"

    with pytest.raises(ValueError, match="validate_run again"):
        control.start_run(run_id, token)


def test_group_can_be_muted_restored_updated_and_deleted_independently(control):
    run_id = control.create_run(
        symbol="BTCUSDT", start="2025-01-01", end="2025-02-01"
    )["run_id"]
    control.add_rule_group(run_id, "bull_long", "VETO", _group("veto_a"))
    control.add_rule_group(
        run_id,
        "bull_long",
        "VETO",
        {
            "id": "veto_b",
            "conditions": [
                {
                    "indicator": "MR_STATE",
                    "condition": "EQUALS",
                    "value": "STRONGLY_ABOVE_MEAN",
                }
            ],
        },
    )

    control.mute_rule_group(run_id, "veto_a")
    groups = {
        group["id"]: group
        for group in control.list_rule_groups(run_id, "bull_long", "VETO")["groups"]
    }
    assert groups["veto_a"]["enabled"] is False
    assert groups["veto_b"]["enabled"] is True

    control.unmute_rule_group(run_id, "veto_a")
    control.update_rule_group(run_id, "veto_b", {"name": "Strong extension"})
    groups = {
        group["id"]: group
        for group in control.list_rule_groups(run_id, "bull_long", "VETO")["groups"]
    }
    assert groups["veto_a"]["enabled"] is True
    assert groups["veto_b"]["name"] == "Strong extension"

    control.delete_rule_group(run_id, "veto_b")
    assert [
        group["id"]
        for group in control.list_rule_groups(run_id, "bull_long", "VETO")["groups"]
    ] == ["veto_a"]


def test_capabilities_and_control_info_steer_clients_to_group_api(control):
    caps = control.get_strategy_capabilities()
    assert caps["indicators"]["MR_MOTION"]["values"] == [
        "TOWARD_MEAN",
        "AWAY_FROM_MEAN",
        "FLAT",
    ]
    assert caps["rule_group_model"]["groups_inside_family"] == "OR"

    info = control.info()
    assert "get_strategy_capabilities" in info["preferred_rule_workflow"]
    assert "set_filter_groups" in info["legacy_control"]
