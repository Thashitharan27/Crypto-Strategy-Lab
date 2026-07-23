from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atr import atr
from config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from engine import BacktestEngine
from loader import load_ohlcv_csv
from statistics import equity_curve, summarize


def candles(rows):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=15*i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        "volume": [1]*len(rows),
    })


def cfg(**kw):
    base = dict(risk_mode=RiskMode.FIXED, fixed_r=10, initial_equity=1000, risk_per_leg=0.01,
                sl_mult=1, tp_mult=1, taker_fee=0, maker_fee=0, slippage=0,
                entry_mode=EntryMode.WAIT_UNTIL_CLOSED)
    base.update(kw)
    return BacktestConfig(**base)


def test_loading_binance_open_time_ms_extra_columns_gap(capsys, tmp_path):
    path = tmp_path / "b.csv"
    path.write_text("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
                    "1704067200000,1,2,0.5,1.5,10,x,x,x,x,x,x\n"
                    "1704067200000,1,2,0.5,1.5,10,x,x,x,x,x,x\n"
                    "1704069000000,2,3,1,2.5,11,x,x,x,x,x,x\n")
    df = load_ohlcv_csv(str(path), "ms")
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.loc[0, "timestamp"] == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert "missing_15m_candles=1" in capsys.readouterr().out


def test_wilder_atr():
    high = np.array([10, 12, 13, 14, 15.], float)
    low = np.array([9, 10, 11, 12, 13.], float)
    close = np.array([9.5, 11, 12, 13, 14.], float)
    out = atr(high, low, close, 3)
    # TR: 1, 2.5, 2, 2, 2 -> first ATR mean first 3 = 1.8333; next = ((prev*2)+2)/3
    assert np.isnan(out[1])
    assert out[2] == pytest.approx(11/6)
    assert out[3] == pytest.approx(((11/6)*2+2)/3)


def test_position_sizing_fees_and_net_r():
    df = candles([(100,101,99,100), (100,111,89,100)])
    trades = BacktestEngine(df, cfg(taker_fee=0.001, tie_policy=TiePolicy.OPTIMISTIC)).run()
    row = trades.iloc[0]
    assert row.long_quantity == pytest.approx(1)  # 1000*1% / (1*10)
    assert row.long_risk_amount == pytest.approx(10)
    assert row.long_entry_notional == pytest.approx(100)
    assert row.long_fees == pytest.approx(0.21)  # entry 100 + exit 110 notionals at 0.1%
    assert row.long_net_r == pytest.approx((10 - 0.21) / 10)
    assert row.pair_net_r < row.pair_gross_r


def test_long_tp_short_sl_and_long_sl_short_tp():
    up = BacktestEngine(candles([(100,100,100,100), (100,111,100,100)]), cfg()).run().iloc[0]
    assert up.long_exit_reason == "TP" and up.short_exit_reason == "SL"
    down = BacktestEngine(candles([(100,100,100,100), (100,100,89,100)]), cfg()).run().iloc[0]
    assert down.long_exit_reason == "SL" and down.short_exit_reason == "TP"


def test_same_candle_pessimistic_and_optimistic():
    data = candles([(100,100,100,100), (100,111,89,100)])
    pess = BacktestEngine(data, cfg(tie_policy=TiePolicy.PESSIMISTIC)).run().iloc[0]
    opt = BacktestEngine(data, cfg(tie_policy=TiePolicy.OPTIMISTIC)).run().iloc[0]
    assert pess.ambiguous_candle and opt.ambiguous_candle
    assert pess.long_exit_reason == "SL" and pess.short_exit_reason == "SL"
    assert opt.long_exit_reason == "TP" and opt.short_exit_reason == "TP"


def test_end_of_data_closure_no_lookahead():
    # Entry candle hits both levels, but same candle must not close the trade.
    df = candles([(100,111,89,100)])
    row = BacktestEngine(df, cfg()).run().iloc[0]
    assert row.long_exit_reason == "END_OF_DATA"
    assert row.short_exit_reason == "END_OF_DATA"
    assert row.holding_bars == 0


