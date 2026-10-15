"""Exercise the real localhost chart server from the browser launch API."""
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import urlopen
from unittest.mock import Mock, patch
import json

import pytest

from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_visualizer_coordinator import BrowserVisualizerCoordinator


def test_user_launch_reuses_chart_server_and_releases_it_at_shutdown(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    model = Mock()
    model.seed.request = SimpleNamespace(symbol="BTCUSDT", strategy_timeframe="4h")
    model.manifest = {"run_id": "BTCUSDT_4h_test"}
    model.run_dir = tmp_path / "BTCUSDT_4h_test"
    model.trade_count = 0
    model.available_chart_timeframes.return_value = []
    model.build_payload.return_value = {
        "run": {"runId": "BTCUSDT_4h_test", "symbol": "BTCUSDT"},
        "candles": [], "markers": [], "positionBox": {},
    }
    coordinator = BrowserVisualizerCoordinator(Mock(), tmp_path)
    app = create_browser_app(token="t" * 48, visualizer_coordinator=coordinator)
    with patch("crypto_strategy_lab.browser_visualizer_coordinator.load_browser_visualizer", return_value=model) as load:
        with TestClient(app, base_url="http://127.0.0.1:8767") as client:
            response = client.post("/api/v1/visualizer/sessions/BTCUSDT_4h_test", headers={
                "Authorization": "Bearer " + "t" * 48,
                "Origin": "http://127.0.0.1:8767",
            })
            assert response.status_code == 201
            chart_url = response.json()["url"]
            assert chart_url.startswith("http://127.0.0.1:")
            load.assert_called_once_with(coordinator._service, tmp_path, "BTCUSDT_4h_test")
            with urlopen(chart_url, timeout=5) as html:
                assert b"BTCUSDT_4h_test" in html.read()
            with urlopen(chart_url + "api/payload?full_run=1", timeout=5) as payload:
                assert json.loads(payload.read())["run"]["runId"] == "BTCUSDT_4h_test"
            model.build_payload.assert_called_once()
        # Lifespan shutdown closes the temporary visualizer listener.
        with pytest.raises((URLError, OSError)):
            urlopen(chart_url, timeout=2)
