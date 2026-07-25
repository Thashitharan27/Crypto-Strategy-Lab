import pandas as pd
import pytest
from config import BacktestConfig, RiskMode, TrailApplyTo, TrailIntrabarMode
from engine import BacktestEngine
from trade import ExitReason, ExitSource, Position, Side


def engine(mode="PESSIMISTIC", enabled=True):
    data=pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=20,freq="15min",tz="UTC"),"open":[100]*20,"high":[101]*20,"low":[99]*20,"close":[100]*20})
    cfg=BacktestConfig(use_intrabar_data=False,enable_trade_telemetry=False,risk_mode=RiskMode.FIXED,fixed_r=1,enable_trailing_profit=enabled,trail_intrabar_mode=TrailIntrabarMode(mode),maker_fee=0,taker_fee=0,slippage=0)
    return BacktestEngine(data,cfg)


def position(side=Side.LONG):
    p=Position(side,pd.Timestamp("2024-01-01",tz="UTC"),0,100,1,98 if side==Side.LONG else 102,103 if side==Side.LONG else 97,1,1,100,1,original_sl=98 if side==Side.LONG else 102)
    p.trailing_enabled=True; p.trailing_activation_price=103 if side==Side.LONG else 97; p.favourable_price=100
    return p

@pytest.mark.parametrize("side,high,low,expected",[(Side.LONG,103,102,102),(Side.SHORT,98,97,98)])
def test_activation_then_reversal_exits_at_two_r_optimistic(side,high,low,expected):
    e=engine("OPTIMISTIC"); p=position(side)
    assert e._maybe_exit_bar(p,1,high,low,p.entry_time,ExitSource.FALLBACK_15M)
    assert p.exit_reason==ExitReason.TRAILING_STOP; assert p.exit_price==expected; assert p.price_r==2

@pytest.mark.parametrize("side,first,second",[(Side.LONG,(105,104),(104,103)),(Side.SHORT,(96,95),(97,96))])
def test_trailing_stop_is_monotonic(side,first,second):
    e=engine(); p=position(side); p.trailing_active=True
    e._maybe_exit_bar(p,1,*first,p.entry_time,ExitSource.FALLBACK_15M); old=p.trailing_stop
    e._maybe_exit_bar(p,2,*second,p.entry_time,ExitSource.FALLBACK_15M)
    assert p.trailing_stop >= old if side==Side.LONG else p.trailing_stop <= old


def test_pessimistic_activation_bar_defers_new_stop_but_optimistic_exits():
    pessimistic=position(); optimistic=position()
    assert not engine("PESSIMISTIC")._maybe_exit_bar(pessimistic,1,103,102,pessimistic.entry_time,ExitSource.FALLBACK_15M)
    assert engine("OPTIMISTIC")._maybe_exit_bar(optimistic,1,103,102,optimistic.entry_time,ExitSource.FALLBACK_15M)


def test_fixed_tp_unchanged_when_trailing_disabled():
    e=engine(enabled=False); p=position(); p.trailing_enabled=False
    assert e._maybe_exit_bar(p,1,103,99,p.entry_time,ExitSource.FALLBACK_15M)
    assert p.exit_reason==ExitReason.TP


def test_apply_to_is_independent_and_reuses_stored_r():
    e=engine(); e.config=BacktestConfig(use_intrabar_data=False,enable_trade_telemetry=False,risk_mode=RiskMode.FIXED,fixed_r=2,enable_trailing_profit=True,trail_apply_to=TrailApplyTo.LONG_ONLY)
    e._open_pair(0); pair=e.active_pairs[0]
    assert pair.long.trailing_enabled and not pair.short.trailing_enabled
    assert pair.long.trailing_activation_price == pair.long.entry_price + pair.long.risk*3
