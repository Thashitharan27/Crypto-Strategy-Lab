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


def test_summary_formats_percentage_points_without_multiplying_twice() -> None:
    app()
    window = MainWindow()
    try:
        summary = {
            "ending_equity": 919.16,
            "total_return_percentage": -8.0842,
            "total_trades": 18,
            "win_rate": 5 / 18,
            "profit_factor": 0.35,
            "maximum_drawdown_percentage": -8.762,
            "average_net_r": -0.46,
            "total_net_r": -8.34,
            "total_fees": 7.75,
            "signals_traded": 18,
            "signals_evaluated": 18,
        }
        window.populate_summary(summary)
        assert window.kpi_labels["Total Return"].text() == "-8.08%"
        assert window.kpi_labels["Maximum Drawdown"].text() == "-8.76%"
        assert window.kpi_labels["Win Rate"].text() == "27.78%"
    finally:
        window.close()
