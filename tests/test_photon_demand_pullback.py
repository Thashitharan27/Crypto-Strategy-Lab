from copy import deepcopy
from dataclasses import asdict
import json
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.photon_demand_pullback import demand_pullback_setups


def scenario(bearish=True):
    t = 1767225600
    bars = [dict(time=t+i*60, open=o, high=h, low=l, close=c) for i,(o,h,l,c) in enumerate([
        (108,109,107,108), (108,109,102,104), (104,106,103,105),
        (105,112,104,111), (111,131,110,130), (130,132,129,131)])]
    bounds = dict(low=100, high=160, equilibrium=130)
    snapshots = lambda trend, interval: dict(interval=interval, snapshots=[dict(
        availableAt=t, trend=trend, internal=trend, range=deepcopy(bounds))], events=[])
    guides = {'4h': snapshots(1,14400), '15m': snapshots(1,900),
              '1m': dict(interval=60, snapshots=[dict(availableAt=t+(i+1)*60,
                  trend=1, internal=(-1 if bearish and i in (1,2) else 1)) for i in range(6)], events=[])}
    guides['15m']['events'] = [dict(kind='TREND_CHANGE', direction=1, availableAt=t+60)]
    guides['15m']['supplyDemand'] = dict(zones=[dict(id='d', kind='DEMAND', timeframe='15m',
        lower=100, upper=105, availableAt=t+60, originTime=t-900)], events=[])
    return bars, guides


@pytest.mark.parametrize('bearish', [True,False])
def test_both_returns_and_prefix_invariance(bearish):
    bars,guides=scenario(bearish)
    signals,live=demand_pullback_setups(bars,np.ones(6),guides)
    assert [i for i,s in enumerate(signals) if s] == [3]
    s=signals[3]
    assert s['stop']==99.95 and s['target']==130
    assert s['returnModel']==('BEARISH_TO_BULLISH' if bearish else 'BULLISH_BOUNCE')
    for n in range(1,7):
        assert demand_pullback_setups(bars[:n],np.ones(n),guides)==(signals[:n],live[:n])


@pytest.mark.parametrize('case',['4h_bear','no_change','no_touch','invalidated','stale','15m_bear','gap','no_return','born_at_touch'])
def test_rejects_missing_or_invalid_sequence(case):
    bars,guides=scenario()
    t=bars[0]['time']
    if case=='4h_bear': guides['4h']['snapshots'][0]['trend']=-1
    if case=='no_change': guides['15m']['events']=[]
    if case=='no_touch': guides['15m']['supplyDemand']['zones'][0].update(lower=90,upper=95)
    if case=='invalidated': guides['15m']['supplyDemand']['events']=[dict(kind='INVALIDATED',zoneId='d',availableAt=t+180)]
    if case=='stale': guides['4h']['snapshots'][0]['availableAt']=t-14400
    if case=='15m_bear': guides['15m']['snapshots'].append(dict(availableAt=t+180,trend=-1,range=dict(low=100,high=160,equilibrium=130)))
    if case=='gap': bars[2]['time']+=30
    if case=='no_return':
        for s in guides['1m']['snapshots'][1:]: s['internal']=-1
    if case=='born_at_touch': guides['15m']['supplyDemand']['zones'][0]['availableAt']=t+180
    assert not any(demand_pullback_setups(bars,np.ones(6),guides)[0])


@pytest.mark.parametrize('preset,model',[('Demand_Pullback','ORIGINAL'),('First_Pullback','FIRST_PULLBACK'),('Sweep_Reclaim','SWEEP_RECLAIM')])
def test_config_roundtrip(preset,model):
    from crypto_strategy_lab.data_lake_config import load_data_lake_config, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=load_data_lake_config(f'config/data_lake/Photon_15m_{preset}_1m.json')
    c=normalize_data_lake_config(asdict(c))
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert native.photon_demand_pullback
    assert native.photon_demand_entry_model==model