def test_equity_and_drawdown():
    data = candles([(100,100,100,100), (100,111,100,100), (100,100,89,100)])
    trades = BacktestEngine(data, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=10)).run()
    summary = summarize(trades, 1000)
    curve = equity_curve(trades, 1000)
    assert summary["ending_equity"] == pytest.approx(trades.equity_after_trade.iloc[-1])
    assert "maximum_drawdown" in summary
    assert not curve.empty

def one_minute(start, rows):
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": [1]*len(rows),
    })

def test_strategy_entry_time_is_candle_close_and_uses_close_price_not_high_low():
    df = candles([(100, 1000, 1, 100), (100, 111, 89, 100)])
    row = BacktestEngine(df, cfg()).run().iloc[0]
    assert row.strategy_candle_open_time == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert row.strategy_entry_time == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert row.strategy_entry_price == 100
    assert row.long_exit_reason == "SL"


def test_atr_uses_strategy_candles_not_intrabar_volatility():
    rows = [(100+i, 102+i, 99+i, 101+i) for i in range(20)]
    strat = candles(rows)
    start = pd.Timestamp("2024-01-01 00:15", tz="UTC")
    quiet = one_minute(start, [(100,100,100,100)]*60)
    wild = one_minute(start, [(100,10000,1,100)]*60)
    c = cfg(risk_mode=RiskMode.ATR, atr_period=14, entry_mode=EntryMode.EVERY_N_CANDLES, use_intrabar_data=True)
    a = BacktestEngine(strat, c, quiet).run().atr_at_entry.iloc[0]
    b = BacktestEngine(strat, c, wild).run().atr_at_entry.iloc[0]
    assert a == pytest.approx(b)
    assert a == pytest.approx(atr(strat.high.to_numpy(float), strat.low.to_numpy(float), strat.close.to_numpy(float), 14)[13])


def test_intrabar_resolves_each_side_and_sources():
    strat = candles([(100,100,100,100), (100,100,100,100)])
    intra = one_minute(pd.Timestamp("2024-01-01 00:16", tz="UTC"), [(100,111,100,100)])
    row = BacktestEngine(strat, cfg(use_intrabar_data=True), intra).run().iloc[0]
    assert row.long_exit_reason == "TP"
    assert row.short_exit_reason == "SL"
    assert row.long_exit_source == "1M_INTRABAR"
    assert row.long_exit_time == pd.Timestamp("2024-01-01 00:16", tz="UTC")


def test_leverage_caps_and_full_notional_fees():
    df = candles([(100,100,100,100), (100,111,100,100)])
    row = BacktestEngine(df, cfg(taker_fee=0.001, max_effective_leverage_per_leg=0.05)).run().iloc[0]
    assert row.leverage_capped
    assert row.long_quantity < row.long_uncapped_quantity
    assert row.long_effective_leverage == pytest.approx(0.05)
    assert row.long_entry_fee == pytest.approx(row.long_entry_notional * 0.001)


def test_warmup_candles_do_not_trade_before_start():
    df = candles([(100,100,100,100)]*20 + [(100,111,100,100)])
    c = cfg(trading_start_date="2024-01-01 04:00", risk_mode=RiskMode.ATR, atr_period=14)
    engine = BacktestEngine(df, c)
    trades = engine.run()
    assert engine.warmup_candle_count == 16
    assert (trades.strategy_entry_time >= pd.Timestamp("2024-01-01 04:00", tz="UTC")).all()


def test_missing_intrabar_fallback_policy_records_flag():
    strat = candles([(100,100,100,100), (100,111,100,100)])
    intra = one_minute(pd.Timestamp("2024-01-01 00:16", tz="UTC"), [(100,100,100,100), (100,100,100,100), (100,100,100,100)])
    intra.loc[2, "timestamp"] = pd.Timestamp("2024-01-01 00:20", tz="UTC")
    row = BacktestEngine(strat, cfg(use_intrabar_data=True), intra).run().iloc[0]
    assert row.missing_intrabar_data
    assert row.long_exit_source == "15M_FALLBACK"

