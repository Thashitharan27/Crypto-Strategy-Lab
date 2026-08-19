import os
import sys

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.enhanced_engine import EnhancedBacktestEngine
from crypto_strategy_lab.gui.enhanced_config import (
    build_enhanced_backtest_config,
    enhanced_default_gui_config,
)
from crypto_strategy_lab.mean_reversion_v2 import (
    bollinger_reentry_flags,
    classify_signal,
    moving_mean,
)


def test_v2_defaults_match_research_design():
    values = enhanced_default_gui_config()
    assert values["mean_reversion_mean_type"] == "SMA"
    assert values["mean_reversion_period"] == 20
    assert values["mean_reversion_bb_stddevs"] == 2.0
    assert values["mean_reversion_rsi_period"] == 14
    assert values["mean_reversion_rsi_oversold"] == 30.0
    assert values["mean_reversion_rsi_overbought"] == 70.0
    assert values["mean_reversion_require_reentry"] is True
    cfg = build_enhanced_backtest_config(values, require_paths=False)
    assert cfg.mean_reversion_mean_type == "SMA"
    assert cfg.mean_reversion_bb_stddevs == 2.0
    assert cfg.mean_reversion_rsi_period == 14


def test_moving_mean_supports_causal_sma_and_ema():
    close = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    sma = moving_mean(close, 3, "SMA")
    ema = moving_mean(close, 3, "EMA")
    assert np.isnan(sma[0]) and np.isnan(sma[1])
    assert sma[2] == pytest.approx(11.0)
    assert np.isnan(ema[0]) and np.isnan(ema[1])
    assert np.isfinite(ema[-1])


def test_reentry_confirmation_can_span_multiple_outside_candles():
    close = np.array([100.0, 94.0, 93.0, 96.0, 100.0])
    lower = np.array([95.0] * len(close))
    upper = np.array([105.0] * len(close))
    rsi = np.array([50.0, 28.0, 32.0, 38.0, 50.0])
    long_reentry, short_reentry = bollinger_reentry_flags(close, lower, upper, rsi, 30.0, 70.0)
    assert long_reentry.tolist() == [False, False, False, True, False]
    assert not short_reentry.any()
    assert classify_signal(96.0, 95.0, 105.0, 38.0, 30.0, 70.0, True, False, True) == "STRONG_LONG"


def test_enhanced_engine_records_signal_without_changing_di_direction():
    n = 30
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": np.arange(n, dtype=float) + 100,
            "high": np.arange(n, dtype=float) + 102,
            "low": np.arange(n, dtype=float) + 99,
            "close": np.arange(n, dtype=float) + 101,
            "volume": 1.0,
        }
    )
    values = enhanced_default_gui_config()
    values.update({"adx_period": 2, "mean_reversion_period": 5, "mean_reversion_rsi_period": 5})
    config = build_enhanced_backtest_config(values, require_paths=False)
    engine = EnhancedBacktestEngine(candles, config)
    engine.plus_di_values[:] = 30
    engine.minus_di_values[:] = 10
    engine.di_spread[:] = 20
    i = n - 1
    close = float(engine.close[i])
    engine.mean_reversion_mean[i] = close
    engine.mean_reversion_bb_lower[i] = close - 1.0
    engine.mean_reversion_bb_upper[i] = close + 1.0
    engine.mean_reversion_sigma[i] = 0.5
    engine.mean_reversion_bb_zscore[i] = 0.0
    engine.mean_reversion_rsi_values[i] = 35.0
    engine.mean_reversion_long_reentry[i] = True
    engine.mean_reversion_short_reentry[i] = False
    snapshot = engine._mean_reversion_snapshot(i, "LONG", "LONG")
    assert engine._selected_direction(i) == "LONG"
    assert snapshot["mean_reversion_signal"] == "STRONG_LONG"
    assert snapshot["mean_reversion_alignment"] == "FAVORS_REVERSION"
    assert snapshot["mean_reversion_reentry_confirmation"] == "LONG"


def test_enhanced_di_tab_exposes_configurable_mean_reversion_controls():
    qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from crypto_strategy_lab.gui.enhanced_main_window import MainWindow

    app = qtwidgets.QApplication.instance() or qtwidgets.QApplication(sys.argv)
    window = MainWindow()
    try:
        assert window.mean_reversion_mean_type.currentText() == "SMA"
        assert window.mean_reversion_period.value() == 20
        assert window.mean_reversion_bb_stddevs.value() == pytest.approx(2.0)
        assert window.mean_reversion_rsi_period.value() == 14
        assert window.mean_reversion_rsi_oversold.value() == pytest.approx(30.0)
        assert window.mean_reversion_rsi_overbought.value() == pytest.approx(70.0)
        assert window.mean_reversion_require_reentry.isChecked()
        values = window.values()
        assert values["mean_reversion_mean_type"] == "SMA"
        assert values["mean_reversion_bb_stddevs"] == pytest.approx(2.0)
        idx = [window.tabs.tabText(i) for i in range(window.tabs.count())].index("DI Direction & Pressure")
        labels = [w.text() for w in window.tabs.widget(idx).findChildren(qtwidgets.QLabel)]
        assert any("POTENTIAL LONG" in text for text in labels)
        assert any("STRONG SHORT" in text for text in labels)
    finally:
        window.close()
