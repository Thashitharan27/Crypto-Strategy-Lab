from dataclasses import asdict, replace
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.ny_opening_range import MODE, range_entry_plan
from crypto_strategy_lab.strategy_rule_model import compile_profiles, MARKET_PERMISSIONS


def setup(side='LONG'):
    return dict(side=side,stop=80. if side=='LONG' else 120.,zone=dict(bottom=90.,top=110.))


def sr(side='LONG',price=None,state=None):
    long=side=='LONG';prefix='support' if long else 'resistance'
    price=(96. if long else 104.) if price is None else price
    return {prefix+'_zone_low' if long else prefix+'_zone_high':price,
            'nearest_'+prefix+'_price':price,prefix+'_state':state or prefix.upper()+'_HELD'}


@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_default_preserves_geometry_skip_rejects_and_sr_refines_without_clamping(side):
    z=setup(side)
    default=range_entry_plan(z,100.,2.)
    assert default['passed'] and default['stop_price']==z['stop']
    assert range_entry_plan(z,100.,2.,policy='SKIP')['reason']=='NY_RANGE_TARGET_TOO_FAR'
    plan=range_entry_plan(z,100.,2.,policy='SR_STOP',sr_context=sr(side),atr=2.)
    assert plan['passed'] and plan['stop_source']=='CONFIRMED_SR'
    assert plan['stop_price']==pytest.approx(95.9 if side=='LONG' else 104.1)
    assert plan['target_price']==pytest.approx(108.2 if side=='LONG' else 91.8)
    assert plan['distance']<default['distance']
    assert abs(plan['target_price']-100.)/abs(100.-plan['stop_price'])==pytest.approx(2.)
    assert z==setup(side)  # Entry planning never mutates saved signal evidence.


@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_percentage_allowance_and_exact_limit_and_no_sr_needed_when_target_fits(side):
    z=setup(side);z['stop']=94. if side=='LONG' else 106.
    assert not range_entry_plan(z,100.,2.,policy='SKIP')['passed']
    plan=range_entry_plan(z,100.,2.,policy='SKIP',extension_pct=10.)
    assert plan['passed'] and plan['target_limit']==(112. if side=='LONG' else 88.)
    assert plan['target_price']==plan['target_limit']
    sr_plan=range_entry_plan(z,100.,2.,policy='SR_STOP',extension_pct=10.)
    assert sr_plan['passed'] and sr_plan['stop_source']=='BREAKOUT_EXTREME'
    # Check executable price again: an adverse change can exceed the cap.
    adverse=100.5 if side=='LONG' else 99.5
    assert not range_entry_plan(z,adverse,2.,policy='SKIP',extension_pct=10.)['passed']


@pytest.mark.parametrize('side',['LONG','SHORT'])
@pytest.mark.parametrize('case',['missing','broken','no_structure','wrong_side','not_nearer','too_wide','no_atr'])
def test_sr_option_skips_unsafe_or_missing_levels_instead_of_falling_back(side,case):
    z=setup(side);context=sr(side);atr=2.
    if case=='missing':context=None
    if case=='broken':context=sr(side,state=('SUPPORT_BROKEN' if side=='LONG' else 'RESISTANCE_BROKEN'))
    if case=='no_structure':context=sr(side,state='NO_SUPPORT_NEARBY' if side=='LONG' else 'NO_RESISTANCE_NEARBY')
    if case=='wrong_side':context=sr(side,102. if side=='LONG' else 98.)
    if case=='not_nearer':context=sr(side,79. if side=='LONG' else 121.)
    if case=='too_wide':context=sr(side,90. if side=='LONG' else 110.)
    if case=='no_atr':atr=np.nan
    plan=range_entry_plan(z,100.,2.,policy='SR_STOP',sr_context=context,atr=atr)
    assert not plan['passed']
    assert plan['reason'].startswith('NY_RANGE_')