def test_matching_intrabar_candles_record_intrabar_exit_source():
    strat = candles([(100,100,100,100), (100,100,100,100), (100,100,100,100)])
    start = pd.Timestamp("2024-01-01 00:15", tz="UTC")
    rows = [(100,100,100,100)] * 15 + [(100,111,100,100)]
    intra = one_minute(start, rows)
    row = BacktestEngine(strat, cfg(use_intrabar_data=True), intra).run().iloc[0]
    assert row.long_exit_source == "1M_INTRABAR"
    assert row.long_fallback_reason is None
    assert row.long_exit_time == pd.Timestamp("2024-01-01 00:30", tz="UTC")


def test_summary_counts_intrabar_fallback_and_end_of_data_sources():
    strat = candles([(100,100,100,100), (100,111,100,100), (100,100,100,100)])
    intra = one_minute(pd.Timestamp("2024-01-01 00:15", tz="UTC"), [(100,111,100,100)] * 30)
    trades = BacktestEngine(strat, cfg(use_intrabar_data=True), intra).run()
    summary = summarize(trades, 1000)
    assert summary["exit_source_counts"]["1M_INTRABAR"] >= 1
    assert "fallback_reason_counts" in summary


def test_plot_frequency_aliases_fall_back_for_older_pandas(monkeypatch):
    import plots

    returns = pd.DataFrame({
        "exit_time": [pd.Timestamp("2024-01-31")],
        "pair_net_pnl": [100.0],
    })
    original_resample = pd.Series.resample

    def legacy_resample(self, rule, *args, **kwargs):
        if rule in {"ME", "YE"}:
            raise ValueError(f"Invalid frequency: {rule}")
        if rule in {"M", "Y"}:
            return object()
        return original_resample(self, rule, *args, **kwargs)

    monkeypatch.setattr(pd.Series, "resample", legacy_resample)

    assert plots._month_year_frequencies(returns) == ("M", "Y")


def test_save_plots_reports_failed_chart_without_raising(monkeypatch, tmp_path):
    import plots

    trades = pd.DataFrame({
        "pair_net_r": [1.0],
        "holding_hours": [2.0],
        "long_exit_time": [pd.Timestamp("2024-01-31")],
        "short_exit_time": [pd.Timestamp("2024-01-31")],
        "pair_net_pnl": [100.0],
    })
    equity = pd.DataFrame({
        "time": [pd.Timestamp("2024-01-31")],
        "equity": [1100.0],
        "drawdown": [0.0],
    })

    original_call = pd.plotting._core.PlotAccessor.__call__

    def fail_drawdown_accessor(self, *args, **kwargs):
        if kwargs.get("y") == "drawdown":
            raise RuntimeError("drawdown boom")
        return original_call(self, *args, **kwargs)

    monkeypatch.setattr(pd.plotting._core.PlotAccessor, "__call__", fail_drawdown_accessor)

    warnings = plots.save_plots(trades, equity, tmp_path)

    assert any("drawdown.png" in warning and "drawdown boom" in warning for warning in warnings)
    assert (tmp_path / "equity_curve.png").exists()
    assert (tmp_path / "r_distribution.png").exists()


def test_price_risk_leg_loses_more_than_configured_after_fees_and_slippage():
    df = candles([(100,100,100,100), (100,100,89,100)])
    row = BacktestEngine(df, cfg(risk_per_leg=0.005, taker_fee=0.001, slippage=0.001)).run().iloc[0]
    assert row.long_exit_reason == "SL"
    assert row.long_net_pnl / row.equity_before_trade < -0.005
    assert row.long_estimated_all_in_stop_risk_percentage > row.long_configured_price_risk_percentage


