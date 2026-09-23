from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from crypto_strategy_lab.strategy_visualizer_browser import (
    BROWSER_DEFAULT_VISIBLE_CANDLES,
    StrategyVisualizerBrowserServer,
    build_browser_visualizer_html,
)


class _FakeVisualizer:
    def __init__(self):
        self.seed = SimpleNamespace(
            request=SimpleNamespace(symbol="BTCUSDT", strategy_timeframe="4h")
        )
        self.manifest = {"run_id": "browser-test-run"}
        self.run_dir = Path("browser-test-run")
        self.trade_count = 2
        self.payload_calls = []
        self.inspect_calls = []

    def trade_label(self, index: int) -> str:
        return f"{index + 1}/2 · #{index + 10} · LONG"

    def build_payload(
        self,
        *,
        trade_index=None,
        visible_candles=BROWSER_DEFAULT_VISIBLE_CANDLES,
        show_rejections=False,
    ):
        self.payload_calls.append(
            (trade_index, visible_candles, show_rejections)
        )
        return {
            "run": {
                "runId": "browser-test-run",
                "symbol": "BTCUSDT",
                "timeframe": "4h",
            },
            "selectedTradeIndex": trade_index,
            "selectedTrade": {"Side": "LONG"},
            "selectedTradeCandleTime": 1_700_000_000,
            "candles": [],
            "overlays": [],
            "srZones": [],
            "srEvents": [],
            "markers": [],
            "priceLines": [],
            "candleContext": {},
            "visibleStart": 1_699_000_000,
            "visibleEnd": 1_701_000_000,
        }

    def rule_inspector_at(self, timestamp):
        self.inspect_calls.append(timestamp)
        return {
            "status": "AVAILABLE",
            "timestamp": str(timestamp),
            "rows": [],
        }

    def sr_inspector_at(self, timestamp):
        return {
            "status": "AVAILABLE",
            "timestamp": str(timestamp),
            "timeframes": [],
            "zones": [],
        }


def test_browser_visualizer_html_exposes_full_window_audit_controls():
    model = _FakeVisualizer()
    html = build_browser_visualizer_html(model, "test-token")

    assert "Strategy Visualizer · Browser Audit" in html
    assert 'id="window-size"' in html
    assert 'id="toggle-inspector"' in html
    assert 'id="fullscreen"' in html
    assert 'id="view-mode"' in html
    assert 'id="sr-tf"' in html
    assert 'id="sr-snapshot"' in html
    assert 'id="nearest-only"' in html
    assert "Pan/zoom freely" in html
    assert "Click a zone below to isolate it on the chart" in html
    assert "/session/test-token" in html
    assert "/api/payload" in html
    assert "/api/inspect" in html
    assert "handleScroll" in html
    assert "handleScale" in html


def test_browser_visualizer_server_is_loopback_read_only_and_serves_model():
    model = _FakeVisualizer()
    server = StrategyVisualizerBrowserServer(model)
    try:
        url = server.start()
        assert url.startswith("http://127.0.0.1:")
        assert f"/session/{server.token}/" in url

        with urlopen(url, timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "browser-test-run" in html

        with urlopen(
            url
            + "api/payload?trade_index=1&visible_candles=2000&show_rejections=1",
            timeout=5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["selectedTradeIndex"] == 1
        assert model.payload_calls[-1] == (1, 2000, True)

        with urlopen(
            url + "api/inspect?timestamp=1700000000",
            timeout=5,
        ) as response:
            inspection = json.loads(response.read().decode("utf-8"))
        assert inspection["rule"]["status"] == "AVAILABLE"
        assert inspection["sr"]["status"] == "AVAILABLE"
        assert model.inspect_calls
    finally:
        server.stop()
