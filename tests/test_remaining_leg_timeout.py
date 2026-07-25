import pandas as pd
import pytest

from config import BacktestConfig, EntryMode, RiskMode
from engine import BacktestEngine
from statistics import summarize


def strategy(rows):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=15*i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1,
    })


def intrabar(rows, start="2024-01-01 00:15"):
    start = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1,
    })


def config(**overrides):
    values = dict(risk_mode=RiskMode.FIXED, fixed_r=10, atr_period=1,
                  initial_equity=1000, risk_per_leg=.01, sl_mult=1, tp_mult=5,
                  maker_fee=0, taker_fee=0, slippage=0,
                  entry_mode=EntryMode.WAIT_UNTIL_CLOSED, use_intrabar_data=True,
                  enable_remaining_leg_timeout_after_first_sl=True,
                  remaining_leg_timeout_after_first_sl_minutes=5)
    values.update(overrides)
    return BacktestConfig(**values)


def quiet_strategy():
    return strategy([(100, 100, 100, 100)] * 3)


def test_intrabar_long_sl_starts_exact_timer_and_times_out_short_at_deadline_open():
    rows = [(100, 100, 100, 100), (100, 100, 89, 100)] + [(100, 101, 99, 100)] * 4 + [(97, 98, 96, 97)] + [(97, 98, 96, 97)] * 23
    row = BacktestEngine(quiet_strategy(), config(slippage=.01, taker_fee=.001), intrabar(rows)).run().iloc[0]
    assert row.long_exit_reason == "SL"
    assert row.short_exit_reason == "REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"
    assert row.first_sl_side == "LONG"
    assert row.first_sl_time == pd.Timestamp("2024-01-01 00:16", tz="UTC")
    assert row.remaining_leg_timeout_deadline == pd.Timestamp("2024-01-01 00:21", tz="UTC")
    assert row.remaining_leg_timeout_exit_time == row.remaining_leg_timeout_deadline
    assert row.short_exit_price == pytest.approx(97 * 1.01)
    assert row.short_exit_fee == pytest.approx(row.short_exit_price * row.short_quantity * .001)
    assert row.remaining_leg_timeout_exit_side == "SHORT"


def test_intrabar_short_sl_times_out_long_with_directional_costs():
    rows = [(100, 100, 100, 100), (100, 111, 100, 100)] + [(100, 101, 99, 100)] * 4 + [(103, 104, 102, 103)] + [(103, 104, 102, 103)] * 23
    row = BacktestEngine(quiet_strategy(), config(slippage=.01, taker_fee=.001), intrabar(rows)).run().iloc[0]
    assert row.short_exit_reason == "SL"
    assert row.long_exit_reason == "REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"
    assert row.first_sl_side == "SHORT"
    assert row.long_exit_price == pytest.approx(103 * .99)
    assert row.long_exit_fee == pytest.approx(row.long_exit_price * row.long_quantity * .001)


def test_natural_tp_before_deadline_is_preserved_and_timeout_not_triggered():
    rows = [(100, 100, 100, 100), (100, 100, 89, 100), (100, 101, 49, 50)] + [(50, 51, 49, 50)] * 27
    row = BacktestEngine(quiet_strategy(), config(), intrabar(rows)).run().iloc[0]
    assert row.short_exit_reason == "TP"
    assert row.remaining_leg_timeout_after_first_sl_started
    assert not row.remaining_leg_timeout_triggered
    assert summarize(pd.DataFrame([row]))["remaining_legs_reaching_tp_before_timeout"] == 1


def test_strategy_candle_fallback_uses_first_open_at_or_after_deadline():
    data = strategy([(100,100,100,100), (100,100,89,100), (96,101,95,96), (95,100,94,95)])
    row = BacktestEngine(data, config(use_intrabar_data=False, remaining_leg_timeout_after_first_sl_minutes=5)).run().iloc[0]
    assert row.first_sl_time == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert row.remaining_leg_timeout_deadline == pd.Timestamp("2024-01-01 00:20", tz="UTC")
    assert row.remaining_leg_timeout_exit_time == pd.Timestamp("2024-01-01 00:30", tz="UTC")
    assert row.short_exit_price == 96
    assert row.short_exit_source == "15M_FALLBACK"
    assert row.short_fallback_reason == "remaining_leg_timeout_intrabar_unavailable"


def test_disabled_and_end_of_data_behavior_and_summary_audit():
    data = strategy([(100,100,100,100), (100,100,89,100)])
    disabled = BacktestEngine(data, config(use_intrabar_data=False, enable_remaining_leg_timeout_after_first_sl=False)).run().iloc[0]
    enabled = BacktestEngine(data, config(use_intrabar_data=False, remaining_leg_timeout_after_first_sl_minutes=60)).run().iloc[0]
    assert disabled.short_exit_reason == enabled.short_exit_reason == "END_OF_DATA"
    assert not disabled.remaining_leg_timeout_after_first_sl_started
    assert enabled.remaining_leg_timeout_after_first_sl_started
    assert not enabled.remaining_leg_timeout_triggered
    stats = summarize(pd.DataFrame([enabled]))
    assert stats["pairs_where_remaining_leg_timeout_started"] == 1
    assert stats["pairs_closed_by_remaining_leg_timeout"] == 0
    assert stats["total_pnl_of_remaining_leg_timeout_pairs"] == pytest.approx(enabled.pair_net_pnl)


def test_enabled_duration_must_be_positive():
    with pytest.raises(ValueError, match="remaining_leg_timeout_after_first_sl_minutes"):
        config(remaining_leg_timeout_after_first_sl_minutes=0)