@pytest.mark.parametrize('collision',[False,True])
@pytest.mark.parametrize('model',['ORIGINAL','FIRST_PULLBACK','SWEEP_RECLAIM'])
def test_engine_next_open_stop_and_midpoint(monkeypatch,collision,model):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS
    from crypto_strategy_lab.photon_trend import MODE
    bars,guides=sweep_scenario() if model=='SWEEP_RECLAIM' else scenario()
    entry_index=5 if model=='SWEEP_RECLAIM' else 4
    if model=='SWEEP_RECLAIM': bars[5].update(open=112,high=131,low=111,close=130)
    if collision: bars[entry_index]['low']=90
    pad=[dict(time=bars[0]['time']-(150-i)*60,open=110,high=111,low=109,close=110) for i in range(150)]
    monkeypatch.setattr('crypto_strategy_lab.photon_trend.prepare_context',lambda *args,**kwargs:guides)
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    config=BacktestConfig(strategy_timeframe_minutes=1,
        strategy_profiles={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()},
        photon_demand_pullback=True,photon_demand_entry_model=model,photon_zone_reversal=True,photon_midpoint_reversal=True,
        photon_midpoint_fixed_1r=True,photon_fixed_target_enabled=True,
        photon_exit_on_15m_change=True,photon_hold_tp_until_15m_reversal=True,
        use_intrabar_data=False,enable_support_resistance_analysis=False,
        market_regime_method='ASSET_RETURN',enable_trade_telemetry=False)
    frame=pd.DataFrame(pad+bars).rename(columns={'time':'timestamp'})
    frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True);frame['volume']=1.
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,config)
    engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    assert len(trades)==1
    row=trades.iloc[0]
    assert pd.Timestamp(row.entry_time)==frame.timestamp.iloc[150+entry_index]
    assert row.long_tp==130
    assert row.long_final_exit_reason==('SL' if collision else 'TP')
    assert json.loads(row.supply_demand_setup)['entryModel']==('15M_DEMAND_PULLBACK' if model=='ORIGINAL' else model)


def test_inactive_legacy_exit_options_do_not_block_new_model():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.photon_lesson import validate
    validate(BacktestConfig(photon_demand_pullback=True, photon_zone_reversal=True,
        photon_fixed_target_enabled=True, photon_hold_tp_until_15m_reversal=True,
        photon_exit_on_15m_change=True))


@pytest.mark.parametrize('bearish',[True,False])
def test_first_pullback_requires_origin_zone_and_price_break(bearish):
    bars,guides=scenario(bearish)
    signals,_=demand_pullback_setups(bars,np.ones(6),guides,entry_model='FIRST_PULLBACK')
    assert signals[3]['entryModel']=='FIRST_PULLBACK'
    assert signals[3]['pullbackHigh']==109
    guides['15m']['supplyDemand']['zones'][0]['availableAt']-=60
    assert not any(demand_pullback_setups(bars,np.ones(6),guides,entry_model='FIRST_PULLBACK')[0])


def sweep_scenario():
    bars,guides=scenario()
    t=bars[0]['time']
    guides['15m']['snapshots'][0]['low']={'price':103,'time':t-900}
    # Touch sweeps 103, bullish shift breaks 109, next candle retests 109.
    bars[4].update(open=111,high=113,low=108,close=112)
    return bars,guides


@pytest.mark.parametrize('model',['FIRST_PULLBACK','SWEEP_RECLAIM'])
def test_new_models_prefix_invariance(model):
    bars,guides=sweep_scenario()
    result=demand_pullback_setups(bars,np.ones(6),guides,entry_model=model)
    expected=3 if model=='FIRST_PULLBACK' else 4
    assert [i for i,s in enumerate(result[0]) if s]==[expected]
    for n in range(1,7):
        assert demand_pullback_setups(bars[:n],np.ones(n),guides,entry_model=model)==(result[0][:n],result[1][:n])


@pytest.mark.parametrize('case',['no_sweep','no_shift','no_retest','failed_retest','unknown_low','future_low','below_zone'])
def test_sweep_reclaim_rejects_missing_sequence(case):
    bars,guides=sweep_scenario()
    if case=='no_sweep':guides['15m']['snapshots'][0]['low']['price']=101
    if case=='no_shift':
        for s in guides['1m']['snapshots']:s['internal']=1
    if case=='no_retest':bars[4]['low']=110
    if case=='failed_retest':bars[4].update(low=107,close=108)
    if case=='unknown_low':guides['15m']['snapshots'][0].pop('low')
    if case=='future_low':
        guides['15m']['snapshots'][0].pop('low')
        future=deepcopy(guides['15m']['snapshots'][0]);future.update(availableAt=bars[2]['time']+60,low={'price':103})
        guides['15m']['snapshots'].append(future)
    if case=='below_zone':bars[2]['low']=99
    assert not any(demand_pullback_setups(bars,np.ones(6),guides,entry_model='SWEEP_RECLAIM')[0])


def test_entry_model_validation():
    from crypto_strategy_lab.photon_demand_pullback import validate_entry_model
    with pytest.raises(ValueError): validate_entry_model('typo')
