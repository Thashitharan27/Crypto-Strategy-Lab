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
