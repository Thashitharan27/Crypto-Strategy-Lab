"""Acceptance tests for the active Reports & Diagnostics redesign."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ReportingConfig, ResearchRunConfig
from crypto_strategy_lab.gui.reports_diagnostics_workspace import (
    REPORT_PROFILE_LABELS,
    REPORT_PROFILE_VALUES,
    apply_reporting_profile,
    matching_reporting_profile,
)


ROOT = Path(__file__).resolve().parents[1]


def test_reporting_profiles_are_deterministic_and_preserve_run_details():
    base = ReportingConfig(run_name="named-run", output_dir="custom/output")
    assert set(REPORT_PROFILE_VALUES) == {"CORE", "REVIEW", "DEEP_DIAGNOSTICS"}
    for profile in REPORT_PROFILE_VALUES:
        first = apply_reporting_profile(base, profile)
        second = apply_reporting_profile(base, profile)
        assert first == second
        assert first.run_name == "named-run"
        assert first.output_dir == "custom/output"
        assert matching_reporting_profile(first) == profile

    assert apply_reporting_profile(base, "CORE").create_standard_charts is False
    assert apply_reporting_profile(base, "REVIEW").create_standard_charts is True
    deep = apply_reporting_profile(base, "DEEP_DIAGNOSTICS")
    assert deep.enable_trade_telemetry is True
    assert deep.save_full_telemetry_csv is True
    assert deep.enable_indicator_lifecycle_analysis is True


def test_active_app_installs_reports_diagnostics_composition():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "apply_reports_diagnostics_workspace" in source
    assert "apply_reports_diagnostics_workspace(window)" in source


def _window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.reports_diagnostics_install import (
        apply_reports_diagnostics_workspace,
    )
    from crypto_strategy_lab.gui.rule_main_window import MainWindow

    app = widgets.QApplication.instance() or widgets.QApplication([])

    class Catalog:
        def symbols(self):
            return ["BTCUSDT"]

        def coverage(self, _request):
            return []

        def inventory(self, *_args):
            return []

    class Service:
        catalog = Catalog()

        def refresh_catalog(self):
            return 0

    window = MainWindow(service=Service())
    apply_reports_diagnostics_workspace(window)
    return app, window


def test_reports_page_is_profile_driven_and_reuses_authoritative_native_widgets():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        widgets = window.reporting_form.widgets
        assert workspace.run_name is widgets["run_name"]
        assert workspace.telemetry_enabled is widgets["enable_trade_telemetry"]
        assert workspace.lifecycle_enabled is widgets["enable_indicator_lifecycle_analysis"]
        assert widgets["analysis_level"].isHidden()
        assert widgets["lifecycle_early_checkpoints"].isHidden()
        assert workspace.profile_selector.currentData() == "REVIEW"
        assert [
            workspace.profile_selector.itemText(index)
            for index in range(workspace.profile_selector.count())
        ] == [
            REPORT_PROFILE_LABELS["CORE"],
            REPORT_PROFILE_LABELS["REVIEW"],
            REPORT_PROFILE_LABELS["DEEP_DIAGNOSTICS"],
            REPORT_PROFILE_LABELS["CUSTOM"],
        ]

        page = window.pages.widget(4)
        buttons = [button.text() for button in page.findChildren(type(workspace.profile_selector).mro()[1])]
        # QComboBox ancestry is not useful for button discovery; verify directly
        # through the page text instead that the retired action does not survive.
        visible_text = "\n".join(
            child.text() for child in page.findChildren(
                pytest.importorskip("PySide6.QtWidgets").QPushButton
            )
        )
        assert "Apply Preset" not in visible_text
    finally:
        window.close()


def test_profile_selection_applies_immediately_and_changes_only_reporting_config():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        before = window.build_config()

        workspace.profile_selector.setCurrentIndex(
            workspace.profile_selector.findData("CORE")
        )
        core = window.build_config()
        assert core.reporting == apply_reporting_profile(before.reporting, "CORE")
        assert (core.data, core.features, core.strategy, core.execution) == (
            before.data,
            before.features,
            before.strategy,
            before.execution,
        )
        assert "Fastest" in workspace.cost_label.text()

        workspace.profile_selector.setCurrentIndex(
            workspace.profile_selector.findData("DEEP_DIAGNOSTICS")
        )
        deep = window.build_config()
        assert deep.reporting == apply_reporting_profile(core.reporting, "DEEP_DIAGNOSTICS")
        assert deep.reporting.save_trade_journey_summary is True
        assert deep.reporting.save_trade_journey_charts is True
        assert deep.reporting.save_full_telemetry_csv is True
        assert deep.reporting.create_lifecycle_charts is True
        assert "Slower" in workspace.cost_label.text()
    finally:
        window.close()


def test_manual_diagnostic_changes_switch_to_custom_and_dependencies_are_automatic():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        assert workspace.profile_selector.currentData() == "REVIEW"

        workspace.journey_summary.setChecked(True)
        assert workspace.telemetry_enabled.isChecked() is True
        assert workspace.profile_selector.currentData() == "CUSTOM"

        workspace.telemetry_enabled.setChecked(False)
        assert workspace.journey_summary.isChecked() is False
        assert workspace.journey_charts.isChecked() is False
        assert workspace.raw_telemetry.isChecked() is False

        workspace.lifecycle_charts.setChecked(True)
        assert workspace.lifecycle_enabled.isChecked() is True
        assert workspace.profile_selector.currentData() == "CUSTOM"
    finally:
        window.close()


def test_run_details_do_not_change_profile_and_output_folder_uses_native_sink():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        assert workspace.profile_selector.currentData() == "REVIEW"

        workspace.run_name.setText("review-2026")
        workspace.output_dir.setText("output/review-2026")
        assert workspace.profile_selector.currentData() == "REVIEW"
        assert window.output_root.text() == "output/review-2026"
        config = window.build_config()
        assert config.reporting.run_name == "review-2026"
        assert config.reporting.output_dir == "output/review-2026"
        assert window.output_root.isHidden()
    finally:
        window.close()


def test_checkpoint_controls_replace_json_editor_and_roundtrip_as_native_tuple():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        workspace.profile_selector.setCurrentIndex(
            workspace.profile_selector.findData("DEEP_DIAGNOSTICS")
        )
        assert workspace.checkpoint_editor.values() == (15, 30, 60)
        assert [spin.suffix() for spin in workspace.checkpoint_editor.spin_boxes] == [
            " min", " min", " min"
        ]

        workspace.checkpoint_editor.spin_boxes[0].setValue(20)
        assert workspace.profile_selector.currentData() == "CUSTOM"
        assert window.build_config().reporting.lifecycle_early_checkpoints == (20, 30, 60)

        workspace.checkpoint_editor.add_button.click()
        assert window.build_config().reporting.lifecycle_early_checkpoints == (20, 30, 60, 75)
    finally:
        window.close()


def test_advanced_controls_and_always_saved_contract_are_presented_as_requested():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        assert workspace.journey_advanced.isHidden()
        assert workspace.lifecycle_advanced.isHidden()
        workspace.show_journey_advanced.setChecked(True)
        workspace.show_lifecycle_advanced.setChecked(True)
        assert not workspace.journey_advanced.isHidden()
        assert not workspace.lifecycle_advanced.isHidden()

        text = "\n".join(
            label.text()
            for label in workspace.findChildren(
                pytest.importorskip("PySide6.QtWidgets").QLabel
            )
        )
        assert "run_manifest.json" in text
        assert "backtest_report.xlsx" in text
        assert "provenance/source_archives.parquet" in text
        assert "Minimum Bucket Sample" in text
        assert "Flat-pattern Threshold" in text
        assert "raw telemetry" in text.lower()
    finally:
        window.close()


def test_custom_reporting_config_survives_active_gui_roundtrip_losslessly():
    _app, window = _window()
    try:
        base = ResearchRunConfig()
        reporting = replace(
            base.reporting,
            run_name="custom-diagnostics",
            output_dir="output/custom-diagnostics",
            enable_trade_telemetry=True,
            save_trade_journey_summary=True,
            telemetry_interval_minutes=30,
            enable_indicator_lifecycle_analysis=True,
            lifecycle_phases=6,
            lifecycle_early_checkpoints=(10, 25, 90),
            lifecycle_minimum_bucket_sample=12,
            lifecycle_flat_pattern_threshold_pct=7.5,
            save_feature_analysis_reports=True,
        )
        config = replace(base, reporting=reporting)
        window.apply_config(config)

        workspace = window.reports_diagnostics_workspace
        assert workspace.profile_selector.currentData() == "CUSTOM"
        assert workspace.checkpoint_editor.values() == (10, 25, 90)
        assert workspace.output_dir.text() == "output/custom-diagnostics"
        assert window.build_config().reporting == reporting
    finally:
        window.close()