def test_all_in_risk_sizing_keeps_stop_loss_near_configured_risk():
    from config import PositionSizingMode

    df = candles([(100,100,100,100), (100,100,89,100)])
    row = BacktestEngine(df, cfg(risk_per_leg=0.005, taker_fee=0.001, slippage=0.001, position_sizing_mode=PositionSizingMode.ALL_IN_STOP_RISK)).run().iloc[0]
    assert row.long_exit_reason == "SL"
    assert -row.long_net_pnl / row.equity_before_trade == pytest.approx(0.005, rel=0.01)
    assert row.long_estimated_all_in_stop_risk_percentage == pytest.approx(0.005, rel=0.01)


def test_end_of_data_uses_final_candle_close_timestamp():
    start = pd.Timestamp("2024-01-01 23:30", tz="UTC")
    df = pd.DataFrame({
        "timestamp": [start, start + pd.Timedelta(minutes=15)],
        "open": [100, 100], "high": [100, 100], "low": [100, 100], "close": [100, 100], "volume": [1, 1],
    })
    row = BacktestEngine(df, cfg()).run().iloc[0]
    assert row.long_exit_reason == "END_OF_DATA"
    assert row.long_exit_time == pd.Timestamp("2024-01-02 00:00", tz="UTC")
    assert row.short_exit_time == pd.Timestamp("2024-01-02 00:00", tz="UTC")


def test_equity_reconciliation_is_exact_sum_of_pair_pnl():
    trades = BacktestEngine(candles([(100,100,100,100), (100,111,100,100), (100,100,89,100)]), cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=10, taker_fee=0.001, slippage=0.001)).run()
    expected = 1000 + trades.pair_net_pnl.sum()
    assert trades.equity_after_trade.iloc[-1] == pytest.approx(expected, abs=1e-12)

