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
        for lab,w in [("Stop Loss Multiple",self.sl),("Take Profit Multiple",self.tp),("Entry Mode",self.entry_mode),("Entry Interval",self.entry_interval),("Maximum Active Pairs",self.max_pairs),("Tie Policy",self.tie)]: strat.addRow(lab,w)
        self.entry_mode.currentTextChanged.connect(lambda t:self.entry_interval.setEnabled(t=="EVERY_N_CANDLES"))
        risk=group("Risk and Position Sizing")
        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line(); self.max_lev_combined=self._line(); self.missing_policy=QComboBox(); self.missing_policy.addItems(["ERROR","WARN_AND_USE_15M","WARN_AND_CONTINUE"]); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("0.5%")
        self.risk_formula=QLabel(); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        for lab,w in [("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Trading Start Date",self.trading_start),("Trading End Date",self.trading_end),("Maximum Leverage Per Leg",self.max_lev_leg),("Maximum Combined Leverage",self.max_lev_combined),("Missing Intrabar Policy",self.missing_policy),("",self.zero_cost),("R Percentage",self.percent_r),("Fixed R Distance",self.fixed_r),("Starting Equity",self.equity),("Risk Per Leg",self.risk_leg),("Formula",self.risk_formula),("Sizing",QLabel("Risk amount per leg = Current Equity × Risk Per Leg\nPosition quantity = Risk Amount ÷ Stop Distance")),("Combined Risk",self.risk_warn)]: risk.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic)
        fees=group("Fees and Execution")
        self.maker=self._line("0.02%"); self.taker=self._line("0.05%"); self.maker_entry=QCheckBox("Use Maker Fee for Entry"); self.maker_exit=QCheckBox("Use Maker Fee for Exit"); self.slippage=self._line("0.01%"); self.cost=QLabel()
        for lab,w in [("Maker Fee",self.maker),("Taker Fee",self.taker),("",self.maker_entry),("",self.maker_exit),("Slippage",self.slippage),("Round-trip Cost",self.cost)]: fees.addRow(lab,w)
        for w in [self.maker,self.taker,self.slippage]: w.textChanged.connect(self.update_dynamic)
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
        page=QWidget(); l=QVBoxLayout(page); self.chart_select=QComboBox(); self.chart_select.addItems(["equity_curve.png","drawdown.png","r_distribution.png","holding_time_distribution.png","monthly_returns.png"]); self.chart=QLabel(alignment=Qt.AlignCenter); self.chart.setMinimumHeight(400); r=QPushButton("Refresh Charts"); o=QPushButton("Open Chart File"); r.clicked.connect(self.refresh_chart); o.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir/"charts"/self.chart_select.currentText())))); self.chart_select.currentTextChanged.connect(self.refresh_chart); l.addWidget(self.chart_select); l.addWidget(self.chart); l.addWidget(r); l.addWidget(o); self.tabs.addTab(page,"Charts")
    def _build_log(self):
        page=QWidget(); l=QVBoxLayout(page); self.log=QTextEdit(readOnly=True); l.addWidget(self.log); row=QHBoxLayout();
        for name,fn in [("Copy Log",lambda:self.log.selectAll() or self.log.copy()),("Clear Log",self.log.clear),("Save Log",self.save_log)]: btn=QPushButton(name); btn.clicked.connect(fn); row.addWidget(btn)
        l.addLayout(row); self.tabs.addTab(page,"Log")
    def values(self):
        return {"run_name":self.run_name.text().strip(),"input_csv":self.input_csv.text(),"strategy_csv":self.input_csv.text(),"intrabar_csv":self.intrabar_csv.text(),"use_intrabar_data":self.use_intrabar.isChecked(),"trading_start_date":self.trading_start.text() or None,"trading_end_date":self.trading_end.text() or None,"max_effective_leverage_per_leg":self.max_lev_leg.text() or None,"max_combined_effective_leverage":self.max_lev_combined.text() or None,"intrabar_missing_policy":self.missing_policy.currentText(),"zero_cost_comparison":self.zero_cost.isChecked(),"output_dir":self.output_folder.text(),"sl_mult":self.sl.value(),"tp_mult":self.tp.value(),"entry_mode":self.entry_mode.currentText(),"entry_interval":self.entry_interval.value(),"max_active_pairs":self.max_pairs.value(),"tie_policy":self.tie.currentText(),"risk_mode":self.risk_mode.currentText(),"atr_period":self.atr_period.value(),"atr_multiplier":self.atr_mult.value(),"percent_r":parse_percentage(self.percent_r.text()),"fixed_r":self.fixed_r.value(),"initial_equity":self.equity.value(),"risk_per_leg":parse_percentage(self.risk_leg.text()),"maker_fee":parse_percentage(self.maker.text()),"taker_fee":parse_percentage(self.taker.text()),"use_maker_entry":self.maker_entry.isChecked(),"use_maker_exit":self.maker_exit.isChecked(),"slippage":parse_percentage(self.slippage.text())}
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
        keys=["total_pairs","wins","losses","flat_pairs","win_rate","loss_rate","average_net_r","median_net_r","total_net_r","profit_factor","ending_equity","total_return_percentage","maximum_drawdown","maximum_drawdown_percentage","maximum_consecutive_wins","maximum_consecutive_losses","average_holding_time","total_fees","ambiguous_event_count","average_combined_effective_leverage","maximum_combined_effective_leverage","total_fees","average_fees_as_percentage_of_expected_winning_profit"]
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
        self.zero_cost.setChecked(bool(values["zero_cost_comparison"]))
        self.percent_r.setText(format_percentage(float(values["percent_r"])))
        self.fixed_r.setValue(float(values["fixed_r"]))
        self.equity.setValue(float(values["initial_equity"]))
        self.risk_leg.setText(format_percentage(float(values["risk_per_leg"])))
        self.maker.setText(format_percentage(float(values["maker_fee"])))
        self.taker.setText(format_percentage(float(values["taker_fee"])))
        self.maker_entry.setChecked(bool(values["use_maker_entry"]))
        self.maker_exit.setChecked(bool(values["use_maker_exit"]))
        self.slippage.setText(format_percentage(float(values["slippage"])))
        self.update_dynamic()
        self.update_planned_output()
    def append_log(self,t): self.log.append(str(t))
    def save_log(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Log","backtest.log","Log (*.log *.txt)");
        if p: Path(p).write_text(self.log.toPlainText())
