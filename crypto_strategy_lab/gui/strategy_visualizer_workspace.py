"""Desktop Strategy Visualizer for immutable completed runs."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import webbrowser

import pandas as pd

from PySide6.QtCore import QObject, Qt, QUrl, Slot
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
    QTabWidget,
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
from crypto_strategy_lab.strategy_visualizer_browser import (
    StrategyVisualizerBrowserServer,
)

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - depends on local Qt packaging.
    QWebChannel = None
    QWebEngineSettings = None
    QWebEngineView = None


class _StrategyChartBridge(QObject):
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    @Slot(str)
    def selectCandle(self, timestamp: str) -> None:
        self.callback(timestamp)


class StrategyVisualizerWorkspace(QWidget):
    """TradingView-style read-only explorer for one completed run."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.model: CompletedRunVisualizer | None = None
        self._base_payload = None
        self._browser = None
        self._web_channel = None
        self._chart_bridge = None
        self._inspected_candle_time = None
        self._browser_server = None

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
        self.open_browser = QPushButton("Open in Browser")
        self.open_browser.clicked.connect(self._open_browser_visualizer)
        self.run_label = QLabel("No run loaded")
        self.run_label.setWordWrap(True)
        run_row.addWidget(self.load_current)
        run_row.addWidget(self.open_run)
        run_row.addWidget(self.open_browser)
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

        self.view_mode = QComboBox()
        self.view_mode.addItem("Normal", "normal")
        self.view_mode.addItem("S/R Review", "sr-review")
        self.view_mode.currentIndexChanged.connect(self._sr_review_controls_changed)

        self.sr_review_timeframe = QComboBox()
        self.sr_review_timeframe.addItem("Strategy TF", "strategy")
        self.sr_review_timeframe.addItem("1H", "1h")
        self.sr_review_timeframe.addItem("4H", "4h")
        self.sr_review_timeframe.addItem("1D", "1d")
        self.sr_review_timeframe.addItem("Compare", "compare")
        self.sr_review_timeframe.currentIndexChanged.connect(
            self._sr_review_controls_changed
        )

        self.sr_review_snapshot = QComboBox()
        self.sr_review_snapshot.addItem("Live through chart", "live")
        self.sr_review_snapshot.addItem("Entry snapshot", "entry")
        self.sr_review_snapshot.currentIndexChanged.connect(
            self._sr_review_controls_changed
        )

        self.sr_review_details = QComboBox()
        self.sr_review_details.addItem("Zones", "zones")
        self.sr_review_details.addItem("Lifecycle", "lifecycle")
        self.sr_review_details.addItem("All", "all")
        self.sr_review_details.currentIndexChanged.connect(
            self._sr_review_controls_changed
        )

        grid.addWidget(QLabel("View"), 3, 0)
        grid.addWidget(self.view_mode, 3, 1)
        grid.addWidget(QLabel("S/R TF"), 3, 2)
        grid.addWidget(self.sr_review_timeframe, 3, 3)
        grid.addWidget(QLabel("Snapshot"), 3, 4)
        grid.addWidget(self.sr_review_snapshot, 3, 5)
        grid.addWidget(QLabel("Details"), 3, 6)
        grid.addWidget(self.sr_review_details, 3, 7, 1, 2)
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

        inspector = QGroupBox("Inspector")
        inspector_layout = QVBoxLayout(inspector)
        self.inspector_tabs = QTabWidget()

        trade_tab = QWidget()
        trade_layout = QVBoxLayout(trade_tab)
        trade_layout.setContentsMargins(0, 0, 0, 0)
        self.trade_table = QTableWidget(0, 2)
        self.trade_table.setHorizontalHeaderLabels(("Field", "Value"))
        self.trade_table.verticalHeader().setVisible(False)
        self.trade_table.horizontalHeader().setStretchLastSection(True)
        self.trade_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trade_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        trade_layout.addWidget(self.trade_table)
        self.inspector_tabs.addTab(trade_tab, "Trade")

        rules_tab = QWidget()
        rules_layout = QVBoxLayout(rules_tab)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_summary = QLabel(
            "Click a decision candle to inspect exact ENTRY / VETO / FLIP conditions."
        )
        self.rule_summary.setWordWrap(True)
        self.rule_summary.setStyleSheet("color:#52606d")
        rules_layout.addWidget(self.rule_summary)
        self.rule_table = QTableWidget(0, 8)
        self.rule_table.setHorizontalHeaderLabels(
            ("Type", "Group", "Group Result", "Evidence", "TF", "Actual", "Required", "Condition")
        )
        self.rule_table.verticalHeader().setVisible(False)
        self.rule_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rule_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        rules_layout.addWidget(self.rule_table, 1)
        self.inspector_tabs.addTab(rules_tab, "Strategy Inspector")

        sr_tab = QWidget()
        sr_layout = QVBoxLayout(sr_tab)
        sr_layout.setContentsMargins(0, 0, 0, 0)
        self.sr_summary = QLabel(
            "Click a candle to inspect the exact persisted S/R context."
        )
        self.sr_summary.setWordWrap(True)
        self.sr_summary.setStyleSheet("color:#52606d")
        sr_layout.addWidget(self.sr_summary)
        self.sr_table = QTableWidget(0, 3)
        self.sr_table.setHorizontalHeaderLabels(("TF", "Field", "Value"))
        self.sr_table.verticalHeader().setVisible(False)
        self.sr_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sr_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sr_table.horizontalHeader().setStretchLastSection(True)
        sr_layout.addWidget(self.sr_table, 2)
        self.sr_zone_label = QLabel("Active zone inventory")
        self.sr_zone_label.setStyleSheet("font-weight:600;color:#52606d")
        sr_layout.addWidget(self.sr_zone_label)
        self.sr_zone_table = QTableWidget(0, 7)
        self.sr_zone_table.setHorizontalHeaderLabels(
            ("TF", "Type", "Zone", "State", "Tests", "Sources", "Nearest")
        )
        self.sr_zone_table.verticalHeader().setVisible(False)
        self.sr_zone_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.sr_zone_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.sr_zone_table.horizontalHeader().setStretchLastSection(True)
        sr_layout.addWidget(self.sr_zone_table, 2)
        self.inspector_tabs.addTab(sr_tab, "S/R Inspector")

        inspector_layout.addWidget(self.inspector_tabs)
        note = QLabel(
            "Rule values are captured at decision time by the production engine. "
            "Older completed runs without rule_trace.parquet are not reconstructed."
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
        self._update_sr_review_controls()
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
        self.open_browser.setEnabled(self.model is not None)

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if QWebEngineView is None:
            raise RuntimeError(
                "Qt WebEngine is unavailable. Reinstall the project PySide6 requirements "
                "to enable Strategy Visualizer."
            )
        browser = QWebEngineView(self.chart_holder)
        if QWebChannel is not None:
            self._web_channel = QWebChannel(browser.page())
            self._chart_bridge = _StrategyChartBridge(
                self._candle_selected_from_chart, browser
            )
            self._web_channel.registerObject("strategyBridge", self._chart_bridge)
            browser.page().setWebChannel(self._web_channel)
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
        self._stop_browser_visualizer()
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

    def _stop_browser_visualizer(self):
        server = self._browser_server
        self._browser_server = None
        if server is not None:
            server.stop()

    def _open_browser_visualizer(self):
        if self.model is None:
            return
        try:
            if self._browser_server is None:
                self._browser_server = StrategyVisualizerBrowserServer(self.model)
            url = self._browser_server.start()
            opened = webbrowser.open(url, new=2)
            self.status.setText(
                "Browser Strategy Visualizer opened on local loopback. "
                "The desktop visualizer remains available as a fallback."
                if opened
                else f"Browser visualizer is ready at {url}"
            )
        except Exception as exc:
            self.status.setText(f"Could not open browser visualizer: {exc}")
            QMessageBox.critical(self, "Strategy Visualizer", str(exc))

    def closeEvent(self, event):
        self._stop_browser_visualizer()
        super().closeEvent(event)

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

    def _update_sr_review_controls(self):
        review = self.view_mode.currentData() == "sr-review"
        for control in (
            self.sr_review_timeframe,
            self.sr_review_snapshot,
            self.sr_review_details,
        ):
            control.setEnabled(review)
        for key, check in self.overlay_checks.items():
            check.setEnabled(not review)
            check.setToolTip(
                "S/R Review uses the View / S/R TF / Snapshot / Details controls below."
                if review
                else "Normal-view chart overlay."
            )

    def _sr_review_controls_changed(self, *_args):
        self._update_sr_review_controls()
        if self._inspected_candle_time is not None and self.model is not None:
            self._populate_sr_inspector(
                self.model.sr_inspector_at(self._inspected_candle_time)
            )
        self._render_chart()

    def _selected_sr_timeframes(self):
        if self.view_mode.currentData() == "sr-review":
            selected = str(self.sr_review_timeframe.currentData() or "strategy")
            return {"strategy", "1h", "4h", "1d"} if selected == "compare" else {selected}
        return {
            key.removeprefix("sr-")
            for key, check in self.overlay_checks.items()
            if key.startswith("sr-") and check.isChecked()
        }

    def _show_selected_trade_sr(self):
        if self.model is None:
            self._populate_sr_inspector(None)
            return
        timestamp = self.model.selected_trade_candle_time(
            self._current_trade_index()
        )
        if timestamp is None:
            self._populate_sr_inspector(
                {
                    "status": "NOT_AVAILABLE",
                    "message": "Selected trade has no persisted signal-candle timestamp.",
                    "timeframes": [],
                }
            )
            return
        self._inspected_candle_time = timestamp
        self._populate_sr_inspector(self.model.sr_inspector_at(timestamp))

    @staticmethod
    def _sr_zone_text(low, high):
        if low is None or high is None:
            return "—"
        return f"{float(low):,.2f} – {float(high):,.2f}"

    @staticmethod
    def _sr_value_text(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, float):
            return f"{value:,.4g}"
        return str(value)

    def _populate_sr_inspector(self, snapshot):
        snapshot = snapshot or {
            "status": "NOT_AVAILABLE",
            "message": "No S/R candle selected.",
            "timeframes": [],
        }
        available = list(snapshot.get("timeframes") or ())
        selected = self._selected_sr_timeframes()
        blocks = [
            item
            for item in available
            if str(item.get("key") or "") in selected
        ]
        rows = []
        for item in blocks:
            tf = str(item.get("timeframe") or "")
            rows.extend(
                [
                    (tf, "Support zone", self._sr_zone_text(item.get("supportZoneLow"), item.get("supportZoneHigh"))),
                    (tf, "Support state", item.get("supportState")),
                    (tf, "Support distance · native ATR", item.get("supportDistanceNativeAtr")),
                    (tf, "Support distance · strategy ATR", item.get("supportDistanceStrategyAtr")),
                    (tf, "Support near / inside", f"{'Yes' if item.get('supportNear') else 'No'} / {'Yes' if item.get('supportInside') else 'No'}"),
                    (tf, "Support tests / rejection", f"{self._sr_value_text(item.get('supportTests'))} / {self._sr_value_text(item.get('supportRejectionAtr'))} ATR"),
                    (tf, "Support bars since test", item.get("supportBarsSinceTest")),
                    (tf, "Support pivot / last break", f"{self._sr_value_text(item.get('supportPivotIndex'))} / {self._sr_value_text(item.get('supportLastBreakIndex'))}"),
                    (tf, "Last broken support zone", self._sr_zone_text(item.get("supportBrokenZoneLow"), item.get("supportBrokenZoneHigh"))),
                    (tf, "Resistance zone", self._sr_zone_text(item.get("resistanceZoneLow"), item.get("resistanceZoneHigh"))),
                    (tf, "Resistance state", item.get("resistanceState")),
                    (tf, "Resistance distance · native ATR", item.get("resistanceDistanceNativeAtr")),
                    (tf, "Resistance distance · strategy ATR", item.get("resistanceDistanceStrategyAtr")),
                    (tf, "Resistance near / inside", f"{'Yes' if item.get('resistanceNear') else 'No'} / {'Yes' if item.get('resistanceInside') else 'No'}"),
                    (tf, "Resistance tests / rejection", f"{self._sr_value_text(item.get('resistanceTests'))} / {self._sr_value_text(item.get('resistanceRejectionAtr'))} ATR"),
                    (tf, "Resistance bars since test", item.get("resistanceBarsSinceTest")),
                    (tf, "Resistance pivot / last break", f"{self._sr_value_text(item.get('resistancePivotIndex'))} / {self._sr_value_text(item.get('resistanceLastBreakIndex'))}"),
                    (tf, "Last broken resistance zone", self._sr_zone_text(item.get("resistanceBrokenZoneLow"), item.get("resistanceBrokenZoneHigh"))),
                    (tf, "Room LONG / SHORT · native ATR", f"{self._sr_value_text(item.get('roomLongNativeAtr'))} / {self._sr_value_text(item.get('roomShortNativeAtr'))}"),
                    (tf, "Structure conflict", item.get("structureConflict")),
                    (tf, "Confirmation", item.get("confirmationRating")),
                    (tf, "S/R completed candle", item.get("completedCandleTime")),
                ]
            )

        self.sr_table.setRowCount(len(rows))
        for row_number, (tf, field, value) in enumerate(rows):
            for column, raw in enumerate((tf, field, self._sr_value_text(value))):
                self.sr_table.setItem(
                    row_number, column, QTableWidgetItem(str(raw))
                )
        self.sr_table.resizeColumnsToContents()
        self.sr_table.horizontalHeader().setStretchLastSection(True)

        zone_items = [
            item
            for item in list(snapshot.get("zones") or ())
            if str(item.get("key") or "") in selected
        ]
        self.sr_zone_table.setRowCount(len(zone_items))
        for row_number, item in enumerate(zone_items):
            zone_text = self._sr_zone_text(
                item.get("zoneLow"), item.get("zoneHigh")
            )
            values = (
                item.get("timeframe", ""),
                item.get("structure", ""),
                zone_text,
                item.get("state", ""),
                self._sr_value_text(item.get("testCount")),
                self._sr_value_text(item.get("sourceCount")),
                "YES" if item.get("nearest") else "",
            )
            for column, value in enumerate(values):
                self.sr_zone_table.setItem(
                    row_number, column, QTableWidgetItem(str(value))
                )
        self.sr_zone_table.resizeColumnsToContents()
        self.sr_zone_table.horizontalHeader().setStretchLastSection(True)
        inventory_available = bool(snapshot.get("zoneInventoryAvailable"))
        self.sr_zone_label.setText(
            f"Active zone inventory · {len(zone_items)} zone(s)"
            if inventory_available
            else "Active zone inventory · unavailable for this legacy run"
        )

        status = str(snapshot.get("status") or "")
        if status == "AVAILABLE":
            suffix = (
                " · Compare"
                if self.sr_review_timeframe.currentData() == "compare"
                and self.view_mode.currentData() == "sr-review"
                else ""
            )
            inventory_note = (
                f" · {len(zone_items)} active zone(s)"
                if inventory_available
                else " · nearest-zone context only"
            )
            self.sr_summary.setText(
                f"{snapshot.get('timestamp', '')}{suffix} · "
                f"{len(blocks)} persisted S/R context(s){inventory_note}"
            )
        else:
            self.sr_summary.setText(str(snapshot.get("message") or status))

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
            self._show_selected_trade_rule_trace()
            self._show_selected_trade_sr()
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
            inventory_available = bool(
                (self._base_payload.get("run") or {}).get(
                    "srZoneInventoryAvailable"
                )
            )
            inventory_note = (
                "Full active S/R zone inventory is available. "
                if inventory_available
                else (
                    "Legacy S/R artifact: this run stores nearest-zone history only; "
                    "rerun it to capture the full active-zone inventory. "
                )
            )
            self.status.setText(
                f"Showing {count:,} canonical strategy candles. " + provenance
                + inventory_note
                + "S/R, VWAP and Bollinger values come from persisted causal artifacts; "
                "EMA lines are display-only overlays."
            )
        except Exception as exc:
            self.status.setText(f"Could not render chart: {exc}")
            QMessageBox.critical(self, "Strategy Visualizer", str(exc))

    def _show_selected_trade_rule_trace(self):
        if self.model is None:
            self._populate_rule_inspector(None)
            return
        timestamp = self.model.selected_trade_candle_time(
            self._current_trade_index()
        )
        if timestamp is None:
            self._populate_rule_inspector(
                {
                    "status": "NOT_EVALUATED",
                    "message": "Selected trade has no persisted signal-candle timestamp.",
                    "rows": [],
                }
            )
            return
        self._populate_rule_inspector(self.model.rule_inspector_at(timestamp))

    def _candle_selected_from_chart(self, timestamp):
        if self.model is None:
            return
        try:
            seconds = int(float(timestamp))
            value = pd.Timestamp(seconds, unit="s", tz="UTC")
            self._inspected_candle_time = value
            self._populate_rule_inspector(self.model.rule_inspector_at(value))
            self._populate_sr_inspector(self.model.sr_inspector_at(value))
            self.inspector_tabs.setCurrentIndex(
                2 if self.view_mode.currentData() == "sr-review" else 1
            )
        except Exception as exc:
            self.rule_summary.setText(f"Could not inspect candle: {exc}")
            self.sr_summary.setText(f"Could not inspect S/R: {exc}")

    def _populate_rule_inspector(self, trace):
        trace = trace or {
            "status": "NOT_EVALUATED",
            "message": "No rule trace selected.",
            "rows": [],
        }
        rows = list(trace.get("rows") or ())
        self.rule_table.setRowCount(len(rows))
        for row_number, item in enumerate(rows):
            values = (
                item.get("type", ""),
                item.get("group", ""),
                item.get("groupStatus", ""),
                item.get("evidence", ""),
                item.get("timeframe", ""),
                item.get("actual", ""),
                item.get("requirement", ""),
                item.get("conditionStatus", ""),
            )
            for column, value in enumerate(values):
                self.rule_table.setItem(
                    row_number, column, QTableWidgetItem(str(value))
                )
        self.rule_table.resizeColumnsToContents()
        self.rule_table.horizontalHeader().setStretchLastSection(True)

        status = str(trace.get("status") or "")
        if status == "AVAILABLE":
            outcome = "PASSED" if trace.get("filterPassed") else "REJECTED"
            self.rule_summary.setText(
                f"{trace.get('timestamp', '')} · {trace.get('regime', '')} "
                f"{trace.get('side', '')} · {trace.get('profile', '')} · "
                f"{outcome}\n{trace.get('filterReason', '')}"
            )
        else:
            self.rule_summary.setText(str(trace.get("message") or status))

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
            review = self.view_mode.currentData() == "sr-review"
            selected_timeframes = self._selected_sr_timeframes()

            if review:
                payload["overlays"] = []
                # Trade price lines can force the candle scale far away from the
                # local structure. The trade inspector still shows the exact
                # entry/stop/target values while S/R Review keeps price local.
                payload["priceLines"] = []
            else:
                payload["overlays"] = [
                    overlay
                    for overlay in payload.get("overlays", ())
                    if self._overlay_enabled(overlay)
                ]

            payload["srZones"] = [
                zone
                for zone in payload.get("srZones", ())
                if zone.get("timeframe") in selected_timeframes
            ]
            details = (
                str(self.sr_review_details.currentData() or "zones")
                if review
                else "zones"
            )
            if review and details == "lifecycle":
                payload["srZones"] = []
            payload["srEvents"] = [
                event
                for event in payload.get("srEvents", ())
                if review
                and details in {"lifecycle", "all"}
                and event.get("timeframe") in selected_timeframes
            ]
            payload["srReview"] = {
                "mode": "review" if review else "normal",
                "snapshot": (
                    str(self.sr_review_snapshot.currentData() or "live")
                    if review
                    else "live"
                ),
                "details": details,
                "timeframes": sorted(selected_timeframes),
                "tradeLevelsHiddenForScale": bool(review),
            }
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
