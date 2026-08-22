"""Composition-based Task-18 desktop GUI for native v2 research runs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, QSettings, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from crypto_strategy_lab.data import MarketKind
from crypto_strategy_lab.data_lake_config import PROFILE_KEYS, ResearchRunConfig
from crypto_strategy_lab.paths import CACHE_DIR, MARKET_DATA_ROOT, OUTPUT_DIR
from .chatgpt_connection import ChatGPTIntegrationWidget
from .github_manager import GitHubIntegrationWidget
from .v2_controller import GuiApplicationService, GuiResearchRequest


def _spin(value, minimum=1, maximum=1000000):
    w = QSpinBox(); w.setRange(minimum, maximum); w.setValue(value); return w


def _double(value, minimum=0, maximum=1000000, decimals=4):
    w = QDoubleSpinBox(); w.setRange(minimum, maximum); w.setDecimals(decimals); w.setValue(value); return w


class NativeProfileEditor(QWidget):
    """Edits native profile dataclasses without a legacy dictionary adapter."""
    def __init__(self, parent=None):
        super().__init__(parent); self._strategy = {}; self._execution = {}
        layout = QVBoxLayout(self); self.selector = QComboBox(); self.selector.addItems(PROFILE_KEYS)
        layout.addWidget(self.selector); form = QFormLayout(); layout.addLayout(form)
        self.enabled = QCheckBox(); self.flip = QCheckBox(); self.entry_rules = QLineEdit()
        self.reward_risk = _double(1.0); self.risk_multiplier = _double(1.0)
        self.stop_multiple = _double(2.0); self.trailing = QCheckBox(); self.break_even = QCheckBox()
        for label, widget in (("Enabled", self.enabled), ("Flip direction", self.flip),
            ("Entry rules (comma separated)", self.entry_rules), ("Reward / risk", self.reward_risk),
            ("Risk multiplier", self.risk_multiplier), ("Stop loss multiple", self.stop_multiple),
            ("Trailing", self.trailing), ("Break-even", self.break_even)): form.addRow(label, widget)
        self.selector.currentTextChanged.connect(self._select); self._current = PROFILE_KEYS[0]
        self.set_profiles(ResearchRunConfig().strategy.profiles, ResearchRunConfig().execution.profiles)

    def _save_current(self):
        key = self._current; s = self._strategy[key]; e = self._execution[key]
        self._strategy[key] = replace(s, enabled=self.enabled.isChecked(), flip_direction=self.flip.isChecked(),
            entry_rules=tuple(x.strip() for x in self.entry_rules.text().split(",") if x.strip()))
        self._execution[key] = replace(e, reward_risk_ratio=self.reward_risk.value(),
            risk_multiplier=self.risk_multiplier.value(), stop_loss_multiple=self.stop_multiple.value(),
            trailing_enabled=self.trailing.isChecked(), break_even_enabled=self.break_even.isChecked())

    def _select(self, key):
        if self._strategy: self._save_current()
        self._current = key; s, e = self._strategy[key], self._execution[key]
        self.enabled.setChecked(s.enabled); self.flip.setChecked(s.flip_direction)
        self.entry_rules.setText(", ".join(s.entry_rules)); self.reward_risk.setValue(e.reward_risk_ratio)
        self.risk_multiplier.setValue(e.risk_multiplier); self.stop_multiple.setValue(e.stop_loss_multiple)
        self.trailing.setChecked(e.trailing_enabled); self.break_even.setChecked(e.break_even_enabled)

    def set_profiles(self, strategy, execution):
        self._strategy, self._execution = dict(strategy), dict(execution); self._current = self.selector.currentText(); self._select(self._current)

    def profiles(self):
        self._save_current(); return dict(self._strategy), dict(self._execution)


class RunWorker(QObject):
    finished = Signal(object); failed = Signal(str)
    def __init__(self, service, request, config): super().__init__(); self.service=service; self.request=request; self.config=config
    @Slot()
    def run(self):
        try: self.finished.emit(self.service.run(self.request, self.config))
        except Exception as exc: self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """The single authoritative GUI, inheriting directly from QMainWindow."""
    def __init__(self, startup_status=None, service=None):
        super().__init__(); self.setWindowTitle("Crypto Strategy Lab v2"); self.resize(1280, 850)
        self.service = service or GuiApplicationService(MARKET_DATA_ROOT, CACHE_DIR)
        self.config = ResearchRunConfig(); self._manifest = None; self._run_dir = None; self._thread = None
        tabs = QTabWidget(); self.setCentralWidget(tabs)
        research = QWidget(); root = QVBoxLayout(research); tabs.addTab(research, "Research Run")
        scroll = QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); grid=QGridLayout(body); scroll.setWidget(body); root.addWidget(scroll)
        grid.addWidget(self._data_panel(),0,0); grid.addWidget(self._strategy_panel(),0,1)
        grid.addWidget(self._feature_panel(),1,0); grid.addWidget(self._execution_panel(),1,1)
        grid.addWidget(self._run_panel(),2,0,1,2); grid.addWidget(self._status_panel(),3,0)
        grid.addWidget(self._results_panel(),3,1)
        tabs.addTab(ChatGPTIntegrationWidget(QSettings("CryptoStrategyLab", "CryptoStrategyLab"),
                                             lambda: self.output_root.text()), "ChatGPT / MCP")
        tabs.addTab(GitHubIntegrationWidget(), "GitHub")
        self._load_catalog(); self.apply_config(self.config)
        if startup_status: startup_status("Native v2 research GUI ready")

    def _group(self, title): box=QGroupBox(title); box.setLayout(QFormLayout()); return box
    def _data_panel(self):
        box=self._group("Data / Request"); f=box.layout(); self.exchange=QComboBox(); self.exchange.addItem("Binance","binance")
        self.market=QComboBox(); self.market.addItem("USD-M Futures",MarketKind.FUTURES_UM)
        self.symbol=QComboBox(); self.symbol.setEditable(True); self.start=QDateEdit(); self.end=QDateEdit()
        self.strategy_tf=QComboBox(); self.strategy_tf.addItems(["15m","1h","4h","1d"])
        self.intrabar_tf=QComboBox(); self.intrabar_tf.addItems(["None","1m","5m","15m"])
        self.datasets=QLabel("Catalog not loaded")
        for a,b in (("Exchange",self.exchange),("Market",self.market),("Symbol",self.symbol),("Period Start",self.start),("Period End (exclusive)",self.end),("Strategy TF",self.strategy_tf),("Intrabar TF",self.intrabar_tf),("Available Datasets",self.datasets)): f.addRow(a,b)
        self.symbol.currentTextChanged.connect(self.refresh_coverage); return box
    def _strategy_panel(self):
        box=QGroupBox("Strategy Profiles / Entry Filters"); l=QVBoxLayout(box); self.run_mode=QComboBox(); self.run_mode.addItems(["COMBINED_SHARED_CAPITAL","ISOLATED_PROFILES","BOTH"]); l.addWidget(self.run_mode)
        self.profile_editor=NativeProfileEditor(); l.addWidget(self.profile_editor); return box
    def _feature_panel(self):
        box=self._group("Research Features"); f=box.layout(); self.atr=_spin(14); self.adx=_spin(14); self.di_lookback=_spin(3)
        self.mr_period=_spin(20); self.regime=QComboBox(); self.regime.addItems(["BTC_STRUCTURAL","ASSET_STRUCTURAL","ASSET_RETURN"])
        self.sr_enabled=QCheckBox(); self.sr_lookback=_spin(200); self.trade_flow=QCheckBox(); self.trade_source=QComboBox(); self.trade_source.addItems(["AGG_TRADES","TRADES"])
        self.order_book=QCheckBox(); self.book_ticker_age=_double(5); self.book_depth_age=_double(90)
        rows=(("Price / Volatility","AUTO WHEN AVAILABLE"),("DI ATR period",self.atr),("DI ADX period",self.adx),("DI pressure lookback",self.di_lookback),("Mean Reversion period",self.mr_period),("Regime",self.regime),("Support / Resistance enabled",self.sr_enabled),("S/R lookback",self.sr_lookback),("Open Interest / Funding / Positioning / Taker Flow","AUTO WHEN AVAILABLE"),("Trade Flow enabled",self.trade_flow),("Trade Flow source",self.trade_source),("Order Book enabled",self.order_book),("Book ticker max age",self.book_ticker_age),("Book depth max age",self.book_depth_age))
        for label,w in rows: f.addRow(label, QLabel(w) if isinstance(w,str) else w)
        return box
    def _execution_panel(self):
        box=self._group("Execution"); f=box.layout(); self.equity=_double(1000); self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","FIXED","PERCENT"])
        self.fixed_r=_double(100); self.percent_r=_double(.002,0,1,6); self.atr_mult=_double(1); self.risk_leg=_double(.01,0,1,6)
        self.max_pairs=_spin(1); self.maker=_double(.0002,0,1,6); self.taker=_double(.0005,0,1,6); self.slippage=_double(.0005,0,1,6)
        self.tie=QComboBox(); self.tie.addItems(["PESSIMISTIC","OPTIMISTIC","INTRABAR"]); self.zero_cost=QCheckBox()
        for a,b in (("RISK — Initial equity",self.equity),("Risk mode",self.risk_mode),("Fixed R",self.fixed_r),("Percent R",self.percent_r),("ATR multiplier",self.atr_mult),("Risk per leg",self.risk_leg),("Max active pairs",self.max_pairs),("FEES — Maker",self.maker),("Taker",self.taker),("SLIPPAGE",self.slippage),("TIE / SAME-BAR POLICY",self.tie),("Zero-cost comparison",self.zero_cost)): f.addRow(a,b)
        return box
    def _run_panel(self):
        box=QGroupBox("Run"); l=QHBoxLayout(box); self.output_root=QLineEdit(str(OUTPUT_DIR/"data_lake_v2")); browse=QPushButton("Output Root…"); browse.clicked.connect(self._browse_output)
        self.save=QPushButton("Save Config…"); self.load=QPushButton("Load Config…"); self.run_button=QPushButton("Run"); self.progress=QProgressBar(); self.stage=QLabel("Ready")
        self.save.clicked.connect(self.save_config); self.load.clicked.connect(self.load_config); self.run_button.clicked.connect(self.start_run)
        for w in (QLabel("Output root"),self.output_root,browse,self.save,self.load,self.run_button,self.progress,self.stage): l.addWidget(w)
        return box
    def _status_panel(self):
        box=QGroupBox("Data Status"); l=QVBoxLayout(box); self.coverage=QTableWidget(0,6); self.coverage.setHorizontalHeaderLabels(["Dataset","Interval","First","Last","Partitions","State"]); self.quality=QLabel("Data quality: not run"); l.addWidget(self.coverage); l.addWidget(self.quality); return box
    def _results_panel(self):
        box=QGroupBox("Results / Canonical Artifacts"); l=QVBoxLayout(box); self.summary=QLabel("No completed run"); l.addWidget(self.summary); self.artifact_buttons={}
        for key in ("workbook","trade_csv","summary","trades","signals","feature_context","telemetry","data_quality"):
            b=QPushButton(key.replace("_"," ").title()); b.setEnabled(False); b.clicked.connect(lambda _=False,k=key:self.open_artifact(k)); self.artifact_buttons[key]=b; l.addWidget(b)
        self.open_folder=QPushButton("Output Folder"); self.open_folder.setEnabled(False); self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._run_dir)))); l.addWidget(self.open_folder); return box

    def request_model(self):
        def dt(w): return pd.Timestamp(w.date().toPython()).tz_localize("UTC").to_pydatetime()
        return GuiResearchRequest(self.exchange.currentData(),self.market.currentData(),self.symbol.currentText(),dt(self.start),dt(self.end),self.strategy_tf.currentText(),None if self.intrabar_tf.currentText()=="None" else self.intrabar_tf.currentText())
    def build_config(self):
        sp,ep=self.profile_editor.profiles(); itf=self.request_model().intrabar_timeframe
        data=replace(self.config.data,strategy_timeframe_minutes=int(pd.Timedelta(self.strategy_tf.currentText()).total_seconds()/60),use_intrabar_data=itf is not None,intrabar_timeframe_minutes=int(pd.Timedelta(itf or "1m").total_seconds()/60))
        features=replace(self.config.features,atr_period=self.atr.value(),adx_period=self.adx.value(),di_pressure_lookback=self.di_lookback.value(),mean_reversion_period=self.mr_period.value(),market_regime_method=self.regime.currentText(),enable_support_resistance_analysis=self.sr_enabled.isChecked(),sr_lookback_bars=self.sr_lookback.value(),trade_flow_enabled=self.trade_flow.isChecked(),trade_flow_source=self.trade_source.currentText(),order_book_enabled=self.order_book.isChecked(),book_ticker_max_age_seconds=self.book_ticker_age.value(),book_depth_max_age_seconds=self.book_depth_age.value())
        strategy=replace(self.config.strategy,profiles=sp,strategy_profile_run_mode=self.run_mode.currentText()); execution=replace(self.config.execution,profiles=ep,initial_equity=self.equity.value(),risk_mode=self.risk_mode.currentText(),fixed_r=self.fixed_r.value(),percent_r=self.percent_r.value(),atr_multiplier=self.atr_mult.value(),risk_per_leg=self.risk_leg.value(),max_active_pairs=self.max_pairs.value(),maker_fee=self.maker.value(),taker_fee=self.taker.value(),slippage=self.slippage.value(),tie_policy=self.tie.currentText(),zero_cost_comparison=self.zero_cost.isChecked())
        return replace(self.config,data=data,features=features,strategy=strategy,execution=execution,reporting=replace(self.config.reporting,output_dir=self.output_root.text()))
    def apply_config(self,c):
        self.config=c; d,f,s,e=c.data,c.features,c.strategy,c.execution; self.strategy_tf.setCurrentText(f"{d.strategy_timeframe_minutes}m"); self.intrabar_tf.setCurrentText(f"{d.intrabar_timeframe_minutes}m" if d.use_intrabar_data else "None"); self.run_mode.setCurrentText(s.strategy_profile_run_mode); self.profile_editor.set_profiles(s.profiles,e.profiles)
        for w,v in ((self.atr,f.atr_period),(self.adx,f.adx_period),(self.di_lookback,f.di_pressure_lookback),(self.mr_period,f.mean_reversion_period),(self.sr_lookback,f.sr_lookback_bars),(self.equity,e.initial_equity),(self.fixed_r,e.fixed_r),(self.percent_r,e.percent_r),(self.atr_mult,e.atr_multiplier),(self.risk_leg,e.risk_per_leg),(self.max_pairs,e.max_active_pairs),(self.maker,e.maker_fee),(self.taker,e.taker_fee),(self.slippage,e.slippage)): w.setValue(v)
        self.regime.setCurrentText(f.market_regime_method); self.sr_enabled.setChecked(f.enable_support_resistance_analysis); self.trade_flow.setChecked(f.trade_flow_enabled); self.trade_source.setCurrentText(f.trade_flow_source); self.order_book.setChecked(f.order_book_enabled); self.risk_mode.setCurrentText(e.risk_mode); self.tie.setCurrentText(e.tie_policy); self.zero_cost.setChecked(e.zero_cost_comparison); self.output_root.setText(c.reporting.output_dir)
    def _load_catalog(self):
        symbols=self.service.catalog.symbols(); self.symbol.clear(); self.symbol.addItems(symbols or ["BTCUSDT"]); self.refresh_coverage()
    def refresh_coverage(self):
        if not self.symbol.currentText(): return
        rows=self.service.catalog.coverage(self.request_model()); self.coverage.setRowCount(len(rows)); self.datasets.setText(", ".join(sorted({r['dataset'] for r in rows})) or "UNAVAILABLE")
        for i,r in enumerate(rows):
            for j,v in enumerate((r['dataset'],r['interval'] or '—',r['first_period'] or '—',r['last_period'] or '—',r['archive_count'],r['state'])): self.coverage.setItem(i,j,QTableWidgetItem(str(v)))
    def start_run(self):
        try: request,config=self.request_model(),self.build_config(); config.validate()
        except Exception as exc: QMessageBox.warning(self,"Invalid research request",str(exc)); return
        self.run_button.setEnabled(False); self.progress.setRange(0,0); self.stage.setText("Native research executing")
        self._thread=QThread(self); self._worker=RunWorker(self.service,request,config); self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run); self._worker.finished.connect(self._finished); self._worker.failed.connect(self._failed); self._worker.finished.connect(self._thread.quit); self._worker.failed.connect(self._thread.quit); self._thread.start()
    def _finished(self,result):
        self.run_button.setEnabled(True); self.progress.setRange(0,100); self.progress.setValue(100); self.stage.setText("COMPLETED"); self._run_dir=Path(result.output_dir); self._manifest,summary=self.service.completed_runs.read(self._run_dir); self.summary.setText("\n".join(f"{k}: {summary.get(k,'—')}" for k in ("ending_equity","net_pnl","total_return_percentage","total_trades","wins","losses","win_rate","total_net_r","average_net_r","profit_factor","maximum_drawdown_percentage","total_fees"))); self.quality.setText("Data quality: "+(result.data_quality.status.value if result.data_quality else "NOT AVAILABLE")); self.open_folder.setEnabled(True)
        for key,b in self.artifact_buttons.items(): b.setEnabled(key in self._manifest.get("artifacts",{}))
    def _failed(self,message): self.run_button.setEnabled(True); self.progress.setRange(0,100); self.stage.setText("FAILED: "+message)
    def open_artifact(self,key): QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.completed_runs.artifact_path(self._run_dir,self._manifest,key))))
    def _browse_output(self):
        p=QFileDialog.getExistingDirectory(self,"Output root",self.output_root.text());
        if p:self.output_root.setText(p)
    def save_config(self):
        p,_=QFileDialog.getSaveFileName(self,"Save native v3 config","research-v3.json","JSON (*.json)");
        if p:self.service.save_config(Path(p),self.build_config())
    def load_config(self):
        p,_=QFileDialog.getOpenFileName(self,"Load native v3 config","","JSON (*.json)");
        if p:self.apply_config(self.service.load_config(Path(p)))
    def start_post_show_tasks(self): pass
