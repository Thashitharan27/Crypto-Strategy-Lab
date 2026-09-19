from unittest.mock import Mock

import duckdb
import pandas as pd
from PySide6.QtCore import QProcess

from crypto_strategy_lab.gui.chatgpt_connection import ChatGPTConnectionManager
from crypto_strategy_lab.walk_forward_candidate_engine import _candidate_rows


def test_connected_gui_does_not_call_busy_socket_probe(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    manager.state = "Connected"
    manager._mcp_started = True
    manager._tunnel_started = True
    manager.mcp = Mock()
    manager.tunnel = Mock()
    manager.mcp.state.return_value = QProcess.Running
    manager.tunnel.state.return_value = QProcess.Running
    manager._reachable = Mock(return_value=False)

    observed = []
    manager.state_changed.connect(lambda *args: observed.append(args))
    manager._poll()

    assert manager.state == "Connected"
    manager._reachable.assert_not_called()
    assert observed[-1] == ("Connected", "Running", "Running")


def _write_parquet(connection, frame, table_name, path):
    connection.register(table_name, frame)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY {table_name} TO '{escaped}' (FORMAT PARQUET)")


def test_candidate_rows_stream_from_duckdb_instead_of_materializing_all(tmp_path):
    samples_path = tmp_path / "samples.parquet"
    context_path = tmp_path / "context.parquet"
    samples = pd.DataFrame(
        {
            "research_signal_index": [1, 2, 3],
            "walk_forward_candidate_id": ["wf-1-long", "wf-2-long", "wf-3-long"],
            "walk_forward_candidate_source": [True, True, True],
            "strategy_profile_key": ["bull_long"] * 3,
            "side": ["LONG"] * 3,
            "entry_time": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03"], utc=True
            ),
            "adx": [20.0, 21.0, 22.0],
        }
    )
    context = pd.DataFrame(
        {
            "strategy_index": [1, 2, 3],
            "decision_available_at": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03"], utc=True
            ),
            "adx": [20.0, 21.0, 22.0],
        }
    )
    with duckdb.connect(":memory:") as connection:
        _write_parquet(connection, samples, "samples", samples_path)
        _write_parquet(connection, context, "context", context_path)

    streamed = _candidate_rows(samples_path, context_path, None, 3)
    assert not isinstance(streamed, pd.DataFrame)
    rows = list(streamed.iterrows())
    assert [int(series["research_signal_index"]) for _, series in rows] == [1, 2, 3]