def timeout_minutes(rows, start="2024-01-01 00:15"):
    t0 = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame({
        "timestamp": [t0 + pd.Timedelta(minutes=i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        "volume": [1] * len(rows),
    })


def test_both_open_timeout_closes_both_legs_at_one_minute_open_with_costs():
    strat = candles([(100, 100, 100, 100), (100, 105, 95, 100), (100, 105, 95, 100), (100, 105, 95, 100)])
    intra = timeout_minutes([(100, 101, 99, 100)] * 30 + [(102, 999, 1, 102)] + [(100, 101, 99, 100)] * 14)
    row = BacktestEngine(strat, cfg(use_intrabar_data=True, enable_both_open_timeout=True, max_both_open_minutes=30, taker_fee=0.001, slippage=0.01), intra).run().iloc[0]
    assert row.long_exit_reason == row.short_exit_reason == "BOTH_OPEN_TIMEOUT"
    assert row.long_exit_source == row.short_exit_source == "1M_INTRABAR"
    assert row.both_open_timeout_triggered == True
    assert row.timeout_exit_time == pd.Timestamp("2024-01-01 00:45", tz="UTC")
    assert row.timeout_minutes == 30
    assert row.long_exit_price == pytest.approx(102 * 0.99)
    assert row.short_exit_price == pytest.approx(102 * 1.01)
    assert row.long_exit_fee == pytest.approx(row.long_exit_price * row.long_quantity * 0.001)


def test_timeout_waits_for_duration_and_ignores_pairs_after_one_leg_closed():
    no_timeout = BacktestEngine(candles([(100, 100, 100, 100), (100, 105, 95, 100)]), cfg(enable_both_open_timeout=True, max_both_open_minutes=30)).run().iloc[0]
    assert no_timeout.long_exit_reason == "END_OF_DATA"
    one_leg_closed = BacktestEngine(candles([(100, 100, 100, 100), (100, 111, 100, 100), (100, 105, 95, 100), (100, 105, 95, 100)]), cfg(enable_both_open_timeout=True, max_both_open_minutes=30)).run().iloc[0]
    assert one_leg_closed.long_exit_reason == "TP"
    assert one_leg_closed.short_exit_reason != "BOTH_OPEN_TIMEOUT"


def test_timeout_replacement_entry_waits_for_next_completed_strategy_candle_and_recalculates_atr_size():
    strat = candles([(100,100,100,100),(100,105,95,100),(100,105,95,100),(130,140,120,130),(130,140,120,130),(130,200,50,130)])
    intra = timeout_minutes([(100,101,99,100)] * 60)
    trades = BacktestEngine(strat, cfg(use_intrabar_data=True, enable_both_open_timeout=True, max_both_open_minutes=30, entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=1, risk_mode=RiskMode.PERCENT, percent_r=0.1), intra).run()
    assert len(trades) >= 2
    assert trades.iloc[0].timeout_exit_time == pd.Timestamp("2024-01-01 00:45", tz="UTC")
    assert trades.iloc[1].entry_time > trades.iloc[0].timeout_exit_time
    assert trades.iloc[1].strategy_entry_price == pytest.approx(130)
    assert trades.iloc[1].r_distance == pytest.approx(13)
    assert trades.iloc[1].long_quantity != pytest.approx(trades.iloc[0].long_quantity)


def test_disabled_timeout_preserves_existing_results_and_summary_records_timeout():
    data = candles([(100,100,100,100),(100,105,95,100),(100,105,95,100),(100,105,95,100)])
    baseline = BacktestEngine(data, cfg()).run()
    disabled = BacktestEngine(data, cfg(enable_both_open_timeout=False)).run()
    pd.testing.assert_frame_equal(baseline, disabled)
    timed = BacktestEngine(data, cfg(enable_both_open_timeout=True, max_both_open_minutes=30)).run()
    summary = summarize(timed, 1000)
    assert summary["pairs_closed_by_both_open_timeout"] == 1
    assert "Long BOTH_OPEN_TIMEOUT / Short BOTH_OPEN_TIMEOUT" in summary["exit_combinations"]


def test_be_after_long_sl_moves_short_to_executed_entry_and_records_be_exit():
    strat = candles([(100, 100, 100, 100), (100, 100, 89, 100), (100, 91, 80, 100)])
    row = BacktestEngine(strat, cfg(enable_be_after_opposite_sl=True)).run().iloc[0]
    assert row.long_exit_reason == "SL"
    assert row.short_be_triggered
    assert row.short_current_sl == pytest.approx(row.short_entry_price)
    assert row.short_exit_reason == "BE"
    assert row.pair_be_triggered


def test_be_after_short_sl_moves_long_to_executed_entry_and_tp_unchanged():
    strat = candles([(100, 100, 100, 100), (100, 111, 100, 100), (100, 120, 99, 100)])
    row = BacktestEngine(strat, cfg(enable_be_after_opposite_sl=True, tp_mult=2)).run().iloc[0]
    assert row.short_exit_reason == "SL"
    assert row.long_be_triggered
    assert row.long_current_sl == pytest.approx(row.long_entry_price)
    assert row.long_tp == pytest.approx(120)
    assert row.long_exit_reason == "BE"


def test_first_leg_tp_and_timeout_do_not_trigger_be():
    tp_first = BacktestEngine(candles([(100,100,100,100), (100,111,100,100)]), cfg(enable_be_after_opposite_sl=True)).run().iloc[0]
    assert tp_first.long_exit_reason == "TP"
    assert not tp_first.short_be_triggered
    timeout = BacktestEngine(candles([(100,100,100,100), (100,105,95,100), (100,105,95,100), (100,105,95,100)]), cfg(enable_be_after_opposite_sl=True, enable_both_open_timeout=True, max_both_open_minutes=30)).run().iloc[0]
    assert timeout.long_exit_reason == timeout.short_exit_reason == "BOTH_OPEN_TIMEOUT"
    assert not timeout.pair_be_triggered


def test_entry_price_be_uses_slippage_adjusted_entry_and_r_offset():
    data = candles([(100,100,100,100), (100,100,88,100), (100,91,80,100)])
    entry = BacktestEngine(data, cfg(enable_be_after_opposite_sl=True, slippage=0.01)).run().iloc[0]
    assert entry.short_entry_price == pytest.approx(99)
    assert entry.short_current_sl == pytest.approx(99)
    offset = BacktestEngine(data, cfg(enable_be_after_opposite_sl=True, be_mode="R_OFFSET", be_offset_r=0.25)).run().iloc[0]
    assert offset.short_current_sl == pytest.approx(100 - 0.25 * 10)
    assert offset.short_exit_reason == "BE_R_OFFSET"


def test_cost_adjusted_be_offsets_fees_approximately_and_summary_records_outcomes():
    data = candles([(100,100,100,100), (100,100.2,89,100)])
    trades = BacktestEngine(data, cfg(enable_be_after_opposite_sl=True, be_mode="COST_ADJUSTED", taker_fee=0.001)).run()
    row = trades.iloc[0]
    assert row.short_exit_reason == "BE_COST_ADJUSTED"
    assert row.short_net_pnl == pytest.approx(0, abs=1e-9)
    summary = summarize(trades, 1000)
    assert summary["pairs_where_be_was_triggered"] == 1
    assert summary["remaining_legs_stopped_at_be"] == 1
    assert summary["double_sl_count_prevented"] == 1
    assert "Long SL / Short BE_COST_ADJUSTED" in summary["exit_combinations"]


def test_be_same_candle_next_candle_vs_pessimistic_policy():
    strat = candles([(100,100,100,100), (100,100,100,100), (100,100,100,100)])
    intra = one_minute(pd.Timestamp("2024-01-01 00:15", tz="UTC"), [(100,100,100,100), (100,111,89,100), (100,101,89,100)])
    nxt = BacktestEngine(strat, cfg(use_intrabar_data=True, enable_be_after_opposite_sl=True, tie_policy=TiePolicy.PESSIMISTIC), intra).run().iloc[0]
    pess = BacktestEngine(strat, cfg(use_intrabar_data=True, enable_be_after_opposite_sl=True, tie_policy=TiePolicy.PESSIMISTIC, be_same_candle_policy="PESSIMISTIC"), intra).run().iloc[0]
    assert nxt.short_exit_time == pd.Timestamp("2024-01-01 00:17", tz="UTC")
    assert not nxt.short_be_same_candle_ambiguous
    assert pess.short_exit_time == pd.Timestamp("2024-01-01 00:16", tz="UTC")
    assert pess.short_be_same_candle_ambiguous


def test_adx_matches_tradingview_reference_values():
    from adx import adx
    rows = [(100+i, 102+i+(i%3), 99+i-(i%2), 101+i+((i%4)-1)*0.3) for i in range(40)]
    df = candles(rows)
    out, plus, minus = adx(df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float), 14)
    assert out[-1] == pytest.approx(100.0, abs=1e-5)
    assert plus[-1] == pytest.approx(28.365647, abs=1e-5)
    assert minus[-1] == pytest.approx(0.0, abs=1e-5)


def test_adx_uses_strategy_candles_not_intrabar_volatility():
    rows = [(100+i, 102+i+(i%3), 99+i-(i%2), 101+i) for i in range(40)]
    strat = candles(rows)
    quiet = one_minute(pd.Timestamp("2024-01-01 00:15", tz="UTC"), [(100,100,100,100)]*600)
    wild = one_minute(pd.Timestamp("2024-01-01 00:15", tz="UTC"), [(100,10000,1,100)]*600)
    c = cfg(entry_mode=EntryMode.EVERY_N_CANDLES, use_intrabar_data=True, adx_period=14)
    a = BacktestEngine(strat, c, quiet).run().adx.iloc[0]
    b = BacktestEngine(strat, c, wild).run().adx.iloc[0]
    assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b)


