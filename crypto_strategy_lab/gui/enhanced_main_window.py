"""GUI layer for the configurable Bollinger + RSI mean-reversion research model."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import crypto_strategy_lab.gui.main_window as base_main_window_module
import crypto_strategy_lab.gui.worker as worker_module
import crypto_strategy_lab.portfolio as portfolio_module
from crypto_strategy_lab.enhanced_engine import EnhancedBacktestEngine
from crypto_strategy_lab.enhanced_statistics import mean_reversion_analysis_v2
from crypto_strategy_lab.gui.enhanced_config import (
    MEAN_REVERSION_V2_DEFAULTS,
    build_enhanced_backtest_config,
    enhanced_default_gui_config,
    load_enhanced_config_json,
    save_enhanced_config_json,
)
from crypto_strategy_lab.gui.main_window import MainWindow as BaseMainWindow


# Route the existing GUI/worker/portfolio pipeline through the enhanced contract
# without duplicating the mature simulation and output code.
base_main_window_module.build_backtest_config = build_enhanced_backtest_config
base_main_window_module.default_gui_config = enhanced_default_gui_config
base_main_window_module.save_config_json = save_enhanced_config_json
base_main_window_module.load_config_json = load_enhanced_config_json
worker_module.BacktestEngine = EnhancedBacktestEngine
worker_module.mean_reversion_analysis = mean_reversion_analysis_v2
portfolio_module.BacktestEngine = EnhancedBacktestEngine
portfolio_module.build_backtest_config = build_enhanced_backtest_config
portfolio_module.load_config_json = load_enhanced_config_json


class MainWindow(BaseMainWindow):
    """Crypto Strategy Lab main window with mean-reversion research v2 controls."""

    def _build_di_strategy_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QVBoxLayout(inner)

        intro = QLabel(
            "DI-direction strategy settings live here. Mean Reversion Analysis is record-only: "
            "it adds context to each entry but never filters, flips, resizes, or rejects a trade."
        )
        intro.setWordWrap(True)
        form.addWidget(intro)

        direction_box = QGroupBox("DI Direction Selection")
        direction_form = QFormLayout(direction_box)
        rule = QLabel("Current Rule\n+DI above -DI → LONG\n-DI above +DI → SHORT")
        rule.setWordWrap(True)
        direction_form.addRow("", self.enable_di_direction_selection)
        direction_form.addRow("", rule)
        form.addWidget(direction_box)

        pressure_box = QGroupBox("DI Pressure Analysis")
        pressure_form = QFormLayout(pressure_box)
        pressure_mode = QLabel("Analysis Mode: RECORD ONLY\nDoes not filter or reject trades.")
        pressure_help = QLabel(
            "DI direction chooses LONG or SHORT from +DI versus -DI. DI Pressure Analysis measures "
            "whether directional pressure is strengthening or weakening before entry. DI Spread entry "
            "filtering remains under Strategy Profiles → Rules → DI Spread."
        )
        pressure_help.setWordWrap(True)
        pressure_form.addRow("", self.enable_di_pressure_analysis)
        pressure_form.addRow("Lookback", self.di_pressure_lookback)
        pressure_form.addRow("", pressure_mode)
        pressure_form.addRow("", pressure_help)
        form.addWidget(pressure_box)

        mean_box = QGroupBox("Mean Reversion Analysis")
        mean_form = QFormLayout(mean_box)
        mean_mode = QLabel("Analysis Mode: RECORD ONLY\nDoes not filter or reject trades.")
        mean_mode.setWordWrap(True)

        self.mean_reversion_mean_type = QComboBox()
        self.mean_reversion_mean_type.addItems(["SMA", "EMA"])
        self.mean_reversion_bb_stddevs = QDoubleSpinBox()
        self.mean_reversion_bb_stddevs.setRange(0.1, 10.0)
        self.mean_reversion_bb_stddevs.setDecimals(2)
        self.mean_reversion_bb_stddevs.setSingleStep(0.1)
        self.mean_reversion_rsi_period = QSpinBox()
        self.mean_reversion_rsi_period.setRange(2, 1000)
        self.mean_reversion_rsi_oversold = QDoubleSpinBox()
        self.mean_reversion_rsi_oversold.setRange(0.0, 100.0)
        self.mean_reversion_rsi_oversold.setDecimals(1)
        self.mean_reversion_rsi_overbought = QDoubleSpinBox()
        self.mean_reversion_rsi_overbought.setRange(0.0, 100.0)
        self.mean_reversion_rsi_overbought.setDecimals(1)
        self.mean_reversion_require_reentry = QCheckBox("Require close back inside Bollinger Band for STRONG signal")
        self.mean_reversion_track_atr_distance = QCheckBox("Track distance from mean in ATR units")
        self.mean_reversion_track_motion = QCheckBox("Track motion toward / away from mean")

        self.enable_mean_reversion_analysis.setToolTip(
            "Record Bollinger, RSI, mean-distance, and re-entry telemetry. This never changes trade selection."
        )
        self.mean_reversion_period.setToolTip(
            "Lookback used for the selected moving mean and the Bollinger rolling standard deviation."
        )
        self.mean_reversion_mean_type.setToolTip("SMA is the default textbook mean; EMA remains available for comparison.")
        self.mean_reversion_bb_stddevs.setToolTip("Bollinger Band width in population standard deviations around the selected mean.")
        self.mean_reversion_rsi_period.setToolTip("Wilder RSI lookback used to identify momentum exhaustion.")
        self.mean_reversion_rsi_oversold.setToolTip("RSI at or below this value arms a potential LONG mean-reversion setup.")
        self.mean_reversion_rsi_overbought.setToolTip("RSI at or above this value arms a potential SHORT mean-reversion setup.")

        mean_form.addRow("", self.enable_mean_reversion_analysis)
        mean_form.addRow("Mean Type", self.mean_reversion_mean_type)
        mean_form.addRow("Mean / BB Period", self.mean_reversion_period)
        mean_form.addRow("BB Standard Deviations", self.mean_reversion_bb_stddevs)
        mean_form.addRow("RSI Period", self.mean_reversion_rsi_period)
        mean_form.addRow("RSI Oversold", self.mean_reversion_rsi_oversold)
        mean_form.addRow("RSI Overbought", self.mean_reversion_rsi_overbought)
        mean_form.addRow("", self.mean_reversion_require_reentry)
        mean_form.addRow("", self.mean_reversion_track_atr_distance)
        mean_form.addRow("", self.mean_reversion_track_motion)
        mean_form.addRow("", mean_mode)

        mean_help = QLabel(
            "Signal model:\n"
            "• POTENTIAL LONG: close below the lower band + RSI oversold.\n"
            "• STRONG LONG: an RSI-confirmed lower-band excursion closes back inside the band.\n"
            "• POTENTIAL SHORT: close above the upper band + RSI overbought.\n"
            "• STRONG SHORT: an RSI-confirmed upper-band excursion closes back inside the band.\n\n"
            "The trade list also keeps raw BB location, BB z-score, RSI value/state, ATR distance, and "
            "toward/away motion so DI × MR behaviour can be researched without hard-coded DI cutoffs."
        )
        mean_help.setWordWrap(True)
        mean_form.addRow("", mean_help)
        form.addWidget(mean_box)

        self.mean_reversion_controls = [
            self.mean_reversion_mean_type,
            self.mean_reversion_period,
            self.mean_reversion_bb_stddevs,
            self.mean_reversion_rsi_period,
            self.mean_reversion_rsi_oversold,
            self.mean_reversion_rsi_overbought,
            self.mean_reversion_require_reentry,
            self.mean_reversion_track_atr_distance,
            self.mean_reversion_track_motion,
        ]
        for control in self.mean_reversion_controls:
            if hasattr(control, "toggled"):
                control.toggled.connect(self.update_dynamic)
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self.update_dynamic)
            if hasattr(control, "currentTextChanged"):
                control.currentTextChanged.connect(self.update_dynamic)
        self.enable_mean_reversion_analysis.toggled.connect(self.update_dynamic)

        form.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.di_strategy_page = page
        self.config_controls += inner.findChildren(QWidget)
        self.tabs.addTab(page, "DI Direction & Pressure")
        self.analysis_level.setCurrentText("Standard (Recommended)")
        self._apply_analysis_preset()
        self._set_analysis_advanced(False)

    def values(self):
        values = super().values()
        values.update(
            {
                "mean_reversion_mean_type": self.mean_reversion_mean_type.currentText(),
                "mean_reversion_bb_stddevs": self.mean_reversion_bb_stddevs.value(),
                "mean_reversion_rsi_period": self.mean_reversion_rsi_period.value(),
                "mean_reversion_rsi_oversold": self.mean_reversion_rsi_oversold.value(),
                "mean_reversion_rsi_overbought": self.mean_reversion_rsi_overbought.value(),
                "mean_reversion_require_reentry": self.mean_reversion_require_reentry.isChecked(),
                "mean_reversion_track_atr_distance": self.mean_reversion_track_atr_distance.isChecked(),
                "mean_reversion_track_motion": self.mean_reversion_track_motion.isChecked(),
            }
        )
        return values

    def apply_values(self, values):
        merged = {**MEAN_REVERSION_V2_DEFAULTS, **values}
        super().apply_values(merged)
        self.mean_reversion_mean_type.setCurrentText(str(merged["mean_reversion_mean_type"]).upper())
        self.mean_reversion_bb_stddevs.setValue(float(merged["mean_reversion_bb_stddevs"]))
        self.mean_reversion_rsi_period.setValue(int(merged["mean_reversion_rsi_period"]))
        self.mean_reversion_rsi_oversold.setValue(float(merged["mean_reversion_rsi_oversold"]))
        self.mean_reversion_rsi_overbought.setValue(float(merged["mean_reversion_rsi_overbought"]))
        self.mean_reversion_require_reentry.setChecked(bool(merged["mean_reversion_require_reentry"]))
        self.mean_reversion_track_atr_distance.setChecked(bool(merged["mean_reversion_track_atr_distance"]))
        self.mean_reversion_track_motion.setChecked(bool(merged["mean_reversion_track_motion"]))
        self.update_dynamic()
        self.update_planned_output()

    def update_dynamic(self):
        super().update_dynamic()
        if not hasattr(self, "mean_reversion_controls"):
            return
        enabled = self.enable_mean_reversion_analysis.isChecked()
        for control in self.mean_reversion_controls:
            control.setEnabled(enabled)
        self.mean_reversion_track_motion.setEnabled(enabled and self.mean_reversion_track_atr_distance.isChecked())
        if not self.mean_reversion_track_atr_distance.isChecked():
            self.mean_reversion_track_motion.setChecked(False)
