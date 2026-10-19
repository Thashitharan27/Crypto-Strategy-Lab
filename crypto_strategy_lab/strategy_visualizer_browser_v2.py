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
from threading import Event, Lock, Thread
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
#app{height:100%;display:grid;grid-template-rows:auto auto auto minmax(0,1fr)}
#diagnostics{background:#0f1720;border-bottom:1px solid #2b3948}
#diagnostics summary{cursor:pointer;padding:5px 10px;font:12px Segoe UI,Arial,sans-serif;color:#b8c2cc}
#diagnostics:not([open]) #diag{display:none}
#toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px;background:#101923;border-bottom:1px solid #2b3948}
button,select{background:#172330;color:#e6edf3;border:1px solid #3a4a5c;border-radius:5px;padding:5px 8px}
#trade{width:380px;min-width:140px;max-width:55vw}
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
.ema-menu{position:relative;font:12px Segoe UI,Arial,sans-serif}
.ema-menu>summary{cursor:pointer;list-style:none;border:1px solid #475569;border-radius:4px;padding:4px 9px;white-space:nowrap}
.ema-menu>summary::-webkit-details-marker{display:none}
.ema-options{position:absolute;z-index:30;top:calc(100% + 5px);left:0;display:flex;flex-direction:column;gap:7px;min-width:110px;padding:11px;background:#17232f;border:1px solid #475569;border-radius:6px;box-shadow:0 6px 18px #0009}
.ema-options label{display:block;white-space:nowrap;cursor:pointer}
.bad{color:#f08a8a}.good{color:#6fd3a4}.muted{color:#91a0b2}
*{box-sizing:border-box}
body{font-size:14px}
button,select,input{font:inherit}
button,select{min-height:34px;padding:6px 11px;cursor:pointer}
button:hover{background:#25364b;border-color:#6884aa}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #60a5fa;outline-offset:2px}
#toolbar{gap:10px;padding:10px 16px;background:#131c2b}
.brand{font-size:15px;letter-spacing:.2px;white-space:nowrap}
.brand small{font-size:11px;color:#91a0b2;margin-left:6px}
.symbol{font-weight:700;color:#f0f6ff;border-left:1px solid #344155;padding-left:16px}
#indicators-btn{background:#2962ff;border-color:#477aff;font-weight:600;min-width:140px}
.toolbar-spacer{flex:1}
#reviewbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:8px 16px;border-bottom:1px solid #2b3948;background:#101722}
#timeframe-note{font-size:12px}
#active-indicators{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.indicator-chip{font-size:12px;padding:3px 8px;min-height:26px;border-radius:14px;background:#182940;border-color:#334c6d}
#diagnostics summary{padding:7px 16px}
dialog{width:min(660px,calc(100vw - 32px));max-height:85vh;padding:0;border:1px solid #3b4d66;border-radius:12px;background:#131d2b;color:#e6edf3;box-shadow:0 24px 90px #000b}
dialog::backdrop{background:#020617a8}
.dialog-header{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid #2b3948}
.dialog-header h2{font-size:20px;margin:0}
.dialog-body{padding:18px 22px;overflow:auto;max-height:calc(85vh - 78px)}
#indicator-search{width:100%;padding:11px 12px;border:1px solid #475569;border-radius:6px;background:#0c1420;color:#e6edf3;margin:14px 0}
.indicator-heading{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#93a9c6;margin:16px 0 7px}
#ema-menu>summary{display:block}
#ema-menu .ema-options{position:static;display:grid;grid-template-columns:1fr 1fr;gap:6px;box-shadow:none;background:none;border:0;padding:0}
.indicator-option,.ema-options label{display:flex;align-items:center;gap:9px;padding:10px;border-radius:6px;background:#192638;font-size:14px;cursor:pointer}
input[type=checkbox]{accent-color:#3976ff;width:16px;height:16px;flex-shrink:0}
.indicator-option[hidden],.ema-options label[hidden]{display:none!important}
.panel-settings{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-top:1px solid #344155;margin-top:18px;padding-top:14px}
@media(max-width:700px){.toolbar-spacer{display:none}.brand small{display:none}#trade{max-width:100%;width:100%}#reviewbar>label{width:100%}#ema-menu .ema-options{grid-template-columns:1fr}}
.indicator-group{padding:16px;margin:12px 0;border:1px solid #344155;border-radius:8px;background:#172334}
.indicator-group h3{margin:0 0 6px;font-size:16px}
.indicator-group p{font-size:12px;color:#93a9c6;margin:0 0 12px}
.period-picker>summary{cursor:pointer;padding:10px;border:1px solid #475569;border-radius:6px;background:#0c1420;list-style:none;font-size:14px}
.period-picker[open]>summary{margin-bottom:8px}
.period-picker .ema-options,.period-options{display:flex!important;flex-wrap:wrap;gap:6px}
.period-options label,.ema-options label{padding:8px 10px;min-width:66px;justify-content:center}
.rsi-method{font-size:12px;color:#b8c2cc;margin:12px 0 6px}
.indicator-group[hidden]{display:none}
</style>
<script src="__LIGHTWEIGHT_CHARTS_URL__"></script>
</head>
<body>
<div id="app">
  <div id="toolbar">
    <strong class="brand">CSL <small>Strategy Visualizer V2 · Diagnostic</small></strong>
    <span id="chart-symbol" class="symbol"></span>
    <label for="chart-timeframe">Chart timeframe</label>
    <select id="chart-timeframe" aria-label="Chart timeframe"></select>
    <button id="indicators-btn" aria-haspopup="dialog">ƒx Indicators <span id="indicator-count"></span></button>
    <span class="toolbar-spacer"></span>
    <button id="fit">Fit full run</button>
    <button id="reset-price">Reset price</button>
  </div>
  <div id="reviewbar">
    <label for="trade">Review trade</label><select id="trade"></select>
    <button id="center">Center selected</button>
    <div id="active-indicators" aria-label="Active indicators"></div>
    <span id="timeframe-note" class="muted" role="status"></span>
  </div>
  <details id="diagnostics"><summary>Trade diagnostics (expand)</summary><div id="diag">Loading…</div></details>
  <div id="chart-wrap">
    <div id="chart"></div>
    <div id="fib-layer"></div>
    <div id="trade-box-layer"></div>
  </div>
</div>
<dialog id="indicator-dialog" aria-labelledby="indicator-title">
  <div class="dialog-header"><h2 id="indicator-title">Indicators</h2><button id="close-indicators" aria-label="Close indicators">✕</button></div>
  <div class="dialog-body">
    <p class="muted">EMA and Wilder RSI use Crypto Strategy Lab calculations for the selected chart timeframe.</p>
    <input id="indicator-search" type="search" placeholder="Search indicators…" aria-label="Search indicators">
    <section class="indicator-group" data-search="ema exponential moving average price overlays">
    <h3>EMA</h3><p>Exponential moving average · select one or more periods (bars).</p>
    <details id="ema-menu" class="ema-menu period-picker"><summary>Periods <span id="ema-period-summary"></span> ▾</summary>
      <div class="ema-options" role="group" aria-label="Visible EMA periods">
        <label><input type="checkbox" class="ema-period" value="9"> EMA 9</label>
        <label><input type="checkbox" class="ema-period" value="20" checked> EMA 20</label>
        <label><input type="checkbox" class="ema-period" value="50"> EMA 50</label>
        <label><input type="checkbox" class="ema-period" value="100"> EMA 100</label>
        <label><input type="checkbox" class="ema-period" value="200"> EMA 200</label>
        <label><input type="checkbox" class="ema-period" value="320" checked> EMA 320</label>
        <label><input type="checkbox" class="ema-period" value="1600" checked> EMA 1600</label>
      </div>
    </details>
    </section>
    <section class="indicator-group" data-search="rsi relative strength index wilder ema research oscillator">
    <h3>RSI</h3><p>Relative strength index · select periods by smoothing method.</p>
    <label class="indicator-option" title="RSI 14 + EMA RSI 224 / 1120"><input type="checkbox" id="show-rsi" checked> Show RSI panel</label>
    <details class="period-picker" id="rsi-period-picker"><summary>Periods <span id="rsi-period-summary"></span> ▾</summary>
    <div class="rsi-method">Wilder · CSL strategy calculation</div>
    <div class="period-options">
    <label class="indicator-option"><input type="checkbox" class="rsi-line" value="rsi:14" checked> Wilder RSI 14 (CSL)</label>
    </div>
    <div class="rsi-method">EMA smoothing · research calculation</div>
    <div class="period-options">
    <label class="indicator-option"><input type="checkbox" class="rsi-line" value="ema_rsi:224" checked> EMA RSI 224 (research)</label>
    <label class="indicator-option"><input type="checkbox" class="rsi-line" value="ema_rsi:1120" checked> EMA RSI 1120 (research)</label>
    </div></details>
    </section>
    <p id="indicator-empty" class="muted" hidden>No matching indicators.</p>
    <div class="panel-settings"><label for="rsi-height">RSI panel height</label><input id="rsi-height" type="range" min="120" max="420" value="260" step="10" title="Adjust RSI panel height">
    <button id="reset-rsi">Reset RSI zoom</button>
    </div>
  </div>
</dialog>
<script>
(() => {
  const boot = __BOOTSTRAP__;
  const $ = id => document.getElementById(id);
  $('chart-symbol').textContent = boot.run.symbol;
  const indicatorDialog = $('indicator-dialog');
  const indicatorInputs = [...document.querySelectorAll('.ema-period, .rsi-line, #show-rsi')];
  function indicatorName(input) {
    if (input.classList.contains('ema-period')) return 'EMA ' + input.value;
    return (input.value.startsWith('ema_rsi:') ? 'EMA RSI ' : 'Wilder RSI ') + input.value.split(':')[1];
  }
  // Family names stay on the cards; the selectors show only their periods.
  for (const input of indicatorInputs.filter(input => input.id !== 'show-rsi')) {
    const label = input.closest('label');
    label.title = indicatorName(input);
    input.setAttribute('aria-label', indicatorName(input));
    for (const node of [...label.childNodes]) if (node.nodeType === Node.TEXT_NODE) node.remove();
    label.appendChild(document.createTextNode(' ' + input.value.split(':').pop()));
  }
  function updateIndicatorSummary() {
    $('ema-period-summary').textContent = [...document.querySelectorAll('.ema-period:checked')].map(input => input.value).join(', ') || 'None';
    const rsiPeriods = [...document.querySelectorAll('.rsi-line:checked')];
    $('rsi-period-summary').textContent = rsiPeriods.map(input => input.value.split(':')[1] + (input.value.startsWith('ema_rsi:') ? ' EMA' : ' Wilder')).join(', ') || 'None';
    const active = indicatorInputs.filter(input => input.checked && (input.classList.contains('ema-period') || (input.classList.contains('rsi-line') && $('show-rsi').checked)));
    $('indicator-count').textContent = '(' + active.length + ')';
    $('active-indicators').replaceChildren();
    for (const input of active) {
      const chip = document.createElement('button');
      chip.className = 'indicator-chip';
      chip.textContent = indicatorName(input) + ' ×';
      chip.title = 'Remove ' + indicatorName(input);
      chip.addEventListener('click', () => {
        input.checked = false;
        input.dispatchEvent(new Event('change'));
      });
      $('active-indicators').appendChild(chip);
    }
  }
  $('indicators-btn').addEventListener('click', () => {
    indicatorDialog.showModal();
    $('indicator-search').focus();
  });
  $('close-indicators').addEventListener('click', () => indicatorDialog.close());
  indicatorDialog.addEventListener('click', event => {
    if (event.target !== indicatorDialog) return;
    const rect = indicatorDialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) indicatorDialog.close();
  });
  $('indicator-search').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    const groups = [...document.querySelectorAll('.indicator-group')];
    for (const group of groups) {
      group.hidden = !(group.dataset.search + ' ' + group.textContent).toLowerCase().includes(query);
      if (query && !group.hidden) group.querySelector('details').open = true;
    }
    $('indicator-empty').hidden = groups.some(group => !group.hidden);
  });
  indicatorInputs.forEach(input => input.addEventListener('change', updateIndicatorSummary));
  updateIndicatorSummary();
  const tradeSelect = $('trade');
  const diag = $('diag');
  const chartWrap = $('chart-wrap');
  const fibLayer = $('fib-layer');
  const tradeBoxLayer = $('trade-box-layer');
  let payload = null;
  let currentTimeframe = boot.run.timeframe;
  let loadGeneration = 0;
  const timeframeSelect = $('chart-timeframe');
  timeframeSelect.add(new Option(currentTimeframe + ' (strategy)', currentTimeframe));
  let currentTrade = 0;
  let chart = null;
  let candles = null;
  let trendEmaLines = [];
  let rsiSeries = null;
  let rsiZoomFactor = 1.0;
  let rsiCenter = 50;
  let priceZoomFactor = 1.0;
  let pricePanOffset = 0.0;
  let verticalPan = null;
  let defaultPriceRange = null;

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

  function computeSelectedPriceRange() {
    const items=payload?.candles || [];
    const start=Number(payload?.selectedTradeViewStart);
    const end=Number(payload?.selectedTradeViewEnd);
    let low=Infinity, high=-Infinity;
    for (const bar of items) {
      const time=Number(bar?.time);
      if (Number.isFinite(start) && time < start) continue;
      if (Number.isFinite(end) && time > end) continue;
      const lo=Number(bar?.low), hi=Number(bar?.high);
      if (Number.isFinite(lo)) low=Math.min(low,lo);
      if (Number.isFinite(hi)) high=Math.max(high,hi);
    }
    const trade=payload?.selectedTrade || {};
    for (const value of [
      trade.Entry ?? trade.entry, trade.Stop ?? trade.stop,
      trade.Target ?? trade.target, trade.Exit ?? trade.exit,
    ]) {
      const price=Number(value);
      if (Number.isFinite(price)) { low=Math.min(low,price); high=Math.max(high,price); }
    }
    for (const item of (payload?.fibDerivation?.levels || [])) {
      const price=Number(item?.price);
      if (Number.isFinite(price)) { low=Math.min(low,price); high=Math.max(high,price); }
    }
    if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return null;
    const span=high-low;
    const pad=Math.max(span*.08,Math.abs(high)*.0005);
    return {minValue:low-pad,maxValue:high+pad};
  }

  function resetPriceScale() {
    defaultPriceRange=computeSelectedPriceRange();
    priceZoomFactor=1.0;
    pricePanOffset=0.0;
    chart?.priceScale('right').applyOptions({autoScale:false});
    requestAnimationFrame(() => {
      chart?.priceScale('right').applyOptions({autoScale:true});
      candles?.applyOptions({});
      drawFibOverlay();
      drawTradeBox();
    });
  }

  function redrawOverlays() {
    drawFibOverlay();
    drawTradeBox();
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
    const entryTime=Number(payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime || fib.entryTime);
    const anchors=resolveFibAnchorTimes(fib,items,entryTime);
    const startTime=Number(anchors.startTime);
    const endTime=Number.isFinite(entryTime) ? entryTime : Number(anchors.endTime);
    const scale=chart.timeScale();
    const plotRight=Math.max(0,$('chart-wrap').clientWidth-76);
    // Swing pivots can precede the selected candle window. Lightweight Charts
    // returns null for an unknown/off-window timestamp; do not hide all levels.
    const axisX=(time, edge) => {
      const x=scale.timeToCoordinate(time);
      return x != null && Number.isFinite(Number(x)) ? Number(x) : edge;
    };
    const x1=axisX(startTime,0);
    const x2=axisX(endTime,plotRight);
    const left=Math.max(0,Math.min(plotRight,Math.min(x1,x2)));
    const right=Math.max(0,Math.min(plotRight,Math.max(x1,x2)));
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
    // Draw the impulse diagonal only when its actual anchors map to the chart;
    // off-window pivots must not prevent the horizontal Fib bands from drawing.
    const rawStartX=chart.timeScale().timeToCoordinate(startTime);
    if ([rawStartX,anchorEndX,startY,endY].every(v => v != null && Number.isFinite(Number(v)))) {
      const dx=Number(anchorEndX)-Number(rawStartX), dy=Number(endY)-Number(startY);
      const anchor=document.createElement('div');
      anchor.className='fib-anchor';
      anchor.style.left=Number(rawStartX)+'px';
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
    trendEmaLines = [];
    rsiSeries = null;
    chart = window.LightweightCharts.createChart($('chart'),{
      autoSize:true,
      layout:{background:{type:'solid',color:'#0f1720'},textColor:'#b8c2cc'},
      grid:{vertLines:{color:'#1d2937'},horzLines:{color:'#1d2937'}},
      rightPriceScale:{borderColor:'#334155',autoScale:true,entireTextOnly:true,scaleMargins:{top:.08,bottom:.08}},
      timeScale:{borderColor:'#334155',timeVisible:true,secondsVisible:false,rightOffset:8},
      handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},
      handleScale:{
        axisPressedMouseMove:{time:true,price:true},
        axisDoubleClickReset:{time:true,price:true},
        mouseWheel:true,pinch:true,
      },
    });
    candles = chart.addSeries(window.LightweightCharts.CandlestickSeries,{
      upColor:'#22a06b',downColor:'#d84a4a',borderVisible:false,
      wickUpColor:'#22a06b',wickDownColor:'#d84a4a',
      autoscaleInfoProvider: original => {
        const info=original();
        const base=defaultPriceRange || info?.priceRange;
        if (!base) return info;
        const min=Number(base.minValue), max=Number(base.maxValue);
        if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return info;
        const span=max-min;
        const mid=(min+max)/2 + span*pricePanOffset;
        const half=(span/2)*priceZoomFactor;
        return {...(info || {}),priceRange:{minValue:mid-half,maxValue:mid+half}};
      },
    });
    candles.setData(payload.candles || []);
    const selectedEmas = new Set([...document.querySelectorAll('.ema-period:checked')].map(input => Number(input.value)));
    if (selectedEmas.size) {
      for (const overlay of (payload.overlays || [])) {
        if (overlay.kind !== 'ema' || !selectedEmas.has(Number(overlay.period))) continue;
        const emaColors = {9:'#60a5fa',20:'#4ade80',50:'#fb923c',100:'#a78bfa',200:'#e879f9',320:'#facc15',1600:'#fb7185'};
        const series=chart.addSeries(window.LightweightCharts.LineSeries,{
          color:emaColors[Number(overlay.period)] || '#e2e8f0',
          lineWidth:2,priceLineVisible:false,lastValueVisible:true,
          crosshairMarkerVisible:false,
          // Share candle coordinates, but do not let trend EMA lines enlarge
          // the auto price range and override custom vertical zoom/pan.
          autoscaleInfoProvider: () => null,
          title:overlay.name,
        });
        series.setData(overlay.data || []);
        trendEmaLines.push(series);
      }
    }
    const selectedRsi = new Set([...document.querySelectorAll('.rsi-line:checked')].map(input => input.value));
    const rsiOverlays = (payload.overlays || []).filter(o => ((o.kind === 'ema_rsi' && [224,1120].includes(Number(o.period))) || (o.kind === 'rsi' && Number(o.period) === 14)) && selectedRsi.has(o.kind + ':' + o.period));
    if (rsiOverlays.length && $('show-rsi').checked && rsiOverlays.some(o => (o.data || []).length)) {
      // The built-in second pane shares the price chart's time scale:
      // horizontal panning, zooming, and crosshair remain aligned.
      for (const overlay of rsiOverlays) {
      const line = chart.addSeries(window.LightweightCharts.LineSeries,{
        color:overlay.kind === 'rsi' ? '#f59e0b' : (Number(overlay.period)===224 ? '#a78bfa' : '#22d3ee'),
        lineWidth:2,title:overlay.name,
        priceFormat:{type:'price',precision:1,minMove:0.1},
        priceLineVisible:false,lastValueVisible:true,
        autoscaleInfoProvider: original => {
          const info=original();
          const half=50*rsiZoomFactor;
          return {...(info || {}),priceRange:{minValue:rsiCenter-half,maxValue:rsiCenter+half}};
        },
      },1);
      line.setData(overlay.data || []);
      if (!rsiSeries) rsiSeries=line;
      }
      for (const level of [30,70]) {
        rsiSeries.createPriceLine({
          price:level,color:'#64748b',lineWidth:1,
          lineStyle:window.LightweightCharts.LineStyle.Dashed,
          axisLabelVisible:true,title:String(level),
        });
      }
      requestAnimationFrame(() => chart?.panes()[1]?.setHeight(Number($('rsi-height').value)));
    }
    const redraw=redrawOverlays;
    chart.timeScale().subscribeVisibleTimeRangeChange(redraw);
    if (window.ResizeObserver) new ResizeObserver(redraw).observe($('chart-wrap'));
    requestAnimationFrame(() => {
      redraw();
      setTimeout(redraw, 40);
    });
  }

  $('rsi-height').addEventListener('input', () => {
    if (rsiSeries && chart?.panes()[1]) {
      chart.panes()[1].setHeight(Number($('rsi-height').value));
      requestAnimationFrame(redrawOverlays);
    }
  });
  $('reset-rsi').addEventListener('click', () => {
    rsiZoomFactor=1.0;
    rsiCenter=50;
    rsiSeries?.applyOptions({});
  });

  $('show-rsi').addEventListener('change', () => {
    if (!payload || !chart) return;
    const visibleRange=chart.timeScale().getVisibleRange();
    buildChart();
    if (visibleRange) chart.timeScale().setVisibleRange(visibleRange);
  });

  document.querySelectorAll('.ema-period, .rsi-line').forEach(input => input.addEventListener('change', () => {
    if (!payload || !chart) return;
    const visibleRange = chart.timeScale().getVisibleRange();
    buildChart();
    if (visibleRange) chart.timeScale().setVisibleRange(visibleRange);
  }));

  function centerSelected() {
    if (!payload || !chart) return;
    const start = Number(payload.selectedTradeViewStart);
    const end = Number(payload.selectedTradeViewEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    chart.timeScale().setVisibleRange({from:start,to:end});
    defaultPriceRange=computeSelectedPriceRange();
    priceZoomFactor=1.0;
    pricePanOffset=0.0;
    chart.priceScale('right').applyOptions({autoScale:false});
    requestAnimationFrame(() => chart.priceScale('right').applyOptions({autoScale:true}));
    requestAnimationFrame(() => {
      drawFibOverlay();
      drawTradeBox();
      setTimeout(() => { drawFibOverlay(); drawTradeBox(); }, 40);
    });
  }

  function inCandlePane(event) {
    const rect=chartWrap.getBoundingClientRect();
    if (!chart || !candles || event.clientY < rect.top || event.clientY >= rect.bottom) return false;
    if (!rsiSeries) return true;
    const paneHeight=chart.panes()[0].getHeight();
    return event.clientY - rect.top < paneHeight;
  }

  // Wheel over the right price scale changes vertical zoom only.
  chartWrap.addEventListener('wheel',event => {
    const rect=chartWrap.getBoundingClientRect();
    const overPriceScale=event.clientX-rect.left >= rect.width-86;
    if (!overPriceScale || !candles) return;
    if (!inCandlePane(event)) {
      if (!rsiSeries) return;
      event.preventDefault();
      event.stopPropagation();
      const direction=event.deltaY>0 ? 1.12 : 0.89;
      rsiZoomFactor=Math.max(.04,Math.min(1,rsiZoomFactor*direction));
      rsiSeries.applyOptions({});
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const direction=event.deltaY > 0 ? 1.12 : 0.89;
    priceZoomFactor=Math.max(.005,Math.min(50,priceZoomFactor*direction));
    chart?.priceScale('right').applyOptions({autoScale:true});
    candles.applyOptions({});
    requestAnimationFrame(redrawOverlays);
  },{passive:false,capture:true});

  // Primarily vertical left-drag moves the chart price range up/down.
  // Horizontal drags remain normal time-axis panning.
  chartWrap.addEventListener('pointerdown',event => {
    if (event.button !== 0 || !candles || !inCandlePane(event)) return;
    const rect=chartWrap.getBoundingClientRect();
    if (event.clientX-rect.left >= rect.width-86) return;
    verticalPan={
      pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,
      lastY:event.clientY,active:false,
    };
  },{capture:true});

  chartWrap.addEventListener('pointermove',event => {
    if (!verticalPan || verticalPan.pointerId !== event.pointerId || !(event.buttons & 1)) {
      if (event.buttons) requestAnimationFrame(redrawOverlays);
      return;
    }
    const dx=event.clientX-verticalPan.startX;
    const dyTotal=event.clientY-verticalPan.startY;
    if (!verticalPan.active) {
      if (Math.abs(dyTotal) < 7 || Math.abs(dyTotal) <= Math.abs(dx)*1.15) return;
      verticalPan.active=true;
      chartWrap.setPointerCapture?.(event.pointerId);
    }
    event.preventDefault();
    event.stopPropagation();
    const dy=event.clientY-verticalPan.lastY;
    verticalPan.lastY=event.clientY;
    const height=Math.max(120,chartWrap.clientHeight);
    pricePanOffset += (dy/height)*2.0*priceZoomFactor;
    pricePanOffset=Math.max(-8,Math.min(8,pricePanOffset));
    chart?.priceScale('right').applyOptions({autoScale:true});
    candles.applyOptions({});
    requestAnimationFrame(redrawOverlays);
  },{passive:false,capture:true});

  const finishVerticalPan=event => {
    if (!verticalPan || verticalPan.pointerId !== event.pointerId) return;
    if (verticalPan.active) {
      event.preventDefault();
      event.stopPropagation();
      chartWrap.releasePointerCapture?.(event.pointerId);
    }
    verticalPan=null;
  };
  chartWrap.addEventListener('pointerup',finishVerticalPan,{capture:true});
  chartWrap.addEventListener('pointercancel',finishVerticalPan,{capture:true});

  async function load() {
    const generation = ++loadGeneration;
    const requestedTimeframe = currentTimeframe;
    diag.textContent = 'Loading…';
    $('timeframe-note').textContent = 'Loading ' + requestedTimeframe + '…';
    try {
      const nextPayload = await getJson(api('/api/payload',{
        trade_index:String(currentTrade),
        chart_timeframe:requestedTimeframe,
        full_run:'1',
      }));
      if (generation !== loadGeneration) return;
      payload = nextPayload;
      timeframeSelect.replaceChildren();
      for (const item of (payload.run.availableChartTimeframes || [{interval:boot.run.timeframe}])) {
        const label = item.interval + (item.interval === boot.run.timeframe ? ' (strategy)' : '') + (item.coverage === 'partial' ? ' (partial data)' : '');
        timeframeSelect.add(new Option(label, item.interval));
      }
      timeframeSelect.value = requestedTimeframe;
      $('timeframe-note').textContent = requestedTimeframe === boot.run.timeframe
        ? 'CSL indicators · strategy timeframe'
        : 'CSL indicators · chart timeframe ' + requestedTimeframe + ' · trades from ' + boot.run.timeframe;
      buildChart();
      renderDiagnostics();
      requestAnimationFrame(centerSelected);
    } catch (error) {
      if (generation !== loadGeneration) return;
      currentTimeframe = payload?.chartTimeframe || boot.run.timeframe;
      timeframeSelect.value = currentTimeframe;
      $('timeframe-note').textContent = 'Could not load ' + requestedTimeframe + ': ' + error.message;
      diag.textContent = 'ERROR: ' + error.message;
    }
  }

  timeframeSelect.addEventListener('change', () => {
    currentTimeframe = timeframeSelect.value;
    load();
  });

  tradeSelect.addEventListener('change',() => {
    currentTrade = Number(tradeSelect.value);
    load();
  });
  $('center').addEventListener('click',centerSelected);
  $('fit').addEventListener('click',() => {
    chart?.timeScale().fitContent();
    defaultPriceRange=null;
    priceZoomFactor=1.0;
    pricePanOffset=0.0;
    chart?.priceScale('right').applyOptions({autoScale:true});
    candles?.applyOptions({});
  });
  $('reset-price').addEventListener('click',resetPriceScale);
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
        self._stop_requested: Event | None = None

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
                host = self.headers.get("Host", "")
                origin = self.headers.get("Origin")
                try:
                    parsed_host = urlsplit("http://" + host)
                    port = int(self.server.server_address[1])
                    safe_host = (
                        parsed_host.hostname in {"127.0.0.1", "localhost"}
                        and parsed_host.port == port
                        and parsed_host.username is None
                        and parsed_host.password is None
                        and parsed_host.path == ""
                        and parsed_host.query == ""
                        and parsed_host.fragment == ""
                    )
                    safe_origin = origin is None or origin in {
                        f"http://127.0.0.1:{port}", f"http://localhost:{port}"
                    }
                    request_path = urlsplit(self.path).path
                    root = f"/session/{owner.token}"
                    document = request_path in {root, root + "/", root + "/index.html"}
                    site = self.headers.get("Sec-Fetch-Site", "same-origin")
                    safe_fetch = site in {"same-origin", "none"} or (
                        site == "same-site" and document
                        and self.headers.get("Sec-Fetch-Mode") == "navigate"
                        and self.headers.get("Sec-Fetch-Dest") == "document"
                    )
                except ValueError:
                    safe_host = safe_origin = safe_fetch = False
                if not (safe_host and safe_origin and safe_fetch):
                    self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return
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

        server = _LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 0.1
        self._server = server
        stopped = Event()
        self._stop_requested = stopped

        def serve_until_stopped():
            while not stopped.is_set():
                server.handle_request()

        try:
            thread = Thread(target=serve_until_stopped,
                            name="strategy-visualizer-v2-browser", daemon=True)
            self._thread = thread
            thread.start()
        except BaseException:
            stopped.set()
            thread = self._thread
            if thread is not None:
                try:
                    thread.join(timeout=2.0)
                except RuntimeError:
                    pass
            server.server_close()
            self._server = None
            self._thread = None
            raise
        return self.url

    def stop(self) -> None:
        server, thread = self._server, self._thread
        if self._stop_requested is not None:
            self._stop_requested.set()
        self._server = None
        self._thread = None
        self._stop_requested = None
        if server is None:
            return
        if thread is not None:
            try:
                thread.join(timeout=2.0)
            except RuntimeError:
                pass
        server.server_close()

__all__=[
    "StrategyVisualizerV2BrowserServer",
    "build_browser_visualizer_v2_html",
]
