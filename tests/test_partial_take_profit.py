import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, RiskMode, TiePolicy
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles


def candles(*bars):
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
                "open": 100,
                "close": 100,
                "high": high,
                "low": low,
                "volume": 1,
            }
            for i, (high, low) in enumerate(bars)
        ]
    )


def base_profile(**changes):
    values = dict(
        enabled=True,
        stop_loss_multiple=2,
        partial_profit_enabled=True,
        tp1_r=1,
        tp1_close_pct=50,
        tp2_r=2,
    )
    values.update(changes)
    return StrategyProfile(**values)


def open_long(*bars, profile=None, fee=0, tie_policy=TiePolicy.PESSIMISTIC, engine_class=BacktestEngine):
    profiles = default_profiles()
    profiles["sideways_long"] = profile or base_profile()
    cfg = BacktestConfig(
        risk_mode=RiskMode.FIXED,
        fixed_r=10,
        atr_period=1,
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        strategy_profiles=profiles,
        maker_fee=0,
        taker_fee=fee,
        slippage=0,
        tie_policy=tie_policy,
    )
    engine = engine_class(candles(*bars), cfg)
    engine.market_regime_values[:] = "SIDEWAYS"
    engine.plus_di_values[:] = 50
    engine.minus_di_values[:] = 10
    engine.di_spread[:] = 40
    engine._open_pair(0)
    pair = engine.active_pairs[0]
    assert pair.long is not None and pair.short is None
    return engine, pair.long


def test_long_tp1_then_stop_closes_only_remainder():
    engine, position = open_long((100, 100), (120, 99), (105, 79))
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.sl == pytest.approx(80)
    assert engine._scan_exit(position, 2)
    assert not position.tp2_hit
    assert position.stop_exit_quantity == pytest.approx(position.original_quantity / 2)
    assert position.final_exit_reason == "TP1_THEN_SL"


def test_long_tp1_then_tp2_and_fee_reconciliation():
    engine, position = open_long((100, 100), (140, 99), fee=0.001, tie_policy=TiePolicy.OPTIMISTIC)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.tp2_hit
    assert position.remaining_quantity == 0
    expected = (
        position.entry_fee
        + position.tp1_exit_price * position.tp1_quantity * 0.001
        + position.tp2_exit_price * position.tp2_quantity * 0.001
    )
    assert position.fees == pytest.approx(expected)
    assert position.net_pnl == pytest.approx(position.gross_pnl - expected)


def test_pessimistic_same_candle_stop_precedes_tp1():
    engine, position = open_long((100, 100), (120, 79), tie_policy=TiePolicy.PESSIMISTIC)
    assert engine._scan_exit(position, 1)
    assert not position.tp1_hit
    assert position.final_exit_reason == "SL"


def test_optimistic_same_candle_runs_tp1_then_tp2():
    engine, position = open_long((100, 100), (140, 79), tie_policy=TiePolicy.OPTIMISTIC)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.tp2_hit
    assert position.stop_exit_time is None or pd.isna(position.stop_exit_time)


def test_partial_take_profit_does_not_move_stop_by_itself():
    engine, position = open_long((100, 100), (120, 99))
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.sl == pytest.approx(80)
    assert not position.be_triggered


