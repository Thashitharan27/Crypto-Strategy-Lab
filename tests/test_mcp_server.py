import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.server import BacktestReports, create_server


@pytest.fixture
def reports(tmp_path: Path) -> BacktestReports:
    one = tmp_path / "run-one"
    two = tmp_path / "run-two"
    one.mkdir()
    two.mkdir()
    (one / "config.json").write_text(json.dumps({"symbol": "BTC", "strategy_timeframe_minutes": 15, "atr_period": 14}))
    (one / "summary.json").write_text(json.dumps({"total_trades": 2, "wins": 1, "ending_equity": 1100}))
    (one / "trade_list.csv").write_text("side,pnl\nLONG,10\nSHORT,-4\n")
    (two / "summary.json").write_text(json.dumps({"net_profit": 25}))
    return BacktestReports(tmp_path)


def test_paths_are_confined(reports: BacktestReports, tmp_path: Path):
    with pytest.raises(ValueError, match="traversal"):
        reports.resolve_run("../outside")
    with pytest.raises(ValueError, match="Absolute"):
        reports.resolve_run(str(tmp_path.resolve()))
    assert reports.resolve_run("run-one").name == "run-one"


def test_listing_latest_and_reads(reports: BacktestReports):
    names = {item["folder_name"] for item in reports.list_runs()}
    assert names == {"run-one", "run-two"}
    assert reports.latest_run()["folder_name"] in names
    csv_report = reports.read_report("run-one", "trade_list.csv", limit=1)
    assert csv_report["columns"] == ["side", "pnl"]
    assert csv_report["truncated"] and csv_report["row_count"] == 2
    assert reports.read_report("run-one", "summary.json")["data"]["wins"] == 1


def test_read_only_trade_queries(reports: BacktestReports):
    selected = reports.query_trades("run-one", "SELECT side, pnl FROM trades ORDER BY pnl DESC")
    assert selected["rows"][0] == ["LONG", 10]
    counted = reports.query_trades("run-one", "WITH positive AS (SELECT * FROM trades WHERE pnl > 0) SELECT count(*) FROM positive")
    assert counted["rows"] == [[1]]
    with pytest.raises(ValueError, match="read-only"):
        reports.query_trades("run-one", "DELETE FROM trades")
    with pytest.raises(ValueError, match="multiple"):
        reports.query_trades("run-one", "SELECT * FROM trades; SELECT 1")
    with pytest.raises(ValueError, match="read-only"):
        reports.query_trades("run-one", "SELECT * FROM read_csv('/etc/passwd')")


def test_compare_tolerates_missing_optional_fields(reports: BacktestReports):
    compared = reports.compare_runs(["run-one", "run-two"])
    assert compared[0]["symbol"] == "BTC"
    assert compared[0]["total_trades"] == 2
    assert compared[1]["symbol"] is None
    assert compared[1]["net_profit"] == 25


def test_create_server_uses_v2_sdk_and_registers_six_tools(reports: BacktestReports):
    from mcp.server import MCPServer

    server = create_server(reports)

    assert isinstance(server, MCPServer)
    assert set(server._tool_manager._tools) == {
        "list_runs",
        "latest_run",
        "list_run_files",
        "read_report",
        "query_trades",
        "compare_runs",
    }


def test_package_does_not_eagerly_import_server_module():
    result = subprocess.run(
        [sys.executable, "-c", "import mcp_server, sys; print('mcp_server.server' in sys.modules)"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
