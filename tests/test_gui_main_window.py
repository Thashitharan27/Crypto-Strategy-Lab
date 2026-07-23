import os
import sys

import pytest

from config import BacktestConfig
from gui.config_logic import load_config_json, save_config_json

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

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
