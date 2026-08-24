"""Minimal researcher-facing output workspace for native v3 runs.

The active GUI intentionally exposes one stable completed-run output contract.
Question-specific research is performed on demand from canonical artifacts
instead of accumulating permanent report toggles and telemetry modes.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ReportsDiagnosticsWorkspace(QWidget):
    """Run details plus an informational description of the canonical outputs."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.form = window.reporting_form
        self.widgets = self.form.widgets
        self._syncing_output = False

        # Keep the stable shell's ReportingConfig form alive as the one native
        # config boundary, but do not expose retired reporting/telemetry fields.
        self.form.setParent(window)
        self.form.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self._run_details_box())
        layout.addWidget(self._saved_outputs_box())
        layout.addWidget(self._research_model_box())
        layout.addStretch()

        self.window.output_root.textChanged.connect(self._source_output_changed)
        self.refresh_from_form()

    def _run_details_box(self) -> QGroupBox:
        box = QGroupBox("Run Details")
        form = QFormLayout(box)

        self.run_name = self.widgets["run_name"]
        self.output_dir = QLineEdit(self.window.output_root.text())
        self.output_dir.setPlaceholderText(
            "Folder where completed run directories are saved"
        )
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
    def _saved_outputs_box() -> QGroupBox:
        box = QGroupBox("Completed Run Output")
        layout = QVBoxLayout(box)
        note = QLabel(
            "Every completed run saves one clean output set — there are no report "
            "profiles, telemetry modes, or question-specific report toggles.\n\n"
            "Human review\n"
            "• backtest_report.xlsx — dashboard, monthly/yearly performance, market regime and direction × regime\n"
            "• trade_list.csv — easy-to-open completed trade list\n"
            "• summary.json — compact run statistics\n"
            "• data_quality.json — required input-data quality\n\n"
            "Research & reproducibility\n"
            "• artifacts/trades.parquet — authoritative completed trades\n"
            "• artifacts/feature_context.parquet — causal feature/research state for every strategy row\n"
            "• artifacts/signals.parquet — entered and rejected decisions with exact causal attachment\n"
            "• provenance/source_archives.parquet — exact selected Binance archive provenance\n"
            "• run_manifest.json — hashes, config, provenance, artifact catalog and completion marker"
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#f7f9fb; padding:10px; border:1px solid #d9e2ec"
        )
        layout.addWidget(note)
        return box

    @staticmethod
    def _research_model_box() -> QGroupBox:
        box = QGroupBox("On-Demand Research")
        layout = QVBoxLayout(box)
        note = QLabel(
            "DI, ADX, volatility, funding, open interest, positioning, taker flow, "
            "support/resistance and state-transition questions should be analysed "
            "from the canonical completed-run artifacts when needed. This avoids "
            "keeping fixed reports that duplicate the same data or become stale as "
            "the research questions change."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#52606d")
        layout.addWidget(note)
        return box

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

    def refresh_from_form(self) -> None:
        self._source_output_changed(self.window.output_root.text())
        self.refresh_review_summary()

    def refresh_review_summary(self) -> None:
        summary = getattr(self.window, "review_summary", None)
        if summary is None:
            return
        text = summary.text()
        if not text:
            return
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("Reports:") or line.startswith("Output:"):
                lines[index] = "Output: Canonical completed-run set"
                summary.setText("\n".join(lines))
                return
