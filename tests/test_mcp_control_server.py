from types import SimpleNamespace

import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.walk_forward_candidate_engine import teacher_loss_flip_policy
import mcp_server.control_server as control_server_module
from mcp_server.control_server import (
    CAUSAL_EXPERIMENT_TOOLS,
    CONTROL_TOOLS,
    READ_TOOLS,
    WALK_FORWARD_STATE_TOOLS,
    create_control_server,
)


class FakeControl:
    def info(self):
        return {"scope": "BACKTEST_ONLY"}

    def list_configs(self):
        return []

    def load_config(self, name):
        return {"name": name}

    def create_run(self, **kwargs):
        return kwargs

    def set_run_settings(self, run_id, patch):
        return {"run_id": run_id, "patch": patch}

    def get_strategy_capabilities(self):
        return {"indicators": {}}

    def get_rule_workspace(self, run_id, profile=None):
        return {"run_id": run_id, "profile": profile}

    def list_rule_groups(self, run_id, profile, family):
        return {"run_id": run_id, "profile": profile, "family": family}

    def set_rule_groups(self, run_id, profile, family, groups):
        return {"run_id": run_id, "profile": profile, "family": family, "groups": groups}

    def add_rule_group(self, run_id, profile, family, group):
        return {"run_id": run_id, "profile": profile, "family": family, "group": group}

    def update_rule_group(self, run_id, group_id, patch):
        return {"run_id": run_id, "group_id": group_id, "patch": patch}

    def delete_rule_group(self, run_id, group_id):
        return {"run_id": run_id, "group_id": group_id}

    def mute_rule_group(self, run_id, group_id):
        return {"run_id": run_id, "group_id": group_id, "enabled": False}

    def unmute_rule_group(self, run_id, group_id):
        return {"run_id": run_id, "group_id": group_id, "enabled": True}

    def set_filter_groups(self, run_id, profile, rules, **kwargs):
        return {"run_id": run_id, "profile": profile, "rules": rules, **kwargs}

    def validate_run(self, run_id):
        return {"run_id": run_id, "ready": True}

    def start_run(self, run_id, validation_token):
        return {"run_id": run_id, "validation_token": validation_token}

    def get_run_status(self, run_id):
        return {"run_id": run_id}

    def list_control_runs(self, limit):
        return [{"limit": limit}]

    def cancel_run(self, run_id):
        return {"run_id": run_id, "status": "CANCELLED"}

    def read_control_log(self, run_id, stream, lines):
        return {"run_id": run_id, "stream": stream, "lines": lines}

    def create_walk_forward_state(self, state_id, markdown, initial_event=None):
        return {"state_id": state_id, "markdown": markdown, "initial_event": initial_event}

    def read_walk_forward_state(self, state_id, recent_events=50):
        return {"state_id": state_id, "recent_events": recent_events}

    def update_walk_forward_state(self, state_id, markdown, expected_sha256, event=None):
        return {
            "state_id": state_id,
            "markdown": markdown,
            "expected_sha256": expected_sha256,
            "event": event,
        }

    def append_walk_forward_event(self, state_id, event):
        return {"state_id": state_id, "event": event}

    def create_walk_forward_experiment(
        self, experiment_id, definition, operation_id, initial_phase="RESEARCH_WF", notes=None
    ):
        return {
            "experiment_id": experiment_id,
            "definition": definition,
            "operation_id": operation_id,
            "initial_phase": initial_phase,
            "notes": notes,
        }

    def read_walk_forward_experiment(self, experiment_id, recent_events=100):
        return {"experiment_id": experiment_id, "recent_events": recent_events}

    def list_walk_forward_experiments(self):
        return []

    def append_walk_forward_experiment_event(
        self,
        experiment_id,
        event_type,
        payload,
        operation_id,
        expected_sequence,
        expected_state_hash,
        effective_market_time=None,
        event_time=None,
        source="CHATGPT_RESEARCH",
    ):
        return {
            "experiment_id": experiment_id,
            "event_type": event_type,
            "payload": payload,
            "operation_id": operation_id,
            "expected_sequence": expected_sequence,
            "expected_state_hash": expected_state_hash,
            "effective_market_time": effective_market_time,
            "event_time": event_time,
            "source": source,
        }


