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
