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
    QSpinBox, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from crypto_strategy_lab.data import MarketKind
from crypto_strategy_lab.data_lake_config import (
    ExecutionConfig, ExecutionProfileConfig, FeatureConfig, PROFILE_KEYS,
    ReportingConfig, ResearchRunConfig, StrategyConfig, StrategyProfileConfig,
)
from crypto_strategy_lab.paths import CACHE_DIR, MARKET_DATA_ROOT, OUTPUT_DIR
from .chatgpt_connection import ChatGPTIntegrationWidget
from .github_manager import GitHubIntegrationWidget
from .v2_controller import GuiApplicationService, GuiResearchRequest
from .ux_presentation import (ENUM_LABELS, PROFILE_LABELS, REPORT_PRESETS,
    apply_report_preset, clone_profile_pair, display_percentage, metadata)


STRATEGY_TIMEFRAMES = ("15m", "1h", "4h", "1d")
INTRABAR_TIMEFRAMES = ("1m", "5m", "15m")
TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
TIMEFRAME_LABELS = {"1m": "1 Minute", "5m": "5 Minutes", "15m": "15 Minutes",
                    "1h": "1 Hour", "4h": "4 Hours", "1d": "1 Day"}

STRATEGY_GROUPS = (
    ("Profiles", ("strategy_profile_run_mode",), None),
    ("Direction", ("enable_di_direction_selection", "enable_di_pressure_analysis",
        "di_pressure_allow_expanding", "di_pressure_allow_contracting", "di_pressure_allow_mixed"), None),
    ("Entry Filters", ("enable_mean_reversion_analysis", "sr_filter_mode",
        "sr_long_avoid_near_resistance", "sr_long_require_near_support", "sr_long_block_broken_support",
        "sr_long_min_room_to_resistance_atr", "sr_short_avoid_near_support",
        "sr_short_require_near_resistance", "sr_short_block_broken_resistance",
        "sr_short_min_room_to_support_atr"), None),
    ("Entry Timing / Schedule", ("entry_mode", "entry_interval", "enable_daily_entry_schedule",
        "daily_entry_time", "daily_entry_timezone", "daily_entry_missed_policy"), None),
)

FEATURE_GROUPS = (
    ("Price / Volatility", ("atr_period", "bb_period", "bb_stddevs"), None),
    ("DI", ("adx_period", "di_pressure_lookback"), None),
    ("Mean Reversion", ("mean_reversion_period", "mean_reversion_mean_type",
        "mean_reversion_bb_stddevs", "mean_reversion_rsi_period", "mean_reversion_rsi_oversold",
        "mean_reversion_rsi_overbought", "mean_reversion_require_reentry",
        "mean_reversion_track_atr_distance", "mean_reversion_track_motion"), None),
    ("Regime", ("market_regime_method", "structural_regime_sma_days",
        "structural_regime_slope_lookback_days", "bull_regime_lookback_days",
        "bull_regime_return_threshold"), None),
    ("Support / Resistance", ("enable_support_resistance_analysis", "sr_timeframe_minutes",
        "sr_pivot_left", "sr_pivot_right", "sr_lookback_bars", "sr_zone_width_atr",
        "sr_near_distance_atr", "enable_sr_hold_confirmation", "sr_hold_confirmation_bars",
        "sr_hold_confirmation_atr", "sr_break_tolerance_atr", "sr_break_basis"), None),
    ("Open Interest", ("oi_zscore_window_days", "oi_zscore_min_samples"), "AUTO WHEN AVAILABLE"),
    ("Funding", ("funding_zscore_window_days", "funding_zscore_min_samples",
        "funding_extreme_zscore"), "AUTO WHEN AVAILABLE"),
    ("Positioning", ("basis_zscore_window_days",), "AUTO WHEN AVAILABLE"),
    ("Taker Flow", ("taker_flow_interval",), "AUTO WHEN AVAILABLE"),
    ("Trade Flow", ("trade_flow_enabled", "trade_flow_source", "trade_flow_base_interval",
        "trade_flow_windows", "large_trade_quote_threshold"), None),
    ("Order Book", ("order_book_enabled", "order_book_base_interval",
        "book_ticker_max_age_seconds", "book_depth_max_age_seconds"), None),
)

EXECUTION_GROUPS = (
    ("Risk", ("initial_equity", "risk_mode", "fixed_r", "percent_r", "atr_multiplier",
        "risk_per_leg", "max_effective_leverage_per_leg", "max_combined_effective_leverage",
        "max_active_pairs"), None),
    ("Take Profit", ("sr_take_profit_mode", "sr_take_profit_maximum_r",
        "sr_take_profit_minimum_r", "sr_take_profit_buffer_r", "sr_take_profit_no_level_policy"), None),
    ("Fees", ("maker_fee", "taker_fee", "use_maker_entry", "use_maker_exit",
        "zero_cost_comparison"), None),
    ("Slippage", ("slippage",), None),
    ("Tie / Same-bar Policy", ("tie_policy",), None),
)