def test_disabled_adx_filter_matches_unfiltered_engine():
    df = candles([(100,100,100,100), (100,111,100,100), (100,100,89,100), (100,111,100,100)])
    base = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=10)).run()
    disabled = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=10, enable_adx_filter=True, adx_filter_mode="Disabled")).run()
    pd.testing.assert_frame_equal(base.drop(columns=["signals_evaluated", "signals_skipped_by_adx", "signals_traded"], errors="ignore"), disabled.drop(columns=["signals_evaluated", "signals_skipped_by_adx", "signals_traded"], errors="ignore"))


def test_adx_filter_skips_entries_records_signals_and_outputs_stats():
    df = candles([(100+i, 102+i+(i%3), 99+i-(i%2), 101+i) for i in range(45)])
    unfiltered = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50)).run()
    engine = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50, enable_adx_filter=True, adx_filter_mode="ADX <= Maximum", adx_maximum=101))
    filtered = engine.run()
    assert len(filtered) < len(unfiltered)
    assert len(engine.skipped_signals) > 0
    assert {"adx", "plus_di", "minus_di", "adx_filter_passed", "adx_filter_reason"}.issubset(filtered.columns)
    summary = summarize(filtered, 1000)
    assert "signals_evaluated" in summary and "average_adx_of_winning_trades" in summary
    from statistics import adx_analysis
    analysis = adx_analysis(filtered)
    assert list(analysis.columns) == ["Bucket", "Trades", "Wins", "Losses", "Win rate", "Average PnL", "Average duration", "Double SL count", "TP/SL count"]


