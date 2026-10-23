from dataclasses import replace

import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles
from crypto_strategy_lab.trade import Side, ExitSource
from crypto_strategy_lab.di_partial_cost import minimum_cost_cover_distance


def opened(short=False, adjust=True, pct=10., fee=.0005, slip=.0005, atr_multiplier=1.):
    frame = pd.DataFrame(dict(timestamp=pd.date_range('2026-01-01',periods=4,freq='15min'),
                              open=[100.]*4,high=[100.1]*4,low=[99.9]*4,close=[100.]*4,volume=[1.]*4))
    profiles = default_profiles()
    profiles['sideways_short' if short else 'sideways_long'] = StrategyProfile(
        enabled=True,di_partial_1r_enabled=True, di_partial_1r_close_pct=pct,
        di_partial_cost_atr_enabled=adjust, reward_risk_ratio=3., stop_loss_multiple=2.)
    config = BacktestConfig(strategy_profiles=profiles,atr_period=1,risk_mode='ATR',atr_multiplier=atr_multiplier,
                            use_intrabar_data=False,enable_trade_telemetry=False,
                            taker_fee=fee,maker_fee=fee,slippage=slip)
    e = BacktestEngine(frame,config)
    e.market_regime_values[:]='SIDEWAYS'
    e.plus_di_values[:]=10 if short else 50
    e.minus_di_values[:]=50 if short else 10
    e._open_pair(0)
    return e,e.active_pairs[0].position


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('pct',[5.,10.,20.,50.])
def test_adjusted_stop_covers_native_costs_at_partial_then_be(short,pct):
    e,p=opened(short,pct=pct)
    sign=-1 if short else 1
    assert p.risk >= p.di_partial_original_stop_distance
    assert p.risk == pytest.approx(max(p.di_partial_original_stop_distance,p.di_partial_minimum_cost_stop_distance))
    assert p.quantity*p.risk == pytest.approx(p.risk_amount)
    assert p.tp1_quantity/p.original_quantity == pytest.approx(pct/100)
    assert p.tp1_price == pytest.approx(p.entry_price+sign*p.risk)
    assert p.tp2_price == pytest.approx(p.entry_price+sign*3*p.risk)
    ts=pd.Timestamp(p.entry_time)
    high=p.entry_price-.01 if short else p.tp1_price+.01
    low=p.tp1_price-.01 if short else p.entry_price+.01
    e._maybe_exit_bar(p,1,high,low,ts,ExitSource.INTRABAR)
    assert p.is_open and p.tp1_hit and p.be_triggered
    assert p.sl == p.entry_price
    e._maybe_exit_bar(p,2,p.entry_price+.01,p.entry_price-.01,ts+pd.Timedelta(minutes=1),ExitSource.INTRABAR)
    assert not p.is_open
    assert p.exit_reason.value=='BE'
    assert p.net_pnl >= -1e-8
    if p.risk > p.di_partial_original_stop_distance:
        assert p.net_pnl == pytest.approx(0,abs=1e-8)
    assert p.fees == pytest.approx(p.entry_fee+p.tp1_fees+p.stop_fees)


def test_first_option_alone_does_not_adjust_atr_or_promise_zero_cost_exit():
    e,p=opened(adjust=False)
    assert p.risk == pytest.approx(.4)
    assert p.risk == p.di_partial_original_stop_distance
    e._maybe_exit_bar(p,1,p.tp1_price+.01,p.entry_price+.01,p.entry_time,ExitSource.INTRABAR)
    e._maybe_exit_bar(p,2,p.entry_price+.01,p.entry_price-.01,pd.Timestamp(p.entry_time)+pd.Timedelta(minutes=1),ExitSource.INTRABAR)
    assert p.net_pnl<0


def test_wider_existing_stop_is_not_tightened():
    e,p=opened(atr_multiplier=100.)
    assert p.risk == p.di_partial_original_stop_distance
    assert p.risk > p.di_partial_minimum_cost_stop_distance
    assert p.quantity*p.risk == pytest.approx(p.risk_amount)


