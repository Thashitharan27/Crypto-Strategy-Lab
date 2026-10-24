from dataclasses import asdict
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.imbalance_inducement import CONFIRMED, context_zones, inducement_setups, validate_model
from crypto_strategy_lab.imbalance_origin_retest import MODE
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS


def fixture(side='LONG'):
    highs=[10,11,12,13,12,11,13,15,14,13,15,17,16,15,17,19,18,17,22,23]
    lows=[7,8,9,10,9,8,10,12,11,10,12,14,13,12,14,16,15,15,16,20]
    bars=[];rows=[]
    for i,(h,l) in enumerate(zip(highs,lows)):
        t=pd.Timestamp('2026-01-01',tz='UTC')+pd.Timedelta(hours=i)
        o=c=(h+l)/2
        if i==17:o=16.5;c=15.8
        if i==18:o=16;c=21
        bars.append(dict(time=t,end=t+pd.Timedelta(hours=1),open=o,high=h,low=l,close=c))
        rows.extend([(o,h,l,c)]*4)
    rows.extend([(16,17.5,14.8,17.2),(17.2,18,17,17.8),(17.7,17.8,17.2,17.4),
                 (17.4,18.8,17.3,18.5),(17.5,18.4,17.4,18.2),(18.2,20,18,19.5)])
    a=np.array(rows,float)
    if side=='SHORT':a=40-a[:,[0,2,1,3]]
    ts=pd.date_range('2026-01-01',periods=len(a),freq='15min',tz='UTC')
    return bars,(ts,*a.T,np.ones(len(a)))


@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_completed_context_shift_separate_retest_and_prefix_causality(side):
    _,args=fixture(side)
    result=inducement_setups(*args,strength=1,displacement_atr=.5)
    assert [i for i,z in enumerate(result) if z]==[84]
    z=result[84]
    assert z['side']==side and z['entryModel']==CONFIRMED
    assert z['target']==(19 if side=='LONG' else 21)
    assert z['reversalExtreme']==pytest.approx(14.8 if side=='LONG' else 25.2)
    assert pd.Timestamp(z['zone']['confirmedTime'])<=pd.Timestamp(z['zone']['touchTime'])
    assert pd.Timestamp(z['shiftTime'])<=pd.Timestamp(z['entryZone']['touchTime'])
    assert pd.Timestamp(z['entryZone']['confirmedTime'])>pd.Timestamp(z['entryZone']['pivotTime'])
    for end in (60,77,78,79,80,81,82,83,84,85,86):
        assert inducement_setups(*(a[:end] for a in args),strength=1,displacement_atr=.5)==result[:end]


def test_context_requires_confirmed_trend_and_close_break_not_wick():
    bars,_=fixture()
    assert context_zones(bars,1,.5)[19]['target']==19
    for end in range(1,len(bars)+1):
        assert context_zones(bars[:end],1,.5)==context_zones(bars,1,.5)[:end]
    bars[18]['close']=18.5
    assert not any(context_zones(bars,1,.5))
    bars,_=fixture();bars[13]['low']=9
    assert not any(context_zones(bars,1,.5))
    bars,_=fixture();bars[17].update(low=11,close=11.5)
    assert not any(context_zones(bars,1,.5))


@pytest.mark.parametrize('change',['partial_fill','origin_close_failure','stop_breach','wick_shift','missing_lower','missing_context','expire','no_retest'])
def test_invalid_or_incomplete_confirmation_cannot_enter(change):
    _,args=fixture();ts,o,h,l,c,atr=args;kw={}
    if change=='partial_fill':l[80]=17.1;l[81]=17.1;o[80]=17.2;c[80]=17.4
    if change=='origin_close_failure':c[80]=14.9
    if change=='stop_breach':l[84]=14.7
    if change=='wick_shift':c[83]=17.9
    if change=='missing_lower':ts=ts[:83].append(ts[83:]+pd.Timedelta(minutes=15))
    if change=='missing_context':c[76]=np.nan
    if change=='expire':kw['max_wait']=1
    if change=='no_retest':l[84]=18;o[84]=18.1
    assert not any(inducement_setups(ts,o,h,l,c,atr,strength=1,displacement_atr=.5,**kw))


def test_production_entry_sweep_stop_target_and_saved_visualizer_evidence():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    _,(ts,o,h,l,c,atr)=fixture()
    frame=pd.DataFrame(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=1.))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    cfg=BacktestConfig(strategy_timeframe_minutes=15,telemetry_interval_minutes=15,
        strategy_profiles={k:StrategyProfile(**asdict(v)) for k,v in profiles.items()},
        use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',
        enable_trade_telemetry=False,io_entry_model=CONFIRMED,sd_swing_strength=1,ls_displacement_atr=.5,sd_minimum_r=.1)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,cfg);engine.market_regime_values[:]='SIDEWAYS'
    assert engine._entry_decision(84)['execution_index']==85
    plan=engine._sr_stop_plan(84,85)
    assert plan['passed'] and plan['stop_price']<14.8 and plan['level_price']==19
    # Next-open failure of the refined origin cannot use the wider sweep stop.
    expected=engine._expected_entry_price;engine._expected_entry_price=lambda *a:17.
    assert not engine._sr_stop_plan(84,85)['passed']
    engine._expected_entry_price=expected
    trades=engine.run();assert len(trades)>0
    setup=json.loads(trades.iloc[0].supply_demand_setup)
    assert setup['entryModel']==CONFIRMED
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:trades.iloc[0].to_dict())
    saved=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert saved['status']=='AVAILABLE' and isinstance(saved['shiftTime'],int)
    assert isinstance(saved['entryZone']['confirmedTime'],int)


def test_open_deeper_origin_filters_shallow_entry_in_complete_pipeline(monkeypatch):
    import copy
    import crypto_strategy_lab.imbalance_inducement as module
    bars,args=fixture()
    shallow=context_zones(bars,1,.5)[19]
    deep=copy.deepcopy(shallow)
    deep['zone'].update(bottom=10.,top=12.,confirmedTime=bars[18]['end'].isoformat())
    deep['imbalance'].update(bottom=12.,top=20.)
    def releases(bars,*args):
        result=[None]*len(bars)
        if len(bars)>18:result[18]=deep
        if len(bars)>19:result[19]=shallow
        return result
    monkeypatch.setattr(module,'context_zones',releases)
    assert not any(inducement_setups(*args,strength=1,displacement_atr=.5))
    deep['side']='SHORT'  # An opposite-side origin cannot veto this long.
    assert inducement_setups(*args,strength=1,displacement_atr=.5)[84]['side']=='LONG'


@pytest.mark.parametrize('model,context,entry',[('bad',60,15),(CONFIRMED,60,60),(CONFIRMED,60,45),(CONFIRMED,0,15),(CONFIRMED,60.5,15)])
def test_invalid_model_and_timeframe_rejected(model,context,entry):
    with pytest.raises(ValueError):validate_model(model,context,entry)


def test_config_adapter_and_legacy_default():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig,DataConfig,StrategyConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    cfg=ResearchRunConfig(data=DataConfig(strategy_timeframe_minutes=15),strategy=StrategyConfig(profiles=profiles),
        execution=ExecutionConfig(io_entry_model=CONFIRMED,io_context_minutes=240))
    native=native_simulator_config(cfg.data,cfg.features,cfg.strategy,cfg.execution)
    assert native.io_entry_model==CONFIRMED and native.io_context_minutes==240
    assert ExecutionConfig().io_entry_model=='ORIGIN_REJECTION'