STRATEGY_PROFILE_GROUPS = (
    ("Direction", ("enabled", "flip_direction"), None),
    ("Entry Filters", ("flip_rule_match_mode", "reject_rule_match_mode", "rsi_period",
        "momentum_lookback_hours"), None),
)

EXECUTION_PROFILE_GROUPS = (
    ("Risk", ("risk_multiplier",), None),
    ("Stop Loss", ("stop_loss_multiple",), None),
    ("Take Profit", ("reward_risk_ratio",), None),
    ("Break-even", ("break_even_enabled", "break_even_activation_r", "break_even_offset_r"), None),
    ("Trailing", ("trailing_enabled", "trailing_activation_r", "trailing_distance_r"), None),
    ("Partials", ("partial_stop_enabled", "sl1_r", "sl1_close_pct", "sl2_r",
        "partial_profit_enabled", "tp1_r", "tp1_close_pct", "tp2_r"), None),
    ("Timeout", ("timeout_enabled", "timeout_minutes"), None),
    ("Advanced Profit Management", ("r_step_trailing_enabled", "r_step_activation_r",
        "r_step_distance_r", "r_step_size_r", "r_step_maximum_r", "r_step_activation_close_pct",
        "atr_checkpoint_tp_extension_enabled", "atr_checkpoint_di_spread_minimum",
        "atr_checkpoint_bb_width_minimum", "atr_checkpoint_profit_lock_start",
        "atr_checkpoint_profit_lock_distance"), None),
)


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


class EntryRuleEditor(QTableWidget):
    """Ordered, lossless entry-rule editor with friendly common columns.

    Each row retains its original dictionary in ``Qt.UserRole``-equivalent
    private storage. Editing a visible cell updates only that key, so advanced
    and future rule properties survive a GUI round trip.
    """
    COLUMNS = ("action", "indicator", "condition", "minimum", "maximum")
    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(("Action", "Indicator", "Condition", "Minimum", "Maximum"))
        self._payloads = []

    def set_tuple(self, rules: tuple) -> None:
        from copy import deepcopy
        self.blockSignals(True)
        try:
            self._payloads = deepcopy(list(rules)); self.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                for column, key in enumerate(self.COLUMNS):
                    value = rule.get(key, "") if isinstance(rule, dict) else ""
                    if key in ("action","indicator","condition"):
                        editor = QComboBox()
                        choices = ({"FLIP":"Flip Direction","REJECT":"Reject Entry"} if key == "action" else
                            {name:name.replace("_"," ").title() for name in ("ADX","RSI","DI_SPREAD","CLOSE_LOCATION","BB_WIDTH")} if key == "indicator" else
                            {"INSIDE":"Inside Range","OUTSIDE":"Outside Range"})
                        if not value: editor.addItem(f"Select {key}…", "")
                        for native,label in choices.items(): editor.addItem(label,native)
                        index = editor.findData(value)
                        if index < 0 and value: editor.addItem(str(value), value); index = editor.count() - 1
                        editor.setCurrentIndex(max(index, 0)); self.setCellWidget(row, column, editor)
                    else: self.setItem(row, column, QTableWidgetItem(str(value)))
        finally: self.blockSignals(False)

    def tuple_value(self) -> tuple:
        from copy import deepcopy
        result = deepcopy(self._payloads)
        for row, rule in enumerate(result):
            if not isinstance(rule, dict): continue
            for column, key in enumerate(self.COLUMNS):
                cell = self.cellWidget(row, column)
                text = cell.currentData() if isinstance(cell, QComboBox) else (self.item(row, column).text() if self.item(row, column) else "")
                original = rule.get(key, "")
                if str(text) != str(original):
                    old = rule.get(key)
                    if isinstance(old, bool): value = text.lower() in ("true", "1", "yes")
                    elif key in ("minimum", "maximum") and text != "":
                        numeric=float(text); value=int(numeric) if isinstance(old,int) and numeric.is_integer() else numeric
                    elif isinstance(old, int): value = int(text)
                    elif isinstance(old, float): value = float(text)
                    else: value = text
                    rule[key] = value
        return tuple(result)

    def add_rule(self):
        self._payloads.append({"action": "FLIP", "indicator": "RSI", "condition": "INSIDE", "minimum": 0.0, "maximum": 100.0})
        self.set_tuple(tuple(self._payloads))

    def remove_selected(self):
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        for row in rows: self.removeRow(row); self._payloads.pop(row)


