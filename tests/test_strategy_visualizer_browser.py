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

    def available_chart_timeframes(self):
        return [
            {
                "interval": "1h",
                "coverage": "full",
                "strategyTimeframe": False,
                "first": "2026-01-01T00:00:00+00:00",
                "last": "2026-01-02T00:00:00+00:00",
            },
            {
                "interval": "4h",
                "coverage": "full",
                "strategyTimeframe": True,
                "first": "2026-01-01T00:00:00+00:00",
                "last": "2026-01-02T00:00:00+00:00",
            },
        ]

    def trade_label(self, index: int) -> str:
        return f"{index + 1}/2 · #{index + 10} · LONG"

    def build_payload(
        self,
        *,
        trade_index=None,
        visible_candles=BROWSER_DEFAULT_VISIBLE_CANDLES,
        show_rejections=False,
        full_run=False,
        chart_timeframe=None,
    ):
        self.payload_calls.append(
            (
                trade_index,
                visible_candles,
                show_rejections,
                full_run,
                chart_timeframe,
            )
        )
        return {
            "run": {
                "runId": "browser-test-run",
                "symbol": "BTCUSDT",
                "timeframe": "4h",
                "strategyTimeframe": "4h",
                "chartTimeframe": chart_timeframe or "4h",
            },
            "selectedTradeIndex": trade_index,
            "selectedTrade": {"Side": "LONG"},
            "fibDerivation": {
                "status": "AVAILABLE",
                "message": "",
                "reconstructedLegacy": False,
                "direction": "LONG",
                "impulseStartPrice": 90.0,
                "impulseEndPrice": 110.0,
                "impulseStartTime": 1_699_990_000,
                "impulseEndTime": 1_699_998_000,
                "entryTime": 1_700_000_000,
                "entryLevel": 0.5,
                "stopLevel": 0.618,
                "stopBoundaryPrice": 97.64,
                "actualStopPrice": 95.0,
                "targetR": 2.0,
                "targetPrice": 110.0,
                "availableRoomR": 2.5,
                "levels": [
                    {"level": 0.5, "price": 100.0, "selected": True, "stopBoundary": False},
                    {"level": 0.618, "price": 97.64, "selected": False, "stopBoundary": True},
                ],
            },
            "selectedTradeCandleTime": 1_700_000_000,
            "selectedTradeChartCandleTime": 1_700_000_000,
            "candles": [],
            "overlays": [],
            "srZones": [],
            "srEvents": [],
            "markers": [],
            "allTradeMarkers": [
                {"time": 1_700_000_000, "position": "belowBar", "shape": "arrowUp", "text": "#1 LONG", "kind": "all-trade-entry"},
                {"time": 1_700_003_600, "position": "aboveBar", "shape": "square", "text": "#1 EXIT", "kind": "all-trade-exit"},
            ],
            "priceLines": [],
            "positionBox": {
                "enabled": True,
                "side": "LONG",
                "entry": 100.0,
                "stop": 95.0,
                "target": 110.0,
                "entryTime": 1_700_000_000,
                "entryChartTime": 1_700_000_000,
                "exitTime": 1_700_003_600,
                "exitChartTime": 1_700_003_600,
                "exitPrice": 108.0,
                "exitReason": "TP",
                "open": False,
                "visibleEnd": 1_701_000_000,
            },
            "candleContext": {},
            "visibleStart": 1_699_000_000,
            "visibleEnd": 1_701_000_000,
            "fullRun": bool(full_run),
            "chartTimeframe": chart_timeframe or "4h",
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
    assert 'id="chart-tf"' in html
    assert 'id="toggle-inspector"' in html
    assert 'id="fullscreen"' in html
    assert 'id="reset-price"' in html
    assert 'id="view-mode"' in html
    assert 'id="sr-tf"' in html
    assert 'id="sr-snapshot"' in html
    assert 'id="nearest-only"' in html
    assert 'id="trade-mode"' in html
    assert 'id="chart-view"' in html
    assert "Full run" in html
    assert "Selected trade view" in html
    assert "No trades" in html
    assert "Selected trade" in html
    assert "All trades" in html
    assert 'id="show-position-box"' in html
    assert 'id="show-fib"' in html
    assert 'id="position-box-layer"' in html
    assert 'id="fib-layer"' in html
    assert ".fib-band" in html
    assert ".fib-level-label" in html
    assert "Pan/zoom freely" in html
    assert "Click a zone below to isolate it on the chart" in html
    assert "/session/test-token" in html
    assert "/api/payload" in html
    assert "/api/inspect" in html
    assert "handleScroll" in html
    assert "handleScale" in html
    assert "axisPressedMouseMove:{time:true,price:true}" in html
    assert "axisDoubleClickReset:{time:true,price:true}" in html
    assert "priceZoomFactor" in html
    assert "Math.max(.005,Math.min(50,priceZoomFactor * direction))" in html
    assert "pricePanOffset" in html
    assert "defaultPriceRange" in html
    assert "defaultPriceRangeKey" in html
    assert "computeDefaultPriceRange" in html
    assert "ensureDefaultPriceRange(false)" in html
    assert "Time pan/zoom keeps price size fixed" in html
    assert "Reset price restores default" in html
    assert "verticalPan" in html
    assert "Time pan/zoom keeps price size fixed" in html
    assert "vertical drag = price pan" in html
    assert "Math.abs(dyTotal) <= Math.abs(dx) * 1.15" in html
    assert "pricePanOffset += (dy / height) * 2.0 * priceZoomFactor" in html
    assert "const base = defaultPriceRange || info?.priceRange" in html
    assert "Time pan/zoom must never silently" in html
    assert "$('reset-price').addEventListener('click',resetPriceScale)" in html
    assert "overPriceScale" in html
    assert "event.clientX - rect.left >= rect.width - 86" in html
    assert "full_run" in html
    assert "full_run:'1'" in html
    assert 'id="window-size"' not in html
    assert "chart_timeframe" in html
    assert "current canonical cache" in html
    assert "drawPositionBox" in html
    assert ".position-box.reward" in html
    assert ".position-box.risk" in html
    assert "addRect('reward'" in html
    assert "addRect('risk'" in html
    assert "const minWidth = 104" in html
    assert "right = Math.max(right,left + minWidth)" in html
    assert "if (entryX < 0 || entryX > chartRight) return" in html
    assert "never clamp an off-screen entry" in html
    assert "OPEN " in html
    assert "CLOSE " in html
    assert "box.exitPrice" in html
    assert "Fib swing" in html
    assert "drawFibOverlay" in html
    assert "item.level.toFixed(3)" in html
    assert "ENTRY" in html
    assert "STOP" in html
    assert "SWING LOW" in html
    assert "SWING HIGH" in html
    assert "allTradeMarkers" in html
    assert "tradeMode.value === 'selected'" in html
    assert "tradeMode.value === 'all'" in html
    assert "Fib derivation" in html
    assert "centerSelectedTrade()" in html
    assert "const windowBars = 240" in html
    assert "entryIndex = candleIndexForTime(entryTime)" in html
    assert "chart.timeScale().setVisibleRange({from:firstTime,to:lastTime})" in html
    assert "Selected trade viewport is active" in html
    assert "selectedTradeViewStart" in html
    assert "selectedTradeViewEnd" in html
    assert "computeSelectedTradePriceRange" in html
    assert "defaultPriceRangeKey = payloadPriceRangeKey() + ':selected:' + currentTrade" in html
    assert "centerSelectedTrade(true)" in html
    assert "applyChartView" in html
    assert "chartView.value === 'selected'" in html
    assert "chartView.value = 'selected'" in html
    assert "tradeMode.value === 'selected'" in html
    assert "requestAnimationFrame(centerSelectedTrade)" in html
    assert "chartView.value = 'full'" in html
    assert "Chart view only changes the visible time range; the full run remains loaded." in html
    assert "resolveFibAnchorTimes" in html
    assert "rawStartTime !== null" in html
    assert "rawEndTime !== null" in html
    assert "fib.impulseBars" in html
    assert "candidateEnd - impulseBars" in html
    assert "DISPLAY " in html
    assert "nearestIndex" in html
    assert "candleIndexForTime" in html
    assert "logicalToCoordinate(index)" in html
    assert "const x1 = xForCandleTime(startTime)" in html
    assert "const rawX2 = xForCandleTime(endTime)" in html
    assert "createPriceLine" not in html
    assert BROWSER_DEFAULT_VISIBLE_CANDLES == 120


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
            + "api/payload?trade_index=1&chart_timeframe=1h&visible_candles=2000&show_rejections=1",
            timeout=5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["selectedTradeIndex"] == 1
        assert model.payload_calls[-1] == (1, 2000, True, False, "1h")

        with urlopen(
            url
            + "api/payload?trade_index=0&visible_candles=1000&full_run=1",
            timeout=5,
        ) as response:
            full_payload = json.loads(response.read().decode("utf-8"))
        assert full_payload["fullRun"] is True
        assert model.payload_calls[-1] == (0, 1000, False, True, None)

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
