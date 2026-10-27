from copy import deepcopy
from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_trend import MODE, trend_setups, resolve_retest
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS


def test_optional_chart_metadata_does_not_select_a_strategy():
    from unittest.mock import Mock
    from crypto_strategy_lab.photon_trend import selected
    for missing in (None,[],Mock(),{}):
        assert selected(missing) is False


@pytest.mark.parametrize('coverage,expected',[('full','15m'),('partial','1m'),('missing','1m')])
def test_photon_defaults_to_15m_review_without_changing_execution(coverage,expected):
    import re
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    model=SimpleNamespace(seed=SimpleNamespace(request=SimpleNamespace(symbol='BTCUSDT',strategy_timeframe='1m'),config=SimpleNamespace(strategy=SimpleNamespace(profiles=profiles))),
        run_dir=SimpleNamespace(name='test'),manifest={},trade_count=0,
        available_chart_timeframes=lambda:[] if coverage=='missing' else [dict(interval='15m',coverage=coverage)])
    html=build_browser_visualizer_v2_html(model,'photon')
    boot=json.loads(re.search(r'const boot = (.*?);',html).group(1))
    assert boot['run']['defaultChartTimeframe']==expected
    assert boot['run']['timeframe']=='1m'
    assert 'boot.run.defaultChartTimeframe || boot.run.timeframe' in html
    assert 'if(boot.run.photonTrading){load();return;}' in html
    # The existing loader keeps 1m replay facts separate from the review chart.
    assert "await getChartPayload(boot.run.timeframe)" in html


def walkthrough(short=False):
    """Authored causal context: reaction, alignment, pullback, shift, later fill."""
    t=1767225600
    rows=[(100,104,98,102),(102,108,101,107),(101,102,96,97),
          (98,99,95,96),(97,105,96,104),(101,103,98,102),
          (103,122,102,120),(120,121,119,120)]
    bars=[dict(time=t+i*60,open=o,high=h,low=l,close=c) for i,(o,h,l,c) in enumerate(rows)]
    sign=-1 if short else 1
    if short:
        for b in bars:
            b.update(open=220-b['open'],high=220-b['low'],low=220-b['high'],close=220-b['close'])
    def state(interval):
        return dict(interval=interval,events=[],snapshots=[dict(availableAt=t,trend=sign,internal=sign,
                    low=dict(time=t-3600,price=80),high=dict(time=t-1800,price=140),
                    range=dict(low=80,high=140,equilibrium=110,knownAt=t))])
    guides={tf:state(sec) for tf,sec in [('1m',60),('15m',900),('4h',14400),('1d',86400),('1w',604800)]}
    guides['1m']['events']=[dict(availableAt=t+300,kind='CHOCH',direction=sign,fromTime=t+120)]
    guides['15m']['events']=[dict(availableAt=t+180,kind='BOS',direction=sign)]
    z=dict(id='parent',timeframe='15m',kind='SUPPLY' if short else 'DEMAND',availableAt=t+60,lower=96,upper=102)
    if short:z.update(lower=118,upper=124)
    guides['15m']['supplyDemand']=dict(zones=[z],events=[])
    return bars,guides


@pytest.mark.parametrize('short',[False,True])
def test_staged_walkthrough_and_prefix_invariance(short):
    bars,guides=walkthrough(short)
    signals,live=trend_setups(bars,np.ones(len(bars)),guides=guides)
    assert [i for i,s in enumerate(signals) if s]==[4]
    s=signals[4]
    assert s['side']==('SHORT' if short else 'LONG')
    assert s['entry']==(121 if short else 99)
    assert s['stop']==pytest.approx(125.05 if short else 94.95)
    assert s['target']==(80 if short else 140)
    assert s['contextTouchAt']<s['alignmentAt']<s['parentTouchAt']<s['signalAvailableAt']
    assert live[4]==4 and live[5] is None  # first later minute fills
    for end in range(1,len(bars)+1):
        got=trend_setups(bars[:end],np.ones(end),guides=guides)
        assert got==(signals[:end],live[:end])
    guides['4h']['snapshots'][0]['range']['high']=999
    assert s['range4h']['high']==140