class LosslessDoubleSpinBox(QDoubleSpinBox):
    """Friendly numeric display that retains an untouched native float exactly."""
    def __init__(self, parent=None):
        super().__init__(parent); self._native_value = 0.0; self._edited = False
        self.valueChanged.connect(self._mark_edited)

    def _mark_edited(self, _value): self._edited = True

    def set_native_value(self, native: float, scale: float) -> None:
        self.blockSignals(True)
        try: self._native_value = native; self._edited = False; self.setValue(native * scale)
        finally: self.blockSignals(False)

    def native_value(self, scale: float) -> float:
        return self.value() / scale if self._edited else self._native_value


class DataclassForm(QWidget):
    """Lossless editor for every scalar/tuple field of one native dataclass."""
    changed = Signal()

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

    def __init__(self, value, *, excluded=(), groups=None, parent=None):
        super().__init__(parent); self.cls = type(value); self.widgets: dict[str, QWidget] = {}
        available = [item.name for item in fields(value) if item.name not in excluded]
        groups = groups or ((self.cls.__name__, tuple(available), None),)
        assigned = [name for _title, names, _note in groups for name in names]
        if len(assigned) != len(set(assigned)) or set(assigned) != set(available):
            raise ValueError(f"Grouped form fields must represent {self.cls.__name__} exactly once")
        self.section_titles = tuple(title for title, _names, _note in groups); self._forms = {}
        self._dependents = {
            "trade_flow_enabled": ("trade_flow_source","trade_flow_base_interval","trade_flow_windows","large_trade_quote_threshold"),
            "order_book_enabled": ("order_book_base_interval","book_ticker_max_age_seconds","book_depth_max_age_seconds"),
            "enable_support_resistance_analysis": ("sr_timeframe_minutes","sr_pivot_left","sr_pivot_right","sr_lookback_bars","sr_zone_width_atr","sr_near_distance_atr","enable_sr_hold_confirmation","sr_hold_confirmation_bars","sr_hold_confirmation_atr","sr_break_tolerance_atr","sr_break_basis"),
            "break_even_enabled": ("break_even_activation_r","break_even_offset_r"),
            "trailing_enabled": ("trailing_activation_r","trailing_distance_r"),
            "partial_profit_enabled": ("tp1_r","tp1_close_pct","tp2_r"),
            "partial_stop_enabled": ("sl1_r","sl1_close_pct","sl2_r"),
            "timeout_enabled": ("timeout_minutes",),
            "r_step_trailing_enabled": ("r_step_activation_r","r_step_distance_r","r_step_size_r","r_step_maximum_r","r_step_activation_close_pct"),
            "atr_checkpoint_tp_extension_enabled": ("atr_checkpoint_di_spread_minimum","atr_checkpoint_bb_width_minimum","atr_checkpoint_profit_lock_start","atr_checkpoint_profit_lock_distance"),
        }
        outer = QVBoxLayout(self)
        for title, names, note in groups:
            group = QGroupBox(title); form = QFormLayout(group)
            if note:
                status = QLabel(note); status.setObjectName("availabilityStatus"); form.addRow(status)
            for name in names:
                widget = self._widget(name, getattr(value, name)); self.widgets[name] = widget
                info = metadata(name); widget.setToolTip(info.help); self._forms[name] = form
                form.addRow(info.label, widget)
            outer.addWidget(group)
        outer.addStretch()
        for controller, dependents in self._dependents.items():
            if controller in self.widgets:
                self.widgets[controller].toggled.connect(lambda checked,names=dependents: self._set_visible(names,checked))
        for widget in self.widgets.values():
            signal = (widget.toggled if isinstance(widget,QCheckBox) else widget.valueChanged if isinstance(widget,(QSpinBox,QDoubleSpinBox)) else widget.currentIndexChanged if isinstance(widget,QComboBox) else widget.textChanged)
            signal.connect(self.changed.emit)
        self.set_value(value)

    def _set_visible(self, names, visible):
        for name in names:
            if name in self.widgets:
                widget=self.widgets[name]; form=self._forms[name]; label=form.labelForField(widget)
                widget.setVisible(visible)
                if label: label.setVisible(visible)

    def _widget(self, name: str, value: Any) -> QWidget:
        if name in self.CHOICES:
            widget = QComboBox()
            for native in self.CHOICES[name]: widget.addItem(ENUM_LABELS.get(name, {}).get(native, native), native)
            return widget
        if isinstance(value, bool): return QCheckBox()
        if isinstance(value, int):
            widget = QSpinBox(); widget.setRange(-2_000_000_000, 2_000_000_000); return widget
        if isinstance(value, float):
            info = metadata(name); widget = LosslessDoubleSpinBox(); widget.setRange(-1e12, 1e12)
            widget.setDecimals(info.decimals); widget.setSuffix(info.unit if info.unit != "$" else "")
            widget.setPrefix("$" if info.unit == "$" else ""); return widget
        if isinstance(value, tuple): return TupleEditor()
        return QLineEdit()

    def set_value(self, value) -> None:
        for name, widget in self.widgets.items():
            raw = getattr(value, name)
            if isinstance(widget, QCheckBox): widget.setChecked(raw)
            elif isinstance(widget, LosslessDoubleSpinBox): widget.set_native_value(raw, metadata(name).scale)
            elif isinstance(widget, QSpinBox): widget.setValue(raw)
            elif isinstance(widget, QComboBox):
                index = widget.findData(raw)
                if index < 0: widget.addItem(str(raw), raw); index = widget.count() - 1
                widget.setCurrentIndex(index)
            elif isinstance(widget, TupleEditor): widget.set_tuple(tuple(raw))
            else: widget.setText("" if raw is None else str(raw))
        for controller, dependents in self._dependents.items():
            if controller in self.widgets: self._set_visible(dependents,self.widgets[controller].isChecked())

    def value(self, base=None):
        base = base or self.cls(); values = {}
        for name, widget in self.widgets.items():
            old = getattr(base, name)
            if isinstance(widget, QCheckBox): raw = widget.isChecked()
            elif isinstance(widget, LosslessDoubleSpinBox): raw = widget.native_value(metadata(name).scale)
            elif isinstance(widget, QSpinBox): raw = widget.value()
            elif isinstance(widget, QComboBox): raw = widget.currentData()
            elif isinstance(widget, TupleEditor): raw = widget.tuple_value()
            else:
                text = widget.text()
                if old is None and not text: raw = None
                elif isinstance(old, (int, float)): raw = type(old)(text)
                elif name in self.OPTIONAL_NUMERIC: raw = self.OPTIONAL_NUMERIC[name](text)
                else: raw = text
            values[name] = raw
        return replace(base, **values)


