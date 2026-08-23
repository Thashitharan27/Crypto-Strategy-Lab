"""Researcher-facing Reports & Diagnostics workspace.

Canonical run artifacts are mandatory and stay outside the user's toggle surface.
This workspace exposes only optional human review and passive diagnostics while
reusing the authoritative ReportingConfig widgets for config round-tripping.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ux_presentation import (
    REPORT_PROFILE_LABELS,
    apply_report_profile,
    detect_report_profile,
)


class CheckpointEditor(QWidget):
    """Friendly comma-separated lifecycle checkpoint editor."""

    changed = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("15, 30, 60")
        self.help = QLabel("Minutes after entry. Example: 15, 30, 60")
        self.help.setStyleSheet("color:#52606d")
        layout.addWidget(self.edit)
        layout.addWidget(self.help)
        self.edit.editingFinished.connect(self._commit)

    def set_tuple(self, values: tuple) -> None:
        self.edit.setText(", ".join(str(int(value)) for value in values))
        self._set_valid(True)

    def tuple_value(self) -> tuple[int, ...]:
        parts = [part.strip() for part in self.edit.text().split(",") if part.strip()]
        values = tuple(int(part) for part in parts)
        if not values or any(value <= 0 for value in values):
            raise ValueError("Checkpoints must contain positive minute values")
        if tuple(sorted(set(values))) != values:
            raise ValueError("Checkpoints must be unique and increasing")
        return values

    def _commit(self) -> None:
        try:
            values = self.tuple_value()
        except (TypeError, ValueError):
            self._set_valid(False)
            return
        self._set_valid(True)
        self.changed.emit(values)

    def _set_valid(self, valid: bool) -> None:
        self.edit.setStyleSheet("" if valid else "border:1px solid #c62828")
        self.help.setText(
            "Minutes after entry. Example: 15, 30, 60"
            if valid else "Use positive, increasing minutes separated by commas."
        )


class Disclosure(QWidget):
    """Small collapsible block for rarely changed diagnostic settings."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        outer.addWidget(self.toggle)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(12, 4, 0, 0)
        outer.addWidget(self.body)
        self.toggle.toggled.connect(self.body.setVisible)
        self.body.hide()