class FakeReports:
    def list_runs(self, limit):
        return [{"folder_name": "run-one", "limit": limit}]

    def latest_run(self):
        return {"folder_name": "run-one"}

    def get_run_manifest(self, run):
        return {"run_id": run}

    def list_run_files(self, run):
        return [{"run": run, "filename": "summary.json"}]

    def read_report(self, run, filename, sheet, limit):
        return {"run": run, "filename": filename, "sheet": sheet, "limit": limit}

    def read_run_file(self, run, filename, sheet, limit):
        return {"run": run, "filename": filename, "sheet": sheet, "limit": limit}

    def query_trades(self, run, sql):
        return {"run": run, "sql": sql, "kind": "trades"}

    def query_signals(self, run, sql):
        return {"run": run, "sql": sql, "kind": "signals"}

    def query_feature_context(self, run, sql):
        return {"run": run, "sql": sql, "kind": "feature_context"}

    def query_parquet(self, run, filename, sql):
        return {"run": run, "filename": filename, "sql": sql}

    def research_aggregate(self, run, spec):
        return {"run": run, "spec": spec}

    def compare_runs(self, runs):
        return [{"run": run} for run in runs]


def test_control_server_registers_unified_research_and_bounded_control_tools():
    from mcp.server import MCPServer

    server = create_control_server(FakeControl(), FakeReports())
    assert isinstance(server, MCPServer)
    assert set(server._tool_manager._tools) == (
        set(CONTROL_TOOLS)
        | set(WALK_FORWARD_STATE_TOOLS)
        | set(CAUSAL_EXPERIMENT_TOOLS)
        | set(READ_TOOLS)
    )
    assert "shell" not in server._tool_manager._tools
    assert "live_trade" not in server._tool_manager._tools
    assert "place_order" not in server._tool_manager._tools
    assert "edit_source" not in server._tool_manager._tools
    assert "write_file" not in server._tool_manager._tools


def test_unified_server_keeps_expected_tool_groups_stable():
    assert set(CONTROL_TOOLS) == {
        "mcp_health_status",
        "control_info",
        "list_configs",
        "load_config",
        "create_run",
        "set_run_settings",
        "get_strategy_capabilities",
        "get_rule_workspace",
        "list_rule_groups",
        "set_rule_groups",
        "add_rule_group",
        "update_rule_group",
        "delete_rule_group",
        "mute_rule_group",
        "unmute_rule_group",
        "set_filter_groups",
        "validate_run",
        "start_run",
        "get_run_status",
        "list_control_runs",
        "cancel_run",
        "read_control_log",
    }
    assert set(WALK_FORWARD_STATE_TOOLS) == {
        "create_walk_forward_state",
        "read_walk_forward_state",
        "update_walk_forward_state",
        "append_walk_forward_event",
    }
    assert set(CAUSAL_EXPERIMENT_TOOLS) == {
        "create_walk_forward_experiment",
        "read_walk_forward_experiment",
        "summarize_walk_forward_monthly",
        "summarize_walk_forward_rule_performance",
        "summarize_walk_forward_periodic_review",
        "list_walk_forward_experiments",
        "append_walk_forward_experiment_event",
        "get_next_walk_forward_candidate",
        "freeze_and_reveal_walk_forward_candidate",
        "resolve_walk_forward_trade",
        "advance_walk_forward",
        "continue_walk_forward_autonomous",
        "submit_walk_forward_decision",
        "record_walk_forward_review",
        "record_walk_forward_teacher_review",
        "materialize_walk_forward_strategy",
        "create_run_from_walk_forward_experiment",
    }
    assert set(READ_TOOLS) == {
        "list_runs",
        "latest_run",
        "get_run_manifest",
        "list_run_files",
        "read_report",
        "read_run_file",
        "query_trades",
        "query_signals",
        "query_feature_context",
        "query_parquet",
        "research_aggregate",
        "compare_runs",
    }


def _review_cache_definition():
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "15m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 3.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": "BTCUSDT_15m_reference",
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def test_review_packet_cache_recovers_same_head_without_state_mutation(tmp_path):
    control = SimpleNamespace(project_root=tmp_path / "project")
    store = CausalExperimentStore(
        control.project_root / "walk_forward_experiments"
    )
    head = store.create(
        "BTCUSDT_15M_WF_CACHE_TEST",
        _review_cache_definition(),
        "create:cache-test",
    )
    args = (control, object())
    kwargs = {
        "experiment_id": "BTCUSDT_15M_WF_CACHE_TEST",
        "operation_id": "autonomous:first",
        "expected_sequence": head["sequence"],
        "expected_state_hash": head["state_hash"],
        "review_interval_months": 3,
    }
    packet = {
        "status": "TEACHER_LOSS_REVIEW_REQUIRED",
        "experiment_id": kwargs["experiment_id"],
        "sequence": head["sequence"],
        "state_hash": head["state_hash"],
        "teacher": {
            "pair_id": "wf-14594-short",
            "result": "LOSS",
        },
        "entry_context": {"feature_context": {"adx": 28.21}},
    }

    with teacher_loss_flip_policy(True):
        persisted = control_server_module._persist_review_packet(
            control_server_module._ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS,
            args,
            kwargs,
            packet,
        )
        recovered = control_server_module._load_cached_review_packet(
            control_server_module._ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS,
            args,
            {**kwargs, "operation_id": "autonomous:recovery"},
        )

    assert persisted["review_packet_cache"]["persisted"] is True
    assert persisted["review_packet_cache"]["hit"] is False
    assert recovered is not None
    assert recovered["status"] == "TEACHER_LOSS_REVIEW_REQUIRED"
    assert recovered["teacher"]["pair_id"] == "wf-14594-short"
    assert recovered["review_packet_cache"]["hit"] is True
    assert recovered["review_packet_cache"]["persisted"] is True
    assert recovered["autonomous"]["assistant_judgment_required"] is True
    readback = store.read(kwargs["experiment_id"], recent_events=10)
    assert readback["sequence"] == head["sequence"]
    assert readback["state_hash"] == head["state_hash"]
    assert [event["event_type"] for event in readback["recent_events"]] == ["WF_CREATED"]


