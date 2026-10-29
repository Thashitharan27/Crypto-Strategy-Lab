"""Standalone feed boundaries and renderer integration contracts."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from crypto_strategy_lab import photon_live as live


def row(t, close_time=None):
    return [t * 1000, "100", "103", "99", "102", "1",
            (t + 60) * 1000 - 1 if close_time is None else close_time]


def test_history_pages_and_never_maps_an_unfinished_candle(monkeypatch):
    calls = []
    def request(path, **params):
        calls.append(params)
        if len(calls) == 1:
            return [row(i * 60) for i in range(1000)]
        return [row(60000), row(60060, close_time=999999999)]
    monkeypatch.setattr(live, "public_json", request)
    bars = live.history("BTCUSDT", "1m", 0, 60120)
    assert len(bars) == 1001
    assert bars[-1] == dict(time=60000, open=100., high=103., low=99., close=102.)
    assert calls[1]["startTime"] == 60000000


def test_history_refuses_nonadvancing_feed(monkeypatch):
    monkeypatch.setattr(live, "public_json", lambda *a, **kw: [row(0)] * 1000)
    with pytest.raises(ValueError, match="did not advance"):
        live.history("BTCUSDT", "1m", 60, 120)


@pytest.mark.parametrize("symbol", ["../BTC", "BTCUSDT<script>", "", "X" * 25])
def test_symbol_validation(symbol):
    with pytest.raises(ValueError):
        live.LiveMarket(symbol)


def test_payload_reuses_closed_mapping_and_adds_minute_lazily(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path)
    now = 900 * 1000 + 61
    monkeypatch.setattr(live, "public_json", lambda *a, **kw: {"serverTime": now * 1000})
    calls = []
    def history(symbol, tf, start, end):
        calls.append((tf, end))
        seconds = live.INTERVALS[tf]
        return [dict(time=end-seconds*3+i*seconds, open=100+i, high=103+i, low=99+i, close=102+i) for i in range(3)]
    monkeypatch.setattr(live, "history", history)
    market = live.LiveMarket("BTCUSDT")
    market.start = 0
    first = market.payload("15m")
    second = market.payload("15m")
    assert first["photonMapping"] is second["photonMapping"]
    assert [x[0] for x in calls] == ["15m", "1d"]
    assert "1m" not in first["photonMapping"]["timeframes"]
    minute = market.payload("1m")
    assert "1m" in minute["photonMapping"]["timeframes"]
    assert "1m" not in first["photonMapping"]["timeframes"]
    for guide in minute["photonMapping"]["timeframes"].values():
        assert all(state["availableAt"] <= now for state in guide["snapshots"])


def test_browser_is_desktop_independent_and_script_parses(tmp_path):
    result = subprocess.run([sys.executable, "-c",
        "from crypto_strategy_lab.photon_live import browser_html;import sys;"
        "browser_html('BTCUSDT','token');assert not any(k.startswith('PySide6') for k in sys.modules)"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    html = live.browser_html("BTCUSDT", "token")
    script = re.findall(r"<script>([\s\S]*?)</script>", html)[-1]
    path = tmp_path / "workspace.js"
    path.write_text(script, encoding="utf-8")
    node = shutil.which("node")
    if node:
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert "wss://fstream.binance.com/market/ws/" in script
    assert "if(replayActive){status.textContent=" in script
    assert "q.set('symbol',boot.run.symbol)" in script
