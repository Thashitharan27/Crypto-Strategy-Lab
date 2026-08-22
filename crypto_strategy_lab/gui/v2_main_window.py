"""Composition-based Task-18 desktop GUI for native v2 research runs."""
from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtCore import QObject, QDate, QSettings, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from crypto_strategy_lab.data import MarketKind
from crypto_strategy_lab.data_lake_config import (
    ExecutionConfig, ExecutionProfileConfig, FeatureConfig, PROFILE_KEYS,
    ResearchRunConfig, StrategyConfig, StrategyProfileConfig,
)
from crypto_strategy_lab.paths import CACHE_DIR, MARKET_DATA_ROOT, OUTPUT_DIR
from .chatgpt_connection import ChatGPTIntegrationWidget
from .github_manager import GitHubIntegrationWidget
from .v2_controller import GuiApplicationService, GuiResearchRequest


TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def timeframe_minutes(value: str) -> int:
    try:
        return TIMEFRAME_MINUTES[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported native timeframe: {value}") from exc


def timeframe_label(minutes: int) -> str:
    reverse = {value: key for key, value in TIMEFRAME_MINUTES.items()}
    try:
        return reverse[int(minutes)]
    except KeyError as exc:
        raise ValueError(f"Unsupported native timeframe minutes: {minutes}") from exc


class TupleEditor(QPlainTextEdit):
    """Structured JSON tuple editor preserving rule objects and their order."""

    def set_tuple(self, value: tuple) -> None:
        self.setPlainText(json.dumps(list(value), indent=2))

    def tuple_value(self) -> tuple:
        value = json.loads(self.toPlainText() or "[]")
        if not isinstance(value, list):
            raise ValueError("Tuple fields must be represented by a JSON array")
        return tuple(value)


class DataclassForm(QWidget):
    """Lossless editor for every scalar/tuple field of one native dataclass."""

    CHOICES = {
        "strategy_profile_run_mode": ("COMBINED_SHARED_CAPITAL", "ISOLATED_PROFILES", "BOTH"),
        "entry_mode": ("WAIT_UNTIL_CLOSED", "EVERY_N_CANDLES"),
        "sr_filter_mode": ("ANALYSIS_ONLY", "APPLY_ENTRY_RULES"),
        "daily_entry_missed_policy": ("SKIP_DAY", "NEXT_AVAILABLE_CANDLE"),
        "market_regime_method": ("BTC_STRUCTURAL", "ASSET_STRUCTURAL", "ASSET_RETURN"),
        "trade_flow_source": ("AGG_TRADES", "TRADES"),
        "sr_break_basis": ("CLOSE", "WICK"),
        "mean_reversion_mean_type": ("SMA", "EMA"),
        "risk_mode": ("ATR", "FIXED", "PERCENT"),
        "tie_policy": ("PESSIMISTIC", "OPTIMISTIC", "INTRABAR"),
        "sr_take_profit_mode": ("FIXED_R", "SR_CAPPED_R"),
        "sr_take_profit_no_level_policy": ("USE_FIXED_TP", "REJECT_TRADE"),
        "flip_rule_match_mode": ("ANY", "ALL"),
        "reject_rule_match_mode": ("ANY", "ALL"),
    }
    OPTIONAL_NUMERIC = {"large_trade_quote_threshold": float,
                        "max_effective_leverage_per_leg": float,
                        "max_combined_effective_leverage": float}

    def __init__(self, value, *, excluded=(), parent=None):
        super().__init__(parent); self.cls = type(value); self.widgets: dict[str, QWidget] = {}
        form = QFormLayout(self)
        for item in fields(value):
            if item.name in excluded:
                continue
            widget = self._widget(item.name, getattr(value, item.name))
            self.widgets[item.name] = widget
            form.addRow(item.name.replace("_", " ").title(), widget)
        self.set_value(value)

    def _widget(self, name: str, value: Any) -> QWidget:
        if name in self.CHOICES:
            widget = QComboBox(); widget.addItems(self.CHOICES[name]); return widget
        if isinstance(value, bool): return QCheckBox()
        if isinstance(value, int):
            widget = QSpinBox(); widget.setRange(-2_000_000_000, 2_000_000_000); return widget
        if isinstance(value, float):
            widget = QDoubleSpinBox(); widget.setRange(-1e12, 1e12); widget.setDecimals(8); return widget
        if isinstance(value, tuple): return TupleEditor()
        return QLineEdit()

    def set_value(self, value) -> None:
        for name, widget in self.widgets.items():
            raw = getattr(value, name)
            if isinstance(widget, QCheckBox): widget.setChecked(raw)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): widget.setValue(raw)
            elif isinstance(widget, QComboBox):
                if widget.findText(str(raw)) < 0: widget.addItem(str(raw))
                widget.setCurrentText(str(raw))
            elif isinstance(widget, TupleEditor): widget.set_tuple(tuple(raw))
            else: widget.setText("" if raw is None else str(raw))

    def value(self, base=None):
        base = base or self.cls(); values = {}
        for name, widget in self.widgets.items():
            old = getattr(base, name)
            if isinstance(widget, QCheckBox): raw = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): raw = widget.value()
            elif isinstance(widget, QComboBox): raw = widget.currentText()
            elif isinstance(widget, TupleEditor): raw = widget.tuple_value()
            else:
                text = widget.text()
                if old is None and not text: raw = None
                elif isinstance(old, (int, float)): raw = type(old)(text)
                elif name in self.OPTIONAL_NUMERIC: raw = self.OPTIONAL_NUMERIC[name](text)
                else: raw = text
            values[name] = raw
        return replace(base, **values)