def test_bollinger_width_matches_manual_population_std_and_csv_columns():
    df = candles([(100+i, 100+i, 100+i, 100+i) for i in range(25)])
    trades = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50)).run()
    row = trades[trades["bb_width"].notna()].iloc[0]
    closes = np.array([100+i for i in range(20)], float)
    sma = closes.mean(); std = closes.std(ddof=0)
    assert row.bb_middle == pytest.approx(sma)
    assert row.bb_upper == pytest.approx(sma + 2*std)
    assert row.bb_lower == pytest.approx(sma - 2*std)
    assert row.bb_width == pytest.approx((4*std)/sma)
    assert row.bb_width_pct == pytest.approx(row.bb_width * 100)
    assert {"bb_width_change", "bb_width_change_pct", "di_spread", "di_ratio", "di_spread_change"}.issubset(trades.columns)


def test_di_spread_and_ratio_match_manual_calculation():
    df = candles([(100+i, 102+i+(i%3), 99+i-(i%2), 101+i) for i in range(45)])
    row = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50)).run().dropna(subset=["plus_di", "minus_di"]).iloc[-1]
    assert row.di_spread == pytest.approx(abs(row.plus_di - row.minus_di))
    expected_ratio = max(row.plus_di, row.minus_di) / min(row.plus_di, row.minus_di) if min(row.plus_di, row.minus_di) else np.nan
    if np.isfinite(expected_ratio):
        assert row.di_ratio == pytest.approx(expected_ratio)


def test_market_compression_filters_skip_trades_and_disabled_matches():
    df = candles([(100+i, 102+i+(i%3), 99+i-(i%2), 101+i) for i in range(45)])
    base = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50)).run()
    disabled = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50, enable_bb_width_filter=True, bb_width_filter_mode="Disabled", enable_di_spread_filter=True, di_spread_filter_mode="Disabled")).run()
    pd.testing.assert_frame_equal(base.drop(columns=["signals_evaluated", "signals_skipped_by_adx", "signals_traded"], errors="ignore"), disabled.drop(columns=["signals_evaluated", "signals_skipped_by_adx", "signals_traded"], errors="ignore"))
    filtered_engine = BacktestEngine(df, cfg(entry_mode=EntryMode.EVERY_N_CANDLES, max_active_pairs=50, enable_bb_width_filter=True, bb_width_filter_mode="Maximum Width", bb_width_maximum=0.0001, enable_di_spread_filter=True, di_spread_filter_mode="Maximum Spread", di_spread_maximum=0.1))
    filtered = filtered_engine.run()
    assert len(filtered) < len(base)
    assert filtered_engine.skipped_signals
