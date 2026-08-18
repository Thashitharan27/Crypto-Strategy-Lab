import pandas as pd
import pytest
from crypto_strategy_lab.config import BacktestConfig, RiskMode, TrailApplyTo, TrailIntrabarMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.trade import ExitReason, ExitSource, Position, Side, TradePair
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


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


def test_profiles_enable_trailing_independently_by_direction_and_reuse_stored_r():
    e=engine()
    profiles={}
    for key in PROFILE_KEYS:
        profiles[key]=StrategyProfile(
            enabled=True,
            stop_loss_multiple=2,
            reward_risk_ratio=1.5,
            trailing_enabled=key.endswith("_long"),
            trailing_activation_r=3,
            trailing_distance_r=1,
        )
    e.config=BacktestConfig(
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        risk_mode=RiskMode.FIXED,
        fixed_r=2,
        enable_strategy_profiles=True,
        strategy_profiles=profiles,
    )
    e._open_pair(0)
    pair=e.active_pairs[0]
    assert pair.long.trailing_enabled and not pair.short.trailing_enabled
    assert pair.long.trailing_activation_price == pair.long.entry_price + pair.long.risk*3


def test_trailing_exit_reports_trigger_time_for_same_candle_later_candles_and_days(side, activation_offset, exit_offset):
    e=engine("PESSIMISTIC"); p=position(side)
    activation=p.entry_time + pd.Timedelta(minutes=activation_offset)
    exit_time=p.entry_time + pd.Timedelta(minutes=exit_offset)
    favourable=(104, 102) if side == Side.LONG else (98, 96)
    reversal=(103, 101) if side == Side.LONG else (99, 97)

    assert not e._maybe_exit_bar(p, 1, *favourable, activation, ExitSource.INTRABAR)
    assert e._maybe_exit_bar(p, 2, *reversal, exit_time, ExitSource.INTRABAR)

    assert p.exit_reason == ExitReason.TRAILING_STOP
    assert p.trailing_activation_time == activation
    assert p.exit_time == exit_time
    assert p.exit_time >= p.trailing_activation_time


def test_pessimistic_scan_does_not_replay_historical_intrabar_candles():
    e=engine("PESSIMISTIC")
    start=pd.Timestamp("2024-01-01 00:00", tz="UTC")
    e.intrabar_data=pd.DataFrame({
        "timestamp":pd.date_range(start, periods=61, freq="1min"),
        "open":[100.0]*61, "high":[101.0]*61, "low":[99.0]*61, "close":[100.0]*61,
    })
    e.config=BacktestConfig(use_intrabar_data=True,enable_trade_telemetry=False,risk_mode=RiskMode.FIXED,fixed_r=1,enable_trailing_profit=True,trail_intrabar_mode=TrailIntrabarMode.PESSIMISTIC,maker_fee=0,taker_fee=0,slippage=0)
    p=position(); p.entry_time=start + pd.Timedelta(minutes=15)
    e.intrabar_data.loc[31:45, ["high", "low"]]=[104.0, 104.0]
    e.intrabar_data.loc[46, ["high", "low"]]=[103.0, 102.0]

    assert not e._scan_exit(p, 2)
    assert p.trailing_activation_time == start + pd.Timedelta(minutes=31)
    assert e._scan_exit(p, 3)
    assert p.exit_time == start + pd.Timedelta(minutes=46)


def test_pair_holding_uses_final_leg_exit_and_timestamp_validations_are_clear():
    e=engine(); entry=pd.Timestamp("2024-01-01", tz="UTC")
    long=position(Side.LONG); short=position(Side.SHORT)
    long.exit_time=entry + pd.Timedelta(hours=1); short.exit_time=entry + pd.Timedelta(hours=3)
    for p in (long, short):
        p.exit_reason=ExitReason.TRAILING_STOP; p.trailing_active=True; p.trailing_activation_time=entry + pd.Timedelta(minutes=30)
        p.exit_price=p.entry_price; p.price_r=p.gross_pnl=p.net_pnl=p.gross_r=p.net_r=p.exit_fee=0; p.fees=p.entry_fee
    pair=TradePair(1,long,short,1000,entry,entry,100)
    pair.equity_after_trade=1000; e.completed_pairs=[pair]

    row=e.results_frame().iloc[0]
    assert row.exit_time == short.exit_time
    assert row.holding_minutes == 180
    assert row.holding_hours == 3
    assert row.holding_bars == 12
    assert row.holding_time == pd.Timedelta(hours=3)
    assert not row.timestamp_validation_failed