class NativeProfileEditor(QWidget):
    """Losslessly edits all native strategy and execution profile fields."""

    def __init__(self, parent=None):
        super().__init__(parent); layout = QVBoxLayout(self)
        self.selector = QComboBox(); self.selector.addItems(PROFILE_KEYS); layout.addWidget(self.selector)
        tabs = QTabWidget(); layout.addWidget(tabs)
        self.strategy_form = DataclassForm(StrategyProfileConfig(), excluded={"entry_rules"})
        strategy_page = QWidget(); strategy_layout = QVBoxLayout(strategy_page)
        strategy_layout.addWidget(self.strategy_form); strategy_layout.addWidget(QLabel("Entry Rules (structured JSON array)"))
        self.entry_rules = TupleEditor(); strategy_layout.addWidget(self.entry_rules)
        self.execution_form = DataclassForm(ExecutionProfileConfig())
        tabs.addTab(strategy_page, "Strategy Profile"); tabs.addTab(self.execution_form, "Execution Profile")
        self._strategy = {}; self._execution = {}; self._current = PROFILE_KEYS[0]
        self.selector.currentTextChanged.connect(self._select)

    def _store(self) -> None:
        if not self._strategy: return
        key = self._current
        strategy = self.strategy_form.value(self._strategy[key])
        self._strategy[key] = replace(strategy, entry_rules=self.entry_rules.tuple_value())
        self._execution[key] = self.execution_form.value(self._execution[key])

    def _render(self, key: str) -> None:
        self._current = key; self.strategy_form.set_value(self._strategy[key])
        self.entry_rules.set_tuple(tuple(self._strategy[key].entry_rules))
        self.execution_form.set_value(self._execution[key])

    def _select(self, key: str) -> None:
        self._store(); self._render(key)

    def set_profiles(self, strategy, execution) -> None:
        # Block the selector signal so stale widgets can never overwrite incoming profiles.
        self.selector.blockSignals(True)
        try:
            self._strategy, self._execution = dict(strategy), dict(execution)
            self._render(self.selector.currentText() or PROFILE_KEYS[0])
        finally:
            self.selector.blockSignals(False)

    def profiles(self):
        self._store(); return dict(self._strategy), dict(self._execution)


