from dataclasses import asdict, replace
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS
from crypto_strategy_lab.trade import ExitSource


def engine_with_setup(short=False, distance=.5, pct=10., target_distance=10., minimum=None):
    ts=pd.date_range('2026-01-01',periods=300,freq='15min',tz='UTC')
    frame=pd.DataFrame(dict(timestamp=ts,open=100.,high=101.,low=99.,close=100.,volume=1.))
    profiles,_=compile_profiles(direction_mode='SNEAKY_PIVOT',market_permissions=MARKET_PERMISSIONS)
    config=BacktestConfig(strategy_profiles={k:StrategyProfile(**asdict(p)) for k,p in profiles.items()},
        use_intrabar_data=True,intrabar_timeframe_minutes=1,enable_support_resistance_analysis=False,enable_trade_telemetry=False,
        taker_fee=.0005,maker_fee=.0005,slippage=.0005,sp_cost_cover_enabled=True,
        sp_cost_cover_close_pct=pct,sp_minimum_r_enabled=minimum is not None,sd_minimum_r=minimum or 1.5)
    minute=frame.loc[frame.index.repeat(15)].reset_index(drop=True)
    minute.timestamp=pd.date_range(ts[0],periods=len(minute),freq="1min",tz="UTC")
    e=RuleAwareDataLakeProductionBacktestEngine(frame,config,intrabar_data=minute)
    e.market_regime_values[:]='SIDEWAYS'
    sign=-1 if short else 1
    entry=100*(1+sign*config.slippage)
    setup={'side':'SHORT' if short else 'LONG','stop':entry-sign*distance,
           'target':entry+sign*target_distance,'setupAtr':1.}
    e.sd_setups[193]=setup
    e._sneaky_fill=100.
    return e,entry,setup


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('distance',[.5,4.])
@pytest.mark.parametrize('pct',[10.,20.])
def test_native_swing_floor_cost_cover_partial_and_be(short,distance,pct):
    e,entry,setup=engine_with_setup(short,distance,pct)
    e._open_pair(194,schedule={'indicator_index':193,'fill_price':100.,'actual_entry_timestamp':e.times[194]})
    pair=e.active_pairs[-1];p=pair.position
    sign=-1 if short else 1
    assert p.risk==pytest.approx(max(distance,p.sp_minimum_cost_stop_distance))
    assert p.sp_original_swing_stop_distance==pytest.approx(distance)
    assert p.quantity*p.risk==pytest.approx(p.risk_amount)
    assert p.original_sl==pytest.approx(entry-sign*p.risk)
    assert p.tp==p.tp2_price==setup['target']
    assert p.tp1_price==pytest.approx(entry+sign*p.risk)
    assert p.tp1_quantity/p.original_quantity==pytest.approx(pct/100.)
    e._maybe_exit_bar(p,194,max(entry,p.tp1_price)+.01,min(entry,p.tp1_price)-.01,e.times[194],ExitSource.INTRABAR)
    assert p.tp1_hit and p.is_open and p.sl==entry
    e._maybe_exit_bar(p,195,entry+.01,entry-.01,e.times[195],ExitSource.INTRABAR)
    assert not p.is_open and p.exit_reason.value=='BE'
    assert p.net_pnl>=-1e-8
    if p.risk>distance:
        assert p.net_pnl==pytest.approx(0,abs=1e-8)
    row=e._build_result_row(pair,'PAIR',[p])
    assert row['sp_cost_cover_enabled']
    assert row['break_even_activation_r']==1.
    assert not row['di_partial_1r_enabled']


@pytest.mark.parametrize('short',[False,True])
def test_adjusted_stop_rechecks_minimum_r_and_rejects_tp_before_partial(short):
    e,_,_=engine_with_setup(short,minimum=8.)
    assert e._sr_stop_plan(193,194)['reason']=='SNEAKY_MINIMUM_R_REJECTED'
    e,_,_=engine_with_setup(short,target_distance=1.)
    assert e._sr_stop_plan(193,194)['reason']=='SNEAKY_COST_COVER_INSUFFICIENT_ROOM'
    e._open_pair(194,schedule={'indicator_index':193,'fill_price':100.})
    assert not e.active_pairs


def test_config_roundtrip_and_conflicting_modes():
    from crypto_strategy_lab.gui.config_logic import build_backtest_config
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig, ExecutionConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=ResearchRunConfig(execution=ExecutionConfig(sp_cost_cover_enabled=True,sp_cost_cover_close_pct=15.))
    c.validate()
    n=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    assert n.sp_cost_cover_enabled and n.sp_cost_cover_close_pct==15.
    assert build_backtest_config({'sp_cost_cover_enabled':True,'sp_cost_cover_close_pct':20.},require_paths=False).sp_cost_cover_close_pct==20.
    for pct in (0,100,float('nan')):
        with pytest.raises(ValueError,match='percentage'):
            BacktestConfig(sp_cost_cover_enabled=True,sp_cost_cover_close_pct=pct)
    e,_,_=engine_with_setup()
    profiles=dict(e.config.strategy_profiles)
    profiles['sideways_long']=replace(profiles['sideways_long'],position_sizing_stop_override_enabled=True)
    with pytest.raises(ValueError,match='separate sizing'):
        replace(e.config,strategy_profiles=profiles)


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('event',['stop_first','final_tp'])
def test_partial_stop_priority_and_original_final_target(short,event):
    e,entry,setup=engine_with_setup(short)
    e._open_pair(194,schedule={'indicator_index':193,'fill_price':100.,'actual_entry_timestamp':e.times[194]})
    p=e.active_pairs[-1].position
    if event=='stop_first':
        e._maybe_exit_bar(p,194,max(p.original_sl,p.tp1_price)+.01,min(p.original_sl,p.tp1_price)-.01,e.times[194],ExitSource.INTRABAR)
        assert not p.tp1_hit and p.exit_reason.value=='SL'
    else:
        e._maybe_exit_bar(p,194,max(entry,p.tp1_price)+.01,min(entry,p.tp1_price)-.01,e.times[194],ExitSource.INTRABAR)
        assert p.is_open and p.tp1_hit
        e._maybe_exit_bar(p,195,max(p.tp1_price,p.tp)+.01,min(p.tp1_price,p.tp)-.01,e.times[195],ExitSource.INTRABAR)
        assert not p.is_open and p.exit_reason.value=='TP'
        assert p.tp2_exit_price==pytest.approx(setup['target'])