@pytest.mark.parametrize('missing',['alignment','shift','counter_15m','unknown_4h','invalidated','gap','expired','outside_value'])
def test_required_stages_and_invalidations(missing):
    bars,guides=walkthrough()
    kwargs={}
    if missing=='alignment':guides['15m']['events']=[]
    if missing=='shift':guides['1m']['events']=[]
    if missing=='counter_15m':guides['15m']['snapshots'][0]['trend']=-1
    if missing=='unknown_4h':guides['4h']['snapshots'][0]['trend']=0
    if missing=='invalidated':guides['15m']['supplyDemand']['events']=[dict(availableAt=bars[3]['time']+60,kind='INVALIDATED',zoneId='parent')]
    if missing=='gap':bars[3]['time']+=1
    if missing=='expired':kwargs['confirmation_minutes']=1
    if missing=='outside_value':guides['4h']['snapshots'][0]['range']['equilibrium']=90
    assert not any(trend_setups(bars,np.ones(len(bars)),guides=guides,**kwargs)[0])


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('deviation',['existing_alignment','4h_value','15m_value','internal_only'])
def test_flexible_candidates_keep_frozen_mismatches_and_are_prefix_safe(short,deviation):
    bars,guides=walkthrough(short);sign=-1 if short else 1
    codes={'existing_alignment':'FRESH_15M_CONFIRMATION','4h_value':'4H_ENTRY_VALUE',
           '15m_value':'15M_ENTRY_VALUE','internal_only':'15M_SWING_ALIGNMENT'}
    if deviation=='existing_alignment':guides['15m']['events']=[]
    if deviation=='4h_value':guides['4h']['snapshots'][0]['range']['equilibrium']=130 if short else 90
    if deviation=='15m_value':guides['15m']['snapshots'][0]['range']['equilibrium']=130 if short else 90
    if deviation=='internal_only':guides['15m']['snapshots'][0]['trend']=-sign
    assert not any(trend_setups(bars,np.ones(len(bars)),guides=guides)[0])
    signals,live=trend_setups(bars,np.ones(len(bars)),guides=guides,flexible=True)
    s=signals[4]
    assert s and s['side']==('SHORT' if short else 'LONG')
    assert s['review']['status']=='REVIEW_REQUIRED'
    assert codes[deviation] in {c['code'] for c in s['review']['mismatches']}
    assert s['entryModel']=='FLEXIBLE_REVIEW' and live[4]==4 and live[5] is None
    for end in range(1,len(bars)+1):
        assert trend_setups(bars[:end],np.ones(end),guides=guides,flexible=True)==(signals[:end],live[:end])
    saved=deepcopy(s['review']);guides['15m']['snapshots'][0]['trend']=0
    assert s['review']==saved


def test_flexible_accepts_a_later_internal_shift_without_a_swing_reversal():
    bars,guides=walkthrough();t=bars[0]['time']
    m=guides['15m']['snapshots'][0];m.update(trend=-1,internal=-1)
    aligned=deepcopy(m);aligned.update(availableAt=t+180,internal=1)
    guides['15m']['snapshots'].append(aligned)
    guides['15m']['events'][0]['kind']='CHOCH'
    s=trend_setups(bars,np.ones(len(bars)),guides=guides,flexible=True)[0][4]
    assert s['alignmentAt']==t+180
    codes={c['code'] for c in s['review']['mismatches']}
    assert '15M_SWING_ALIGNMENT' in codes and 'FRESH_15M_CONFIRMATION' not in codes


@pytest.mark.parametrize('missing',['shift','zone','alignment','4h','stop','reward','gap'])
def test_flexible_keeps_structural_and_execution_requirements(missing):
    bars,guides=walkthrough()
    if missing=='shift':guides['1m']['events']=[]
    if missing=='zone':guides['15m']['supplyDemand']['zones']=[]
    if missing=='alignment':guides['15m']['snapshots'][0].update(trend=-1,internal=-1)
    if missing=='4h':guides['4h']['snapshots'][0]['trend']=0
    if missing=='stop':bars[3]['low']=79
    if missing=='reward':guides['15m']['snapshots'][0]['range']['high']=98
    if missing=='gap':bars[3]['time']+=1
    assert not any(trend_setups(bars,np.ones(len(bars)),guides=guides,flexible=True)[0])


def test_preferred_setup_and_opposing_or_missing_narrative_are_explicit():
    bars,guides=walkthrough()
    s=trend_setups(bars,np.ones(len(bars)),guides=guides)[0][4]
    assert s['review']['status']=='PREFERRED_ALIGNMENT' and not s['review']['mismatches']
    guides['1d']['snapshots'][0]['trend']=-1;guides['1w']['snapshots'][0]['trend']=0
    s=trend_setups(bars,np.ones(len(bars)),guides=guides)[0][4]
    warnings={c['code']:c['detail'] for c in s['review']['mismatches']}
    assert 'opposes' in warnings['1D_CONTEXT'] and 'unknown' in warnings['1W_CONTEXT']


