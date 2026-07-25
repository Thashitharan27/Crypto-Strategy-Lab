"""Main PySide6 window for the backtester."""
from __future__ import annotations
import os, sys, time, traceback
from dataclasses import replace
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QSettings, QThread, QTimer, Qt, QSortFilterProxyModel, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import *

from loader import load_ohlcv_csv
from .config_logic import *
from .table_model import PandasTableModel
from .worker import BacktestWorker
from output_manager import planned_run_dir

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Long-Short Crypto Backtester"); self.resize(1200, 800)
        self.settings = QSettings("LongShortCrypto", "Backtester"); self.worker=None; self.thread=None; self.started=0; self.last_summary={}; self.output_dir=Path("output")
        self.tabs=QTabWidget(); self.setCentralWidget(self.tabs)
        self._build_config(); self._build_summary(); self._build_trades(); self._build_charts(); self._build_log(); self.reset_defaults(); self._restore_settings()
    def _line(self, text=""):
        w=QLineEdit(text); return w
    def _spin(self, v, mn=-1e12, mx=1e12, dec=6):
        s=QDoubleSpinBox(); s.setRange(mn,mx); s.setDecimals(dec); s.setValue(v); return s
    def _build_config(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); form=QVBoxLayout(inner); self.config_controls=[]
        def group(title): g=QGroupBox(title); l=QFormLayout(g); form.addWidget(g); return l
        data=group("Data")
        self.input_csv=self._line(); self.input_csv.setReadOnly(True); b=QPushButton("Browse"); b.clicked.connect(self.browse_csv); row=QHBoxLayout(); row.addWidget(self.input_csv); row.addWidget(b); data.addRow("15-Minute Strategy CSV", row)
        self.intrabar_csv=self._line(); self.intrabar_csv.setReadOnly(True); bi=QPushButton("Browse"); bi.clicked.connect(self.browse_intrabar_csv); row=QHBoxLayout(); row.addWidget(self.intrabar_csv); row.addWidget(bi); data.addRow("1-Minute Intrabar CSV", row)
        self.use_intrabar=QCheckBox("Use 1-minute data for exit resolution"); self.use_intrabar.setChecked(True); data.addRow("", self.use_intrabar)
        data.addRow(QLabel("ATR, entry price, SL, and TP are calculated from 15-minute candles.\n1-minute candles are used only to determine the exact exit sequence.\nFees are charged on full notional, not margin; leverage changes required margin but does not reduce trading fees."))
        self.run_name=self._line(); self.run_name.setPlaceholderText("Optional run name prefix"); data.addRow("Run Name", self.run_name)
        self.output_folder=self._line(); self.output_folder.setReadOnly(True); bo=QPushButton("Browse"); bo.clicked.connect(self.browse_output); row=QHBoxLayout(); row.addWidget(self.output_folder); row.addWidget(bo); data.addRow("Output Folder", row)
        self.planned_output=QLabel("Output run folder: not calculated yet"); self.planned_output.setWordWrap(True); data.addRow("Next Run Folder", self.planned_output)
        self.dataset_info=QLabel("No CSV loaded."); data.addRow("Dataset Information", self.dataset_info); val=QPushButton("Validate Data"); val.clicked.connect(self.validate_data); data.addRow(val)
        strat=group("Strategy")
        self.sl=self._spin(2,0); self.tp=self._spin(3,0); self.entry_mode=QComboBox(); self.entry_mode.addItems(["WAIT_UNTIL_CLOSED","EVERY_N_CANDLES","CUSTOM"]); self.entry_interval=QSpinBox(); self.entry_interval.setRange(1,999999); self.max_pairs=QSpinBox(); self.max_pairs.setRange(1,999999); self.tie=QComboBox(); self.tie.addItems(["PESSIMISTIC","OPTIMISTIC"])
        self.both_timeout=QCheckBox("Enable Both-Open Timeout"); self.both_timeout_duration=QSpinBox(); self.both_timeout_duration.setRange(1,999999); self.both_timeout_unit=QComboBox(); self.both_timeout_unit.addItems(["Hours","Minutes"]); timeout_row=QHBoxLayout(); timeout_row.addWidget(self.both_timeout_duration); timeout_row.addWidget(self.both_timeout_unit); self.both_timeout_help=QLabel("If both long and short remain open beyond this time, both positions are\nclosed and a new pair may open at the next eligible 15-minute candle.\n\nThis rule does not apply after one leg has already closed."); self.both_timeout_help.setWordWrap(True)
        for lab,w in [("Stop Loss Multiple",self.sl),("Take Profit Multiple",self.tp),("Entry Mode",self.entry_mode),("Entry Interval",self.entry_interval),("Maximum Active Pairs",self.max_pairs),("Tie Policy",self.tie),("",self.both_timeout),("Maximum Both-Open Time",timeout_row),("",self.both_timeout_help)]: strat.addRow(lab,w)
        self.enable_trailing_profit=QCheckBox("Enable Trailing Profit")
        self.enable_trailing_profit.setToolTip("Replace fixed TP with an R-based profit-locking trailing stop.")
        self.trail_activation_r=self._spin(3.0,0.000001); self.trail_activation_r.setToolTip("Favourable move, in the trade's existing R, required to activate trailing.")
        self.trail_distance_r=self._spin(1.0,0.000001); self.trail_distance_r.setToolTip("Distance behind the favourable extreme, using the same stored trade R.")
        self.trail_apply_to=QComboBox(); self.trail_apply_to.addItems(["BOTH","LONG_ONLY","SHORT_ONLY"]); self.trail_apply_to.setToolTip("Choose which independently managed leg uses trailing profit.")
        self.trail_intrabar_mode=QComboBox(); self.trail_intrabar_mode.addItems(["PESSIMISTIC","OPTIMISTIC"]); self.trail_intrabar_mode.setToolTip("Pessimistic tests the prior stop first; optimistic updates from the favourable extreme first.")
        for lab,w in [("",self.enable_trailing_profit),("Trailing Activation (R)",self.trail_activation_r),("Trailing Distance (R)",self.trail_distance_r),("Apply Trailing To",self.trail_apply_to),("Intrabar Trailing Mode",self.trail_intrabar_mode)]: strat.addRow(lab,w)
        self.entry_mode.currentTextChanged.connect(lambda t:self.entry_interval.setEnabled(t=="EVERY_N_CANDLES"))
        sched=group("Entry Schedule")
        self.enable_daily_schedule=QCheckBox("Enable Daily Scheduled Entry")
        self.daily_entry_time=self._line("00:00")
        self.daily_entry_timezone=self._line("UTC")
        self.daily_entry_missed_policy=QComboBox(); self.daily_entry_missed_policy.addItems(["SKIP_DAY","NEXT_AVAILABLE_CANDLE"])
        self.next_entry_summary=QLabel("Next eligible entry time: 00:00 UTC when enabled"); self.next_entry_summary.setWordWrap(True)
        help_text=QLabel("When enabled, the strategy attempts an entry once per day at the selected time.\n\nIf a trade is open at that time and SKIP_DAY is selected, no entry is opened later that day."); help_text.setWordWrap(True)
        for lab,w in [("",self.enable_daily_schedule),("Daily Entry Time",self.daily_entry_time),("Entry Timezone",self.daily_entry_timezone),("Missed Entry Policy",self.daily_entry_missed_policy),("Summary",self.next_entry_summary),("",help_text)]: sched.addRow(lab,w)
        self.enable_daily_schedule.toggled.connect(self.update_dynamic)
        self.both_timeout.toggled.connect(self.both_timeout_duration.setEnabled); self.both_timeout.toggled.connect(self.both_timeout_unit.setEnabled)
        risk=group("Risk and Position Sizing")
        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line(); self.max_lev_combined=self._line(); self.missing_policy=QComboBox(); self.missing_policy.addItems(["ERROR","WARN_AND_USE_15M","WARN_AND_CONTINUE"]); self.trade_direction=QComboBox(); self.trade_direction.addItems(["BOTH","LONG_ONLY","SHORT_ONLY","BOTH_INDEPENDENT"]); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("0.5%")
        self.risk_formula=QLabel(); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        for lab,w in [("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Trading Start Date",self.trading_start),("Trading End Date",self.trading_end),("Maximum Leverage Per Leg",self.max_lev_leg),("Maximum Combined Leverage",self.max_lev_combined),("Missing Intrabar Policy",self.missing_policy),("Trade Direction",self.trade_direction),("",self.zero_cost),("R Percentage",self.percent_r),("Fixed R Distance",self.fixed_r),("Starting Equity",self.equity),("Risk Per Leg",self.risk_leg),("Formula",self.risk_formula),("Sizing",QLabel("Risk amount per leg = Current Equity × Risk Per Leg\nPosition quantity = Risk Amount ÷ Stop Distance")),("Combined Risk",self.risk_warn)]: risk.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic)
        trend=group("Trend Filter")
        self.enable_adx=QCheckBox("Enable ADX Filter"); self.adx_period=QSpinBox(); self.adx_period.setRange(1,99999); self.adx_mode=QComboBox(); self.adx_mode.addItems(["Disabled","ADX <= Maximum","ADX >= Minimum","Range"]); self.adx_max=self._spin(25,0); self.adx_min=self._spin(20,0)
        for lab,w in [("",self.enable_adx),("ADX Period",self.adx_period),("Filter Mode",self.adx_mode),("Maximum ADX",self.adx_max),("Minimum ADX",self.adx_min)]: trend.addRow(lab,w)
        self.enable_adx.toggled.connect(self.update_dynamic); self.adx_mode.currentTextChanged.connect(self.update_dynamic)
        compression=group("Market Compression Filters")
        self.enable_bb_width=QCheckBox("Enable Bollinger Width Filter"); self.bb_width_mode=QComboBox(); self.bb_width_mode.addItems(["Disabled","Maximum Width","Minimum Width","Range"]); self.bb_width_min=self._spin(0,0); self.bb_width_max=self._spin(0.03,0)
        self.enable_di_spread=QCheckBox("Enable DI Spread Filter"); self.di_spread_mode=QComboBox(); self.di_spread_mode.addItems(["Disabled","Maximum Spread","Minimum Spread","Range"]); self.di_spread_min=self._spin(0,0); self.di_spread_max=self._spin(10,0)
        for lab,w in [("",self.enable_bb_width),("Bollinger Width Mode",self.bb_width_mode),("Minimum Width",self.bb_width_min),("Maximum Width",self.bb_width_max),("",self.enable_di_spread),("DI Spread Mode",self.di_spread_mode),("Minimum Spread",self.di_spread_min),("Maximum Spread",self.di_spread_max)]: compression.addRow(lab,w)
        for w in [self.enable_bb_width,self.bb_width_mode,self.enable_di_spread,self.di_spread_mode]: w.toggled.connect(self.update_dynamic) if hasattr(w,"toggled") else w.currentTextChanged.connect(self.update_dynamic)
        telemetry=group("Trade Telemetry")
        self.enable_trade_telemetry=QCheckBox("Enable Trade Telemetry"); self.telemetry_interval=QSpinBox(); self.telemetry_interval.setRange(1,999999); self.telemetry_interval.setSuffix(" minutes"); self.save_full_telemetry=QCheckBox("Save Full Telemetry CSV"); self.save_journey_summary=QCheckBox("Save Journey Summary"); self.save_journey_charts=QCheckBox("Save Journey Charts"); self.telemetry_estimate=QLabel("Estimated telemetry rows: calculated after data validation when practical."); self.telemetry_estimate.setWordWrap(True)
        telemetry.addRow(QLabel("Records how ATR, ADX, DI Spread, and Bollinger Band Width change while each trade is active."));
        for lab,w in [("",self.enable_trade_telemetry),("Telemetry Interval",self.telemetry_interval),("",self.save_full_telemetry),("",self.save_journey_summary),("",self.save_journey_charts),("Estimate",self.telemetry_estimate)]: telemetry.addRow(lab,w)
        self.enable_trade_telemetry.toggled.connect(self.update_dynamic); self.telemetry_interval.valueChanged.connect(self.update_dynamic)
        fees=group("Fees and Execution")
        self.maker=self._line("0.02%"); self.taker=self._line("0.05%"); self.maker_entry=QCheckBox("Use Maker Fee for Entry"); self.maker_exit=QCheckBox("Use Maker Fee for Exit"); self.slippage=self._line("0.01%"); self.cost=QLabel()
        for lab,w in [("Maker Fee",self.maker),("Taker Fee",self.taker),("",self.maker_entry),("",self.maker_exit),("Slippage",self.slippage),("Round-trip Cost",self.cost)]: fees.addRow(lab,w)
        for w in [self.maker,self.taker,self.slippage]: w.textChanged.connect(self.update_dynamic)
        be_rule=group("Break-Even After Opposite SL")
        self.be_after_sl=QCheckBox("Enable BE After Opposite SL"); self.be_mode=QComboBox(); self.be_mode.addItems(["ENTRY_PRICE","COST_ADJUSTED","R_OFFSET"]); self.be_offset=self._spin(0,0); self.be_same_candle=QComboBox(); self.be_same_candle.addItems(["NEXT_CANDLE","PESSIMISTIC"]); self.be_help=QLabel("When one leg hits SL, the still-open opposite leg keeps its TP but its SL\nmoves to break-even.\n\nEntry-price break-even does not recover fees or slippage."); self.be_help.setWordWrap(True)
        for lab,w in [("",self.be_after_sl),("BE Mode",self.be_mode),("BE Offset in R",self.be_offset),("Same-Candle BE Policy",self.be_same_candle),("",self.be_help)]: be_rule.addRow(lab,w)
        self.be_mode.currentTextChanged.connect(lambda t:self.be_offset.setEnabled(t=="R_OFFSET"))
        be=group("Break-Even Calculator")
        self.be_label=QLabel(); self.be_label.setWordWrap(True); be.addRow(self.be_label)
        controls=group("Backtest Controls")
        self.run_btn=QPushButton("Run Backtest"); self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setEnabled(False); self.open_btn=QPushButton("Open Output Folder"); self.save_btn=QPushButton("Save Configuration"); self.load_btn=QPushButton("Load Configuration"); self.reset_btn=QPushButton("Reset Defaults")
        for w in [self.run_btn,self.cancel_btn,self.open_btn,self.save_btn,self.load_btn,self.reset_btn]: controls.addRow(w)
        self.progress=QProgressBar(); self.status=QLabel("Ready"); self.elapsed=QLabel("Elapsed: 0s"); controls.addRow(self.progress); controls.addRow(self.status); controls.addRow(self.elapsed)
        for w in [self.run_name,self.output_folder]: w.textChanged.connect(self.update_planned_output)
        self.run_btn.clicked.connect(self.run_backtest); self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel()); self.open_btn.clicked.connect(lambda: os.startfile(str(self.output_dir)) if sys.platform.startswith("win") else os.system(f'xdg-open "{self.output_dir}"'))
        self.save_btn.clicked.connect(self.save_config); self.load_btn.clicked.connect(self.load_config); self.reset_btn.clicked.connect(self.reset_defaults)
        scroll.setWidget(inner); outer.addWidget(scroll); self.tabs.addTab(page,"Configuration"); self.config_controls=inner.findChildren(QWidget); self.update_dynamic()
    def _build_summary(self):
        page=QWidget(); l=QVBoxLayout(page); self.summary_table=QTableWidget(0,2); self.summary_table.setHorizontalHeaderLabels(["Metric","Value"]); self.combo_table=QTableWidget(0,5); self.combo_table.setHorizontalHeaderLabels(["Exit Combination","Count","Percentage","Average Net R","Total Net R"]); self.combo_table.setSortingEnabled(True); l.addWidget(QLabel("Results")); l.addWidget(self.summary_table); l.addWidget(QLabel("Exit Combination Table")); l.addWidget(self.combo_table); self.tabs.addTab(page,"Summary")
    def _build_trades(self):
        page=QWidget(); l=QVBoxLayout(page); self.filter=QLineEdit(); self.filter.setPlaceholderText("Text filter"); self.trade_model=PandasTableModel(); self.proxy=QSortFilterProxyModel(); self.proxy.setSourceModel(self.trade_model); self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive); self.proxy.setFilterKeyColumn(-1); self.filter.textChanged.connect(self.proxy.setFilterFixedString); self.trade_view=QTableView(); self.trade_view.setModel(self.proxy); self.trade_view.setSortingEnabled(True); exp=QPushButton("Export Filtered Trades"); exp.clicked.connect(self.export_filtered); l.addWidget(self.filter); l.addWidget(self.trade_view); l.addWidget(exp); self.tabs.addTab(page,"Trades")
    def _build_charts(self):
        page=QWidget(); l=QVBoxLayout(page); self.chart_select=QComboBox(); self.chart_select.addItems(["equity_curve.png","drawdown.png","r_distribution.png","holding_time_distribution.png","adx_distribution.png","adx_vs_pnl.png","bb_width_histogram.png","di_spread_histogram.png","bb_width_vs_pnl.png","di_spread_vs_pnl.png","monthly_returns.png"]); self.chart=QLabel(alignment=Qt.AlignCenter); self.chart.setMinimumHeight(400); r=QPushButton("Refresh Charts"); o=QPushButton("Open Chart File"); r.clicked.connect(self.refresh_chart); o.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir/"charts"/self.chart_select.currentText())))); self.chart_select.currentTextChanged.connect(self.refresh_chart); l.addWidget(self.chart_select); l.addWidget(self.chart); l.addWidget(r); l.addWidget(o); self.tabs.addTab(page,"Charts")
    def _build_log(self):
        page=QWidget(); l=QVBoxLayout(page); self.log=QTextEdit(readOnly=True); l.addWidget(self.log); row=QHBoxLayout();
        for name,fn in [("Copy Log",lambda:self.log.selectAll() or self.log.copy()),("Clear Log",self.log.clear),("Save Log",self.save_log)]: btn=QPushButton(name); btn.clicked.connect(fn); row.addWidget(btn)
        l.addLayout(row); self.tabs.addTab(page,"Log")
    def values(self):
        return {"run_name":self.run_name.text().strip(),"input_csv":self.input_csv.text(),"strategy_csv":self.input_csv.text(),"intrabar_csv":self.intrabar_csv.text(),"use_intrabar_data":self.use_intrabar.isChecked(),"trading_start_date":self.trading_start.text() or None,"trading_end_date":self.trading_end.text() or None,"max_effective_leverage_per_leg":self.max_lev_leg.text() or None,"max_combined_effective_leverage":self.max_lev_combined.text() or None,"intrabar_missing_policy":self.missing_policy.currentText(),"zero_cost_comparison":self.zero_cost.isChecked(),"trade_direction":self.trade_direction.currentText(),"enable_trailing_profit":self.enable_trailing_profit.isChecked(),"trail_activation_r":self.trail_activation_r.value(),"trail_distance_r":self.trail_distance_r.value(),"trail_apply_to":self.trail_apply_to.currentText(),"trail_intrabar_mode":self.trail_intrabar_mode.currentText(),"output_dir":self.output_folder.text(),"sl_mult":self.sl.value(),"tp_mult":self.tp.value(),"entry_mode":self.entry_mode.currentText(),"entry_interval":self.entry_interval.value(),"enable_daily_entry_schedule":self.enable_daily_schedule.isChecked(),"daily_entry_time":self.daily_entry_time.text().strip(),"daily_entry_timezone":self.daily_entry_timezone.text().strip(),"daily_entry_missed_policy":self.daily_entry_missed_policy.currentText(),"max_active_pairs":self.max_pairs.value(),"tie_policy":self.tie.currentText(),"risk_mode":self.risk_mode.currentText(),"atr_period":self.atr_period.value(),"atr_multiplier":self.atr_mult.value(),"percent_r":parse_percentage(self.percent_r.text()),"fixed_r":self.fixed_r.value(),"initial_equity":self.equity.value(),"risk_per_leg":parse_percentage(self.risk_leg.text()),"maker_fee":parse_percentage(self.maker.text()),"taker_fee":parse_percentage(self.taker.text()),"use_maker_entry":self.maker_entry.isChecked(),"use_maker_exit":self.maker_exit.isChecked(),"slippage":parse_percentage(self.slippage.text()),"enable_both_open_timeout":self.both_timeout.isChecked(),"max_both_open_minutes":self.both_timeout_duration.value()*(60 if self.both_timeout_unit.currentText()=="Hours" else 1),"both_open_timeout_unit":self.both_timeout_unit.currentText(),"enable_adx_filter":self.enable_adx.isChecked(),"adx_period":self.adx_period.value(),"adx_filter_mode":self.adx_mode.currentText(),"adx_maximum":self.adx_max.value(),"adx_minimum":self.adx_min.value(),"enable_bb_width_filter":self.enable_bb_width.isChecked(),"bb_width_filter_mode":self.bb_width_mode.currentText(),"bb_width_maximum":self.bb_width_max.value(),"bb_width_minimum":self.bb_width_min.value(),"enable_di_spread_filter":self.enable_di_spread.isChecked(),"di_spread_filter_mode":self.di_spread_mode.currentText(),"di_spread_maximum":self.di_spread_max.value(),"di_spread_minimum":self.di_spread_min.value(),"enable_be_after_opposite_sl":self.be_after_sl.isChecked(),"be_mode":self.be_mode.currentText(),"be_offset_r":self.be_offset.value(),"be_same_candle_policy":self.be_same_candle.currentText(),"enable_trade_telemetry":self.enable_trade_telemetry.isChecked(),"save_full_telemetry_csv":self.save_full_telemetry.isChecked(),"save_trade_journey_summary":self.save_journey_summary.isChecked(),"save_trade_journey_charts":self.save_journey_charts.isChecked(),"telemetry_interval_minutes":self.telemetry_interval.value()}
    def reset_defaults(self):
        self.apply_values(default_gui_config())
    def _restore_settings(self):
        self.input_csv.setText(self.settings.value("last_csv", self.input_csv.text())); self.output_folder.setText(self.settings.value("last_output", self.output_folder.text()))
    def browse_csv(self):
        p,_=QFileDialog.getOpenFileName(self,"Select CSV",self.input_csv.text(),"CSV files (*.csv)");
        if p: self.input_csv.setText(p); self.settings.setValue("last_csv",p); self.validate_data()
    def browse_intrabar_csv(self):
        p,_=QFileDialog.getOpenFileName(self,"Select Intrabar CSV",self.intrabar_csv.text(),"CSV files (*.csv)");
        if p: self.intrabar_csv.setText(p)
    def browse_output(self):
        p=QFileDialog.getExistingDirectory(self,"Select Output Folder",self.output_folder.text());
        if p: self.output_folder.setText(p); self.settings.setValue("last_output",p)
    def validate_data(self):
        try:
            df=load_ohlcv_csv(self.input_csv.text(), expected_timeframe_minutes=15, label="Strategy data"); sm=df.attrs.get("summary"); miss=sm.missing_candles; tf=f"{sm.detected_timeframe_minutes} minutes"; self.dataset_info.setText(f"Total candles: {len(df):,}\nStart date: {df.timestamp.min()}\nEnd date: {df.timestamp.max()}\nDetected timeframe: {tf}\nMissing candles: {miss}\nRows removed: see log/console\nDuplicate candles removed: see log/console"); self.append_log("Data validation passed."); return True
        except Exception as e: QMessageBox.warning(self,"Invalid CSV",str(e)); self.append_log(traceback.format_exc()); return False
    def update_planned_output(self):
        try:
            cfg=build_backtest_config(self.values(), require_paths=False); self.planned_output.setText(str(planned_run_dir(cfg).resolve()))
        except Exception:
            self.planned_output.setText("Output run folder: unavailable until configuration is valid")
    def update_dynamic(self):
        m=getattr(self,'risk_mode',None) and self.risk_mode.currentText(); self.atr_period.setVisible(m=="ATR"); self.atr_mult.setVisible(m=="ATR"); self.percent_r.setVisible(m=="PERCENT"); self.fixed_r.setVisible(m=="FIXED"); self.risk_formula.setText({"ATR":"R = ATR × ATR Multiplier","PERCENT":"R = Entry Price × Percentage","FIXED":"R = Fixed Price Distance"}.get(m,""));
        try: r=parse_percentage(self.risk_leg.text()); self.risk_warn.setText(f"Combined Risk Per Pair = {format_percentage(r*2,2)}" + (" WARNING: exceeds 5%." if r*2>0.05 else ""))
        except Exception: pass
        if hasattr(self,"enable_daily_schedule"):
            en=self.enable_daily_schedule.isChecked(); self.daily_entry_time.setEnabled(en); self.daily_entry_timezone.setEnabled(en); self.daily_entry_missed_policy.setEnabled(en); self.next_entry_summary.setText(f"Next eligible entry time: {self.daily_entry_time.text() or '00:00'} {self.daily_entry_timezone.text() or 'UTC'}" if en else "Daily schedule disabled; existing entry mode controls entries.")
        if hasattr(self,"enable_trade_telemetry"):
            enabled=self.enable_trade_telemetry.isChecked(); self.telemetry_interval.setEnabled(enabled); self.save_full_telemetry.setEnabled(enabled); self.save_journey_summary.setEnabled(enabled); self.save_journey_charts.setEnabled(enabled)
        if hasattr(self,"adx_mode"):
            enabled=self.enable_adx.isChecked() and self.adx_mode.currentText() != "Disabled"
            self.adx_period.setEnabled(self.enable_adx.isChecked())
            self.adx_mode.setEnabled(self.enable_adx.isChecked())
            self.adx_max.setEnabled(enabled and self.adx_mode.currentText() in ("ADX <= Maximum","Range"))
            self.adx_min.setEnabled(enabled and self.adx_mode.currentText() in ("ADX >= Minimum","Range"))
        if hasattr(self,"bb_width_mode"):
            bben=self.enable_bb_width.isChecked() and self.bb_width_mode.currentText() != "Disabled"
            self.bb_width_mode.setEnabled(self.enable_bb_width.isChecked()); self.bb_width_max.setEnabled(bben and self.bb_width_mode.currentText() in ("Maximum Width","Range")); self.bb_width_min.setEnabled(bben and self.bb_width_mode.currentText() in ("Minimum Width","Range"))
            dien=self.enable_di_spread.isChecked() and self.di_spread_mode.currentText() != "Disabled"
            self.di_spread_mode.setEnabled(self.enable_di_spread.isChecked()); self.di_spread_max.setEnabled(dien and self.di_spread_mode.currentText() in ("Maximum Spread","Range")); self.di_spread_min.setEnabled(dien and self.di_spread_mode.currentText() in ("Minimum Spread","Range"))
        try: cost=(parse_percentage(self.maker.text())+parse_percentage(self.taker.text()))*2; self.cost.setText(f"Approx. long entry + long exit + short entry + short exit: {format_percentage(cost,4)}. Actual cost varies based on exit price and quantity.")
        except Exception: pass
        try: be=theoretical_break_even(self.sl.value(),self.tp.value()); actual=self.last_summary.get('win_rate'); diff="n/a" if actual is None else format_percentage(actual-be,2); self.be_label.setText(f"Theoretical break-even before fees: {format_percentage(be,2)}\nActual backtest win rate: {format_percentage(actual,2) if actual is not None else 'n/a'}\nDifference from break-even: {diff}\nThe theoretical value assumes every winner is exactly one TP and one SL. Fees, slippage, end-of-data exits, and other outcomes increase the actual required win rate.")
        except Exception: pass
    def run_backtest(self):
        try: vals=self.values(); cfg=build_backtest_config(vals); Path(vals['output_dir']).mkdir(parents=True,exist_ok=True); cfg=replace(cfg, output_run_dir=planned_run_dir(cfg)); self.planned_output.setText(str(cfg.output_run_dir.resolve()))
        except Exception as e: QMessageBox.warning(self,"Validation Problems",str(e)); return
        if not self.validate_data(): return
        self.output_dir=cfg.output_run_dir; self.thread=QThread(); self.worker=BacktestWorker(cfg); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.status.connect(self.on_status); self.worker.log.connect(self.append_log); self.worker.finished.connect(self.on_finished); self.worker.failed.connect(self.on_failed); self.started=time.time(); self.cancel_btn.setEnabled(True); self.run_btn.setEnabled(False); self.thread.start()
    def on_status(self,s,p): self.status.setText(s); self.progress.setValue(p); self.elapsed.setText(f"Elapsed: {int(time.time()-self.started)}s")
    def on_finished(self,summary,trades,equity,out): self.last_summary=summary; self.output_dir=Path(out); self.populate_summary(summary); self.trade_model.set_dataframe(trades); self.refresh_chart(); self.cleanup_thread(); self.update_dynamic()
    def on_failed(self,msg,tb): QMessageBox.critical(self,"Backtest Error",msg); self.append_log(tb); self.cleanup_thread()
    def cleanup_thread(self): self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False); self.thread.quit(); self.thread.wait(); self.thread=None; self.worker=None
    def populate_summary(self,s):
        keys=["trade_direction","total_pairs","total_trades","wins","losses","flat_pairs","win_rate","loss_rate","average_net_r","median_net_r","total_net_r","profit_factor","ending_equity","total_return_percentage","maximum_drawdown","maximum_drawdown_percentage","maximum_consecutive_wins","maximum_consecutive_losses","average_holding_time","expectancy","average_winner","average_loser","total_fees","ambiguous_event_count","average_combined_effective_leverage","maximum_combined_effective_leverage","total_fees","pairs_closed_by_both_open_timeout","pairs_where_be_was_triggered","remaining_legs_stopped_at_be","remaining_legs_reaching_tp_after_be_move","average_pnl_of_be_triggered_pairs","total_pnl_of_be_triggered_pairs","double_sl_count_prevented","be_same_candle_ambiguity_count","average_timeout_pair_pnl","total_timeout_pair_pnl","timeout_pairs_profitable","timeout_pairs_losing","average_fees_as_percentage_of_expected_winning_profit","scheduled_entry_opportunities","trades_opened_on_schedule","scheduled_entries_skipped_because_trade_was_open","scheduled_entries_skipped_by_filters","scheduled_entries_skipped_due_to_missing_data","average_entry_delay","maximum_entry_delay","days_with_trades","days_without_trades","signals_evaluated","signals_skipped_by_adx","signals_traded","average_adx_of_winning_trades","average_adx_of_losing_trades","average_plus_di_of_winners","average_plus_di_of_losers","average_minus_di_of_winners","average_minus_di_of_losers"]
        self.summary_table.setRowCount(len(keys)+1); vals={**s,"starting_equity":self.equity.value()}; keys.insert(10,"starting_equity")
        for r,k in enumerate(keys): self.summary_table.setItem(r,0,QTableWidgetItem(k)); v=vals.get(k,""); txt=format_percentage(v) if "rate" in k else (f"{v:.4f}R" if k.endswith("net_r") else str(v)); self.summary_table.setItem(r,1,QTableWidgetItem(txt))
        combos=s.get("exit_combinations",{}); self.combo_table.setRowCount(len(combos))
        for r,(k,v) in enumerate(combos.items()):
            for c,x in enumerate([k,v['count'],format_percentage(v['percentage'],2),f"{v['average_net_r']:.4f}R",f"{v['total_net_r']:.4f}R"]): self.combo_table.setItem(r,c,QTableWidgetItem(str(x)))
    def refresh_chart(self):
        p=self.output_dir/"charts"/self.chart_select.currentText(); self.chart.setPixmap(QPixmap(str(p)).scaled(self.chart.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation)) if p.exists() else self.chart.setText(f"Chart not found: {p}")
    def export_filtered(self):
        p,_=QFileDialog.getSaveFileName(self,"Export Filtered Trades","filtered_trades.csv","CSV (*.csv)");
        if p: self.trade_model.dataframe.to_csv(p,index=False)
    def save_config(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Configuration","backtest_config.json","JSON (*.json)");
        if p: save_config_json(p,self.values())
    def load_config(self):
        p,_=QFileDialog.getOpenFileName(self,"Load Configuration","","JSON (*.json)");
        if p: self.apply_values(load_config_json(p))
    def apply_values(self,d):
        values = {**default_gui_config(), **d}
        self.run_name.setText(str(values.get("run_name", "")))
        self.input_csv.setText(str(values["input_csv"]))
        self.intrabar_csv.setText(str(values["intrabar_csv"]))
        self.use_intrabar.setChecked(bool(values["use_intrabar_data"]))
        self.output_folder.setText(str(values["output_dir"]))
        self.sl.setValue(float(values["sl_mult"]))
        self.tp.setValue(float(values["tp_mult"]))
        self.entry_mode.setCurrentText(values["entry_mode"])
        self.entry_interval.setValue(int(values["entry_interval"]))
        self.enable_daily_schedule.setChecked(bool(values.get("enable_daily_entry_schedule", False)))
        self.daily_entry_time.setText(str(values.get("daily_entry_time", "00:00")))
        self.daily_entry_timezone.setText(str(values.get("daily_entry_timezone", "UTC")))
        self.daily_entry_missed_policy.setCurrentText(str(values.get("daily_entry_missed_policy", "SKIP_DAY")))
        self.max_pairs.setValue(int(values["max_active_pairs"]))
        self.tie.setCurrentText(values["tie_policy"])
        self.risk_mode.setCurrentText(values["risk_mode"])
        self.atr_period.setValue(int(values["atr_period"]))
        self.atr_mult.setValue(float(values["atr_multiplier"]))
        self.trading_start.setText(str(values["trading_start_date"] or ""))
        self.trading_end.setText(str(values["trading_end_date"] or ""))
        self.max_lev_leg.setText(str(values["max_effective_leverage_per_leg"] or ""))
        self.max_lev_combined.setText(str(values["max_combined_effective_leverage"] or ""))
        self.missing_policy.setCurrentText(values["intrabar_missing_policy"])
        self.zero_cost.setChecked(bool(values["zero_cost_comparison"])); self.trade_direction.setCurrentText(str(values.get("trade_direction", "BOTH"))); self.enable_trailing_profit.setChecked(bool(values.get("enable_trailing_profit",False))); self.trail_activation_r.setValue(float(values.get("trail_activation_r",3))); self.trail_distance_r.setValue(float(values.get("trail_distance_r",1))); self.trail_apply_to.setCurrentText(str(values.get("trail_apply_to","BOTH"))); self.trail_intrabar_mode.setCurrentText(str(values.get("trail_intrabar_mode","PESSIMISTIC")))
        self.percent_r.setText(format_percentage(float(values["percent_r"])))
        self.fixed_r.setValue(float(values["fixed_r"]))
        self.equity.setValue(float(values["initial_equity"]))
        self.risk_leg.setText(format_percentage(float(values["risk_per_leg"])))
        self.maker.setText(format_percentage(float(values["maker_fee"])))
        self.taker.setText(format_percentage(float(values["taker_fee"])))
        self.maker_entry.setChecked(bool(values["use_maker_entry"]))
        self.maker_exit.setChecked(bool(values["use_maker_exit"]))
        self.slippage.setText(format_percentage(float(values["slippage"])))
        self.enable_adx.setChecked(bool(values.get("enable_adx_filter", False))); self.adx_period.setValue(int(values.get("adx_period", 14))); self.adx_mode.setCurrentText(values.get("adx_filter_mode", "Disabled")); self.adx_max.setValue(float(values.get("adx_maximum", 25.0))); self.adx_min.setValue(float(values.get("adx_minimum", 20.0)))
        self.enable_bb_width.setChecked(bool(values.get("enable_bb_width_filter", False))); self.bb_width_mode.setCurrentText(values.get("bb_width_filter_mode", "Disabled")); self.bb_width_max.setValue(float(values.get("bb_width_maximum", 0.03))); self.bb_width_min.setValue(float(values.get("bb_width_minimum", 0.0)))
        self.enable_di_spread.setChecked(bool(values.get("enable_di_spread_filter", False))); self.di_spread_mode.setCurrentText(values.get("di_spread_filter_mode", "Disabled")); self.di_spread_max.setValue(float(values.get("di_spread_maximum", 10.0))); self.di_spread_min.setValue(float(values.get("di_spread_minimum", 0.0)))
        self.both_timeout.setChecked(bool(values.get("enable_both_open_timeout", False)))
        mins=int(values.get("max_both_open_minutes", 480)); unit=values.get("both_open_timeout_unit") or ("Hours" if mins % 60 == 0 else "Minutes")
        self.both_timeout_unit.setCurrentText(unit); self.both_timeout_duration.setValue(max(1, mins//60 if unit=="Hours" else mins))
        self.both_timeout_duration.setEnabled(self.both_timeout.isChecked()); self.both_timeout_unit.setEnabled(self.both_timeout.isChecked())
        self.enable_trade_telemetry.setChecked(bool(values.get("enable_trade_telemetry", True))); self.telemetry_interval.setValue(int(values.get("telemetry_interval_minutes", 15))); self.save_full_telemetry.setChecked(bool(values.get("save_full_telemetry_csv", True))); self.save_journey_summary.setChecked(bool(values.get("save_trade_journey_summary", True))); self.save_journey_charts.setChecked(bool(values.get("save_trade_journey_charts", True)))
        self.be_after_sl.setChecked(bool(values.get("enable_be_after_opposite_sl", False)))
        self.be_mode.setCurrentText(values.get("be_mode", "ENTRY_PRICE")); self.be_offset.setValue(float(values.get("be_offset_r", 0.0))); self.be_same_candle.setCurrentText(values.get("be_same_candle_policy", "NEXT_CANDLE")); self.be_offset.setEnabled(self.be_mode.currentText()=="R_OFFSET")
        self.update_dynamic()
        self.update_planned_output()
    def append_log(self,t): self.log.append(str(t))
    def save_log(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Log","backtest.log","Log (*.log *.txt)");
        if p: Path(p).write_text(self.log.toPlainText())
