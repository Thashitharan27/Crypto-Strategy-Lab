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


def test_sneaky_four_levels_and_utc_day_separators():
    html=build_browser_visualizer_v2_html(_Model(),'sneaky')
    assert 'id="day-separators" type="checkbox" checked' in html
    assert 'function drawDaySeparators()' in html
    assert 'Math.floor(bar.time/86400)' in html
    assert 'bar.time%86400!==0' in html
    assert "addEventListener('change',drawDaySeparators)" in html
    assert 'function drawSneakyLevels(sd,xAt,height)' in html
    assert "rangeHigh:'#fb7185',rangeLow:'#34d399',swingHigh:'#fbbf24',swingLow:'#60a5fa'" in html
    assert "if(sd.strategy==='SNEAKY_PIVOT') {drawSneakyLevels(sd,xAt,height);return;}" in html
    assert 'Unavailable in the pre-setup history' in html
    assert "payload.supplyDemandDerivation.levels || []" in html


def test_replay_manual_plan_controls_history_and_chart_preview():
    html=build_browser_visualizer_v2_html(_Model(),'manual')
    for name in ('Manual entry price','Manual stop-loss price','Manual take-profit price'):
        assert f'aria-label="{name}"' in html
    assert 'Save plan' in html and 'Use auto levels' in html
    assert 'function cslRecordManualPlan' in html
    assert 'planHistory' in html and 'originalPlan' in html
    assert 'chart.subscribeClick(event=>' in html
    assert 'candles.coordinateToPrice(event.point.y)' in html
    assert 'Preview entry ' in html and 'Preview SL ' in html and 'Preview TP ' in html
    assert 'Move box' in html and 'Confirm manual entry' in html
    assert 'manual ? manualPlanDraft.entryTime : Number(open.time)' in html
    assert "payload.candles || []).some(bar=>bar.time===time)" in html
    assert 'Manual results are gross R before fees/slippage.' in html
    assert 'version:3' in html
    assert 'Saved plan changes' in html
    assert "(record?.planHistory || []).slice(-20)" in html


def test_calendar_replay_controls_and_manual_only_context():
    html=build_browser_visualizer_v2_html(_Model(),'days')
    for label in ('Day replay','Next day','Previous day','Replay UTC day','Manual day direction'):
        assert label in html
    assert 'function cslDaySource' in html
    assert 'manualDayReviews' in html
    assert 'No automatic trade is required.' in html
    assert 'End of this UTC day.' in html


def test_drawing_controls_and_incremental_replay_are_available():
    html=build_browser_visualizer_v2_html(_Model(),'drawing')
    for text in ('Trend line','Horizontal line','Rectangle','Fib retracement','Text note','Undo drawing','Export drawings','Follow replay'):
        assert text in html
    assert 'function cslDrawingShapes' in html
    assert 'function updateReplayChart()' in html
    assert 'refreshReplay(true)' in html
    assert 'item.series.update(point)' in html
    assert "node.textContent=shape.text" in html


def test_manual_position_closing_and_sidebar_controls():
    html=build_browser_visualizer_v2_html(_Model(),'close')
    for text in ('Close manual position','Pick exit','Drawing toolbar','Drawing settings','manualResults','current-profit','current-loss'):
        assert text in html
    assert 'cslAdvanceManualPosition' in html
    assert "$('drawing-settings').appendChild($('drawing-tools'))" in html


def test_supply_demand_overlay_and_details_use_saved_evidence():
    html = build_browser_visualizer_v2_html(_Model(), "sd")
    assert "function drawSupplyDemandOverlay(sd)" in html
    assert "supplyDemandDerivation" in html
    assert "Bounce confirmed" in html
    assert "Liquidity sweep" in html
    assert "Equal lows" in html
    assert "Displacement" in html
    assert "1h confirmed swing retest" in html
    assert "\\nFirst touch:" in html
    assert "\nFirst touch:" not in html


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
    assert 'id="ema-menu"' in html
    assert 'class="ema-period"' in html
    assert "selectedEmas.has(Number(overlay.period))" in html
    assert 'value="9"' in html
    assert 'value="100"' in html
    assert "fvgDerivation" in html


def test_v2_server_uses_minimal_payload_path():
    from crypto_strategy_lab import strategy_visualizer_browser_v2

    source = __import__("inspect").getsource(strategy_visualizer_browser_v2)
    assert "build_v2_diagnostic_payload" in source
    assert "build_payload(" not in source


