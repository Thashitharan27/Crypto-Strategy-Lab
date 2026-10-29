from copy import deepcopy
from dataclasses import asdict
import json
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.photon_candle_pullback import candle_pullback_setups


def scenario(short=False):
    t=1767225600
    parents=[dict(time=t,open=110,high=111,low=104,close=106),
             dict(time=t+900,open=106,high=110,low=105,close=109),
             dict(time=t+1800,open=109,high=135,low=108,close=120)]
    bars=[]
    for p in parents:
        for j in range(15):bars.append(dict(time=p['time']+j*60,open=p['open'],high=p['high'],low=p['low'],close=p['close'] if j==14 else p['open']))
    bounds=dict(low=90,high=120,equilibrium=105,lowTime=t-1800,highTime=t-900)
    guides={'4h':dict(interval=14400,snapshots=[dict(availableAt=t,trend=1,range={**bounds,'low':80,'high':130})]),
            '15m':dict(interval=900,snapshots=[dict(availableAt=t+i*900,trend=-1 if i<2 else 1,range=deepcopy(bounds)) for i in range(4)],
                       events=[dict(kind='TREND_CHANGE',direction=1,availableAt=t+1800)])}
    if short:
        for b in bars:b.update(open=220-b['open'],high=220-b['low'],low=220-b['high'],close=220-b['close'])
        for g in guides.values():
            for s in g['snapshots']:
                s['trend']=-s['trend'];r=s['range'];s['range']={**r,'low':220-r['high'],'high':220-r['low'],'equilibrium':220-r['equilibrium']}
        guides['15m']['events'][0]['direction']=-1
    return bars,guides


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('tf',['15m','4h'])
def test_colour_change_target_stop_and_every_prefix(short,tf):
    bars,g=scenario(short);signals,live=candle_pullback_setups(bars,np.ones(len(bars)),g,target_timeframe=tf)
    assert [i for i,s in enumerate(signals) if s]==[29]
    s=signals[29]
    assert s['side']==('SHORT' if short else 'LONG')
    assert s['target']==(100 if short else 120) if tf=='15m' else s['target']==(90 if short else 130)
    assert s['stop']==pytest.approx(116.05 if short else 103.95)
    assert live[29]==29 and s['targetKnownAt']==bars[0]['time']
    for n in range(1,len(bars)+1):
        assert candle_pullback_setups(bars[:n],np.ones(n),g,target_timeframe=tf)==(signals[:n],live[:n])


@pytest.mark.parametrize('case',['opposing_4h','no_pullback','unknown_target','stale','gap','target_behind','minimum_r'])
def test_rejects_incomplete_setups(case):
    bars,g=scenario();kwargs={}
    if case=='opposing_4h':g['4h']['snapshots'][0]['trend']=-1
    if case=='no_pullback':bars[14]['close']=111
    if case=='unknown_target':g['15m']['snapshots'][0]['range']=None
    if case=='stale':g['4h']['snapshots'][0]['availableAt']-=14400
    if case=='gap':bars.pop(16)
    if case=='target_behind':g['15m']['snapshots'][0]['range']['high']=108
    if case=='minimum_r':kwargs['minimum_r']=100
    assert not any(candle_pullback_setups(bars,np.ones(len(bars)),g,**kwargs)[0])


