"""Acceptance tests for the active artifact-oriented Reports & Diagnostics UI."""
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
        assert first.enable_trade_telemetry is False
        assert first.enable_indicator_lifecycle_analysis is False

    assert apply_reporting_profile(base, "CORE").create_standard_charts is False
    review = apply_reporting_profile(base, "REVIEW")
    assert review.create_standard_charts is True
    assert review.save_indicator_analysis_reports is True
    assert review.save_feature_analysis_reports is False
    deep = apply_reporting_profile(base, "DEEP_DIAGNOSTICS")
    assert deep.create_standard_charts is True
    assert deep.save_indicator_analysis_reports is True
    assert deep.save_feature_analysis_reports is True


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


def test_reports_page_is_profile_driven_and_legacy_telemetry_modules_are_absent():
    _app, window = _window()
    try:
        qt_widgets = pytest.importorskip("PySide6.QtWidgets")
        workspace = window.reports_diagnostics_workspace
        widgets = window.reporting_form.widgets
        assert workspace.run_name is widgets["run_name"]
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
        visible_text = "\n".join(
            [child.text() for child in page.findChildren(qt_widgets.QLabel)]
            + [child.title() for child in page.findChildren(qt_widgets.QGroupBox)]
        )
        assert "Trade Journey Diagnostics" not in visible_text
        assert "Indicator Lifecycle Diagnostics" not in visible_text
        assert "Telemetry Interval" not in visible_text
        assert "Early Checkpoints" not in visible_text
        assert "Optional Artifact-Derived Analysis" in visible_text
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
        assert deep.reporting.save_feature_analysis_reports is True
        assert deep.reporting.enable_trade_telemetry is False
        assert deep.reporting.enable_indicator_lifecycle_analysis is False
        assert "without simulator telemetry" in workspace.cost_label.text()
    finally:
        window.close()


def test_manual_artifact_report_change_switches_to_custom():
    _app, window = _window()
    try:
        workspace = window.reports_diagnostics_workspace
        assert workspace.profile_selector.currentData() == "REVIEW"

        widget = window.reporting_form.widgets["save_feature_analysis_reports"]
        widget.setChecked(True)
        assert workspace.profile_selector.currentData() == "CUSTOM"
        assert window.build_config().reporting.save_feature_analysis_reports is True
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


def test_always_saved_contract_and_artifact_derived_analysis_are_presented():
    _app, window = _window()
    try:
        qt_widgets = pytest.importorskip("PySide6.QtWidgets")
        workspace = window.reports_diagnostics_workspace
        text = "\n".join(
            [label.text() for label in workspace.findChildren(qt_widgets.QLabel)]
            + [box.title() for box in workspace.findChildren(qt_widgets.QGroupBox)]
        )
        assert "run_manifest.json" in text
        assert "backtest_report.xlsx" in text
        assert "provenance/source_archives.parquet" in text
        assert "feature-context" in text
        assert "Optional Artifact-Derived Analysis" in text
        assert "after the simulation" in text
    finally:
        window.close()


def test_loaded_legacy_diagnostic_settings_are_retired_to_inert_values():
    _app, window = _window()
    try:
        base = ResearchRunConfig()
        reporting = replace(
            base.reporting,
            enable_trade_telemetry=True,
            save_full_telemetry_csv=True,
            save_trade_journey_summary=True,
            save_trade_journey_charts=True,
            enable_indicator_lifecycle_analysis=True,
            create_lifecycle_charts=True,
            save_feature_analysis_reports=True,
        )
        window.apply_config(replace(base, reporting=reporting))

        current = window.build_config().reporting
        assert current.enable_trade_telemetry is False
        assert current.save_full_telemetry_csv is False
        assert current.save_trade_journey_summary is False
        assert current.save_trade_journey_charts is False
        assert current.enable_indicator_lifecycle_analysis is False
        assert current.create_lifecycle_charts is False
        assert current.save_feature_analysis_reports is True
    finally:
        window.close()
