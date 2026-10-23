from dataclasses import asdict, replace
import json
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.tjr_confluence import MODE, confluence_setups, validate_settings
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


def candles(short=False):
    o=np.array([20,19,15,12,14,15,12,11,10.5,15,14,14.3,15.1,16.])
    h=np.array([21,19.5,16,15,16,17,15,14,14,17,22,15.4,16,17.])
    l=np.array([19,17,14,10,12,12,11,9,10,14.5,13,14.1,15,15.5])
    c=np.array([20,17.2,15,12,14,15,12,12,13.5,16,20,15.2,15.8,16.5])
    if short:o,h,l,c=40-o,40-l,40-h,40-c
    return pd.date_range('2026-01-01',periods=len(o),freq='15min',tz='UTC'),o,h,l,c,np.ones(len(o))


@pytest.mark.parametrize('short',[False,True])
def test_all_five_concepts_and_prefix_causality(short):
    args=candles(short);s=confluence_setups(*args,strength=1)
    assert [i for i,x in enumerate(s) if x]==[11]
    z=s[11];assert z['side']==('SHORT' if short else 'LONG')
    assert z['sweepTime']==args[0][7].isoformat()
    assert z['structureTime']==z['inverseTime']==(args[0][10]+pd.Timedelta(minutes=15)).isoformat()
    assert z['equilibrium']==pytest.approx(24.5 if short else 15.5)
    assert z['zone']['entryBottom']==pytest.approx(25.5 if short else 14.)
    assert z['zone']['entryTop']==pytest.approx(26. if short else 14.5)
    assert z['inverseFvg'] is not None
    for end in range(1,len(args[0])+1):
        assert confluence_setups(*(a[:end] for a in args),strength=1)==s[:end]


@pytest.mark.parametrize('change',['no_sweep','no_reclaim','no_ifvg','no_structure','no_retest','wrong_colour','small_body','broken_sweep','broken_fvg','expired','gap','nan'])
def test_missing_stage_rejects(change):
    ts,o,h,l,c,a=candles();kw={}
    if change=='no_sweep':l[7]=10.1
    if change=='no_reclaim':c[7]=9.8
    if change=='no_ifvg':o[1]=17.4
    if change=='no_structure':h[5]=23
    if change=='no_retest':l[11]=14.7;o[11]=15.;c[11]=15.2
    if change=='wrong_colour':o[11]=15.3
    if change=='small_body':o[11]=15.1
    if change=='broken_sweep':l[10]=8.9
    if change=='broken_fvg':c[11]=13.9;l[11]=13.8
    if change=='expired':kw['max_wait']=3
    if change=='gap':ts=ts[:9].append(ts[9:]+pd.Timedelta(minutes=15))
    if change=='nan':c[9]=np.nan
    assert not any(confluence_setups(ts,o,h,l,c,a,strength=1,**kw))


