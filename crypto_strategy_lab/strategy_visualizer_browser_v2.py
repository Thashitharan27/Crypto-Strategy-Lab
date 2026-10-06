"""Minimal browser Strategy Visualizer V2 used to verify candle/trade alignment.

V2 intentionally starts with only the pieces needed to prove the chart coordinate
pipeline: full-run candles, completed-trade selection, OPEN/EXIT markers, and a
small diagnostic readout.  The legacy browser visualizer remains untouched.
"""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

from crypto_strategy_lab.strategy_visualizer import (
    CompletedRunVisualizer,
    LIGHTWEIGHT_CHARTS_URL,
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def build_browser_visualizer_v2_html(
    model: CompletedRunVisualizer,
    session_token: str,
) -> str:
    request = model.seed.request
    bootstrap = {
        "sessionBase": f"/session/{session_token}",
        "trades": [
            {"index": index, "label": model.trade_label(index)}
            for index in range(model.trade_count)
        ],
        "run": {
            "runId": str(model.manifest.get("run_id") or model.run_dir.name),
            "symbol": request.symbol,
            "timeframe": request.strategy_timeframe,
            "tradeCount": model.trade_count,
        },
    }
    encoded = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    template = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Visualizer V2 · Diagnostic</title>
<style>
html,body{height:100%;margin:0;background:#0b121a;color:#e6edf3;font-family:Segoe UI,Arial,sans-serif}
#app{height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr)}
#toolbar{display:flex;gap:8px;align-items:center;padding:8px;background:#101923;border-bottom:1px solid #2b3948}
button,select{background:#172330;color:#e6edf3;border:1px solid #3a4a5c;border-radius:5px;padding:5px 8px}
#trade{min-width:460px;max-width:62vw}
#diag{font:12px/1.45 Consolas,monospace;padding:7px 10px;background:#0f1720;border-bottom:1px solid #2b3948;white-space:pre-wrap}
#chart{min-height:0}
.bad{color:#f08a8a}.good{color:#6fd3a4}.muted{color:#91a0b2}
</style>
<script src="__LIGHTWEIGHT_CHARTS_URL__"></script>
</head>
<body>
<div id="app">
  <div id="toolbar">
    <strong>Strategy Visualizer V2 · Diagnostic</strong>
    <select id="trade"></select>
    <button id="center">Center selected</button>
    <button id="fit">Fit full run</button>
    <label><input id="markers" type="checkbox" checked> OPEN/EXIT markers</label>
  </div>
  <div id="diag">Loading…</div>
  <div id="chart"></div>
</div>
<script>
(() => {
  const boot = __BOOTSTRAP__;
  const $ = id => document.getElementById(id);
  const tradeSelect = $('trade');
  const diag = $('diag');
  const showMarkers = $('markers');
  let payload = null;
  let currentTrade = 0;
  let chart = null;
  let candles = null;
  let markerApi = null;

  for (const item of boot.trades) {
    const option = document.createElement('option');
    option.value = String(item.index);
    option.textContent = item.label;
    tradeSelect.appendChild(option);
  }

  function api(path, params={}) {
    const q = new URLSearchParams(params);
    return boot.sessionBase + path + (q.size ? '?' + q.toString() : '');
  }

  async function getJson(url) {
    const r = await fetch(url,{cache:'no-store'});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
    return data;
  }

  function nearestIndex(time) {
    const items = payload?.candles || [];
    if (!items.length || time == null) return null;
    const target = Number(time);
    let lo=0, hi=items.length-1;
    while (lo < hi) {
      const mid = Math.floor((lo+hi)/2);
      if (Number(items[mid].time) < target) lo = mid+1;
      else hi = mid;
    }
    if (lo > 0) {
      const a=Math.abs(Number(items[lo-1].time)-target);
      const b=Math.abs(Number(items[lo].time)-target);
      if (a <= b) return lo-1;
    }
    return lo;
  }

  function fmtTime(time) {
    if (time == null) return 'n/a';
    return new Date(Number(time)*1000).toISOString().replace('.000Z','Z');
  }

  function selectedMarkers() {
    if (!showMarkers.checked || !payload) return [];
    const allowed = new Set(['selected-open','exit']);
    return (payload.markers || []).filter(m => allowed.has(String(m.kind || '')));
  }

  function applyMarkers() {
    if (!candles || !window.LightweightCharts?.createSeriesMarkers) return;
    const source = selectedMarkers().map(m => ({
      time:Number(m.time),
      position:m.position,
      shape:m.shape,
      text:m.text,
      color:String(m.kind)==='selected-open' ? '#6fd3a4' : '#ffd166',
    }));
    markerApi = window.LightweightCharts.createSeriesMarkers(candles, source);
  }

  function renderDiagnostics() {
    if (!payload) return;
    const trade = payload.selectedTrade || {};
    const openMarker = (payload.markers || []).find(m => String(m.kind)==='selected-open');
    const exitMarker = (payload.markers || []).find(m => String(m.kind)==='exit');
    const entryTime = Number(payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime);
    const entryIndex = nearestIndex(entryTime);
    const entryCandle = entryIndex == null ? null : payload.candles[entryIndex];
    const exitIndex = exitMarker ? nearestIndex(Number(exitMarker.time)) : null;
    const exitCandle = exitIndex == null ? null : payload.candles[exitIndex];
    const priceDelta = entryCandle && Number.isFinite(Number(trade.entry))
      ? Math.abs(Number(entryCandle.close)-Number(trade.entry))
      : null;
    const lines = [
      'FULL RUN CANDLES: ' + (payload.candles || []).length,
      'TRADE: #' + (Number(payload.selectedTradeIndex)+1) + ' ' + String(trade.side || ''),
      'persisted entry time: ' + String(trade.entryTime || 'n/a'),
      'chart entry time:     ' + fmtTime(entryTime),
      'entry candle index:   ' + String(entryIndex),
      'entry candle time:    ' + fmtTime(entryCandle?.time),
      'entry candle OHLC:    ' + (entryCandle ? [entryCandle.open,entryCandle.high,entryCandle.low,entryCandle.close].join(' / ') : 'n/a'),
      'persisted entry price:' + String(trade.entry ?? 'n/a'),
      'entry close delta:    ' + (priceDelta == null ? 'n/a' : priceDelta.toFixed(6)),
      'OPEN marker time:     ' + fmtTime(openMarker?.time),
      'EXIT marker time:     ' + fmtTime(exitMarker?.time),
      'exit candle index:    ' + String(exitIndex),
      'exit candle time:     ' + fmtTime(exitCandle?.time),
      'selected view bounds: ' + fmtTime(payload.selectedTradeViewStart) + ' -> ' + fmtTime(payload.selectedTradeViewEnd),
    ];
    diag.textContent = lines.join('\\n');
  }

  function buildChart() {
    if (chart) chart.remove();
    chart = window.LightweightCharts.createChart($('chart'),{
      autoSize:true,
      layout:{background:{type:'solid',color:'#0f1720'},textColor:'#b8c2cc'},
      grid:{vertLines:{color:'#1d2937'},horzLines:{color:'#1d2937'}},
      rightPriceScale:{borderColor:'#334155',autoScale:true},
      timeScale:{borderColor:'#334155',timeVisible:true,secondsVisible:false,rightOffset:8},
    });
    candles = chart.addSeries(window.LightweightCharts.CandlestickSeries,{
      upColor:'#22a06b',downColor:'#d84a4a',borderVisible:false,
      wickUpColor:'#22a06b',wickDownColor:'#d84a4a',
    });
    candles.setData(payload.candles || []);
    applyMarkers();
  }

  function centerSelected() {
    if (!payload || !chart) return;
    const start = Number(payload.selectedTradeViewStart);
    const end = Number(payload.selectedTradeViewEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    chart.timeScale().setVisibleRange({from:start,to:end});
    chart.priceScale('right').applyOptions({autoScale:true});
  }

  async function load() {
    diag.textContent = 'Loading…';
    try {
      payload = await getJson(api('/api/payload',{
        trade_index:String(currentTrade),
        chart_timeframe:boot.run.timeframe,
        full_run:'1',
      }));
      buildChart();
      renderDiagnostics();
      requestAnimationFrame(centerSelected);
    } catch (error) {
      diag.textContent = 'ERROR: ' + error.message;
    }
  }

  tradeSelect.addEventListener('change',() => {
    currentTrade = Number(tradeSelect.value);
    load();
  });
  $('center').addEventListener('click',centerSelected);
  $('fit').addEventListener('click',() => chart?.timeScale().fitContent());
  showMarkers.addEventListener('change',() => {
    buildChart();
    renderDiagnostics();
    requestAnimationFrame(centerSelected);
  });

  if (!window.LightweightCharts) {
    diag.textContent = 'ERROR: Lightweight Charts failed to load.';
    return;
  }
  load();
})();
</script>
</body>
</html>"""
    return template.replace("__LIGHTWEIGHT_CHARTS_URL__", LIGHTWEIGHT_CHARTS_URL).replace("__BOOTSTRAP__", encoded)


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StrategyVisualizerV2BrowserServer:
    """Serve the isolated V2 diagnostic browser on loopback only."""

    def __init__(self, model: CompletedRunVisualizer):
        self.model = model
        self.token = secrets.token_urlsafe(18)
        self._lock = Lock()
        self._server: _LoopbackHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("V2 browser visualizer server is not running")
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}/session/{self.token}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CryptoStrategyLabVisualizerV2/1.0"

            def log_message(self, _format, *_args):
                return

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
                self._send(int(status), _json_bytes(value), "application/json; charset=utf-8")

            def do_GET(self):
                try:
                    parsed = urlsplit(self.path)
                    prefix = f"/session/{owner.token}"
                    if parsed.path in {prefix, prefix + "/", prefix + "/index.html"}:
                        self._send(
                            HTTPStatus.OK,
                            build_browser_visualizer_v2_html(owner.model, owner.token).encode("utf-8"),
                            "text/html; charset=utf-8",
                        )
                        return
                    if parsed.path != prefix + "/api/payload":
                        self._json({"error":"not found"}, HTTPStatus.NOT_FOUND)
                        return
                    query = parse_qs(parsed.query)
                    trade_raw = (query.get("trade_index") or ["0"])[0]
                    trade_index = int(trade_raw) if trade_raw else 0
                    chart_timeframe = (query.get("chart_timeframe") or [""])[0].strip() or None
                    with owner._lock:
                        result = owner.model.build_v2_diagnostic_payload(
                            trade_index=trade_index,
                            chart_timeframe=chart_timeframe,
                        )
                    self._json(result)
                except (TypeError, ValueError) as exc:
                    self._json({"error":str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # pragma: no cover
                    self._json({"error":str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        self._server = _LoopbackHTTPServer(("127.0.0.1",0),Handler)
        self._thread = Thread(target=self._server.serve_forever,name="strategy-visualizer-v2-browser",daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        server=self._server
        thread=self._thread
        self._server=None
        self._thread=None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


__all__=[
    "StrategyVisualizerV2BrowserServer",
    "build_browser_visualizer_v2_html",
]