def test_break_even_protection_controls_remaining_stop_after_tp1():
    profile = base_profile(break_even_enabled=True, break_even_activation_r=1, break_even_offset_r=0)
    engine, position = open_long((100, 100), (120, 99), (100, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.be_triggered
    assert position.sl == pytest.approx(100)
    assert engine._scan_exit(position, 2)
    assert position.stop_exit_price == pytest.approx(100)
    assert position.final_exit_reason == "TP1_THEN_BE"


def test_break_even_profit_offset_controls_remaining_stop_after_tp1():
    profile = base_profile(break_even_enabled=True, break_even_activation_r=1, break_even_offset_r=0.5)
    engine, position = open_long((100, 100), (120, 106), (106, 104), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.be_triggered
    assert position.sl == pytest.approx(110)
    assert engine._scan_exit(position, 2)
    assert position.stop_exit_price == pytest.approx(110)
    assert position.final_exit_reason == "TP1_THEN_BE_R_OFFSET"


def test_combined_profile_ladders_allow_sl1_then_tp1_then_tp2():
    profile = base_profile(partial_stop_enabled=True, sl1_r=0.5, sl1_close_pct=25, sl2_r=2)
    engine, position = open_long((100, 100), (100, 95), (120, 100), (140, 100), profile=profile)
    assert engine._scan_exit(position, 1)
    assert engine._scan_exit(position, 2)
    assert engine._scan_exit(position, 3)
    assert position.sl1_hit and position.tp1_hit and position.tp2_hit
    assert position.sl1_quantity + position.tp1_quantity + position.tp2_quantity == pytest.approx(position.original_quantity)
    assert position.remaining_quantity == 0


def test_combined_partial_profit_uses_break_even_as_the_only_stop_override():
    profile = base_profile(
        partial_stop_enabled=True,
        sl1_r=0.5,
        sl1_close_pct=25,
        sl2_r=2,
        break_even_enabled=True,
        break_even_activation_r=1,
        break_even_offset_r=0,
    )
    engine, position = open_long((100, 100), (120, 100), (100, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and not position.sl1_hit
    assert position.be_triggered and position.sl == pytest.approx(100)
    assert engine._scan_exit(position, 2)
    assert not position.sl1_hit
    assert position.stop_exit_price == pytest.approx(100)
    assert position.final_exit_reason == "TP1_THEN_BE"


def test_fib_fill_minute_defers_partial_tp_and_break_even_until_next_bar():
    """Exercise actual partial/BE machinery through Fib's conservative guard."""
    from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin
    from crypto_strategy_lab.trade import ExitSource

    class FibExitEngine(FibonacciRetracementMixin, BacktestEngine):
        pass

    profile = base_profile(
        break_even_enabled=True,
        break_even_activation_r=1,
        break_even_offset_r=0,
    )
    engine, pos = open_long(
        (100, 100), (120, 99), (120, 99),
        profile=profile, fee=0.0005, engine_class=FibExitEngine,
    )
    fill_time = pd.Timestamp(engine.times[1])
    pos.fib_limit_fill_time = fill_time
    pos.fib_limit_fill_price = 100.0

    # The 120 high on an OHLC fill minute might precede the limit fill.
    # Neither TP1 nor a new BE stop can be awarded on ambiguous evidence.
    engine._maybe_exit_bar(pos, 1, 120.0, 99.0, fill_time, ExitSource.INTRABAR)
    assert not pos.tp1_hit
    assert not pos.be_triggered
    assert pos.is_open

    # The same favorable price on the following execution minute is causal.
    next_time = fill_time + pd.Timedelta(minutes=1)
    engine._maybe_exit_bar(pos, 1, 120.0, 99.0, next_time, ExitSource.INTRABAR)
    assert pos.tp1_hit
    assert pos.be_triggered
    assert pos.sl == pytest.approx(100.0)
    assert pos.tp1_exit_time == next_time
    assert pos.remaining_quantity == pytest.approx(pos.original_quantity / 2)
    expected_tp1_fee = pos.tp1_exit_price * pos.tp1_quantity * 0.0005
    assert pos.tp1_fees == pytest.approx(expected_tp1_fee)


def test_fib_fill_minute_keeps_adverse_partial_stop_eligible():
    """A pending-limit fill suppresses pre-fill profit, not protective exits."""
    from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin
    from crypto_strategy_lab.trade import ExitSource

    class FibExitEngine(FibonacciRetracementMixin, BacktestEngine):
        pass

    profile = base_profile(
        partial_stop_enabled=True, sl1_r=0.5, sl1_close_pct=25, sl2_r=2,
    )
    engine, pos = open_long(
        (100, 100), (140, 89), (120, 100),
        profile=profile, fee=0.0005, engine_class=FibExitEngine,
    )
    fill_time = pd.Timestamp(engine.times[1])
    pos.fib_limit_fill_time = fill_time
    pos.fib_limit_fill_price = 100.0

    engine._maybe_exit_bar(pos, 1, 140.0, 89.0, fill_time, ExitSource.INTRABAR)
    assert pos.sl1_hit
    assert not pos.tp1_hit
    assert pos.is_open
    assert pos.sl1_quantity == pytest.approx(pos.original_quantity * 0.25)
    assert pos.remaining_quantity == pytest.approx(pos.original_quantity * 0.75)
    assert pos.sl1_exit_time == fill_time
    assert pos.sl1_fees == pytest.approx(
        pos.sl1_exit_price * pos.sl1_quantity * 0.0005
    )


def test_fib_fill_minute_combined_partials_allow_adverse_sl1_then_later_tp1():
    """A mixed partial ladder never credits pre-fill profit on the fill minute."""
    from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin
    from crypto_strategy_lab.trade import ExitSource

    class FibExitEngine(FibonacciRetracementMixin, BacktestEngine):
        pass

    profile = base_profile(
        partial_stop_enabled=True, sl1_r=0.5, sl1_close_pct=25, sl2_r=2,
    )
    engine, pos = open_long(
        (100, 100), (140, 89), (120, 100),
        profile=profile, fee=0.0005, engine_class=FibExitEngine,
    )
    fill_time = pd.Timestamp(engine.times[1])
    pos.fib_limit_fill_time = fill_time
    pos.fib_limit_fill_price = 100.0

    engine._maybe_exit_bar(pos, 1, 140.0, 89.0, fill_time, ExitSource.INTRABAR)
    assert pos.sl1_hit and not pos.tp1_hit and pos.is_open
    assert pos.sl1_exit_time == fill_time
    assert pos.remaining_quantity == pytest.approx(pos.original_quantity * 0.75)

    # The following minute is after entry, so TP1 can close its scheduled
    # fraction of the surviving position through the existing ladder.
    next_time = fill_time + pd.Timedelta(minutes=1)
    engine._maybe_exit_bar(pos, 1, 120.0, 100.0, next_time, ExitSource.INTRABAR)
    assert pos.tp1_hit
    assert pos.tp1_exit_time == next_time
    assert pos.sl1_quantity + pos.tp1_quantity + pos.remaining_quantity == pytest.approx(
        pos.original_quantity
    )
    assert pos.sl1_fees == pytest.approx(
        pos.sl1_exit_price * pos.sl1_quantity * 0.0005
    )
    assert pos.tp1_fees == pytest.approx(
        pos.tp1_exit_price * pos.tp1_quantity * 0.0005
    )


def test_fib_fill_minute_defers_trailing_activation_until_next_minute():
    """Trailing cannot activate on a possibly pre-entry favorable extreme."""
    from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin
    from crypto_strategy_lab.trade import ExitSource

    class FibExitEngine(FibonacciRetracementMixin, BacktestEngine):
        pass

    profile = base_profile(
        partial_profit_enabled=False,
        trailing_enabled=True,
        trailing_activation_r=1,
        trailing_distance_r=0.5,
    )
    engine, pos = open_long(
        (100, 100), (130, 99), (130, 99),
        profile=profile, engine_class=FibExitEngine,
    )
    fill_time = pd.Timestamp(engine.times[1])
    pos.fib_limit_fill_time = fill_time
    pos.fib_limit_fill_price = 100.0

    engine._maybe_exit_bar(pos, 1, 130.0, 99.0, fill_time, ExitSource.INTRABAR)
    assert not pos.trailing_active
    assert pos.trailing_stop is None
    assert pos.is_open

    following_time = fill_time + pd.Timedelta(minutes=1)
    engine._maybe_exit_bar(pos, 1, 130.0, 99.0, following_time, ExitSource.INTRABAR)
    assert pos.trailing_active
    assert pos.trailing_activation_time == following_time
    assert pos.trailing_stop is not None
    assert pos.is_open


def test_fib_trailing_ratchet_stop_only_exits_on_following_minute():
    """A newly ratcheted stop must not retroactively stop the same OHLC minute."""
    from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin
    from crypto_strategy_lab.trade import ExitSource, ExitReason

    class FibExitEngine(FibonacciRetracementMixin, BacktestEngine):
        pass

    profile = base_profile(
        partial_profit_enabled=False,
        trailing_enabled=True,
        trailing_activation_r=1,
        trailing_distance_r=0.5,
    )
    engine, pos = open_long(
        (100, 100), (130, 99), (130, 99), (110, 109),
        profile=profile, engine_class=FibExitEngine,
    )
    fill_time = pd.Timestamp(engine.times[1])
    pos.fib_limit_fill_time = fill_time
    pos.fib_limit_fill_price = 100.0
    engine._maybe_exit_bar(pos, 1, 130.0, 99.0, fill_time, ExitSource.INTRABAR)
    assert not pos.trailing_active

    minute_two = fill_time + pd.Timedelta(minutes=1)
    engine._maybe_exit_bar(pos, 1, 130.0, 99.0, minute_two, ExitSource.INTRABAR)
    assert pos.trailing_active and pos.is_open
    new_stop = pos.trailing_stop
    assert new_stop is not None
    assert new_stop > 100

    # The ratcheted stop becomes executable only on a subsequent minute.
    minute_three = minute_two + pd.Timedelta(minutes=1)
    engine._maybe_exit_bar(
        pos, 1, float(new_stop) + 1, float(new_stop) - 1,
        minute_three, ExitSource.INTRABAR,
    )
    assert not pos.is_open
    assert pos.exit_reason == ExitReason.TRAILING_STOP
    assert pos.exit_time == minute_three
    assert pos.exit_price == pytest.approx(new_stop)