def test_browser_review_warns_before_manual_decision_without_future_evidence():
    import shutil,subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required for review projection')
    bars,guides=walkthrough()
    s=trend_setups(bars,np.ones(len(bars)),guides=guides,flexible=True)[0][4]
    s['status']='AVAILABLE';at=s['signalAvailableAt']
    legacy={k:v for k,v in s.items() if k!='review'}
    script=PHOTON_HELPERS+'\nconst sd='+json.dumps(s)+';const legacy='+json.dumps(legacy)+f';console.log(JSON.stringify([cslPhotonReviewView(sd,{at-1}),cslPhotonReviewView(sd,{at}),cslPhotonReviewView(legacy)]));'
    before,now,old=json.loads(subprocess.run([node],input=script,text=True,capture_output=True,check=True).stdout)
    assert before is None
    assert 'Manual review' in now['label']
    assert now['mismatches']==s['review']['mismatches']
    assert old['legacy'] and 'not saved' in old['label']
    dom="const nodes={};const $=id=>nodes[id]??(nodes[id]={children:[],replaceChildren(){this.children=[]},appendChild(c){this.children.push(c)}});const document={createElement:()=>({style:{}})};"
    script=PHOTON_HELPERS+'\n'+dom+'const sd='+json.dumps(s)+f';renderPhotonEntryReview(sd,{at});console.log(JSON.stringify(nodes));renderPhotonEntryReview(sd,{at-1});console.log(JSON.stringify(nodes));'
    visible,hidden=[json.loads(line) for line in subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout.splitlines()]
    assert visible['photon-entry-review']['hidden'] is False
    assert 'Manual review' in visible['photon-entry-review-label']['textContent']
    rows=visible['photon-entry-checks']['children']
    assert len(rows)==len(s['review']['checks'])+1
    assert any(row.get('style',{}).get('color')=='#fbbf24' for row in rows)
    assert 'Confirm manual entry' in rows[-1]['textContent']
    assert hidden['photon-entry-review']['hidden'] is True
    assert hidden['photon-entry-checks']['children']==[]



def test_causal_real_context_prefix():
    # Real aggregation, structure and zone computation, independent of authored guide.
    rng=np.random.default_rng(24);n=700
    close=100+np.sin(np.arange(n)/13)*8+rng.normal(0,.2,n)
    bars=[dict(time=1767225600+i*60,open=float(close[max(0,i-1)]),high=float(max(close[max(0,i-1)],c)+.2),low=float(min(close[max(0,i-1)],c)-.2),close=float(c)) for i,c in enumerate(close)]
    full=trend_setups(bars,np.ones(n))
    for end in (60,301,650):
        assert trend_setups(bars[:end],np.ones(end))==(full[0][:end],full[1][:end])


def test_optional_4h_target_uses_its_own_saved_anchor():
    bars,guides=walkthrough()
    h=guides['4h']['snapshots'][0]
    h['range'].update(high=150,equilibrium=115)
    h['high']['time']-=600
    s=trend_setups(bars,np.ones(len(bars)),guides=guides,target_4h=True)[0][4]
    assert s['target']==150 and s['targetMode']=='4H_SWING'
    assert pd.Timestamp(s['opposingZone']['pivotTime']).timestamp()==h['high']['time']


def test_trade_chart_uses_the_engine_minute_mapping_and_warmup():
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    from crypto_strategy_lab.data_lake_config import load_data_lake_config
    from crypto_strategy_lab.research_warmup import strategy_warmup_period
    from crypto_strategy_lab.photon_trend import prepare_context
    c=load_data_lake_config('config/data_lake/Photon_4H_Trend_1m.json')
    bars,_=walkthrough()
    frame=pd.DataFrame(bars)
    frame['period_start']=pd.to_datetime(frame.time,unit='s',utc=True)
    model=object.__new__(CompletedRunVisualizer)
    start=pd.Timestamp('2026-01-01',tz='UTC');end=start+pd.Timedelta(days=1)
    model.seed=SimpleNamespace(config=c,request=SimpleNamespace(period_start=start,period_end=end))
    seen=[]
    def market(a,b,*,chart_timeframe):
        seen.append((a,b,chart_timeframe))
        return frame
    model._market_frame=market
    mapping=model._photon_mapping_payload()
    assert seen==[(start-strategy_warmup_period(c),end,'1m')]
    assert mapping['mappingOnly'] is False and mapping['strategy']==MODE
    expected=prepare_context(bars)
    for tf in ('15m','4h','1d','1w'):
        assert mapping['timeframes'][tf]==expected[tf]
    assert model._photon_mapping_payload() is mapping and len(seen)==1


