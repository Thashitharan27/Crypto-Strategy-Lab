from dataclasses import asdict
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.ny_opening_range import MODE, range_reversal_setups
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS
from crypto_strategy_lab.supply_demand_retest import SupplyDemandRetestMixin


def fixture(day='2026-06-01'):
    start=pd.Timestamp(day,tz='America/New_York').tz_convert('UTC')
    ts=pd.date_range(start,periods=56,freq='5min')
    rows=[(100.,110.,90.,100.)]*48
    rows.extend([(100,115,99,112),(112,117,108,111),(111,116,103,105),(105,108,100,102),
                 (100,103,88,100),(100,101,85,88),(88,103,84,100),(100,106,98,104)])
    return ts,*np.asarray(rows,float).T


def test_closed_range_reentry_full_extreme_multiple_trades_and_prefix_causality():
    args=fixture();result=range_reversal_setups(*args)
    assert [i for i,z in enumerate(result) if z]==[50,54]
    assert result[50]['side']=='SHORT' and result[50]['stop']==117
    assert result[54]['side']=='LONG' and result[54]['stop']==84
    assert result[50]['targetR']==2
    assert result[50]['zone']['bottom']==90 and result[50]['zone']['top']==110
    assert pd.Timestamp(result[50]['zone']['confirmedTime'])==args[0][48]
    for end in range(1,len(result)+1):
        assert range_reversal_setups(*(a[:end] for a in args))==result[:end]


@pytest.mark.parametrize('day,utc_hour,close_hour',[('2026-01-15',5,4),('2026-06-01',4,4),('2026-03-08',5,5),('2026-11-01',4,3)])
def test_new_york_offset_and_dst_use_exactly_four_elapsed_hours(day,utc_hour,close_hour):
    args=fixture(day);z=range_reversal_setups(*args)[50]
    start=pd.Timestamp(z['zone']['pivotTime']);end=pd.Timestamp(z['zone']['confirmedTime'])
    assert start.hour==utc_hour and end-start==pd.Timedelta(hours=4)
    assert end.tz_convert('America/New_York').hour==close_hour
    next_midnight=pd.Timestamp(z['dayEnd'])
    assert next_midnight.tz_convert('America/New_York').hour==0


def test_wicks_and_boundary_closes_do_not_trigger():
    ts,o,h,l,c=fixture();c[48]=109;c[49]=110
    assert range_reversal_setups(ts,o,h,l,c)[50] is None
    # A pending outside close may touch the boundary, then strictly re-enter.
    c[48]=112;c[49]=110
    assert range_reversal_setups(ts,o,h,l,c)[49] is None
    assert range_reversal_setups(ts,o,h,l,c)[50]['side']=='SHORT'


@pytest.mark.parametrize('change',['missing_opening','invalid_opening','partial_day','missing_excursion','invalid_excursion'])
def test_incomplete_range_or_unknown_excursion_cannot_signal(change):
    ts,o,h,l,c=fixture()
    if change=='missing_opening':ts=ts.delete(20);o,h,l,c=[np.delete(a,20) for a in (o,h,l,c)]
    if change=='invalid_opening':c[20]=np.nan
    if change=='partial_day':ts=ts[1:];o,h,l,c=[a[1:] for a in (o,h,l,c)]
    if change=='missing_excursion':ts=ts.delete(49);o,h,l,c=[np.delete(a,49) for a in (o,h,l,c)]
    if change=='invalid_excursion':c[49]=np.nan
    result=range_reversal_setups(ts,o,h,l,c)
    assert not any(z and z['side']=='SHORT' for z in result)


def test_cross_to_opposite_outside_is_not_a_reentry_and_does_not_reuse_extreme():
    ts,o,h,l,c=fixture();c[49]=88;l[49]=80
    z=range_reversal_setups(ts,o,h,l,c)[50]
    assert z['side']=='LONG' and z['stop']==80
    assert z['breakoutTime']==ts[49].isoformat()


