from __future__ import annotations

import os

import pytest

from crypto_strategy_lab.gui.research_feature_ownership import apply_research_feature_ownership
from crypto_strategy_lab.gui.risk_execution_install import apply_risk_execution_workspace


def _window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.rule_main_window import MainWindow

    app = widgets.QApplication.instance() or widgets.QApplication([])

    class Catalog:
        def symbols(self):
            return ["BTCUSDT"]

        def coverage(self, _request):
            return []

    class Service:
        catalog = Catalog()

        def refresh_catalog(self):
            return 0

    window = MainWindow(service=Service())
    apply_research_feature_ownership(window)
    apply_risk_execution_workspace(window)
    return app, window


def test_risk_page_is_reorganized_around_one_execution_plan():
    app, window = _window()
    try:
        from PySide6.QtWidgets import QGroupBox

        page = window.pages.widget(3)
        titles = {
            box.title()
            for box in page.findChildren(QGroupBox)
            if not box.isHidden()
        }
        assert "Effective Plan" in titles
        assert "1. Entry Execution" in titles
        assert "2. Account Risk & Position Sizing" in titles
        assert "3. Stop & Position Sizing" in titles
        assert "4. Profit Target" in titles
        assert "5. Trade Management" in titles
        assert "Advanced Trade Management" in titles
        assert "Exposure & Costs" in titles
        assert "Base Trade Management" not in titles

        workspace = window.risk_execution_workspace
        assert window.execution_form.isHidden()
        assert window.base_execution_form.isHidden()
        assert not window.execution_form.widgets["entry_timing_mode"].isHidden()
        assert "effective sizing budget" in workspace.summary_label.text().lower()
        assert "Entry fill:" in workspace.summary_label.text()
        assert "ATR distance unit" in workspace.summary_label.text()
    finally:
        window.close()
        app.processEvents()


def test_stop_distance_method_shows_only_the_active_parameter():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        mode = window.execution_form.widgets["risk_mode"]
        atr = window.execution_form.widgets["atr_multiplier"]
        percent = window.execution_form.widgets["percent_r"]
        fixed = window.execution_form.widgets["fixed_r"]
        sr_timeframe = window.execution_form.widgets["sr_stop_timeframe_minutes"]
        sr_buffer = window.execution_form.widgets["sr_stop_buffer_atr"]
        stop_multiplier = window.base_execution_form.widgets["stop_loss_multiple"]
        sizing_override = window.base_execution_form.widgets[
            "position_sizing_stop_override_enabled"
        ]
        sizing_multiple = window.base_execution_form.widgets[
            "position_sizing_stop_multiple"
        ]

        mode.setCurrentIndex(mode.findData("ATR"))
        workspace.refresh_visibility()
        assert not atr.isHidden()
        assert percent.isHidden()
        assert fixed.isHidden()

        mode.setCurrentIndex(mode.findData("PERCENT"))
        workspace.refresh_visibility()
        assert atr.isHidden()
        assert not percent.isHidden()
        assert fixed.isHidden()

        mode.setCurrentIndex(mode.findData("FIXED"))
        workspace.refresh_visibility()
        assert atr.isHidden()
        assert percent.isHidden()
        assert not fixed.isHidden()

        mode.setCurrentIndex(mode.findData("SR_STRUCTURE"))
        workspace.refresh_visibility()
        assert atr.isHidden()
        assert percent.isHidden()
        assert fixed.isHidden()
        assert not sr_timeframe.isHidden()
        assert not sr_buffer.isHidden()
        assert stop_multiplier.isHidden()
        assert sizing_override.isHidden()
        assert sizing_multiple.isHidden()
        assert "structural s/r" in workspace.summary_label.text().lower()
    finally:
        window.close()
        app.processEvents()