def test_review_packet_cache_is_invalid_after_authoritative_head_moves(tmp_path):
    control = SimpleNamespace(project_root=tmp_path / "project")
    store = CausalExperimentStore(
        control.project_root / "walk_forward_experiments"
    )
    head = store.create(
        "BTCUSDT_15M_WF_CACHE_STALE",
        _review_cache_definition(),
        "create:cache-stale",
    )
    args = (control, object())
    kwargs = {
        "experiment_id": "BTCUSDT_15M_WF_CACHE_STALE",
        "operation_id": "autonomous:first",
        "expected_sequence": head["sequence"],
        "expected_state_hash": head["state_hash"],
        "review_interval_months": 3,
    }
    packet = {
        "status": "TEACHER_REVIEW_REQUIRED",
        "experiment_id": kwargs["experiment_id"],
        "sequence": head["sequence"],
        "state_hash": head["state_hash"],
        "teacher": {"pair_id": "wf-10-long", "result": "WIN"},
    }

    with teacher_loss_flip_policy(False):
        control_server_module._persist_review_packet(
            control_server_module._ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS,
            args,
            kwargs,
            packet,
        )

    store.append_event(
        kwargs["experiment_id"],
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "TEST", "reason": "advance authoritative head"},
        "checkpoint:move-head",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00+00:00",
        source="SYSTEM",
    )

    with teacher_loss_flip_policy(False):
        with pytest.raises(ValueError, match="changed since it was read"):
            control_server_module._load_cached_review_packet(
                control_server_module._ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS,
                args,
                kwargs,
            )


def test_mcp_advance_recovers_exact_seq1_to40_to43_self_stale_pattern(tmp_path):
    control = SimpleNamespace(project_root=tmp_path / "project")
    store = CausalExperimentStore(
        control.project_root / "walk_forward_experiments"
    )
    experiment_id = "BTCUSDT_15M_WF_MCP_SELF_STALE"
    head = store.create(
        experiment_id,
        _review_cache_definition(),
        "create:mcp-self-stale",
    )
    calls = {"count": 0}

    def append_same_operation_batch(kwargs, count):
        current = store.read_fast(experiment_id, recent_events=0)
        for offset in range(count):
            appended = store.append_event(
                experiment_id,
                "CHECKPOINT_CREATED",
                {
                    "checkpoint_type": "MCP_SELF_STALE_TEST",
                    "batch_call": calls["count"],
                    "offset": offset + 1,
                },
                (
                    kwargs["operation_id"]
                    + f":internal-{calls['count']}-{offset + 1}"
                ),
                current["sequence"],
                current["state_hash"],
                effective_market_time=(
                    f"2025-01-{min(28, 2 + offset):02d}T"
                    f"{min(23, offset):02d}:00:00+00:00"
                ),
                source="DETERMINISTIC_ORCHESTRATOR",
            )
            current = {
                "sequence": appended["sequence"],
                "state_hash": appended["state_hash"],
            }
        return current

    def fake_action(*args, **kwargs):
        calls["count"] += 1
        current = store.read_fast(experiment_id, recent_events=0)
        assert int(kwargs["expected_sequence"]) == int(current["sequence"])
        assert str(kwargs["expected_state_hash"]) == str(current["state_hash"])

        if calls["count"] == 1:
            advanced = append_same_operation_batch(kwargs, 39)
            assert advanced["sequence"] == 40
            raise ValueError(
                "walk-forward experiment changed since it was read; "
                "read the verified chain head again"
            )

        if calls["count"] == 2:
            advanced = append_same_operation_batch(kwargs, 3)
            assert advanced["sequence"] == 43
            raise ValueError(
                "walk-forward experiment changed since it was read; "
                "read the verified chain head again"
            )

        current = store.read_fast(experiment_id, recent_events=0)
        assert current["sequence"] == 43
        return {
            "status": "PERIODIC_REVIEW_REQUIRED",
            "experiment_id": experiment_id,
            "sequence": current["sequence"],
            "state_hash": current["state_hash"],
            "review_interval_months": 3,
        }

    args = (control, object())
    kwargs = {
        "experiment_id": experiment_id,
        "operation_id": "advance:mcp-self-stale",
        "expected_sequence": head["sequence"],
        "expected_state_hash": head["state_hash"],
        "review_interval_months": 3,
        "max_transitions": 100,
    }

    result = control_server_module._with_create_advance_grace(
        fake_action, *args, **kwargs
    )

    assert calls["count"] == 3
    assert result["status"] == "PERIODIC_REVIEW_REQUIRED"
    assert result["mcp_internal_head_handoffs"] == 2
    persisted = store.read_fast(experiment_id, recent_events=0)
    assert result["sequence"] == persisted["sequence"] == 43
    assert result["state_hash"] == persisted["state_hash"]


