"""Minimal browser Strategy Visualizer V2 used to verify candle/trade alignment.

V2 intentionally starts with only the pieces needed to prove the chart coordinate
pipeline: full-run candles, completed-trade selection, trade-box geometry, and a
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
#chart-wrap{position:relative;min-height:0}
#chart{position:absolute;inset:0;z-index:1}
#fib-layer{position:absolute;inset:0;z-index:3;pointer-events:none;overflow:hidden}
#trade-box-layer{position:absolute;inset:0;z-index:5;pointer-events:none;overflow:hidden}
.fib-band{position:absolute;box-sizing:border-box;border-top:1px solid rgba(255,255,255,.18)}
.fib-level-label{position:absolute;transform:translateY(-50%);padding:2px 5px;border-radius:3px;font:10px/1.2 Segoe UI,Arial,sans-serif;font-weight:700;white-space:nowrap;color:#f8fafc;background:rgba(15,23,32,.90);border:1px solid rgba(148,163,184,.44);box-shadow:0 1px 3px rgba(0,0,0,.32)}
.fib-anchor{position:absolute;height:1px;transform-origin:0 50%;background:rgba(148,163,184,.65)}
.trade-rect{position:absolute;box-sizing:border-box;border-radius:2px}
.trade-rect.risk{background:rgba(219,68,68,.22);border:1px solid rgba(255,105,105,.9)}
.trade-rect.reward{background:rgba(38,166,91,.23);border:1px solid rgba(83,220,141,.9)}
.trade-label{position:absolute;padding:2px 5px;border-radius:3px;font:11px/1.2 Segoe UI,Arial,sans-serif;white-space:nowrap}
.trade-label.entry{background:rgba(43,108,176,.96);color:#fff}
.trade-label.exit{background:rgba(184,132,50,.96);color:#fff}
.trade-label.tp{background:rgba(32,139,85,.96);color:#fff}
.trade-label.sl{background:rgba(184,58,58,.96);color:#fff}
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
  </div>
  <div id="diag">Loading…</div>
  <div id="chart-wrap">
    <div id="chart"></div>
    <div id="fib-layer"></div>
    <div id="trade-box-layer"></div>
  </div>
</div>
<script>
(() => {
  const boot = __BOOTSTRAP__;
  const $ = id => document.getElementById(id);
  const tradeSelect = $('trade');
  const diag = $('diag');
  const fibLayer = $('fib-layer');
  const tradeBoxLayer = $('trade-box-layer');
  let payload = null;
  let currentTrade = 0;
  let chart = null;
  let candles = null;

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
      'persisted entry time: ' + String(trade['Entry Time'] || trade.entryTime || 'n/a'),
      'chart entry time:     ' + fmtTime(entryTime),
      'entry candle index:   ' + String(entryIndex),
      'entry candle time:    ' + fmtTime(entryCandle?.time),
      'entry candle OHLC:    ' + (entryCandle ? [entryCandle.open,entryCandle.high,entryCandle.low,entryCandle.close].join(' / ') : 'n/a'),
      'persisted entry price:' + String(trade.Entry ?? trade.entry ?? 'n/a'),
      'entry close delta:    ' + (priceDelta == null ? 'n/a' : priceDelta.toFixed(6)),
      'OPEN marker time:     ' + fmtTime(openMarker?.time),
      'EXIT marker time:     ' + fmtTime(exitMarker?.time),
      'exit candle index:    ' + String(exitIndex),
      'exit candle time:     ' + fmtTime(exitCandle?.time),
      'selected view bounds: ' + fmtTime(payload.selectedTradeViewStart) + ' -> ' + fmtTime(payload.selectedTradeViewEnd),
      'Fib: ' + String(payload.fibDerivation?.status || 'NOT_AVAILABLE'),
    ];
    diag.textContent = lines.join('\\n');
  }

  function addTradeLabel(x,y,className,text) {
    if (![x,y].every(v => v != null && Number.isFinite(Number(v)))) return;
    const label=document.createElement('div');
    label.className='trade-label '+className;
    label.style.left=Math.max(2,Number(x))+'px';
    label.style.top=Math.max(2,Number(y)-10)+'px';
    label.textContent=text;
    tradeBoxLayer.appendChild(label);
  }

  function resolveFibAnchorTimes(fib, items, entryTime) {
    const rawStart=Number(fib.impulseStartTime);
    const rawEnd=Number(fib.impulseEndTime);
    if (Number.isFinite(rawStart) && rawStart > 0 && Number.isFinite(rawEnd) && rawEnd > 0)
      return {startTime:rawStart,endTime:rawEnd};

    const startPrice=Number(fib.impulseStartPrice);
    const endPrice=Number(fib.impulseEndPrice);
    if (!Number.isFinite(startPrice) || !Number.isFinite(endPrice) || !items.length)
      return {startTime:entryTime,endTime:entryTime};

    let entryIndex=items.findIndex(item => Number(item.time) >= Number(entryTime));
    if (entryIndex < 0) entryIndex=items.length;
    const first=Math.max(0,entryIndex-320);
    const last=Math.max(first+1,entryIndex);
    const longSide=String(fib.direction || '').toUpperCase()==='LONG';
    const startField=longSide ? 'low' : 'high';
    const endField=longSide ? 'high' : 'low';

    let startIndex=-1, endIndex=-1;
    const impulseBars=Math.round(Number(fib.impulseBars));
    if (Number.isFinite(impulseBars) && impulseBars > 0) {
      let best=Infinity;
      for (let candidateEnd=first+impulseBars; candidateEnd<last; candidateEnd++) {
        const candidateStart=candidateEnd-impulseBars;
        const observedStart=Number(items[candidateStart]?.[startField]);
        const observedEnd=Number(items[candidateEnd]?.[endField]);
        if (!Number.isFinite(observedStart) || !Number.isFinite(observedEnd)) continue;
        const score=Math.abs(observedStart-startPrice)/Math.max(1,Math.abs(startPrice))+
          Math.abs(observedEnd-endPrice)/Math.max(1,Math.abs(endPrice));
        if (score < best) { best=score; startIndex=candidateStart; endIndex=candidateEnd; }
      }
    }

    function nearest(from,to,field,price) {
      let bestIndex=-1, bestDistance=Infinity;
      for (let i=from;i<to;i++) {
        const value=Number(items[i]?.[field]);
        if (!Number.isFinite(value)) continue;
        const distance=Math.abs(value-price);
        if (distance < bestDistance) { bestDistance=distance; bestIndex=i; }
      }
      return bestIndex;
    }

    if (endIndex < 0) endIndex=nearest(first,last,endField,endPrice);
    if (endIndex < 0) endIndex=Math.max(first,last-1);
    if (startIndex < 0) startIndex=nearest(first,Math.max(first+1,endIndex),startField,startPrice);
    if (startIndex < 0 || startIndex >= endIndex) startIndex=Math.max(first,endIndex-1);
    return {
      startTime:Number(items[startIndex]?.time || entryTime),
      endTime:Number(items[endIndex]?.time || entryTime),
    };
  }

  function drawFibOverlay() {
    fibLayer.replaceChildren();
    if (!payload || !chart || !candles) return;
    const fib=payload.fibDerivation || {};
    if (fib.status !== 'AVAILABLE') return;

    const items=payload.candles || [];
    const entryTime=Number(fib.entryTime || payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime);
    const anchors=resolveFibAnchorTimes(fib,items,entryTime);
    const startTime=Number(anchors.startTime);
    const endTime=Number.isFinite(entryTime) ? entryTime : Number(anchors.endTime);
    const x1=chart.timeScale().timeToCoordinate(startTime);
    const x2=chart.timeScale().timeToCoordinate(endTime);
    if ([x1,x2].some(v => v == null || !Number.isFinite(Number(v)))) return;

    const left=Math.max(0,Math.min(Number(x1),Number(x2)));
    const right=Math.min($('chart-wrap').clientWidth-76,Math.max(Number(x1),Number(x2)));
    if (right <= left) return;

    const ordered=(fib.levels || [])
      .map(item => ({level:Number(item.level),price:Number(item.price)}))
      .filter(item => Number.isFinite(item.level) && Number.isFinite(item.price))
      .sort((a,b) => a.price-b.price);
    if (ordered.length < 2) return;

    const palette=[
      'rgba(133,77,255,.09)','rgba(46,160,255,.10)','rgba(0,196,140,.10)',
      'rgba(82,196,92,.10)','rgba(230,168,33,.11)','rgba(222,76,76,.10)'
    ];

    for (let i=0;i<ordered.length-1;i++) {
      const aY=candles.priceToCoordinate(ordered[i].price);
      const bY=candles.priceToCoordinate(ordered[i+1].price);
      if ([aY,bY].some(v => v == null || !Number.isFinite(Number(v)))) continue;
      const band=document.createElement('div');
      band.className='fib-band';
      band.style.left=left+'px';
      band.style.width=Math.max(2,right-left)+'px';
      band.style.top=Math.min(Number(aY),Number(bY))+'px';
      band.style.height=Math.max(1,Math.abs(Number(bY)-Number(aY)))+'px';
      band.style.background=palette[i % palette.length];
      fibLayer.appendChild(band);
    }

    for (const item of ordered) {
      const y=candles.priceToCoordinate(item.price);
      if (y == null || !Number.isFinite(Number(y))) continue;
      const label=document.createElement('div');
      label.className='fib-level-label';
      label.style.left=Math.max(4,left+6)+'px';
      label.style.top=Number(y)+'px';
      label.textContent=item.level.toFixed(3).replace(/0+$/,'').replace(/[.]$/,'')+
        '  ('+item.price.toFixed(2)+')';
      fibLayer.appendChild(label);
    }

    const startY=candles.priceToCoordinate(Number(fib.impulseStartPrice));
    const endY=candles.priceToCoordinate(Number(fib.impulseEndPrice));
    const anchorEndX=chart.timeScale().timeToCoordinate(Number(anchors.endTime));
    if ([x1,anchorEndX,startY,endY].every(v => v != null && Number.isFinite(Number(v)))) {
      const dx=Number(anchorEndX)-Number(x1), dy=Number(endY)-Number(startY);
      const anchor=document.createElement('div');
      anchor.className='fib-anchor';
      anchor.style.left=Number(x1)+'px';
      anchor.style.top=Number(startY)+'px';
      anchor.style.width=Math.hypot(dx,dy)+'px';
      anchor.style.transform='rotate('+Math.atan2(dy,dx)+'rad)';
      fibLayer.appendChild(anchor);
    }
  }

  function drawTradeBox() {
    tradeBoxLayer.replaceChildren();
    if (!payload || !chart || !candles) return;
    const trade=payload.selectedTrade || {};
    const markers=payload.markers || [];
    const open=markers.find(m => String(m.kind)==='selected-open');
    const exit=markers.find(m => String(m.kind)==='exit');
    if (!open) return;

    const entry=Number(trade.Entry ?? trade.entry);
    const stop=Number(trade.Stop ?? trade.stop);
    const target=Number(trade.Target ?? trade.target);
    const exitPrice=Number(trade.Exit ?? trade.exit);
    const x1=chart.timeScale().timeToCoordinate(Number(open.time));
    const endTime=exit ? Number(exit.time) : Number(payload.selectedTradeViewEnd);
    const x2=chart.timeScale().timeToCoordinate(endTime);
    const entryY=candles.priceToCoordinate(entry);
    const stopY=candles.priceToCoordinate(stop);
    const targetY=candles.priceToCoordinate(target);
    const exitY=candles.priceToCoordinate(exitPrice);
    if ([x1,x2,entryY].some(v => v == null || !Number.isFinite(Number(v)))) return;

    const left=Math.min(Number(x1),Number(x2));
    const right=Math.max(Number(x1),Number(x2));
    const width=Math.max(48,right-left);

    function rect(a,b,className){
      if ([a,b].some(v => v == null || !Number.isFinite(Number(v)))) return;
      const el=document.createElement('div');
      el.className='trade-rect '+className;
      el.style.left=left+'px';
      el.style.width=width+'px';
      el.style.top=Math.min(Number(a),Number(b))+'px';
      el.style.height=Math.max(2,Math.abs(Number(b)-Number(a)))+'px';
      tradeBoxLayer.appendChild(el);
    }
    rect(entryY,stopY,'risk');
    rect(entryY,targetY,'reward');
    addTradeLabel(left+4,entryY,'entry','OPEN '+String(trade.Entry ?? trade.entry ?? ''));
    if (exit && Number.isFinite(exitPrice))
      addTradeLabel(Math.max(left+4,right-90),exitY,'exit','EXIT '+String(trade.Exit ?? trade.exit ?? ''));

    const exitReason=String(trade['Exit Reason'] ?? trade.exitReason ?? '').trim().toUpperCase();
    const exitedAtStop=exitReason === 'SL' || exitReason.includes('STOP');
    const exitedAtTarget=exitReason === 'TP' || exitReason.includes('TAKE') || exitReason.includes('TARGET');
    const boundaryX=right+6;
    if (exitedAtStop) {
      if (Number.isFinite(target))
        addTradeLabel(boundaryX,targetY,'tp','TP '+String(trade.Target ?? trade.target ?? ''));
    } else if (exitedAtTarget) {
      if (Number.isFinite(stop))
        addTradeLabel(boundaryX,stopY,'sl','SL '+String(trade.Stop ?? trade.stop ?? ''));
    } else {
      if (Number.isFinite(target))
        addTradeLabel(boundaryX,targetY,'tp','TP '+String(trade.Target ?? trade.target ?? ''));
      if (Number.isFinite(stop))
        addTradeLabel(boundaryX,stopY,'sl','SL '+String(trade.Stop ?? trade.stop ?? ''));
    }
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
    const redraw=() => { drawFibOverlay(); drawTradeBox(); };
    chart.timeScale().subscribeVisibleTimeRangeChange(redraw);
    if (window.ResizeObserver) new ResizeObserver(redraw).observe($('chart-wrap'));
    requestAnimationFrame(() => {
      redraw();
      setTimeout(redraw, 40);
    });
  }

  function centerSelected() {
    if (!payload || !chart) return;
    const start = Number(payload.selectedTradeViewStart);
    const end = Number(payload.selectedTradeViewEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    chart.timeScale().setVisibleRange({from:start,to:end});
    chart.priceScale('right').applyOptions({autoScale:true});
    requestAnimationFrame(() => {
      drawFibOverlay();
      drawTradeBox();
      setTimeout(() => { drawFibOverlay(); drawTradeBox(); }, 40);
    });
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
