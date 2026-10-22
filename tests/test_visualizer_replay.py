import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS


def evaluate_manual(expression):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required to verify manual replay plans')
    result=subprocess.run([node,'--input-type=commonjs'],input=REPLAY_HELPERS+'\n'+expression,
        text=True,encoding='utf-8',capture_output=True,check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('side,price,r',[('LONG',110,1),('LONG',95,-.5),('SHORT',90,1),('SHORT',105,-.5)])
def test_manual_close_records_separate_result_without_changing_automatic_trade(side,price,r):
    stop=90 if side=='LONG' else 110
    result=evaluate_manual(f'''
const record={{side:'{side}',netR:42,manualEntry:{{entry:100,stop:{stop},target:120,candleTime:60,replayTime:120}}}};
const bars=[{{time:60,open:100,high:110,low:90,close:105}},{{time:120,open:105,high:115,low:85,close:{price}}},{{time:180,open:1,high:999,low:1,close:999}}];
const result=cslCloseManualPosition(record,bars,180,60,'now');
console.log(JSON.stringify({{record,result,duplicate:cslCloseManualPosition(result,bars,180,60,'later')}}));
''')
    assert result['result']['manualExit']['price']==price
    assert result['result']['manualExit']['grossR']==r
    assert result['result']['manualExit']['candleTime']==120
    assert result['result']['manualExit']['exitTime']==180
    assert result['result']['netR']==42
    assert 'manualExit' not in result['record']
    assert 'error' in result['duplicate']


@pytest.mark.parametrize('exit_request',[{'time':0,'price':100},{'time':180,'price':100},{'time':120,'price':999}])
def test_manual_exit_rejects_pre_entry_future_or_unreachable_price(exit_request):
    result=evaluate_manual('''
const record={side:'LONG',manualEntry:{entry:100,stop:90,candleTime:60}};
const bars=[0,60,120,180].map(time=>({time,open:100,high:110,low:90,close:100}));
console.log(JSON.stringify(cslCloseManualPosition(record,bars,180,60,'now',REQUEST)));
'''.replace('REQUEST',json.dumps(exit_request)))
    assert 'error' in result


@pytest.mark.parametrize('side,scenario,reason,price',[
    ('LONG','tp','TP',120),('LONG','sl','SL',90),('LONG','both','SL',90),
    ('LONG','gap_sl','SL',85),('LONG','gap_tp','TP',125),
    ('SHORT','tp','TP',80),('SHORT','sl','SL',110),('SHORT','both','SL',110),
    ('SHORT','gap_sl','SL',115),('SHORT','gap_tp','TP',75)])
def test_manual_levels_close_on_first_known_hit_with_conservative_ties(side,scenario,reason,price):
    long=side=='LONG'
    stop,target=(90,120) if long else (110,80)
    bar={'time':120,'open':100,'high':105,'low':95,'close':100}
    if scenario in ('tp','both'):bar['high' if long else 'low']=target
    if scenario in ('sl','both'):bar['low' if long else 'high']=stop
    if scenario.startswith('gap'):
        bar.update(open=price,high=max(price,100),low=min(price,100),close=100)
    result=evaluate_manual('''
const record={side:SIDE,manualEntry:{entry:100,stop:STOP,target:TARGET,candleTime:60,replayTime:120}};
const bars=[{time:60,open:100,high:999,low:1,close:100},BAR,{time:180,open:1,high:999,low:1,close:1}];
const before=cslAdvanceManualPosition(record,bars,179,60,'before');
const after=cslAdvanceManualPosition(record,bars,180,60,'after');
console.log(JSON.stringify({record,before,after}));
'''.replace('SIDE',json.dumps(side)).replace('STOP',str(stop)).replace('TARGET',str(target)).replace('BAR',json.dumps(bar)))
    assert 'manualExit' not in result['before']
    exit=result['after']['manualExit']
    assert exit['reason']==reason and exit['price']==price
    assert exit['ambiguous']==(scenario=='both')
    assert exit['candleTime']==120
    assert 'manualExit' not in result['record']


def test_replay_series_updates_replace_entry_stub_and_append_only_new_points():
    result=evaluate_manual('''
const old=[{time:0,open:100,high:100,low:100,close:100}];
const next=[{time:0,open:100,high:110,low:90,close:105},{time:60,open:105,high:107,low:104,close:106}];
const appended=cslSeriesTail(old,next),steady=cslSeriesTail(next,[...next,{time:120,close:108}]);
const restart=cslSeriesTail(next,old),empty=cslSeriesTail([],next);
console.log(JSON.stringify({appended,steady,restart,empty,old}));
''')
    assert not result['appended']['reset']
    assert result['appended']['points'][0]['high']==110
    assert [p['time'] for p in result['steady']['points']]==[60,120]
    assert result['restart']['reset']
    assert len(result['empty']['points'])==2
    assert result['old'][0]['high']==100


def test_manual_day_is_independent_of_automatic_trades_and_future_prices():
    result=evaluate_manual('''
const candles=Array.from({length:288},(_,i)=>({time:i*900,open:15,high:16,low:14,close:15}));
candles[10].high=25;candles[20].low=5;candles[106].high=20;candles[116].low=10;
const source={candles,markers:[{kind:'exit',time:200*900}],selectedTrade:{'Net R':999,Side:'SHORT'},supplyDemandDerivation:{status:'AVAILABLE',future:'secret'},fibDerivation:{status:'AVAILABLE'}};
const first=cslDaySource(source,172800,900,'LONG');
const changed={...source,candles:candles.map(bar=>bar.time>=172800?{...bar,open:999,high:9999,low:0,close:999}:bar)};
const second=cslDaySource(changed,172800,900,'LONG');
const projected=cslReplayView(first,173700,900,172800,false,true);
console.log(JSON.stringify({first,second,projected,source}));
''')
    first=result['first']
    assert first['selectedTrade']==result['second']['selectedTrade']
    assert first['dayContext']==result['second']['dayContext']
    assert {x['role']:x['price'] for x in first['dayContext']['levels']}=={
        'rangeHigh':20,'rangeLow':10,'swingHigh':25,'swingLow':5}
    assert 'Net R' not in first['selectedTrade']
    assert first['supplyDemandDerivation']=={'status':'NOT_AVAILABLE'}
    assert result['source']['selectedTrade']['Net R']==999
    view=result['projected']['view']
    assert all(bar['time']+900<=173700 for bar in view['candles'])
    assert len(view['markers'])==1 and view['markers'][0]['text']=='Manual day plan'
    assert not result['projected']['outcomeVisible']


def test_day_replay_handles_missing_context_and_both_directions():
    result=evaluate_manual('''
const source={candles:[{time:86400,open:100,high:110,low:90,close:105}]};
const long=cslDaySource(source,86400,900,'LONG');
const short=cslDaySource(source,86400,900,'SHORT');
let missing=false;try{cslDaySource(source,172800,900);}catch{missing=true;}
console.log(JSON.stringify({long,short,missing}));
''')
    assert result['missing']
    assert result['long']['dayContext']['levels']==[]
    assert result['long']['selectedTrade']['Stop']==99
    assert result['short']['selectedTrade']['Stop']==101
    assert result['long']['selectedTrade']['Target']==102
    assert result['short']['selectedTrade']['Target']==98


@pytest.mark.parametrize('side,entry,stop,target,valid',[
    ('LONG',100,90,120,True),('SHORT',100,110,80,True),
    ('LONG',100,110,120,False),('SHORT',100,90,80,False),
    ('LONG','',90,120,False),('LONG',100,100,120,False),
    ('LONG',100,90,100,False),('LONG',100,-1,120,False),
    ('UNKNOWN',100,90,120,False),('LONG','Infinity',90,120,False)])
def test_manual_price_plan_validation(side,entry,stop,target,valid):
    data=json.dumps([entry,stop,target,side])
    result=evaluate_manual('console.log(JSON.stringify(cslManualPlan(...'+data+')));')
    assert ('error' not in result)==valid
    if valid:assert result['rewardRisk']==2


def test_manual_revisions_preserve_original_plan_and_decision():
    result=evaluate_manual('''
const record={decision:'Take',notes:'original judgement',netR:null};
const auto={entry:100,stop:90,target:120};
const first=cslRecordManualPlan(record,cslManualPlan(101,91,131,'LONG'),auto,
  {recordedAt:'first',replayTime:'entry',futureSeen:false});
const second=cslRecordManualPlan(first,cslManualPlan(105,95,125,'LONG'),auto,
  {recordedAt:'second',replayTime:'next candle',futureSeen:true});
const same=cslRecordManualPlan(second,second.manualPlan,auto,{recordedAt:'third'});
console.log(JSON.stringify({record,auto,first,second,same}));
''')
    assert 'manualPlan' not in result['record']
    assert result['auto']=={'entry':100,'stop':90,'target':120}
    assert result['second']['originalPlan']==result['auto']
    assert result['second']['decision']=='Take'
    assert result['second']['notes']=='original judgement'
    assert result['first']['planHistory'][0]['entry']==101
    assert not result['second']['planHistory'][0]['futureSeen']
    assert result['second']['planHistory'][1]['futureSeen']
    assert result['second']['planHistory'][1]['replayTime']=='next candle'
    assert len(result['second']['planHistory'])==2
    assert result['same']==result['second']


def source():
    return {
        "candles": [dict(time=t, open=10, high=999, low=1, close=900) for t in (0, 60, 120, 180)],
        "overlays": [dict(kind="ema", period=20, data=[dict(time=t, value=t+500) for t in (0, 60, 120, 180)])],
        "markers": [dict(kind="selected-open", time=120), dict(kind="exit", time=180)],
        "selectedTrade": {"Pair": 1, "Side": "LONG", "Entry Time": "1970-01-01T00:02:00Z", "Entry": 12, "Stop": 9, "Target": 20,
                          "Exit Time": "1970-01-01T00:03:30Z", "Exit": 20, "Exit Reason": "TP", "Net R": 42, "Net P&L": 4200},
        "fvgDerivation": {"status": "AVAILABLE", "signalTime": 60},
        "fibDerivation": {"status": "AVAILABLE", "outcomeSensitiveValue": 777},
        "selectedTradeViewEnd": 99999,
    }


def test_moving_only_entry_candle_records_a_separate_revision():
    result=evaluate_manual('''
const original={entry:100,stop:90,target:120,entryTime:120};
const first=cslRecordManualPlan({decision:'Take'},original,original,{recordedAt:'first'});
const moved=cslRecordManualPlan(first,{...original,entryTime:180},original,{recordedAt:'moved',futureSeen:true});
console.log(JSON.stringify({first,moved}));
''')
    assert len(result['moved']['planHistory'])==2
    assert result['first']['manualPlan']['entryTime']==120
    assert result['moved']['manualPlan']['entryTime']==180
    assert result['moved']['originalPlan']['entryTime']==120
    assert result['moved']['planHistory'][-1]['futureSeen']


@pytest.mark.parametrize('cutoff,price,valid',[(179,100,False),(180,100,True),(180,80,False),(180,95,True),(180,105,True)])
def test_manual_confirmation_requires_closed_selected_candle_and_reachable_price(cutoff,price,valid):
    result=evaluate_manual(f'''
const record={{decision:'Take',manualPlan:{{entry:{price},stop:90,target:120,entryTime:120}},planHistory:[{{recordedAt:'saved',futureSeen:true}}]}};
const bars=[{{time:120,open:99,high:105,low:95,close:103}},{{time:180,open:100,high:200,low:1,close:100}}];
const result=cslConfirmManualEntry(record,bars,{cutoff},60,'confirmed');
console.log(JSON.stringify({{record,result}}));
''')
    assert ('error' not in result['result'])==valid
    assert 'manualEntry' not in result['record']
    if valid:
        entry=result['result']['manualEntry']
        assert entry['candleTime']==120
        assert entry['entry']==price
        assert entry['planSavedAt']=='saved'
        assert entry['futureSeen']
        assert entry['candle']['high']==105
        assert 'unknown' in entry['confirmation']


def test_manual_confirmation_is_single_and_flags_previously_seen_results():
    result=evaluate_manual('''
const record={manualPlan:{entry:100,stop:90,target:120,entryTime:120},netR:-1,revealedAt:'earlier',outcomePreviouslyShown:true};
const first=cslConfirmManualEntry(record,[{time:120,open:100,high:105,low:95,close:101}],180,60,'now');
console.log(JSON.stringify({first,again:cslConfirmManualEntry(first,[],240,60,'later')}));
''')
    assert 'error' in result['again']
    assert result['first']['manualEntry']['automaticOutcomeShown']
    assert result['first']['manualEntry']['outcomePreviouslyShown']
    assert result['first']['manualEntry']['futureSeen']


def project(data, cutoff=120, entry=120, reveal=False, advanced=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to verify the browser replay projection")
    script = REPLAY_HELPERS + "\nconst data=" + json.dumps(data) + ";\n"
    script += f"const result=cslReplayView(data,{cutoff},60,{entry},{str(reveal).lower()},{str(advanced).lower()});\n"
    script += "console.log(JSON.stringify({result,source:data}));"
    result = subprocess.run([node, "--input-type=commonjs"], input=script, text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


def test_entry_preview_hides_outcomes_and_unfinished_candle_values():
    original = source()
    result = project(original)
    view = result["result"]["view"]
    assert not result["result"]["outcomeVisible"]
    assert view["candles"][-1] == dict(time=120, open=12, high=12, low=12, close=12)
    assert [p["time"] for p in view["overlays"][0]["data"]] == [0, 60]
    assert view["selectedTrade"] == {key: original["selectedTrade"][key] for key in ("Pair", "Side", "Entry Time", "Entry", "Stop", "Target")}
    assert view["markers"] == [dict(kind="selected-open", time=120)]
    assert view["fibDerivation"] == {"status": "NOT_AVAILABLE"}
    assert view["selectedTradeViewEnd"] != original["selectedTradeViewEnd"]
    assert result["source"] == original


def test_intrabar_entry_never_exposes_the_containing_candle_final_prices():
    view = project(source(), cutoff=150, entry=150)["result"]["view"]
    assert view["candles"][-1]["high"] == 12
    assert len(view["overlays"][0]["data"]) == 2


def test_stepping_reveals_only_closed_bars_and_waits_for_exit():
    first = project(source(), cutoff=180, advanced=True)["result"]
    assert [b["time"] for b in first["view"]["candles"]] == [0, 60, 120]
    assert first["view"]["candles"][-1]["high"] == 999
    assert not first["outcomeVisible"]
    assert "Exit" not in first["view"]["selectedTrade"]
    second = project(source(), cutoff=240, advanced=True)["result"]
    assert second["outcomeVisible"]
    assert second["view"]["selectedTrade"]["Net R"] == 42


def test_setup_evidence_is_not_shown_before_confirmation_candle_closes():
    data = source()
    data["fvgDerivation"]["signalTime"] = 120
    assert project(data)["result"]["view"]["fvgDerivation"]["status"] == "NOT_AVAILABLE"
    assert project(data, cutoff=180, advanced=True)["result"]["view"]["fvgDerivation"]["status"] == "AVAILABLE"


def test_explicit_reveal_restores_original_payload():
    data = source()
    result = project(data, reveal=True)["result"]
    assert result["outcomeVisible"]
    assert result["view"] == data


def test_only_known_fib_geometry_is_retained():
    data = source()
    data["fibDerivation"].update(impulseEndTime=60, impulseEndPrice=20, levels=[dict(level=.5, price=15)])
    fib = project(data)["result"]["view"]["fibDerivation"]
    assert fib["status"] == "AVAILABLE"
    assert fib["impulseEndPrice"] == 20
    assert "outcomeSensitiveValue" not in fib
    data["fibDerivation"]["impulseEndTime"] = 120
    assert project(data)["result"]["view"]["fibDerivation"]["status"] == "NOT_AVAILABLE"

@pytest.mark.parametrize('side,stop,target,close', [('LONG',90,120,105),('SHORT',110,80,95)])
def test_position_resize_applies_only_to_future_candles_and_preserves_initial_risk(side,stop,target,close):
    result=evaluate_manual(f'''
const original={{side:'{side}',manualEntry:{{entry:100,stop:{stop},target:{target},candleTime:0,replayTime:60}}}};
const amended=cslAmendManualPosition(original,100,{target},120,'now',{close});
const bars=[{{time:60,open:100,high:109,low:91,close:{close}}},{{time:120,open:{close},high:110,low:90,close:100}}];
console.log(JSON.stringify({{original,amended,before:cslAdvanceManualPosition(amended,bars,120,60,'now'),after:cslAdvanceManualPosition(amended,bars,180,60,'now'),rewind:cslAmendManualPosition(amended,100,{target},60,'now',{close}),invalid:cslAmendManualPosition(amended,-1,{target},120,'now',{close})}}));
''')
    assert 'manualExit' not in result['before']
    assert result['after']['manualExit']['grossR']==0
    assert result['after']['manualExit']['price']==100
    assert result['amended']['manualEntry']['stop']==stop
    assert result['amended']['positionHistory'][0]['effectiveAt']==120
    assert 'positionHistory' not in result['original']
    assert 'error' in result['rewind']
    assert 'error' in result['invalid']

def test_previous_day_zones_ignore_current_day_and_future_candles():
    result=evaluate_manual('''
const day=86400,interval=900;
const bars=Array.from({length:96},(_,i)=>({time:i*interval,open:100,close:100,high:110+Math.sin(i)*4,low:90+Math.sin(i)*4}));
const base=cslPreviousDayZones(bars,day,interval,2);
const future=[...bars,{time:day,open:999,high:99999,low:1,close:999}];
console.log(JSON.stringify({base,future:cslPreviousDayZones(future,day,interval,2),wide:cslPreviousDayZones(bars,day,interval,4),missing:cslPreviousDayZones(bars.slice(1),day,interval,2)}));
''')
    assert result['base']==result['future']
    assert 2<=len(result['base']['zones'])<=8
    assert sum(zone['extreme'] for zone in result['base']['zones'])==2
    assert all(zone['bottom']<zone['top'] for zone in result['base']['zones'])
    assert any(zone['touches']>1 for zone in result['base']['zones'])
    assert result['wide']['zones']!=result['base']['zones']
    assert result['missing']['zones']==[]
    assert 'complete previous' in result['missing']['reason']


def test_previous_day_zones_reject_gaps_duplicates_and_coarse_timeframes():
    result=evaluate_manual('''
const bars=Array.from({length:96},(_,i)=>({time:i*900,high:110,low:90}));bars[4].time=bars[3].time;
console.log(JSON.stringify([cslPreviousDayZones(bars,86400,900),cslPreviousDayZones([],86400,14400)]));
''')
    assert all(item['zones']==[] and item['reason'] for item in result)

@pytest.mark.parametrize('interval',[300,3600])
def test_replay_chart_timeframe_switch_clips_future_and_preserves_trade(interval):
    result=evaluate_manual('''
const view={selectedTrade:{Side:'LONG',Entry:100,'Entry Time':'1970-01-01T01:00:00Z'},markers:[{kind:'selected-open',time:3600}],dayContext:{day:0},supplyDemandDerivation:{status:'AVAILABLE'}};
const bars=[0,INTERVAL,INTERVAL*2,INTERVAL*3,INTERVAL*4,3600,7200].filter((v,i,a)=>a.indexOf(v)===i).sort((a,b)=>a-b).map(time=>({time,open:100,high:999,low:1,close:500}));
const chart={chartTimeframe:'alternate',candles:bars,overlays:[{kind:'ema',data:bars.map(bar=>({time:bar.time,value:500}))}]};
const result=cslReplayChart(view,chart,4500,INTERVAL,3600);
console.log(JSON.stringify({view,result}));
'''.replace('INTERVAL',str(interval)))
    projected=result['result']
    assert projected['selectedTrade']==result['view']['selectedTrade']
    assert projected['dayContext']==result['view']['dayContext']
    assert projected['supplyDemandDerivation']==result['view']['supplyDemandDerivation']
    assert all(bar['time']+interval<=4500 or bar['open']==bar['high']==bar['low']==bar['close']==100 for bar in projected['candles'])
    assert all(point['time']+interval<=4500 for point in projected['overlays'][0]['data'])

@pytest.mark.parametrize('interval',[60,300,900,3600])
def test_next_replay_advances_one_selected_chart_candle(interval):
    result=evaluate_manual('''
const interval=INTERVAL,bars=Array.from({length:8},(_,i)=>({time:i*interval}));
const first=cslNextReplayCutoff(bars,interval,interval);
const second=cslNextReplayCutoff(bars,first,interval);
console.log(JSON.stringify({first,second,exhausted:cslNextReplayCutoff(bars,8*interval,interval),boundary:cslNextReplayCutoff(bars,interval,interval,interval),mid:cslNextReplayCutoff(bars,interval+30,interval)}));
'''.replace('INTERVAL',str(interval)))
    assert result['first']==2*interval
    assert result['second']==3*interval
    assert result['mid']==2*interval
    assert result['exhausted'] is None
    assert result['boundary'] is None


def test_five_minute_entry_enables_management_before_strategy_candle_closes():
    result=evaluate_manual('''
const record={side:'LONG',decision:'Take',manualPlan:{entry:100,stop:90,target:120,entryTime:300,interval:300,timeframe:'5m'}};
const bars=[{time:300,open:99,high:106,low:95,close:105},{time:600,open:105,high:108,low:101,close:107}];
const confirmed=cslConfirmManualEntry(record,bars,600,300,'confirmed');
const amended=cslAmendManualPosition(confirmed,100,120,600,'amended',105);
const closed=cslCloseManualPosition(amended,bars,900,confirmed.manualEntry.interval,'closed');
console.log(JSON.stringify({confirmed,amended,closed,early:cslConfirmManualEntry(record,bars,599,300,'early')}));
''')
    assert result['confirmed']['manualEntry']['interval']==300
    assert result['confirmed']['manualEntry']['timeframe']=='5m'
    assert result['amended']['positionHistory'][0]['stop']==100
    assert result['closed']['manualExit']['price']==107
    assert result['closed']['manualExit']['grossR']==.7
    assert result['closed']['manualExit']['availableAt']==900
    assert 'error' in result['early']


def test_manual_plan_timeframe_changes_are_recorded_even_with_same_prices_and_time():
    result=evaluate_manual('''
const plan={entry:100,stop:90,target:120,entryTime:900,interval:900,timeframe:'15m'};
const record=cslRecordManualPlan({},plan,plan,{recordedAt:'first'});
const updated=cslRecordManualPlan(record,{...plan,interval:300,timeframe:'5m'},plan,{recordedAt:'changed'});
console.log(JSON.stringify(updated));
''')
    assert len(result['planHistory'])==2
    assert result['manualPlan']['timeframe']=='5m'
    assert result['originalPlan']['timeframe']=='15m'
