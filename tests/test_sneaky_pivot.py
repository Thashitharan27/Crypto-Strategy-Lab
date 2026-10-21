from dataclasses import asdict, replace
import json
import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.sneaky_pivot import MODE, sneaky_setups, validate_settings
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


def candles(short=False, days=3):
    n=96*days
    ts=pd.date_range('2026-01-01',periods=n,freq='15min',tz='UTC')
    o=np.full(n,15.);c=o.copy();h=o+1;l=o-1
    for d in range(days):
        j=d*96;h[j+10]=20;l[j+20]=10
        if d:
            o[j]=12;c[j]=10.2;h[j]=12.1;l[j]=10
            o[j+1]=10.3;c[j+1]=11;h[j+1]=11.2;l[j+1]=10.1
            o[j+2]=11;h[j+2]=12;l[j+2]=10.9;c[j+2]=11.5
    if short:o,h,l,c=30-o,30-l,30-h,30-c
    return ts,o,h,l,c,np.ones(n)


@pytest.mark.parametrize('short',[False,True])
def test_all_day_signal_frozen_geometry_and_causality(short):
    args=candles(short);s=sneaky_setups(*args)
    setup=s[97];assert setup is not None
    assert setup['side']==('SHORT' if short else 'LONG')
    assert setup['target']==(10 if short else 20)
    assert setup['stop']==pytest.approx(20.05 if short else 9.95)
    assert setup['trigger']==pytest.approx(18.8 if short else 11.2)
    # Prefixes include day boundary, initial test, confirmation and breakout.
    for end in [95,96,97,98,99,120,len(args[0])]:
        assert sneaky_setups(*(x[:end] for x in args))==s[:end]
    # Not restricted to midnight: move the setup to 06:00, using same prior day.
    ts,o,h,l,c,atr=candles(short)
    for x in (o,h,l,c):x[120:123]=x[96:99];x[96:99]=15
    assert sneaky_setups(ts,o,h,l,c,atr)[121] is not None


def test_four_saved_levels_and_legacy_reconstruction_match_without_future_data():
    from crypto_strategy_lab.sneaky_pivot import historical_levels
    ts,o,h,l,c,atr=candles(days=3)
    h[10]=25;l[20]=5
    setup=sneaky_setups(ts,o,h,l,c,atr)[193]
    assert setup is not None
    assert {x['role']:x['price'] for x in setup['levels']}=={
        'rangeHigh':20.,'rangeLow':10.,'swingHigh':25.,'swingLow':5.}
    frame=pd.DataFrame(dict(period_start=ts,high=h,low=l))
    assert historical_levels(frame,ts[192])==setup['levels']
    frame['period_start']=frame.period_start.dt.as_unit('us')
    assert historical_levels(frame,ts[192])==setup['levels']
    frame.loc[frame.period_start>=ts[192],['high','low']]=[999,0]
    assert historical_levels(frame,ts[192])==setup['levels']
    assert setup['levelsSource']=='Saved at setup'


def test_missing_outer_swings_are_explicit_not_substituted_with_range():
    setup=sneaky_setups(*candles())[97]
    assert [x['price'] for x in setup['levels'] if x['role'].startswith('swing')]==[None,None]


def test_legacy_visualizer_recovers_four_roles_without_rewriting_trade():
    from types import SimpleNamespace
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    ts,o,h,l,c,atr=candles(days=3);h[10]=25;l[20]=5
    setup=sneaky_setups(ts,o,h,l,c,atr)[193]
    expected=setup.pop('levels');setup.pop('levelsSource')
    raw=json.dumps(setup)
    model=object.__new__(CompletedRunVisualizer)
    model.trades=pd.DataFrame({'supply_demand_setup':[raw]})
    model.seed=SimpleNamespace(request=SimpleNamespace(period_start=ts[96]),config=ResearchRunConfig())
    model._market_frame=lambda *args,**kwargs:pd.DataFrame(dict(period_start=ts.as_unit('us'),high=h,low=l))
    result=model.supply_demand_derivation(0)
    assert result['status']=='AVAILABLE'
    assert result['levels']==expected
    assert result['levelsSource']=='Reconstructed historical context (legacy run)'
    assert model.trades.iloc[0].supply_demand_setup==raw


