import os
import sys

import pytest

from config import BacktestConfig
from gui.config_logic import load_config_json, save_config_json

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication

from gui.main_window import MainWindow


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


def test_gui_default_atr_period_matches_backtest_config():
    app()
    window = MainWindow()
    try:
        assert window.atr_period.value() == BacktestConfig().atr_period == 14
        window.atr_period.setValue(7)
        window.reset_defaults()
        assert window.atr_period.value() == BacktestConfig().atr_period == 14
    finally:
        window.close()


def test_saved_and_loaded_gui_config_preserves_atr_period(tmp_path):
    path = tmp_path / "backtest_config.json"
    save_config_json(path, {"atr_period": 21})

    app()
    window = MainWindow()
    try:
        window.apply_values(load_config_json(path))
        assert window.atr_period.value() == 21
        assert window.values()["atr_period"] == 21
    finally:
        window.close()


def test_gui_reset_restores_all_default_values_and_run_name():
    from gui.config_logic import default_gui_config, format_percentage

    app()
    window = MainWindow()
    defaults = default_gui_config()
    try:
        window.apply_values({
            "run_name": "custom",
            "atr_period": 7,
            "atr_multiplier": 2.5,
            "sl_mult": 9,
            "tp_mult": 10,
            "initial_equity": 555,
            "risk_per_leg": 0.123,
            "maker_fee": 0.1,
            "taker_fee": 0.2,
            "slippage": 0.3,
            "strategy_timeframe_minutes": 99,
            "intrabar_timeframe_minutes": 3,
            "use_intrabar_data": False,
        })
        assert window.values()["run_name"] == "custom"

        window.reset_defaults()
        values = window.values()

        for key in [
            "run_name", "input_csv", "strategy_csv", "intrabar_csv", "use_intrabar_data",
            "output_dir", "sl_mult", "tp_mult", "entry_mode", "entry_interval",
            "max_active_pairs", "tie_policy", "risk_mode", "atr_period", "atr_multiplier",
            "trading_start_date", "trading_end_date", "max_effective_leverage_per_leg",
            "max_combined_effective_leverage", "intrabar_missing_policy", "zero_cost_comparison",
            "percent_r", "fixed_r", "initial_equity", "risk_per_leg", "maker_fee",
            "taker_fee", "use_maker_entry", "use_maker_exit", "slippage",
        ]:
            assert values[key] == defaults[key]

        assert window.atr_period.value() == 14
        assert window.atr_mult.value() == 1.0
        assert window.sl.value() == 2.0
        assert window.tp.value() == 3.0
        assert window.equity.value() == 1000
        assert window.risk_leg.text() == format_percentage(0.005)
        assert window.maker.text() == format_percentage(0.0002)
        assert window.taker.text() == format_percentage(0.0005)
        assert window.slippage.text() == format_percentage(0.0001)
        assert values["use_intrabar_data"] is True
    finally:
        window.close()
