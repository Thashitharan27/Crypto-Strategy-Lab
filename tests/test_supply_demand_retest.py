from dataclasses import asdict, replace
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.supply_demand_retest import MODE, SupplyDemandRetestMixin, retest_setups
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


def fixture(side="LONG"):
    h=np.array([10,11,13,11,10,9,8,9,10,9,8,9,10,11,12.],float)
    l=np.array([8,9,10,9,8,5,6,7,8,7,5.5,6,7,8,9.],float)
    o=(h+l)/2; c=o.copy(); o[8]=8.;c[8]=9.8;o[9]=8.;c[9]=8.5
    if side=="SHORT": o,h,l,c=20-o,20-l,20-h,20-c
    return pd.date_range("2026-01-01",periods=len(h),freq="1h",tz="UTC"),o,h,l,c


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_confirmed_zone_touch_bounce_later_retest_and_prefix_causality(side):
    ts,o,h,l,c=fixture(side)
    result=retest_setups(ts,o,h,l,c)
    assert result[8] is None
    setup=result[9]
    assert setup["side"]==side
    assert pd.Timestamp(setup["zone"]["pivotTime"])==ts[5]
    assert pd.Timestamp(setup["zone"]["confirmedTime"])==ts[8]
    assert pd.Timestamp(setup["zone"]["touchTime"])==ts[8]
    assert pd.Timestamp(setup["zone"]["bounceTime"])==ts[8]
    assert setup["target"]== (13. if side=="LONG" else 7.)
    for end in range(1,len(ts)+1):
        assert retest_setups(ts[:end],o[:end],h[:end],l[:end],c[:end]) == result[:end]


@pytest.mark.parametrize("change",["doji","wrong_colour","broken_zone","missing_hour","no_bounce","unconfirmed_pivot"])
def test_invalid_retests_do_not_signal(change):
    ts,o,h,l,c=fixture()
    if change=="doji":c[9]=o[9]
    if change=="wrong_colour":c[9]=7.5
    if change=="broken_zone":c[9]=4.
    if change=="missing_hour":ts=ts[:8].append(ts[8:]+pd.Timedelta(hours=1))
    if change=="no_bounce":c[8]=8.5
    if change=="unconfirmed_pivot":l[7]=4.
    assert retest_setups(ts,o,h,l,c)[9] is None


def test_consumed_zone_does_not_repeat_and_snapshot_is_detached():
    ts,o,h,l,c=fixture();o[10]=7.;c[10]=7.5
    result=retest_setups(ts,o,h,l,c)
    assert result[9] is not None
    assert result[10] is None
    assert result[9]["zone"]["bounceTime"] == ts[8].isoformat()


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_native_geometry_and_next_open(side):
    ts,o,h,l,c=fixture(side)
    engine=SupplyDemandRetestMixin()
    engine.signal_strategy_mode=MODE
    engine.config=SimpleNamespace(sd_stop_buffer_atr=.1,sd_minimum_r=1.)
    engine.times=ts
    engine.sd_setups=retest_setups(ts,o,h,l,c)
    engine.atr_values=np.ones(len(ts))
    engine._effective_trade_direction=lambda i: side
    engine._expected_entry_price=lambda i,j,d: 8.5 if side=="LONG" else 11.5
    schedule=engine._entry_decision(9)
    assert schedule["execution_index"]==10
    plan=engine._sr_stop_plan(9,10)
    assert plan["passed"]
    assert plan["stop_price"]==pytest.approx(4.9 if side=="LONG" else 15.1)
    assert plan["level_price"]==(13. if side=="LONG" else 7.)
    engine.config.sd_minimum_r=10.
    assert not engine._sr_stop_plan(9,10)["passed"]
    engine.config.sd_minimum_r=1.
    engine._expected_entry_price=lambda i,j,d: 14. if side=="LONG" else 6.
    assert not engine._sr_stop_plan(9,10)["passed"]


def test_marker_and_config_round_trip_and_invalid_values():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig,DataConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles)==MODE
    config=ResearchRunConfig(execution=ExecutionConfig(sd_swing_strength=3,sd_stop_buffer_atr=.25,sd_minimum_r=2.))
    native=native_simulator_config(config.data,config.features,config.strategy,config.execution)
    assert (native.sd_swing_strength,native.sd_stop_buffer_atr,native.sd_minimum_r)==(3,.25,2.)
    for kwargs in [{"sd_swing_strength":0},{"sd_swing_strength":1.5},{"sd_stop_buffer_atr":-1},{"sd_minimum_r":0},{"sd_minimum_r":float("nan")}]:
        with pytest.raises(ValueError):
            ResearchRunConfig(execution=ExecutionConfig(**kwargs)).validate()


def test_production_engine_causal_entries_targets_and_saved_zones():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    rng=np.random.default_rng(11);n=1200
    c=100+8*np.sin(np.arange(n)/20)+rng.normal(0,.4,n);o=np.r_[c[0],c[:-1]]
    frame=pd.DataFrame(dict(timestamp=pd.date_range("2026-01-01",periods=n,freq="1h",tz="UTC"),open=o,high=np.maximum(o,c)+rng.uniform(.1,.8,n),low=np.minimum(o,c)-rng.uniform(.1,.8,n),close=c,volume=np.ones(n)))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    native={k:replace(StrategyProfile(**asdict(p)),trailing_enabled=True,stop_loss_multiple=2.) for k,p in profiles.items()}
    config=BacktestConfig(strategy_timeframe_minutes=60,telemetry_interval_minutes=60,strategy_profiles=native,use_intrabar_data=False,enable_support_resistance_analysis=False,market_regime_method="ASSET_RETURN",enable_trade_telemetry=False,sd_minimum_r=.1)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,config);engine.market_regime_values[:]='SIDEWAYS'
    trades=engine.run()
    assert len(trades)>0
    for row in trades.itertuples():
        setup=json.loads(row.supply_demand_setup)
        assert pd.Timestamp(row.entry_time)==pd.Timestamp(row.signal_candle_time)+pd.Timedelta(hours=1)
        assert getattr(row,row.side.lower()+"_tp")==setup["target"]
        assert pd.Timestamp(setup["zone"]["confirmedTime"])<=pd.Timestamp(setup["zone"]["touchTime"])
        assert pd.Timestamp(setup["zone"]["bounceTime"])<pd.Timestamp(setup["signalTime"])


def test_visualizer_reads_saved_zones_without_recomputing():
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    ts,o,h,l,c=fixture()
    setup=retest_setups(ts,o,h,l,c)[9]
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:{"supply_demand_setup":json.dumps(setup)})
    result=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert result["status"]=="AVAILABLE"
    assert result["zone"]["bottom"]==5.
    assert result["signalTime"]==int(ts[9].timestamp())
    fake._trade_row=lambda i:{"supply_demand_setup":"bad json"}
    assert CompletedRunVisualizer.supply_demand_derivation(fake,0)["status"]=="NOT_AVAILABLE"
