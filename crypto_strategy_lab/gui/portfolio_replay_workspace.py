"""Human-facing portfolio replay workspace for completed resilience runs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.portfolio_replay import (
    discover_resilience_runs,
    run_portfolio_replay,
)


class PortfolioReplayWorkspace(QWidget):
    """Select finalized Every Viable Entry runs and replay one shared account."""

    COLUMNS = (
        "Use",
        "Symbol",
        "Timeframe",
        "Candidates",
        "Completed",
        "Run folder",
    )

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.host_window = window
        self._runs: list[dict] = []
        self._last_run_dir: Path | None = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Build a realistic shared-account portfolio directly from finalized "
            "Every Viable Entry — resilience outputs. The strategy and indicators are "
            "not rerun: resilience rows are treated as candidate opportunities, then "
            "portfolio occupancy and risk limits are reapplied chronologically."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        source_box = QGroupBox("1. Finalized Every Viable Entry runs")
        source_layout = QVBoxLayout(source_box)
        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh completed runs")
        self.latest_button = QPushButton("Select latest per symbol")
        self.clear_button = QPushButton("Clear selection")
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.latest_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addStretch()
        source_layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        source_layout.addWidget(self.table, 1)
        self.source_note = QLabel()
        self.source_note.setWordWrap(True)
        source_layout.addWidget(self.source_note)
        layout.addWidget(source_box, 2)

        policy_box = QGroupBox("2. Shared portfolio policy")
        policy_form = QFormLayout(policy_box)
        self.initial_equity = QDoubleSpinBox()
        self.initial_equity.setRange(1.0, 1_000_000_000.0)
        self.initial_equity.setDecimals(2)
        self.initial_equity.setPrefix("$")
        configured_equity = getattr(
            getattr(getattr(window, "config", None), "execution", None),
            "initial_equity",
            1000.0,
        )
        self.initial_equity.setValue(float(configured_equity))

        self.risk_per_trade = QDoubleSpinBox()
        self.risk_per_trade.setRange(0.01, 100.0)
        self.risk_per_trade.setDecimals(2)
        self.risk_per_trade.setSuffix("%")
        self.risk_per_trade.setValue(1.0)

        self.maximum_total_risk = QDoubleSpinBox()
        self.maximum_total_risk.setRange(0.01, 100.0)
        self.maximum_total_risk.setDecimals(2)
        self.maximum_total_risk.setSuffix("%")
        self.maximum_total_risk.setValue(5.0)

        self.maximum_open_positions = QSpinBox()
        self.maximum_open_positions.setRange(1, 100)
        self.maximum_open_positions.setValue(5)

        self.one_active_per_symbol = QCheckBox(
            "Allow only one accepted open trade per symbol"
        )
        self.one_active_per_symbol.setChecked(True)
        self.common_period_only = QCheckBox(
            "Use only the common overlapping date range across selected runs"
        )
        self.common_period_only.setChecked(True)

        policy_form.addRow("Initial equity", self.initial_equity)
        policy_form.addRow("Risk per accepted trade", self.risk_per_trade)
        policy_form.addRow("Maximum total portfolio risk", self.maximum_total_risk)
        policy_form.addRow("Maximum simultaneous positions", self.maximum_open_positions)
        policy_form.addRow("Symbol occupancy", self.one_active_per_symbol)
        policy_form.addRow("Replay period", self.common_period_only)
        layout.addWidget(policy_box)

        policy_note = QLabel(
            "When several assets have candidates at the exact same timestamp and capacity is "
            "limited, the replay uses Symbol A→Z as a deterministic priority. Exits at a "
            "timestamp are processed before new entries at that same timestamp."
        )
        policy_note.setWordWrap(True)
        policy_note.setStyleSheet("color:#52606d")
        layout.addWidget(policy_note)

        actions = QHBoxLayout()
        self.run_button = QPushButton("Run Portfolio Replay")
        self.open_folder_button = QPushButton("Open Portfolio Output")
        self.open_folder_button.setEnabled(False)
        actions.addWidget(self.run_button)
        actions.addWidget(self.open_folder_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(150)
        layout.addWidget(self.summary)

        self.refresh_button.clicked.connect(self.refresh_runs)
        self.latest_button.clicked.connect(self.select_latest_per_symbol)
        self.clear_button.clicked.connect(self.clear_selection)
        self.run_button.clicked.connect(self.run_replay)
        self.open_folder_button.clicked.connect(self.open_last_output)

        self.refresh_runs()

    def _output_root(self) -> Path:
        widget = getattr(self.host_window, "output_root", None)
        text = widget.text().strip() if widget is not None and hasattr(widget, "text") else ""
        if text:
            return Path(text)
        reporting = getattr(getattr(self.host_window, "config", None), "reporting", None)
        return Path(getattr(reporting, "output_dir", "output/data_lake_v2"))

    def refresh_runs(self):
        selected = set(self.selected_run_dirs())
        root = self._output_root()
        self._runs = discover_resilience_runs(root)
        self.table.setRowCount(len(self._runs))
        for row, metadata in enumerate(self._runs):
            use = QTableWidgetItem()
            use.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            use.setCheckState(
                Qt.CheckState.Checked
                if Path(metadata["run_dir"]) in selected
                else Qt.CheckState.Unchecked
            )
            use.setData(Qt.ItemDataRole.UserRole, str(metadata["run_dir"]))
            self.table.setItem(row, 0, use)
            values = (
                metadata["symbol"],
                str(metadata.get("strategy_timeframe") or "—"),
                f"{metadata.get('candidate_rows', 0):,}",
                str(metadata.get("completed_at") or "—"),
                str(metadata["run_dir"]),
            )
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        if self._runs:
            self.source_note.setText(
                f"Found {len(self._runs)} hash-validated Every Viable Entry run(s) in {root}. "
                "Select one finalized run per symbol."
            )
        else:
            self.source_note.setText(
                f"No completed Every Viable Entry resilience runs were found in {root}."
            )

    def selected_run_dirs(self) -> list[Path]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    result.append(Path(value))
        return result

    def select_latest_per_symbol(self):
        seen = set()
        for row, metadata in enumerate(self._runs):
            item = self.table.item(row, 0)
            if item is None:
                continue
            symbol = metadata["symbol"]
            checked = symbol not in seen
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            seen.add(symbol)

    def clear_selection(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)

    def run_replay(self):
        selected = self.selected_run_dirs()
        if len(selected) < 2:
            QMessageBox.warning(
                self,
                "Portfolio Replay",
                "Select at least two finalized Every Viable Entry runs.",
            )
            return
        if self.risk_per_trade.value() > self.maximum_total_risk.value():
            QMessageBox.warning(
                self,
                "Portfolio Replay",
                "Risk per accepted trade cannot exceed maximum total portfolio risk.",
            )
            return

        self.run_button.setEnabled(False)
        self.status.setText("Replaying candidate opportunities against one shared account…")
        try:
            summary, _candidates, _realized, run_dir = run_portfolio_replay(
                selected,
                output_root=self._output_root(),
                initial_equity=self.initial_equity.value(),
                risk_per_trade=self.risk_per_trade.value() / 100.0,
                maximum_total_risk=self.maximum_total_risk.value() / 100.0,
                maximum_open_positions=self.maximum_open_positions.value(),
                one_active_trade_per_symbol=self.one_active_per_symbol.isChecked(),
                common_period_only=self.common_period_only.isChecked(),
            )
        except Exception as exc:
            self.status.setText(f"Portfolio replay failed: {exc}")
            QMessageBox.critical(self, "Portfolio Replay Failed", str(exc))
            return
        finally:
            self.run_button.setEnabled(True)

        self._last_run_dir = Path(run_dir)
        self.open_folder_button.setEnabled(True)
        self.status.setText(f"Portfolio replay saved to {run_dir}")
        blocked = summary.get("blocked_by_reason", {})
        blocked_text = ", ".join(
            f"{name}: {count}" for name, count in blocked.items()
        ) or "None"
        self.summary.setPlainText(
            "Portfolio Replay Complete\n"
            f"Assets: {', '.join(summary['portfolio_assets'])}\n"
            f"Replay period: {summary['replay_period_start']} → {summary['replay_period_end']}\n"
            f"Candidates in scope: {summary['candidate_rows_in_scope']:,}\n"
            f"Accepted trades: {summary['accepted_trades']:,}\n"
            f"Blocked candidates: {summary['blocked_candidates']:,}\n"
            f"Blocked by: {blocked_text}\n"
            f"Ending equity: ${summary['ending_equity']:,.2f}\n"
            f"Total return: {summary['total_return_percentage']:.2f}%\n"
            f"Closed-equity max drawdown: {summary['closed_equity_maximum_drawdown_percentage']:.2f}%\n"
            f"Maximum simultaneous positions observed: {summary['maximum_observed_open_positions']}\n"
            f"Maximum observed open risk: {summary['maximum_observed_open_risk_fraction'] * 100.0:.2f}%\n\n"
            "Mark-to-market drawdown is not claimed from resilience endpoints alone."
        )

    def open_last_output(self):
        if self._last_run_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_run_dir)))
