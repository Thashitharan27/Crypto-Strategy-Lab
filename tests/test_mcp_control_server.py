from mcp_server.control_server import CONTROL_TOOLS, READ_TOOLS, create_control_server


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
    assert set(server._tool_manager._tools) == set(CONTROL_TOOLS) | set(READ_TOOLS)

    # The unified endpoint may start backtests and analyze completed outputs, but
    # its write boundary must remain backtest-only.
    assert "shell" not in server._tool_manager._tools
    assert "live_trade" not in server._tool_manager._tools
    assert "place_order" not in server._tool_manager._tools
    assert "edit_source" not in server._tool_manager._tools


def test_unified_server_keeps_expected_tool_groups_stable():
    assert set(CONTROL_TOOLS) == {
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
