"""Loopback browser host for the read-only Strategy Visualizer.

The desktop workstation owns the completed-run model.  This module exposes that
same immutable model through a short-lived, read-only HTTP server bound only to
127.0.0.1 so the visualizer can use a normal system browser without changing
strategy execution or persisted research artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    MAX_VISIBLE_CANDLES,
)


BROWSER_DEFAULT_VISIBLE_CANDLES = min(1000, MAX_VISIBLE_CANDLES)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def build_browser_visualizer_html(
    model: CompletedRunVisualizer,
    session_token: str,
) -> str:
    """Build the responsive browser shell; chart data is fetched from loopback APIs."""
    request = model.seed.request
    bootstrap = {
        "sessionBase": f"/session/{session_token}",
        "defaultVisibleCandles": BROWSER_DEFAULT_VISIBLE_CANDLES,
        "maxVisibleCandles": MAX_VISIBLE_CANDLES,
        "chartTimeframes": model.available_chart_timeframes(),
        "trades": [
            {"index": index, "label": model.trade_label(index)}
            for index in range(model.trade_count)
        ],
        "run": {
            "runId": str(model.manifest.get("run_id") or model.run_dir.name),
            "symbol": request.symbol,
            "timeframe": request.strategy_timeframe,
            "strategyTimeframe": request.strategy_timeframe,
            "tradeCount": model.trade_count,
        },
    }
    encoded = json.dumps(
        bootstrap, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")

    template = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Visualizer · Browser Audit</title>
<style>
:root {
  color-scheme: dark;
  --bg:#0b121a; --panel:#111b26; --panel2:#0f1720; --border:#2b3948;
  --text:#e6edf3; --muted:#91a0b2; --accent:#8fb4ff; --good:#6fd3a4;
  --bad:#f08a8a; --warn:#d8b36a;
}
*{box-sizing:border-box}
html,body{height:100%;margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
button,select,input{font:inherit}
button,select{
  background:#172330;color:var(--text);border:1px solid #3a4a5c;border-radius:5px;
  min-height:30px;padding:4px 8px
}
button:hover,select:hover{border-color:#6f86a0}
button{cursor:pointer}
label{display:flex;align-items:center;gap:5px;color:#b7c2cf;font-size:12px;white-space:nowrap}
#app{height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto}
#toolbar,#layers{
  display:flex;align-items:center;gap:7px;padding:7px 9px;border-bottom:1px solid var(--border);
  background:#101923;overflow-x:auto
}
#toolbar{flex-wrap:wrap}
#layers{padding-top:5px;padding-bottom:5px}
#trade-select{min-width:340px;max-width:min(620px,48vw);flex:1}
.spacer{flex:1}
.run-badge{font-size:12px;color:#b8c5d4;padding:4px 7px;border:1px solid #334155;border-radius:5px;background:#0d1620}
.layer-group{display:flex;gap:9px;align-items:center;padding-right:10px;border-right:1px solid #334155}
.layer-group:last-child{border-right:0}
#main{min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 390px}
#main.inspector-collapsed{grid-template-columns:minmax(0,1fr) 0}
#chart-wrap{position:relative;min-width:0;min-height:0;background:#0f1720}
#chart{position:absolute;inset:0;z-index:1}
#zone-layer,#zone-label-layer{position:absolute;inset:0;pointer-events:none;overflow:hidden}
#zone-layer{z-index:2}
#zone-label-layer{z-index:4}
.zone-band{position:absolute;box-sizing:border-box;border-radius:2px}
.zone-label{
  position:absolute;right:72px;max-width:260px;padding:2px 6px;border-radius:3px;
  font-size:11px;font-weight:600;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.35)
}
.zone-label.support{background:rgba(33,92,68,.94);color:#c7f4de;border:1px solid rgba(111,211,164,.55)}
.zone-label.resistance{background:rgba(107,52,52,.94);color:#ffd1d1;border:1px solid rgba(240,138,138,.55)}
#readout{
  position:absolute;left:10px;top:8px;z-index:5;pointer-events:none;
  background:rgba(15,23,32,.86);border:1px solid #334155;border-radius:5px;
  padding:7px 9px;font-size:12px;line-height:1.45;max-width:68%;white-space:normal
}
#facts{font-size:11px;color:#b8c2cc;margin-top:3px}
#error{
  position:absolute;inset:20px;z-index:20;display:none;place-items:center;text-align:center;
  color:#ffb4b4;background:rgba(15,23,32,.9);padding:20px
}
#inspector{
  min-width:0;overflow:hidden;border-left:1px solid var(--border);background:#101923;
  display:grid;grid-template-rows:auto auto minmax(0,1fr)
}
#main.inspector-collapsed #inspector{display:none}
#inspector-head{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid var(--border)}
#inspector-head strong{font-size:13px}
#tabs{display:flex;border-bottom:1px solid var(--border)}
.tab{
  flex:1;border:0;border-radius:0;background:transparent;color:#9eabba;min-height:34px
}
.tab.active{color:#fff;background:#172330;border-bottom:2px solid var(--accent)}
#inspector-body{overflow:auto;padding:9px}
.panel{display:none}.panel.active{display:block}
.kv{width:100%;border-collapse:collapse;font-size:12px}
.kv th,.kv td{padding:5px 6px;border-bottom:1px solid #273443;text-align:left;vertical-align:top}
.kv th{width:42%;color:#aeb9c6;font-weight:500}
.section-title{font-weight:650;font-size:12px;margin:10px 0 5px;color:#cbd5e1}
.note{font-size:11px;color:var(--muted);line-height:1.4;margin:4px 0 8px}
.status-pass{color:var(--good)}.status-fail{color:var(--bad)}.status-warn{color:var(--warn)}
.rule-row,.zone-row{
  border:1px solid #2b3948;border-radius:5px;margin:5px 0;padding:6px 7px;background:#111c27;font-size:11px
}
.zone-row{cursor:pointer}
.zone-row:hover{border-color:#657b94}
.zone-row.focused{outline:1px solid var(--accent);background:#17283a}
.row-head{display:flex;justify-content:space-between;gap:8px;font-weight:600;margin-bottom:3px}
.row-sub{color:#aab7c6;line-height:1.45}
#footer{
  display:flex;gap:12px;align-items:center;justify-content:space-between;padding:5px 9px;
  border-top:1px solid #263241;color:#8f9baa;font-size:11px;background:#0d151e
}
#footer a{color:#a9c8ff;text-decoration:none}
kbd{border:1px solid #475569;border-bottom-width:2px;border-radius:3px;padding:0 4px;font-size:10px;color:#cbd5e1}
@media(max-width:900px){
  #main{grid-template-columns:minmax(0,1fr)}
  #inspector{position:absolute;right:0;top:92px;bottom:25px;width:min(390px,92vw);z-index:30;box-shadow:-8px 0 28px rgba(0,0,0,.38)}
  #main.inspector-collapsed #inspector{display:none}
  #trade-select{min-width:220px;max-width:100%}
}
</style>
<script src="__LIGHTWEIGHT_CHARTS_URL__"></script>
</head>
<body>
<div id="app">
  <div id="toolbar">
    <span class="run-badge" id="run-badge"></span>
    <button id="prev-trade" title="Previous trade">◀</button>
    <select id="trade-select" title="Completed trade"></select>
    <button id="next-trade" title="Next trade">▶</button>
    <label>Chart TF
      <select id="chart-tf"></select>
    </label>
    <label>Window
      <select id="window-size"></select>
    </label>
    <button id="center-trade">Center trade</button>
    <button id="fit-chart">Fit loaded</button>
    <span class="spacer"></span>
    <button id="toggle-inspector">Hide inspector</button>
    <button id="fullscreen">Full screen</button>
  </div>
  <div id="layers">
    <div class="layer-group">
      <strong style="font-size:11px;color:#94a3b8">Layers</strong>
      <label><input type="checkbox" data-overlay="ema50" checked>EMA 50</label>
      <label><input type="checkbox" data-overlay="ema100" checked>EMA 100</label>
      <label><input type="checkbox" data-overlay="ema200" checked>EMA 200</label>
      <label><input type="checkbox" data-overlay="vwap" checked>VWAP</label>
      <label><input type="checkbox" data-overlay="bb">BB</label>
      <label><input type="checkbox" id="show-rejections">Rejected</label>
    </div>
    <div class="layer-group">
      <label>View
        <select id="view-mode">
          <option value="normal">Normal</option>
          <option value="audit">S/R Audit</option>
        </select>
      </label>
      <label>S/R TF
        <select id="sr-tf">
          <option value="4h">4H</option>
          <option value="strategy">Strategy TF</option>
          <option value="1h">1H</option>
          <option value="1d">1D</option>
          <option value="compare">Compare all</option>
        </select>
      </label>
      <label>Snapshot
        <select id="sr-snapshot">
          <option value="live">Live through loaded chart</option>
          <option value="entry">Entry snapshot</option>
        </select>
      </label>
      <label>Details
        <select id="sr-details">
          <option value="zones">Zones</option>
          <option value="lifecycle">Lifecycle</option>
          <option value="all">All</option>
        </select>
      </label>
      <label><input type="checkbox" id="nearest-only">Nearest only</label>
      <button id="clear-zone">Clear zone focus</button>
    </div>
  </div>
  <div id="main">
    <div id="chart-wrap">
      <div id="chart"></div>
      <div id="zone-layer"></div>
      <div id="zone-label-layer"></div>
      <div id="readout">Loading completed-run chart…</div>
      <div id="error"></div>
    </div>
    <aside id="inspector">
      <div id="inspector-head">
        <strong>Inspector</strong>
        <span id="inspect-time" class="note"></span>
      </div>
      <div id="tabs">
        <button class="tab active" data-tab="trade">Trade</button>
        <button class="tab" data-tab="rules">Strategy</button>
        <button class="tab" data-tab="sr">S/R</button>
      </div>
      <div id="inspector-body">
        <div class="panel active" id="panel-trade"></div>
        <div class="panel" id="panel-rules"></div>
        <div class="panel" id="panel-sr"></div>
      </div>
    </aside>
  </div>
  <div id="footer">
    <span>Read-only completed-run browser · no strategy re-evaluation · loopback only</span>
    <span>Shortcuts: <kbd>F</kbd> fit · <kbd>Home</kbd> center · <kbd>I</kbd> inspector · <kbd>Esc</kbd> clear zone</span>
    <span>Charting by <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></span>
  </div>
</div>
<script>
(() => {
  const boot = __BOOTSTRAP__;
  const $ = id => document.getElementById(id);
  const main = $('main');
  const chartWrap = $('chart-wrap');
  const zoneLayer = $('zone-layer');
  const zoneLabelLayer = $('zone-label-layer');
  const errorBox = $('error');
  const readout = $('readout');
  const tradeSelect = $('trade-select');
  const chartTf = $('chart-tf');
  const windowSize = $('window-size');
  const viewMode = $('view-mode');
  const srTf = $('sr-tf');
  const srSnapshot = $('sr-snapshot');
  const srDetails = $('sr-details');
  const nearestOnly = $('nearest-only');
  const showRejections = $('show-rejections');
  let payload = null;
  let chart = null;
  let candle = null;
  let currentTrade = 0;
  let inspectedTime = null;
  let focusedZone = null;
  let lastInspection = null;

  function updateRunBadge() {
    const selected = chartTf.value || boot.run.strategyTimeframe;
    $('run-badge').textContent =
      boot.run.symbol + ' · Strategy ' + boot.run.strategyTimeframe +
      ' · Chart ' + selected + ' · ' +
      boot.run.tradeCount.toLocaleString() + ' trades';
  }

  for (const item of boot.trades) {
    const option = document.createElement('option');
    option.value = String(item.index);
    option.textContent = item.label;
    tradeSelect.appendChild(option);
  }

  for (const item of (boot.chartTimeframes || [])) {
    const option = document.createElement('option');
    option.value = String(item.interval);
    option.textContent = String(item.interval).toUpperCase() +
      (item.strategyTimeframe ? ' · strategy' : '') +
      (item.coverage === 'partial' ? ' · partial coverage' : '');
    option.disabled = item.coverage === 'partial';
    if (String(item.interval) === String(boot.run.strategyTimeframe))
      option.selected = true;
    chartTf.appendChild(option);
  }
  if (!chartTf.options.length) {
    const option = document.createElement('option');
    option.value = String(boot.run.strategyTimeframe);
    option.textContent = String(boot.run.strategyTimeframe).toUpperCase() + ' · strategy';
    chartTf.appendChild(option);
  }
  updateRunBadge();

  const windowChoices = [240, 500, 1000, 2000, 5000]
    .filter(value => value <= Number(boot.maxVisibleCandles));
  if (!windowChoices.includes(Number(boot.defaultVisibleCandles)))
    windowChoices.push(Number(boot.defaultVisibleCandles));
  windowChoices.sort((a,b) => a-b);
  for (const value of windowChoices) {
    const option = document.createElement('option');
    option.value = String(value);
    option.textContent = value.toLocaleString() + ' candles';
    if (value === Number(boot.defaultVisibleCandles)) option.selected = true;
    windowSize.appendChild(option);
  }
  const fullRunOption = document.createElement('option');
  fullRunOption.value = 'full';
  fullRunOption.textContent = 'Full run';
  windowSize.appendChild(fullRunOption);

  function api(path, params={}) {
    const query = new URLSearchParams(params);
    return boot.sessionBase + path + (query.toString() ? '?' + query.toString() : '');
  }
  async function fetchJson(url) {
    const response = await fetch(url, {cache:'no-store'});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
    return body;
  }
  function showError(message) {
    errorBox.style.display = 'grid';
    errorBox.textContent = String(message || 'Unknown visualizer error');
  }
  function clearError() {
    errorBox.style.display = 'none';
    errorBox.textContent = '';
  }
  function esc(value) {
    return String(value ?? '')
      .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
      .replaceAll('"','&quot;').replaceAll("'","&#039;");
  }
  function fmt(value, digits=4) {
    const n = Number(value);
    return Number.isFinite(n)
      ? n.toLocaleString(undefined,{maximumFractionDigits:digits})
      : '—';
  }
  function stamp(time) {
    if (!time) return '';
    return new Date(Number(time)*1000).toISOString().replace('T',' ').slice(0,16) + ' UTC';
  }
  function selectedTimeframes() {
    return srTf.value === 'compare'
      ? new Set(['strategy','1h','4h','1d'])
      : new Set([srTf.value]);
  }
  function overlayEnabled(overlay) {
    const key = overlay.kind === 'ema'
      ? 'ema' + overlay.period
      : overlay.kind;
    const box = document.querySelector('[data-overlay="' + key + '"]');
    return !box || box.checked;
  }
  function zoneNearest(zone) {
    return srSnapshot.value === 'entry'
      ? Boolean(zone.nearestAtEntry)
      : Boolean(zone.nearestAtEnd);
  }
  function zoneActive(zone) {
    return srSnapshot.value === 'entry'
      ? Boolean(zone.activeAtEntry)
      : Boolean(zone.activeAtEnd);
  }
  function zoneMatchesFocus(zone) {
    if (!focusedZone) return false;
    const identity = Array.isArray(zone.zoneIdentity) ? String(zone.zoneIdentity[1] ?? '') : '';
    return identity === String(focusedZone.id) &&
      String(zone.timeframe) === String(focusedZone.timeframe) &&
      String(zone.structure).toUpperCase() === String(focusedZone.structure).toUpperCase();
  }
  function visibleZones() {
    if (!payload) return [];
    const tfs = selectedTimeframes();
    return (payload.srZones || []).filter(zone => {
      if (!tfs.has(String(zone.timeframe))) return false;
      if (nearestOnly.checked && !zoneNearest(zone)) return false;
      if (focusedZone && !zoneMatchesFocus(zone)) return false;
      return true;
    });
  }

  function renderTrade(summary) {
    const rows = Object.entries(summary || {}).map(([key,value]) =>
      '<tr><th>' + esc(key) + '</th><td>' + esc(
        typeof value === 'number' ? fmt(value,6) : value
      ) + '</td></tr>'
    ).join('');
    $('panel-trade').innerHTML =
      '<div class="note">Exact selected completed-trade values.</div>' +
      '<table class="kv">' + rows + '</table>';
  }

  function statusClass(text) {
    const value = String(text || '').toUpperCase();
    if (['PASS','MATCHED','TRIGGERED','PASSED'].some(x => value.includes(x)))
      return 'status-pass';
    if (['FAIL','REJECT','MISSING'].some(x => value.includes(x)))
      return 'status-fail';
    return 'status-warn';
  }
  function renderRules(trace) {
    const panel = $('panel-rules');
    if (!trace || trace.status !== 'AVAILABLE') {
      panel.innerHTML = '<div class="note">' + esc(trace?.message || trace?.status || 'No rule trace selected.') + '</div>';
      return;
    }
    const header =
      '<div class="note">' + esc(trace.timestamp || '') + ' · ' +
      esc(trace.regime || '') + ' · ' + esc(trace.side || '') + ' · ' +
      esc(trace.profile || '') + '</div>';
    const rows = (trace.rows || []).map(item =>
      '<div class="rule-row">' +
        '<div class="row-head"><span>' + esc(item.type) + ' · ' + esc(item.group) + '</span>' +
        '<span class="' + statusClass(item.conditionStatus) + '">' + esc(item.conditionStatus) + '</span></div>' +
        '<div class="row-sub">' + esc(item.evidence) +
        (item.timeframe ? ' · ' + esc(item.timeframe) : '') +
        '<br>Actual: <b>' + esc(item.actual) + '</b> · Required: <b>' + esc(item.requirement) + '</b>' +
        '<br>Group: ' + esc(item.groupStatus) + '</div>' +
      '</div>'
    ).join('');
    panel.innerHTML = header + rows;
  }

  function zoneLabel(item) {
    const low = fmt(item.zoneLow,6), high = fmt(item.zoneHigh,6);
    return low + ' – ' + high;
  }
  function focusZoneFromInspector(item) {
    focusedZone = {
      id: item.zoneId,
      timeframe: item.key,
      structure: item.structure,
    };
    renderChart(false);
    renderSr(lastInspection?.sr || null);
  }
  function renderSr(snapshot) {
    lastInspection = {...(lastInspection || {}), sr:snapshot};
    const panel = $('panel-sr');
    if (!snapshot || snapshot.status !== 'AVAILABLE') {
      panel.innerHTML = '<div class="note">' + esc(snapshot?.message || snapshot?.status || 'No S/R snapshot selected.') + '</div>';
      return;
    }
    const tfs = selectedTimeframes();
    let html = '<div class="note">Persisted S/R exactly at ' + esc(snapshot.timestamp || '') +
      '. Click a zone below to isolate it on the chart.</div>';
    for (const block of (snapshot.timeframes || []).filter(x => tfs.has(String(x.key)))) {
      html += '<div class="section-title">' + esc(block.timeframe) + '</div>' +
        '<table class="kv">' +
        '<tr><th>Support</th><td>' + esc(
          block.supportZoneLow == null ? '—' : fmt(block.supportZoneLow,6) + ' – ' + fmt(block.supportZoneHigh,6)
        ) + '</td></tr>' +
        '<tr><th>Support state</th><td>' + esc(block.supportState || '—') + '</td></tr>' +
        '<tr><th>Support distance</th><td>' + esc(fmt(block.supportDistanceNativeAtr,4)) + ' native ATR</td></tr>' +
        '<tr><th>Resistance</th><td>' + esc(
          block.resistanceZoneLow == null ? '—' : fmt(block.resistanceZoneLow,6) + ' – ' + fmt(block.resistanceZoneHigh,6)
        ) + '</td></tr>' +
        '<tr><th>Resistance state</th><td>' + esc(block.resistanceState || '—') + '</td></tr>' +
        '<tr><th>Resistance distance</th><td>' + esc(fmt(block.resistanceDistanceNativeAtr,4)) + ' native ATR</td></tr>' +
        '<tr><th>Room LONG / SHORT</th><td>' + esc(fmt(block.roomLongNativeAtr,4)) + ' / ' + esc(fmt(block.roomShortNativeAtr,4)) + ' ATR</td></tr>' +
        '<tr><th>Conflict</th><td>' + (block.structureConflict ? 'YES' : 'No') + '</td></tr>' +
        '</table>';
    }
    const zones = (snapshot.zones || []).filter(item => tfs.has(String(item.key)));
    html += '<div class="section-title">Active zone inventory · ' + zones.length + '</div>';
    html += '<div id="zone-list"></div>';
    panel.innerHTML = html;
    const list = panel.querySelector('#zone-list');
    for (const item of zones) {
      const row = document.createElement('div');
      const isFocused = focusedZone &&
        String(focusedZone.id) === String(item.zoneId) &&
        String(focusedZone.timeframe) === String(item.key) &&
        String(focusedZone.structure).toUpperCase() === String(item.structure).toUpperCase();
      row.className = 'zone-row' + (isFocused ? ' focused' : '');
      row.innerHTML =
        '<div class="row-head"><span>' + esc(item.timeframe) + ' · ' + esc(item.structure) + '</span>' +
        '<span>' + (item.nearest ? 'NEAREST' : '') + '</span></div>' +
        '<div class="row-sub">' + esc(zoneLabel(item)) +
        '<br>State: ' + esc(item.state || '—') +
        ' · Tests: ' + esc(item.testCount ?? '—') +
        ' · Sources: ' + esc(item.sourceCount ?? '—') +
        '<br>Distance: ' + esc(fmt(item.distanceNativeAtr,4)) + ' native ATR' +
        (item.held ? ' · HELD' : '') + (item.tested ? ' · TESTED' : '') +
        '</div>';
      row.addEventListener('click', () => focusZoneFromInspector(item));
      list.appendChild(row);
    }
  }

  async function inspectTime(time, activateTab=true) {
    if (!time) return;
    inspectedTime = Number(time);
    $('inspect-time').textContent = stamp(inspectedTime);
    try {
      const data = await fetchJson(api('/api/inspect',{timestamp:String(inspectedTime)}));
      lastInspection = data;
      renderRules(data.rule);
      renderSr(data.sr);
      if (activateTab) activateInspectorTab(viewMode.value === 'audit' ? 'sr' : 'rules');
      if (viewMode.value === 'audit') renderChart(false);
    } catch (error) {
      $('panel-rules').innerHTML = '<div class="note status-fail">' + esc(error.message) + '</div>';
      $('panel-sr').innerHTML = '<div class="note status-fail">' + esc(error.message) + '</div>';
    }
  }

  function activateInspectorTab(name) {
    document.querySelectorAll('.tab').forEach(button =>
      button.classList.toggle('active', button.dataset.tab === name)
    );
    document.querySelectorAll('.panel').forEach(panel =>
      panel.classList.toggle('active', panel.id === 'panel-' + name)
    );
  }

  function shortState(value) {
    return String(value || '')
      .replace('SUPPORT_','').replace('RESISTANCE_','').replaceAll('_',' ');
  }
  function xForTime(time, startSide) {
    const direct = chart.timeScale().timeToCoordinate(time);
    if (direct !== null && direct !== undefined) return direct;
    const range = chart.timeScale().getVisibleRange();
    if (!range) return null;
    const target = Number(time);
    const from = Number(range.from);
    const to = Number(range.to);
    if (!Number.isFinite(target) || !Number.isFinite(from) || !Number.isFinite(to) || to <= from)
      return null;
    if (target <= from) return 0;
    if (target >= to) return chartWrap.clientWidth;
    return ((target - from) / (to - from)) * chartWrap.clientWidth;
  }
  function drawZones() {
    if (!payload || !chart || !candle) return;
    zoneLayer.replaceChildren();
    zoneLabelLayer.replaceChildren();
    if (viewMode.value === 'audit' && srDetails.value === 'lifecycle') return;
    const labels = [];
    for (const zone of visibleZones()) {
      const entryFrozen = viewMode.value === 'audit' &&
        srSnapshot.value === 'entry' && Boolean(zone.activeAtEntry);
      const drawStart = entryFrozen
        ? Math.max(Number(zone.start), Number(payload.selectedTradeCandleTime || zone.start))
        : zone.start;
      const drawEnd = entryFrozen ? payload.visibleEnd : zone.end;
      const x1 = xForTime(drawStart,true), x2 = xForTime(drawEnd,false);
      const yHigh = candle.priceToCoordinate(Number(zone.high));
      const yLow = candle.priceToCoordinate(Number(zone.low));
      if ([x1,x2,yHigh,yLow].some(v => v == null || !Number.isFinite(Number(v)))) continue;

      const active = zoneActive(zone);
      const nearest = zoneNearest(zone);
      const focused = zoneMatchesFocus(zone);
      const baseAlpha = viewMode.value === 'audit'
        ? (focused ? .34 : nearest ? .23 : active ? .12 : .045)
        : (focused ? .26 : nearest ? .13 : active ? .07 : .035);
      const support = String(zone.structure) === 'support';
      const fill = support
        ? 'rgba(53,180,119,' + baseAlpha + ')'
        : 'rgba(220,90,90,' + baseAlpha + ')';
      const borderAlpha = Math.min(.85, baseAlpha + (focused ? .42 : .28));
      const border = support
        ? 'rgba(86,214,151,' + borderAlpha + ')'
        : 'rgba(238,120,120,' + borderAlpha + ')';

      const band = document.createElement('div');
      band.className = 'zone-band';
      band.style.left = Math.min(x1,x2) + 'px';
      band.style.width = Math.max(2,Math.abs(x2-x1)) + 'px';
      band.style.top = Math.min(yHigh,yLow) + 'px';
      band.style.height = Math.max(2,Math.abs(yLow-yHigh)) + 'px';
      band.style.background = fill;
      band.style.borderTop = (focused ? '2px' : '1px') + ' solid ' + border;
      band.style.borderBottom = (focused ? '2px' : '1px') + ' solid ' + border;
      zoneLayer.appendChild(band);

      if (nearest || focused) {
        const state = srSnapshot.value === 'entry' ? zone.stateAtEntry : zone.stateEnd;
        labels.push({
          top:(Number(yHigh)+Number(yLow))/2-10,
          structure:zone.structure,
          text:zone.name + (state ? ' · ' + shortState(state) : '') +
            (focused ? ' · FOCUSED' : ''),
        });
      }
    }
    labels.sort((a,b) => a.top-b.top);
    let lastTop = -999;
    for (const item of labels) {
      const top = Math.max(4,item.top <= lastTop + 20 ? lastTop + 22 : item.top);
      lastTop = top;
      const label = document.createElement('div');
      label.className = 'zone-label ' + item.structure;
      label.style.top = top + 'px';
      label.textContent = item.text;
      zoneLabelLayer.appendChild(label);
    }
  }

  function seriesMarkerSource() {
    const result = [...(payload?.markers || [])];
    if (viewMode.value === 'audit' && ['lifecycle','all'].includes(srDetails.value)) {
      const tfs = selectedTimeframes();
      result.push(...(payload.srEvents || []).filter(event => tfs.has(String(event.timeframe))));
    }
    if (inspectedTime && viewMode.value === 'audit') {
      result.push({
        time:inspectedTime, position:'belowBar', shape:'circle',
        text:'AUDIT', kind:'audit',
      });
    } else if (
      viewMode.value === 'audit' && srSnapshot.value === 'entry' &&
      payload?.selectedTradeCandleTime
    ) {
      result.push({
        time:payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime,
        position:'belowBar', shape:'circle',
        text:'S/R SNAPSHOT', kind:'sr-snapshot',
      });
    }
    return result.sort((a,b) => Number(a.time)-Number(b.time));
  }

  function renderChart(resetRange=true) {
    if (!payload || !window.LightweightCharts) return;
    const previousRange = (!resetRange && chart)
      ? chart.timeScale().getVisibleRange()
      : null;
    if (chart) chart.remove();
    zoneLayer.replaceChildren();
    zoneLabelLayer.replaceChildren();
    $('chart').replaceChildren();

    const LC = window.LightweightCharts;
    chart = LC.createChart($('chart'), {
      autoSize:true,
      attributionLogo:true,
      layout:{background:{type:'solid',color:'#0f1720'},textColor:'#b8c2cc'},
      grid:{vertLines:{color:'#1d2937'},horzLines:{color:'#1d2937'}},
      rightPriceScale:{borderColor:'#334155'},
      timeScale:{
        borderColor:'#334155',timeVisible:true,secondsVisible:false,rightOffset:10,
        shiftVisibleRangeOnNewBar:false,
      },
      crosshair:{mode:0},
      handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},
      handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true},
    });
    candle = chart.addSeries(LC.CandlestickSeries,{
      upColor:'#22a06b',downColor:'#d84a4a',borderVisible:false,
      wickUpColor:'#22a06b',wickDownColor:'#d84a4a',
    });
    candle.setData(payload.candles || []);

    const seriesStyles = {
      ema:{lineWidth:1,color:'#8fb4ff'},
      vwap:{lineWidth:1,color:'#d5a94b'},
      bb:{lineWidth:1,color:'#8a94a3',lineStyle:2},
      sr:{lineWidth:1,color:'#9da8b5',lineStyle:2},
    };
    if (viewMode.value !== 'audit') {
      for (const overlay of (payload.overlays || []).filter(overlayEnabled)) {
        const style = {...(seriesStyles[overlay.kind] || seriesStyles.sr)};
        const line = chart.addSeries(LC.LineSeries,{
          ...style,title:overlay.name,priceLineVisible:false,lastValueVisible:false,
          crosshairMarkerVisible:false,
        });
        line.setData(overlay.data || []);
      }
    }

    if (LC.createSeriesMarkers) {
      const markers = seriesMarkerSource().map(m => ({
        time:m.time,position:m.position,shape:m.shape,text:m.text,
        color:m.kind==='enter' ? '#6fd3a4'
          : m.kind==='exit' ? '#ffd166'
          : m.kind==='audit' ? '#d9b8ff'
          : m.kind==='sr-snapshot' ? '#9ec5ff'
          : m.kind==='sr-event' && m.event==='break' ? '#ff8e8e'
          : m.kind==='sr-event' && m.event==='held' ? '#7ee2ac'
          : m.kind==='sr-event' ? '#d8b36a'
          : '#9aa5b1',
      }));
      LC.createSeriesMarkers(candle,markers);
    }

    if (viewMode.value !== 'audit') {
      for (const line of payload.priceLines || []) {
        const color = line.kind==='entry' ? '#7db7ff' : line.kind==='stop' ? '#f08a8a' : '#79d39d';
        candle.createPriceLine({
          price:line.price,color,lineWidth:2,lineStyle:2,axisLabelVisible:true,title:line.title,
        });
      }
    }

    chart.subscribeClick(param => {
      if (!param || !param.time) return;
      showAt(param.time,param.seriesData.get(candle));
      inspectTime(param.time,true);
    });
    chart.subscribeCrosshairMove(param => {
      if (!param || !param.time || !param.seriesData.has(candle)) return;
      if (param.sourceEvent && param.sourceEvent.type === 'mousemove')
        showAt(param.time,param.seriesData.get(candle));
    });
    chart.timeScale().subscribeVisibleTimeRangeChange(() => drawZones());
    if (window.ResizeObserver) new ResizeObserver(() => drawZones()).observe(chartWrap);

    if (previousRange) {
      chart.timeScale().setVisibleRange(previousRange);
    } else if (resetRange && payload.visibleStart && payload.visibleEnd) {
      chart.timeScale().setVisibleRange({from:payload.visibleStart,to:payload.visibleEnd});
    } else {
      chart.timeScale().fitContent();
    }
    requestAnimationFrame(() => drawZones());
  }

  function showAt(time,bar) {
    const fact = (payload?.candleContext || {})[String(time)] || {};
    const parts = Object.entries(fact).map(([k,v]) => k + ': ' + v);
    const ohlc = bar
      ? 'O ' + fmt(bar.open) + '  H ' + fmt(bar.high) + '  L ' + fmt(bar.low) + '  C ' + fmt(bar.close)
      : '';
    readout.innerHTML = '<b>' + esc(stamp(time)) + '</b>' +
      (ohlc ? '<br>' + esc(ohlc) : '') +
      (parts.length ? '<div id="facts">' + parts.map(esc).join(' · ') + '</div>' : '');
  }

  async function loadPayload() {
    clearError();
    readout.textContent = 'Loading completed-run chart…';
    const trade = boot.trades.length ? currentTrade : '';
    try {
      const fullRun = windowSize.value === 'full';
      payload = await fetchJson(api('/api/payload',{
        trade_index:String(trade),
        chart_timeframe:chartTf.value || boot.run.strategyTimeframe,
        visible_candles:fullRun ? String(boot.defaultVisibleCandles) : windowSize.value,
        full_run:fullRun ? '1' : '0',
        show_rejections:showRejections.checked ? '1' : '0',
      }));
      renderTrade(payload.selectedTrade || {});
      updateRunBadge();
      renderChart(true);
      const referenceNote = payload.chartTimeframe !== payload.run.strategyTimeframe
        ? 'Reference candles: ' + String(payload.chartTimeframe).toUpperCase() +
          ' from current canonical cache; strategy evidence remains ' +
          String(payload.run.strategyTimeframe).toUpperCase() + '. '
        : '';
      readout.textContent = referenceNote + (payload.fullRun
        ? 'Full run loaded · ' + (payload.candles || []).length.toLocaleString() + ' candles. '
        : (payload.candles || []).length.toLocaleString() + ' candles loaded. ') +
        'Pan/zoom freely. Click aligned strategy candles for exact persisted rule and S/R evidence.';
      if (payload.selectedTradeCandleTime) {
        await inspectTime(payload.selectedTradeCandleTime,false);
        inspectedTime = Number(
          payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime
        );
      }
      updateTradeButtons();
    } catch (error) {
      showError(error.message);
    }
  }

  function updateTradeButtons() {
    $('prev-trade').disabled = currentTrade <= 0 || !boot.trades.length;
    $('next-trade').disabled = currentTrade >= boot.trades.length - 1 || !boot.trades.length;
    tradeSelect.value = String(currentTrade);
  }
  function setTrade(index) {
    if (!boot.trades.length) return;
    currentTrade = Math.max(0,Math.min(boot.trades.length-1,Number(index)));
    focusedZone = null;
    inspectedTime = null;
    loadPayload();
  }
  function clearZoneFocus() {
    focusedZone = null;
    renderChart(false);
    if (lastInspection?.sr) renderSr(lastInspection.sr);
  }
  function toggleInspector() {
    main.classList.toggle('inspector-collapsed');
    $('toggle-inspector').textContent =
      main.classList.contains('inspector-collapsed') ? 'Show inspector' : 'Hide inspector';
    setTimeout(() => { drawZones(); },50);
  }

  $('prev-trade').addEventListener('click',() => setTrade(currentTrade-1));
  $('next-trade').addEventListener('click',() => setTrade(currentTrade+1));
  tradeSelect.addEventListener('change',() => setTrade(Number(tradeSelect.value)));
  chartTf.addEventListener('change',() => {
    focusedZone = null;
    inspectedTime = null;
    updateRunBadge();
    loadPayload();
  });
  windowSize.addEventListener('change',loadPayload);
  showRejections.addEventListener('change',loadPayload);
  function centerSelectedTrade() {
    if (!chart || !payload?.selectedTradeCandleTime) return;
    const candles = payload.candles || [];
    if (!candles.length) return;
    const target = Number(
      payload.selectedTradeChartCandleTime || payload.selectedTradeCandleTime
    );
    let index = candles.findIndex(item => Number(item.time) >= target);
    if (index < 0) index = candles.length - 1;
    const radius = 120;
    const from = Number(candles[Math.max(0,index-radius)]?.time);
    const to = Number(candles[Math.min(candles.length-1,index+radius)]?.time);
    if (Number.isFinite(from) && Number.isFinite(to) && from < to)
      chart.timeScale().setVisibleRange({from,to});
  }
  $('center-trade').addEventListener('click',() => {
    if (payload?.fullRun) centerSelectedTrade();
    else if (chart && payload?.visibleStart && payload?.visibleEnd)
      chart.timeScale().setVisibleRange({from:payload.visibleStart,to:payload.visibleEnd});
  });
  $('fit-chart').addEventListener('click',() => chart?.timeScale().fitContent());
  $('toggle-inspector').addEventListener('click',toggleInspector);
  $('fullscreen').addEventListener('click',async() => {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen?.();
    else await document.exitFullscreen?.();
  });
  $('clear-zone').addEventListener('click',clearZoneFocus);

  document.querySelectorAll('[data-overlay]').forEach(box =>
    box.addEventListener('change',() => renderChart(false))
  );
  [viewMode,srTf,srSnapshot,srDetails,nearestOnly].forEach(control =>
    control.addEventListener('change',() => {
      if (focusedZone && !selectedTimeframes().has(String(focusedZone.timeframe)))
        focusedZone = null;
      renderChart(false);
      if (lastInspection?.sr) renderSr(lastInspection.sr);
    })
  );
  document.querySelectorAll('.tab').forEach(button =>
    button.addEventListener('click',() => activateInspectorTab(button.dataset.tab))
  );
  window.addEventListener('keydown',event => {
    if (event.target && ['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName)) return;
    if (event.key === 'Home') {
      event.preventDefault();
      $('center-trade').click();
    } else if (event.key.toLowerCase() === 'f') {
      chart?.timeScale().fitContent();
    } else if (event.key.toLowerCase() === 'i') {
      toggleInspector();
    } else if (event.key === 'Escape') {
      clearZoneFocus();
    }
  });

  if (!window.LightweightCharts) {
    showError('Chart library could not be loaded. Check internet access and reopen Strategy Visualizer.');
    return;
  }
  updateTradeButtons();
  loadPayload();
})();
</script>
</body>
</html>"""
    return (
        template.replace("__LIGHTWEIGHT_CHARTS_URL__", LIGHTWEIGHT_CHARTS_URL)
        .replace("__BOOTSTRAP__", encoded)
    )


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StrategyVisualizerBrowserServer:
    """Serve one CompletedRunVisualizer session on a random loopback port."""

    def __init__(self, model: CompletedRunVisualizer):
        self.model = model
        self.token = secrets.token_urlsafe(18)
        self._lock = Lock()
        self._server: _LoopbackHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("browser visualizer server is not running")
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}/session/{self.token}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CryptoStrategyLabVisualizer/1.0"

            def log_message(self, _format, *_args):
                return

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
                self._send(
                    int(status),
                    _json_bytes(value),
                    "application/json; charset=utf-8",
                )

            def do_GET(self):
                try:
                    parsed = urlsplit(self.path)
                    prefix = f"/session/{owner.token}"
                    if parsed.path in {prefix, prefix + "/", prefix + "/index.html"}:
                        body = build_browser_visualizer_html(
                            owner.model, owner.token
                        ).encode("utf-8")
                        self._send(
                            HTTPStatus.OK,
                            body,
                            "text/html; charset=utf-8",
                        )
                        return
                    if not parsed.path.startswith(prefix + "/api/"):
                        self._json(
                            {"error": "not found"},
                            HTTPStatus.NOT_FOUND,
                        )
                        return
                    query = parse_qs(parsed.query)
                    if parsed.path == prefix + "/api/payload":
                        trade_raw = (query.get("trade_index") or [""])[0]
                        trade_index = (
                            int(trade_raw)
                            if trade_raw not in {"", "none", "null"}
                            else None
                        )
                        visible = int(
                            (query.get("visible_candles") or [
                                str(BROWSER_DEFAULT_VISIBLE_CANDLES)
                            ])[0]
                        )
                        visible = max(60, min(MAX_VISIBLE_CANDLES, visible))
                        chart_timeframe = (
                            (query.get("chart_timeframe") or [""])[0].strip()
                            or None
                        )
                        full_run = (
                            (query.get("full_run") or ["0"])[0]
                            in {"1", "true", "yes", "on"}
                        )
                        show_rejections = (
                            (query.get("show_rejections") or ["0"])[0]
                            in {"1", "true", "yes", "on"}
                        )
                        with owner._lock:
                            result = owner.model.build_payload(
                                trade_index=trade_index,
                                visible_candles=visible,
                                show_rejections=show_rejections,
                                full_run=full_run,
                                chart_timeframe=chart_timeframe,
                            )
                        self._json(result)
                        return
                    if parsed.path == prefix + "/api/inspect":
                        raw = (query.get("timestamp") or [""])[0]
                        if not raw:
                            self._json(
                                {"error": "timestamp is required"},
                                HTTPStatus.BAD_REQUEST,
                            )
                            return
                        timestamp = datetime.fromtimestamp(
                            float(raw), tz=timezone.utc
                        )
                        with owner._lock:
                            result = {
                                "rule": owner.model.rule_inspector_at(timestamp),
                                "sr": owner.model.sr_inspector_at(timestamp),
                            }
                        self._json(result)
                        return
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                except (TypeError, ValueError) as exc:
                    self._json(
                        {"error": str(exc)},
                        HTTPStatus.BAD_REQUEST,
                    )
                except Exception as exc:  # pragma: no cover - defensive server boundary
                    self._json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

        self._server = _LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="strategy-visualizer-browser",
            daemon=True,
        )
        self._thread.start()
        return self.url

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


__all__ = [
    "BROWSER_DEFAULT_VISIBLE_CANDLES",
    "StrategyVisualizerBrowserServer",
    "build_browser_visualizer_html",
]