def test_separate_sizing_stop_shows_actual_gross_stop_exposure():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        risk = window.execution_form.widgets["risk_per_leg"]
        actual_stop = window.base_execution_form.widgets["stop_loss_multiple"]
        override = window.base_execution_form.widgets[
            "position_sizing_stop_override_enabled"
        ]
        sizing_stop = window.base_execution_form.widgets[
            "position_sizing_stop_multiple"
        ]
        target = window.base_execution_form.widgets["reward_risk_ratio"]

        risk.setValue(5.0)
        actual_stop.setValue(0.2)
        target.setValue(0.2)
        override.setChecked(True)
        sizing_stop.setValue(1.0)
        app.processEvents()
        workspace.refresh_visibility()

        assert not override.isHidden()
        assert not sizing_stop.isHidden()
        summary = workspace.summary_label.text()
        assert "sizing budget 5.00%" in summary
        assert "separate 1× reference stop" in summary
        assert "about 1.00%" in summary
        assert "gross stop exposure before fees/slippage" in summary
        assert "Fixed target = 0.20 sizing-R" in summary
        assert "physical target:stop = 1:1" in summary
        target_label = workspace.target_card.rows["reward_risk_ratio"][0]
        assert target_label is not None
        assert target_label.text() == "Profit Target (Sizing-R)"

        override.setChecked(False)
        app.processEvents()
        workspace.refresh_visibility()
        assert sizing_stop.isHidden()
        assert "gross stop exposure before fees/slippage" not in workspace.summary_label.text()
    finally:
        window.close()
        app.processEvents()


def test_separate_sizing_mode_disables_incompatible_r_based_management():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        break_even = window.base_execution_form.widgets["break_even_enabled"]
        override = window.base_execution_form.widgets[
            "position_sizing_stop_override_enabled"
        ]
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]

        break_even.setChecked(True)
        target_mode.setCurrentIndex(target_mode.findData("SR_CAPPED_R"))
        override.setChecked(True)
        app.processEvents()
        workspace.refresh_visibility()

        assert break_even.isChecked() is False
        assert break_even.isEnabled() is False
        assert target_mode.currentData() == "FIXED_R"
        assert target_mode.isEnabled() is False

        override.setChecked(False)
        app.processEvents()
        workspace.refresh_visibility()
        assert break_even.isEnabled() is True
        assert target_mode.isEnabled() is True
    finally:
        window.close()
        app.processEvents()


def test_sr_structural_stop_automatically_owns_support_resistance_dependency():
    app, window = _window()
    try:
        stop_mode = window.execution_form.widgets["risk_mode"]
        sr_toggle = window.feature_form.widgets["enable_support_resistance_analysis"]
        panel = window.research_features_panel

        sr_toggle.setChecked(False)
        stop_mode.setCurrentIndex(stop_mode.findData("SR_STRUCTURE"))
        app.processEvents()

        assert sr_toggle.isChecked() is True
        assert sr_toggle.isEnabled() is False
        assert panel.sr_card.status.text() == "REQUIRED BY STOP POLICY"
        assert window.build_config().features.enable_support_resistance_analysis is True

        stop_mode.setCurrentIndex(stop_mode.findData("ATR"))
        app.processEvents()
        assert sr_toggle.isEnabled() is True
        assert sr_toggle.isChecked() is False
    finally:
        window.close()
        app.processEvents()


def test_optional_trade_management_reveals_settings_only_when_enabled():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        enabled = window.base_execution_form.widgets["break_even_enabled"]
        activation = window.base_execution_form.widgets["break_even_activation_r"]
        offset = window.base_execution_form.widgets["break_even_offset_r"]

        enabled.setChecked(False)
        workspace.refresh_visibility()
        assert activation.isHidden()
        assert offset.isHidden()

        enabled.setChecked(True)
        workspace.refresh_visibility()
        assert not activation.isHidden()
        assert not offset.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_sr_target_policy_automatically_owns_support_resistance_dependency():
    app, window = _window()
    try:
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]
        sr_toggle = window.feature_form.widgets["enable_support_resistance_analysis"]
        panel = window.research_features_panel

        sr_toggle.setChecked(False)
        target_mode.setCurrentIndex(target_mode.findData("SR_CAPPED_R"))
        app.processEvents()

        assert sr_toggle.isChecked() is True
        assert sr_toggle.isEnabled() is False
        assert panel.sr_card.status.text() == "REQUIRED BY TARGET POLICY"
        assert not window.execution_form.widgets["sr_take_profit_minimum_r"].isHidden()
        assert window.build_config().features.enable_support_resistance_analysis is True

        target_mode.setCurrentIndex(target_mode.findData("SR_LEVEL"))
        app.processEvents()
        assert sr_toggle.isChecked() is True
        assert not window.execution_form.widgets["sr_take_profit_timeframe_minutes"].isHidden()

        target_mode.setCurrentIndex(target_mode.findData("FIXED_R"))
        app.processEvents()
        assert sr_toggle.isEnabled() is True
        assert sr_toggle.isChecked() is False
        assert window.execution_form.widgets["sr_take_profit_minimum_r"].isHidden()
    finally:
        window.close()
        app.processEvents()


