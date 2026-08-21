from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication

from crypto_strategy_lab.gui.data_lake_main_window import MainWindow, _parse_gui_period, strategy_warmup_period
from crypto_strategy_lab.paths import MARKET_DATA_ROOT


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


def test_data_lake_gui_does_not_expose_csv_paths_as_strategy_config() -> None:
    app()
    window = MainWindow()
    try:
        assert window.market_data_folder == MARKET_DATA_ROOT
        assert "Data Lake" in window.input_csv.text()
        assert "Data Lake" in window.intrabar_csv.text()
        values = window._data_lake_strategy_values()
        assert "input_csv" not in values
        assert "intrabar_csv" not in values
        assert "structural_regime_benchmark_csv" not in values
        config = window._build_data_lake_config()
        assert config.intrabar_csv is None
        assert config.input_csv.name.endswith("_DATA_LAKE.csv")
    finally:
        window.close()


def test_date_only_gui_end_is_next_day_exclusive() -> None:
    start, end = _parse_gui_period(
        "2026-07-01",
        "2026-07-31",
        pd.Timestamp("2020-01-01T00:00:00Z"),
        pd.Timestamp("2030-01-01T00:00:00Z"),
    )
    assert start == pd.Timestamp("2026-07-01T00:00:00Z")
    assert end == pd.Timestamp("2026-08-01T00:00:00Z")


def test_asset_return_warmup_covers_regime_lookback() -> None:
    app()
    window = MainWindow()
    try:
        window.profile_editor.regime_method.setCurrentIndex(
            window.profile_editor.regime_method.findData("ASSET_RETURN")
        )
        config = window._build_data_lake_config()
        assert strategy_warmup_period(config).days >= config.bull_regime_lookback_days
    finally:
        window.close()