def test_v2_html_includes_trade_box_and_correct_summary_keys():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert 'id="trade-box-layer"' in html
    assert "function drawTradeBox()" in html
    assert "timeToCoordinate(displayCandleTime(manual ? manualPlanDraft.entryTime : Number(open.time)))" in html
    assert "trade.Entry ?? trade.entry" in html
    assert "trade['Entry Time'] || trade.entryTime" in html


def test_v2_trade_box_layer_stays_above_chart_canvas():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "#chart{position:absolute;inset:0;z-index:1}" in html
    assert "#trade-box-layer{position:absolute;inset:0;z-index:5" in html
    assert "const width=Math.max(manual?72:48,right-left)" in html


def test_v2_trade_box_shows_opposite_boundary_without_floating_markers():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "OPEN/EXIT markers" not in html
    assert "createSeriesMarkers" not in html
    assert "trade['Exit Reason']" in html
    assert "(manual?'Auto exit (':'Exit (')+String(trade['Exit Reason']" in html
    assert "layoutOverlayLabels" in html
    assert "(manual && !currentReview()?.manualEntry?'Preview TP ':'Target ')+formatPrice(trade.Target ?? trade.target)" in html
    assert "(manual && !currentReview()?.manualEntry?'Preview SL ':'Stop ')+formatPrice(trade.Stop ?? trade.stop)" in html


def test_v2_fib_overlay_has_structure_only_no_trade_specific_fib_labels():
    html = build_browser_visualizer_v2_html(_Model(), "abc")

    assert "resolveFibAnchorTimes" in html
    assert "fib.levels" in html
    assert "fib.impulseStartPrice" in html
    assert "fib.impulseEndPrice" in html
    assert "item.selected ? '  ENTRY'" not in html
    assert "item.stopBoundary ? '  STOP'" not in html
    assert "Target" in html  # trade box remains responsible for target/stop labels


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
    assert 'id="ema-menu"' in html
    for period in (9, 20, 50, 100, 200, 320, 1600):
        assert f'class="ema-period" value="{period}"' in html
    assert "selectedEmas.has(Number(overlay.period))" in html
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
    assert "o.kind === 'ema_rsi' && [224,1120].includes(Number(o.period))" in html
    assert "const line = chart.addSeries(window.LightweightCharts.LineSeries" in html
    assert "chart?.panes()[1]?.setHeight(Number($(\'rsi-height\').value))" in html
    assert "for (const level of [30,70])" in html
    assert "if (visibleRange) chart.timeScale().setVisibleRange(visibleRange)" in html


def test_rsi_pane_does_not_capture_candle_price_gestures():
    html=build_browser_visualizer_v2_html(_Model(),"abc")
    assert "function inCandlePane(event)" in html
    assert "chart.panes()[0].getHeight()" in html
    assert "!inCandlePane(event)" in html


def test_v2_ema_rsi_pair_is_selectable_in_one_pane():
    html=build_browser_visualizer_v2_html(_Model(),"abc")
    assert "EMA RSI 224 / 1120" in html
    assert "for (const overlay of rsiOverlays)" in html
    assert "Number(overlay.period)===224" in html
    assert "if (!rsiSeries) rsiSeries=line" in html


def test_ema_rsi_custom_smoothing_differs_from_wilder_and_waits_for_history():
    import numpy as np
    from crypto_strategy_lab.strategy_visualizer import _ema_rsi
    from crypto_strategy_lab.indicators import rsi as wilder_rsi
    close = np.array([100.0 + i * 0.015 + 3.0 * np.sin(i / 9.0) for i in range(1800)])
    fast = _ema_rsi(close, 224)
    slow = _ema_rsi(close, 1120)
    assert np.isnan(fast[:224]).all()
    assert np.isnan(slow[:1120]).all()
    assert np.isfinite(fast[224:]).all()
    assert np.isfinite(slow[1120:]).all()
    assert np.all((fast[224:] >= 0) & (fast[224:] <= 100))
    assert np.all((slow[1120:] >= 0) & (slow[1120:] <= 100))
    assert not np.isclose(fast[-1], wilder_rsi(close, 224)[-1])


def test_ema_rsi_warmup_covers_supported_chart_timeframes():
    import inspect
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    source=inspect.getsource(CompletedRunVisualizer.build_v2_diagnostic_payload)
    assert "interval_to_timedelta(chart_timeframe)" in source
    assert "interval * 2240" in source