@pytest.mark.parametrize('change',['gap','weak','wrong_colour','break_level','no_prior_day'])
def test_missing_stage(change):
    ts,o,h,l,c,atr=candles(days=2)
    if change=='gap':ts=ts[:80].append(ts[80:]+pd.Timedelta(minutes=15))
    if change=='weak':o[96]=10.3
    if change=='wrong_colour':c[97]=10.2
    if change=='break_level':l[97]=9
    if change=='no_prior_day':ts=ts[1:];o,h,l,c,atr=[x[1:] for x in (o,h,l,c,atr)]
    s=sneaky_setups(ts,o,h,l,c,atr)
    assert not s[96 if change=='no_prior_day' else 97]


def test_settings_round_trip_and_requirements():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig, ExecutionConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    for values in [(-1,.5,3,1440),(.3,0,3,1440),(.3,.5,0,1440),(.3,.5,3,1),(.3,np.nan,3,1440)]:
        with pytest.raises(ValueError):validate_settings(*values)
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE
    cfg=ResearchRunConfig(execution=ExecutionConfig(sp_level_tolerance_atr=.2,sp_body_atr=.7,sp_confirmation_bars=4,sp_hold_minutes=300))
    native=native_simulator_config(cfg.data,cfg.features,cfg.strategy,cfg.execution)
    assert (native.sp_level_tolerance_atr,native.sp_body_atr,native.sp_confirmation_bars,native.sp_hold_minutes)==(.2,.7,4,300)
    cfg=replace(cfg,strategy=replace(cfg.strategy,profiles=profiles),data=replace(cfg.data,strategy_timeframe_minutes=60))
    with pytest.raises(ValueError,match='15m'):cfg.validate()


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('event',['fill','no_break','missing'])
def test_native_breakout_fill_saved_evidence_and_timeout(short,event):
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    ts,o,h,l,c,_=candles(short,days=12)
    if event=='no_break':
        for j in range(96,len(ts),96):
            if short:l[j+2]=18.8;c[j+2]=19.
            else:h[j+2]=11.2;c[j+2]=11.
    frame=pd.DataFrame(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=np.ones(len(ts))))
    minute=frame.loc[frame.index.repeat(15)].reset_index(drop=True)
    minute.timestamp=pd.date_range(ts[0],periods=len(minute),freq='1min',tz='UTC')
    if event=='missing':minute=minute.drop(index=98*15+4)
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    config=BacktestConfig(strategy_timeframe_minutes=15,intrabar_timeframe_minutes=1,
        strategy_profiles={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()},
        use_intrabar_data=True,enable_support_resistance_analysis=False,
        market_regime_method='ASSET_RETURN',enable_trade_telemetry=False,sp_hold_minutes=75)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,config,intrabar_data=minute)
    engine.market_regime_values[:]='SIDEWAYS'
    if event=='missing':
        with pytest.raises(ValueError,match='complete 1m'):engine.run()
        return
    trades=engine.run()
    if event=='no_break':
        assert len(trades)==0
        return
    assert len(trades)>0
    for row in trades.itertuples():
        setup=json.loads(row.supply_demand_setup)
        assert setup['strategy']==MODE
        assert row.entry_schedule_status=='SNEAKY_BREAKOUT_FILLED'
        assert pd.Timestamp(setup['signalTime'])+pd.Timedelta(minutes=15)<=pd.Timestamp(row.entry_time)<pd.Timestamp(setup['signalTime'])+pd.Timedelta(minutes=30)
        assert getattr(row,row.side.lower()+'_tp')==setup['target']
        assert getattr(row,row.side.lower()+'_sl')==pytest.approx(setup['stop'])
        assert pd.Timestamp(row.exit_time)<=pd.Timestamp(setup['setupStart'])+pd.Timedelta(minutes=75)


def test_visualizer_names_breakout_instead_of_next_open():
    from pathlib import Path
    source=Path('crypto_strategy_lab/strategy_visualizer_browser_v2.py').read_text(encoding='utf-8')
    assert 'All-day level test → reversal → breakout' in source
    assert 'Enter only on a breakout during the next 15m candle' in source
