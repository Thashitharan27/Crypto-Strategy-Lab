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


@pytest.mark.parametrize('side', ['LONG','SHORT'])
def test_position_tool_places_directional_two_to_one_preview(side):
    result=evaluate_manual(f'''console.log(JSON.stringify(cslPositionToolPlan('{side}',100,900,96,300,'5m')));''')
    assert result['side']==side and result['entryTime']==900 and result['interval']==300
    assert result['timeframe']=='5m' and result['rewardRisk']==2
    if side=='LONG':assert result['stop']<result['entry']<result['target']
    else:assert result['target']<result['entry']<result['stop']
    assert 'manualEntry' not in result


def test_position_box_width_is_bounded_and_does_not_depend_on_replay_duration():
    result=evaluate_manual('''console.log(JSON.stringify({normal:cslPositionBoxWidth(8),zoom:cslPositionBoxWidth(100),wide:cslPositionBoxWidth(8,40),cap:cslPositionBoxWidth(100,100),tiny:cslPositionBoxWidth(1,1)}));''')
    assert result=={'normal':96,'zoom':180,'wide':320,'cap':720,'tiny':48}


def test_position_tool_keeps_prices_positive_and_rejects_invalid_side():
    result=evaluate_manual('''console.log(JSON.stringify({plan:cslPositionToolPlan('SHORT',1,900,1000,60,'1m'),bad:cslPositionToolPlan('BUY',100,900,90,60,'1m')}));''')
    assert result['plan']['target']>0 and result['plan']['stop']>1
    assert 'error' in result['bad']


def test_multiple_day_trades_keep_legacy_record_and_independent_results():
    result=evaluate_manual('''
const first={key:JSON.stringify(['run','BTCUSDT','manual-day',0]),runId:'run',symbol:'BTCUSDT',reviewType:'manual-day',day:0,side:'LONG',manualEntry:{entry:100,stop:90,candleTime:60,interval:60},manualExit:{price:110,candleTime:120,availableAt:180,grossR:1}};
const original=JSON.stringify(first),records=[first],next=cslNextDayTrade(records,'run','BTCUSDT',0,240,60);
const pending={key:next.key,runId:'run',symbol:'BTCUSDT',reviewType:'manual-day',day:0,side:'SHORT',tradeNotBefore:next.notBefore,manualPlan:{entry:110,stop:120,target:90,entryTime:180}};
const second=cslConfirmManualEntry(pending,[{time:180,open:110,high:115,low:105,close:111}],240,60,'confirmed');
const ended={...second,manualExit:{price:90,candleTime:240,availableAt:300,grossR:2}};
const third=cslNextDayTrade([first,ended],'run','BTCUSDT',0,300,60);
console.log(JSON.stringify({next,third,second,unchanged:original===JSON.stringify(first),report:cslReviewComparison([], [first,ended]),pending:cslNextDayTrade([first,pending],'run','BTCUSDT',0,240,60),blocked:cslNextDayTrade([first,second],'run','BTCUSDT',0,300,60),future:cslNextDayTrade([first],'run','BTCUSDT',0,120,60)}));
''')
    assert result['unchanged'] and result['next']['notBefore']==180
    assert result['second']['manualEntry']['candleTime']==180
    assert result['next']['key']!=result['third']['key']
    assert result['pending']['existingKey']==result['next']['key']
    assert 'error' in result['blocked'] and 'error' in result['future']
    assert result['report']['closed']==2
    assert [r['after'] for r in result['report']['rows']]==[1,2]
    assert result['report']['rows'][1]['label'].endswith('Trade 2')
    assert result['report']['rows'][1]['entryTime']=='1970-01-01T00:03:00.000Z'


def test_second_trade_rejects_an_entry_before_previous_exit_and_day_end():
    result=evaluate_manual('''
const record={tradeNotBefore:180,side:'LONG',manualPlan:{entry:100,stop:90,target:120,entryTime:120}};
const early=cslConfirmManualEntry(record,[{time:120,low:90,high:110}],240,60,'now');
const late=cslNextDayTrade([{runId:'r',symbol:'s',reviewType:'manual-day',day:0,manualEntry:{interval:60},manualExit:{candleTime:86340,availableAt:86400}}],'r','s',0,86400,60);
console.log(JSON.stringify({early,late}));
''')
    assert 'previous position' in result['early']['error']
    assert 'error' in result['late']