def test_v2_collapsible_diagnostics_and_adjustable_rsi_scale():
    html=build_browser_visualizer_v2_html(_Model(),"abc")
    assert '<details id="diagnostics">' in html
    assert '<summary>Trade diagnostics (expand)</summary>' in html
    assert 'id="rsi-height"' in html
    assert 'id="reset-rsi"' in html
    assert "rsiZoomFactor=Math.max(.04,Math.min(1" in html
    assert "chart?.panes()[1]?.setHeight" in html
    assert "if (!inCandlePane(event))" in html


def test_rsi14_returns_alongside_ema_rsi_pair():
    html=build_browser_visualizer_v2_html(_Model(),"abc")
    assert "RSI 14 + EMA RSI 224 / 1120" in html
    assert "o.kind === 'rsi' && Number(o.period) === 14" in html
    assert "overlay.kind === 'rsi' ? '#f59e0b'" in html


def test_v2_includes_price_ema20_with_existing_trend_emas():
    import inspect
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    html = build_browser_visualizer_v2_html(_Model(), "abc")
    for period in (20, 320, 1600):
        assert f'class="ema-period" value="{period}" checked' in html
    for period in (9, 100):
        assert f'class="ema-period" value="{period}">' in html
    assert "selectedEmas.has(Number(overlay.period))" in html
    assert "20:'#4ade80'" in html
    source = inspect.getsource(CompletedRunVisualizer.build_v2_diagnostic_payload)
    assert "for period in (9, 20, 50, 100, 200, 300, 320, 1600):" in source


def test_standard_visualizer_ema320_layer_and_payload_support():
    import inspect
    from crypto_strategy_lab import strategy_visualizer, strategy_visualizer_browser
    source = inspect.getsource(strategy_visualizer)
    browser_source = inspect.getsource(strategy_visualizer_browser)
    assert 'periods = (20, 50, 100, 200, 300, 320)' in source
    assert 'periods += (1600,)' in source
    assert 'data-overlay="ema320" checked' in browser_source
    assert 'strategy_warmup_period(self.seed.config)' in source


