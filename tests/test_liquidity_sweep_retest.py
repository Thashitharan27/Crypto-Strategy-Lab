import json
from dataclasses import asdict,replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.liquidity_sweep_retest import MODE,liquidity_sweep_setups,validate_settings
from crypto_strategy_lab.strategy_rule_model import compile_profiles,infer_direction_mode,MARKET_PERMISSIONS


def fixture(side="LONG"):
    h=np.array([10,12,11,10,12,16,13,12,14,12,13,11.5,14.5,12,13.])
    l=np.array([8.5,9,8.5,8,9,11,10.5,10,11,10.05,10.8,9.7,10.4,10.8,11.5])
    o=(h+l)/2;c=o.copy();o[11]=10.9;c[11]=10.5;o[12]=10.5;c[12]=14.4;o[13]=11.3;c[13]=11.8
    if side=="SHORT":o,h,l,c=30-o,30-l,30-h,30-c
    return pd.date_range("2026-01-01",periods=len(h),freq="1h",tz="UTC"),o,h,l,c,np.ones(len(h))


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_sweep_displacement_retest_and_causal_prefixes(side):
    args=fixture(side)
    setups=liquidity_sweep_setups(*args,strength=1)
    assert [i for i,s in enumerate(setups) if s]==[13]
    setup=setups[13]
    assert setup["side"]==side
    assert setup["strategy"]==MODE
    assert setup["target"]==(16. if side=="LONG" else 14.)
    assert pd.Timestamp(setup["sweepTime"])==args[0][11]
    assert pd.Timestamp(setup["zone"]["confirmedTime"])==args[0][13]
    for end in range(1,len(args[0])+1):
        assert liquidity_sweep_setups(*(a[:end] for a in args),strength=1)==setups[:end]


@pytest.mark.parametrize("change",["unequal","no_sweep","no_reclaim","weak_displacement","wrong_colour","broken_zone","gap","expired"])
def test_missing_required_stage_rejects(change):
    ts,o,h,l,c,atr=fixture()
    kwargs={}
    if change=="unequal":kwargs['tolerance_atr']=.001
    if change=="no_sweep":l[11]=10.1
    if change=="no_reclaim":c[11]=9.9
    if change=="weak_displacement":c[12]=11.4
    if change=="wrong_colour":o[13]=11.9
    if change=="broken_zone":c[13]=9.5
    if change=="gap":ts=ts[:11].append(ts[11:]+pd.Timedelta(hours=1))
    if change=="expired":kwargs['max_wait']=1; c[13]=o[13];o[14]=11.;c[14]=11.6;l[14]=10.8
    assert not any(liquidity_sweep_setups(ts,o,h,l,c,atr,strength=1,**kwargs))


def test_invalid_settings_and_marker_round_trip():
    for args in [(-.1,1.,3,20),(.1,0.,3,20),(.1,1.,0,20),(.1,1.,3,0),(.1,float('nan'),3,20)]:
        with pytest.raises(ValueError):validate_settings(*args)
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE


@pytest.mark.parametrize("minutes",[15,60])
def test_production_geometry_next_open_and_saved_evidence(minutes):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    _,o,h,l,c,_=fixture();repeat=70
    o,h,l,c=[np.tile(a,repeat) for a in (o,h,l,c)]
    frame=pd.DataFrame(dict(timestamp=pd.date_range('2026-01-01',periods=len(c),freq=f'{minutes}min',tz='UTC'),open=o,high=h,low=l,close=c,volume=np.ones(len(c))))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()}
    config=BacktestConfig(strategy_timeframe_minutes=minutes,telemetry_interval_minutes=minutes,strategy_profiles=native,sd_swing_strength=1,use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,config);engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    assert len(trades)>0
    for row in trades.itertuples():
        setup=json.loads(row.supply_demand_setup)
        assert setup['strategy']==MODE
        assert pd.Timestamp(row.entry_time)==pd.Timestamp(row.signal_candle_time)+pd.Timedelta(minutes=minutes)
        assert getattr(row,row.side.lower()+'_tp')==setup['target']
        assert pd.Timestamp(setup['sweepTime'])<pd.Timestamp(setup['zone']['bounceTime'])<pd.Timestamp(setup['signalTime'])


def test_native_config_keeps_liquidity_parameters():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    config=ResearchRunConfig(execution=ExecutionConfig(ls_equal_tolerance_atr=.2,ls_displacement_atr=.8,ls_base_bars=4,ls_max_wait_bars=30))
    native=native_simulator_config(config.data,config.features,config.strategy,config.execution)
    assert (native.ls_equal_tolerance_atr,native.ls_displacement_atr,native.ls_base_bars,native.ls_max_wait_bars)==(.2,.8,4,30)