@pytest.mark.parametrize('side,exit_price,gross,fees', [('LONG',120,200,3.4),('SHORT',80,200,2.6)])
def test_trade_card_estimates_size_fees_and_slippage(side,exit_price,gross,fees):
    result=evaluate_manual(f'''
const plan={{entry:100,stop:{90 if side=='LONG' else 110},target:{exit_price},side:'{side}'}};
console.log(JSON.stringify(cslTradeCardQuote(plan,null,{exit_price},1000,{{entryFee:.001,exitFee:.002,slippage:.001}})));
''')
    assert result['quantity']==10
    assert result['gross']==pytest.approx(gross)
    assert result['fees']==pytest.approx(fees)
    slippage=2.2 if side=='LONG' else 1.8
    assert result['slippage']==pytest.approx(slippage)
    assert result['net']==pytest.approx(gross-fees-slippage)


def test_trade_card_preserves_original_risk_and_weights_only_known_partials():
    result=evaluate_manual('''
const record={side:'LONG',manualEntry:{entry:100,stop:90},partialExits:[{effectiveAt:20,fraction:.25,price:110},{effectiveAt:40,fraction:.25,price:120}]};
const before=JSON.stringify(record),plan={entry:100,stop:100,target:130};
const quote=cslTradeCardQuote(plan,record,100,1000,{entryFee:.001,exitFee:.001,slippage:0},30);
console.log(JSON.stringify({quote,unchanged:before===JSON.stringify(record),missing:cslTradeCardQuote(plan,record,100,1000,null,30),invalid:cslTradeCardQuote(plan,record,100,0,null,30)}));
''')
    assert result['unchanged']
    assert result['quote']['remainingFraction']==.75
    assert result['quote']['gross']==25
    assert result['quote']['fees']==pytest.approx(2.025)
    assert result['quote']['net']==pytest.approx(22.975)
    assert result['missing']['net'] is None
    assert result['invalid'] is None


@pytest.mark.parametrize('side,stop', [('LONG',90),('SHORT',110)])
def test_risk_sizing_matches_net_stop_loss_for_amount_and_percent(side,stop):
    result=evaluate_manual(f'''
const plan={{entry:100,stop:{stop},target:{120 if side=='LONG' else 80},side:'{side}'}},costs={{entryFee:.001,exitFee:.002,slippage:.001}};
const amount=cslRiskPositionSize(plan,null,10,0,0,'amount',costs);
const percent=cslRiskPositionSize(plan,null,0,1,1000,'percent',costs);
const atStop=cslTradeCardQuote(plan,null,plan.stop,amount.notional,costs);
console.log(JSON.stringify({{amount,percent,atStop}}));
''')
    assert result['amount']['riskBudget']==10
    assert result['amount']['costsIncluded']
    assert result['amount']['notional']==result['percent']['notional']
    assert result['atStop']['net']==pytest.approx(-10)


def test_risk_sizing_retains_original_stop_after_break_even_and_partial_exit():
    result=evaluate_manual('''
const plan={entry:100,stop:100,target:120,side:'LONG'},record={side:'LONG',manualEntry:{entry:100,stop:90,target:120},partialExits:[{fraction:.5,price:110,effectiveAt:1}]};
console.log(JSON.stringify(cslRiskPositionSize(plan,record,10,0,0,'amount',null)));
''')
    assert result['notional']==100
    assert not result['costsIncluded']


@pytest.mark.parametrize('amount,percent,equity,mode', [(0,1,1000,'amount'),(-10,1,1000,'amount'),(10,1,0,'percent'),(10,101,1000,'percent'),(10,0,1000,'percent')])
def test_risk_sizing_rejects_invalid_budget(amount,percent,equity,mode):
    result=evaluate_manual(f'''console.log(JSON.stringify(cslRiskPositionSize({{entry:100,stop:90,side:'LONG'}},null,{amount},{percent},{equity},'{mode}',null)));''')
    assert 'error' in result


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


