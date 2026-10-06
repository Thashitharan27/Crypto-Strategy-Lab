from __future__ import annotations

from types import SimpleNamespace

from crypto_strategy_lab.strategy_visualizer_browser_v2 import (
    build_browser_visualizer_v2_html,
)


class _Model:
    trade_count = 2
    run_dir = SimpleNamespace(name="demo-run")
    manifest = {"run_id":"demo-run"}
    seed = SimpleNamespace(
        request=SimpleNamespace(
            symbol="BTCUSDT",
            strategy_timeframe="15m",
        )
    )

    def trade_label(self, index: int) -> str:
        return f"{index + 1}/2 · trade"


def test_v2_html_is_minimal_and_diagnostic():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "Strategy Visualizer V2 · Diagnostic" in html
    assert "FULL RUN CANDLES:" in html
    assert "persisted entry time:" in html
    assert "entry candle index:" in html
    assert "entry candle time:" in html
    assert "OPEN marker time:" in html
    assert "EXIT marker time:" in html
    assert "selected view bounds:" in html
    assert "lines.join('\\n')" in html
    assert "lines.join('\n')" not in html
    assert "setVisibleRange({from:start,to:end})" in html
    assert "Fib" not in html
    assert "EMA 20" not in html
    assert "S/R" not in html


def test_v2_server_uses_minimal_payload_path():
    from crypto_strategy_lab import strategy_visualizer_browser_v2

    source = __import__("inspect").getsource(strategy_visualizer_browser_v2)
    assert "build_v2_diagnostic_payload" in source
    assert "build_payload(" not in source


def test_v2_html_includes_trade_box_and_correct_summary_keys():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert 'id="trade-box-layer"' in html
    assert "function drawTradeBox()" in html
    assert "timeToCoordinate(Number(open.time))" in html
    assert "trade.Entry ?? trade.entry" in html
    assert "trade['Entry Time'] || trade.entryTime" in html