class ProfileSelector(QComboBox):
    """Shows friendly names while accepting native keys programmatically."""
    def setCurrentText(self, text):
        index = self.findData(text)
        super().setCurrentIndex(index if index >= 0 else self.findText(text))


class TimeframeCombo(QComboBox):
    """Friendly visible timeframes with the native interval as user data."""
    def currentText(self): return self.currentData()
    def setCurrentText(self, text):
        index=self.findData(text); super().setCurrentIndex(index if index >= 0 else self.findText(text))


class NativeProfileEditor(QWidget):
    """Losslessly edits all native strategy and execution profile fields."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent); layout = QVBoxLayout(self)
        self.selector = ProfileSelector()
        for key in PROFILE_KEYS: self.selector.addItem(PROFILE_LABELS[key], key)
        layout.addWidget(self.selector)
        self.overview = QGridLayout(); layout.addLayout(self.overview); self.profile_cards = {}
        for index, key in enumerate(PROFILE_KEYS):
            card = QLabel(); card.setFrameShape(QLabel.Box); self.profile_cards[key] = card
            self.overview.addWidget(card, index // 2, index % 2)
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.copy_button = QPushButton("Copy Profile"); self.paste_button = QPushButton("Paste Profile")
        self.reset_button = QPushButton("Reset Profile"); self.apply_all_button = QPushButton("Apply Strategy to All Profiles")
        for button in (self.copy_button,self.paste_button,self.reset_button,self.apply_all_button): actions.addWidget(button)
        tabs = QTabWidget(); layout.addWidget(tabs)
        self.strategy_form = DataclassForm(StrategyProfileConfig(), excluded={"entry_rules"},
                                           groups=STRATEGY_PROFILE_GROUPS)
        strategy_page = QWidget(); strategy_layout = QVBoxLayout(strategy_page)
        strategy_layout.addWidget(self.strategy_form); strategy_layout.addWidget(QLabel("Ordered Entry Rules"))
        self.entry_rules = EntryRuleEditor(); strategy_layout.addWidget(self.entry_rules)
        rule_actions = QHBoxLayout(); add_rule = QPushButton("+ Add Rule"); remove_rule = QPushButton("Remove Selected")
        add_rule.clicked.connect(self.entry_rules.add_rule); remove_rule.clicked.connect(self.entry_rules.remove_selected)
        rule_actions.addWidget(add_rule); rule_actions.addWidget(remove_rule); strategy_layout.addLayout(rule_actions)
        self.execution_form = DataclassForm(ExecutionProfileConfig(), groups=EXECUTION_PROFILE_GROUPS)
        tabs.addTab(strategy_page, "Strategy Profile"); tabs.addTab(self.execution_form, "Execution Profile")
        self._strategy = {}; self._execution = {}; self._current = PROFILE_KEYS[0]; self._rendering = False
        self._clipboard = None; self.selector.currentIndexChanged.connect(lambda: self._select(self.selector.currentData()))
        self.copy_button.clicked.connect(self.copy_profile); self.paste_button.clicked.connect(self.paste_profile)
        self.reset_button.clicked.connect(self.reset_profile); self.apply_all_button.clicked.connect(self.apply_strategy_to_all)
        self.strategy_form.changed.connect(self._notify_changed); self.execution_form.changed.connect(self._notify_changed)
        self.entry_rules.itemChanged.connect(lambda _item: self._notify_changed())

    def _notify_changed(self):
        if not self._rendering: self.changed.emit()

    def _store(self) -> None:
        if not self._strategy: return
        key = self._current
        strategy = self.strategy_form.value(self._strategy[key])
        self._strategy[key] = replace(strategy, entry_rules=self.entry_rules.tuple_value())
        self._execution[key] = self.execution_form.value(self._execution[key])

    def _render(self, key: str) -> None:
        self._rendering=True
        try:
            self._current = key; self.strategy_form.set_value(self._strategy[key])
            self.entry_rules.set_tuple(tuple(self._strategy[key].entry_rules))
            self.execution_form.set_value(self._execution[key]); self._render_cards()
        finally: self._rendering=False

    def _render_cards(self):
        for key in PROFILE_KEYS:
            if key not in self._strategy: continue
            s, e = self._strategy[key], self._execution[key]
            protection = ", ".join(name for on,name in ((e.break_even_enabled,"Break-even"),(e.trailing_enabled,"Trailing"),(e.partial_profit_enabled,"Partial TP"),(e.timeout_enabled,"Timeout")) if on) or "Base exits"
            self.profile_cards[key].setText(f"{PROFILE_LABELS[key].upper()}\n{'Enabled' if s.enabled else 'Disabled'} · {'Flipped' if s.flip_direction else 'Normal'}\nEntry Rules {len(s.entry_rules)}  |  Risk {e.risk_multiplier:.2f}x\nStop {e.stop_loss_multiple:g} units  |  Target {e.reward_risk_ratio:g}R\n{protection}")

    def _select(self, key: str) -> None:
        self._store(); self._render(key)

    def set_profiles(self, strategy, execution) -> None:
        # Block the selector signal so stale widgets can never overwrite incoming profiles.
        self.selector.blockSignals(True)
        try:
            self._strategy, self._execution = dict(strategy), dict(execution)
            self._render(self.selector.currentData() or PROFILE_KEYS[0])
        finally:
            self.selector.blockSignals(False)

    def profiles(self):
        self._store(); return dict(self._strategy), dict(self._execution)

    def copy_profile(self):
        self._store(); self._clipboard = clone_profile_pair(self._strategy[self._current], self._execution[self._current])

    def paste_profile(self):
        if self._clipboard:
            self._strategy[self._current], self._execution[self._current] = clone_profile_pair(*self._clipboard); self._render(self._current); self.changed.emit()

    def reset_profile(self):
        self._strategy[self._current] = StrategyProfileConfig(); self._execution[self._current] = ExecutionProfileConfig(); self._render(self._current); self.changed.emit()

    def apply_strategy_to_all(self):
        self._store(); source = self._strategy[self._current]
        for key in PROFILE_KEYS: self._strategy[key] = clone_profile_pair(source, self._execution[key])[0]
        self._render(self._current); self.changed.emit()


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
        super().__init__(); self.setWindowTitle("Crypto Strategy Lab — Research Workstation"); self.resize(1500, 920)
        self.service = service or GuiApplicationService(MARKET_DATA_ROOT, CACHE_DIR)
        self.config = ResearchRunConfig(); self._manifest = None; self._run_dir = None; self._thread = None; self._applying_config = False
        root = QWidget(); shell = QHBoxLayout(root); self.setCentralWidget(root)
        nav = QVBoxLayout(); shell.addLayout(nav); self.pages = QStackedWidget(); shell.addWidget(self.pages, 1)
        self.profile_editor = NativeProfileEditor()
        self.strategy_form = DataclassForm(StrategyConfig(), excluded={"profiles"}, groups=STRATEGY_GROUPS)
        self.feature_form = DataclassForm(FeatureConfig(), groups=FEATURE_GROUPS)
        self.execution_form = DataclassForm(ExecutionConfig(), excluded={"profiles"}, groups=EXECUTION_GROUPS)
        self.reporting_form = DataclassForm(ReportingConfig(), excluded={"output_dir"})
        setup = self._page("Setup", self._data_panel(), self._status_panel())
        strategy = self._page("Strategy & Profiles", self._scroll(self.profile_editor), self._scroll(self.strategy_form))
        features = self._page("Research Features", self._scroll(self.feature_form))
        risk = self._page("Risk & Execution", self._scroll(self.execution_form), self._risk_explanation())
        reports = self._page("Reports & Diagnostics", self._report_presets(), self._scroll(self.reporting_form))
        review = self._page("Review & Run", self._review_panel(), self._run_panel())
        results = self._page("Results Dashboard", self._results_panel())
        library = self._page("Data Library", self._data_library_panel())
        chat = ChatGPTIntegrationWidget(QSettings("CryptoStrategyLab", "CryptoStrategyLab"), lambda: self.output_root.text())
        github = GitHubIntegrationWidget()
        groups = (("NEW RESEARCH",(("Setup",setup),("Strategy & Profiles",strategy),("Research Features",features),("Risk & Execution",risk),("Reports",reports),("Review & Run",review))),
                  ("RESULTS",(("Results Dashboard",results),)),("DATA",(("Data Library",library),)),
                  ("TOOLS",(("ChatGPT / MCP",chat),("GitHub",github))))
        for heading, entries in groups:
            title=QLabel(heading); title.setStyleSheet("font-weight:bold; color:#52606d; margin-top:10px"); nav.addWidget(title)
            for label,page in entries:
                index=self.pages.addWidget(page); button=QPushButton(label); button.setFlat(True)
                button.clicked.connect(lambda _=False,i=index: self.pages.setCurrentIndex(i)); nav.addWidget(button)
        nav.addStretch(); self.current_research = QLabel(); self.current_research.setMinimumWidth(245)
        self.current_research.setStyleSheet("background:#f4f7fa; padding:12px; border:1px solid #d9e2ec")
        nav.addWidget(self.current_research); quick_run=QPushButton("RUN BACKTEST"); quick_run.clicked.connect(self.start_run); nav.addWidget(quick_run)
        self._connect_request_refresh(); self._connect_live_summary(); self.service.refresh_catalog(); self._load_catalog(); self.apply_config(self.config)
        if startup_status: startup_status("Native v2 research GUI ready")

    @staticmethod
    def _page(title, *widgets):
        page=QWidget(); layout=QVBoxLayout(page); heading=QLabel(title)
        heading.setStyleSheet("font-size:22px; font-weight:bold; margin:8px"); layout.addWidget(heading)
        for widget in widgets: layout.addWidget(widget)
        return page

    def _status_panel_clone(self):
        box=QGroupBox("Technical Catalog Detail"); layout=QVBoxLayout(box)
        note=QLabel("Availability, friendly coverage dates, interval and partition counts are supplied by the catalog service. Raw archive paths are never displayed.")
        note.setWordWrap(True); layout.addWidget(note); return box

    def _data_library_panel(self):
        box=QGroupBox("Catalog Coverage"); layout=QVBoxLayout(box)
        refresh=QPushButton("Refresh Catalog View"); refresh.clicked.connect(self.refresh_data_library); layout.addWidget(refresh)
        self.library_table=QTableWidget(0,7); self.library_table.setHorizontalHeaderLabels(
            ["Symbol","Dataset Family","Interval","First Available UTC","Last Available UTC","Partitions","State"])
        layout.addWidget(self.library_table); return box

    def refresh_data_library(self):
        if not hasattr(self.service.catalog,"inventory"): return
        rows=self.service.catalog.inventory(self.market.currentData()); self.library_table.setRowCount(len(rows))
        for row_number,row in enumerate(rows):
            count=row.get("archive_count",0); first=row.get("first_period"); last=row.get("last_period")
            state="UNAVAILABLE" if not count else "AVAILABLE" if first is not None and last is not None else "PARTIAL"
            values=(row.get("symbol","—"),self._dataset_family(row.get("dataset","")),row.get("interval") or "Event data",
                    first or "—",last or "—",count,row.get("state",state))
            for column,value in enumerate(values): self.library_table.setItem(row_number,column,QTableWidgetItem(str(value)))

    @staticmethod
    def _dataset_family(dataset):
        value=str(dataset).lower()
        if "kline" in value: return "Candles"
        if "fund" in value: return "Funding"
        if "metric" in value or "interest" in value or "ratio" in value: return "Futures Positioning"
        if "agg" in value or value == "trades": return "Trades"
        if "book" in value or "depth" in value: return "Order Book"
        return str(dataset).replace("_"," ").title()

    def _risk_explanation(self):
        box=QGroupBox("Effective Risk"); layout=QVBoxLayout(box); self.risk_explanation=QLabel(); self.risk_explanation.setWordWrap(True); layout.addWidget(self.risk_explanation); return box

    def _report_presets(self):
        box=QGroupBox("Report Preset"); layout=QHBoxLayout(box); self.report_preset=QComboBox()
        self.report_preset.addItem("Quick — core artifacts", "QUICK"); self.report_preset.addItem("Standard — Recommended", "STANDARD"); self.report_preset.addItem("Deep Research — full diagnostics", "DEEP_RESEARCH")
        apply_button=QPushButton("Apply Preset"); apply_button.clicked.connect(self.apply_reporting_preset)
        layout.addWidget(self.report_preset); layout.addWidget(apply_button); return box

    def apply_reporting_preset(self):
        current=self.reporting_form.value(self.config.reporting); updated=apply_report_preset(current,self.report_preset.currentData())
        self.reporting_form.set_value(updated)

    def _review_panel(self):
        box=QGroupBox("Experiment Review"); layout=QVBoxLayout(box); self.review_summary=QLabel(); self.review_summary.setWordWrap(True); layout.addWidget(self.review_summary); return box

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
        self.strategy_tf = TimeframeCombo()
        for value in STRATEGY_TIMEFRAMES: self.strategy_tf.addItem(TIMEFRAME_LABELS[value],value)
        self.intrabar_tf = TimeframeCombo(); self.intrabar_tf.addItem("None — Strategy Bars Only",None)
        for value in INTRABAR_TIMEFRAMES: self.intrabar_tf.addItem(TIMEFRAME_LABELS[value],value)
        self.datasets = QLabel("Catalog not loaded"); self.datasets.setWordWrap(True)
        date_note=QLabel("Research includes data from the start date up to, but not including, the selected end boundary."); date_note.setWordWrap(True)
        for label, widget in (("Exchange", self.exchange), ("Market", self.market), ("Symbol", self.symbol),
            ("Start Date", self.start), ("End Date", self.end), ("Date Range",date_note), ("Strategy Timeframe", self.strategy_tf),
            ("Intrabar / Exit Detail", self.intrabar_tf), ("Research Data Availability", self.datasets)): form.addRow(label, widget)
        return box

    def _config_tabs(self):
        tabs = QTabWidget()
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
        cards=QGridLayout(); layout.addLayout(cards); self.kpi_cards={}
        labels=("Trades","Wins","Losses","Win Rate","Net R","Average R","Net PnL","Ending Equity","Profit Factor","Maximum Drawdown","Fees")
        for index,label in enumerate(labels):
            card=QLabel(f"{label}\n—"); card.setFrameShape(QLabel.Box); card.setMinimumHeight(55); cards.addWidget(card,index//4,index%4); self.kpi_cards[label]=card
        self.summary = QLabel("No completed run"); layout.addWidget(self.summary); self.timings=QLabel("Run timings: —"); layout.addWidget(self.timings); self.artifact_buttons = {}
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

    def _connect_live_summary(self):
        for form in (self.strategy_form,self.feature_form,self.execution_form,self.reporting_form): form.changed.connect(self._refresh_summary_from_widgets)
        self.profile_editor.changed.connect(self._refresh_summary_from_widgets)
        self.output_root.textChanged.connect(self._refresh_summary_from_widgets)

    def _refresh_summary_from_widgets(self):
        if self._applying_config: return
        try: self._render_research_summary(self.build_config())
        except (ValueError,TypeError,KeyError): pass

    def request_model(self):
        def utc(widget): return pd.Timestamp(widget.date().toPython(), tz="UTC").to_pydatetime()
        intrabar = self.intrabar_tf.currentData()
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
        result = replace(self.config, data=data, features=self.feature_form.value(self.config.features),
                       strategy=strategy, execution=execution,
                       reporting=replace(self.reporting_form.value(self.config.reporting), output_dir=self.output_root.text()))
        return result

    def apply_config(self, config):
        self._applying_config=True
        try:
            self.config = config; data = config.data
            self.strategy_tf.setCurrentText(timeframe_label(data.strategy_timeframe_minutes))
            self.intrabar_tf.setCurrentText(timeframe_label(data.intrabar_timeframe_minutes) if data.use_intrabar_data else None)
            self.profile_editor.set_profiles(config.strategy.profiles, config.execution.profiles)
            self.strategy_form.set_value(config.strategy); self.feature_form.set_value(config.features)
            self.execution_form.set_value(config.execution); self.output_root.setText(config.reporting.output_dir)
            self.reporting_form.set_value(config.reporting)
        finally: self._applying_config=False
        self._render_research_summary(config)

    def _render_research_summary(self, config):
        enabled=sum(profile.enabled for profile in config.strategy.profiles.values())
        intrabar=f"{config.data.intrabar_timeframe_minutes}m exits" if config.data.use_intrabar_data else "bar-close exits"
        risk=display_percentage(config.execution.risk_per_leg)
        text=(f"CURRENT RESEARCH\n\n{self.symbol.currentText() or 'BTCUSDT'}\n{timeframe_label(config.data.strategy_timeframe_minutes)} strategy / {intrabar}\n\nProfiles  {enabled} of 6 ON\nDI  {'ON' if config.strategy.enable_di_direction_selection else 'OFF'}\nMean Reversion  {'ON' if config.strategy.enable_mean_reversion_analysis else 'OFF'}\nTrade Flow  {'ON' if config.features.trade_flow_enabled else 'OFF'}\nOrder Book  {'ON' if config.features.order_book_enabled else 'OFF'}\n\nBase risk  {risk}\nMax trades  {config.execution.max_active_pairs}\n\nData  {self._data_state()}")
        self.current_research.setText(text)
        self.risk_explanation.setText(f"Base Risk: {risk}\nAt ${config.execution.initial_equity:,.2f}, planned base full-stop loss is ${config.execution.initial_equity * config.execution.risk_per_leg:,.2f}. Profile multipliers use the existing execution configuration.")
        if hasattr(self,"review_summary"):
            mode=ENUM_LABELS["strategy_profile_run_mode"].get(config.strategy.strategy_profile_run_mode,config.strategy.strategy_profile_run_mode)
            self.review_summary.setText(f"{self.symbol.currentText() or 'BTCUSDT'} — {timeframe_label(config.data.strategy_timeframe_minutes)} Research\n\nProfile Test: {mode}\nProfiles: {enabled} of 6 enabled\nStarting Equity: ${config.execution.initial_equity:,.2f}\nBase Risk: {risk}\nMaximum Active Trades: {config.execution.max_active_pairs}\nReports: {config.reporting.analysis_level}\n\nDATA STATUS: {self._data_state()}")

    def _data_state(self):
        return self.data_readiness(self._coverage_rows_from_table(), self.strategy_tf.currentData(), self.intrabar_tf.currentData())[0]

    @staticmethod
    def data_readiness(rows, strategy_interval, intrabar_interval=None):
        """Classify catalog coverage using execution candles as required data."""
        required={strategy_interval}
        if intrabar_interval: required.add(intrabar_interval)
        candle_rows=[row for row in rows if "kline" in str(row.get("dataset","")).lower()]
        missing=[]
        for interval in required:
            matches=[row for row in candle_rows if row.get("interval") == interval]
            if not matches or not any(row.get("state") == "AVAILABLE" for row in matches): missing.append(interval)
        if missing: return "BLOCKED", "Required candle coverage unavailable: " + ", ".join(sorted(missing))
        optional=[row for row in rows if row not in candle_rows and row.get("state") != "AVAILABLE"]
        if optional: return "WARN", "Required candles are ready; optional research coverage is partial or unavailable."
        return "READY", "Required execution data is available."

    def _coverage_rows_from_table(self):
        return [{"dataset":self.coverage.item(row,0).text(),"interval":None if self.coverage.item(row,1).text()=="—" else self.coverage.item(row,1).text(),"state":self.coverage.item(row,5).text()}
                for row in range(self.coverage.rowCount()) if all(self.coverage.item(row,column) for column in (0,1,5))]

    def _load_catalog(self):
        current = self.symbol.currentText(); symbols = self.service.catalog.symbols()
        self.symbol.blockSignals(True); self.symbol.clear(); self.symbol.addItems(symbols or [current or "BTCUSDT"])
        if current: self.symbol.setCurrentText(current)
        self.symbol.blockSignals(False); self.refresh_coverage()

    def refresh_coverage(self):
        if not self.symbol.currentText() or self.start.date() >= self.end.date(): return
        rows = self.service.catalog.coverage(self.request_model()); self.coverage.setRowCount(len(rows))
        grouped={}
        for row in rows: grouped.setdefault(self._dataset_family(row["dataset"]),[]).append(row["state"])
        self.datasets.setText("\n".join(f"{family}: {('AVAILABLE' if all(x == 'AVAILABLE' for x in states) else 'PARTIAL' if any(x == 'AVAILABLE' for x in states) else 'UNAVAILABLE')}" for family,states in sorted(grouped.items())) or "Required candle data: UNAVAILABLE")
        for row_number, row in enumerate(rows):
            values = (row["dataset"], row["interval"] or "—", row["first_period"] or "—",
                      row["last_period"] or "—", row["archive_count"], row["state"])
            for column, value in enumerate(values): self.coverage.setItem(row_number, column, QTableWidgetItem(str(value)))
        self.refresh_data_library()
        if hasattr(self,"current_research"): self._refresh_summary_from_widgets()

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
        keys=("total_trades","wins","losses","win_rate","total_net_r","average_net_r","net_pnl","ending_equity","profit_factor","maximum_drawdown_percentage","total_fees")
        for (label,card),key in zip(self.kpi_cards.items(),keys): card.setText(f"{label}\n{summary.get(key,'—')}")
        stage_timings=self._manifest.get("execution_result",{}).get("stage_timings",{})
        self.timings.setText("Run timings: " + (" · ".join(f"{name.replace('_',' ').title()} {value}s" for name,value in stage_timings.items()) or "not recorded"))
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