def test_zero_buffer_does_not_require_atr_and_zone_edge_falls_back_to_level():
    plan=range_entry_plan(setup(),100.,2.,policy='SR_STOP',sr_context=dict(nearest_support_price=96.,support_state='SUPPORT_HELD'),atr=np.nan,sr_buffer_atr=0.)
    assert plan['passed'] and plan['stop_price']==96.


def test_configuration_round_trip_and_sr_dependency_are_explicit():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig,DataConfig,StrategyConfig,normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    cfg=ResearchRunConfig(data=DataConfig(strategy_timeframe_minutes=5),strategy=StrategyConfig(profiles=profiles),
        execution=ExecutionConfig(ny_range_overshoot_policy='SKIP',ny_range_max_extension_pct=15.,ny_range_sr_buffer_atr=.1))
    cfg.validate();restored=normalize_data_lake_config(cfg.to_dict())
    native=native_simulator_config(restored.data,restored.features,restored.strategy,restored.execution)
    assert (native.ny_range_overshoot_policy,native.ny_range_max_extension_pct,native.ny_range_sr_buffer_atr)==('SKIP',15.,.1)
    sr_cfg=replace(cfg,execution=replace(cfg.execution,ny_range_overshoot_policy='SR_STOP'))
    with pytest.raises(ValueError,match='requires support/resistance'):sr_cfg.validate()
    replace(sr_cfg,features=replace(sr_cfg.features,enable_support_resistance_analysis=True)).validate()
    for fields in (dict(ny_range_overshoot_policy='bad'),dict(ny_range_max_extension_pct=-1),dict(ny_range_sr_buffer_atr=np.nan)):
        with pytest.raises(ValueError):replace(cfg,execution=replace(cfg.execution,**fields)).validate()


def test_production_sr_stop_changes_risk_size_and_persists_actual_decision():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
    from test_ny_opening_range import fixture
    ts,o,h,l,c=fixture()
    frame=pd.DataFrame(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=1.))
    profiles,_=compile_profiles(direction_mode=MODE,market_permissions=MARKET_PERMISSIONS)
    cfg=BacktestConfig(strategy_timeframe_minutes=5,telemetry_interval_minutes=5,
        strategy_profiles={k:StrategyProfile(**asdict(v)) for k,v in profiles.items()},
        use_intrabar_data=False,enable_support_resistance_analysis=True,market_regime_method='ASSET_RETURN',
        enable_trade_telemetry=False,ny_range_overshoot_policy='SR_STOP',ny_range_sr_buffer_atr=0.)
    engine=RuleAwareDataLakeProductionBacktestEngine(frame,cfg);engine.market_regime_values[:]='SIDEWAYS'
    original_context=engine._analyze_support_resistance
    engine._analyze_support_resistance=lambda i,side: replace(original_context(i,side),**sr(side,108. if side=='SHORT' else 96.))
    plan=engine._sr_stop_plan(50,51)
    assert plan['passed'] and plan['stop_price']==108. and plan['original_stop']==117.
    rows=engine.run();assert not rows.empty
    row=rows.iloc[0];saved=json.loads(row.supply_demand_setup)
    assert saved['stop']==108. and saved['originalStop']==117.
    assert saved['stopSource']=='CONFIRMED_SR' and saved['overshootPolicy']=='SR_STOP'
    assert saved['target']>=saved['targetLimit']
    assert saved['target']==row.short_tp
    # The native position risk must use the selected stop, not the old extreme.
    assert row.short_sl==108.
    position=engine.completed_pairs[0].position
    assert position.risk==pytest.approx(abs(position.entry_price-108.))
    assert position.quantity==pytest.approx(cfg.initial_equity*cfg.risk_per_leg/position.risk)
    fake=SimpleNamespace(trade_count=1,_trade_row=lambda i:row.to_dict())
    view=CompletedRunVisualizer.supply_demand_derivation(fake,0)
    assert view['status']=='AVAILABLE' and isinstance(view['srAvailableAt'],int)
