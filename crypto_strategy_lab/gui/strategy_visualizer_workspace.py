"""Desktop Strategy Visualizer for immutable completed runs."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.strategy_visualizer import (
    CompletedRunVisualizer,
    DEFAULT_VISIBLE_CANDLES,
    MAX_VISIBLE_CANDLES,
    MIN_VISIBLE_CANDLES,
    build_visualizer_html,
)

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - depends on local Qt packaging.
    QWebEngineSettings = None
    QWebEngineView = None


class StrategyVisualizerWorkspace(QWidget):
    """TradingView-style read-only explorer for one completed run."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.model: CompletedRunVisualizer | None = None
        self._base_payload = None
        self._browser = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        intro = QLabel(
            "Explore the exact completed-run candles, entries, exits and causal "
            "research evidence. This view never re-runs or changes the strategy."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#52606d")
        outer.addWidget(intro)

        run_row = QHBoxLayout()
        self.load_current = QPushButton("Load Current Run")
        self.load_current.clicked.connect(self.load_current_run)
        self.open_run = QPushButton("Open Completed Run…")
        self.open_run.clicked.connect(self.open_completed_run)
        self.run_label = QLabel("No run loaded")
        self.run_label.setWordWrap(True)
        run_row.addWidget(self.load_current)
        run_row.addWidget(self.open_run)
        run_row.addWidget(self.run_label, 1)
        outer.addLayout(run_row)

        controls = QGroupBox("Chart Controls")
        grid = QGridLayout(controls)
        self.previous_trade = QPushButton("◀ Previous")
        self.previous_trade.clicked.connect(lambda: self._step_trade(-1))
        self.trade_selector = QComboBox()
        self.trade_selector.setMinimumWidth(360)
        self.trade_selector.currentIndexChanged.connect(self._trade_changed)
        self.next_trade = QPushButton("Next ▶")
        self.next_trade.clicked.connect(lambda: self._step_trade(1))
        self.visible_candles = QSpinBox()
        self.visible_candles.setRange(MIN_VISIBLE_CANDLES, MAX_VISIBLE_CANDLES)
        self.visible_candles.setValue(DEFAULT_VISIBLE_CANDLES)
        self.visible_candles.setSuffix(" candles")
        self.visible_candles.editingFinished.connect(self._reload_payload)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._reload_payload)

        grid.addWidget(QLabel("Trade"), 0, 0)
        grid.addWidget(self.previous_trade, 0, 1)
        grid.addWidget(self.trade_selector, 0, 2, 1, 3)
        grid.addWidget(self.next_trade, 0, 5)
        grid.addWidget(QLabel("Window"), 0, 6)
        grid.addWidget(self.visible_candles, 0, 7)
        grid.addWidget(self.refresh_button, 0, 8)

        self.overlay_checks = {}
        overlay_specs = (
            ("ema50", "EMA 50", True),
            ("ema100", "EMA 100", True),
            ("ema200", "EMA 200", True),
            ("vwap", "VWAP", True),
            ("bb", "Bollinger Bands", False),
            ("sr-strategy", "S/R Strategy TF", False),
            ("sr-1h", "S/R 1H", False),
            ("sr-4h", "S/R 4H", True),
            ("sr-1d", "S/R 1D", False),
        )
        for column, (key, label, checked) in enumerate(overlay_specs):
            check = QCheckBox(label)
            check.setChecked(checked)
            check.toggled.connect(self._render_chart)
            self.overlay_checks[key] = check
            grid.addWidget(check, 1 + column // 5, column % 5)

        self.show_rejections = QCheckBox("Rejected signals")
        self.show_rejections.setToolTip(
            "Show decision-point rejections from signals.parquet. These can be dense."
        )
        self.show_rejections.toggled.connect(self._reload_payload)
        grid.addWidget(self.show_rejections, 2, 5, 1, 2)
        grid.setColumnStretch(2, 1)
        outer.addWidget(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.chart_holder = QWidget()
        chart_layout = QVBoxLayout(self.chart_holder)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_placeholder = QLabel(
            "Load a completed run to open the interactive chart."
        )
        self.chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_placeholder.setMinimumHeight(520)
        self.chart_placeholder.setStyleSheet(
            "background:#0f1720;color:#b8c2cc;border:1px solid #334155"
        )
        chart_layout.addWidget(self.chart_placeholder)
        splitter.addWidget(self.chart_holder)

        inspector = QGroupBox("Selected Trade")
        inspector_layout = QVBoxLayout(inspector)
        self.trade_table = QTableWidget(0, 2)
        self.trade_table.setHorizontalHeaderLabels(("Field", "Value"))
        self.trade_table.verticalHeader().setVisible(False)
        self.trade_table.horizontalHeader().setStretchLastSection(True)
        self.trade_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trade_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        inspector_layout.addWidget(self.trade_table)
        note = QLabel(
            "Click a candle on the chart for OHLC plus the causal evidence snapshot "
            "available at that candle. Rule-by-rule ENTRY/VETO/FLIP pass/fail is Phase 2."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#52606d")
        inspector_layout.addWidget(note)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#52606d")
        outer.addWidget(self.status)

        self._set_navigation_enabled(False)
        self.refresh_available_run()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_available_run()

    def refresh_available_run(self):
        available = bool(
            getattr(self.window, "_manifest", None)
            and getattr(self.window, "_run_dir", None)
        )
        self.load_current.setEnabled(available)
        if available and self.model is None:
            self.status.setText("A completed run is available. Click Load Current Run.")

    def _set_navigation_enabled(self, enabled: bool):
        self.previous_trade.setEnabled(enabled)
        self.trade_selector.setEnabled(enabled)
        self.next_trade.setEnabled(enabled)
        self.visible_candles.setEnabled(enabled or self.model is not None)
        self.refresh_button.setEnabled(self.model is not None)

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if QWebEngineView is None:
            raise RuntimeError(
                "Qt WebEngine is unavailable. Reinstall the project PySide6 requirements "
                "to enable Strategy Visualizer."
            )
        browser = QWebEngineView(self.chart_holder)
        if QWebEngineSettings is not None:
            try:
                browser.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                    True,
                )
            except (AttributeError, RuntimeError):
                pass
        layout = self.chart_holder.layout()
        layout.removeWidget(self.chart_placeholder)
        self.chart_placeholder.hide()
        layout.addWidget(browser)
        self._browser = browser
        return browser

    def load_current_run(self):
        manifest = getattr(self.window, "_manifest", None)
        run_dir = getattr(self.window, "_run_dir", None)
        if not manifest or not run_dir:
            QMessageBox.information(
                self, "Strategy Visualizer", "There is no completed run loaded."
            )
            return
        self._load_model(Path(run_dir), manifest)

    def open_completed_run(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Completed Run",
            str(getattr(self.window, "_run_dir", "") or ""),
            "Run Manifest (run_manifest.json)",
        )
        if not path:
            return
        selected = Path(path)
        if selected.name.lower() != "run_manifest.json":
            QMessageBox.warning(
                self, "Strategy Visualizer", "Select a completed run_manifest.json file."
            )
            return
        self._load_model(selected.parent, None)

    def _load_model(self, run_dir: Path, manifest):
        self.status.setText("Loading completed-run artifacts…")
        try:
            self.model = CompletedRunVisualizer.load(
                self.window.service, run_dir, manifest
            )
            self._populate_trade_selector()
            request = self.model.seed.request
            self.run_label.setText(
                f"{request.symbol} · {request.strategy_timeframe} · "
                f"{self.model.trade_count:,} completed trades"
            )
            self._set_navigation_enabled(self.model.trade_count > 0)
            self.visible_candles.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self._reload_payload()
        except Exception as exc:
            self.model = None
            self._base_payload = None
            self._set_navigation_enabled(False)
            self.status.setText(f"Could not load run: {exc}")
            QMessageBox.critical(self, "Strategy Visualizer", str(exc))

    def _populate_trade_selector(self):
        self.trade_selector.blockSignals(True)
        try:
            self.trade_selector.clear()
            if self.model is None:
                return
            if not self.model.trade_count:
                self.trade_selector.addItem("No completed trades", None)
                return
            for index in range(self.model.trade_count):
                self.trade_selector.addItem(self.model.trade_label(index), index)
            self.trade_selector.setCurrentIndex(0)
        finally:
            self.trade_selector.blockSignals(False)

    def _current_trade_index(self):
        if self.model is None or not self.model.trade_count:
            return None
        value = self.trade_selector.currentData()
        return int(value) if value is not None else 0

    def _step_trade(self, offset: int):
        if self.model is None or not self.model.trade_count:
            return
        target = max(
            0,
            min(
                self.trade_selector.count() - 1,
                self.trade_selector.currentIndex() + int(offset),
            ),
        )
        self.trade_selector.setCurrentIndex(target)

    def _trade_changed(self, _index):
        self._reload_payload()

    def _reload_payload(self, *_args):
        if self.model is None:
            return
        self.status.setText("Loading chart window…")
        try:
            self._base_payload = self.model.build_payload(
                trade_index=self._current_trade_index(),
                visible_candles=self.visible_candles.value(),
                show_rejections=self.show_rejections.isChecked(),
            )
            self._populate_trade_inspector(
                self._base_payload.get("selectedTrade") or {}
            )
            self._render_chart()
            count = len(self._base_payload.get("candles") or ())
            verified = (self._base_payload.get("run") or {}).get("sourceVerified")
            provenance = (
                "Candle source provenance matches the completed run. "
                if verified is True
                else "Legacy run: candle source provenance could not be independently verified. "
                if verified is None
                else ""
            )
            self.status.setText(
                f"Showing {count:,} canonical strategy candles. " + provenance
                + "S/R, VWAP and Bollinger values come from the run's causal feature context; "
                "EMA lines are display-only overlays."
            )
        except Exception as exc:
            self.status.setText(f"Could not render chart: {exc}")
            QMessageBox.critical(self, "Strategy Visualizer", str(exc))

    def _overlay_enabled(self, overlay):
        kind = overlay.get("kind")
        if kind == "ema":
            return self.overlay_checks[f"ema{overlay.get('period')}"].isChecked()
        if kind == "vwap":
            return self.overlay_checks["vwap"].isChecked()
        if kind == "bb":
            return self.overlay_checks["bb"].isChecked()
        if kind == "sr":
            key = f"sr-{overlay.get('timeframe')}"
            check = self.overlay_checks.get(key)
            return bool(check and check.isChecked())
        return True

    def _render_chart(self, *_args):
        if not self._base_payload:
            return
        try:
            browser = self._ensure_browser()
            payload = deepcopy(self._base_payload)
            payload["overlays"] = [
                overlay
                for overlay in payload.get("overlays", ())
                if self._overlay_enabled(overlay)
            ]
            browser.setHtml(
                build_visualizer_html(payload),
                QUrl("https://cdn.jsdelivr.net/"),
            )
        except Exception as exc:
            self.status.setText(f"Chart unavailable: {exc}")

    def _populate_trade_inspector(self, summary):
        items = list(summary.items())
        self.trade_table.setRowCount(len(items))
        for row, (key, value) in enumerate(items):
            if isinstance(value, float):
                text = f"{value:,.6g}"
            else:
                text = str(value)
            self.trade_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.trade_table.setItem(row, 1, QTableWidgetItem(text))
        self.trade_table.resizeColumnsToContents()
        self.trade_table.horizontalHeader().setStretchLastSection(True)