def test_mcp_review_packet_reconciles_same_operation_tail_before_cache(tmp_path):
    control = SimpleNamespace(project_root=tmp_path / "project")
    store = CausalExperimentStore(
        control.project_root / "walk_forward_experiments"
    )
    experiment_id = "BTCUSDT_15M_WF_MCP_STALE_PACKET"
    head = store.create(
        experiment_id,
        _review_cache_definition(),
        "create:mcp-stale-packet",
    )

    appended = store.append_event(
        experiment_id,
        "CHECKPOINT_CREATED",
        {"checkpoint_type": "MCP_PACKET_TAIL"},
        "advance:mcp-packet:boundary",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-02T00:00:00+00:00",
        source="DETERMINISTIC_ORCHESTRATOR",
    )

    args = (control, object())
    kwargs = {
        "experiment_id": experiment_id,
        "operation_id": "advance:mcp-packet",
        "expected_sequence": head["sequence"],
        "expected_state_hash": head["state_hash"],
        "review_interval_months": 3,
    }
    stale_packet = {
        "status": "PERIODIC_REVIEW_REQUIRED",
        "experiment_id": experiment_id,
        "sequence": head["sequence"],
        "state_hash": head["state_hash"],
        "review_interval_months": 3,
    }

    reconciled = control_server_module._reconcile_review_result_head(
        args, kwargs, stale_packet
    )
    assert reconciled["sequence"] == appended["sequence"]
    assert reconciled["state_hash"] == appended["state_hash"]
    assert reconciled["post_action_head_reconciliation"]["same_operation_only"] is True

    persisted = control_server_module._persist_review_packet(
        control_server_module._ORIGINAL_ADVANCE_WALK_FORWARD,
        args,
        kwargs,
        stale_packet,
    )
    assert persisted["sequence"] == appended["sequence"]
    assert persisted["state_hash"] == appended["state_hash"]
    assert persisted["review_packet_cache"]["persisted"] is True


def test_mcp_self_stale_recovery_rejects_foreign_tail(tmp_path):
    control = SimpleNamespace(project_root=tmp_path / "project")
    store = CausalExperimentStore(
        control.project_root / "walk_forward_experiments"
    )
    experiment_id = "BTCUSDT_15M_WF_MCP_FOREIGN"
    head = store.create(
        experiment_id,
        _review_cache_definition(),
        "create:mcp-foreign",
    )

    def fake_action(*args, **kwargs):
        current = store.read_fast(experiment_id, recent_events=0)
        store.append_event(
            experiment_id,
            "CHECKPOINT_CREATED",
            {"checkpoint_type": "FOREIGN_MUTATION"},
            "another-operation:boundary",
            current["sequence"],
            current["state_hash"],
            effective_market_time="2025-01-02T00:00:00+00:00",
            source="DETERMINISTIC_ORCHESTRATOR",
        )
        raise ValueError(
            "walk-forward experiment changed since it was read; "
            "read the verified chain head again"
        )

    args = (control, object())
    kwargs = {
        "experiment_id": experiment_id,
        "operation_id": "advance:mcp-foreign",
        "expected_sequence": head["sequence"],
        "expected_state_hash": head["state_hash"],
        "review_interval_months": 3,
        "max_transitions": 100,
    }

    with pytest.raises(ValueError, match="changed since it was read"):
        control_server_module._with_create_advance_grace(
            fake_action, *args, **kwargs
        )
