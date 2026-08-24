"""Researcher-facing Reports & Diagnostics workspace for the native v3 GUI.

The active workspace is intentionally artifact-oriented.  Legacy simulator
telemetry workflows (Trade Journey and Indicator Lifecycle) are retired from the
v3 UI because the canonical completed-run artifacts now support post-run feature
research without changing simulation behavior.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.data_lake_config import ReportingConfig


_RETIRED_DIAGNOSTIC_DEFAULTS = {
    "enable_trade_telemetry": False,
    "save_full_telemetry_csv": False,
    "save_trade_journey_summary": False,
    "save_trade_journey_charts": False,
    "telemetry_interval_minutes": 15,
    "enable_indicator_lifecycle_analysis": False,
    "lifecycle_phases": 4,
    "lifecycle_early_checkpoints": (15, 30, 60),
    "lifecycle_minimum_bucket_sample": 20,
    "create_lifecycle_charts": False,
    "lifecycle_flat_pattern_threshold_pct": 5.0,
}

REPORT_PROFILE_VALUES = {
    "CORE": {
        "analysis_level": "QUICK",
        **_RETIRED_DIAGNOSTIC_DEFAULTS,
        "save_feature_analysis_reports": False,
        "save_indicator_analysis_reports": False,
        "create_standard_charts": False,
    },
    "REVIEW": {
        "analysis_level": "STANDARD",
        **_RETIRED_DIAGNOSTIC_DEFAULTS,
        "save_feature_analysis_reports": False,
        "save_indicator_analysis_reports": True,
        "create_standard_charts": True,
    },
    "DEEP_DIAGNOSTICS": {
        "analysis_level": "DEEP",
        **_RETIRED_DIAGNOSTIC_DEFAULTS,
        "save_feature_analysis_reports": True,
        "save_indicator_analysis_reports": True,
        "create_standard_charts": True,
    },
}

REPORT_PROFILE_LABELS = {
    "CORE": "Core",
    "REVIEW": "Review — Recommended",
    "DEEP_DIAGNOSTICS": "Deep Research",
    "CUSTOM": "Custom",
}

REPORT_PROFILE_COSTS = {
    "CORE": "Fastest — canonical completed-run artifacts only.",
    "REVIEW": "Normal — standard charts and indicator review from completed-run artifacts.",
    "DEEP_DIAGNOSTICS": "More output — adds extended trade/exit analysis without simulator telemetry.",
    "CUSTOM": "Custom — output size depends on the artifact-derived reports selected below.",
}

REPORT_DIAGNOSTIC_FIELDS = tuple(REPORT_PROFILE_VALUES["REVIEW"])


def apply_reporting_profile(reporting: ReportingConfig, profile: str) -> ReportingConfig:
    """Apply one deterministic artifact-oriented reporting profile."""
    if profile not in REPORT_PROFILE_VALUES:
        raise ValueError(f"Unknown reporting profile: {profile}")
    return replace(reporting, **REPORT_PROFILE_VALUES[profile])


def matching_reporting_profile(reporting: ReportingConfig) -> str:
    """Return the exact active profile represented by a config, otherwise CUSTOM."""
    for profile, values in REPORT_PROFILE_VALUES.items():
        if all(getattr(reporting, name) == value for name, value in values.items()):
            return profile
    return "CUSTOM"


def retire_legacy_diagnostics(reporting: ReportingConfig) -> ReportingConfig:
    """Normalize removed telemetry-era controls to inert values on config load."""
    return replace(reporting, **_RETIRED_DIAGNOSTIC_DEFAULTS)


class ReportsDiagnosticsWorkspace(QWidget):
    """Compact profile-driven reports workspace over authoritative native widgets."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.form = window.reporting_form
        self.widgets = self.form.widgets
        self._rendering = False
        self._syncing_output = False
        self._last_signature = None

        # Keep the authoritative form alive as the one ReportingConfig boundary.
        # Only current v3 controls are reparented into this workspace; retired
        # telemetry-era widgets remain hidden inside the form and are normalized
        # to inert values whenever a config is loaded.
        self.form.setParent(window)
        self.form.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self._profile_box())
        layout.addWidget(self._run_details_box())
        layout.addWidget(self._always_saved_box())
        layout.addWidget(self._analysis_outputs_box())
        layout.addStretch()

        self.form.changed.connect(self._on_form_changed)
        self.window.output_root.textChanged.connect(self._source_output_changed)
        self.refresh_from_form()

    def _profile_box(self) -> QGroupBox:
        box = QGroupBox("Reporting Profile")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self.profile_selector = QComboBox()
        for key in ("CORE", "REVIEW", "DEEP_DIAGNOSTICS", "CUSTOM"):
            self.profile_selector.addItem(REPORT_PROFILE_LABELS[key], key)
        self.profile_selector.currentIndexChanged.connect(self._profile_selected)
        row.addWidget(QLabel("Profile"))
        row.addWidget(self.profile_selector, 1)
        layout.addLayout(row)

        self.cost_label = QLabel()
        self.cost_label.setWordWrap(True)
        self.cost_label.setStyleSheet(
            "background:#eef5fb; padding:9px; border:1px solid #c8d9e8"
        )
        layout.addWidget(self.cost_label)

        note = QLabel(
            "Profiles apply immediately. Trade Journey and Indicator Lifecycle are retired from the native v3 path; research now uses canonical completed-run artifacts."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#52606d")
        layout.addWidget(note)
        return box

    def _run_details_box(self) -> QGroupBox:
        box = QGroupBox("Run Details")
        form = QFormLayout(box)
        self.run_name = self.widgets["run_name"]
        self.output_dir = QLineEdit(self.window.output_root.text())
        self.output_dir.setPlaceholderText("Folder where completed run directories are saved")
        self.output_dir.textChanged.connect(self._workspace_output_changed)

        output_row = QWidget()
        row = QHBoxLayout(output_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.output_dir, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.window._browse_output)
        row.addWidget(browse)

        form.addRow("Run Name", self.run_name)
        form.addRow("Output Folder", output_row)
        return box

    @staticmethod
    def _always_saved_box() -> QGroupBox:
        box = QGroupBox("Always Saved")
        layout = QVBoxLayout(box)
        note = QLabel(
            "Canonical completed-run and provenance artifacts are always published and are not optional toggles:\n"
            "• run_manifest.json, trade_list.csv, summary.json, data_quality.json and backtest_report.xlsx\n"
            "• canonical trades, signals and feature-context Parquet artifacts\n"
            "• telemetry status artifact from the original run (typed empty when collection is not enabled)\n"
            "• source archive provenance snapshot (provenance/source_archives.parquet)\n\n"
            "These files preserve reproducibility, causal research queries and completed-run integrity regardless of the optional analysis below."
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#f7f9fb; padding:10px; border:1px solid #d9e2ec")
        layout.addWidget(note)
        return box

    def _analysis_outputs_box(self) -> QGroupBox:
        box = QGroupBox("Optional Artifact-Derived Analysis")
        layout = QVBoxLayout(box)
        controls = (
            ("create_standard_charts", "Create standard result charts"),
            ("save_indicator_analysis_reports", "Save indicator analysis reports"),
            ("save_feature_analysis_reports", "Save extended trade/exit analysis reports"),
        )
        for name, text in controls:
            widget = self.widgets[name]
            widget.setText(text)
            layout.addWidget(widget)

        note = QLabel(
            "These reports are calculated after the simulation from completed-run artifacts. They do not change entries, exits, fills, risk or cache identity."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#52606d")
        layout.addWidget(note)
        return box

    def _current_reporting(self) -> ReportingConfig:
        return self.form.value(self.window.config.reporting)

    @staticmethod
    def _signature(reporting: ReportingConfig) -> tuple:
        return tuple((name, getattr(reporting, name)) for name in REPORT_DIAGNOSTIC_FIELDS)

    def _set_profile_selector(self, profile: str) -> None:
        index = self.profile_selector.findData(profile)
        self.profile_selector.blockSignals(True)
        try:
            self.profile_selector.setCurrentIndex(index)
        finally:
            self.profile_selector.blockSignals(False)
        self.cost_label.setText(REPORT_PROFILE_COSTS[profile])

    def _profile_selected(self, _index: int) -> None:
        if self._rendering:
            return
        profile = self.profile_selector.currentData()
        if profile == "CUSTOM":
            self.cost_label.setText(REPORT_PROFILE_COSTS["CUSTOM"])
            self.refresh_review_summary()
            return
        self.apply_profile(profile)

    def apply_profile(self, profile: str) -> None:
        current = self._current_reporting()
        updated = apply_reporting_profile(current, profile)
        self._rendering = True
        try:
            self.form.set_value(updated)
        finally:
            self._rendering = False
        self._last_signature = self._signature(self._current_reporting())
        self._set_profile_selector(profile)
        self.form.changed.emit()
        self.refresh_review_summary()

    def refresh_from_form(self) -> None:
        self._rendering = True
        try:
            current = self._current_reporting()
            normalized = retire_legacy_diagnostics(current)
            if normalized != current:
                self.form.set_value(normalized)
            reporting = self._current_reporting()
            profile = matching_reporting_profile(reporting)
            self._last_signature = self._signature(reporting)
            self._set_profile_selector(profile)
            self._sync_output_from_source()
        finally:
            self._rendering = False
        self.refresh_review_summary()

    def _on_form_changed(self) -> None:
        if self._rendering:
            return
        try:
            signature = self._signature(self._current_reporting())
        except Exception:
            return
        if self._last_signature is not None and signature != self._last_signature:
            self._set_profile_selector("CUSTOM")
        self._last_signature = signature
        self.refresh_review_summary()

    def _workspace_output_changed(self, text: str) -> None:
        if self._syncing_output:
            return
        self._syncing_output = True
        try:
            self.window.output_root.setText(text)
        finally:
            self._syncing_output = False

    def _source_output_changed(self, text: str) -> None:
        if self._syncing_output:
            return
        self._syncing_output = True
        try:
            self.output_dir.setText(text)
        finally:
            self._syncing_output = False
        self.refresh_review_summary()

    def _sync_output_from_source(self) -> None:
        self._source_output_changed(self.window.output_root.text())

    def refresh_review_summary(self) -> None:
        summary = getattr(self.window, "review_summary", None)
        if summary is None:
            return
        text = summary.text()
        if not text:
            return
        profile = self.profile_selector.currentData() or "CUSTOM"
        replacement = f"Reports: {REPORT_PROFILE_LABELS[profile]}"
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("Reports:"):
                lines[index] = replacement
                summary.setText("\n".join(lines))
                break
