"""Researcher-facing Reports & Diagnostics workspace for the native v3 GUI.

The workspace is deliberately presentation-only.  It reuses the authoritative
ReportingConfig widgets owned by the stable GUI shell, so changing report
profiles cannot alter data, strategy, feature, or execution semantics.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.data_lake_config import ReportingConfig


REPORT_PROFILE_VALUES = {
    "CORE": {
        "analysis_level": "QUICK",
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
        "save_feature_analysis_reports": False,
        "save_indicator_analysis_reports": False,
        "create_standard_charts": False,
    },
    "REVIEW": {
        "analysis_level": "STANDARD",
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
        "save_feature_analysis_reports": False,
        "save_indicator_analysis_reports": True,
        "create_standard_charts": True,
    },
    "DEEP_DIAGNOSTICS": {
        "analysis_level": "DEEP",
        "enable_trade_telemetry": True,
        "save_full_telemetry_csv": True,
        "save_trade_journey_summary": True,
        "save_trade_journey_charts": True,
        "telemetry_interval_minutes": 15,
        "enable_indicator_lifecycle_analysis": True,
        "lifecycle_phases": 4,
        "lifecycle_early_checkpoints": (15, 30, 60),
        "lifecycle_minimum_bucket_sample": 20,
        "create_lifecycle_charts": True,
        "lifecycle_flat_pattern_threshold_pct": 5.0,
        "save_feature_analysis_reports": True,
        "save_indicator_analysis_reports": True,
        "create_standard_charts": True,
    },
}

REPORT_PROFILE_LABELS = {
    "CORE": "Core",
    "REVIEW": "Review — Recommended",
    "DEEP_DIAGNOSTICS": "Deep Diagnostics",
    "CUSTOM": "Custom",
}

REPORT_PROFILE_COSTS = {
    "CORE": "Fastest — canonical run artifacts only; optional diagnostic reports are off.",
    "REVIEW": "Normal — recommended charts and indicator review without heavy journey telemetry.",
    "DEEP_DIAGNOSTICS": "Slower — journey telemetry, lifecycle analysis, raw telemetry and extra reports.",
    "CUSTOM": "Custom — run time and output size depend on the diagnostics selected below.",
}

REPORT_DIAGNOSTIC_FIELDS = tuple(REPORT_PROFILE_VALUES["REVIEW"])


def apply_reporting_profile(reporting: ReportingConfig, profile: str) -> ReportingConfig:
    """Apply one deterministic presentation profile while preserving run details."""
    if profile not in REPORT_PROFILE_VALUES:
        raise ValueError(f"Unknown reporting profile: {profile}")
    return replace(reporting, **REPORT_PROFILE_VALUES[profile])


def matching_reporting_profile(reporting: ReportingConfig) -> str:
    """Return the exact profile represented by a config, otherwise CUSTOM."""
    for profile, values in REPORT_PROFILE_VALUES.items():
        if all(getattr(reporting, name) == value for name, value in values.items()):
            return profile
    return "CUSTOM"


class CheckpointEditor(QWidget):
    """Friendly ordered minute controls replacing the raw JSON tuple editor."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[int] = []
        self.spin_boxes: list[QSpinBox] = []
        self._rendering = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chips = QHBoxLayout()
        layout.addLayout(self.chips)
        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Add checkpoint")
        self.add_button.clicked.connect(self.add_checkpoint)
        actions.addWidget(self.add_button)
        actions.addStretch()
        layout.addLayout(actions)

    def values(self) -> tuple[int, ...]:
        return tuple(self._values)

    def set_values(self, values: Iterable[int]) -> None:
        self._rendering = True
        try:
            self._values = [int(value) for value in values]
            self._rebuild()
        finally:
            self._rendering = False

    def add_checkpoint(self) -> None:
        value = (self._values[-1] + 15) if self._values else 15
        self._values.append(value)
        self._rebuild()
        if not self._rendering:
            self.changed.emit()

    def _remove_checkpoint(self, index: int) -> None:
        if not 0 <= index < len(self._values):
            return
        self._values.pop(index)
        self._rebuild()
        if not self._rendering:
            self.changed.emit()

    def _update_checkpoint(self, index: int, value: int) -> None:
        if not 0 <= index < len(self._values):
            return
        self._values[index] = int(value)
        if not self._rendering:
            self.changed.emit()

    def _clear_row(self) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_row()
        self.spin_boxes = []
        for index, value in enumerate(self._values):
            chip = QWidget()
            row = QHBoxLayout(chip)
            row.setContentsMargins(3, 0, 3, 0)
            spin = QSpinBox()
            spin.setRange(0, 2_000_000_000)
            spin.setSuffix(" min")
            spin.setValue(value)
            spin.setToolTip("Minutes after entry for this early lifecycle checkpoint.")
            remove = QPushButton("×")
            remove.setFixedWidth(28)
            remove.setToolTip("Remove checkpoint")
            spin.valueChanged.connect(
                lambda new_value, item=index: self._update_checkpoint(item, new_value)
            )
            remove.clicked.connect(
                lambda _checked=False, item=index: self._remove_checkpoint(item)
            )
            row.addWidget(spin)
            row.addWidget(remove)
            self.spin_boxes.append(spin)
            self.chips.addWidget(chip)
        self.chips.addStretch()


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

        # The stable shell's ReportingConfig form must remain alive because its
        # value()/set_value() methods are still the single native config boundary.
        # Reparent every widget that is not shown directly so replacing the old
        # page cannot destroy an authoritative field.
        self.form.setParent(window)
        self.form.hide()
        self.widgets["analysis_level"].setParent(self)
        self.widgets["analysis_level"].hide()
        self.widgets["lifecycle_early_checkpoints"].setParent(self)
        self.widgets["lifecycle_early_checkpoints"].hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self._profile_box())
        layout.addWidget(self._run_details_box())
        layout.addWidget(self._always_saved_box())
        layout.addWidget(self._analysis_outputs_box())
        layout.addWidget(self._trade_journey_box())
        layout.addWidget(self._lifecycle_box())
        layout.addStretch()

        self.form.changed.connect(self._on_form_changed)
        self.checkpoint_editor.changed.connect(self._checkpoint_changed)
        self.window.output_root.textChanged.connect(self._source_output_changed)

        self._connect_dependencies()
        self.refresh_from_form()

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------
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
            "Profiles apply immediately. Changing a diagnostic setting switches the profile to Custom."
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
            "• canonical trades, signals, feature-context and telemetry Parquet artifacts\n"
            "• source archive provenance snapshot (provenance/source_archives.parquet)\n\n"
            "These files preserve reproducibility, research queries and completed-run integrity regardless of the profile below."
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#f7f9fb; padding:10px; border:1px solid #d9e2ec")
        layout.addWidget(note)
        return box

    def _analysis_outputs_box(self) -> QGroupBox:
        box = QGroupBox("Analysis Outputs")
        layout = QVBoxLayout(box)
        controls = (
            ("create_standard_charts", "Create standard result charts"),
            ("save_indicator_analysis_reports", "Save indicator analysis reports"),
            ("save_feature_analysis_reports", "Save extended feature analysis reports"),
        )
        for name, text in controls:
            widget = self.widgets[name]
            widget.setText(text)
            layout.addWidget(widget)
        return box

    def _trade_journey_box(self) -> QGroupBox:
        box = QGroupBox("Trade Journey Diagnostics")
        layout = QVBoxLayout(box)
        intro = QLabel(
            "Inspect what happened after entry. Journey summaries and charts automatically enable the telemetry they require."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#52606d")
        layout.addWidget(intro)

        self.telemetry_enabled = self.widgets["enable_trade_telemetry"]
        self.journey_summary = self.widgets["save_trade_journey_summary"]
        self.journey_charts = self.widgets["save_trade_journey_charts"]
        self.telemetry_interval = self.widgets["telemetry_interval_minutes"]
        self.raw_telemetry = self.widgets["save_full_telemetry_csv"]
        self.telemetry_enabled.setText("Capture trade journey telemetry")
        self.journey_summary.setText("Save trade journey summary")
        self.journey_charts.setText("Create trade journey charts")
        self.raw_telemetry.setText("Save full raw telemetry CSV — large output")
        layout.addWidget(self.telemetry_enabled)
        layout.addWidget(self.journey_summary)
        layout.addWidget(self.journey_charts)

        interval_form = QFormLayout()
        interval_form.addRow("Telemetry Interval (minutes)", self.telemetry_interval)
        layout.addLayout(interval_form)

        self.show_journey_advanced = QCheckBox("Show Advanced")
        layout.addWidget(self.show_journey_advanced)
        self.journey_advanced = QGroupBox("Advanced Trade Journey Output")
        advanced = QVBoxLayout(self.journey_advanced)
        raw_note = QLabel(
            "Raw telemetry can be substantially larger than the canonical telemetry artifact. Enable it only for detailed debugging or external analysis."
        )
        raw_note.setWordWrap(True)
        raw_note.setStyleSheet("color:#52606d")
        advanced.addWidget(raw_note)
        advanced.addWidget(self.raw_telemetry)
        self.journey_advanced.setVisible(False)
        self.show_journey_advanced.toggled.connect(self.journey_advanced.setVisible)
        layout.addWidget(self.journey_advanced)
        return box

    def _lifecycle_box(self) -> QGroupBox:
        box = QGroupBox("Indicator Lifecycle Diagnostics")
        layout = QVBoxLayout(box)
        intro = QLabel(
            "Track how indicator evidence evolves from entry through the trade. Lifecycle charts automatically enable lifecycle analysis."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#52606d")
        layout.addWidget(intro)

        self.lifecycle_enabled = self.widgets["enable_indicator_lifecycle_analysis"]
        self.lifecycle_charts = self.widgets["create_lifecycle_charts"]
        self.lifecycle_phases = self.widgets["lifecycle_phases"]
        self.lifecycle_minimum_sample = self.widgets["lifecycle_minimum_bucket_sample"]
        self.lifecycle_flat_threshold = self.widgets["lifecycle_flat_pattern_threshold_pct"]
        self.lifecycle_enabled.setText("Enable indicator lifecycle analysis")
        self.lifecycle_charts.setText("Create lifecycle charts")
        layout.addWidget(self.lifecycle_enabled)
        layout.addWidget(self.lifecycle_charts)

        form = QFormLayout()
        form.addRow("Lifecycle Phases", self.lifecycle_phases)
        self.checkpoint_editor = CheckpointEditor()
        checkpoint_container = QWidget()
        checkpoint_layout = QVBoxLayout(checkpoint_container)
        checkpoint_layout.setContentsMargins(0, 0, 0, 0)
        checkpoint_note = QLabel("Early checkpoints after entry")
        checkpoint_note.setStyleSheet("color:#52606d")
        checkpoint_layout.addWidget(checkpoint_note)
        checkpoint_layout.addWidget(self.checkpoint_editor)
        form.addRow("Early Checkpoints", checkpoint_container)
        layout.addLayout(form)

        self.show_lifecycle_advanced = QCheckBox("Show Advanced")
        layout.addWidget(self.show_lifecycle_advanced)
        self.lifecycle_advanced = QGroupBox("Advanced Lifecycle Thresholds")
        advanced = QFormLayout(self.lifecycle_advanced)
        advanced.addRow("Minimum Bucket Sample", self.lifecycle_minimum_sample)
        advanced.addRow("Flat-pattern Threshold (%)", self.lifecycle_flat_threshold)
        self.lifecycle_advanced.setVisible(False)
        self.show_lifecycle_advanced.toggled.connect(self.lifecycle_advanced.setVisible)
        layout.addWidget(self.lifecycle_advanced)
        return box

    # ------------------------------------------------------------------
    # Profiles and native config synchronization
    # ------------------------------------------------------------------
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
            self._sync_checkpoints_from_native()
            self._refresh_enabled_state()
        finally:
            self._rendering = False
        self._last_signature = self._signature(self._current_reporting())
        self._set_profile_selector(profile)
        # DataclassForm.set_value may have emitted while rendering; emit once at
        # the end so the existing summary/config observers see the final profile.
        self.form.changed.emit()
        self.refresh_review_summary()

    def refresh_from_form(self) -> None:
        self._rendering = True
        try:
            self._sync_checkpoints_from_native()
            self._normalize_loaded_dependencies()
            reporting = self._current_reporting()
            profile = matching_reporting_profile(reporting)
            self._last_signature = self._signature(reporting)
            self._set_profile_selector(profile)
            self._sync_output_from_source()
            self._refresh_enabled_state()
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
        self._refresh_enabled_state()
        self.refresh_review_summary()

    # ------------------------------------------------------------------
    # Friendly checkpoint bridge
    # ------------------------------------------------------------------
    def _sync_checkpoints_from_native(self) -> None:
        native = self.widgets["lifecycle_early_checkpoints"]
        self.checkpoint_editor.set_values(native.tuple_value())

    def _checkpoint_changed(self) -> None:
        native = self.widgets["lifecycle_early_checkpoints"]
        native.blockSignals(True)
        try:
            native.set_tuple(self.checkpoint_editor.values())
        finally:
            native.blockSignals(False)
        self.form.changed.emit()

    # ------------------------------------------------------------------
    # Automatic dependencies and visibility
    # ------------------------------------------------------------------
    def _connect_dependencies(self) -> None:
        for widget in (self.journey_summary, self.journey_charts, self.raw_telemetry):
            widget.toggled.connect(self._journey_output_toggled)
        self.telemetry_enabled.toggled.connect(self._telemetry_toggled)
        self.lifecycle_charts.toggled.connect(self._lifecycle_chart_toggled)
        self.lifecycle_enabled.toggled.connect(self._lifecycle_toggled)

    def _journey_output_toggled(self, checked: bool) -> None:
        if self._rendering:
            return
        if checked and not self.telemetry_enabled.isChecked():
            self.telemetry_enabled.setChecked(True)
        self._refresh_enabled_state()

    def _telemetry_toggled(self, checked: bool) -> None:
        if self._rendering:
            return
        if not checked:
            for dependent in (self.journey_summary, self.journey_charts, self.raw_telemetry):
                if dependent.isChecked():
                    dependent.setChecked(False)
        self._refresh_enabled_state()

    def _lifecycle_chart_toggled(self, checked: bool) -> None:
        if self._rendering:
            return
        if checked and not self.lifecycle_enabled.isChecked():
            self.lifecycle_enabled.setChecked(True)
        self._refresh_enabled_state()

    def _lifecycle_toggled(self, checked: bool) -> None:
        if self._rendering:
            return
        if not checked and self.lifecycle_charts.isChecked():
            self.lifecycle_charts.setChecked(False)
        self._refresh_enabled_state()

    def _normalize_loaded_dependencies(self) -> None:
        if any(widget.isChecked() for widget in (
            self.journey_summary, self.journey_charts, self.raw_telemetry
        )) and not self.telemetry_enabled.isChecked():
            self.telemetry_enabled.setChecked(True)
        if self.lifecycle_charts.isChecked() and not self.lifecycle_enabled.isChecked():
            self.lifecycle_enabled.setChecked(True)

    def _refresh_enabled_state(self) -> None:
        telemetry = self.telemetry_enabled.isChecked()
        self.telemetry_interval.setEnabled(telemetry)
        lifecycle = self.lifecycle_enabled.isChecked()
        self.lifecycle_phases.setEnabled(lifecycle)
        self.checkpoint_editor.setEnabled(lifecycle)
        self.lifecycle_minimum_sample.setEnabled(lifecycle)
        self.lifecycle_flat_threshold.setEnabled(lifecycle)

    # ------------------------------------------------------------------
    # Run detail bridge and review summary
    # ------------------------------------------------------------------
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
        found = False
        for index, line in enumerate(lines):
            if line.startswith("Reports:"):
                lines[index] = replacement
                found = True
                break
        if found:
            summary.setText("\n".join(lines))