def test_v2_rejects_untrusted_host_origin_and_api_cross_site():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import StrategyVisualizerV2BrowserServer

    server = StrategyVisualizerV2BrowserServer(_Model())
    try:
        url = server.start()
        with urlopen(url, timeout=5) as response:
            assert response.status == 200
        for headers in (
            {"Host": "bad.invalid"},
            {"Origin": "http://bad.invalid"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            try:
                urlopen(Request(url, headers=headers), timeout=5)
                assert False, f"Unexpected request accepted: {headers}"
            except HTTPError as exc:
                assert exc.code == 403
        same_site = {
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        with urlopen(Request(url, headers=same_site), timeout=5) as response:
            assert response.status == 200
        try:
            urlopen(Request(url + "api/payload?trade_index=0", headers=same_site), timeout=5)
            assert False, "Cross-port API read should be rejected"
        except HTTPError as exc:
            assert exc.code == 403
    finally:
        server.stop()


def test_v2_partial_thread_start_cleanup():
    from threading import Thread
    from unittest.mock import patch
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import StrategyVisualizerV2BrowserServer

    server = StrategyVisualizerV2BrowserServer(_Model())
    with patch.object(Thread, "start", side_effect=RuntimeError("thread start blocked")):
        try:
            server.start()
            assert False, "Expected thread failure"
        except RuntimeError as exc:
            assert str(exc) == "thread start blocked"
    assert server._server is None
    server.stop()


def test_switching_to_second_trade_keeps_chart_and_strategy_candles_separate():
    import json
    import shutil
    import subprocess
    import pytest
    from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS

    node=shutil.which('node')
    if not node:pytest.skip('Node is required for replay load regression')
    html=build_browser_visualizer_v2_html(_Model(),'second-trade')
    loader=html[html.index('  async function load('):html.index("  timeframeSelect.addEventListener('change'")]
    script=REPLAY_HELPERS+r'''
let replayActive=true,replayBusy=false,replayRevealed=false,replayAdvanced=false,dayMode=false;
let currentTimeframe='5m',currentTrade=1,loadGeneration=0,manualPick=null;
let sourcePayload=null,marketPayload=null,payload=null,replayChartSource=null,replayEntryTime=0,replayCutoff=0;
const manualMarkets=new Map(),calls=[],controls={},diag={},chartWrap={style:{}},boot={run:{timeframe:'15m'}};
const timeframeSelect={replaceChildren(){},add(){},value:'5m'};
function Option(label,value){this.label=label;this.value=value;}
function $(id){return controls[id] || (controls[id]={style:{}});}
function stopReplay(){}
function updateReplayControls(){}
function api(path,query){return query;}
async function getJson(query){
  calls.push(query);
  const step=query.chart_timeframe==='5m'?300:900;
  return {chartTimeframe:query.chart_timeframe,run:{availableChartTimeframes:[{interval:'5m'},{interval:'15m'}]},
    selectedTrade:{Side:'LONG',Entry:100,'Entry Time':'1970-01-01T00:25:00Z'},markers:[{kind:'selected-open',time:900}],
    candles:Array.from({length:10},(_,i)=>({time:i*step,open:100,high:110,low:90,close:101})),overlays:[]};
}
function initializeReplay(){replayEntryTime=Date.parse(sourcePayload.selectedTrade['Entry Time'])/1000;replayCutoff=replayEntryTime;}
function refreshReplay(){
  payload=cslReplayView(sourcePayload,replayCutoff,900,replayEntryTime,false,true).view;
  if(replayChartSource)payload=cslReplayChart(payload,replayChartSource,replayCutoff,300,replayEntryTime);
}
'''+loader+r'''
(async()=>{
  await load();
  replayCutoff=1800;refreshReplay();
  const secondTrade={strategyTimes:sourcePayload.candles.map(bar=>bar.time),chartTimes:payload.candles.map(bar=>bar.time),cutoff:replayCutoff};
  const strategy=sourcePayload;calls.length=0;
  await load(true);
  console.log(JSON.stringify({secondTrade,preserved:sourcePayload===strategy,preservedCutoff:replayCutoff,calls,errors:diag.textContent}));
})().catch(error=>{process.stderr.write(error.stack);process.exit(1);});
'''
    output=subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True)
    result=json.loads(output.stdout)
    assert result['secondTrade']['strategyTimes'][:3]==[0,900,1800]
    assert 1500 in result['secondTrade']['chartTimes']  # Latest closed 5m entry must be drawable.
    assert max(result['secondTrade']['chartTimes'])==1500
    assert result['preserved'] is True
    assert result['preservedCutoff']==1800
    assert [call['chart_timeframe'] for call in result['calls']]==['5m']
    assert not result['errors'].startswith('ERROR:')

def test_review_comparison_api_returns_finite_gross_and_net_without_changing_run():
    import json
    from urllib.request import urlopen
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import StrategyVisualizerV2BrowserServer

    class ComparisonModel(_Model):
        def _trade_row(self,index):
            return {'pair_gross_r': 2 if index==0 else float('nan'), 'pair_net_r':1.8 if index==0 else None}
        def selected_trade_summary(self,index):
            return {'Pair':index+1,'Side':'LONG','Entry Time':'2020-01-01T00:00:00Z'}

    server=StrategyVisualizerV2BrowserServer(ComparisonModel())
    try:
        url=server.start()
        with urlopen(url+'api/review-comparison',timeout=5) as response:
            data=json.load(response)
        assert data['trades'][0]['grossR']==2 and data['trades'][0]['netR']==1.8
        assert data['trades'][1]['grossR'] is None and data['trades'][1]['netR'] is None
        page=build_browser_visualizer_v2_html(ComparisonModel(),'report')
        assert "window.open(api('/review-report'),'_blank')" in page and 'Review report' in page
        assert 'review-report-dialog' not in page
        with urlopen(url+'review-report',timeout=5) as response:
            report_page=response.read().decode('utf-8')
        assert 'comparisonReportViewedAt=viewedAt' in report_page
        assert 'cslComparisonReportHtml' in report_page
    finally:
        server.stop()

def test_swing_lines_start_at_the_pivot_and_wait_for_confirmation():
    import json
    import shutil
    import subprocess
    import pytest
    node=shutil.which('node')
    if not node:pytest.skip('Node required for chart overlay verification')
    html=build_browser_visualizer_v2_html(_Model(),'origins')
    code=html[html.index('  function drawSneakyLevels('):html.index('  function formatPrice(')]
    script='''
let replayActive=true,replayCutoff=200;
const chartWrap={clientWidth:1000},candles={priceToCoordinate:x=>x};
let drawn=[];
const fvgLayer={appendChild:x=>drawn.push(x)};
const document={createElement:()=>({style:{},offsetHeight:10})};
const formatPrice=String;
const sd={opposingZone:{pivotTime:50},zone:{touchTime:180,top:125,bottom:90,bounceTime:190},signalTime:190,
 levels:[{role:'swingHigh',label:'Older',price:100,time:'1970-01-01T00:01:40Z',confirmedAt:'1970-01-01T00:02:00Z'},
 {role:'rangeHigh',label:'Day',price:110},
 {role:'recentHigh',label:'Recent',price:120,time:'1970-01-01T00:02:30Z',confirmedAt:'1970-01-01T00:04:10Z'}]};
'''+code+'''
drawSneakyLevels(sd,time=>time,500);
const before=drawn.filter(x=>x.className==='fvg-level sneaky-level').map(x=>x.style.left);
drawn=[];replayCutoff=300;drawSneakyLevels(sd,time=>time,500);
console.log(JSON.stringify({before,after:drawn.filter(x=>x.className==='fvg-level sneaky-level').map(x=>x.style.left)}));
'''
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result['before']==['50px','100px']
    assert result['after']==['150px','50px','100px']

def test_previous_day_zones_default_to_enabled_narrow_and_start_at_origin():
    html=build_browser_visualizer_v2_html(_Model(),'sr-defaults')
    assert 'id="sr-zones" type="checkbox" checked' in html
    assert '<option value="1" selected>Narrow zones</option>' in html
    assert 'timeToCoordinate(zone.time)' in html
    assert 'timeToCoordinate(item.time)' in html

def test_drag_target_updates_live_box_and_r_label_without_saving_preview():
    import json
    import shutil
    import subprocess
    import pytest
    from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required for live resize verification')
    html=build_browser_visualizer_v2_html(_Model(),'live-r')
    start=html.index("  chartWrap.addEventListener('pointermove',event=>{\n    if(!positionResize)")
    end=html.index('  const finishPositionResize=',start)
    code=html[start:end]
    script=REPLAY_HELPERS+'''
let handler,draws=0;
const chartWrap={addEventListener:(name,fn)=>handler=fn,getBoundingClientRect:()=>({top:0})};
const candles={coordinateToPrice:()=>130},handle={style:{}};
const tradeBoxLayer={querySelector:()=>handle},sourcePayload={selectedTrade:{Side:'LONG'}};
const manualPlanDraft={entry:100,stop:90,target:120};
let positionResize={key:'target',price:null};
const currentReview=()=>null,formatPrice=String,drawTradeBox=()=>draws++;
'''+code+'''
handler({clientY:50,preventDefault(){},stopImmediatePropagation(){}});
console.log(JSON.stringify({draws,text:handle.textContent,draft:manualPlanDraft,preview:positionResize.price}));
'''
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result['draws']==1 and result['text']=='130 · 3.00R'
    assert result['draft']['target']==120 and result['preview']==130
    assert 'formatPrice(trade.Target ?? trade.target)+targetRText' in html

def test_cover_costs_button_uses_saved_run_rates_and_records_atomic_action():
    import json
    import shutil
    import subprocess
    import pytest
    from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required for manual cost-cover UI verification')
    model=_Model()
    model.seed=SimpleNamespace(request=model.seed.request,config=SimpleNamespace(execution=SimpleNamespace(maker_fee=.0002,taker_fee=.0005,use_maker_entry=True,slippage=.0005)))
    html=build_browser_visualizer_v2_html(model,'costs')
    assert '"manualCosts":{"entryFee":0.0002,"exitFee":0.0005,"slippage":0.0005}' in html
    assert 'Cover costs + BE' in html
    start=html.index("  $('manual-cover-costs').addEventListener('click',()=>{")
    end=html.index('  function closeManualPosition(',start)
    code=html[start:end]
    script=REPLAY_HELPERS+'''
let handler,saves=0,refreshed=0,draws=0,manualEntryMessage='';
let reviewRecords=[{side:'LONG',manualEntry:{entry:100,stop:90,target:130,candleTime:0,replayTime:60}}];
const $=()=>({addEventListener:(name,fn)=>handler=fn});
const manualCloseLocked=()=>false,stopReplay=()=>{},advanceManualPosition=()=>{},currentReview=()=>reviewRecords[0];
const manualMarket=()=>({candles:[{time:0,close:100},{time:60,close:110}]}),manualInterval=()=>60,replayCutoff=120;
const boot={run:{manualCosts:{entryFee:.001,exitFee:.001,slippage:0}}};
const saveReviews=()=>saves++,refreshManualPlan=()=>refreshed++,redrawOverlays=()=>draws++;
'''+code+'''
handler();console.log(JSON.stringify({record:reviewRecords[0],saves,refreshed,draws,manualEntryMessage}));
'''
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result['saves']==result['refreshed']==result['draws']==1
    assert result['record']['positionHistory'][-1]['stop']==100
    assert len(result['record']['partialExits'])==1
    assert 'Closed ' in result['manualEntryMessage'] and '% remains' in result['manualEntryMessage']