def test_waiting_across_stop_has_no_manual_trade_or_loss_until_confirmation():
    result=evaluate_manual('''
const waiting={decision:'Wait',initialDecision:'Wait',side:'LONG',notes:'wait for confirmation',manualPlan:{entry:100,stop:90,target:120,entryTime:0}};
const bars=[{time:0,open:100,high:105,low:95,close:101},{time:60,open:95,high:99,low:80,close:85}];
const advanced=cslAdvanceManualPosition(waiting,bars,120,60,'later');
const skipped=cslReviewDecision(advanced,'Skip',120,'skipped','setup invalidated before entry');
console.log(JSON.stringify({advanced,skipped,waitingState:cslManualReviewState(advanced),skipState:cslManualReviewState(skipped),summary:cslManualWorkflowSummary([skipped])}));
''')
    assert 'manualEntry' not in result['advanced']
    assert 'manualExit' not in result['advanced']
    assert result['waitingState']=='Waiting / not entered'
    assert result['skipState']=='Skipped'
    assert result['skipped']['initialDecision']=='Wait'
    assert result['skipped']['decisionHistory'][0]['previous']=='Wait'
    assert result['summary']['skipped']==1
    assert result['summary']['entered']==0
    assert result['summary']['grossR']==0


def test_confirmation_is_the_only_transition_from_wait_to_entered_and_keeps_decision_history():
    result=evaluate_manual('''
let record={side:'LONG',decision:'Wait',initialDecision:'Wait',manualPlan:{entry:100,stop:90,target:120,entryTime:60},revealedAt:'advanced',netR:-1};
record=cslReviewDecision(record,'Skip',90,'skip');
const entered=cslConfirmManualEntry(record,[{time:60,open:100,high:105,low:95,close:102}],120,60,'confirmed');
const forbidden=cslReviewDecision(entered,'Skip',120,'skip entered');
console.log(JSON.stringify({record,entered,forbidden,state:cslManualReviewState(entered),summary:cslManualWorkflowSummary([entered,{decision:'Take',netR:-9},{decision:'Skip',manualExit:{grossR:-99}}])}));
''')
    assert result['record']['decision']=='Skip'
    assert 'manualEntry' not in result['record']
    assert result['entered']['decision']=='Take'
    assert result['entered']['initialDecision']=='Wait'
    assert [event['decision'] for event in result['entered']['decisionHistory']]==['Skip','Take']
    assert result['entered']['decisionHistory'][-1]['automaticOutcomeShown'] is True
    assert result['state']=='Entered'
    assert 'error' in result['forbidden']
    assert result['summary']['entered']==1
    assert result['summary']['open']==1
    assert result['summary']['closed']==0
    assert result['summary']['grossR']==0

def test_review_comparison_matches_identity_and_keeps_unentered_open_and_days_separate():
    result=evaluate_manual('''
const trades=[0,1,2,3,4].map(index=>({index,pair:index+1,grossR:-1,netR:-1.1}));
const records=[{tradeIndex:0,pair:1,decision:'Wait'},
 {tradeIndex:1,pair:2,manualEntry:{replayTime:500},manualExit:{grossR:2,method:'REPLAY_LEVEL_HIT',availableAt:400}},
 {tradeIndex:2,pair:3,manualEntry:{}},
 {tradeIndex:3,pair:999,manualEntry:{},manualExit:{grossR:99}},
 {reviewType:'manual-day',day:0,manualEntry:{},manualExit:{grossR:3}}];
console.log(JSON.stringify(cslReviewComparison(trades,records)));
''')
    assert result['before']==-2 and result['after']==2 and result['matched']==2
    assert result['closed']==2
    rows=result['rows']
    assert rows[0]['after']==0 and rows[0]['status']=='Waiting · not entered'
    assert rows[1]['change']==3 and rows[1]['note']=='Confirmed after stop/target candle'
    assert rows[2]['after'] is None and rows[2]['change'] is None
    assert rows[3]['status']=='Not reviewed' and rows[4]['after'] is None
    assert rows[5]['before'] is None and rows[5]['after']==3 and rows[5]['change'] is None


def test_standalone_report_escapes_data_and_keeps_prices_in_expandable_details():
    from crypto_strategy_lab.visualizer_review_report import REPORT_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for report presentation verification')
    script=REPORT_HELPERS+'''
const row={label:'Trade <img src=x onerror=alert(1)>',entryTime:'2020-01-01T00:00:00Z',side:'LONG',before:-1,after:2,change:3,status:'Win',entry:100,stop:90,target:120,exit:120,net:-1.1,note:'<script>unsafe</script>'};
console.log(JSON.stringify(cslComparisonReportHtml({rows:[row],before:-1,after:2,matched:1,closed:1},{symbol:'BTC<script>',timeframe:'15m',runId:'test'})));
'''
    result=subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True)
    page=json.loads(result.stdout)
    assert '<img src=x' not in page and '&lt;img src=x' in page
    assert 'BTC&lt;script&gt;' in page
    assert '<details><summary>Details' in page
    assert 'Initial stop' in page and 'Automatic net R' in page
    assert '<option value="losses">Losers</option>' in page
    assert 'data-state="wins"' in page
    assert "row.dataset.state!==this.value" in page
    assert '</script></body></html>' in page

