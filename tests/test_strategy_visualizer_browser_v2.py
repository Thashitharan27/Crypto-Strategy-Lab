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
    assert 'id="fib-layer"' in html
    assert "function drawFibOverlay()" in html
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


def test_v2_trade_box_layer_stays_above_chart_canvas():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "#chart{position:absolute;inset:0;z-index:1}" in html
    assert "#trade-box-layer{position:absolute;inset:0;z-index:5" in html
    assert "const width=Math.max(48,right-left)" in html


def test_v2_trade_box_shows_opposite_boundary_without_floating_markers():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "OPEN/EXIT markers" not in html
    assert "createSeriesMarkers" not in html
    assert "trade['Exit Reason']" in html
    assert "exitedAtStop" in html
    assert "exitedAtTarget" in html
    assert "'TP '+String(trade.Target ?? trade.target ?? '')" in html
    assert "'SL '+String(trade.Stop ?? trade.stop ?? '')" in html


def test_v2_fib_overlay_has_structure_only_no_trade_specific_fib_labels():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "resolveFibAnchorTimes" in html
    assert "fib.levels" in html
    assert "fib.impulseStartPrice" in html
    assert "fib.impulseEndPrice" in html
    assert "item.selected ? '  ENTRY'" not in html
    assert "item.stopBoundary ? '  STOP'" not in html
    assert "TP" in html  # trade box remains responsible for TP/SL labels


def test_v2_supports_price_zoom_and_vertical_pan():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert 'id="reset-price"' in html
    assert "priceZoomFactor" in html
    assert "pricePanOffset" in html
    assert "autoscaleInfoProvider" in html
    assert "chartWrap.addEventListener('wheel'" in html
    assert "chartWrap.addEventListener('pointerdown'" in html
    assert "chartWrap.addEventListener('pointermove'" in html
    assert "Math.abs(dyTotal) <= Math.abs(dx)*1.15" in html
    assert "axisPressedMouseMove:{time:true,price:true}" in html


def test_v2_fib_levels_remain_drawable_when_swing_anchor_is_offscreen():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    # Pivot timestamp lookup can return null if the original impulse lies
    # outside the selected candle window. Clip horizontal levels to the plot.
    assert "const axisX=(time, edge) =>" in html
    assert "const x1=axisX(startTime,0);" in html
    assert "const x2=axisX(endTime,plotRight);" in html
    assert "const entryTime=Number(payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime || fib.entryTime);" in html
    assert "const rawStartX=chart.timeScale().timeToCoordinate(startTime);" in html
    assert "if ([x1,x2].some(v => v == null" not in html


def test_v2_renders_trading_ema_overlays_with_toggle():
    html = build_browser_visualizer_v2_html(_Model(), "abc")
    assert 'id="fib-emas"' in html
    assert "overlay.period" in html
    assert "[320,1600]" in html
    assert "series.setData(overlay.data || [])" in html
    assert "window.LightweightCharts.LineSeries" in html


def test_v2_ema_toggle_preserves_chart_viewport():
    html = build_browser_visualizer_v2_html(_Model(), "abc")
    assert "const visibleRange = chart.timeScale().getVisibleRange();" in html
    assert "if (visibleRange) chart.timeScale().setVisibleRange(visibleRange);" in html


def test_v2_trend_ema_overlays_do_not_override_price_zoom_and_pan():
    html = build_browser_visualizer_v2_html(_Model(), "abc")
    assert "autoscaleInfoProvider: () => null" in html
    assert "priceZoomFactor=Math.max(.005,Math.min(50" in html
    assert "pricePanOffset=Math.max(-8,Math.min(8" in html


def test_v2_rsi_lower_pane_uses_native_payload_and_preserves_viewport():
    html=build_browser_visualizer_v2_html(_Model(),"abc")
    assert 'id="show-rsi"' in html
    assert "o.kind === 'rsi' && Number(o.period) === 14" in html
    assert "rsiSeries = chart.addSeries(window.LightweightCharts.LineSeries" in html
    assert "chart.panes()[1].setHeight(155)" in html
    assert "for (const level of [30,70])" in html
    assert "if (visibleRange) chart.timeScale().setVisibleRange(visibleRange)" in html