def test_later_colour_confirmation_and_frozen_target():
    bars,g=scenario();t=bars[0]['time']
    # More red pullback candles: the first green candle triggers, regardless of swing events.
    bars[29]['close']=105.5
    for b in bars[30:]:b.update(open=106,high=115,low=105,close=106)
    bars[44]['close']=112
    g['15m']['snapshots'][2]['range']['high']=200
    signals,_=candle_pullback_setups(bars,np.ones(len(bars)),g)
    assert [i for i,s in enumerate(signals) if s]==[44]
    assert signals[44]['target']==120
    assert signals[44]['colourConfirmedAt']==t+2700
    assert signals[44]['trendChange15m'] is None


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('collision',[False,True])
@pytest.mark.parametrize('low_rr,min_gate',[(False,False),(True,False),(True,True)])
def test_engine_both_sides_next_open_and_old_flags_ignored(monkeypatch,short,collision,low_rr,min_gate):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles,MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars,g=scenario(short)
    if low_rr:g['15m']['snapshots'][0]['range']['low' if short else 'high']=109.5 if short else 110.5
    if collision:
        bars[30]['high' if short else 'low']=125 if short else 95
    pad=[dict(time=bars[0]['time']-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_midpoint_reversal.prepare_midpoint_context',lambda bars:g)
    p,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    config=BacktestConfig(strategy_timeframe_minutes=1,strategy_profiles={k:StrategyProfile(**asdict(v)) for k,v in p.items()},
        photon_candle_pullback=True,photon_candle_minimum_r_enabled=min_gate,photon_demand_pullback=True,photon_midpoint_reversal=True,photon_quarter_range=True,
        photon_midpoint_fixed_1r=True,photon_zone_reversal=True,photon_fixed_target_enabled=True,
        photon_exit_on_15m_change=True,photon_hold_tp_until_15m_reversal=True,
        use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False)
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'});frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    e=RuleAwareDataLakeProductionBacktestEngine(frame,config);e.market_regime_values[:]='SIDEWAYS';trades=e.run()
    if min_gate:
        assert len(trades)==0
        return
    assert len(trades)==1
    row=trades.iloc[0];side='short' if short else 'long'
    assert pd.Timestamp(row.entry_time)==frame.timestamp.iloc[180]
    assert row[side+'_tp']==((109.5 if short else 110.5) if low_rr else 100 if short else 120)
    assert row[side+'_final_exit_reason']==('SL' if collision else 'TP')
    assert json.loads(row.supply_demand_setup)['entryModel']=='CANDLE_PULLBACK_PREVIOUS_EXTREME'


@pytest.mark.parametrize('tf,label',[('15m','15m_Target'),('4h','4H_Target')])
def test_preset_roundtrip(tf,label):
    from crypto_strategy_lab.data_lake_config import load_data_lake_config,normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=normalize_data_lake_config(asdict(load_data_lake_config(f'config/data_lake/Photon_15m_Candle_Pullback_{label}_1m.json')))
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.photon_candle_pullback and native.photon_candle_target_timeframe==tf
    assert not native.photon_candle_minimum_r_enabled
    assert all(p.enabled for p in c.strategy.profiles.values())


def test_saved_setup_has_visualizer_evidence():
    from types import SimpleNamespace
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    bars,g=scenario();setups,_=candle_pullback_setups(bars,np.ones(len(bars)),g)
    model=SimpleNamespace(trade_count=1,_trade_row=lambda _:dict(supply_demand_setup=json.dumps(setups[29])))
    evidence=CompletedRunVisualizer.supply_demand_derivation(model,0)
    assert evidence['status']=='AVAILABLE'
    assert evidence['target']==120


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('event_kind',[None,'BOS','TREND_CHANGE'])
def test_colour_return_does_not_require_15m_swing_alignment_or_change(short,event_kind):
    bars,g=scenario(short)
    sign=-1 if short else 1
    for s in g['15m']['snapshots']:s['trend']=-sign
    g['15m']['events']=[] if event_kind is None else [dict(kind=event_kind,direction=-sign,availableAt=bars[29]['time']+60)]
    signals,_=candle_pullback_setups(bars,np.ones(len(bars)),g)
    assert signals[29]['entryRule']=='FIRST_COLOUR_RETURN'
    assert signals[29]['entryRuleVersion']==2
    assert signals[29]['trendChange15m'] is None


def test_rejected_first_colour_is_not_retried_on_later_same_colour():
    bars,g=scenario()
    # First green offers less than 1R; later green would offer ample room.
    bars[29]['close']=119
    for b in bars[30:]:b.update(open=109,high=116,low=108,close=115)
    signals,_=candle_pullback_setups(bars,np.ones(len(bars)),g,minimum_r=1)
    assert not any(signals)


def test_doji_does_not_trigger_and_later_first_green_does():
    bars,g=scenario()
    bars[29]['close']=bars[15]['open']
    for b in bars[30:]:b.update(open=106,high=115,low=105,close=106)
    bars[44]['close']=112
    signals,_=candle_pullback_setups(bars,np.ones(len(bars)),g)
    assert signals[29] is None and signals[44]


def reported_case():
    from pathlib import Path
    data=json.loads((Path(__file__).parent/'fixtures/photon_june1_colour_entry.json').read_text())
    return data['bars'],data['guides']


def test_reported_red_candle_triggers_before_later_swing_change():
    bars,g=reported_case()
    signals,_=candle_pullback_setups(bars,np.ones(len(bars)),g,target_timeframe='4h')
    s=next(x for x in signals if x)
    assert pd.Timestamp(s['triggerCandle']['time'])==pd.Timestamp('2026-06-01T17:30Z')
    assert s['signalAvailableAt']==int(pd.Timestamp('2026-06-01T17:45Z').timestamp())
    assert s['signalAvailableAt']<g['15m']['events'][0]['availableAt']
    assert s['stopBoundary']==71761.1  # The later 71788.5 peak is not known.
    assert s['target']==71035.3


def test_reported_entry_engine_fills_at_1745_and_not_1915(monkeypatch):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles,MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars,g=reported_case()
    pad=[dict(time=bars[0]['time']-(150-i)*60,open=71314.9,high=71324.9,low=71304.9,close=71314.9) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_midpoint_reversal.prepare_midpoint_context',lambda _:g)
    p,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    config=BacktestConfig(strategy_timeframe_minutes=1,strategy_profiles={k:StrategyProfile(**asdict(v)) for k,v in p.items()},
        photon_candle_pullback=True,photon_candle_target_timeframe='4h',use_intrabar_data=False,
        enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False)
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'});frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    e=RuleAwareDataLakeProductionBacktestEngine(frame,config);e.market_regime_values[:]='SIDEWAYS';trades=e.run()
    assert len(trades)==1
    row=trades.iloc[0]
    assert pd.Timestamp(row.entry_time)==pd.Timestamp('2026-06-01T17:45Z')
    assert row.entry_price==pytest.approx(71694.6*(1-config.slippage))
    assert json.loads(row.supply_demand_setup)['stopBoundary']==71761.1


def test_candle_chart_labels_distinguish_old_and_new_rules():
    import shutil,subprocess
    from crypto_strategy_lab.visualizer_photon import PHOTON_HELPERS
    node=shutil.which('node')
    if not node:pytest.skip('Node required')
    script=PHOTON_HELPERS+'''\nconst base={pullbackAt:1,signalAvailableAt:2,side:'SHORT'};
console.log(JSON.stringify({current:cslPhotonCandleLabels({...base,entryRule:'FIRST_COLOUR_RETURN'}),old:cslPhotonCandleLabels(base)}));'''
    result=json.loads(subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True).stdout)
    assert result['current'][1][1]=='First red 15m close confirmed'
    assert result['old'][1][1]=='15m swing change + colour confirmed'
    assert 'CHoCH' not in json.dumps(result)