def test_previous_day_zone_origins_use_earliest_contributing_candle():
    result=evaluate_manual('''
const interval=900,day=86400;
const bars=Array.from({length:96},(_,i)=>({time:i*interval,high:110,low:90}));
bars[10].high=120;bars[20].high=119.9;bars[30].low=80;
console.log(JSON.stringify(cslPreviousDayZones(bars,day,interval,1)));
''')
    assert len(result['zones'])==2
    support,resistance=result['zones']
    assert support['time']==30*900
    assert resistance['time']==10*900
    assert resistance['touches']>=2
    assert all(zone['time']<86400 for zone in result['zones'])

@pytest.mark.parametrize('side,plan,original,expected',[
 ('LONG',{'entry':100,'stop':90,'target':130},None,3),
 ('SHORT',{'entry':100,'stop':110,'target':70},None,3),
 ('LONG',{'entry':100,'stop':95,'target':130},None,6),
 ('LONG',{'entry':105,'stop':95,'target':130},None,2.5),
 ('LONG',{'entry':100,'stop':100,'target':130},{'entry':100,'stop':90},3),
 ('SHORT',{'entry':100,'stop':95,'target':70},{'entry':100,'stop':110},3),
 ('LONG',{'entry':100,'stop':100,'target':130},None,None),
 ('LONG',{'entry':100,'stop':90,'target':None},None,None),
])
def test_target_r_uses_draft_risk_before_entry_and_original_risk_after_entry(side,plan,original,expected):
    result=evaluate_manual('console.log(JSON.stringify(cslTargetR('+json.dumps(plan)+','+json.dumps(side)+','+json.dumps(original)+')));')
    assert result==expected

@pytest.mark.parametrize('side',['LONG','SHORT'])
@pytest.mark.parametrize('exit_kind',['be','tp','gap','manual'])
def test_cost_cover_partial_and_remaining_exit_are_weighted_and_costed(side,exit_kind):
    result=evaluate_manual('''
const side=SIDE,long=side==='LONG',entry={entry:100,stop:long?90:110,target:long?130:70,candleTime:0,replayTime:60,interval:60};
const record={side,manualEntry:entry};
const bars=[{time:0,open:100,high:101,low:99,close:100},{time:60,open:100,high:long?111:101,low:long?99:89,close:long?110:90}];
const costs={entryFee:.001,exitFee:.001,slippage:.001};
const covered=cslCoverCostsAndBreakEven(record,bars,120,60,'partial',costs);
const again=cslCoverCostsAndBreakEven(covered,bars,120,60,'repeat',costs);
let bar;
if(KIND==='be')bar={time:120,open:long?109:91,high:long?112:100,low:long?100:88,close:100};
if(KIND==='tp')bar={time:120,open:long?110:90,high:long?131:91,low:long?109:69,close:long?130:70};
if(KIND==='gap')bar={time:120,open:long?95:105,high:long?97:107,low:long?93:103,close:long?96:104};
if(KIND==='manual')bar={time:120,open:100,high:110,low:90,close:long?105:95};
const ended=KIND==='manual'?cslCloseManualPosition(covered,[...bars,bar],180,60,'close'):cslAdvanceManualPosition(covered,[...bars,bar],180,60,'exit');
console.log(JSON.stringify({record,covered,again,ended,summary:cslManualWorkflowSummary([ended]),comparison:cslReviewComparison([], [{...ended,reviewType:'manual-day',day:0}])}));
'''.replace('SIDE',json.dumps(side)).replace('KIND',json.dumps(exit_kind)))
    covered=result['covered']; partial=covered['partialExits'][0]; x=partial['fraction']
    sign=1 if side=='LONG' else -1
    assert 0<x<1
    assert x==pytest.approx(.4/(10-sign*10*.002))
    assert covered['positionHistory'][-1]['stop']==100
    assert covered['manualEntry']['stop']==(90 if side=='LONG' else 110)
    assert 'partialExits' not in result['record']
    assert 'already' in result['again']['error']
    end=result['ended']['manualExit']; final=end['price']
    expected_gross=x*10+(1-x)*sign*(final-100)
    expected_cost=.2+.002*(x*(110 if side=='LONG' else 90)+(1-x)*final)
    assert end['grossR']==pytest.approx(expected_gross/10)
    assert end['estimatedNetR']==pytest.approx((expected_gross-expected_cost)/10,abs=1e-10)
    assert end['closedFraction']==pytest.approx(1-x) and end['remainingFraction']==0
    assert result['summary']['partialExitCount']==1 and result['summary']['estimatedNetClosed']==1
    assert result['comparison']['rows'][0]['estimatedNetR']==end['estimatedNetR']
    if exit_kind=='be':assert end['estimatedNetR']==0 and end['grossR']>0
    if exit_kind=='gap':assert end['estimatedNetR']<0