@pytest.mark.parametrize('toggle,change',[('require_ifvg','ifvg'),('require_structure','structure'),('require_equilibrium','equilibrium')])
def test_optional_confirmations(toggle,change):
    ts,o,h,l,c,a=candles()
    if change=='ifvg':o[1]=17.4
    if change=='structure':h[5]=23
    if change=='equilibrium':c[11]=15.8;h[11]=16.
    assert not any(confluence_setups(ts,o,h,l,c,a,strength=1))
    assert any(confluence_setups(ts,o,h,l,c,a,strength=1,**{toggle:False}))


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('minutes',[15,60])
def test_native_next_open_geometry_and_saved_evidence(short,minutes):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    _,o,h,l,c,_=candles(short)
    o,h,l,c=[np.r_[np.full(200,20.),np.tile(x,8)] for x in (o,h,l,c)]
    ts=pd.date_range('2026-01-01',periods=len(o),freq=f'{minutes}min',tz='UTC')
    frame=pd.DataFrame(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=1.))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE
    cfg=BacktestConfig(strategy_profiles={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()},
        strategy_timeframe_minutes=minutes,telemetry_interval_minutes=minutes,sd_swing_strength=1,tc_displacement_atr=.01,
        sd_stop_buffer_atr=.1,tc_target_r=3.,slippage=.0001,use_intrabar_data=False,
        enable_support_resistance_analysis=False,enable_trade_telemetry=False)
    e=RuleAwareDataLakeProductionBacktestEngine(frame,cfg);e.market_regime_values[:]='SIDEWAYS'
    trades=e.run();assert len(trades)>0
    for _,r in trades.iterrows():
        side=r.side.lower();sign=1 if side=='long' else -1
        z=json.loads(r.supply_demand_setup)
        assert z['strategy']==MODE and z['requiredIfvg'] and z['requiredStructure'] and z['requiredEquilibrium']
        assert pd.Timestamp(r.entry_time)==pd.Timestamp(z['signalTime'])+pd.Timedelta(minutes=minutes)
        assert sign*(r[side+'_entry_price']-r[side+'_original_sl'])>0
        risk=abs(r[side+'_entry_price']-r[side+'_original_sl'])
        assert r[side+'_tp']==pytest.approx(r[side+'_entry_price']+sign*3*risk)
        assert r[side+'_original_sl']==pytest.approx(z['sweepExtreme']-sign*.1*z['setupAtr'])
        assert r.applied_reward_risk_ratio==3.


def test_settings_roundtrip_and_validation():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    from crypto_strategy_lab.gui.config_logic import build_backtest_config
    cfg=ResearchRunConfig(execution=ExecutionConfig(tc_target_r=4.,tc_require_ifvg=False,tc_min_reversal_body_percent=60.))
    cfg.validate();n=native_simulator_config(cfg.data,cfg.features,cfg.strategy,cfg.execution)
    assert n.tc_target_r==4. and not n.tc_require_ifvg and n.tc_min_reversal_body_percent==60.
    assert build_backtest_config({'tc_target_r':4.,'tc_require_ifvg':False},require_paths=False).tc_target_r==4.
    for args in [(0,30,64,50,3),(.5,0,64,50,3),(.5,30,0,50,3),(.5,30,64,101,3),(.5,30,64,50,0)]:
        with pytest.raises(ValueError):validate_settings(*args)


def test_visualizer_reads_saved_confluence_without_reconstruction():
    from types import SimpleNamespace
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    setup=confluence_setups(*candles(),strength=1)[11]
    setup.update(target=34.,stop=8.9,targetR=3.)
    holder=SimpleNamespace(trade_count=1,_trade_row=lambda index:{'supply_demand_setup':json.dumps(setup)})
    result=CompletedRunVisualizer.supply_demand_derivation(holder,0)
    assert result['status']=='AVAILABLE'
    assert isinstance(result['signalTime'],int)
    assert isinstance(result['inverseFvg']['confirmedTime'],int)
    assert result['zone']['entryBottom']==14.


@pytest.mark.parametrize('short',[False,True])
def test_actual_gap_fill_must_remain_in_equilibrium_half(short):
    from types import SimpleNamespace
    from crypto_strategy_lab.supply_demand_retest import SupplyDemandRetestMixin
    class Engine(SupplyDemandRetestMixin):
        signal_strategy_mode=MODE
        def _effective_trade_direction(self,i):return 'SHORT' if short else 'LONG'
        def _expected_entry_price(self,i,execution_i,side):return 24. if short else 16.
    e=Engine();e.config=SimpleNamespace(sd_stop_buffer_atr=.1,tc_require_equilibrium=True,tc_target_r=3.,sd_minimum_r=1.5)
    e.atr_values=np.ones(1);e.sd_setups=[confluence_setups(*candles(short),strength=1)[11]]
    assert not e._sr_stop_plan(0,1)['passed']
    e.config.tc_require_equilibrium=False;e.config.strategy_timeframe_minutes=15
    assert e._sr_stop_plan(0,1)['passed']