class RunWorker(QObject):
    finished = Signal(object); failed = Signal(str)
    def __init__(self, service, request, config):
        super().__init__(); self.service = service; self.request = request; self.config = config
    @Slot()
    def run(self):
        try: self.finished.emit(self.service.run(self.request, self.config))
        except Exception as exc: self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """The single authoritative GUI, inheriting directly from QMainWindow."""

    def __init__(self, startup_status=None, service=None):
        super().__init__(); self.setWindowTitle("Crypto Strategy Lab v2"); self.resize(1400, 900)
        self.service = service or GuiApplicationService(MARKET_DATA_ROOT, CACHE_DIR)
        self.config = ResearchRunConfig(); self._manifest = None; self._run_dir = None; self._thread = None
        tabs = QTabWidget(); self.setCentralWidget(tabs)
        research = QWidget(); grid = QGridLayout(research); tabs.addTab(research, "Research Run")
        grid.addWidget(self._data_panel(), 0, 0); grid.addWidget(self._config_tabs(), 0, 1)
        grid.addWidget(self._run_panel(), 1, 0, 1, 2); grid.addWidget(self._status_panel(), 2, 0)
        grid.addWidget(self._results_panel(), 2, 1)
        tabs.addTab(ChatGPTIntegrationWidget(QSettings("CryptoStrategyLab", "CryptoStrategyLab"),
                                             lambda: self.output_root.text()), "ChatGPT / MCP")
        tabs.addTab(GitHubIntegrationWidget(), "GitHub")
        self._connect_request_refresh(); self.service.refresh_catalog(); self._load_catalog(); self.apply_config(self.config)
        if startup_status: startup_status("Native v2 research GUI ready")

    @staticmethod
    def _scroll(widget):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(widget); return scroll

    def _data_panel(self):
        box = QGroupBox("Data / Request"); form = QFormLayout(box)
        self.exchange = QComboBox(); self.exchange.addItem("Binance", "binance")
        self.market = QComboBox(); self.market.addItem("USD-M Futures", MarketKind.FUTURES_UM)
        self.symbol = QComboBox(); self.symbol.setEditable(True)
        self.start = QDateEdit(QDate(2024, 1, 1)); self.start.setCalendarPopup(True)
        self.end = QDateEdit(QDate.currentDate()); self.end.setCalendarPopup(True)
        self.strategy_tf = QComboBox(); self.strategy_tf.addItems(TIMEFRAME_MINUTES)
        self.intrabar_tf = QComboBox(); self.intrabar_tf.addItems(["None", *TIMEFRAME_MINUTES])
        self.datasets = QLabel("Catalog not loaded")
        for label, widget in (("Exchange", self.exchange), ("Market", self.market), ("Symbol", self.symbol),
            ("Period Start", self.start), ("Period End (exclusive)", self.end), ("Strategy TF", self.strategy_tf),
            ("Intrabar TF", self.intrabar_tf), ("Available Datasets", self.datasets)): form.addRow(label, widget)
        return box

    def _config_tabs(self):
        tabs = QTabWidget(); self.profile_editor = NativeProfileEditor()
        self.strategy_form = DataclassForm(StrategyConfig(), excluded={"profiles"})
        self.feature_form = DataclassForm(FeatureConfig())
        self.execution_form = DataclassForm(ExecutionConfig(), excluded={"profiles"})
        tabs.addTab(self._scroll(self.profile_editor), "Profiles")
        tabs.addTab(self._scroll(self.strategy_form), "Strategy")
        tabs.addTab(self._scroll(self.feature_form), "Research Features")
        tabs.addTab(self._scroll(self.execution_form), "Execution")
        return tabs

    def _run_panel(self):
        box = QGroupBox("Run"); layout = QHBoxLayout(box)
        self.output_root = QLineEdit(str(OUTPUT_DIR / "data_lake_v2")); browse = QPushButton("Output Root…")
        browse.clicked.connect(self._browse_output); self.save = QPushButton("Save Config…"); self.load = QPushButton("Load Config…")
        self.run_button = QPushButton("Run"); self.progress = QProgressBar(); self.stage = QLabel("Ready")
        self.save.clicked.connect(self.save_config); self.load.clicked.connect(self.load_config); self.run_button.clicked.connect(self.start_run)
        for widget in (QLabel("Output root"), self.output_root, browse, self.save, self.load,
                       self.run_button, self.progress, self.stage): layout.addWidget(widget)
        return box

    def _status_panel(self):
        box = QGroupBox("Data Status"); layout = QVBoxLayout(box)
        self.resolution = QLabel("Requested/effective resolution: not run")
        self.coverage = QTableWidget(0, 6); self.coverage.setHorizontalHeaderLabels(
            ["Dataset", "Interval", "First UTC", "Last UTC", "Partitions", "State"])
        self.quality = QLabel("Data quality: not run")
        self.quality_table = QTableWidget(0, 6); self.quality_table.setHorizontalHeaderLabels(
            ["Dataset", "Interval", "Required", "Rows", "Status", "Issues"])
        for widget in (self.resolution, self.coverage, self.quality, self.quality_table): layout.addWidget(widget)
        return box

    def _results_panel(self):
        box = QGroupBox("Results / Canonical Artifacts"); layout = QVBoxLayout(box)
        self.summary = QLabel("No completed run"); layout.addWidget(self.summary); self.artifact_buttons = {}
        for key in ("workbook", "trade_csv", "summary", "trades", "signals", "feature_context", "telemetry", "data_quality"):
            button = QPushButton(key.replace("_", " ").title()); button.setEnabled(False)
            button.clicked.connect(lambda _=False, name=key: self.open_artifact(name))
            self.artifact_buttons[key] = button; layout.addWidget(button)
        self.open_folder = QPushButton("Output Folder"); self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._run_dir))))
        layout.addWidget(self.open_folder); return box

    def _connect_request_refresh(self):
        self.symbol.currentTextChanged.connect(self.refresh_coverage)
        self.exchange.currentIndexChanged.connect(self.refresh_coverage); self.market.currentIndexChanged.connect(self.refresh_coverage)
        self.start.dateChanged.connect(self.refresh_coverage); self.end.dateChanged.connect(self.refresh_coverage)
        self.strategy_tf.currentTextChanged.connect(self.refresh_coverage); self.intrabar_tf.currentTextChanged.connect(self.refresh_coverage)

    def request_model(self):
        def utc(widget): return pd.Timestamp(widget.date().toPython(), tz="UTC").to_pydatetime()
        intrabar = None if self.intrabar_tf.currentText() == "None" else self.intrabar_tf.currentText()
        return GuiResearchRequest(self.exchange.currentData(), self.market.currentData(), self.symbol.currentText(),
                                  utc(self.start), utc(self.end), self.strategy_tf.currentText(), intrabar)

    def build_config(self):
        strategy_profiles, execution_profiles = self.profile_editor.profiles()
        intrabar = self.request_model().intrabar_timeframe
        data = replace(self.config.data, strategy_timeframe_minutes=timeframe_minutes(self.strategy_tf.currentText()),
            use_intrabar_data=intrabar is not None,
            intrabar_timeframe_minutes=timeframe_minutes(intrabar) if intrabar else self.config.data.intrabar_timeframe_minutes)
        strategy = replace(self.strategy_form.value(self.config.strategy), profiles=strategy_profiles)
        execution = replace(self.execution_form.value(self.config.execution), profiles=execution_profiles)
        return replace(self.config, data=data, features=self.feature_form.value(self.config.features),
                       strategy=strategy, execution=execution,
                       reporting=replace(self.config.reporting, output_dir=self.output_root.text()))

    def apply_config(self, config):
        self.config = config; data = config.data
        self.strategy_tf.setCurrentText(timeframe_label(data.strategy_timeframe_minutes))
        self.intrabar_tf.setCurrentText(timeframe_label(data.intrabar_timeframe_minutes) if data.use_intrabar_data else "None")
        self.profile_editor.set_profiles(config.strategy.profiles, config.execution.profiles)
        self.strategy_form.set_value(config.strategy); self.feature_form.set_value(config.features)
        self.execution_form.set_value(config.execution); self.output_root.setText(config.reporting.output_dir)

    def _load_catalog(self):
        current = self.symbol.currentText(); symbols = self.service.catalog.symbols()
        self.symbol.blockSignals(True); self.symbol.clear(); self.symbol.addItems(symbols or [current or "BTCUSDT"])
        if current: self.symbol.setCurrentText(current)
        self.symbol.blockSignals(False); self.refresh_coverage()

    def refresh_coverage(self):
        if not self.symbol.currentText() or self.start.date() >= self.end.date(): return
        rows = self.service.catalog.coverage(self.request_model()); self.coverage.setRowCount(len(rows))
        self.datasets.setText(", ".join(sorted({row["dataset"] for row in rows})) or "UNAVAILABLE")
        for row_number, row in enumerate(rows):
            values = (row["dataset"], row["interval"] or "—", row["first_period"] or "—",
                      row["last_period"] or "—", row["archive_count"], row["state"])
            for column, value in enumerate(values): self.coverage.setItem(row_number, column, QTableWidgetItem(str(value)))

    def start_run(self):
        try: request, config = self.request_model(), self.build_config(); config.validate()
        except Exception as exc: QMessageBox.warning(self, "Invalid research request", str(exc)); return
        self.run_button.setEnabled(False); self.progress.setRange(0, 0); self.stage.setText("Native research executing")
        self._thread = QThread(self); self._worker = RunWorker(self.service, request, config); self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run); self._worker.finished.connect(self._finished); self._worker.failed.connect(self._failed)
        self._worker.finished.connect(self._thread.quit); self._worker.failed.connect(self._thread.quit); self._thread.start()

    def _finished(self, result):
        self.run_button.setEnabled(True); self.progress.setRange(0, 100); self.progress.setValue(100); self.stage.setText("COMPLETED")
        self._run_dir = Path(result.output_dir); self._manifest, summary = self.service.completed_runs.read(self._run_dir)
        self.summary.setText("\n".join(f"{key}: {summary.get(key, '—')}" for key in (
            "ending_equity", "net_pnl", "total_return_percentage", "total_trades", "wins", "losses",
            "win_rate", "total_net_r", "average_net_r", "profit_factor", "maximum_drawdown_percentage", "total_fees")))
        self.render_resolution(self._manifest)
        self.render_data_quality(result.data_quality); self.open_folder.setEnabled(True)
        for key, button in self.artifact_buttons.items(): button.setEnabled(key in self._manifest.get("artifacts", {}))

    def render_data_quality(self, report):
        if report is None:
            self.quality.setText("Data quality: NOT AVAILABLE"); self.quality_table.setRowCount(0); return
        self.quality.setText("Data quality: " + report.overall_status.value)
        self.quality_table.setRowCount(len(report.datasets))
        for row, dataset in enumerate(report.datasets):
            values = (dataset.dataset, dataset.interval or "event", dataset.required, dataset.row_count,
                      dataset.status.value, "; ".join(issue.code for issue in dataset.issues) or "—")
            for column, value in enumerate(values): self.quality_table.setItem(row, column, QTableWidgetItem(str(value)))

    def render_resolution(self, manifest):
        request = manifest["request"]
        requested = request.get("requested_intrabar_interval") or "none"
        effective = request.get("effective_intrabar_interval") or "none"
        fallback = "FALLBACK" if requested != effective else "AS REQUESTED"
        self.resolution.setText(f"Requested: {requested} | Effective: {effective} | {fallback}")

    def _failed(self, message):
        self.run_button.setEnabled(True); self.progress.setRange(0, 100); self.stage.setText("FAILED: " + message)
    def open_artifact(self, key):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.completed_runs.artifact_path(self._run_dir, self._manifest, key))))
    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Output root", self.output_root.text())
        if path: self.output_root.setText(path)
    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save native v3 config", "research-v3.json", "JSON (*.json)")
        if path: self.service.save_config(Path(path), self.build_config())
    def load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load native v3 config", "", "JSON (*.json)")
        if path: self.apply_config(self.service.load_config(Path(path)))
    def start_post_show_tasks(self): pass