from mcp_server.control_server import create_control_server


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


def test_control_server_registers_only_bounded_backtest_actions():
    from mcp.server import MCPServer

    server = create_control_server(FakeControl())
    assert isinstance(server, MCPServer)
    assert set(server._tool_manager._tools) == {
        "control_info",
        "list_configs",
        "load_config",
        "create_run",
        "set_run_settings",
        "set_filter_groups",
        "validate_run",
        "start_run",
        "get_run_status",
        "list_control_runs",
        "cancel_run",
        "read_control_log",
    }
    assert "shell" not in server._tool_manager._tools
    assert "live_trade" not in server._tool_manager._tools
    assert "place_order" not in server._tool_manager._tools