def test_larger_partial_requires_smaller_cost_cover_distance():
    assert minimum_cost_cover_distance(100,1,.1,.0005,.0005,.0005) == pytest.approx(
        2*minimum_cost_cover_distance(100,1,.2,.0005,.0005,.0005))


def test_new_be_stop_is_not_applied_earlier_in_the_trigger_candle():
    e,p=opened()
    e._maybe_exit_bar(p,1,p.tp1_price+.01,p.entry_price-.01,p.entry_time,ExitSource.INTRABAR)
    assert p.is_open and p.be_triggered


def test_original_sl_precedes_partial_on_ambiguous_bar():
    e,p=opened()
    e._maybe_exit_bar(p,1,p.tp1_price+.01,p.original_sl-.01,p.entry_time,ExitSource.INTRABAR)
    assert not p.tp1_hit
    assert p.exit_reason.value=='SL'


@pytest.mark.parametrize('pct',[0,100,float('nan'),float('inf')])
def test_invalid_partial_percent_is_rejected(pct):
    with pytest.raises(ValueError,match='percentage'):
        StrategyProfile(di_partial_1r_enabled=True,di_partial_1r_close_pct=pct).validate('test')


def test_profile_roundtrip_preserves_di_options_in_native_adapter():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig
    from crypto_strategy_lab.research_adapters import native_simulator_config
    c=ResearchRunConfig();profiles=dict(c.execution.profiles)
    profiles['sideways_long']=replace(profiles['sideways_long'],reward_risk_ratio=3.,di_partial_1r_enabled=True,
                                      di_partial_1r_close_pct=12.5,di_partial_cost_atr_enabled=True)
    c=replace(c,execution=replace(c.execution,profiles=profiles))
    native=native_simulator_config(c.data,c.features,c.strategy,c.execution)
    p=native.strategy_profiles['sideways_long']
    assert p.di_partial_1r_enabled and p.di_partial_cost_atr_enabled
    assert p.di_partial_1r_close_pct==12.5


def test_native_production_composition_keeps_di_partial_geometry():
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    e,p=opened()
    production=RuleAwareDataLakeProductionBacktestEngine(e.data,e.config)
    production.market_regime_values[:]='SIDEWAYS'
    production.plus_di_values[:]=50.
    production.minus_di_values[:]=10.
    production._open_pair(0)
    q=production.active_pairs[0].position
    assert q.di_partial_1r_enabled
    assert q.risk==pytest.approx(p.risk)
    assert q.tp1_quantity==pytest.approx(p.tp1_quantity)
    assert q.tp2_price==pytest.approx(p.tp2_price)


def test_cost_mode_requires_atr_and_actual_stop_sizing():
    e,p=opened()
    with pytest.raises(ValueError,match='ATR risk mode'):
        replace(e.config,risk_mode='FIXED')
    profile=e.config.strategy_profiles['sideways_long']
    with pytest.raises(ValueError,match='actual adjusted stop'):
        replace(profile,position_sizing_stop_override_enabled=True).validate()


def test_zero_costs_leave_atr_unchanged():
    e,p=opened(fee=0.,slip=0.)
    assert p.risk==pytest.approx(.4)
    assert p.di_partial_minimum_cost_stop_distance==0.


def test_final_target_closes_only_remaining_quantity_and_reports_effective_plan():
    e,p=opened()
    e._maybe_exit_bar(p,1,p.tp2_price+.01,p.entry_price+.01,p.entry_time,ExitSource.INTRABAR)
    assert not p.is_open and p.tp1_hit and p.tp2_hit
    assert p.tp1_quantity/p.original_quantity==pytest.approx(.1)
    assert p.tp2_quantity/p.original_quantity==pytest.approx(.9)
    assert p.remaining_quantity==0.
    row=e._build_result_row(e.active_pairs[0],'long',[p])
    assert row['di_partial_1r_enabled'] and row['di_partial_cost_atr_enabled']
    assert row['tp1_close_pct']==10.
    assert row['tp1_r']==1. and row['tp2_r']==3.