class ReportsDiagnosticsWorkspace(QWidget):
    """Friendly composition over the authoritative ReportingConfig form."""

    PROFILE_ORDER = ("CORE", "REVIEW", "DEEP_DIAGNOSTICS", "CUSTOM")

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.form = window.reporting_form
        self.widgets = self.form.widgets
        self._syncing = False

        # The DataclassForm remains the source of truth for build_config/apply_config,
        # but its raw serialization-oriented presentation is retired.
        self.form.setParent(window)
        self.form.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        profile_box = QGroupBox("Output Profile")
        profile_layout = QVBoxLayout(profile_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("What should this run produce?"))
        self.profile = QComboBox()
        for key in self.PROFILE_ORDER:
            self.profile.addItem(REPORT_PROFILE_LABELS[key], key)
        row.addWidget(self.profile, 1)
        profile_layout.addLayout(row)
        self.profile_summary = QLabel()
        self.profile_summary.setWordWrap(True)
        self.profile_summary.setStyleSheet(
            "background:#f7f9fb; padding:10px; border:1px solid #d9e2ec"
        )
        profile_layout.addWidget(self.profile_summary)
        layout.addWidget(profile_box)

        run_box = QGroupBox("Run Details")
        run_form = QFormLayout(run_box)
        run_form.addRow("Run Name", self.widgets["run_name"])
        output_note = QLabel(
            "The output folder is selected on Review & Run. The run name is optional and is stored in provenance and human reports."
        )
        output_note.setWordWrap(True)
        output_note.setStyleSheet("color:#52606d")
        run_form.addRow(output_note)
        layout.addWidget(run_box)

        required = QGroupBox("Always Saved — Canonical Run Record")
        required_layout = QVBoxLayout(required)
        required_note = QLabel(
            "These artifacts are required for reproducibility and later research, so they do not have enable switches."
        )
        required_note.setWordWrap(True)
        required_note.setStyleSheet("font-weight:bold")
        required_layout.addWidget(required_note)
        items = QLabel(
            "Summary & trade list  •  Trades Parquet  •  Full feature context  •  Signal decisions\n"
            "Data quality  •  Source/code provenance  •  Run manifest"
        )
        items.setWordWrap(True)
        items.setStyleSheet("color:#334e68; padding:6px")
        required_layout.addWidget(items)
        layout.addWidget(required)

        review = QGroupBox("Human Review")
        review_layout = QVBoxLayout(review)
        review_note = QLabel(
            "Optional presentation output. Review is the recommended everyday profile; Core skips these to finish sooner."
        )
        review_note.setWordWrap(True)
        review_note.setStyleSheet("color:#52606d")
        review_layout.addWidget(review_note)
        self._label_checkbox("create_human_workbook", "Performance workbook")
        self._label_checkbox("create_standard_charts", "Standard charts")
        review_layout.addWidget(self.widgets["create_human_workbook"])
        review_layout.addWidget(self.widgets["create_standard_charts"])
        layout.addWidget(review)

        journey = QGroupBox("Trade Journey Diagnostics · Moderate")
        journey_layout = QVBoxLayout(journey)
        self._label_checkbox("enable_trade_telemetry", "Enable Trade Journey Diagnostics")
        journey_layout.addWidget(self.widgets["enable_trade_telemetry"])
        journey_note = QLabel(
            "Captures passive within-trade observations for post-run journey analysis. It never changes entries, exits or sizing."
        )
        journey_note.setWordWrap(True)
        journey_note.setStyleSheet("color:#52606d")
        journey_layout.addWidget(journey_note)
        self.journey_body = QWidget()
        journey_form = QFormLayout(self.journey_body)
        journey_form.addRow("Sampling Interval", self.widgets["telemetry_interval_minutes"])
        self._label_checkbox("save_trade_journey_summary", "Create journey summary tables")
        self._label_checkbox("save_trade_journey_charts", "Create journey charts")
        journey_form.addRow(self.widgets["save_trade_journey_summary"])
        journey_form.addRow(self.widgets["save_trade_journey_charts"])
        self.journey_advanced = Disclosure("Advanced output")
        self._label_checkbox("save_full_telemetry_csv", "Also save raw telemetry CSV · Large output")
        self.journey_advanced.form.addRow(self.widgets["save_full_telemetry_csv"])
        journey_form.addRow(self.journey_advanced)
        journey_layout.addWidget(self.journey_body)
        layout.addWidget(journey)

        lifecycle = QGroupBox("Indicator Lifecycle Diagnostics · Moderate")
        lifecycle_layout = QVBoxLayout(lifecycle)
        self._label_checkbox(
            "enable_indicator_lifecycle_analysis", "Enable Indicator Lifecycle Diagnostics"
        )
        lifecycle_layout.addWidget(self.widgets["enable_indicator_lifecycle_analysis"])
        lifecycle_note = QLabel(
            "Analyzes how ADX, DI spread, ATR and Bollinger width develop after entry. Requires passive trade telemetry."
        )
        lifecycle_note.setWordWrap(True)
        lifecycle_note.setStyleSheet("color:#52606d")
        lifecycle_layout.addWidget(lifecycle_note)
        self.lifecycle_body = QWidget()
        lifecycle_form = QFormLayout(self.lifecycle_body)
        lifecycle_form.addRow("Lifecycle Phases", self.widgets["lifecycle_phases"])
        self.checkpoints = CheckpointEditor()
        lifecycle_form.addRow("Early Checkpoints", self.checkpoints)
        self._label_checkbox("create_lifecycle_charts", "Create lifecycle charts")
        lifecycle_form.addRow(self.widgets["create_lifecycle_charts"])
        self.lifecycle_advanced = Disclosure("Advanced analysis settings")
        self.lifecycle_advanced.form.addRow(
            "Minimum Trades Per Bucket", self.widgets["lifecycle_minimum_bucket_sample"]
        )
        self.lifecycle_advanced.form.addRow(
            "Flat Pattern Threshold", self.widgets["lifecycle_flat_pattern_threshold_pct"]
        )
        lifecycle_form.addRow(self.lifecycle_advanced)
        lifecycle_layout.addWidget(self.lifecycle_body)
        layout.addWidget(lifecycle)

        technical = QGroupBox("Additional Diagnostic Export")
        technical_layout = QVBoxLayout(technical)
        technical_note = QLabel(
            "Generate a dedicated ADX / DI / Bollinger / Mean-Reversion workbook. This is optional because the canonical feature context is already saved."
        )
        technical_note.setWordWrap(True)
        technical_note.setStyleSheet("color:#52606d")
        technical_layout.addWidget(technical_note)
        self._label_checkbox("save_indicator_analysis_reports", "Indicator analysis workbook")
        technical_layout.addWidget(self.widgets["save_indicator_analysis_reports"])
        layout.addWidget(technical)
        layout.addStretch()

        self.profile.currentIndexChanged.connect(self._profile_selected)
        self.widgets["enable_trade_telemetry"].toggled.connect(self._journey_toggled)
        self.widgets["enable_indicator_lifecycle_analysis"].toggled.connect(
            self._lifecycle_toggled
        )
        self.checkpoints.changed.connect(self._checkpoint_changed)
        self.form.changed.connect(self._authoritative_changed)
        if hasattr(window, "strategy_tf"):
            window.strategy_tf.currentIndexChanged.connect(self._strategy_timeframe_changed)
        self.refresh_from_config(window.config.reporting)

    def _label_checkbox(self, name: str, text: str) -> None:
        widget = self.widgets[name]
        if isinstance(widget, QCheckBox):
            widget.setText(text)

    def _strategy_minutes(self) -> int:
        try:
            value = self.window.strategy_tf.currentData()
        except AttributeError:
            return 15
        mapping = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        return int(mapping.get(value, 15))

    def _normalize_sampling_interval(self, reporting):
        if not (
            reporting.enable_trade_telemetry
            or reporting.enable_indicator_lifecycle_analysis
        ):
            return reporting
        strategy_minutes = self._strategy_minutes()
        interval = max(int(reporting.telemetry_interval_minutes), strategy_minutes)
        if interval % strategy_minutes:
            interval = strategy_minutes
        return replace(reporting, telemetry_interval_minutes=interval)

    def _ensure_sampling_compatible(self) -> None:
        if self._syncing:
            return
        try:
            current = self.form.value(self.window.config.reporting)
        except (TypeError, ValueError, KeyError):
            return
        normalized = self._normalize_sampling_interval(current)
        if normalized.telemetry_interval_minutes == current.telemetry_interval_minutes:
            return
        self._syncing = True
        try:
            self.widgets["telemetry_interval_minutes"].setValue(
                int(normalized.telemetry_interval_minutes)
            )
        finally:
            self._syncing = False

    def _strategy_timeframe_changed(self, _index: int) -> None:
        self._ensure_sampling_compatible()
        self._sync_profile_label()

    def _profile_selected(self, _index: int) -> None:
        if self._syncing:
            return
        profile = self.profile.currentData()
        if profile == "CUSTOM":
            return
        current = self.form.value(self.window.config.reporting)
        updated = self._normalize_sampling_interval(apply_report_profile(current, profile))
        self._syncing = True
        try:
            self.form.set_value(updated)
            self.checkpoints.set_tuple(tuple(updated.lifecycle_early_checkpoints))
        finally:
            self._syncing = False
        self.refresh_visibility()
        self._sync_profile_label()

    def _authoritative_changed(self) -> None:
        if self._syncing:
            return
        self._ensure_sampling_compatible()
        self.refresh_visibility()
        self._sync_profile_label()

    def _journey_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        if not checked:
            self._syncing = True
            try:
                for name in (
                    "save_full_telemetry_csv", "save_trade_journey_summary",
                    "save_trade_journey_charts",
                ):
                    self.widgets[name].setChecked(False)
            finally:
                self._syncing = False
        self._ensure_sampling_compatible()
        self.refresh_visibility()
        self._sync_profile_label()

    def _lifecycle_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        if not checked and self.widgets["create_lifecycle_charts"].isChecked():
            self._syncing = True
            try:
                self.widgets["create_lifecycle_charts"].setChecked(False)
            finally:
                self._syncing = False
        self._ensure_sampling_compatible()
        self.refresh_visibility()
        self._sync_profile_label()

    def _checkpoint_changed(self, values: tuple) -> None:
        hidden = self.widgets["lifecycle_early_checkpoints"]
        self._syncing = True
        try:
            hidden.set_tuple(tuple(values))
        finally:
            self._syncing = False
        self._sync_profile_label()

    def refresh_from_config(self, reporting) -> None:
        self._syncing = True
        try:
            self.checkpoints.set_tuple(tuple(reporting.lifecycle_early_checkpoints))
        finally:
            self._syncing = False
        self._ensure_sampling_compatible()
        self.refresh_visibility()
        self._sync_profile_label()

    def refresh_visibility(self, *_args) -> None:
        journey = self.widgets["enable_trade_telemetry"].isChecked()
        lifecycle = self.widgets["enable_indicator_lifecycle_analysis"].isChecked()
        self.journey_body.setVisible(journey)
        self.lifecycle_body.setVisible(lifecycle)
        # Lifecycle analysis needs the same passive telemetry capture. Communicate
        # the dependency without creating a second hidden switch.
        if lifecycle and not journey:
            self.widgets["enable_trade_telemetry"].setText(
                "Trade Journey Diagnostics off — lifecycle still captures required passive telemetry"
            )
        else:
            self.widgets["enable_trade_telemetry"].setText("Enable Trade Journey Diagnostics")

    def _sync_profile_label(self) -> None:
        try:
            reporting = self.form.value(self.window.config.reporting)
        except (TypeError, ValueError, KeyError):
            return
        profile = detect_report_profile(reporting)
        index = self.profile.findData(profile)
        self.profile.blockSignals(True)
        try:
            self.profile.setCurrentIndex(max(index, 0))
        finally:
            self.profile.blockSignals(False)
        descriptions = {
            "CORE": "Core saves the complete canonical run record and skips optional presentation/diagnostic work. Fastest output profile.",
            "REVIEW": "Review saves the canonical run record plus the performance workbook and standard charts. Recommended for normal research runs.",
            "DEEP_DIAGNOSTICS": "Deep Diagnostics also captures trade journeys, lifecycle analysis and technical diagnostic exports. Expect more runtime and disk use.",
            "CUSTOM": "Custom reflects your current mix of optional outputs. Canonical artifacts are still always saved.",
        }
        self.profile_summary.setText(descriptions[profile])