def test_ema_920_execution_plan_is_explicit_and_generic_stop_target_controls_are_hidden():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        selector = window.rule_builder.direction_mode
        timing = window.execution_form.widgets["entry_timing_mode"]
        risk_mode = window.execution_form.widgets["risk_mode"]
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]
        base_target = window.base_execution_form.widgets["reward_risk_ratio"]

        ema_index = selector.findData("EMA_9_20_PULLBACK")
        selector.setCurrentIndex(ema_index)
        selector.activated.emit(ema_index)
        app.processEvents()
        workspace.refresh_visibility()

        assert timing.currentData() == "NEXT_CANDLE_OPEN"
        assert not timing.isHidden()
        assert risk_mode.isHidden()
        assert target_mode.isHidden()
        assert base_target.isHidden()
        assert not workspace.ema_stop_method.isHidden()
        assert workspace.ema_stop_method.text() == "EMA 9/20 Micro-Swing — Automatic"
        assert workspace.ema_stop_confirmation.text() == "2 left / 2 right"
        assert workspace.ema_stop_lookback.text() == "20 bars"
        assert workspace.ema_stop_buffer.text() == "0.05 × ATR"
        assert workspace.ema_stop_maximum.text() == "1.50 × ATR"
        assert not workspace.ema_target_method.isHidden()
        assert workspace.ema_target_method.text() == "EMA 9/20 Fixed 1R — Automatic"
        assert workspace.ema_target_value.text() == "1.00 R"
        assert "Next Candle Open — Causal" in workspace.summary_label.text()
        assert "confirmed micro-swing" in workspace.summary_label.text()
        assert "automatic fixed 1.00R target" in workspace.summary_label.text()

        plan = window.execution_form.widgets["ema_920_trade_plan"]
        plan.setCurrentIndex(plan.findData("EMA_20_100_CROSS"))
        app.processEvents()
        assert workspace.ema_stop_method.text() == "EMA 100 at Signal Close — Automatic"
        assert workspace.ema_stop_confirmation.isHidden()
        assert workspace.ema_stop_lookback.isHidden()
        assert workspace.ema_stop_maximum.isHidden()
        assert "below EMA 100" in workspace.ema_stop_buffer.text()
        assert "signal-candle EMA 100" in workspace.summary_label.text()
        assert "EMA 100 stop remains active" in workspace.ema_target_value.text()

        # Entry timing remains deliberately editable for A/B execution testing.
        legacy_index = timing.findData("SIGNAL_CLOSE")
        timing.setCurrentIndex(legacy_index)
        app.processEvents()
        assert timing.currentData() == "SIGNAL_CLOSE"
        assert "Signal Candle Close — Legacy" in workspace.summary_label.text()

        # Returning to a normal strategy restores the generic stop/target controls.
        di_index = selector.findData("DI")
        selector.setCurrentIndex(di_index)
        selector.activated.emit(di_index)
        app.processEvents()
        workspace.refresh_visibility()
        assert not risk_mode.isHidden()
        assert not target_mode.isHidden()
        assert not base_target.isHidden()
        assert workspace.ema_stop_method.isHidden()
        assert workspace.ema_target_method.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_ema_920_hidden_generic_sr_policy_does_not_force_sr_dependency():
    app, window = _window()
    try:
        selector = window.rule_builder.direction_mode
        stop_mode = window.execution_form.widgets["risk_mode"]
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]
        sr_toggle = window.feature_form.widgets["enable_support_resistance_analysis"]

        sr_toggle.setChecked(False)
        stop_mode.setCurrentIndex(stop_mode.findData("SR_STRUCTURE"))
        target_mode.setCurrentIndex(target_mode.findData("SR_LEVEL"))
        app.processEvents()
        assert sr_toggle.isChecked() is True
        assert sr_toggle.isEnabled() is False

        ema_index = selector.findData("EMA_9_20_PULLBACK")
        selector.setCurrentIndex(ema_index)
        selector.activated.emit(ema_index)
        app.processEvents()

        # EMA 9/20 owns stop and target internally. Hidden generic S/R execution
        # values must not force S/R calculation unless a visible rule requires it.
        assert sr_toggle.isEnabled() is True
        assert sr_toggle.isChecked() is False
    finally:
        window.close()
        app.processEvents()
