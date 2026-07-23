from datetime import datetime
from pathlib import Path

import pandas as pd

from config import BacktestConfig
from output_manager import periodic_results, run_folder_name


def test_run_folder_name_uses_required_parts_and_run_name():
    cfg = BacktestConfig(strategy_csv=Path("data/BTCUSDT_15m.csv"), run_name="My Run", atr_period=14, sl_mult=2, tp_mult=3)
    name = run_folder_name(cfg, datetime(2026, 7, 23, 12, 34, 56))
    assert name == "My_Run_BTC_15m_ATR14_SL2_TP3_2026-07-23_12-34-56"


def test_periodic_results_groups_by_exit_period():
    trades = pd.DataFrame({
        "long_exit_time": ["2024-01-01", "2024-01-20", "2024-02-01"],
        "short_exit_time": ["2024-01-02", "2024-01-21", "2024-02-02"],
        "pair_net_pnl": [10.0, -2.0, 5.0],
        "pair_net_r": [1.0, -0.2, 0.5],
    })
    monthly = periodic_results(trades, "ME")
    assert list(monthly["pair_count"]) == [2, 1]
    assert list(monthly["net_pnl"]) == [8.0, 5.0]