def test_cost_cover_fraction_scales_with_stop_distance_at_same_one_r_profit():
    result=evaluate_manual('''
const costs={entryFee:.001,exitFee:.001,slippage:0};
const quote=risk=>cslCoverCostsQuote({side:'LONG',manualEntry:{entry:100,stop:100-risk}},100+risk,costs);
console.log(JSON.stringify({wide:quote(10),tight:quote(1)}));
''')
    assert result['tight']['fraction']==pytest.approx(result['wide']['fraction']*10)


@pytest.mark.parametrize('case',['losing','tiny_profit','no_costs','invalid_cost','future','rewind','closed'])
def test_cost_cover_rejects_invalid_actions_without_mutating_position(case):
    result=evaluate_manual('''
const record={side:'LONG',manualEntry:{entry:100,stop:90,target:130,candleTime:0,replayTime:60}};
const costs={entryFee:.001,exitFee:.001,slippage:.001};
let cutoff=120,price=110;
if(CASE==='losing')price=99;if(CASE==='tiny_profit')price=100.01;
if(CASE==='no_costs')Object.assign(costs,{entryFee:0,exitFee:0,slippage:0});
if(CASE==='invalid_cost')costs.entryFee=-1;
if(CASE==='future')cutoff=90;
if(CASE==='rewind')record.positionHistory=[{stop:95,target:130,effectiveAt:180}];
if(CASE==='closed')record.manualExit={grossR:0};
const bars=[{time:0,close:100},{time:60,close:price},{time:180,close:999}];
console.log(JSON.stringify({result:cslCoverCostsAndBreakEven(record,bars,cutoff,60,'now',costs),record}));
'''.replace('CASE',json.dumps(case)))
    assert 'error' in result['result']
    assert 'partialExits' not in result['record']


def test_partial_exit_cannot_be_closed_retroactively_and_prefix_is_unchanged():
    result=evaluate_manual('''
const record={side:'LONG',manualEntry:{entry:100,stop:90,target:130,candleTime:0,replayTime:60}};
const bars=[{time:0,open:100,high:101,low:99,close:100},{time:60,open:100,high:111,low:99,close:110}];
const costs={entryFee:.001,exitFee:.001,slippage:0};
const now=cslCoverCostsAndBreakEven(record,bars,120,60,'now',costs);
const future=cslCoverCostsAndBreakEven(record,[...bars,{time:120,close:999}],120,60,'now',costs);
const retro=cslCloseManualPosition(now,bars,120,60,'retro',{time:0,price:100});
console.log(JSON.stringify({now,future,retro,before:cslManualSettlement(now,110,60),after:cslManualSettlement(now,110,120)}));
''')
    assert result['now']==result['future']
    assert 'partial exit' in result['retro']['error']
    assert result['before']['remainingFraction']==1
    assert result['after']['remainingFraction']<1


def test_cost_cover_then_close_on_unaligned_chart_cutoff_keeps_journal_order():
    result=evaluate_manual('''
const record={side:'LONG',manualEntry:{entry:100,stop:90,target:130,candleTime:0,replayTime:60}};
const bars=[{time:0,open:100,high:101,low:99,close:100},{time:60,open:100,high:111,low:99,close:110}];
const covered=cslCoverCostsAndBreakEven(record,bars,125,60,'partial',{entryFee:.001,exitFee:.001,slippage:0});
const closed=cslCloseManualPosition(covered,bars,125,60,'close');
console.log(JSON.stringify({covered,closed}));
''')
    assert 'error' not in result['closed']
    assert result['closed']['manualExit']['availableAt']==125
    assert result['closed']['manualExit']['exitTime']==125
    assert result['covered']['positionHistory'][-1]['method']=='COVER_COSTS_AND_BE'
    assert result['closed']['manualExit']['grossR']==pytest.approx(1.)
