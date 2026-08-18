import pandas as pd
import pytest

from crypto_strategy_lab.config import AfterTP1StopMode, BacktestConfig, RiskMode, TiePolicy
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
        after_tp1_stop_mode=AfterTP1StopMode.KEEP_ORIGINAL_SL.value,
    )
    values.update(changes)
    return StrategyProfile(**values)


def open_long(*bars, profile=None, fee=0, tie_policy=TiePolicy.PESSIMISTIC):
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
    engine = BacktestEngine(candles(*bars), cfg)
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
    assert engine._scan_exit(position, 2)
    assert not position.tp2_hit
    assert position.stop_exit_quantity == pytest.approx(position.original_quantity / 2)
    assert position.final_exit_reason == "TP1_THEN_SL"


def test_long_tp1_then_tp2_and_fee_reconciliation():
    engine, position = open_long(
        (100, 100),
        (140, 99),
        fee=0.001,
        tie_policy=TiePolicy.OPTIMISTIC,
    )
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


@pytest.mark.parametrize(
    "mode,offset,expected",
    [
        (AfterTP1StopMode.KEEP_ORIGINAL_SL, 0, 80),
        (AfterTP1StopMode.MOVE_TO_ENTRY, 0, 100),
        (AfterTP1StopMode.MOVE_TO_R_OFFSET, 1, 110),
    ],
)
def test_after_tp1_stop_modes_are_profile_owned(mode, offset, expected):
    profile = base_profile(after_tp1_stop_mode=mode.value, after_tp1_stop_offset_r=offset)
    engine, position = open_long((100, 100), (120, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and position.is_open
    assert position.sl == pytest.approx(expected)


def test_combined_profile_ladders_allow_sl1_then_tp1_then_tp2():
    profile = base_profile(
        partial_stop_enabled=True,
        sl1_r=0.5,
        sl1_close_pct=25,
        sl2_r=2,
    )
    engine, position = open_long(
        (100, 100),
        (100, 95),
        (120, 100),
        (140, 100),
        profile=profile,
    )
    assert engine._scan_exit(position, 1)
    assert engine._scan_exit(position, 2)
    assert engine._scan_exit(position, 3)
    assert position.sl1_hit and position.tp1_hit and position.tp2_hit
    assert position.sl1_quantity + position.tp1_quantity + position.tp2_quantity == pytest.approx(position.original_quantity)
    assert position.remaining_quantity == 0


def test_combined_move_to_entry_after_tp1_overrides_pending_sl_ladder():
    profile = base_profile(
        partial_stop_enabled=True,
        sl1_r=0.5,
        sl1_close_pct=25,
        sl2_r=2,
        after_tp1_stop_mode=AfterTP1StopMode.MOVE_TO_ENTRY.value,
    )
    engine, position = open_long((100, 100), (120, 100), (100, 99), profile=profile)
    assert engine._scan_exit(position, 1)
    assert position.tp1_hit and not position.sl1_hit
    assert engine._scan_exit(position, 2)
    assert position.stop_exit_price == pytest.approx(100)
    assert position.stop_exit_quantity == pytest.approx(position.original_quantity / 2)
