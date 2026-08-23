from __future__ import annotations

from dataclasses import replace
import os

import pytest

from crypto_strategy_lab.data_lake_config import ReportingConfig
from crypto_strategy_lab.gui.reports_diagnostics_install import (
    apply_reports_diagnostics_workspace,
)
from crypto_strategy_lab.gui.ux_presentation import detect_report_profile


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
    apply_reports_diagnostics_workspace(window)
    return app, window


def test_reports_page_exposes_outputs_not_serialization_fields():
    app, window = _window()
    try:
        from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton

        page = window.pages.widget(4)
        titles = {
            box.title()
            for box in page.findChildren(QGroupBox)
            if not box.isHidden()
        }
        assert "Output Profile" in titles
        assert "Run Details" in titles
        assert "Always Saved — Canonical Run Record" in titles
        assert "Human Review" in titles
        assert "Trade Journey Diagnostics · Moderate" in titles
        assert "Indicator Lifecycle Diagnostics · Moderate" in titles
        assert "Additional Diagnostic Export" in titles

        visible_text = " ".join(
            label.text()
            for label in page.findChildren(QLabel)
            if not label.isHidden()
        )
        assert "Full feature context" in visible_text
        assert "Run manifest" in visible_text
        assert "Analysis Level" not in visible_text
        assert not any(
            button.text() == "Apply Preset"
            for button in page.findChildren(QPushButton)
            if not button.isHidden()
        )
        assert window.reporting_form.isHidden()
        assert window.reports_diagnostics_workspace.profile.currentData() == "REVIEW"
    finally:
        window.close()
        app.processEvents()


def test_output_profiles_apply_immediately_and_manual_changes_become_custom():
    app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        profile = workspace.profile

        profile.setCurrentIndex(profile.findData("CORE"))
        app.processEvents()
        core = window.build_config().reporting
        assert core.create_human_workbook is False
        assert core.create_standard_charts is False
        assert core.enable_trade_telemetry is False
        assert core.enable_indicator_lifecycle_analysis is False
        assert detect_report_profile(core) == "CORE"

        profile.setCurrentIndex(profile.findData("REVIEW"))
        app.processEvents()
        review = window.build_config().reporting
        assert review.create_human_workbook is True
        assert review.create_standard_charts is True
        assert review.enable_trade_telemetry is False
        assert review.save_indicator_analysis_reports is False
        assert detect_report_profile(review) == "REVIEW"

        window.reporting_form.widgets["create_standard_charts"].setChecked(False)
        app.processEvents()
        assert workspace.profile.currentData() == "CUSTOM"
    finally:
        window.close()
        app.processEvents()


def test_deep_diagnostics_normalizes_sampling_to_strategy_timeframe():
    app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        timeframe = window.strategy_tf
        timeframe.setCurrentIndex(timeframe.findData("1h"))
        profile = workspace.profile
        profile.setCurrentIndex(profile.findData("DEEP_DIAGNOSTICS"))
        app.processEvents()

        reporting = window.build_config().reporting
        assert reporting.telemetry_interval_minutes == 60
        assert reporting.enable_trade_telemetry is True
        assert reporting.enable_indicator_lifecycle_analysis is True
        assert reporting.save_trade_journey_summary is True
        assert reporting.create_lifecycle_charts is True
        assert reporting.save_indicator_analysis_reports is True
        assert workspace.profile.currentData() == "DEEP_DIAGNOSTICS"
    finally:
        window.close()
        app.processEvents()


def test_friendly_checkpoint_editor_round_trips_without_json():
    app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        lifecycle = window.reporting_form.widgets["enable_indicator_lifecycle_analysis"]
        lifecycle.setChecked(True)
        workspace.checkpoints.edit.setText("15, 45, 90")
        workspace.checkpoints._commit()
        app.processEvents()

        reporting = window.build_config().reporting
        assert reporting.lifecycle_early_checkpoints == (15, 45, 90)
        assert workspace.checkpoints.edit.text() == "15, 45, 90"
    finally:
        window.close()
        app.processEvents()


def test_disabling_journey_clears_dependent_outputs_and_loaded_config_refreshes():
    app, window = _window()
    try:
        widgets = window.reporting_form.widgets
        widgets["enable_trade_telemetry"].setChecked(True)
        widgets["save_full_telemetry_csv"].setChecked(True)
        widgets["save_trade_journey_summary"].setChecked(True)
        widgets["save_trade_journey_charts"].setChecked(True)
        widgets["enable_trade_telemetry"].setChecked(False)
        app.processEvents()

        reporting = window.build_config().reporting
        assert reporting.save_full_telemetry_csv is False
        assert reporting.save_trade_journey_summary is False
        assert reporting.save_trade_journey_charts is False
        reporting.validate if False else None

        loaded = replace(
            window.config,
            reporting=replace(
                ReportingConfig(),
                create_standard_charts=False,
                lifecycle_early_checkpoints=(30, 60, 120),
            ),
        )
        window.apply_config(loaded)
        app.processEvents()
        assert window.reports_diagnostics_workspace.profile.currentData() == "CUSTOM"
        assert window.reports_diagnostics_workspace.checkpoints.edit.text() == "30, 60, 120"
    finally:
        window.close()
        app.processEvents()
