from dataclasses import asdict, replace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.imbalance_origin_retest import MODE, origin_retest_setups
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


def fixture(side="LONG"):
    h=np.array([10,10,10,10,10,10,14,15,13,12.],float)
    l=np.array([8,8,8,8,8,8,9,12,9,10.],float)
    o=np.array([9,9,9,9,9,9.5,9,13,9.5,11.])
    c=np.array([9,9,9,9,9,9,13,14,12,11.5])
    if side=="SHORT":o,h,l,c=30-o,30-l,30-h,30-c
    return pd.date_range("2026-01-01",periods=len(h),freq="1h",tz="UTC"),o,h,l,c,np.ones(len(h))


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_origin_rejection_is_causal_single_use_and_symmetric(side):
    args=fixture(side); result=origin_retest_setups(*args)
    assert [i for i,s in enumerate(result) if s] == [8]
    assert result[8]["side"]==side
    assert result[8]["target"]==15
    assert result[8]["zone"]["bottom"]==(8 if side=="LONG" else 20)
    for end in range(1,len(result)+1):
        assert origin_retest_setups(*(a[:end] for a in args))==result[:end]


@pytest.mark.parametrize("change",["partial_fill","breached","wrong_colour","gap","nan","no_structure","expired"])
def test_rejects_unqualified_entries(change):
    ts,o,h,l,c,atr=fixture();kw={};l[9]=10.5
    if change=="partial_fill":l[8]=10.5;o[8]=11
    if change=="breached":l[8]=7
    if change=="wrong_colour":o[8]=12.5
    if change=="gap":ts=ts[:8].append(ts[8:]+pd.Timedelta(hours=1))
    if change=="nan":c[8]=np.nan
    if change=="no_structure":h[1]=20
    if change=="expired":kw['max_wait']=1;l[8]=10.5;o[8]=11;l[9]=9
    assert not any(origin_retest_setups(ts,o,h,l,c,atr,**kw))


def test_production_engine_mode_execution_geometry_and_saved_evidence():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    from types import SimpleNamespace
    ts,o,h,l,c,atr=fixture()
    # Warm up ATR without introducing setups, then the known displacement/retest.
    n=60
    frame=pd.DataFrame(dict(timestamp=pd.date_range(ts[0]-pd.Timedelta(hours=n),periods=n+len(ts),freq='1h',tz='UTC'),
        open=np.r_[np.full(n,9.),o],high=np.r_[np.full(n,10.),h],low=np.r_[np.full(n,8.),l],close=np.r_[np.full(n,9.),c],volume=1.))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE
    native={k:StrategyProfile(**asdict(v)) for k,v in profiles.items()}
    cfg=BacktestConfig(strategy_timeframe_minutes=60,telemetry_interval_minutes=60,strategy_profiles=native,
        use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method='ASSET_RETURN',enable_trade_telemetry=False,sd_minimum_r=.1)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,cfg)
    engine.market_regime_values[:]='SIDEWAYS'
    assert engine.signal_strategy_mode==MODE
    assert engine._entry_decision(n+8)['execution_index']==n+9
    plan=engine._sr_stop_plan(n+8,n+9)
    assert plan['passed'] and plan['stop_price']<8 and plan['level_price']==15
    trades=engine.run()
    assert len(trades)>0
    setup=json.loads(trades.iloc[0].supply_demand_setup)
    assert setup['strategy']==MODE and setup['target']==15
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:trades.iloc[0].to_dict())
    assert CompletedRunVisualizer.supply_demand_derivation(fake,0)['status']=='AVAILABLE'