@pytest.mark.parametrize('mode',[MODE,'PHOTON_STRUCTURE_MAP'])
def test_chart_controls_show_structure_without_disabling_trades(mode):
    import re, shutil, subprocess
    from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
    node=shutil.which('node')
    if not node:pytest.skip('Node required for browser control projection')
    profiles,_=compile_profiles(direction_mode=mode,market_permissions=MARKET_PERMISSIONS)
    model=SimpleNamespace(seed=SimpleNamespace(request=SimpleNamespace(symbol='BTCUSDT',strategy_timeframe='1m'),config=SimpleNamespace(strategy=SimpleNamespace(profiles=profiles))),
        run_dir=SimpleNamespace(name='test'),manifest={},trade_count=0)
    html=build_browser_visualizer_v2_html(model,'photon')
    boot=json.loads(re.search(r'const boot = (.*?);',html).group(1))
    init=html[html.index('  if(boot.run.mappingOnly) {'):html.index('  function applyPhotonDisplay()')]
    js="const boot="+json.dumps(boot)+";const nodes={};const $=id=>nodes[id]??(nodes[id]={hidden:true,disabled:false});const indicatorInputs=[];const initPhotonInspector=()=>nodes.inspectorInitialized=true;const document={body:{classList:{add(){}}}};"+init+";console.log(JSON.stringify(nodes));"
    nodes=json.loads(subprocess.run([node],input=js,text=True,capture_output=True,check=True).stdout)
    assert nodes['photon-view']['hidden'] is False
    assert nodes['photon-context']['hidden'] is False
    if mode==MODE:
        assert not boot['run']['mappingOnly'] and boot['run']['photonTrading']
        assert nodes['photon-view']['value']=='BOTH'
        assert 'manual-confirm' not in nodes  # trading controls never disabled
    else:
        assert nodes['photon-view']['value']=='BOTH'
        assert nodes['inspectorInitialized'] is True
        assert 'manual-confirm' not in nodes  # manual simulation is enabled in mapping mode too


@pytest.mark.parametrize('short',[False,True])
def test_limit_fill_and_gap_safety(short):
    s=dict(side='SHORT' if short else 'LONG',entry=100,stop=110 if short else 90)
    assert resolve_retest(s,dict(open=100,high=105,low=95))==('FILLED',100)
    assert resolve_retest(s,dict(open=120 if short else 80,high=121,low=79))[0]=='INVALIDATED'
    assert resolve_retest(s,dict(open=105 if short else 95,high=108,low=92))==('FILLED',105 if short else 95)
    assert resolve_retest(s,dict(open=95 if short else 105,high=99 if short else 108,low=92 if short else 101))[0]=='WAITING'
    s['target']=80 if short else 120
    assert resolve_retest(s,dict(open=75 if short else 125,high=130,low=70))[0]=='INVALIDATED'


@pytest.mark.parametrize('reason',['expiry','target','zone','trend','gap'])
def test_unfilled_order_is_cancelled_before_next_minute(reason):
    bars,guides=walkthrough()
    bars[5].update(open=105,low=101,high=108,close=106)
    kwargs={}
    at=bars[5]['time']+60
    if reason=='expiry':kwargs['retest_minutes']=1
    if reason=='target':bars[5]['high']=141
    if reason=='zone':guides['15m']['supplyDemand']['events']=[dict(availableAt=at,kind='INVALIDATED',zoneId='parent')]
    if reason=='trend':
        changed=deepcopy(guides['15m']['snapshots'][0]);changed.update(availableAt=at,trend=-1)
        guides['15m']['snapshots'].append(changed)
    if reason=='gap':bars[5]['time']+=1
    signals,live=trend_setups(bars,np.ones(len(bars)),guides=guides,**kwargs)
    assert signals[4] is not None
    assert live[5] is None


