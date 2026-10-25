from copy import deepcopy
from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.photon_trend import MODE, trend_setups, resolve_retest
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS


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


def test_causal_real_context_prefix():
    # Real aggregation, structure and zone computation, independent of authored guide.
    rng=np.random.default_rng(24);n=700
    close=100+np.sin(np.arange(n)/13)*8+rng.normal(0,.2,n)
    bars=[dict(time=1767225600+i*60,open=float(close[max(0,i-1)]),high=float(max(close[max(0,i-1)],c)+.2),low=float(min(close[max(0,i-1)],c)-.2),close=float(c)) for i,c in enumerate(close)]
    full=trend_setups(bars,np.ones(n))
    for end in (60,301,650):
        assert trend_setups(bars[:end],np.ones(end))==(full[0][:end],full[1][:end])


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
    from crypto_strategy_lab.data_lake_config import load_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=load_data_lake_config('config/data_lake/Photon_4H_Trend_1m.json')
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.strategy_timeframe_minutes==1
    assert native.photon_confirmation_minutes==1440 and native.photon_retest_minutes==60
    with pytest.raises(ValueError,match='actual 1m'):
        replace(native,strategy_timeframe_minutes=15)
    with pytest.raises(ValueError,match='timeout'):
        replace(native,photon_retest_minutes=1.5)


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('collision',['normal','stop_and_target','target_only','flip','minimum_r','window'])
def test_production_engine_limit_geometry_costs_and_saved_evidence(monkeypatch,short,collision):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    bars,guides=walkthrough(short)
    signals,live=trend_setups(bars,np.ones(len(bars)),guides=guides)
    # Keep ATR/regime warmup separate from the authored market-structure evidence.
    pad=[dict(time=bars[0]['time']-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    source=pad+bars
    if collision=='stop_and_target':
        source[155].update(high=145,low=75)
    if collision=='window':
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
    if collision=='window':config=replace(config,trading_end_date=pd.Timestamp(bars[4]['time']+60,unit='s',tz='UTC').isoformat())
    frame=pd.DataFrame(source).rename(columns={'time':'timestamp'})
    frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,config);engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    if collision in ('flip','minimum_r','window'):
        assert len(trades)==0
        return
    assert len(trades)==1
    row=trades.iloc[0];s=json.loads(row.supply_demand_setup)
    assert pd.Timestamp(row.entry_time)==frame.timestamp.iloc[155]
    assert row.side==s['side']
    if collision=='stop_and_target':
        assert row[row.side.lower()+'_final_exit_reason']=='SL'
        assert pd.Timestamp(row.exit_time)==pd.Timestamp(row.entry_time)
    assert row.actual_entry_price==pytest.approx(s['entry']*(1-config.slippage if short else 1+config.slippage))
    assert row.pair_total_fees>0
    if collision=='target_only':
        assert pd.Timestamp(row.exit_time)>pd.Timestamp(row.entry_time)
    assert row[row.side.lower()+'_tp']==s['target']
    assert row[row.side.lower()+'_sl']==pytest.approx(s['stop'])
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:row.to_dict())
    evidence=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert evidence['status']=='AVAILABLE' and evidence['strategy']==MODE
