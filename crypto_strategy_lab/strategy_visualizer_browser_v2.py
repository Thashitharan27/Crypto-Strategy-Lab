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
from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
from crypto_strategy_lab.visualizer_drawings import DRAWING_HELPERS
from crypto_strategy_lab.visualizer_structure import STRUCTURE_HELPERS
from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
from crypto_strategy_lab.photon_structure import selected as photon_selected
from crypto_strategy_lab.photon_trend import selected as photon_trading_selected
from crypto_strategy_lab.visualizer_workspace import WORKSPACE_HELPERS, WORKSPACE_STYLES
from crypto_strategy_lab.visualizer_review_report import build_review_report_html


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def build_browser_visualizer_v2_html(
    model: CompletedRunVisualizer,
    session_token: str,
) -> str:
    request = model.seed.request
    swing_strength = getattr(getattr(getattr(model.seed,"config",None),"execution",None),"sd_swing_strength",2)
    if not isinstance(swing_strength,int) or isinstance(swing_strength,bool) or swing_strength<1:
        swing_strength=2
    execution=getattr(getattr(model.seed,"config",None),"execution",None)
    try:
        manual_costs={
            "entryFee":float(execution.maker_fee if execution.use_maker_entry else execution.taker_fee),
            "exitFee":float(execution.taker_fee), "slippage":float(execution.slippage),
        }
    except (AttributeError,TypeError,ValueError):
        manual_costs=None
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
            "swingStrength": swing_strength,
            "manualCosts": manual_costs,
            "emaReversal": getattr(model, "_ema_source", lambda period: "close")(300) == "high",
            "mappingOnly": photon_selected(getattr(getattr(getattr(model.seed, "config", None), "strategy", None), "profiles", {})),
            "photonStructure": any(select(getattr(getattr(getattr(model.seed,"config",None),"strategy",None),"profiles",{})) for select in (photon_selected,photon_trading_selected)),
            "photonTrading": photon_trading_selected(getattr(getattr(getattr(model.seed,"config",None),"strategy",None),"profiles",{})),
        },
    }
    encoded = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    template = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CSL · Chart workspace</title>
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
#structure-layer{position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden}
#chart-wrap[style*="crosshair"] #structure-layer *{pointer-events:none!important}
#fvg-layer{position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden}
#sr-layer{position:absolute;inset:0;z-index:2;pointer-events:none;overflow:hidden}
.sr-zone{position:absolute;border-top:1px solid;border-bottom:1px solid;box-sizing:border-box}
#day-layer{position:absolute;inset:0;z-index:2;pointer-events:none;overflow:hidden}
.utc-day-line{position:absolute;top:0;border-left:1px dashed #8295ab88}
.utc-day-label{position:absolute;top:4px;font-size:11px;color:#b5c6d8;background:#101923dd;padding:3px 6px;border-radius:3px;white-space:nowrap}
#fvg-review{padding:8px 16px;background:#122a31;border-bottom:1px solid #2d5862;font-size:12px;line-height:1.6}
#fvg-review[hidden]{display:none}
.fvg-zone{position:absolute;background:#22d3ee35;border:2px solid #22d3ee}
.fvg-note{position:absolute;font-size:11px;background:#12313d;color:#b6f6ff;padding:2px 5px;white-space:nowrap}
.fvg-level{position:absolute;height:1px;border-top:1px dashed #eab308}
#workspace{display:flex;min-height:0}
#chart-wrap{flex:1;min-width:0}
#setup-panel{width:278px;flex-shrink:0;padding:18px;background:#111e2c;border-left:1px solid #344155;overflow:auto;font-size:13px}
#setup-panel[hidden]{display:none}
#setup-panel h3{margin:0 0 14px;font-size:17px}
.setup-check{padding:8px 0;border-bottom:1px solid #273747;line-height:1.5}
.setup-facts{color:#aac0d5;line-height:1.8;margin-top:16px}
.fvg-note{font-size:12px;font-weight:600;border-radius:4px;padding:4px 7px}
.fvg-band{position:absolute;border-top:1px dashed #8597a950}
.formation-candle{position:absolute;border:2px solid #e2e8f0;border-radius:3px;background:#e2e8f018}
.trade-label{font-size:12px;padding:4px 7px;line-height:1.2}
#review-setup[aria-pressed=true]{background:#195d76;border-color:#22d3ee}
@media(max-width:900px){#setup-panel{width:215px;padding:10px}}
#trade-box-layer{position:absolute;inset:0;z-index:5;pointer-events:none;overflow:hidden}
#trade-card{position:absolute;z-index:9;top:12px;right:86px;width:260px;max-width:calc(100% - 100px);max-height:calc(100% - 32px);overflow:auto;background:#101c29ed;border:1px solid #3a5065;border-radius:9px;box-shadow:0 4px 18px #0004;font:12px/1.5 system-ui,sans-serif;color:#c9d8e6}
#trade-card[hidden]{display:none}
#trade-card summary{cursor:pointer;padding:9px 12px;color:#e6edf3;font-weight:600}
.trade-card-body{padding:0 12px 10px}
.trade-card-controls{display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.trade-card-controls input{width:80px;background:#0c1420;color:#e6edf3;border:1px solid #475569;border-radius:4px;padding:4px}
.trade-card-controls label{display:flex;align-items:center;gap:6px}.trade-card-controls [hidden]{display:none}
#trade-card-values{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:8px 0}
#trade-card-values dt{color:#93a9bd}#trade-card-values dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.trade-card-note{font-size:10px;color:#93a9bd}.trade-card-positive{color:#6ee7b7}.trade-card-negative{color:#fda4af}
#drawing-layer{position:absolute;inset:0;z-index:6;pointer-events:none;overflow:hidden}
#drawing-tools{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:6px 10px;background:#121e2b;border-bottom:1px solid #334155}
#drawing-tools{flex-basis:100%}
#drawing-tools input{background:#0c1420;color:#e6edf3;border:1px solid #475569;border-radius:4px;padding:4px}
#drawing-status{font-size:12px;color:#b9d7f5}
#workspace{position:relative}
#drawing-rail{width:44px;flex-shrink:0;display:flex;flex-direction:column;gap:4px;padding:6px 3px;background:#111c29;border-right:1px solid #334155;overflow-y:auto}
#drawing-rail button{width:38px;min-height:34px;padding:5px;border-color:transparent;flex-shrink:0}
#drawing-rail button[aria-pressed=true]{color:#60a5fa;background:#203b58;border-color:#4689d0}
#drawing-rail svg{width:22px;height:22px;display:block;margin:auto;stroke:currentColor;fill:none;stroke-width:1.7}
#drawing-settings{position:absolute;left:52px;top:6px;z-index:15;width:270px;max-height:calc(100% - 16px);overflow:auto;background:#142233;border:1px solid #475569;border-radius:6px;box-shadow:0 6px 22px #0008}
#drawing-settings[hidden]{display:none}
#drawing-settings #drawing-tools{display:flex;flex-direction:column;align-items:stretch;margin:0;border:0}
#drawing-settings select,#drawing-settings input{max-width:100%;box-sizing:border-box}
#drawing-hint{position:absolute;z-index:8;top:8px;left:8px;background:#142233e8;color:#b9d7f5;border:1px solid #475569;border-radius:4px;padding:6px 10px;font-size:12px;pointer-events:none}
.fib-band{position:absolute;box-sizing:border-box;border-top:1px solid rgba(255,255,255,.18)}
.fib-level-label{position:absolute;transform:translateY(-50%);padding:2px 5px;border-radius:3px;font:10px/1.2 Segoe UI,Arial,sans-serif;font-weight:700;white-space:nowrap;color:#f8fafc;background:rgba(15,23,32,.90);border:1px solid rgba(148,163,184,.44);box-shadow:0 1px 3px rgba(0,0,0,.32)}
.fib-anchor{position:absolute;height:1px;transform-origin:0 50%;background:rgba(148,163,184,.65)}
.trade-rect{position:absolute;box-sizing:border-box;border-radius:2px}
.trade-rect.risk{background:rgba(219,68,68,.22);border:1px solid rgba(255,105,105,.9)}
.trade-rect.reward{background:rgba(38,166,91,.23);border:1px solid rgba(83,220,141,.9)}
.trade-rect.reward.current-profit{background:rgba(12,145,80,.48);border-color:#34d399}
.trade-rect.risk.current-loss{background:rgba(180,36,52,.48);border-color:#fb7185}
.trade-label{position:absolute;padding:2px 5px;border-radius:3px;font:11px/1.2 Segoe UI,Arial,sans-serif;white-space:nowrap}
.position-handle{position:absolute;pointer-events:auto;cursor:ns-resize;height:12px;z-index:9;border-top:2px dashed #fff;touch-action:none;background:rgba(255,255,255,.08)}
#manual-workflow-state{border:1px solid #456078;border-radius:4px;padding:3px 6px;color:#c5e5ff}
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
#replay-controls{flex-basis:100%;padding:12px;background:#17283b;border:1px solid #42607f;border-radius:7px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#replay-controls[hidden]{display:none}
#replay-notes{width:260px;max-width:100%;background:#0c1420;color:#e6edf3;border:1px solid #475569;border-radius:5px;padding:8px;font:inherit}
#replay-status{flex-basis:100%;font-size:13px;line-height:1.5;color:#c8e3f9}
.manual-plan{display:flex;align-items:center;gap:8px;flex-wrap:wrap;flex-basis:100%;padding-top:8px;border-top:1px solid #42607f}
.manual-plan input{width:125px;background:#0c1420;color:#e6edf3;border:1px solid #475569;border-radius:4px;padding:6px}
#manual-plan-status{flex-basis:100%;color:#b9d7f5;font-size:12px}
#replay-toggle[aria-pressed=true]{background:#255b91;border-color:#60a5fa}
#day-replay[aria-pressed=true]{background:#255b91;border-color:#60a5fa}
button:disabled{opacity:.45;cursor:default}
__WORKSPACE_STYLES__
body.mapping-only #trade-panel,body.mapping-only #open-trade-plan,
body.mapping-only #trade-panel-toggle,body.mapping-only #journal-panel-toggle,
body.mapping-only #position-tools-button,body.mapping-only #trade,
body.mapping-only label[for="trade"],body.mapping-only #center,
body.mapping-only #day-trade,body.mapping-only #manual-new-trade,
body.mapping-only label:has(#day-side),body.mapping-only #replay-toggle{display:none!important}
body.mapping-only #reviewbar{flex-wrap:wrap}
body.mapping-only #photon-status{flex-basis:100%;line-height:1.6;padding:6px 0}
body.mapping-only{overflow:auto}
body.mapping-only #app{grid-template-rows:auto auto minmax(300px,1fr) auto auto;grid-template-areas:'top' 'context' 'chart' 'playback' 'diagnostics';min-height:100%}
body.mapping-only #workspace{min-height:300px}
body.mapping-only #reviewbar{overflow:visible;white-space:normal}
body.mapping-only #reviewbar>*{max-width:100%;flex-shrink:1}
body.mapping-only #toolbar{flex-wrap:wrap}
body.structure-lines #day-layer{display:none}
#photon-context[hidden]{display:none}
#photon-context{flex-basis:100%;min-width:0}
#photon-context-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:#344155}
.photon-context-state{padding:9px 12px;background:#111e2c;min-width:0;line-height:1.5}
.photon-context-state strong,.photon-context-state small{display:block}
.photon-context-state small{color:#b3c3d5}
#photon-context details{padding:6px 0}
#photon-context summary{cursor:pointer}
#photon-context-chart{height:155px;min-width:0;cursor:crosshair}
#photon-context-chart svg{display:block;width:100%;height:155px}
#photon-event-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding-top:6px}
#photon-event-select{max-width:100%;min-width:0;flex:1}
#photon-event-detail{font-size:12px;line-height:1.6;padding:6px 0;color:#c5d4e6;white-space:normal}
#photon-value-controls,#photon-zone-filters{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
#photon-value-controls{padding-top:7px}
#photon-value-controls label,#photon-zone-filters label{display:flex;gap:5px;align-items:center}
#photon-zone-panel{border-top:1px solid #344155;margin-top:4px}
#photon-zone-select{width:100%;max-width:100%;margin-top:7px}
#photon-zone-detail,#photon-range-status{font-size:12px;line-height:1.6;color:#c5d4e6;white-space:normal}
body.mapping-only #replay-controls>strong,body.mapping-only #manual-workflow-state,
body.mapping-only #replay-controls>[data-replay-decision],body.mapping-only #replay-notes,
body.mapping-only #replay-controls>.manual-plan,body.mapping-only #replay-report,
body.mapping-only #replay-export{display:none!important}
@media(max-width:650px){#photon-context-strip{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
<script src="__LIGHTWEIGHT_CHARTS_URL__"></script>
</head>
<body>
<div id="app">
  <div id="toolbar">
    <strong class="brand">CSL <small>Chart workspace</small></strong>
    <span id="chart-symbol" class="symbol"></span>
    <label for="chart-timeframe">Chart timeframe</label>
    <select id="chart-timeframe" aria-label="Chart timeframe"></select>
    <label id="photon-view-label" for="photon-view" hidden>View</label>
    <select id="photon-view" aria-label="Structure display" hidden>
      <option value="CANDLES">Candles</option>
      <option value="LINES">Structure lines</option>
      <option value="BOTH">Candles + structure lines</option>
    </select>
    <label id="photon-labels-wrap" hidden><input id="photon-labels" type="checkbox"> Break levels</label>
    <label id="photon-developing-wrap" hidden><input id="photon-developing" type="checkbox"> Unconfirmed leg (dashed)</label>
    <button id="indicators-btn" aria-haspopup="dialog">ƒx Indicators <span id="indicator-count"></span></button>
    <button id="open-trade-plan" aria-controls="trade-panel" aria-pressed="false">Trade panel</button>
    <span class="toolbar-spacer"></span>
    <details id="chart-options"><summary>Chart settings ▾</summary><div class="chart-options-body">
    <label title="Confirmed chart-timeframe swings, sweeps, structure breaks, FVGs and midpoint; visual references, not entries"><input id="structure-guide" type="checkbox"> Structure guide</label>
    <button id="fit">Fit full run</button>
    <button id="reset-price">Reset price</button>
    <label title="Previous UTC day confirmed swing zones; visual reference only"><input id="sr-zones" type="checkbox" checked> Previous-day S/R</label>
    <select id="sr-width" aria-label="S/R zone width"><option value="1" selected>Narrow zones</option><option value="2">Normal zones</option><option value="4">Wide zones</option></select>
    <span id="sr-status" role="status" hidden></span>
    <label><input id="day-separators" type="checkbox" checked> UTC days</label>
    </div></details>
  </div>
  <div id="reviewbar">
    <label for="trade">Review trade</label><select id="trade"></select>
    <button id="center">Center selected</button>
    <button id="review-setup" aria-pressed="false" hidden>Review setup</button>
    <button id="replay-toggle" aria-pressed="false" disabled>Trade replay</button>
    <button id="day-replay" aria-pressed="false" disabled>Day replay</button>
    <button id="structure-review" disabled title="Review any day with market structure; enter trades only when you confirm manually">Structure review</button>
    <span id="day-navigation" hidden>
      <button id="previous-day">Previous day</button>
      <input id="replay-day" type="date" aria-label="Replay UTC day">
      <button id="next-day">Next day</button>
      <select id="day-trade" aria-label="Trades for this UTC day"></select><button id="manual-new-trade">New trade</button>
      <label>Direction <select id="day-side" aria-label="Manual day direction"><option>LONG</option><option>SHORT</option></select></label>
    </span>
    <div id="active-indicators" aria-label="Active indicators"></div>
    <span id="timeframe-note" class="muted" role="status"></span>
    <span id="photon-status" class="muted" role="status" style="display:block;max-width:100%;white-space:normal"></span>
    <section id="photon-context" aria-label="Multi-timeframe market narrative" hidden>
      <div id="photon-context-strip" aria-live="polite"></div>
      <div id="photon-value-controls">
        <label><input id="photon-range-show" type="checkbox" checked> Premium / discount</label>
        <select id="photon-range-timeframe" aria-label="Premium discount range timeframe"><option value="4h">4H range</option><option value="15m">15m range</option><option value="1d">Daily range</option></select>
        <span id="photon-range-status" role="status"></span>
        <span id="photon-zone-summary" role="status"></span>
      </div>
      <details id="photon-zone-panel"><summary>Supply / demand zones · layers and inspection</summary>
        <div id="photon-zone-filters">
          <label><input id="photon-zones-show" type="checkbox" checked> Show zones</label>
          <label><input id="photon-zone-1d" type="checkbox" checked> Daily</label>
          <label><input id="photon-zone-4h" type="checkbox" checked> 4H</label>
          <label><input id="photon-zone-15m" type="checkbox" checked> 15m</label>
          <label><input id="photon-zone-history" type="checkbox"> Include ended zones</label>
        </div>
        <select id="photon-zone-select" aria-label="Supply demand zone to inspect"><option value="">Choose a supply / demand zone</option></select>
        <button id="photon-zone-focus" disabled>Focus selected zone</button>
        <div id="photon-zone-detail" role="status"></div>
      </details>
      <details id="photon-context-details"><summary>Weekly / daily context · shared replay clock</summary>
        <div id="photon-context-chart" aria-label="Weekly and daily structure overview"></div>
      </details>
      <div id="photon-event-row"><label for="photon-event-select">Inspect event</label>
        <select id="photon-event-timeframe" aria-label="Event timeframe"><option value="15m">15m</option><option value="4h">4H</option><option value="1d">Daily</option><option value="1w">Weekly</option></select>
        <select id="photon-event-select" aria-label="Known structure events"></select>
        <button id="photon-next-event" disabled>Next structure event</button></div>
      <div id="photon-event-detail" role="status"></div>
    </section>
    <div id="replay-controls" hidden>
      <strong>Your judgement:</strong>
      <span id="manual-workflow-state" role="status"></span><button data-replay-decision="Wait">Wait</button><button data-replay-decision="Skip">Skip</button><button data-replay-decision="Unsure">Unsure</button>
      <input id="replay-notes" aria-label="Pre-entry judgement note" placeholder="Why would you take or skip it?">
      <button id="replay-step">Next candle</button><button id="replay-play">Play</button>
      <label><input id="replay-follow" type="checkbox" checked> Follow replay</label>
      <select id="replay-speed" aria-label="Replay speed"><option value="1500">Slow</option><option value="750" selected>Normal</option><option value="300">Fast</option></select>
      <button id="replay-reveal">Reveal result</button><button id="replay-restart">Restart at entry</button>
      <button id="replay-export">Export reviews</button>
      <button id="replay-report">Review report</button>
      <div class="manual-plan" role="group" aria-label="Manual trade plan">
        <strong>My plan</strong>
        <button id="manual-show-box" hidden>Restore trade box</button>
        <label>Entry <input id="manual-entry" type="number" step="any" min="0" aria-label="Manual entry price"></label><button data-pick-level="entry">Pick entry</button>
        <label>SL <input id="manual-stop" type="number" step="any" min="0" aria-label="Manual stop-loss price"></label><button data-pick-level="stop">Pick SL</button>
        <label>TP <input id="manual-target" type="number" step="any" min="0" aria-label="Manual take-profit price"></label><button data-pick-level="target">Pick TP</button>
        <button id="manual-move">Move box</button>
        <button id="manual-current">Enter at current candle</button><span id="manual-time"></span>
        <button id="manual-confirm">Confirm manual entry</button>
        <button id="manual-be">SL to break-even</button>
        <button id="manual-cover-costs">Cover costs + BE</button>
        <button id="manual-close">Close manual position</button><button id="manual-pick-exit">Pick exit</button>
        <span id="manual-exit-status" role="status"></span>
        <button id="manual-save">Save plan</button><button id="manual-reset">Use auto levels</button>
        <span id="manual-plan-status" role="status"></span>
        <details id="manual-history" hidden><summary>Saved plan changes</summary><div id="manual-history-content"></div></details>
      </div>
      <span id="replay-status" role="status"></span>
    </div>
    <div id="drawing-tools" role="group" aria-label="Chart drawing tools">
      <strong>Draw</strong><select id="drawing-tool" aria-label="Drawing tool">
        <option value="cursor">Cursor</option><option value="trend">Trend line</option><option value="ray">Ray</option>
        <option value="hline">Horizontal line</option><option value="vline">Vertical line</option><option value="rect">Rectangle</option>
        <option value="fib">Fib retracement</option><option value="measure">Measure</option><option value="text">Text note</option>
      </select>
      <input id="drawing-color" type="color" value="#60a5fa" aria-label="Drawing color">
      <input id="drawing-text" aria-label="Drawing note" placeholder="Text note" size="12" maxlength="200">
      <select id="drawing-selected" aria-label="Saved drawing"><option value="">Saved drawings</option></select>
      <button id="drawing-edit">Redraw selected</button><button id="drawing-delete">Delete selected</button>
      <button id="drawing-undo">Undo drawing</button><button id="drawing-clear">Clear drawings</button><button id="drawing-export">Export drawings</button>
      <span id="drawing-status" role="status"></span>
    </div>
  </div>
  <details id="diagnostics"><summary>Trade diagnostics (expand)</summary><div id="diag">Loading…</div></details>
  <div id="workspace"><nav id="drawing-rail" aria-label="Drawing toolbar"></nav>
    <aside id="position-tools-menu" aria-label="Position drawing tools" hidden>
      <strong>Position tools</strong>
      <button id="draw-long-position"><span class="position-long-icon">↗</span> Long Position</button>
      <button id="draw-short-position"><span class="position-short-icon">↘</span> Short Position</button>
      <small>Click entry, then drag SL / TP. Confirm entry to open the replay position.</small>
    </aside>
    <aside id="drawing-settings" aria-label="Drawing settings" hidden><button id="drawing-settings-close" aria-label="Close drawing settings">Close ✕</button></aside>
    <div id="chart-wrap" tabindex="0" aria-label="Chart workspace">
    <div id="drawing-hint" role="status" hidden></div>
    <div id="position-placement-hint" role="status" hidden></div>
    <div id="chart"></div>
    <div id="day-layer"></div>
    <div id="sr-layer"></div>
    <div id="fib-layer"></div>
    <div id="structure-layer" aria-label="Market structure references"></div>
    <div id="fvg-layer"></div>
    <div id="trade-box-layer"></div>
    <details id="trade-card" aria-label="Manual trade estimate" open hidden>
      <summary id="trade-card-title">Trade estimate</summary>
      <div class="trade-card-body">
        <div class="trade-card-controls">
          <select id="trade-card-risk-mode" aria-label="Risk sizing method"><option value="amount">Fixed risk</option><option value="percent">% of equity</option></select><button id="trade-card-corner" title="Open trade plan" aria-label="Open trade plan">Plan</button>
          <label id="trade-card-amount-field"><span id="trade-card-risk-label">Risk (quote)</span><input id="trade-card-risk" type="number" min="0.01" step="any" value="10" aria-label="Risk amount in quote currency"></label>
          <label id="trade-card-percent-field" hidden>Risk % <input id="trade-card-percent" type="number" min="0.01" max="100" step="any" value="1" aria-label="Risk percentage of equity"></label>
          <label id="trade-card-equity-field" hidden><span id="trade-card-equity-label">Equity (quote)</span><input id="trade-card-equity" type="number" min="0.01" step="any" placeholder="Your equity" aria-label="Account equity in quote currency"></label>
        </div>
        <dl id="trade-card-values"></dl>
        <div id="trade-card-risk-note" class="trade-card-note"></div>
        <div class="trade-card-note">Sizing estimate only. Uses the initial stop after entry; excludes funding, rounding and stop gaps.</div>
      </div>
    </details>
    <svg id="drawing-layer" width="100%" height="100%" aria-label="Chart drawings"></svg>
  </div><aside id="setup-panel" aria-label="FVG setup explanation" hidden></aside>
    <aside id="trade-panel" aria-label="Trade workspace" hidden>
      <header class="workspace-panel-header"><strong>Trade workspace</strong><button id="close-trade-panel" aria-label="Close trade panel">×</button></header>
      <nav class="workspace-tabs" role="tablist" aria-label="Trade workspace sections">
        <button id="workspace-tab-plan" role="tab" aria-controls="plan-tab" aria-selected="true">Plan</button><button id="workspace-tab-risk" role="tab" aria-controls="risk-tab" aria-selected="false">Risk</button><button id="workspace-tab-journal" role="tab" aria-controls="journal-tab" aria-selected="false">Journal</button>
      </nav>
      <section id="plan-tab" class="workspace-tab" role="tabpanel" aria-labelledby="workspace-tab-plan"><div id="plan-content" hidden><details id="position-management" open><summary>Manage position</summary><div id="position-actions"></div></details><details id="plan-details"><summary>Plan details</summary><div id="plan-details-content"></div></details></div><p id="plan-empty" class="workspace-empty">Open Day replay or Trade replay to place and manage a trade.</p></section>
      <section id="risk-tab" class="workspace-tab" role="tabpanel" aria-labelledby="workspace-tab-risk" hidden><div id="risk-content" hidden></div><p id="risk-empty" class="workspace-empty">Open a replay to choose your risk and see fees and expected returns.</p></section>
      <section id="journal-tab" class="workspace-tab" role="tabpanel" aria-labelledby="workspace-tab-journal" hidden><div id="journal-content" hidden></div><p id="journal-empty" class="workspace-empty">Open a replay to record decisions and review results.</p></section>
    </aside>
    <nav id="workspace-rail" aria-label="Workspace panels">
      <button id="trade-panel-toggle" title="Trade plan and risk" aria-label="Trade plan and risk" aria-controls="trade-panel" aria-pressed="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4zM4 10h16M10 10v9"/></svg></button>
      <button id="journal-panel-toggle" title="Review journal" aria-label="Review journal" aria-controls="trade-panel" aria-pressed="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h13v18H6zM3 7h5M3 12h5M3 17h5M11 8h5M11 12h5M11 16h4"/></svg></button>
      <button id="diagnostics-toggle" title="Chart diagnostics" aria-label="Chart diagnostics" aria-controls="diagnostics" aria-pressed="false"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 10v7M12 6v1"/></svg></button>
    </nav>
  </div>
  <span id="workspace-clock" aria-live="off"></span>
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
        <label><input type="checkbox" class="ema-period" value="300"> EMA 300</label>
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
  __REPLAY_HELPERS__
  __DRAWING_HELPERS__
  __STRUCTURE_HELPERS__
  __PHOTON_HELPERS__
  __WORKSPACE_HELPERS__
  const boot = __BOOTSTRAP__;
  const $ = id => document.getElementById(id);
  $('chart-symbol').textContent = boot.run.symbol;
  const indicatorDialog = $('indicator-dialog');
  const indicatorInputs = [...document.querySelectorAll('.ema-period, .rsi-line, #show-rsi')];
  if(boot.run.mappingOnly) {
    document.body.classList.add('mapping-only');
    for(const input of indicatorInputs)input.checked=false;
    $('sr-zones').checked=false;
    $('structure-review').textContent='Review structure';
    $('day-replay').textContent='Structure replay';
    $('structure-review').title='Map completed candles only; no trade entries';
    $('manual-confirm').disabled=true;
    $('manual-confirm').hidden=true;
  }
  if(boot.run.photonStructure) {
    $('photon-view').hidden=false;
    $('photon-view-label').hidden=false;
    $('photon-view').value=boot.run.mappingOnly?'LINES':'BOTH';
    $('photon-labels-wrap').hidden=false;
    $('photon-developing-wrap').hidden=false;
    $('photon-context').hidden=false;
    $('photon-labels').checked=true;
    $('photon-developing').checked=true;
  }
  function applyPhotonDisplay() {
    if(!boot.run.photonStructure || !candles || !chart)return;
    const linesOnly=$('photon-view').value==='LINES';
    document.body.classList.toggle('structure-lines',linesOnly);
    candles.applyOptions({upColor:linesOnly?'transparent':'#089981',downColor:linesOnly?'transparent':'#f23645',
      wickUpColor:linesOnly?'transparent':'#089981',wickDownColor:linesOnly?'transparent':'#f23645',
      priceLineVisible:!linesOnly,lastValueVisible:!linesOnly});
    chart.applyOptions({layout:{background:{type:'solid',color:linesOnly?'#08090c':'#131722'}},
      timeScale:{minBarSpacing:linesOnly?.05:.5},
      grid:{vertLines:{visible:!linesOnly},horzLines:{visible:!linesOnly}}});
  }
  $('photon-view').addEventListener('change',()=>{
    $('structure-guide').checked=true;
    applyPhotonDisplay();
    if(chart && $('photon-view').value==='LINES') {
      defaultPriceRange=null;priceZoomFactor=1;pricePanOffset=0;
      chart.timeScale().fitContent();chart.priceScale('right').applyOptions({autoScale:true});
    }
    redrawOverlays();
  });
  $('photon-labels').addEventListener('change',redrawOverlays);
  $('photon-developing').addEventListener('change',redrawOverlays);
  for(const id of ['photon-range-show','photon-range-timeframe','photon-zones-show','photon-zone-1d','photon-zone-4h','photon-zone-15m','photon-zone-history','photon-zone-select'])$(id).addEventListener('change',redrawOverlays);
  $('photon-zone-panel').addEventListener('toggle',redrawOverlays);
  $('photon-zone-focus').addEventListener('click',()=>{
    const market=replayChartSource || marketPayload || sourcePayload;
    const cutoff=replayActive?replayCutoff:(market?.candles?.at(-1)?.time || 0)+chartInterval();
    const selected=Object.values(market?.photonMapping?.timeframes || {}).flatMap(g=>cslPhotonZoneView(g,cutoff)).find(z=>z.id===$('photon-zone-select').value);
    if(!selected||!chart||!candles)return;
    if(selected.endedAt&&selected.endedAt>=market.candles[0].time) {
      const step=market.photonMapping.timeframes[selected.timeframe].interval;
      chart.timeScale().setVisibleRange({from:Math.max(market.candles[0].time,selected.originTime-2*step),to:Math.min(cutoff,selected.endedAt+2*step)});
    }
    const visible=chart.timeScale().getVisibleRange();let low=selected.lower,high=selected.upper;
    for(const bar of market.candles || [])if(bar.time+chartInterval()<=cutoff&&bar.time>=Number(visible?.from ?? -Infinity)&&bar.time<=Number(visible?.to ?? Infinity)) {
      low=Math.min(low,bar.low);high=Math.max(high,bar.high);
    }
    const pad=Math.max((high-low)*.08,Math.abs(high)*.001);
    defaultPriceRange={minValue:low-pad,maxValue:high+pad};priceZoomFactor=1;pricePanOffset=0;
    chart.priceScale('right').applyOptions({autoScale:false});
    requestAnimationFrame(()=>{chart.priceScale('right').applyOptions({autoScale:true});candles.applyOptions({});redrawOverlays();});
  });
  $('photon-event-select').addEventListener('change',()=>{
    $('photon-event-select').dataset.pinned='true';
    const market=replayChartSource || marketPayload || sourcePayload,tf=$('photon-event-timeframe').value,guide=market?.photonMapping?.timeframes[tf];
    const event=guide?.events.find(e=>tf+':'+e.availableAt+':'+e.kind===$('photon-event-select').value);
    const cutoff=replayActive?replayCutoff:(market?.candles?.at(-1)?.time || 0)+chartInterval();
    if(event&&['4h','15m'].includes(tf)&&event.time>=market.candles[0].time&&event.availableAt<=cutoff) {
      chart.timeScale().setVisibleRange({from:Math.max(market.candles[0].time,event.time-12*guide.interval),to:Math.min(cutoff,event.time+12*guide.interval)});
    }
    redrawOverlays();
  });
  $('photon-event-timeframe').addEventListener('change',()=>{$('photon-event-select').dataset.pinned='false';redrawOverlays();});
  $('photon-context-details').addEventListener('toggle',redrawOverlays);
  $('photon-next-event').addEventListener('click',()=>{
    if(!boot.run.photonStructure || !replayActive || replayBusy || replayRevealed)return;
    const market=replayChartSource || marketPayload || sourcePayload;
    const end=replayEnd();
    const next=cslPhotonNextEvent(market?.photonMapping,replayCutoff,end);
    if(!next)return;
    stopReplay();replayCutoff=next;replayAdvanced=true;refreshReplay();
  });
  if (boot.run.emaReversal) {
    for (const input of indicatorInputs) input.checked=input.classList.contains('ema-period') && ['100','300'].includes(input.value);
  }
  function indicatorName(input) {
    if (input.classList.contains('ema-period')) return 'EMA ' + input.value + (boot.run.emaReversal && input.value==='100' ? ' (low)' : boot.run.emaReversal && input.value==='300' ? ' (high)' : '');
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
  const workspacePanels=cslOrganizeWorkspace($);
  const fibLayer = $('fib-layer');
  const tradeBoxLayer = $('trade-box-layer');
  const fvgLayer = $('fvg-layer');
  const fvgReview = document.createElement('div');
  fvgReview.id = 'fvg-review';
  fvgReview.hidden = true;
  $('journal-content').appendChild(fvgReview);
  fvgReview.style.flexBasis = '100%';
  let payload = null;
  let sourcePayload = null;
  let marketPayload = null;
  let replayChartSource = null;
  const manualMarkets=new Map(),manualMarketLoads=new Set();
  let dayMode = false;
  let manualDayTradeKey=null;
  let replayDay = null;
  let replayActive = false;
  let replayCutoff = 0;
  let replayEntryTime = 0;
  let replayInterval = 900;
  let replayAdvanced = false;
  let replayRevealed = false;
  let replayOutcomeVisible = false;
  let replayTimer = null;
  let replayBusy = false;
  let manualPlanDraft = null;
  let manualPick = null;
  let manualEntryTime = null;
  let manualEntryInterval=null,manualEntryTimeframe=null;
  let manualEntryMessage = '';
  let reviewRecords = [];
  let reviewStorageAvailable = true;
  const normalViewsSeen = new Set();
  const reviewStorageKey='csl-replay-reviews-v1';
  try { const saved=JSON.parse(localStorage.getItem(reviewStorageKey)||'[]'); if(Array.isArray(saved)) reviewRecords=saved; } catch { reviewStorageAvailable=false; }
  let reviewMode = false;
  let currentTimeframe = boot.run.timeframe;
  let loadGeneration = 0;
  const timeframeSelect = $('chart-timeframe');
  timeframeSelect.add(new Option(currentTimeframe + ' (strategy)', currentTimeframe));
  let currentTrade = 0;
  let chart = null;
  let chartResizeObserver = null;
  let candles = null;
  let replaySeries = [];
  let trendEmaLines = [];
  let rsiSeries = null;
  let rsiZoomFactor = 1.0;
  let rsiCenter = 50;
  let priceZoomFactor = 1.0;
  let pricePanOffset = 0.0;
  let verticalPan = null;
  let defaultPriceRange = null;
  const drawingKey='csl-drawings-v1:'+boot.run.runId+':'+boot.run.symbol;
  let drawings=[],drawingUndo=[],drawingPoints=[],drawingHover=null,drawingEditId=null;
  let selectedChartObject=null;
  let drawingStorageOk=true;
  $('drawing-settings').appendChild($('drawing-tools'));
  const drawingIcons={cursor:'M5 3l14 8-7 2-3 7z',trend:'M3 20L21 4',ray:'M4 20L21 3M4 17v3h3',hline:'M2 12h20',vline:'M12 2v20',rect:'M4 5h16v14H4z',fib:'M3 4h18M3 9h18M3 14h18M3 20h18',measure:'M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4',text:'M4 5h16M12 5v15M8 20h8'};
  for(const option of $('drawing-tool').options){
    const button=document.createElement('button');button.type='button';button.dataset.drawingTool=option.value;button.title=option.text;button.setAttribute('aria-label',option.text);
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',drawingIcons[option.value]);svg.appendChild(path);button.appendChild(svg);
    button.addEventListener('click',()=>{$('drawing-tool').value=option.value;$('drawing-tool').dispatchEvent(new Event('change'));});$('drawing-rail').appendChild(button);
  }
  const settingsButton=document.createElement('button');settingsButton.textContent='⚙';settingsButton.title='Drawing settings';settingsButton.setAttribute('aria-label','Drawing settings');settingsButton.addEventListener('click',()=>{$('drawing-settings').hidden=!$('drawing-settings').hidden;});$('drawing-rail').appendChild(settingsButton);
  const positionToolsButton=document.createElement('button');positionToolsButton.id='position-tools-button';positionToolsButton.title='Position tools · Long / Short';positionToolsButton.setAttribute('aria-label','Long and Short Position tools');positionToolsButton.setAttribute('aria-controls','position-tools-menu');positionToolsButton.setAttribute('aria-expanded','false');
  positionToolsButton.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3h16v18H4zM4 12h16M8 8l4-3 4 3M12 5v5M8 16l4 3 4-3M12 14v5"/></svg>';
  $('drawing-rail').insertBefore(positionToolsButton,$('drawing-rail').querySelector('[data-drawing-tool="measure"]'));
  positionToolsButton.addEventListener('click',()=>{const menu=$('position-tools-menu');menu.style.top=Math.max(8,Math.min(positionToolsButton.offsetTop,$('workspace').clientHeight-190))+'px';menu.hidden=!menu.hidden;positionToolsButton.setAttribute('aria-expanded',String(!menu.hidden));});
  document.addEventListener('pointerdown',event=>{if(!$('position-tools-menu').contains(event.target) && !positionToolsButton.contains(event.target)){$('position-tools-menu').hidden=true;positionToolsButton.setAttribute('aria-expanded','false');}});
  function beginPositionTool(side) {
    selectedChartObject=null;$('drawing-selected').value='';
    $('position-tools-menu').hidden=true;positionToolsButton.setAttribute('aria-expanded','false');
    if(!replayActive || !dayMode)$('day-replay').click();
    if(currentReview()?.manualExit && !replayRevealed)$('manual-new-trade').click();
    if(!dayMode || !replayActive || manualPlanLocked()) {
      workspacePanels.show('plan');$('position-placement-hint').hidden=false;$('position-placement-hint').textContent='Close the open position, or restart a revealed replay, before drawing another trade.';return;
    }
    stopReplay();$('drawing-tool').value='cursor';drawingPoints=[];drawingHover=null;drawingControls();
    if($('day-side').value!==side){$('day-side').value=side;$('day-side').dispatchEvent(new Event('change'));}
    ensureReview().positionBoxPlaced=false;ensureReview().positionBoxHidden=false;drawTradeBox();
    manualPick='position';chartWrap.style.cursor='crosshair';positionToolsButton.setAttribute('aria-pressed','true');
    $('position-placement-hint').hidden=false;$('position-placement-hint').textContent=side+' position · Click entry on a closed candle · Drag SL / TP after placing · Esc to cancel';
  }
  $('draw-long-position').addEventListener('click',()=>beginPositionTool('LONG'));
  $('draw-short-position').addEventListener('click',()=>beginPositionTool('SHORT'));
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){manualPick=null;$('position-placement-hint').hidden=true;$('position-tools-menu').hidden=true;positionToolsButton.setAttribute('aria-pressed','false');positionToolsButton.setAttribute('aria-expanded','false');chartWrap.style.cursor='';}});
  const undoButton=document.createElement('button');undoButton.textContent='↶';undoButton.title='Undo drawing';undoButton.setAttribute('aria-label','Undo last drawing');undoButton.addEventListener('click',()=>$('drawing-undo').click());$('drawing-rail').appendChild(undoButton);
  $('drawing-settings-close').addEventListener('click',()=>{$('drawing-settings').hidden=true;});
  try {const saved=JSON.parse(localStorage.getItem(drawingKey)||'[]');if(Array.isArray(saved))drawings=saved.filter(item=>item && Array.isArray(item.points) && item.points.length && item.points.every(p=>Number.isFinite(p.time) && Number.isFinite(p.price) && p.price>0));}catch{drawingStorageOk=false;}
  function drawingControls() {
    const selected=selectedChartObject?.type==='drawing'?selectedChartObject.id:$('drawing-selected').value;
    $('drawing-selected').replaceChildren(new Option('Saved drawings ('+drawings.length+')',''));
    drawings.forEach((item,index)=>$('drawing-selected').add(new Option((index+1)+'. '+item.tool+(item.text?' · '+item.text:''),item.id)));
    $('drawing-selected').value=selected;
    $('drawing-delete').disabled=!$('drawing-selected').value;$('drawing-edit').disabled=!$('drawing-selected').value;
    $('drawing-undo').disabled=!drawingUndo.length;
    $('drawing-status').textContent=($('drawing-tool').value==='cursor'?'Drawings saved in this browser.':drawingPoints.length?'Click the second anchor.':'Click a price-chart anchor.')+(drawingStorageOk?'':' Storage unavailable; export to keep drawings.');
    for(const button of document.querySelectorAll('[data-drawing-tool]'))button.setAttribute('aria-pressed',String(button.dataset.drawingTool===$('drawing-tool').value));
    $('drawing-hint').hidden=$('drawing-tool').value==='cursor';
    $('drawing-hint').textContent=$('drawing-tool').selectedOptions[0].text+' · '+(drawingPoints.length?'Click second anchor · Esc to cancel':'Click chart to place · Esc to cancel');
    undoButton.disabled=!drawingUndo.length;
  }
  function saveDrawings(next) {
    drawingUndo.push(drawings);if(drawingUndo.length>30)drawingUndo.shift();drawings=next;
    try{localStorage.setItem(drawingKey,JSON.stringify(drawings));}catch{drawingStorageOk=false;}
    drawingControls();drawUserDrawings();
  }
  function drawingPoint(event) {
    if(!event.point || event.point.y<0 || event.point.y>chart.panes()[0].getHeight())return null;
    const price=candles.coordinateToPrice(event.point.y),bars=payload?.candles || [];
    const logical=chart.timeScale().coordinateToLogical(event.point.x);
    const stepMatch=String(currentTimeframe).match(/^([0-9]+)([mhdw])$/);
    const step=stepMatch?Number(stepMatch[1])*({m:60,h:3600,d:86400,w:604800}[stepMatch[2]]):900;
    const index=Math.round(logical ?? 0);
    const time=event.time!=null?Number(event.time):bars[index]?.time ?? (bars.length?bars.at(-1).time+(index-bars.length+1)*step:NaN);
    return Number.isFinite(price) && price>0 && Number.isFinite(time)?{time,price}:null;
  }
  function drawingClick(event) {
    const tool=$('drawing-tool').value;if(tool==='cursor')return false;
    const point=drawingPoint(event);if(!point)return true;
    drawingPoints.push(point);
    if(drawingPoints.length<(['hline','vline','text'].includes(tool)?1:2)){drawingControls();return true;}
    const item={id:drawingEditId || String(Date.now())+'-'+Math.random().toString(36).slice(2),tool,points:drawingPoints,color:$('drawing-color').value,text:$('drawing-text').value.slice(0,200),recordedAt:new Date().toISOString(),replayTime:replayActive?replayCutoff:null};
    selectedChartObject={type:'drawing',id:item.id};
    saveDrawings(drawingEditId?drawings.map(old=>old.id===drawingEditId?item:old):[...drawings,item]);
    drawingPoints=[];drawingHover=null;drawingEditId=null;$('drawing-tool').value='cursor';chartWrap.style.cursor='';drawingControls();drawUserDrawings();return true;
  }
  function drawUserDrawings() {
    const layer=$('drawing-layer');layer.replaceChildren();if(!chart || !candles)return;
    const bars=payload?.candles || [],width=chartWrap.clientWidth-76,height=chart.panes()[0].getHeight();layer.style.height=height+'px';
    const project=point=>{
      let x=chart.timeScale().timeToCoordinate(point.time);
      if(x==null && bars.length){
        let lo=0,hi=bars.length;while(lo<hi){const mid=(lo+hi)>>1;if(bars[mid].time<point.time)lo=mid+1;else hi=mid;}
        const a=Math.max(0,Math.min(bars.length-2,lo-1)),step=bars[a+1]?.time-bars[a]?.time || replayInterval;
        x=chart.timeScale().logicalToCoordinate(a+(point.time-bars[a].time)/step);
      }
      const y=candles.priceToCoordinate(point.price);return x==null || y==null?null:{x,y};
    };
    const visible=drawings.filter(item=>!replayActive || item.replayTime==null || item.replayTime<=replayCutoff);
    if(drawingPoints.length && drawingHover)visible.push({tool:$('drawing-tool').value,points:[drawingPoints[0],drawingHover],color:$('drawing-color').value});
    for(const item of visible){
      const group=document.createElementNS('http://www.w3.org/2000/svg','g');
      if(item.id){group.dataset.drawingId=item.id;group.setAttribute('class',selectedChartObject?.type==='drawing' && selectedChartObject.id===item.id?'user-drawing selected':'user-drawing');}
      const selectable=item.id && $('drawing-tool').value==='cursor' && !manualPick;
      group.style.cursor=selectable?'pointer':'';
      group.addEventListener('click',event=>{if(!selectable)return;event.stopPropagation();chartWrap.focus({preventScroll:true});selectedChartObject={type:'drawing',id:item.id};$('drawing-selected').value=item.id;drawingControls();drawUserDrawings();drawTradeBox();});
      for(const shape of cslDrawingShapes(item,project,width,height)){
        if(selectable && shape.tag==='line'){
          const hit=document.createElementNS(group.namespaceURI,'line');for(const [key,value]of Object.entries(shape.attrs))hit.setAttribute(key,String(value));hit.setAttribute('stroke','transparent');hit.setAttribute('stroke-width','12');hit.style.pointerEvents='stroke';group.appendChild(hit);
        }
        const node=document.createElementNS('http://www.w3.org/2000/svg',shape.tag);
        for(const [key,value]of Object.entries(shape.attrs))node.setAttribute(key,String(value));
        node.style.pointerEvents=selectable?'visiblePainted':'none';
        if(shape.text!=null)node.textContent=shape.text;group.appendChild(node);
      }
      layer.appendChild(group);
    }
  }
  $('drawing-tool').addEventListener('change',()=>{stopReplay();selectedChartObject=null;$('drawing-selected').value='';manualPick=null;drawingPoints=[];drawingHover=null;drawingEditId=null;chartWrap.style.cursor=$('drawing-tool').value==='cursor'?'':'crosshair';drawingControls();drawUserDrawings();});
  $('drawing-selected').addEventListener('change',()=>{selectedChartObject=$('drawing-selected').value?{type:'drawing',id:$('drawing-selected').value}:null;drawingControls();drawUserDrawings();drawTradeBox();});
  function deleteSelectedChartObject() {
    if(selectedChartObject?.type==='drawing'){
      const id=selectedChartObject.id;if(!drawings.some(item=>item.id===id))return false;
      selectedChartObject=null;$('drawing-selected').value='';saveDrawings(drawings.filter(item=>item.id!==id));return true;
    }
    if(selectedChartObject?.type==='position' && replayActive && selectedChartObject.key===replayKey() && currentReview()){
      currentReview().positionBoxHidden=true;selectedChartObject=null;manualPick=null;chartWrap.style.cursor='';saveReviews();refreshManualPlan();resetPriceScale();redrawOverlays();return true;
    }
    return false;
  }
  document.addEventListener('keydown',event=>{if(cslChartDeleteAllowed(event,document.activeElement) && deleteSelectedChartObject()){event.preventDefault();event.stopPropagation();}});
  $('drawing-delete').addEventListener('click',()=>{selectedChartObject={type:'drawing',id:$('drawing-selected').value};deleteSelectedChartObject();});
  $('manual-show-box').addEventListener('click',()=>{const record=currentReview();if(!record)return;record.positionBoxHidden=false;record.positionBoxPlaced=true;selectedChartObject={type:'position',key:replayKey()};saveReviews();refreshManualPlan();redrawOverlays();});
  $('drawing-clear').addEventListener('click',()=>saveDrawings([]));
  $('drawing-undo').addEventListener('click',()=>{if(!drawingUndo.length)return;drawings=drawingUndo.pop();try{localStorage.setItem(drawingKey,JSON.stringify(drawings));}catch{drawingStorageOk=false;}drawingControls();drawUserDrawings();});
  $('drawing-edit').addEventListener('click',()=>{const item=drawings.find(item=>item.id===$('drawing-selected').value);if(!item)return;stopReplay();drawingEditId=item.id;$('drawing-tool').value=item.tool;$('drawing-color').value=item.color;$('drawing-text').value=item.text || '';manualPick=null;drawingPoints=[];drawingHover=null;chartWrap.style.cursor='crosshair';drawingControls();});
  $('drawing-export').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,runId:boot.run.runId,symbol:boot.run.symbol,drawings},null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='csl-chart-drawings.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){drawingPoints=[];drawingHover=null;drawingEditId=null;$('drawing-tool').value='cursor';chartWrap.style.cursor='';drawingControls();drawUserDrawings();}});
  drawingControls();

  function stopReplay() {
    if(replayTimer) clearInterval(replayTimer);
    replayTimer=null; $('replay-play').textContent='Play';
  }
  function replayKey() {
    if(dayMode)return manualDayTradeKey || JSON.stringify([boot.run.runId,boot.run.symbol,'manual-day',replayDay]);
    const trade=sourcePayload?.selectedTrade || {};
    return JSON.stringify([boot.run.runId,boot.run.symbol,trade.Pair ?? currentTrade,trade['Entry Time']]);
  }
  function currentReview() { return reviewRecords.find(record=>record?.key===replayKey()); }
  function dayTradeReviews() {return reviewRecords.filter(r=>r.runId===boot.run.runId && r.symbol===boot.run.symbol && r.reviewType==='manual-day' && r.day===replayDay);}
  function reportOutcomesSeen(){try{return Boolean(localStorage.getItem('csl-replay-report-seen:'+boot.run.runId));}catch{return false;}}
  function ensureReview() {
    let record=currentReview();if(record)return record;
    const trade=sourcePayload.selectedTrade;
    record={key:replayKey(),runId:boot.run.runId,symbol:boot.run.symbol,reviewType:dayMode?'manual-day':'automatic-trade',day:dayMode?replayDay:null,positionBoxPlaced:!dayMode,tradeIndex:dayMode?null:currentTrade,pair:trade.Pair,entryTime:trade['Entry Time'],side:trade.Side,recordedAt:new Date().toISOString(),outcomePreviouslyShown:normalViewsSeen.has(replayKey()) || reportOutcomesSeen(),notes:'',decision:'Wait',initialDecision:'Wait',initialDecisionReplayTime:replayCutoff,workflowVersion:1};
    reviewRecords.push(record);saveReviews();return record;
  }
  function saveReviews() {
    try { localStorage.setItem(reviewStorageKey,JSON.stringify(reviewRecords)); }
    catch { reviewStorageAvailable=false; }
  }
  function automaticPlan() {
    const trade=sourcePayload?.selectedTrade || {};
    const time=Date.parse(trade['Entry Time'] || '')/1000;
    const bar=(sourcePayload?.candles || []).find(item=>item.time<=time && time<item.time+replayInterval);
    return {entry:Number(trade.Entry),stop:Number(trade.Stop),target:Number(trade.Target),entryTime:bar?.time ?? time,interval:replayInterval,timeframe:boot.run.timeframe};
  }
  function manualPlanLocked() {
    return boot.run.mappingOnly || replayBusy || replayRevealed || Boolean(currentReview()?.manualEntry);
  }
  function manualMarket(record=currentReview()) {
    const entry=record?.manualEntry || manualPlanDraft;
    const timeframe=entry?.timeframe || boot.run.timeframe;
    return manualMarkets.get(timeframe) || (timeframe===boot.run.timeframe?marketPayload:null);
  }
  function manualInterval(record=currentReview()) {return record?.manualEntry?.interval || manualPlanDraft?.interval || replayInterval;}
  function warmManualMarket() {
    const entry=currentReview()?.manualEntry;if(!entry || manualMarket())return;
    const timeframe=entry.timeframe || boot.run.timeframe;if(manualMarketLoads.has(timeframe))return;
    manualMarketLoads.add(timeframe);
    getJson(api('/api/payload',{trade_index:String(currentTrade),chart_timeframe:timeframe,full_run:'1'})).then(data=>{
      manualMarkets.set(timeframe,data);if(replayActive)refreshReplay(true);
    }).catch(error=>{manualEntryMessage='Position candles could not load: '+error.message;refreshManualPlan();});
  }
  function manualCloseLocked() {return !manualMarket() || replayBusy || !replayActive || replayRevealed || !currentReview()?.manualEntry || Boolean(currentReview()?.manualExit);}
  function amendPosition(stop,target) {
    if(manualCloseLocked())return;
    stopReplay();advanceManualPosition();if(manualCloseLocked())return;
    const record=currentReview(),bar=(manualMarket()?.candles || []).filter(item=>item.time+manualInterval()<=replayCutoff).at(-1);
    const updated=cslAmendManualPosition(record,stop,target,replayCutoff,new Date().toISOString(),bar?.close);
    if(updated.error)manualEntryMessage=updated.error;
    else {reviewRecords=reviewRecords.map(item=>item===record?updated:item);saveReviews();manualEntryMessage='Position levels saved at '+fmtTime(replayCutoff)+' UTC.';}
    refreshManualPlan();redrawOverlays();
  }
  $('manual-be').addEventListener('click',()=>amendPosition(currentReview()?.manualEntry?.entry,manualPlanDraft.target));
  $('manual-cover-costs').addEventListener('click',()=>{
    if(manualCloseLocked())return;stopReplay();advanceManualPosition();if(manualCloseLocked())return;
    const record=currentReview(),result=cslCoverCostsAndBreakEven(record,manualMarket()?.candles || [],replayCutoff,manualInterval(),new Date().toISOString(),boot.run.manualCosts);
    if(result.error)manualEntryMessage=result.error;
    else{reviewRecords=reviewRecords.map(item=>item===record?result:item);saveReviews();
      const partial=result.partialExits.at(-1);manualEntryMessage='Closed '+(100*partial.fraction).toFixed(2)+'% to cover estimated costs; '+(100*partial.remainingFraction).toFixed(2)+'% remains with SL at entry.';}
    refreshManualPlan();redrawOverlays();
  });
  function closeManualPosition(requested=null) {
    if(manualCloseLocked())return;
    stopReplay();advanceManualPosition();if(manualCloseLocked())return;const record=currentReview();
    const result=cslCloseManualPosition(record,manualMarket()?.candles || [],replayCutoff,manualInterval(),new Date().toISOString(),requested);
    if(result.error){manualEntryMessage=result.error;manualPick=null;chartWrap.style.cursor='';refreshManualPlan();return;}
    reviewRecords=reviewRecords.map(item=>item===record?result:item);saveReviews();manualEntryMessage='';manualPick=null;chartWrap.style.cursor='';updateReplayControls();redrawOverlays();
  }
  function advanceManualPosition() {
    const record=currentReview();if(!record?.manualEntry || record.manualExit)return;
    const updated=cslAdvanceManualPosition(record,manualMarket()?.candles || [],replayCutoff,manualInterval(),new Date().toISOString());
    if(updated!==record){reviewRecords=reviewRecords.map(item=>item===record?updated:item);saveReviews();stopReplay();}
  }
  function closedPositionHint() {
    const record=currentReview();
    if(record?.manualExit)return dayMode?'This position is closed. Use New trade to add another trade on this day.':'This manual position is already closed.';
    if(replayRevealed)return 'Replay is fully revealed. Restart to review the position.';
    if(!manualMarket())return 'Loading the position entry-timeframe candles.';
    return 'Manage the confirmed manual position.';
  }
  function loadManualPlan(plan) {
    for(const key of ['entry','stop','target']) $('manual-'+key).value=plan[key] ?? '';
    manualEntryTime=plan.entryTime ?? automaticPlan().entryTime;
    manualEntryInterval=plan.interval || replayInterval;manualEntryTimeframe=plan.timeframe || boot.run.timeframe;
    manualEntryMessage='';
    manualPick=null; chartWrap.style.cursor=''; refreshManualPlan();
  }
  function refreshManualPlan() {
    if(manualPlanLocked() && manualPick!=='exit' || manualPick==='exit' && manualCloseLocked()) {manualPick=null;chartWrap.style.cursor='';}
    manualPlanDraft={...cslManualPlan($('manual-entry').value,$('manual-stop').value,$('manual-target').value,sourcePayload?.selectedTrade?.Side),entry:Number($('manual-entry').value),stop:Number($('manual-stop').value),target:Number($('manual-target').value)};
    manualPlanDraft.entryTime=manualEntryTime;manualPlanDraft.interval=manualEntryInterval || replayInterval;manualPlanDraft.timeframe=manualEntryTimeframe || boot.run.timeframe;
    if(currentReview()?.manualEntry){const levels=cslManualLevels(currentReview(),replayCutoff);manualPlanDraft={...levels,entry:currentReview().manualEntry.entry,entryTime:manualEntryTime};for(const key of ['entry','stop','target'])$('manual-'+key).value=manualPlanDraft[key];}
    const saved=currentReview()?.manualPlan;
    const dirty=!saved || ['entry','stop','target','entryTime','interval','timeframe'].some(key=>saved[key]!==manualPlanDraft[key]);
    const confirmed=currentReview()?.manualEntry;
    $('manual-time').textContent='Entry candle: '+fmtTime(manualEntryTime)+' UTC · '+(confirmed?.timeframe || manualEntryTimeframe || boot.run.timeframe);
    const status=manualPlanDraft.error || (confirmed?'Manual entry confirmed at '+fmtTime(confirmed.candleTime)+' UTC.':('R:R '+manualPlanDraft.rewardRisk.toFixed(2)+' · '+(dirty?'Preview only — confirm entry to open a position.':'Saved manual plan.')))+' '+manualEntryMessage+' Drag the box edges to resize SL/TP (and entry before confirmation). Move box selects a candle. Manual results are gross R before fees/slippage. TP/SL checks start after the entry candle; ties use SL.';
    $('manual-plan-status').textContent=manualPick?'Click the chart to place '+manualPick+'.':status;
    if(manualPick!=='position'){$('position-placement-hint').hidden=true;positionToolsButton.setAttribute('aria-pressed','false');}
    $('manual-plan-status').style.color=manualPlanDraft.error || manualEntryMessage.startsWith('Entry not confirmed:')?'#fda4af':'#b9d7f5';
    $('manual-show-box').hidden=!currentReview()?.positionBoxHidden;
    const locked=manualPlanLocked();
    for(const key of ['entry','stop','target']) $('manual-'+key).disabled=locked;
    for(const button of document.querySelectorAll('[data-pick-level]')) button.disabled=locked;
    $('manual-save').disabled=locked || Boolean(manualPlanDraft.error) || !currentReview()?.decision;
    $('manual-reset').disabled=locked;
    $('manual-move').disabled=locked;$('manual-move').title='Choose a closed candle on this chart.';
    $('manual-current').disabled=locked;
    $('manual-current').title='Set entry to the latest closed chart candle close, then confirm.';
    $('manual-confirm').disabled=locked || Boolean(manualPlanDraft.error) || Boolean(currentReview()?.positionBoxHidden);
    $('manual-confirm').title=confirmed?'Entry is already confirmed.':'Only this button opens your manual position. Confirm the selected closed candle and entry price.';
    $('manual-be').disabled=manualCloseLocked();
    const costBar=(manualMarket()?.candles || []).filter(bar=>bar.time>(confirmed?.candleTime ?? Infinity) && bar.time+manualInterval()<=replayCutoff).at(-1);
    const costQuote=cslCoverCostsQuote(currentReview(),Number(costBar?.close),boot.run.manualCosts);
    $('manual-cover-costs').disabled=manualCloseLocked() || Boolean(costQuote.error);
    $('manual-cover-costs').title=costQuote.error || 'Close '+(100*costQuote.fraction).toFixed(2)+'% at the latest closed entry-timeframe candle close, then move SL to entry. Estimated entry/exit fees and slippage; gaps and funding excluded.';
    $('manual-close').disabled=manualCloseLocked();$('manual-pick-exit').disabled=manualCloseLocked() || currentTimeframe!==(confirmed?.timeframe || boot.run.timeframe);
    $('manual-pick-exit').title=currentTimeframe!==(confirmed?.timeframe || boot.run.timeframe)?'Select the entry timeframe to pick an exit candle.':'';
    const managementHint=!confirmed?'Confirm manual entry to enable break-even and closing.':closedPositionHint();
    for(const id of ['manual-be','manual-close'])$(id).title=managementHint;
    const closed=currentReview()?.manualExit;
    const closedKnown=closed && (closed.availableAt ?? closed.candleTime+manualInterval())<=replayCutoff;
    $('manual-exit-status').textContent=closed && !closedKnown?'Previously reviewed manual position; advance to its exit candle to reveal the result.':closed?'Manual position closed ('+(closed.reason || 'Manual')+') · '+(closed.exitTime!=null?'Exit time '+fmtTime(closed.exitTime):'Exit candle '+fmtTime(closed.candleTime))+' UTC · '+formatPrice(closed.price)+' · Gross '+closed.grossR.toFixed(2)+' R ('+closed.returnPercent.toFixed(2)+'%) · before fees/slippage.'+(closed.ambiguous?' Both levels touched: conservative SL used.':''):confirmed?'Manual position open. Close at the latest closed candle, pick an exit, or advance until TP/SL is reached.':'';
    if(closedKnown && closed.estimatedNetR!=null)$('manual-exit-status').textContent+=' Estimated net '+closed.estimatedNetR.toFixed(2)+'R after modeled fees/slippage; funding/rounding excluded.';
    const knownPartials=(currentReview()?.partialExits || []).filter(p=>p.effectiveAt<=replayCutoff);
    if(knownPartials.length && !closedKnown){const fraction=knownPartials.reduce((sum,p)=>sum+p.fraction,0);$('manual-exit-status').textContent+=' '+(100*fraction).toFixed(2)+'% closed; '+(100*(1-fraction)).toFixed(2)+'% remaining. Estimated costs covered if the remainder exits at entry.';}
    const record=currentReview();
    $('manual-history').hidden=!record?.planHistory?.length;
    const history=$('manual-history-content');history.replaceChildren();
    if(record?.originalPlan) {
      const original=document.createElement('p');
      original.textContent=(dayMode?'Starting manual levels':'Automatic plan')+' · Entry '+formatPrice(record.originalPlan.entry)+' · SL '+formatPrice(record.originalPlan.stop)+' · TP '+formatPrice(record.originalPlan.target);history.appendChild(original);
    }
    for(const revision of (record?.positionHistory || []).filter(item=>item.effectiveAt<=replayCutoff)){const line=document.createElement('p');line.textContent=fmtTime(revision.effectiveAt)+' UTC · Position changed · SL '+formatPrice(revision.previousStop)+' → '+formatPrice(revision.stop)+' · TP '+formatPrice(revision.previousTarget)+' → '+formatPrice(revision.target);history.appendChild(line);}
    for(const revision of (record?.planHistory || []).slice(-20)) {
      const line=document.createElement('p');
      line.textContent=String(revision.replayTime)+' · '+(revision.futureSeen?'After advancing / previously viewed':'Pre-entry plan')+(revision.outcomePreviouslyShown?' (outcome previously shown)':'')+' · Entry '+formatPrice(revision.entry)+' · Candle '+(revision.entryTime!=null?fmtTime(revision.entryTime):'automatic')+' · SL '+formatPrice(revision.stop)+' · TP '+formatPrice(revision.target);history.appendChild(line);
    }
  }
  function storeManualPlan() {
    const record=currentReview();
    if(!record || manualPlanDraft?.error) return;
    const updated=cslRecordManualPlan(record,manualPlanDraft,automaticPlan(),{
      recordedAt:new Date().toISOString(),replayTime:fmtTime(replayCutoff),
      futureSeen:replayAdvanced || Boolean(record.revealedAt)});
    reviewRecords=reviewRecords.map(item=>item===record?updated:item);
    saveReviews(); refreshManualPlan();
  }
  function initializeReplay() {
    stopReplay(); replayAdvanced=false; replayRevealed=false; replayOutcomeVisible=false;
    const match=String(boot.run.timeframe).match(/^([0-9]+)([mhdw])$/);
    replayInterval=match ? Number(match[1])*({m:60,h:3600,d:86400,w:604800}[match[2]]) : 0;
    replayEntryTime=Date.parse(sourcePayload?.selectedTrade?.['Entry Time'] || '')/1000;
    replayCutoff=replayEntryTime;
    if(!replayInterval || !Number.isFinite(replayEntryTime)) throw Error('This trade has no usable entry time or strategy interval for replay.');
    ensureReview();
    $('replay-notes').value=currentReview()?.notes || '';
    loadManualPlan(currentReview()?.manualPlan || automaticPlan());
  }
  function updateReplayControls() {
    const record=currentReview();
    if(boot.run.mappingOnly && dayMode) {
      replayDay=cslReplayDisplayDay(replayCutoff,replayEntryTime);
      $('replay-day').value=new Date(replayDay*1000).toISOString().slice(0,10);
    }
    workspacePanels.setReplay(replayActive);
    $('workspace-clock').textContent=replayActive?fmtTime(replayCutoff)+' UTC'+(boot.run.mappingOnly?' · Structure replay':' · '+cslManualReviewState(record)):'';
    $('replay-reveal').textContent=boot.run.mappingOnly?'Reveal remaining history':dayMode?'Reveal day':'Reveal result';
    $('replay-restart').textContent=boot.run.mappingOnly?'Restart replay':dayMode?'Restart day':'Restart at entry';
    $('manual-reset').textContent=dayMode?'Reset starting levels':'Use auto levels';
    const locked=replayRevealed || Boolean(record?.manualEntry);
    $('manual-workflow-state').textContent=cslManualReviewState(record);
    for(const button of document.querySelectorAll('[data-replay-decision]')) {
      button.disabled=replayBusy || locked;
      button.setAttribute('aria-pressed',String(record?.decision===button.dataset.replayDecision));
    }
    $('replay-step').title='Advance one '+currentTimeframe+' chart candle.';
    $('replay-notes').disabled=replayBusy || locked;
    for(const id of ['replay-step','replay-play','replay-reveal']) $(id).disabled=replayBusy || (!dayMode && !record) || replayRevealed;
    if(dayMode) {
      const selector=$('day-trade');selector.replaceChildren();
      dayTradeReviews().forEach((item,index)=>selector.add(new Option('Trade '+(index+1)+' · '+cslManualReviewState(item),item.key)));
      selector.value=replayKey();selector.disabled=replayBusy;
      const next=cslNextDayTrade(reviewRecords,boot.run.runId,boot.run.symbol,replayDay,replayCutoff,replayInterval);
      $('manual-new-trade').disabled=replayBusy || replayRevealed || !record?.manualExit || Boolean(next.error);
      $('manual-new-trade').title=next.error || (!record?.manualExit?'Confirm and close this position before starting another trade.':'Keep this trade saved and start another plan on the same day.');
      const days=[...new Set((marketPayload.candles || []).map(bar=>Math.floor(bar.time/86400)*86400))];
      $('previous-day').disabled=replayBusy || !days.some(day=>day<replayDay);
      $('next-day').disabled=replayBusy || !days.some(day=>day>replayDay);
      $('day-side').disabled=Boolean(record?.manualEntry) || replayBusy || replayRevealed;
    }
    $('replay-restart').disabled=replayBusy;
    let message=String(sourcePayload?.selectedTrade?.Side || '')+' entry preview · '+fmtTime(replayCutoff)+' · '+cslManualReviewState(record);
    if(dayMode)message='Manual day review · '+fmtTime(replayCutoff)+' UTC · '+cslManualReviewState(record)+' · No automatic trade is required. Starting prices are editable placeholders.';
    if(record?.revealedAt && !replayAdvanced && !replayRevealed) message+=' Previously reviewed; original judgement retained.';
    if(replayOutcomeVisible) message+=' Auto reference result: '+String(sourcePayload.selectedTrade['Exit Reason'] || '')+' · '+String(sourcePayload.selectedTrade['Net R'] ?? 'n/a')+' R';
    else if(replayAdvanced && !dayMode) message+=' · Result still hidden.';
    if(replayOutcomeVisible) {
      const scored=reviewRecords.filter(r=>r?.runId===boot.run.runId && r?.symbol===boot.run.symbol && r.netR!=null && Number.isFinite(Number(r.netR)));
      const total=scored.reduce((sum,r)=>sum+Number(r.netR),0);
      const manual=cslManualWorkflowSummary(reviewRecords.filter(r=>r.runId===boot.run.runId && r.symbol===boot.run.symbol));
      message+=' · Auto reference '+total.toFixed(2)+' R · Manual: '+manual.entered+' entered, '+manual.closed+' closed · '+manual.grossR.toFixed(2)+' R gross.';
    }
    message+=' · Saved in this browser; export to keep reviews across visualizer sessions.';
    if(!reviewStorageAvailable) message+=' Browser storage unavailable: export before closing.';
    $('replay-status').textContent=message;
    refreshManualPlan();
  }
  function refreshReplay(incremental=false) {
    if(!sourcePayload) return;
    if(replayActive) {
      const projected=cslReplayView(sourcePayload,replayCutoff,replayInterval,replayEntryTime,dayMode?false:replayRevealed,false);
      payload=projected.view; replayOutcomeVisible=projected.outcomeVisible;
      if(replayChartSource)payload=cslReplayChart(payload,replayChartSource,replayCutoff,chartInterval(),replayEntryTime,!dayMode && replayRevealed);
      warmManualMarket();
      const record=currentReview();
      if(record && replayOutcomeVisible) {
        record.netR=sourcePayload.selectedTrade['Net R'] ?? null;
        record.exitReason=sourcePayload.selectedTrade['Exit Reason'] ?? null;
        saveReviews();
      }
      advanceManualPosition();
    } else {
      payload=sourcePayload;
      normalViewsSeen.add(replayKey());
      const record=currentReview();
      if(record) {
        record.revealedAt=record.revealedAt || new Date().toISOString();
        record.netR=sourcePayload.selectedTrade['Net R'] ?? null;
        record.exitReason=sourcePayload.selectedTrade['Exit Reason'] ?? null;
        saveReviews();
      }
    }
    renderDiagnostics();
    if(incremental && chart && replaySeries.length) updateReplayChart();
    else {defaultPriceRange=null;priceZoomFactor=1;pricePanOffset=0;buildChart();requestAnimationFrame(centerSelected);}
    chartWrap.style.visibility='visible';
    if(replayActive) updateReplayControls();
  }
  function markFutureSeen() {
    const record=currentReview();
    if(!record) return false;
    if(!record.revealedAt) { record.revealedAt=new Date().toISOString(); saveReviews(); }
    return true;
  }
  function replayEnd() {
    return cslReplayEnd(sourcePayload?.candles || [],replayInterval,dayMode?replayDay:null,Boolean(boot.run.mappingOnly));
  }
  function stepReplay() {
    if(replayActive && !manualPlanLocked()) {
      refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();
    }
    if(replayBusy || !replayActive || replayRevealed || (!dayMode && !markFutureSeen())) return;
    const nextCutoff=cslNextReplayCutoff((replayChartSource || sourcePayload).candles || [],replayCutoff,chartInterval(),replayEnd());
    if(nextCutoff==null) {stopReplay();$('replay-status').textContent=boot.run.mappingOnly?'End of available history.':dayMode?'End of this UTC day. Use Next day to continue.':'End of available candles. Export your review to retain it.';return;}
    replayCutoff=nextCutoff; replayAdvanced=true;
    if(dayMode && currentReview())markFutureSeen();
    refreshReplay(true);
  }
  function updateTradeLabels() {
    [...tradeSelect.options].forEach((option,index)=>option.textContent=replayActive ? 'Trade '+(index+1)+' · outcome hidden' : boot.trades[index].label);
  }
  function openReplayDay(day) {
    if(replayBusy || !marketPayload)return;
    stopReplay();
    if(replayActive && !manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    replayDay=day;dayMode=true;replayActive=true;
    const savedTrades=dayTradeReviews();
    if(!savedTrades.some(r=>r.key===manualDayTradeKey))manualDayTradeKey=savedTrades.at(-1)?.key || null;
    const match=String(boot.run.timeframe).match(/^([0-9]+)([mhdw])$/);
    replayInterval=match?Number(match[1])*({m:60,h:3600,d:86400,w:604800}[match[2]]):900;
    const saved=currentReview();
    $('day-side').value=saved?.side || $('day-side').value;
    sourcePayload=cslDaySource(marketPayload,day,replayInterval,$('day-side').value,boot.run.swingStrength);
    $('replay-day').value=new Date(day*1000).toISOString().slice(0,10);
    $('day-navigation').hidden=false;$('replay-controls').hidden=false;
    $('day-replay').setAttribute('aria-pressed','true');$('replay-toggle').setAttribute('aria-pressed','false');
    tradeSelect.disabled=true;timeframeSelect.disabled=false;updateTradeLabels();initializeReplay();refreshReplay();
  }
  $('structure-review').addEventListener('click',()=>{
    if(replayBusy || !marketPayload)return;
    $('structure-guide').checked=true;
    if(!dayMode)$('day-replay').click();
    else redrawOverlays();
  });
  function selectDayTrade(key) {
    if(replayBusy || !dayMode)return;
    if(!manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    const record=dayTradeReviews().find(r=>r.key===key);if(!record)return;
    stopReplay();manualDayTradeKey=key;$('day-side').value=record.side;
    sourcePayload=cslDaySource(marketPayload,replayDay,replayInterval,record.side,boot.run.swingStrength);
    $('replay-notes').value=record.notes || '';
    loadManualPlan(record.manualPlan || automaticPlan());refreshReplay(true);
  }
  $('day-trade').addEventListener('change',()=>selectDayTrade($('day-trade').value));
  $('manual-new-trade').addEventListener('click',()=>{
    if(replayBusy || !dayMode || replayRevealed || !currentReview()?.manualExit)return;
    const next=cslNextDayTrade(reviewRecords,boot.run.runId,boot.run.symbol,replayDay,replayCutoff,replayInterval);
    if(next.error){manualEntryMessage=next.error;refreshManualPlan();return;}
    if(next.existingKey){selectDayTrade(next.existingKey);return;}
    stopReplay();manualDayTradeKey=next.key;workspacePanels.show('plan');
    const record=ensureReview();record.tradeNotBefore=next.notBefore;record.startedReplayTime=replayCutoff;
    const bar=(marketPayload.candles || []).filter(b=>b.time>=next.notBefore && b.time>=replayDay && b.time<replayDay+86400 && b.time+replayInterval<=replayCutoff).at(-1);
    const plan=automaticPlan(),entry=bar?.close ?? (payload.candles || []).at(-1)?.close ?? plan.entry;
    const sign=record.side==='SHORT'?-1:1,risk=Math.abs(plan.entry-plan.stop);
    $('replay-notes').value='';
    loadManualPlan({entry,stop:entry-sign*risk,target:entry+sign*risk*2,entryTime:bar?.time ?? next.notBefore,interval:replayInterval,timeframe:boot.run.timeframe});
    storeManualPlan();saveReviews();refreshReplay(true);
  });
  $('structure-guide').addEventListener('change',redrawOverlays);
  $('day-replay').addEventListener('click',()=>{
    if(replayBusy || !marketPayload)return;
    if(dayMode){
      stopReplay();if(!manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
      dayMode=false;replayActive=false;sourcePayload=replayChartSource || marketPayload;marketPayload=sourcePayload;replayChartSource=null;
      $('day-navigation').hidden=true;$('replay-controls').hidden=true;$('day-replay').setAttribute('aria-pressed','false');
      tradeSelect.disabled=false;timeframeSelect.disabled=false;updateTradeLabels();refreshReplay();return;
    }
    if(currentTimeframe!==boot.run.timeframe){dayMode=true;replayActive=true;currentTimeframe=boot.run.timeframe;load();return;}
    const time=replayActive?replayCutoff:Date.parse(sourcePayload?.selectedTrade?.['Entry Time'] || '')/1000;
    const days=[...new Set((marketPayload.candles || []).map(bar=>Math.floor(bar.time/86400)*86400))];
    const day=Math.floor(time/86400)*86400;openReplayDay(days.includes(day)?day:days[0]);
  });
  for(const [id,direction] of [['previous-day',-1],['next-day',1]])$(id).addEventListener('click',()=>{
    const days=[...new Set((marketPayload?.candles || []).map(bar=>Math.floor(bar.time/86400)*86400))];
    const candidates=days.filter(day=>direction>0?day>replayDay:day<replayDay);
    const day=direction>0?candidates[0]:candidates.at(-1);if(day!=null)openReplayDay(day);
  });
  $('replay-day').addEventListener('change',()=>{
    const day=Date.parse($('replay-day').value+'T00:00:00Z')/1000;
    if((marketPayload?.candles || []).some(bar=>bar.time>=day && bar.time<day+86400))openReplayDay(day);
    else {$('replay-day').value=new Date(replayDay*1000).toISOString().slice(0,10);$('replay-status').textContent='No candles available for that UTC day.';}
  });
  $('day-side').addEventListener('change',()=>{
    if(replayBusy || replayRevealed || currentReview()?.manualEntry)return;
    stopReplay();const record=ensureReview();
    record.sideHistory=[...(record.sideHistory || []),{previous:record.side,side:$('day-side').value,replayTime:replayCutoff,recordedAt:new Date().toISOString(),previousPlan:record.manualPlan}];
    record.side=$('day-side').value;record.manualPlan=null;saveReviews();
    sourcePayload=cslDaySource(marketPayload,replayDay,replayInterval,record.side,boot.run.swingStrength);
    loadManualPlan(automaticPlan());refreshReplay();
  });
  $('replay-toggle').addEventListener('click',()=>{
    if(dayMode){if(!manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}dayMode=false;sourcePayload=marketPayload;replayActive=false;$('day-navigation').hidden=true;$('day-replay').setAttribute('aria-pressed','false');tradeSelect.disabled=false;}
    if(replayActive && !manualPlanLocked()) {refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    stopReplay(); replayActive=!replayActive;
    $('replay-toggle').setAttribute('aria-pressed',String(replayActive));
    $('replay-controls').hidden=!replayActive;
    timeframeSelect.disabled=false;
    updateTradeLabels();
    if(replayActive && currentTimeframe!==boot.run.timeframe) {
      currentTimeframe=boot.run.timeframe; timeframeSelect.value=currentTimeframe; load(); return;
    }
    if(replayActive) initializeReplay();
    else if(replayChartSource){sourcePayload=replayChartSource;marketPayload=replayChartSource;replayChartSource=null;}
    refreshReplay();
  });
  document.querySelectorAll('[data-replay-decision]').forEach(button=>button.addEventListener('click',()=>{
    if(replayBusy || replayRevealed || currentReview()?.manualEntry)return;
    stopReplay();refreshManualPlan();
    const record=ensureReview(),updated=cslReviewDecision(record,button.dataset.replayDecision,replayCutoff,new Date().toISOString(),$('replay-notes').value);
    if(updated.error)return;
    reviewRecords=reviewRecords.map(item=>item===record?updated:item);saveReviews();
    if(!manualPlanDraft.error)storeManualPlan();updateReplayControls();redrawOverlays();
  }));
  for(const key of ['entry','stop','target']) $('manual-'+key).addEventListener('input',()=>{
    if(manualPlanLocked()) return;
    stopReplay();
    if(dayMode){ensureReview().positionBoxPlaced=true;ensureReview().positionBoxHidden=false;}
    manualEntryMessage='';
    refreshManualPlan(); resetPriceScale();
  });
  $('manual-save').addEventListener('click',()=>{if(!manualPlanLocked()){storeManualPlan();updateReplayControls();redrawOverlays();}});
  $('manual-reset').addEventListener('click',()=>{if(!manualPlanLocked()){loadManualPlan(automaticPlan());resetPriceScale();}});
  $('manual-move').addEventListener('click',()=>{
    if(manualPlanLocked()) return;
    stopReplay();$('drawing-tool').value='cursor';drawingPoints=[];drawingHover=null;drawingControls();manualPick='candle';chartWrap.style.cursor='crosshair';refreshManualPlan();
  });
  $('manual-current').addEventListener('click',()=>{
    if(manualPlanLocked())return;stopReplay();
    const interval=chartInterval(),bar=((replayChartSource || sourcePayload)?.candles || []).filter(item=>item.time+interval<=replayCutoff).at(-1);
    const first=dayMode?Math.max(replayDay,currentReview()?.tradeNotBefore ?? replayDay):automaticPlan().entryTime;
    if(!bar || bar.time<first){manualEntryMessage='Advance until a chart candle at or after entry has closed.';refreshManualPlan();return;}
    ensureReview().positionBoxPlaced=true;ensureReview().positionBoxHidden=false;selectedChartObject={type:'position',key:replayKey()};
    manualEntryTime=bar.time;manualEntryInterval=interval;manualEntryTimeframe=currentTimeframe;
    $('manual-entry').value=bar.close;manualEntryMessage='Current closed candle selected. Check SL/TP, then confirm entry.';refreshManualPlan();showManualBox();
  });
  $('manual-confirm').addEventListener('click',()=>{
    if(boot.run.mappingOnly)return;
    if(manualPlanLocked()) return;
    stopReplay();refreshManualPlan();if(manualPlanDraft.error)return;
    ensureReview();storeManualPlan();const record=currentReview();
    const result=cslConfirmManualEntry(record,manualMarket(record)?.candles || [],replayCutoff,manualInterval(record),new Date().toISOString());
    if(result.error) {manualEntryMessage=result.error;refreshManualPlan();return;}
    reviewRecords=reviewRecords.map(item=>item===record?result:item);saveReviews();
    manualEntryMessage='';advanceManualPosition();updateReplayControls();redrawOverlays();
  });
  $('manual-close').addEventListener('click',()=>closeManualPosition());
  $('manual-pick-exit').addEventListener('click',()=>{
    if(manualCloseLocked())return;stopReplay();$('drawing-tool').value='cursor';drawingPoints=[];drawingHover=null;drawingControls();manualPick='exit';chartWrap.style.cursor='crosshair';refreshManualPlan();
  });
  document.querySelectorAll('[data-pick-level]').forEach(button=>button.addEventListener('click',()=>{
    if(manualPlanLocked()) return;
    stopReplay();$('drawing-tool').value='cursor';drawingPoints=[];drawingHover=null;drawingControls();manualPick=button.dataset.pickLevel;chartWrap.style.cursor='crosshair';refreshManualPlan();
  }));
  $('replay-notes').addEventListener('input',()=>{
    const record=currentReview();
    if(record && !replayRevealed && !record.manualEntry) { record.notes=$('replay-notes').value; saveReviews(); }
  });
  $('replay-step').addEventListener('click',()=>{stopReplay();stepReplay();});
  $('replay-play').addEventListener('click',()=>{
    if(replayTimer) {stopReplay();return;}
    if(replayBusy || (!dayMode && !currentReview()) || replayRevealed) return;
    replayTimer=setInterval(stepReplay,Number($('replay-speed').value)); $('replay-play').textContent='Pause';
  });
  $('replay-speed').addEventListener('change',()=>{if(replayTimer){stopReplay();$('replay-play').click();}});
  $('replay-follow').addEventListener('change',()=>{
    if(!$('replay-follow').checked || !chart || !replayActive)return;
    const range=chart.timeScale().getVisibleLogicalRange();if(!range)return;
    const to=(payload.candles || []).length+8;
    chart.timeScale().setVisibleLogicalRange({from:to-(range.to-range.from),to});
  });
  $('replay-reveal').addEventListener('click',()=>{
    if(!manualPlanLocked()) {refreshManualPlan();if(manualPlanDraft.error)return;storeManualPlan();}
    if(replayBusy || (!dayMode && !markFutureSeen())) return;
    if(dayMode){replayCutoff=replayEnd();if(currentReview())markFutureSeen();}
    stopReplay(); replayRevealed=true; refreshReplay();
  });
  $('replay-restart').addEventListener('click',()=>{if(!replayBusy){
    if(!manualPlanLocked()) {refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    initializeReplay();refreshReplay();
  }});
  $('replay-report').title='Open comparison results in a new tab (reveals automatic outcomes)';
  $('replay-report').addEventListener('click',()=>{
    stopReplay();
    if(replayActive && !manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    const reportWindow=window.open(api('/review-report'),'_blank');
    if(reportWindow)reportWindow.opener=null;
    else $('timeframe-note').textContent='Allow new tabs for this visualizer, then click Review report again.';
  });
  window.addEventListener('storage',event=>{
    if(event.key===reviewStorageKey){try{const saved=JSON.parse(event.newValue || '[]');if(Array.isArray(saved))reviewRecords=saved;}catch{}}
  });
  $('replay-export').addEventListener('click',()=>{
    if(replayActive && !manualPlanLocked()) {refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    const records=reviewRecords.filter(record=>record?.runId===boot.run.runId && record?.symbol===boot.run.symbol);
    const workflowSummary=cslManualWorkflowSummary(records);
    const scored=records.filter(record=>record.netR!=null && Number.isFinite(Number(record.netR)));
    const sum=list=>list.reduce((total,record)=>total+Number(record.netR),0);
    const report={version:3,runId:boot.run.runId,symbol:boot.run.symbol,exportedAt:new Date().toISOString(),
      manualDayReviews:records.filter(record=>record.reviewType==='manual-day').length,
      workflowSummary,
      summary:{reviewed:records.length,revealed:scored.length,automaticNetR:sum(scored),manualTakeNetR:sum(scored.filter(r=>r.decision==='Take')),skippedNetR:sum(scored.filter(r=>r.decision==='Skip')),unsureNetR:sum(scored.filter(r=>r.decision==='Unsure'))},
      manualPlans:records.filter(record=>record.manualPlan).length,
      confirmedManualEntries:records.filter(record=>record.manualEntry).length,
      manualResults:{closed:workflowSummary.closed,grossR:workflowSummary.grossR,estimatedNetClosed:workflowSummary.estimatedNetClosed,estimatedNetR:workflowSummary.estimatedNetR,partialExitCount:workflowSummary.partialExitCount},
      interpretation:'Automatic R totals (including legacy manualTakeNetR) are reference backtest comparisons, not manual P&L. Waiting and skipped setups have no manual position or loss; only confirmed manual entries count. Decision history retains changes made after advancing. manualResults contains gross R from confirmed manual entries and user exits or replay TP/SL hits. Level checks start after the entry candle; both levels touched uses SL unless a gap opening establishes order. Cover costs + BE records weighted partial exits plus estimated fees/slippage in a separate estimatedNetR; funding and exchange rounding are excluded; stop gaps can change net results. Other manual positions remain gross only. Portfolio sizing and overlapping positions are not simulated.',reviews:records};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const link=document.createElement('a'); link.href=url; link.download='csl-manual-replay-reviews.json'; document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  window.addEventListener('pagehide',stopReplay);

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
    const bounds=replayActive && !replayRevealed ? replayBounds() : (reviewMode ? setupBounds() : null);
    const start=Number(bounds?.from ?? payload?.selectedTradeViewStart);
    const end=Number(bounds?.to ?? payload?.selectedTradeViewEnd);
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
    for(const level of payload?.dayContext?.levels || [])if(level.price!=null && Number.isFinite(Number(level.price))){low=Math.min(low,Number(level.price));high=Math.max(high,Number(level.price));}
    if(replayActive && manualPlanDraft && currentReview()?.positionBoxPlaced!==false && !currentReview()?.positionBoxHidden) {
      for(const price of [manualPlanDraft.entry,manualPlanDraft.stop,manualPlanDraft.target]) {
        if(Number.isFinite(price) && price>0){low=Math.min(low,price);high=Math.max(high,price);}
      }
    }
    for (const value of (dayMode?[]:[
      trade.Entry ?? trade.entry, trade.Stop ?? trade.stop,
      trade.Target ?? trade.target, trade.Exit ?? trade.exit,
    ])) {
      const price=Number(value);
      if (Number.isFinite(price)) { low=Math.min(low,price); high=Math.max(high,price); }
    }
    for (const item of (payload?.fibDerivation?.levels || [])) {
      const price=Number(item?.price);
      if (Number.isFinite(price)) { low=Math.min(low,price); high=Math.max(high,price); }
    }
    const fvg=payload?.fvgDerivation;
    if (fvg?.status==='AVAILABLE') {
      low=Math.min(low,fvg.impulseOrigin,fvg.impulseExtreme,fvg.bottom);
      high=Math.max(high,fvg.impulseOrigin,fvg.impulseExtreme,fvg.top);
    }
    if(payload?.supplyDemandDerivation?.strategy==='SNEAKY_PIVOT') {
      for(const level of (payload.supplyDemandDerivation.levels || [])) {
        if(level.price==null) continue;
        const price=Number(level.price);
        if(Number.isFinite(price)) {low=Math.min(low,price);high=Math.max(high,price);}
      }
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
      redrawOverlays();
    });
  }

  function redrawOverlays() {
    drawDaySeparators();
    drawPreviousDayZones();
    drawFibOverlay();
    drawStructureGuide();
    drawFvgOverlay();
    drawTradeBox();
    layoutOverlayLabels();
    drawUserDrawings();
  }

  let srCache=null;
  chartWrap.addEventListener('mousemove',event=>{
    chartWrap.removeAttribute('title');
    if(!$('sr-zones').checked || !srCache?.result?.zones || !candles)return;
    const rect=chartWrap.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;
    if(x<0 || x>rect.width-76 || y>chart.panes()[0].getHeight())return;
    const price=candles.coordinateToPrice(y),zone=srCache.result.zones.find(item=>item.bottom<=price && price<=item.top && x>=Math.max(0,Number(chart.timeScale().timeToCoordinate(item.time) ?? 0)));
    if(zone)chartWrap.title='Previous-day '+zone.kind+' · '+formatPrice(zone.bottom)+'–'+formatPrice(zone.top);
  });
  chartWrap.addEventListener('mouseleave',()=>chartWrap.removeAttribute('title'));
  function drawPreviousDayZones() {
    const layer=$('sr-layer');layer.replaceChildren();$('sr-status').textContent='';chartWrap.removeAttribute('title');
    if(!chart || !candles || !$('sr-zones').checked)return;
    const interval=Number(String(currentTimeframe).match(/^([0-9]+)/)?.[1])*({m:60,h:3600,d:86400,w:604800}[String(currentTimeframe).slice(-1)] || 0);
    const anchor=replayActive?replayEntryTime:Date.parse(sourcePayload?.selectedTrade?.['Entry Time'] || '')/1000;
    const day=dayMode?sourcePayload?.dayContext?.day:Math.floor(anchor/86400)*86400;
    const bars=(replayChartSource || marketPayload || sourcePayload)?.candles || [],width=Number($('sr-width').value);
    if(!srCache || srCache.bars!==bars || srCache.day!==day || srCache.width!==width || srCache.interval!==interval)srCache={bars,day,width,interval,result:cslPreviousDayZones(bars,day,interval,width)};
    const result=srCache.result;
    if(result.reason){$('sr-status').textContent=result.reason;return;}
    $('sr-status').textContent=result.zones.length+' zones · '+new Date((day-86400)*1000).toISOString().slice(0,10)+' UTC';
    const right=chartWrap.clientWidth-76,height=chart.panes()[0].getHeight();
    for(const zone of result.zones){
      const start=chart.timeScale().timeToCoordinate(zone.time),left=Math.max(0,Number(start ?? 0));
      const a=candles.priceToCoordinate(zone.top),b=candles.priceToCoordinate(zone.bottom);
      if(a==null || b==null || Math.max(a,b)<0 || Math.min(a,b)>height)continue;
      const el=document.createElement('div');el.className='sr-zone';
      const support=zone.kind==='support',resistance=zone.kind==='resistance';
      Object.assign(el.style,{left:left+'px',width:Math.max(0,right-left)+'px',top:Math.max(0,Math.min(a,b))+'px',height:Math.max(2,Math.min(height,Math.max(a,b))-Math.max(0,Math.min(a,b)))+'px',borderColor:support?'#38bda0':resistance?'#e89861':'#a5a1e8',background:support?'rgba(56,189,160,.12)':resistance?'rgba(232,152,97,.12)':'rgba(165,161,232,.12)'});
      layer.appendChild(el);
    }
  }

  function drawDaySeparators() {
    const layer=$('day-layer'); layer.replaceChildren();
    if(!chart || !$('day-separators').checked) return;
    const height=chart.panes()[0].getHeight(),right=chartWrap.clientWidth-76;
    const visible=chart.timeScale().getVisibleRange();
    let day=null,lastLabel=-Infinity;
    for(const bar of (payload?.candles || [])) {
      const current=Math.floor(bar.time/86400);
      if(current===day) continue;
      day=current;
      if(bar.time%86400!==0) continue;
      if(visible && (bar.time<visible.from || bar.time>visible.to)) continue;
      const x=chart.timeScale().timeToCoordinate(bar.time);
      if(x==null || x<0 || x>right) continue;
      const line=document.createElement('div');line.className='utc-day-line';
      Object.assign(line.style,{left:x+'px',height:height+'px'});layer.appendChild(line);
      if(x-lastLabel<120) continue;
      const label=document.createElement('span');label.className='utc-day-label';
      label.textContent=new Date(current*86400000).toISOString().slice(0,10)+' UTC';
      label.style.left=Math.min(x+5,Math.max(0,right-118))+'px';layer.appendChild(label);lastLabel=x;
    }
  }

  function drawSneakyLevels(sd,xAt,height) {
    const right=Math.max(0,chartWrap.clientWidth-76);
    const start=Math.max(0,xAt(sd.opposingZone.pivotTime,0));
    const colors={rangeHigh:'#fb7185',rangeLow:'#34d399',swingHigh:'#fbbf24',swingLow:'#60a5fa',recentHigh:'#c4a5ff',recentLow:'#67e8f9'};
    let labelBottom=-2;
    const levels=(sd.levels || []).filter(level=>level.price!=null).slice().sort((a,b)=>Number(b.price)-Number(a.price));
    for(const level of levels) {
      if(level.price==null) continue;
      const known=level.confirmedAt==null?null:Date.parse(level.confirmedAt)/1000;
      if(replayActive && Number.isFinite(known) && known>replayCutoff)continue;
      const origin=level.time==null?null:Date.parse(level.time)/1000;
      const levelStart=Number.isFinite(origin)?Math.max(0,xAt(origin,0)):start;
      const y=candles.priceToCoordinate(Number(level.price));
      if(y==null || y<0 || y>height) continue;
      const color=colors[level.role] || '#cbd5e1';
      const line=document.createElement('div');line.className='fvg-level sneaky-level';
      Object.assign(line.style,{left:levelStart+'px',top:y+'px',width:Math.max(0,right-levelStart)+'px',borderColor:color,borderTopStyle:level.role.startsWith('swing') || level.role.startsWith('recent')?'dashed':'solid'});fvgLayer.appendChild(line);
      const label=document.createElement('span');label.className='fvg-note sneaky-level-label';
      label.textContent=level.label+' · '+formatPrice(level.price);
      const labelY=Math.min(height-25,Math.max(2,y-25,labelBottom+4));
      Object.assign(label.style,{left:'12px',top:labelY+'px',color,background:'#101923ed',borderLeft:'3px solid '+color});fvgLayer.appendChild(label);
      labelBottom=labelY+label.offsetHeight;
    }
    // Small candle-outline area only; do not shade the full previous-day range.
    const x=Math.max(0,xAt(sd.zone.touchTime,0)),end=xAt(sd.signalTime,right);
    const top=candles.priceToCoordinate(sd.zone.top),bottom=candles.priceToCoordinate(sd.zone.bottom);
    if(top!=null && bottom!=null) {
      const box=document.createElement('div');box.className='fvg-zone';
      Object.assign(box.style,{left:x+'px',top:top+'px',width:Math.max(3,end-x)+'px',height:Math.max(2,bottom-top)+'px',background:'transparent',borderColor:'#a5d8ff'});fvgLayer.appendChild(box);
    }
    const events=[[sd.zone.touchTime,'1 · Level test'],[sd.zone.bounceTime,'2 · Reversal / breakout armed']];
    events.forEach(([time,text],index)=>{
      const label=document.createElement('span');label.className='fvg-note';label.textContent=text;
      Object.assign(label.style,{left:Math.max(12,Math.min(right-250,xAt(time,0)))+'px',top:Math.max(35,height-72+index*27)+'px'});fvgLayer.appendChild(label);
    });
  }

  function formatPrice(value) {
    if (value == null || !Number.isFinite(Number(value))) return 'n/a';
    const price=Number(value);
    const precision=Math.max(2,Math.min(8,2-Math.floor(Math.log10(Math.abs(price)||1))));
    return price.toLocaleString('en-US',{minimumFractionDigits:precision,maximumFractionDigits:precision});
  }

  function layoutOverlayLabels() {
    const boxes=[];
    const height=chart?.panes()[0]?.getHeight() || chartWrap.clientHeight;
    const width=Math.max(1,chartWrap.clientWidth-80);
    for (const label of chartWrap.querySelectorAll('.fvg-note:not(.sneaky-level-label),.trade-label:not(.manual-price-label)')) {
      const w=label.offsetWidth, h=label.offsetHeight;
      const x=Math.max(2,Math.min(width-w,parseFloat(label.style.left)||0));
      const preferred=Math.max(2,Math.min(height-h-2,parseFloat(label.style.top)||0));
      let y=preferred;
      for (let step=0;step<80;step++) {
        const candidate=preferred+(step%2 ? 1 : -1)*Math.ceil(step/2)*(h+4);
        if (candidate<2 || candidate+h>height-2) continue;
        if (!boxes.some(box=>x<box.x+box.w+4 && x+w+4>box.x && candidate<box.y+box.h+3 && candidate+h+3>box.y)) { y=candidate; break; }
      }
      Object.assign(label.style,{left:x+'px',top:y+'px'});
      boxes.push({x,y,w,h});
    }
  }

  const structureCache=new WeakMap();
  function drawStructureGuide() {
    const layer=$('structure-layer');layer.replaceChildren();
    $('photon-status').textContent='';
    if(!$('structure-guide').checked || !chart || !candles)return;
    const market=replayChartSource || marketPayload || sourcePayload,bars=market?.candles || [];
    if(!bars.length)return;
    const interval=chartInterval(),strength=boot.run.swingStrength || 2;
    const end=bars.at(-1).time+interval,range=chart.timeScale().getVisibleRange();
    const cutoff=replayActive?Math.min(replayCutoff,end):Math.min(end,Number.isFinite(range?.to)?range.to+interval:end);
    if(market.photonMapping){drawPhotonMapping(market.photonMapping,cutoff,bars,interval,layer);return;}
    let cached=structureCache.get(bars);
    if(!cached || cached.interval!==interval || cached.strength!==strength) {
      cached=cslBuildStructureGuide(bars,interval,strength,64);structureCache.set(bars,cached);
    }
    const view=cslStructureGuideView(cached,cutoff),height=chart.panes()[0].getHeight(),width=chartWrap.clientWidth-76;
    layer.style.height=height+'px';
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('width','100%');svg.setAttribute('height',String(height));svg.style.overflow='hidden';layer.appendChild(svg);
    const make=(kind,attrs,title)=>{const node=document.createElementNS(ns,kind);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));node.style.pointerEvents='stroke';const tip=document.createElementNS(ns,'title');tip.textContent=title;node.appendChild(tip);svg.appendChild(node);return node;};
    const x=time=>{const snapped=Math.floor(time/interval)*interval;const direct=chart.timeScale().timeToCoordinate(snapped);if(direct!=null)return Math.max(0,Math.min(width,direct));return time<bars[0].time?0:width;};
    const occupied=[],labelQueue=[];
    const candleSpacing=Math.max(3,chart.timeScale().options().barSpacing || 6);
    for(const bar of bars) {
      const cx=chart.timeScale().timeToCoordinate(bar.time);
      if(cx==null || cx<0 || cx>width)continue;
      const top=candles.priceToCoordinate(bar.high),bottom=candles.priceToCoordinate(bar.low);
      if(top!=null && bottom!=null)occupied.push({x:cx-candleSpacing*.4-2,y:top-2,w:candleSpacing*.8+4,h:bottom-top+4});
    }
    const queueLabel=(text,cx,cy,color,title,above=true)=>labelQueue.push({text,cx,cy,color,title,above});
    const pivots=view.events.filter(e=>e.kind==='swing').sort((a,b)=>a.time-b.time);
    for(let i=1;i<pivots.length;i++) {
      const a=pivots[i-1],b=pivots[i];if(a.swing===b.swing || a.time===b.time)continue;
      const y1=candles.priceToCoordinate(a.price),y2=candles.priceToCoordinate(b.price);if(y1==null||y2==null)continue;
      make('line',{x1:x(a.time),x2:x(b.time),y1,y2,stroke:'#94a3b8','stroke-width':1,'stroke-opacity':.45},'Confirmed swing structure');
    }
    for(const e of view.events) {
      const right=x(Math.min(cutoff,(e.kind==='sweep'||e.kind==='break')?e.availableAt:(e.endAt ?? cutoff))),left=x(Math.max(view.left,e.from ?? e.time));
      if(e.kind==='fvg'||e.kind==='ifvg') {
        const top=candles.priceToCoordinate(e.top),bottom=candles.priceToCoordinate(e.bottom);if(top==null||bottom==null||bottom<0||top>height)continue;
        if(right<=left)continue;
        const ended=e.endAt!=null,color=ended?'#8295ab':e.side==='LONG'?'#34d399':'#fb7185';
        const name=(e.kind==='ifvg'?'IFVG':'FVG')+' · '+e.status;
        const title=(e.side==='LONG'?'Bullish ':'Bearish ')+name+' '+formatPrice(e.bottom)+' - '+formatPrice(e.top)+'; known '+fmtTime(e.availableAt)+(e.endAt!=null?'; stopped '+fmtTime(e.endAt):'')+'; wick fills, close-through inverts';
        if(right-left>36)queueLabel(name,right-4,Math.max(0,top),color,title);
        make('rect',{x:left,y:Math.max(0,top),width:Math.max(1,right-left),height:Math.max(1,Math.min(height,bottom)-Math.max(0,top)),fill:color,'fill-opacity':ended?.025:e.status==='Tested'?.045:.08,stroke:color,'stroke-opacity':ended?.28:e.status==='Tested'?.5:.7,'stroke-dasharray':ended?'2 4':e.kind==='ifvg'?'4 3':'none'},title);
        continue;
      }
      const y=candles.priceToCoordinate(e.price);if(y==null||y<0||y>height)continue;
      const color=e.kind==='equilibrium'?'#c4b5fd':e.kind==='swing'?(e.swing==='high'?'#fb7185':'#60a5fa'):e.kind==='sweep'?'#fbbf24':'#34d399';
      const name=e.kind==='equilibrium'?'50% equilibrium':e.kind==='swing'?e.label+' swing':e.kind==='sweep'?'Liquidity sweep':'Structure break';
      const title=name+' '+formatPrice(e.price)+'; known '+fmtTime(e.availableAt);
      make('line',{x1:left,x2:right,y1:y,y2:y,stroke:color,'stroke-width':1,'stroke-opacity':e.endAt?.5:.85,'stroke-dasharray':e.kind==='equilibrium'?'5 4':e.kind==='swing'?'2 3':'none'},title);
      if(e.kind!=='equilibrium')make('circle',{cx:x(e.time),cy:y,r:e.kind==='swing'?2:3,fill:color,stroke:color},title);
      queueLabel(e.kind==='swing'?e.label:e.kind==='sweep'?'Sweep':e.kind==='break'?'Break':'50%',e.kind==='swing'?x(e.time):right,y,color,title,e.kind==='swing'?e.swing==='high':true);
    }
    for(const item of labelQueue) {
      const w=item.text.length*6+6,h=13;
      const left=Math.max(2,Math.min(width-w-2,item.cx-w));
      for(const offset of (item.above?[-17,5,-32,20]:[5,-17,20,-32])) {
        const top=item.cy+offset;
        if(top<2 || top+h>height-2)continue;
        if(occupied.some(b=>left<b.x+b.w && left+w>b.x && top<b.y+b.h && top+h>b.y))continue;
        const label=make('text',{x:left+3,y:top+10,fill:item.color,'fill-opacity':.78,'font-size':10,'font-family':'system-ui, sans-serif','font-weight':500,'paint-order':'stroke',stroke:'#0f1720','stroke-width':2.5,'stroke-linejoin':'round'},item.title);
        label.appendChild(document.createTextNode(item.text));
        occupied.push({x:left-3,y:top-2,w:w+6,h:h+4});
        break;
      }
    }
  }

  function drawSupplyDemandOverlay(sd) {
    if (!chart || !candles) return;
    const height=chart.panes()[0].getHeight();
    fvgLayer.style.height=height+'px';
    const bars=payload.candles || [];
    function xAt(time,fallback) {
      let found=null; for(const bar of bars) {if(bar.time>time) break; found=bar.time;}
      return found==null ? fallback : (chart.timeScale().timeToCoordinate(found) ?? fallback);
    }
    const end=xAt(sd.signalTime,chartWrap.clientWidth-76);
    if(sd.strategy==='PHOTON_4H_TREND') {
      for(const [zone,name,color] of [[sd.contextZone,'Context reaction','#a78bfa20'],[sd.parentZone,'15m pullback zone','#60a5fa25']]) {
        if(!zone)continue;
        const a=candles.priceToCoordinate(zone.upper),b=candles.priceToCoordinate(zone.lower);
        if(a==null || b==null || b<0 || a>height)continue;
        const start=Math.max(0,xAt(zone.originTime ?? zone.availableAt,0));
        const band=document.createElement('div');band.className='fvg-zone';band.title=name+' '+formatPrice(zone.lower)+' - '+formatPrice(zone.upper);
        Object.assign(band.style,{left:start+'px',top:Math.max(0,a)+'px',width:Math.max(3,end-start)+'px',height:Math.max(2,Math.min(height,b)-Math.max(0,a))+'px',background:color});fvgLayer.appendChild(band);
      }
      for(const [range,name,color] of [[sd.range4h,'4H','#e2e8f0'],[sd.range15m,'15m','#60a5fa']]) {
        for(const [key,label] of [['low',' low'],['equilibrium',' EQ 50%'],['high',' high']]) {
          const price=range?.[key],y=price==null?null:candles.priceToCoordinate(price);
          if(y==null || y<0 || y>height)continue;
          const start=Math.max(0,xAt(range.knownAt,0));
          const line=document.createElement('div');line.className='fvg-level';line.title=name+label+' '+formatPrice(price);
          Object.assign(line.style,{left:start+'px',top:y+'px',width:Math.max(3,end-start)+'px',borderColor:color});fvgLayer.appendChild(line);
          const note=document.createElement('span');note.className='fvg-note';note.textContent=name+label;
          Object.assign(note.style,{left:(start+3)+'px',top:Math.max(2,y-20)+'px'});fvgLayer.appendChild(note);
        }
      }
    }
    if(sd.strategy==='NY_OPENING_RANGE_REVERSAL') {
      for(const [price,name,color] of [[sd.zone.top,'NY 4h high','#60a5fa'],[sd.zone.bottom,'NY 4h low','#60a5fa'],[sd.stop,sd.stopSource==='CONFIRMED_SR'?'Confirmed S/R stop':'Breakout stop','#ef4444'],[sd.target,'Target '+String(sd.targetR)+'R','#22c55e'],...(sd.overshootPolicy && sd.overshootPolicy!=='DEFAULT' && sd.targetLimit!=null?[[sd.targetLimit,'Allowed target boundary','#a78bfa']]:[])]) {
        const y=candles.priceToCoordinate(price);if(y==null || y<0 || y>height)continue;
        const start=Math.max(0,xAt(sd.zone.pivotTime,0)),line=document.createElement('div');line.className='fvg-level';line.title=name+' '+formatPrice(price);
        Object.assign(line.style,{left:start+'px',top:y+'px',width:Math.max(3,end-start)+'px',borderColor:color});fvgLayer.appendChild(line);
      }
      return;
    }
    if(sd.strategy==='TJR_CONFLUENCE') {
      for(const [zone,name,color] of [[sd.zone,'Entry FVG','#22c55e30'],[sd.inverseFvg,'Inverted FVG','#a78bfa30']]) {
        if(!zone)continue;
        const a=candles.priceToCoordinate(zone.top),b=candles.priceToCoordinate(zone.bottom);
        if(a==null || b==null || b<0 || a>height)continue;
        const start=Math.max(0,xAt(zone.pivotTime,0));
        const band=document.createElement('div');band.className='fvg-zone';
        band.title=name+' '+formatPrice(zone.bottom)+' - '+formatPrice(zone.top);
        Object.assign(band.style,{left:start+'px',top:Math.max(0,a)+'px',width:Math.max(3,end-start)+'px',height:Math.max(2,Math.min(height,b)-Math.max(0,a))+'px',background:color});fvgLayer.appendChild(band);
      }
      for(const [price,time,name,color] of [[sd.liquidityLevel,sd.liquidityTime,'Swept liquidity','#fbbf24'],[sd.structureLevel,sd.sweepTime,'Structure','#60a5fa'],[sd.equilibrium,sd.sweepTime,'50% midpoint','#c4b5fd']]) {
        if(price==null)continue;const y=candles.priceToCoordinate(price);if(y==null || y<0 || y>height)continue;
        const start=Math.max(0,xAt(time,0)),line=document.createElement('div');line.className='fvg-level';line.title=name+' '+formatPrice(price);
        Object.assign(line.style,{left:start+'px',top:y+'px',width:Math.max(3,end-start)+'px',borderColor:color});fvgLayer.appendChild(line);
      }
      return;
    }
    if(sd.strategy==='SNEAKY_PIVOT') {drawSneakyLevels(sd,xAt,height);return;}
    if(sd.liquidity) {
      const price=(Number(sd.liquidity.bottom)+Number(sd.liquidity.top))/2;
      const y=candles.priceToCoordinate(price);
      if(y!=null && y>=0 && y<height) {
        const start=Math.max(0,xAt(sd.liquidity.firstTime,0));
        const stop=Math.max(start,xAt(sd.sweepTime,end));
        const line=document.createElement('div'); line.className='fvg-level';
        Object.assign(line.style,{left:start+'px',top:y+'px',width:Math.max(3,stop-start)+'px',borderColor:'#fbbf24'}); fvgLayer.appendChild(line);
        const label=document.createElement('span'); label.className='fvg-note'; label.textContent=(sd.side==='LONG'?'Equal lows':'Equal highs')+' · liquidity pool';
        Object.assign(label.style,{left:(start+3)+'px',top:Math.max(2,y-22)+'px'}); fvgLayer.appendChild(label);
      }
    }
    for(const [zone,name,color] of [[sd.zone,sd.strategy==='SNEAKY_PIVOT'?'Defended setup range':(sd.side==='LONG'?'Demand entry zone':'Supply entry zone'),'#22c55e30'],...(sd.entryZone?[[sd.entryZone,'Confirmation origin','#60a5fa20']]:[]),[sd.opposingZone,sd.strategy==='SNEAKY_PIVOT'?'Previous UTC day range':(sd.strategy==='IMBALANCE_ORIGIN_RETEST'?(sd.entryZone?(sd.targetSource==='FORMATION_EXTREME'?'Pre-pullback extreme / target':'Saved legacy swing target'):'Displacement range / target'):'Opposing swing / target'),'#ef444430']]) {
      const a=candles.priceToCoordinate(zone.top), b=candles.priceToCoordinate(zone.bottom);
      if(a==null || b==null) continue;
      const start=Math.max(0,xAt(zone.pivotTime,0));
      const band=document.createElement('div'); band.className='fvg-zone';
      Object.assign(band.style,{left:start+'px',top:Math.max(0,a)+'px',width:Math.max(3,end-start)+'px',height:Math.max(2,Math.min(height,b)-Math.max(0,a))+'px',background:color});
      fvgLayer.appendChild(band);
      const label=document.createElement('span'); label.className='fvg-note'; label.textContent=name+' '+formatPrice(zone.bottom)+' – '+formatPrice(zone.top);
      Object.assign(label.style,{left:(start+5)+'px',top:Math.max(2,a-22)+'px'}); fvgLayer.appendChild(label);
    }
    for(const [time,text] of (sd.strategy==='PHOTON_4H_TREND' ? [[sd.contextTouchAt,'4H value reaction'],[sd.alignmentAt,'15m aligned'],[sd.parentTouchAt,'15m zone touch'],[sd.signalAvailableAt,'1m CHoCH armed']] : sd.strategy==='SNEAKY_PIVOT' ? [[sd.zone.touchTime,'Initial level test'],[sd.zone.bounceTime,'Reversal candle'],[sd.signalTime,'Breakout armed']] : sd.strategy==='IMBALANCE_ORIGIN_RETEST' ? [[sd.zone.confirmedTime,'Imbalance confirmed'],[sd.signalTime,'Full fill + origin rejection']] : sd.strategy==='LIQUIDITY_SWEEP_RETEST' ? [[sd.sweepTime,'Liquidity sweep'],[sd.zone.bounceTime,'Displacement'],[sd.signalTime,'Zone retest']] : [[sd.zone.touchTime,'First touch'],[sd.zone.bounceTime,'Bounce confirmed'],[sd.signalTime,'Directional retest']])) {
      if(time==null) continue;
      const label=document.createElement('span'); label.className='fvg-note'; label.textContent=text;
      Object.assign(label.style,{left:Math.max(2,xAt(time,0))+'px',top:Math.max(4,(candles.priceToCoordinate(sd.zone.top) ?? 30)+8)+'px'}); fvgLayer.appendChild(label);
    }
  }

  function drawFvgOverlay() {
    fvgLayer.replaceChildren();
    if($('structure-guide').checked && !boot.run.photonTrading)return;
    if(dayMode && payload?.dayContext && chart && candles) {
      const height=chart.panes()[0].getHeight(),right=chartWrap.clientWidth-76;
      fvgLayer.style.height=height+'px';
      for(const level of payload.dayContext.levels || []) {
        const y=candles.priceToCoordinate(level.price);if(level.price==null || y==null || y<0 || y>height)continue;
        const line=document.createElement('div');line.className='fvg-level';
        const origin=level.time ?? payload.dayContext.day;
        const originBar=(payload.candles || []).find(bar=>bar.time>=origin);
        const left=originBar?Math.max(0,chart.timeScale().timeToCoordinate(originBar.time) ?? 0):0;
        Object.assign(line.style,{left:left+'px',top:y+'px',width:Math.max(0,right-left)+'px',borderColor:level.role.endsWith('High')?'#fb7185':'#60a5fa'});fvgLayer.appendChild(line);
        const label=document.createElement('span');label.className='fvg-note';label.textContent=level.label+' · '+formatPrice(level.price);
        Object.assign(label.style,{left:'12px',top:Math.max(2,y-24)+'px'});fvgLayer.appendChild(label);
      }
      return;
    }
    const fvg=payload?.fvgDerivation;
    const sd=payload?.supplyDemandDerivation;
    if (sd?.status==='AVAILABLE') { drawSupplyDemandOverlay(sd); return; }
    if (!chart || !candles || fvg?.status !== 'AVAILABLE') return;
    const paneHeight=chart.panes()[0].getHeight();
    fvgLayer.style.height=paneHeight+'px';
    const right=Math.max(0,chartWrap.clientWidth-76);
    const bars=payload.candles || [];
    const intervalMatch=String(boot.run.timeframe).match(/^([0-9]+)([mhdw])$/);
    const strategySeconds=intervalMatch ? Number(intervalMatch[1])*({m:60,h:3600,d:86400,w:604800}[intervalMatch[2]]) : 900;
    function xAt(time,fallback) {
      let found=null;
      for (const bar of bars) { if (bar.time>time) break; found=bar.time; }
      return found == null ? fallback : (chart.timeScale().timeToCoordinate(found) ?? fallback);
    }
    const left=Math.max(0,Math.min(right,xAt(fvg.formedTime,0)));
    const end=Math.max(left,Math.min(right,xAt(fvg.signalTime,right)));
    const originX=Math.max(0,Math.min(right,xAt(fvg.impulseStartTime,0)));
    const yAt=price=>candles.priceToCoordinate(Number(price));
    function note(text,x,y,color='#b6f6ff') {
      if (y == null || y<0 || y>paneHeight) return;
      const label=document.createElement('span'); label.className='fvg-note';
      label.textContent=text;
      Object.assign(label.style,{left:x+'px',top:Math.max(2,y-24)+'px',color});
      fvgLayer.appendChild(label);
    }
    function band(low,high,x1,x2,color,className='fvg-band') {
      const a=yAt(high), b=yAt(low);
      if (a==null || b==null) return;
      const top=Math.max(0,Math.min(a,b)), bottom=Math.min(paneHeight,Math.max(a,b));
      if (bottom<=top) return;
      const el=document.createElement('div'); el.className=className;
      Object.assign(el.style,{left:x1+'px',top:top+'px',width:Math.max(3,x2-x1)+'px',height:Math.max(2,bottom-top)+'px',background:color});
      fvgLayer.appendChild(el);
    }
    const swingLow=Math.min(fvg.impulseOrigin,fvg.impulseExtreme);
    const swingHigh=Math.max(fvg.impulseOrigin,fvg.impulseExtreme);
    band(fvg.midpoint,swingHigh,originX,end,'#f871710c');
    band(swingLow,fvg.midpoint,originX,end,'#34d3990c');
    note('Premium',originX+5,yAt(swingHigh),'#fda4af');
    note('Discount',originX+5,yAt(fvg.midpoint),'#6ee7b7');
    band(fvg.bottom,fvg.top,left,end,'#22d3ee35','fvg-zone');
    note((fvg.side==='LONG'?'Bullish':'Bearish')+' FVG',left+5,yAt(fvg.top));
    for (const [price,name] of [[fvg.impulseOrigin,'Swing origin'],[fvg.midpoint,'50% equilibrium'],[fvg.impulseExtreme,'Swing extreme'],[fvg.confluenceLevel,'S/R confluence']]) {
      const y=yAt(price); if(y==null || y<0 || y>=paneHeight) continue;
      const line=document.createElement('div'); line.className='fvg-level';
      Object.assign(line.style,{left:originX+'px',width:Math.max(3,end-originX)+'px',top:y+'px',borderColor:name==='S/R confluence'?'#c084fc':'#d6ad49'});
      fvgLayer.appendChild(line); note(name+' '+formatPrice(price),originX+5,y);
    }
    // Exact pivot/break anchors are saved for new runs. Old snapshots retain
    // their levels without inventing a break candle or pivot timestamp.
    if (fvg.structurePivotTime && fvg.structureBreakTime) {
      const bx=xAt(fvg.structureBreakTime,end), px=xAt(fvg.structurePivotTime,originX), y=yAt(fvg.structureLevel);
      if(y!=null && y>=0 && y<paneHeight) {
        const line=document.createElement('div'); line.className='fvg-level';
        Object.assign(line.style,{left:Math.max(0,px)+'px',width:Math.max(3,bx-Math.max(0,px))+'px',top:y+'px',borderTop:'2px solid #fb923c'});
        fvgLayer.appendChild(line); note('BOS',bx+5,y,'#fdba74');
      }
    } else note('BOS level '+formatPrice(fvg.structureLevel),left+5,yAt(fvg.structureLevel),'#fdba74');
    const formation=fvg.formationCandles || [2,1,0].map(offset=>bars.find(bar=>bar.time===fvg.formedTime-offset*strategySeconds)).filter(Boolean);
    const onStrategy=(payload.chartTimeframe || boot.run.timeframe)===boot.run.timeframe;
    formation.forEach((bar,index)=>{
      if (!bars.length || bar.time<bars[0].time || bar.time>bars[bars.length-1].time) return;
      const x=xAt(bar.time,left), hi=yAt(bar.high), lo=yAt(bar.low);
      if(x<0 || x>right || hi==null || lo==null) return;
      // On aggregated charts the three original candles may occupy one bar.
      const half=Math.max(3,Math.min(25,chart.timeScale().options().barSpacing*.4));
      if(onStrategy) band(bar.low,bar.high,x-half,x+half,index===1?'#fbbf2435':'#e2e8f015','formation-candle');
      note(onStrategy ? String(index+1)+(index===1?' Displacement':'') : 'Formation '+String(index+1),x-6,Math.min(hi,lo)-8,'#f8fafc');
    });
    const confirmation=bars.find(bar=>bar.time<=fvg.signalTime && bar.time+strategySeconds>fvg.signalTime) || bars.find(bar=>bar.time===fvg.signalTime);
    const signalY=yAt(confirmation?.close ?? (fvg.bottom+fvg.top)/2);
    note('First revisit / confirmation',end+8,signalY,'#67e8f9');
    if (fvg.targetZone) {
      const zone=fvg.targetZone;
      band(zone.bottom,zone.top,end,right,'#a78bfa25');
      note(String(zone.timeframe_minutes)+'m opposing FVG target',end+8,yAt(zone.top),'#c4b5fd');
    }
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
    if(dayMode)diag.textContent='MANUAL DAY REVIEW · '+$('replay-day').value+' UTC · No automatic trade selected.\\nReplay time: '+fmtTime(replayCutoff)+'\\nManual plans and confirmations are recorded separately; no manual P&L is simulated.';
    const sd=payload.supplyDemandDerivation;
    if(sd?.status==='AVAILABLE') {
      fvgReview.hidden=false; $('setup-panel').hidden=false; $('review-setup').hidden=false;
      $('review-setup').setAttribute('aria-pressed',String(reviewMode));
      $('setup-panel').setAttribute('aria-label','Supply and demand setup explanation');
      fvgReview.textContent=(sd.strategy==='PHOTON_4H_TREND'?'Photon 4H trend':sd.strategy==='NY_OPENING_RANGE_REVERSAL'?'NY opening range':sd.strategy==='IMBALANCE_ORIGIN_RETEST'?'Imbalance origin':sd.strategy==='TJR_CONFLUENCE'?'Confluence':sd.strategy==='SNEAKY_PIVOT'?'Sneaky Pivot':sd.strategy==='LIQUIDITY_SWEEP_RETEST'?'Liquidity sweep':'Supply & demand')+' · '+sd.side+' · Setup details →';
      const panel=$('setup-panel'); panel.replaceChildren();
      const title=document.createElement('h3'); title.textContent=sd.strategy==='PHOTON_4H_TREND'?'4H value reaction → 15m alignment → pullback → 1m CHoCH → origin retest':sd.strategy==='NY_OPENING_RANGE_REVERSAL'?'New York 4h range → outside close → inside close':sd.strategy==='IMBALANCE_ORIGIN_RETEST'?(sd.entryZone?'Inducement → structure shift → origin retest':'Full imbalance fill → origin rejection'):sd.strategy==='TJR_CONFLUENCE'?'Sweep + structure + IFVG + FVG pullback':sd.strategy==='SNEAKY_PIVOT'?'All-day level test → reversal → breakout':sd.strategy==='LIQUIDITY_SWEEP_RETEST'?'Trend + liquidity sweep + zone retest':'1h confirmed swing retest'; panel.appendChild(title);
      const facts=document.createElement('p'); facts.style.whiteSpace='pre-line';
      facts.textContent='Zone confirmed: '+fmtTime(sd.zone.confirmedTime)+'\\nFirst touch: '+fmtTime(sd.zone.touchTime)+'\\nBounce: '+fmtTime(sd.zone.bounceTime)+'\\nRetest: '+fmtTime(sd.signalTime)+'\\nTarget swing: '+formatPrice(sd.target)+'\\nEntry is the next candle open. Zones are saved decision-time evidence.';
      if(sd.strategy==='NY_OPENING_RANGE_REVERSAL') facts.textContent='New York session '+String(sd.sessionDay)+'; range ready '+fmtTime(sd.zone.confirmedTime)+'; outside close candle '+fmtTime(sd.breakoutTime)+'; inside close candle '+fmtTime(sd.signalTime)+'. '+(sd.stopSource==='CONFIRMED_SR'?'Confirmed S/R stop ':'Breakout extreme stop ')+formatPrice(sd.stop)+'; actual-fill target '+String(sd.targetR)+'R ('+formatPrice(sd.target)+'). Entry at next open, still inside the range and within the same New York day. Range uses four elapsed hours from New York midnight; saved decision-time evidence.';
      if(sd.strategy==='NY_OPENING_RANGE_REVERSAL' && sd.overshootPolicy) facts.textContent+=' Policy: '+String(sd.overshootPolicy)+'; target allowance '+String(sd.allowedExtensionPct)+'% of range height'+(sd.targetLimit!=null?' (boundary '+formatPrice(sd.targetLimit)+')':'')+(sd.stopSource==='CONFIRMED_SR'?'; original breakout stop '+formatPrice(sd.originalStop)+'; selected S/R boundary '+formatPrice(sd.srBoundary)+'; context available '+fmtTime(sd.srAvailableAt):'')+'.';
      if(sd.entryZone) facts.textContent='HTF structure close: '+fmtTime(sd.structureBreakTime)+'; origin touch: '+fmtTime(sd.zone.touchTime)+'; lower-timeframe shift: '+fmtTime(sd.shiftTime)+'; confirmation origin retest: '+fmtTime(sd.signalTime)+'. Reversal extreme '+formatPrice(sd.reversalExtreme)+'; '+(sd.targetSource==='FORMATION_EXTREME'?'pre-pullback extreme target ':'saved legacy swing target ')+formatPrice(sd.target)+'. Entry at next open. All zones and timestamps are saved decision-time evidence.';
      if(sd.strategy==='SNEAKY_PIVOT') facts.textContent='Initial test: '+fmtTime(sd.zone.touchTime)+'; reversal: '+fmtTime(sd.signalTime)+'; '+String(sd.levelName)+' '+formatPrice(sd.level)+'; breakout trigger '+formatPrice(sd.trigger)+'; stop '+formatPrice(sd.stop)+(sd.stopSource?' ('+String(sd.stopSource)+')':' (legacy defended-level rule)')+'; fixed target '+formatPrice(sd.target)+'. Enter only on a breakout during the next 15m candle using 1m data. Previous-day levels are fixed at setup; no session restriction.';
      if(sd.strategy==='SNEAKY_PIVOT') {
        const levels=document.createElement('p'); levels.style.whiteSpace='pre-line';
        levels.textContent=(sd.levelsSource || 'Saved at setup')+'\\n'+(sd.levels || []).map(level=>level.label+': '+(level.price==null?'Unavailable in the pre-setup history':formatPrice(level.price))).join('\\n');panel.appendChild(levels);
      }
      if(sd.sweepTime!=null && sd.liquidity) {
        const sweep=document.createElement('p'); sweep.textContent='Equal-level pool: '+formatPrice(sd.liquidity.bottom)+' – '+formatPrice(sd.liquidity.top)+'; swept '+fmtTime(sd.sweepTime)+'. A later displacement confirms the entry zone.'; panel.appendChild(sweep);
      }
      if(sd.strategy==='TJR_CONFLUENCE') facts.textContent='Sweep: '+fmtTime(sd.sweepTime)+'; structure close: '+fmtTime(sd.structureTime)+'; FVG inversion: '+fmtTime(sd.inverseTime)+'; pullback confirmation: '+fmtTime(sd.signalTime)+'. Midpoint '+formatPrice(sd.equilibrium)+'. SL beyond sweep; target '+String(sd.targetR)+'R. Entry at next candle open. Lines and zones show saved setup evidence; prices on hover.';
      if(sd.strategy==='PHOTON_4H_TREND') facts.textContent='4H value reaction: '+fmtTime(sd.contextTouchAt)+'; 15m aligned structure: '+fmtTime(sd.alignmentAt)+'; later 15m zone pullback: '+fmtTime(sd.parentTouchAt)+'; 1m CHoCH known: '+fmtTime(sd.signalAvailableAt)+'. Limit '+formatPrice(sd.entry)+' at the 1m origin; stop '+formatPrice(sd.stop)+'; frozen '+(sd.targetMode==='4H_SWING'?'4H':'15m')+' swing target '+formatPrice(sd.target)+'. Fill requires a later 1m retest. Daily/weekly are context; every trade follows the 4H swing. Same-minute stops count; entry-minute profits are deferred. Saved decision-time evidence.';
      panel.appendChild(facts); return;
    }
    const fvg = payload.fvgDerivation;
    fvgReview.hidden = fvg?.status !== 'AVAILABLE';
    $('setup-panel').hidden = fvgReview.hidden;
    $('review-setup').hidden = fvgReview.hidden;
    if (fvgReview.hidden) reviewMode=false;
    $('review-setup').setAttribute('aria-pressed',String(reviewMode));
    if (!fvgReview.hidden) {
      fvgReview.textContent = reviewMode ? 'Setup review · EMAs temporarily hidden · original indicator selections retained' : 'FVG six-factor v1 · '+fvg.side+' · Setup details →';
      const panel=$('setup-panel'); panel.replaceChildren();
      const heading=document.createElement('h3'); heading.textContent=(fvg.side==='LONG'?'Bullish':'Bearish')+' FVG setup'; panel.appendChild(heading);
      for (const [name,pass] of Object.entries(fvg.checks || {})) {
        const row=document.createElement('div'); row.className='setup-check'; row.textContent=(pass?'✓ ':'✕ ')+name; panel.appendChild(row);
      }
      const facts=document.createElement('div'); facts.className='setup-facts';
      facts.textContent='Gap: '+formatPrice(fvg.bottom)+' – '+formatPrice(fvg.top)+'\\nConfirmation: '+fmtTime(fvg.signalTime)+'\\nEntry: '+String(trade['Entry Time'] || trade.entryTime || 'n/a')+'\\nFormation candles: 1 / 2 displacement / 3\\nOrange: BOS · Purple: S/R\\nRed half: premium · Green half: discount';
      facts.style.whiteSpace='pre-line'; panel.appendChild(facts);
      if (fvg.targetZone) {
        const target=document.createElement('p');
        target.textContent='TP: nearest opposing '+fvg.targetZone.timeframe_minutes+'m FVG '+formatPrice(fvg.targetZone.bottom)+' – '+formatPrice(fvg.targetZone.top)+'; confirmed '+fmtTime(fvg.targetZone.confirmedTime)+'. Target fixed at entry with a buffer before the near edge.';
        panel.appendChild(target);
      }
      if(fvg.separation) {
        const spacing=document.createElement('div'); spacing.className='setup-check';
        spacing.textContent='✓ Separation: '+fvg.separation.clearBars+' clear candles (minimum '+fvg.separation.requiredClearBars+') · '+Number(fvg.separation.moveAwayAtr).toFixed(2)+' ATR away (minimum '+fvg.separation.requiredMoveAwayAtr+')';
        panel.appendChild(spacing);
      } else {
        const spacing=document.createElement('p'); spacing.className='muted'; spacing.textContent='Older run: separation filters were not recorded. Run a new backtest to apply them.'; panel.appendChild(spacing);
      }
      if (!fvg.structureBreakTime) {
        const note=document.createElement('p'); note.className='muted'; note.textContent='Older run: exact BOS candle was not saved. The saved level is shown. New runs include exact anchors.'; panel.appendChild(note);
      }
    }
  }

  function addTradeLabel(x,y,className,text) {
    if (![x,y].every(v => v != null && Number.isFinite(Number(v)))) return;
    const label=document.createElement('div');
    label.className='trade-label '+className;
    label.title=text;
    label.style.left=Math.max(2,Number(x))+'px';
    label.style.top=Math.max(2,Number(y)-10)+'px';
    label.textContent=text;
    tradeBoxLayer.appendChild(label);
    return label;
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

  function showManualBox() {
    if(chart && payload && manualPlanDraft){
      const time=displayCandleTime(manualPlanDraft.entryTime),index=(payload.candles || []).findIndex(bar=>bar.time===time);
      const range=chart.timeScale().getVisibleLogicalRange();
      if(range && index>=0){
        const padding=Math.max(12,Math.ceil(72/chart.timeScale().options().barSpacing));
        const shift=index<range.from?index-range.from-2:Math.max(0,index+padding-range.to);
        if(shift)chart.timeScale().setVisibleLogicalRange({from:range.from+shift,to:range.to+shift});
      }
    }
    resetPriceScale();redrawOverlays();
  }

  $('trade-card-corner').addEventListener('click',()=>workspacePanels.show('plan'));
  for(const id of ['trade-card-risk','trade-card-percent','trade-card-equity'])$(id).addEventListener('input',()=>drawTradeBox());
  $('trade-card-risk-mode').addEventListener('change',()=>drawTradeBox());
  for(const type of ['pointerdown','pointermove','pointerup','click','dblclick','wheel'])$('trade-card').addEventListener(type,event=>event.stopPropagation());
  function refreshTradeCard(plan,price,closed) {
    const record=currentReview(),card=$('trade-card'),values=$('trade-card-values');
    card.hidden=false;values.replaceChildren();
    const side=record?.side || sourcePayload?.selectedTrade?.Side;
    $('trade-card-title').textContent=(closed?'Closed':record?.manualEntry?'Open':'Preview')+' · '+side+' · Trade estimate';
    const mode=$('trade-card-risk-mode').value,costs=boot.run.manualCosts;
    $('trade-card-amount-field').hidden=mode==='percent';
    $('trade-card-percent-field').hidden=mode!=='percent';$('trade-card-equity-field').hidden=mode!=='percent';
    const currency=['USDT','USDC','BUSD','USD','BTC','ETH'].find(unit=>boot.run.symbol?.endsWith(unit)) || 'quote';
    $('trade-card-risk-label').textContent='Risk ('+currency+')';$('trade-card-equity-label').textContent='Equity ('+currency+')';
    const sizing=cslRiskPositionSize({...plan,side},record,Number($('trade-card-risk').value),Number($('trade-card-percent').value),Number($('trade-card-equity').value),mode,costs);
    $('trade-card-risk-note').textContent=sizing.error || (sizing.costsIncluded?'Risk includes estimated fees and slippage at the initial stop.':'Risk uses price movement only; run fee/slippage settings are unavailable.');
    const amount=sizing.notional;
    const quote=p=>cslTradeCardQuote({...plan,side},record,p,amount,costs,replayCutoff);
    const current=quote(price),tp=quote(plan.target),sl=quote(plan.stop);
    const money=v=>v==null?'Unavailable':(v>0?'+':'')+v.toFixed(2);
    const row=(name,value,tone='')=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;dd.className=tone;values.append(dt,dd);};
    row('Entry',formatPrice(plan.entry));row('Stop loss',formatPrice(plan.stop));row('Take profit',formatPrice(plan.target));
    if(!current || !tp || !sl){row('Estimate',sizing.error?'Check risk inputs':'Enter valid trade levels');return;}
    row('Risk budget',sizing.riskBudget.toFixed(2)+' '+currency);
    row('Position value',amount.toFixed(2)+' '+currency);
    row('Quantity / remaining',current.quantity.toFixed(6)+' / '+(current.remainingFraction*100).toFixed(1)+'%');
    const result=(name,q)=>row(name,q.net==null?'Unavailable':money(q.net)+' ('+money(q.net/sizing.riskBudget)+'R)',q.net==null?'':q.net>=0?'trade-card-positive':'trade-card-negative');
    if(record?.manualEntry)result(closed?'Net result est.':'Net if closed now',current);
    if(!closed){result('Net at target',tp);result('Net at stop',sl);}
    const basis=record?.manualEntry?current:tp;
    row(record?.manualEntry?'Fees est. · exit here':'Fees est. · target exit',basis.fees==null?'Unavailable':basis.fees.toFixed(2));
    row('Slippage est.',basis.slippage==null?'Unavailable':basis.slippage.toFixed(2));
    row('Gross R · '+(record?.manualEntry?'current':'target'),basis.grossR.toFixed(2)+'R');
  }
  function drawTradeBox() {
    tradeBoxLayer.replaceChildren();
    if(boot.run.mappingOnly){$('trade-card').hidden=true;return;}
    $('trade-card').hidden=!(payload && chart && candles && replayActive && manualPlanDraft);
    if (!payload || !chart || !candles) return;
    const manual=Boolean(replayActive && manualPlanDraft);
    const boxUnplaced=manual && (currentReview()?.positionBoxHidden || (currentReview()?.positionBoxPlaced===false && !currentReview()?.manualEntry));
    let shownPlan=manual && positionResize?.price!=null?{...manualPlanDraft,[positionResize.key]:positionResize.price}:manualPlanDraft;
    if(manual && positionResize?.key==='entry' && positionResize.price!=null){const delta=positionResize.price-manualPlanDraft.entry;shownPlan={...shownPlan,stop:manualPlanDraft.stop+delta,target:manualPlanDraft.target+delta};}
    const trade=manual ? {...payload.selectedTrade,Entry:shownPlan.entry,Stop:shownPlan.stop,Target:shownPlan.target} : (payload.selectedTrade || {});
    const markers=payload.markers || [];
    const open=markers.find(m => String(m.kind)==='selected-open');
    const exit=markers.find(m => String(m.kind)==='exit');
    if (!open && !manual) return;

    const entry=Number(trade.Entry ?? trade.entry);
    const stop=Number(trade.Stop ?? trade.stop);
    const target=Number(trade.Target ?? trade.target);
    const exitPrice=Number(trade.Exit ?? trade.exit);
    const x1=chart.timeScale().timeToCoordinate(displayCandleTime(manual ? manualPlanDraft.entryTime : Number(open.time)));
    const endTime=exit ? Number(exit.time) : Number(payload.selectedTradeViewEnd);
    const manualExit=manual && currentReview()?.manualExit;
    const visibleManualExit=manualExit && (manualExit.availableAt ?? manualExit.candleTime+manualInterval())<=replayCutoff;
    const lastVisible=(payload.candles || []).at(-1);
    const boxBars=positionResize?.key==='width'?positionResize.bars:currentReview()?.manualBoxBars;
    const x2=manual?Number(x1)+cslPositionBoxWidth(chart.timeScale().options().barSpacing,boxBars):(replayActive && !replayOutcomeVisible)?Number(x1)+100:chart.timeScale().timeToCoordinate(endTime);
    const entryY=candles.priceToCoordinate(entry);
    const stopY=candles.priceToCoordinate(stop);
    const targetY=candles.priceToCoordinate(target);
    const exitY=candles.priceToCoordinate(exitPrice);
    if(manual)refreshTradeCard(shownPlan,visibleManualExit?manualExit.price:lastVisible?.close ?? entry,visibleManualExit);
    if(boxUnplaced)return;
    if ([x1,x2,entryY].some(v => v == null || !Number.isFinite(Number(v)))) return;

    const left=Math.min(Number(x1),Number(x2));
    const right=Math.max(Number(x1),Number(x2));
    const width=Math.max(manual?72:48,right-left);

    function rect(a,b,className){
      if ([a,b].some(v => v == null || !Number.isFinite(Number(v)))) return;
      const el=document.createElement('div');
      el.className='trade-rect '+className;
      if(manual && selectedChartObject?.type==='position' && selectedChartObject.key===replayKey())el.classList.add('selected-position');
      if(manual && $('drawing-tool').value==='cursor' && !manualPick){el.style.pointerEvents='auto';el.style.cursor='pointer';el.title='Click to select · Delete hides this box';el.addEventListener('click',event=>{event.stopPropagation();chartWrap.focus({preventScroll:true});selectedChartObject={type:'position',key:replayKey()};$('drawing-selected').value='';drawUserDrawings();drawTradeBox();});}
      if(manual && (!currentReview()?.manualEntry || manualPlanDraft.error)){el.style.borderStyle='dashed';el.style.opacity='.65';}
      el.style.left=left+'px';
      el.style.width=width+'px';
      el.style.top=Math.min(Number(a),Number(b))+'px';
      el.style.height=Math.max(2,Math.abs(Number(b)-Number(a)))+'px';
      tradeBoxLayer.appendChild(el);
    }
    if(manual && (!manualPlanLocked() || !manualCloseLocked())) {
      for(const [key,y] of [['stop',stopY],['target',targetY],...(!manualPlanLocked()?[['entry',entryY]]:[])]) {
        if(y==null)continue;
        const handle=document.createElement('div');handle.className='position-handle';handle.dataset.positionLevel=key;
        handle.title='Drag '+(key==='stop'?'SL':key==='target'?'TP':'entry');handle.setAttribute('aria-label',handle.title);
        Object.assign(handle.style,{left:(left-5)+'px',top:(y-5)+'px',width:'10px'});tradeBoxLayer.appendChild(handle);
      }
    }
    if(manual) {
      const label=document.createElement('span');label.className='position-side-label';label.textContent=String(trade.Side).toUpperCase();
      Object.assign(label.style,{left:(left+8)+'px',top:(entryY-19)+'px',color:String(trade.Side).toUpperCase()==='SHORT'?'#fda4af':'#6ee7b7'});tradeBoxLayer.appendChild(label);
      const handle=document.createElement('div');handle.className='position-handle position-width-handle';handle.dataset.positionLevel='width';handle.dataset.boxLeft=String(left);handle.title='Drag to resize the position box width';handle.setAttribute('aria-label',handle.title);
      Object.assign(handle.style,{left:(right-5)+'px',top:(entryY-5)+'px',width:'10px'});tradeBoxLayer.appendChild(handle);
    }
    const currentPrice=visibleManualExit?manualExit.price:lastVisible?.close;
    const signedMove=(String(trade.Side).toUpperCase()==='SHORT'?-1:1)*(Number(currentPrice)-entry);
    rect(entryY,stopY,'risk'+(manual && signedMove<0?' current-loss':''));
    rect(entryY,targetY,'reward'+(manual && signedMove>0?' current-profit':''));
    if(!manual)addTradeLabel(left+4,entryY,'entry','Entry '+formatPrice(trade.Entry ?? trade.entry));
    if (!manual && !visibleManualExit && exit && Number.isFinite(exitPrice))
      addTradeLabel(Math.max(left+4,right-90),exitY,'exit',(manual?'Auto exit (':'Exit (')+String(trade['Exit Reason'] || 'closed')+') '+formatPrice(trade.Exit ?? trade.exit));

    const boundaryX=right+6;
    const hasPartial=manual && (currentReview()?.partialExits || []).some(p=>p.effectiveAt<=replayCutoff);
    const targetR=hasPartial?cslManualSettlement(currentReview(),target,replayCutoff).grossR:cslTargetR({entry,stop,target},trade.Side,manual?currentReview()?.manualEntry:null);
    const targetRText=targetR==null?'':' · '+targetR.toFixed(2)+'R';
    if (!manual && Number.isFinite(target))
      addTradeLabel(boundaryX,targetY,'tp','Target '+formatPrice(trade.Target ?? trade.target)+targetRText);
    if (!manual && Number.isFinite(stop))
      addTradeLabel(boundaryX,stopY,'sl','Stop '+formatPrice(trade.Stop ?? trade.stop));
  }

  function buildChart() {
    chartResizeObserver?.disconnect();
    if (chart) chart.remove();
    trendEmaLines = [];
    rsiSeries = null;
    replaySeries=[];
    chart = window.LightweightCharts.createChart($('chart'),{
      autoSize:true,
      layout:{background:{type:'solid',color:'#131722'},textColor:'#9598a1',fontFamily:'Segoe UI, Arial, sans-serif'},
      grid:{vertLines:{color:'#202430'},horzLines:{color:'#202430'}},
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
      upColor:'#089981',downColor:'#f23645',borderVisible:false,
      wickUpColor:'#089981',wickDownColor:'#f23645',
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
    applyPhotonDisplay();
    replaySeries.push({series:candles,kind:'candles',data:payload.candles || []});
    chart.subscribeClick(event=>{
      if(drawingClick(event))return;
      if(!manualPick){selectedChartObject=null;$('drawing-selected').value='';drawUserDrawings();drawTradeBox();}
      if(manualPick==='exit'){
        if(manualCloseLocked())return;
        const point=drawingPoint(event);if(point)closeManualPosition({time:point.time,price:point.price});return;
      }
      if(!replayActive || !manualPick || manualPlanLocked() || !event.point || event.point.y<0 || event.point.y>chart.panes()[0].getHeight()) return;
      if(manualPick==='position') {
        const time=Number(event.time),record=ensureReview(),first=Math.max(replayDay,record.tradeNotBefore ?? replayDay);
        if(event.time==null || !Number.isFinite(time) || time<first || time+chartInterval()>replayCutoff || !(payload.candles || []).some(b=>b.time===time)) {
          $('position-placement-hint').textContent='Choose a closed candle on this day, after the previous trade exit.';return;
        }
        const entry=candles.coordinateToPrice(event.point.y),side=$('day-side').value;
        const stop=candles.coordinateToPrice(event.point.y+(side==='LONG'?48:-48));
        const plan=cslPositionToolPlan(side,entry,time,stop,chartInterval(),currentTimeframe);if(plan.error)return;
        record.positionBoxPlaced=true;record.positionBoxHidden=false;record.manualBoxBars=null;selectedChartObject={type:'position',key:replayKey()};
        loadManualPlan(plan);storeManualPlan();saveReviews();positionToolsButton.setAttribute('aria-pressed','false');$('position-placement-hint').hidden=true;workspacePanels.show('plan');redrawOverlays();return;
      }
      if(manualPick==='candle') {
        const time=Number(event.time);
        const closed=event.time!=null && time+chartInterval()<=replayCutoff;
        const first=Math.max(automaticPlan().entryTime,currentReview()?.tradeNotBefore ?? -Infinity);
        if(!closed || !Number.isFinite(time) || time<first || !(payload.candles || []).some(bar=>bar.time===time)) {
          manualEntryMessage=dayMode?'Choose a closed candle in this UTC day.':'Choose a closed candle at or after the automatic entry.';manualPick=null;chartWrap.style.cursor='';refreshManualPlan();return;
        }
        ensureReview().positionBoxPlaced=true;ensureReview().positionBoxHidden=false;selectedChartObject={type:'position',key:replayKey()};manualEntryTime=time;manualEntryInterval=chartInterval();manualEntryTimeframe=currentTimeframe;manualEntryMessage='';manualPick=null;chartWrap.style.cursor='';refreshManualPlan();showManualBox();return;
      }
      const price=candles.coordinateToPrice(event.point.y);
      if(price==null || !Number.isFinite(price) || price<=0) return;
      ensureReview().positionBoxPlaced=true;$('manual-'+manualPick).value=Number(price.toPrecision(12));
      manualPick=null;chartWrap.style.cursor='';refreshManualPlan();resetPriceScale();
    });
    const selectedEmas = new Set([...document.querySelectorAll('.ema-period:checked')].map(input => Number(input.value)));
    if (selectedEmas.size && !reviewMode) {
      for (const overlay of (payload.overlays || [])) {
        if (overlay.kind !== 'ema' || !selectedEmas.has(Number(overlay.period))) continue;
        const emaColors = {9:'#60a5fa',20:'#4ade80',50:'#fb923c',100:'#a78bfa',200:'#e879f9',320:'#facc15',1600:'#fb7185'};
        const series=chart.addSeries(window.LightweightCharts.LineSeries,{
          color:boot.run.emaReversal && Number(overlay.period)===100 ? '#3b82f6' : Number(overlay.period)===300 ? '#ef4444' : emaColors[Number(overlay.period)] || '#e2e8f0',
          lineWidth:2,priceLineVisible:false,lastValueVisible:true,
          crosshairMarkerVisible:false,
          // Share candle coordinates, but do not let trend EMA lines enlarge
          // the auto price range and override custom vertical zoom/pan.
          autoscaleInfoProvider: () => null,
          title:overlay.name,
        });
        series.setData(overlay.data || []);
        replaySeries.push({series,kind:overlay.kind,period:overlay.period,data:overlay.data || []});
        trendEmaLines.push(series);
      }
    }
    const selectedRsi = new Set([...document.querySelectorAll('.rsi-line:checked')].map(input => input.value));
    const rsiOverlays = (payload.overlays || []).filter(o => ((o.kind === 'ema_rsi' && [224,1120].includes(Number(o.period))) || (o.kind === 'rsi' && Number(o.period) === 14)) && selectedRsi.has(o.kind + ':' + o.period));
    if (rsiOverlays.length && $('show-rsi').checked) {
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
      replaySeries.push({series:line,kind:overlay.kind,period:overlay.period,data:overlay.data || []});
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
    chart.subscribeCrosshairMove(event=>{if(!drawingPoints.length)return;drawingHover=drawingPoint(event);drawUserDrawings();});
    if (window.ResizeObserver) {
      chartResizeObserver=new ResizeObserver(redraw);
      chartResizeObserver.observe($('chart-wrap'));
    }
    requestAnimationFrame(() => {
      if(boot.run.mappingOnly && $('photon-view').value==='LINES')chart.timeScale().fitContent();
      redraw();
      setTimeout(redraw, 40);
    });
  }

  function updateReplayChart() {
    const range=chart.timeScale().getVisibleLogicalRange(),previousCount=replaySeries[0]?.data.length || 0;
    for(const item of replaySeries){
      const next=item.kind==='candles'?(payload.candles || []):((payload.overlays || []).find(o=>o.kind===item.kind && o.period===item.period)?.data || []);
      const delta=cslSeriesTail(item.data,next);
      if(delta.reset)item.series.setData(next);else for(const point of delta.points)item.series.update(point);
      item.data=next;
    }
    if(range){const shift=$('replay-follow').checked?(payload.candles.length-previousCount):0;chart.timeScale().setVisibleLogicalRange({from:range.from+shift,to:range.to+shift});}
    requestAnimationFrame(redrawOverlays);
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

  function replayBounds() {
    if(dayMode)return {from:replayDay-86400,to:replayCutoff+12*replayInterval};
    const sd=payload?.supplyDemandDerivation;
    if(sd?.status==='AVAILABLE') return {from:Math.min(sd.zone.pivotTime,sd.opposingZone?.pivotTime ?? sd.inverseFvg?.pivotTime ?? sd.sweepTime ?? sd.zone.pivotTime)-8*replayInterval,to:replayCutoff+12*replayInterval};
    const known=payload?.fvgDerivation;
    const from=known?.status==='AVAILABLE' ? known.impulseStartTime-8*replayInterval : replayCutoff-80*replayInterval;
    return {from,to:replayCutoff+12*replayInterval};
  }

  function setupBounds() {
    if(replayActive && !replayRevealed) return null;
    const sd=payload?.supplyDemandDerivation;
    if(sd?.status==='AVAILABLE') {
      const entry=Number(payload.selectedTradeChartCandleTime || sd.signalTime);
      return {from:Math.min(sd.zone.pivotTime,sd.opposingZone?.pivotTime ?? sd.inverseFvg?.pivotTime ?? sd.sweepTime ?? sd.zone.pivotTime)-6*3600,to:entry+12*3600};
    }
    const fvg=payload?.fvgDerivation;
    if (fvg?.status!=='AVAILABLE') return null;
    const bars=payload.candles || [];
    const step=bars.length>1 ? bars[1].time-bars[0].time : 900;
    const trade=payload.selectedTrade || {};
    const exit=Date.parse(trade['Exit Time'] || trade.exitTime || '')/1000;
    const entry=Number(payload.selectedTradeChartCandleTime || fvg.signalTime);
    return {from:Math.min(fvg.impulseStartTime,fvg.formedTime)-step*6,to:Math.max(entry,fvg.signalTime,Number.isFinite(exit)?exit:entry)+step*8};
  }

  function centerSelected() {
    if (!payload || !chart) return;
    const bounds=replayActive && !replayRevealed ? replayBounds() : (reviewMode ? setupBounds() : null);
    const start = Number(bounds?.from ?? payload.selectedTradeViewStart);
    const end = Number(bounds?.to ?? payload.selectedTradeViewEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    if(replayActive && !replayRevealed) {
      const bars=payload.candles || [];
      const index=bars.findIndex(bar=>bar.time>=start);
      chart.timeScale().setVisibleLogicalRange({from:Math.max(0,index),to:bars.length+12});
    } else chart.timeScale().setVisibleRange({from:start,to:end});
    defaultPriceRange=computeSelectedPriceRange();
    priceZoomFactor=1.0;
    pricePanOffset=0.0;
    chart.priceScale('right').applyOptions({autoScale:false});
    requestAnimationFrame(() => chart.priceScale('right').applyOptions({autoScale:true}));
    requestAnimationFrame(() => {
      redrawOverlays();
      setTimeout(redrawOverlays, 40);
    });
  }

  function inCandlePane(event) {
    const rect=chartWrap.getBoundingClientRect();
    if (!chart || !candles || event.clientY < rect.top || event.clientY >= rect.bottom) return false;
    if (!rsiSeries) return true;
    const paneHeight=chart.panes()[0].getHeight();
    return event.clientY - rect.top < paneHeight;
  }

  let positionResize=null;
  chartWrap.addEventListener('pointerdown',event=>{
    const handle=event.target.closest?.('.position-handle');if(!handle || event.button!==0)return;
    selectedChartObject={type:'position',key:replayKey()};
    event.preventDefault();event.stopImmediatePropagation();stopReplay();
    positionResize={key:handle.dataset.positionLevel,price:null,bars:null,boxLeft:Number(handle.dataset.boxLeft),pointerId:event.pointerId};
    chartWrap.setPointerCapture(event.pointerId);
  },{capture:true});
  chartWrap.addEventListener('pointermove',event=>{
    if(!positionResize)return;event.preventDefault();event.stopImmediatePropagation();
    if(positionResize.key==='width') {
      positionResize.bars=Math.max(3,(event.clientX-chartWrap.getBoundingClientRect().left-positionResize.boxLeft)/chart.timeScale().options().barSpacing);drawTradeBox();return;
    }
    const y=event.clientY-chartWrap.getBoundingClientRect().top;
    const price=candles.coordinateToPrice(y);if(!Number.isFinite(price) || price<=0)return;
    positionResize.price=price;
    drawTradeBox();
    const handle=tradeBoxLayer.querySelector('[data-position-level="'+positionResize.key+'"]');
    if(handle)handle.style.top=(y-6)+'px';
  },{capture:true});
  const finishPositionResize=event=>{
    if(!positionResize)return;event.preventDefault();event.stopImmediatePropagation();
    const change=positionResize;positionResize=null;chartWrap.releasePointerCapture?.(change.pointerId);
    if(change.key==='width') {
      if(event.type!=='pointercancel' && Number.isFinite(change.bars)){ensureReview().manualBoxBars=change.bars;saveReviews();}redrawOverlays();return;
    }
    if(event.type==='pointercancel' || change.price==null){redrawOverlays();return;}
    if(currentReview()?.manualEntry)amendPosition(change.key==='stop'?change.price:manualPlanDraft.stop,change.key==='target'?change.price:manualPlanDraft.target);
    else if(!manualPlanLocked()){
      if(change.key==='entry'){const delta=change.price-manualPlanDraft.entry;$('manual-stop').value=manualPlanDraft.stop+delta;$('manual-target').value=manualPlanDraft.target+delta;}
      $('manual-'+change.key).value=change.price;refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();redrawOverlays();
    }
  };
  chartWrap.addEventListener('pointerup',finishPositionResize,{capture:true});
  chartWrap.addEventListener('pointercancel',finishPositionResize,{capture:true});

  // Wheel over the right price scale changes vertical zoom only.
  chartWrap.addEventListener('wheel',event => {
    if(event.target.closest?.('#trade-card'))return;
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
    if(event.target.closest?.('.position-handle,.trade-rect,[data-drawing-id],#trade-card'))return;
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

  function chartInterval() {
    const match=String(currentTimeframe).match(/^([0-9]+)([mhdw])$/);
    return match?Number(match[1])*({m:60,h:3600,d:86400,w:604800}[match[2]]):replayInterval;
  }
  function displayCandleTime(time) {
    const bar=((replayChartSource || sourcePayload)?.candles || []).find(item=>item.time<=time && time<item.time+chartInterval());
    return bar?.time ?? time;
  }
  async function load(preserveReplay=false) {
    stopReplay(); replayBusy=true;manualPick=null;chartWrap.style.cursor='';
    $('replay-toggle').disabled=true;
    if(replayActive) { chartWrap.style.visibility='hidden'; $('setup-panel').hidden=true; updateReplayControls(); $('replay-status').textContent='Loading entry preview…'; }
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
      // A new trade still needs strategy candles even when the retained chart
      // timeframe differs. Never project chart candles with the strategy interval.
      const strategyPayload=replayActive && !preserveReplay && requestedTimeframe!==boot.run.timeframe
        ? await getJson(api('/api/payload',{trade_index:String(currentTrade),chart_timeframe:boot.run.timeframe,full_run:'1'}))
        : nextPayload;
      if (generation !== loadGeneration) return;
      manualMarkets.set(requestedTimeframe,nextPayload);
      if(nextPayload.photonMapping)$('structure-guide').checked=true;
      if(preserveReplay && replayActive)replayChartSource=nextPayload;
      else {
        sourcePayload=strategyPayload;marketPayload=strategyPayload;payload=strategyPayload;
        replayChartSource=replayActive && requestedTimeframe!==boot.run.timeframe?nextPayload:null;
        if(replayActive)manualMarkets.set(boot.run.timeframe,strategyPayload);
      }
      timeframeSelect.replaceChildren();
      for (const item of (nextPayload.run.availableChartTimeframes || [{interval:boot.run.timeframe}])) {
        const label = item.interval + (item.interval === boot.run.timeframe ? ' (strategy)' : '') + (item.coverage === 'partial' ? ' (partial data)' : '');
        timeframeSelect.add(new Option(label, item.interval));
      }
      timeframeSelect.value = requestedTimeframe;
      $('timeframe-note').textContent = requestedTimeframe === boot.run.timeframe
        ? 'CSL indicators · strategy timeframe'
        : 'CSL indicators · chart timeframe ' + requestedTimeframe + ' · trades from ' + boot.run.timeframe;
      replayBusy=false;
      $('day-replay').disabled=!(nextPayload.candles || []).length;
      $('structure-review').disabled=!(nextPayload.candles || []).length;
      $('replay-toggle').disabled=!sourcePayload.selectedTrade?.['Entry Time'];
      if(preserveReplay && replayActive){refreshReplay();return;}
      if(dayMode){
        const match=String(boot.run.timeframe).match(/^([0-9]+)([mhdw])$/);
        replayInterval=match?Number(match[1])*({m:60,h:3600,d:86400,w:604800}[match[2]]):900;
        const time=Date.parse(nextPayload.selectedTrade?.['Entry Time'] || '')/1000;
        openReplayDay(replayDay ?? Math.floor((Number.isFinite(time)?time:nextPayload.candles[0].time)/86400)*86400);return;
      }
      if(replayActive) initializeReplay();
      refreshReplay();
    } catch (error) {
      if (generation !== loadGeneration) return;
      currentTimeframe = payload?.chartTimeframe || boot.run.timeframe;
      timeframeSelect.value = currentTimeframe;
      $('timeframe-note').textContent = 'Could not load ' + requestedTimeframe + ': ' + error.message;
      diag.textContent = 'ERROR: ' + error.message;
      if(replayActive) { replayBusy=false;chartWrap.style.visibility='visible';updateReplayControls(); $('replay-status').textContent='Could not load that timeframe: '+error.message+' · Your replay position is preserved; choose another timeframe.'; }
    }
  }

  timeframeSelect.addEventListener('change', () => {
    if(replayActive && !manualPlanLocked()){refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    currentTimeframe = timeframeSelect.value;
    load(replayActive);
  });

  tradeSelect.addEventListener('change',() => {
    if(replayActive && !manualPlanLocked()) {refreshManualPlan();if(!manualPlanDraft.error)storeManualPlan();}
    currentTrade = Number(tradeSelect.value);
    load();
  });
  $('center').addEventListener('click',centerSelected);
  $('review-setup').addEventListener('click',() => {
    if(payload?.fvgDerivation?.status!=='AVAILABLE' && payload?.supplyDemandDerivation?.status!=='AVAILABLE') return;
    reviewMode=!reviewMode;
    renderDiagnostics(); buildChart();
    requestAnimationFrame(centerSelected);
  });
  $('fit').addEventListener('click',() => {
    chart?.timeScale().fitContent();
    defaultPriceRange=null;
    priceZoomFactor=1.0;
    pricePanOffset=0.0;
    chart?.priceScale('right').applyOptions({autoScale:true});
    candles?.applyOptions({});
  });
  $('reset-price').addEventListener('click',resetPriceScale);
  $('sr-zones').addEventListener('change',drawPreviousDayZones);
  $('sr-width').addEventListener('change',drawPreviousDayZones);
  $('day-separators').addEventListener('change',drawDaySeparators);
  if (!window.LightweightCharts) {
    diag.textContent = 'ERROR: Lightweight Charts failed to load.';
    return;
  }
  load();
})();
</script>
</body>
</html>"""
    return template.replace("__LIGHTWEIGHT_CHARTS_URL__", LIGHTWEIGHT_CHARTS_URL).replace("__BOOTSTRAP__", encoded).replace("__REPLAY_HELPERS__", REPLAY_HELPERS).replace("__DRAWING_HELPERS__", DRAWING_HELPERS).replace("__STRUCTURE_HELPERS__", STRUCTURE_HELPERS).replace("__PHOTON_HELPERS__", PHOTON_HELPERS).replace("__WORKSPACE_HELPERS__", WORKSPACE_HELPERS).replace("__WORKSPACE_STYLES__", WORKSPACE_STYLES)


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
                    document = request_path in {root, root + "/", root + "/index.html", root + "/review-report"}
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
                    if parsed.path == prefix + "/review-report":
                        request = owner.model.seed.request
                        context = {"runId": str(owner.model.manifest.get("run_id") or owner.model.run_dir.name),
                                   "symbol": request.symbol, "timeframe": request.strategy_timeframe}
                        self._send(HTTPStatus.OK, build_review_report_html(context, prefix).encode("utf-8"),
                                   "text/html; charset=utf-8")
                        return
                    if parsed.path == prefix + "/api/review-comparison":
                        with owner._lock:
                            trades = []
                            for index in range(owner.model.trade_count):
                                row = owner.model._trade_row(index)
                                summary = owner.model.selected_trade_summary(index)
                                def finite_r(key):
                                    import math
                                    try:
                                        value = float(row.get(key))
                                        return value if math.isfinite(value) else None
                                    except (TypeError, ValueError):
                                        return None
                                trades.append({"index": index, "pair": summary.get("Pair"),
                                    "entryTime": summary.get("Entry Time"), "side": summary.get("Side"),
                                    "grossR": finite_r("pair_gross_r"), "netR": finite_r("pair_net_r")})
                        self._json({"trades": trades})
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