def test_config_requires_actual_minutes_and_roundtrip():
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, ResearchRunConfig
    assert ResearchRunConfig().execution.photon_flexible_entries is False
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=load_data_lake_config('config/data_lake/Photon_4H_Trend_1m.json')
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.strategy_timeframe_minutes==1
    assert native.photon_flexible_entries is True
    assert native.photon_confirmation_minutes==1440 and native.photon_retest_minutes==60
    with pytest.raises(ValueError,match='actual 1m'):
        replace(native,strategy_timeframe_minutes=15)
    with pytest.raises(ValueError,match='timeout'):
        replace(native,photon_retest_minutes=1.5)


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('collision',['normal','stop_and_target','target_only','flip','minimum_r','window','flexible','prepared','prepared_window'])
def test_production_engine_limit_geometry_costs_and_saved_evidence(monkeypatch,short,collision):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    bars,guides=walkthrough(short)
    signals,live=trend_setups(bars,np.ones(len(bars)),guides=guides,flexible=collision=="flexible")
    # Keep ATR/regime warmup separate from the authored market-structure evidence.
    pad=[dict(time=bars[0]['time']-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    source=pad+bars
    if collision=='stop_and_target':
        source[155].update(high=145,low=75)
    if collision in ('window','prepared_window'):
        source[155].update(open=115 if short else 105,high=119 if short else 108,low=112 if short else 101,close=115 if short else 105)
        live[5]=4
    if collision=='target_only':
        source[155]['low' if short else 'high']=75 if short else 145
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.trend_setups',lambda *a,**kw:([None]*150+signals,[None]*150+[x+150 if x is not None else None for x in live]))
    signals[4]['signalIndex']+=150
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:replace(StrategyProfile(**asdict(p)),trailing_enabled=True,partial_profit_enabled=True) for k,p in profiles.items()}
    config=BacktestConfig(strategy_timeframe_minutes=1,telemetry_interval_minutes=1,strategy_profiles=native,use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False)
    if collision=='flip':config=replace(config,strategy_profiles={k:replace(p,flip_direction=True) for k,p in native.items()})
    if collision=='minimum_r':config=replace(config,sd_minimum_r=100.)
    if collision in ('window','prepared_window'):config=replace(config,trading_end_date=pd.Timestamp(bars[4]['time']+60,unit='s',tz='UTC').isoformat())
    frame=pd.DataFrame(source).rename(columns={'time':'timestamp'})
    frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    if collision in ('prepared','prepared_window'):
        from test_prepared_backtest import valid_kwargs
        from crypto_strategy_lab.prepared_backtest import PreparedBacktestFrame
        kwargs=valid_kwargs(len(frame))
        times=frame.timestamp.to_numpy(dtype='datetime64[ns]')
        kwargs.update(timestamp=times,strategy_interval=pd.Timedelta(minutes=1),decision_available_at=times+np.timedelta64(1,'m'),atr=np.ones(len(frame)))
        kwargs.update({key:frame[key].to_numpy(float) for key in ('open','high','low','close','volume')})
        config=replace(config,trading_start_date=frame.timestamp.iloc[0].tz_localize(None).isoformat())
        engine=RuleAwareDataLakeProductionBacktestEngine.from_prepared(PreparedBacktestFrame(**kwargs),None,config)
        assert engine.trading_start.tzinfo is None
    else:
        engine=RuleAwareDataLakeProductionBacktestEngine(frame,config);engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    if collision in ('flip','minimum_r','window','prepared_window'):
        assert len(trades)==0
        return
    assert len(trades)==1
    row=trades.iloc[0];s=json.loads(row.supply_demand_setup)
    assert pd.to_datetime(row.entry_time,utc=True)==frame.timestamp.iloc[155]
    assert row.side==s['side']
    if collision=='stop_and_target':
        assert row[row.side.lower()+'_final_exit_reason']=='SL'
        assert pd.Timestamp(row.exit_time)==pd.Timestamp(row.entry_time)
    assert row.actual_entry_price==pytest.approx(s['entry']*(1-config.slippage if short else 1+config.slippage))
    assert row.pair_total_fees>0
    assert row.photon_review_status==s['review']['status']
    assert row.photon_entry_model==s['entryModel']
    assert row.photon_mismatches=='; '.join(c['label']+': '+c['detail'] for c in s['review']['mismatches'])
    if collision=='target_only':
        assert pd.Timestamp(row.exit_time)>pd.Timestamp(row.entry_time)
    assert row[row.side.lower()+'_tp']==s['target']
    assert row[row.side.lower()+'_sl']==pytest.approx(s['stop'])
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:row.to_dict())
    evidence=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert evidence['status']=='AVAILABLE' and evidence['strategy']==MODE
    if collision=='flexible':
        assert evidence['review']['status']=='REVIEW_REQUIRED'
        assert 'existing 15m alignment' in row.photon_mismatches
        model=object.__new__(CompletedRunVisualizer);model.trades=trades
        assert 'REVIEW' in model.trade_label(0)
        assert model.selected_trade_summary(0)['Photon Review']=='REVIEW_REQUIRED'