def test_day_boundary_cancels_excursion_and_cannot_fill_at_next_midnight():
    ts=pd.date_range('2026-06-01',periods=576,freq='5min',tz='America/New_York').tz_convert('UTC')
    o=np.full(len(ts),100.);h=np.full(len(ts),110.);l=np.full(len(ts),90.);c=o.copy()
    c[286]=112;h[286]=115;c[287]=105
    result=range_reversal_setups(ts,o,h,l,c)
    assert not any(result)
    # A new day cannot inherit an excursion from the previous day.
    c[287]=112;h[287]=115
    assert not any(range_reversal_setups(ts,o,h,l,c))


@pytest.mark.parametrize('side,index,opening',[('SHORT',50,105.),('LONG',54,100.)])
def test_native_next_open_exact_stop_actual_fill_target_and_no_inherited_3r_filter(side,index,opening):
    args=fixture();engine=SupplyDemandRetestMixin()
    engine.signal_strategy_mode=MODE;engine.times=args[0];engine.sd_setups=range_reversal_setups(*args)
    engine.config=SimpleNamespace(strategy_timeframe_minutes=5,ny_range_target_r=2.,sd_minimum_r=3.)
    engine._effective_trade_direction=lambda i:side
    engine._expected_entry_price=lambda *a:opening
    schedule=engine._entry_decision(index);assert schedule['execution_index']==index+1
    plan=engine._sr_stop_plan(index,index+1);assert plan['passed']
    stop=117 if side=='SHORT' else 84
    assert plan['stop_price']==stop
    assert abs(plan['level_price']-opening)/abs(opening-stop)==2
    engine._expected_entry_price=lambda *a:111.
    assert engine._sr_stop_plan(index,index+1)['reason']=='NY_RANGE_ENTRY_OUTSIDE_RANGE'
    engine._expected_entry_price=lambda *a:stop
    assert engine._sr_stop_plan(index,index+1)['reason']=='NY_RANGE_INVALID_ENTRY_GEOMETRY'


def test_production_engine_saved_levels_and_visualizer():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    ts,o,h,l,c=fixture()
    # Force the first short to hit target before the later long setup.
    l[51]=75;c[51]=85
    frame=pd.DataFrame(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=1.))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE
    cfg=BacktestConfig(strategy_timeframe_minutes=5,telemetry_interval_minutes=5,
        strategy_profiles={k:StrategyProfile(**asdict(v)) for k,v in profiles.items()},use_intrabar_data=False,
        enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False,sd_minimum_r=3.)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,cfg);engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run();assert len(trades)>0
    row=trades.iloc[0];setup=json.loads(row.supply_demand_setup)
    assert setup['strategy']==MODE and setup['targetR']==2 and setup['stop']==117
    assert row.applied_reward_risk_ratio==2
    assert pd.Timestamp(row.entry_time)==ts[51]
    assert setup['target']==getattr(row,row.side.lower()+'_tp')
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:row.to_dict())
    saved=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert saved['status']=='AVAILABLE' and isinstance(saved['breakoutTime'],int)


def test_config_adapter_round_trip_and_timeframe_validation():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig,DataConfig,StrategyConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    cfg=ResearchRunConfig(data=DataConfig(strategy_timeframe_minutes=5),strategy=StrategyConfig(profiles=profiles),execution=ExecutionConfig(ny_range_target_r=2.5))
    cfg.validate()
    native=native_simulator_config(cfg.data,cfg.features,cfg.strategy,cfg.execution)
    assert native.ny_range_target_r==2.5
    with pytest.raises(ValueError,match='5m'):
        ResearchRunConfig(strategy=StrategyConfig(profiles=profiles)).validate()
    for r in (0,1.5,float('nan'),float('inf')):
        with pytest.raises(ValueError):ResearchRunConfig(execution=ExecutionConfig(ny_range_target_r=r)).validate()
