"""Main PySide6 window for the backtester."""
from __future__ import annotations
import re, time, traceback
from dataclasses import replace
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QSettings, QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import *

from crypto_strategy_lab.loader import load_ohlcv_csv
from .config_logic import *
from .worker import BacktestWorker
from .portfolio_worker import PortfolioWorker
from .profile_editor import StrategyProfilesWidget
from .chatgpt_connection import ChatGPTIntegrationWidget
from .github_manager import GitHubIntegrationWidget
from crypto_strategy_lab.output_manager import planned_run_dir
from crypto_strategy_lab.support_resistance_analysis import build_sr_event_context_summary
from crypto_strategy_lab.report_workbooks import build_performance_breakdowns
from ..paths import DATA_DIR

REPORT_TARGETS = {
    "backtest": "backtest_report.xlsx", "indicators": "indicator_analysis.xlsx",
    "sr": "support_resistance_analysis.xlsx", "trades": "trade_list.csv",
    "charts": "charts", "output": ".",
}


def report_button_states(run_dir: Path) -> dict[str, bool]:
    """Return report availability independently of Qt for easy UI testing."""
    return {name: (run_dir / relative).exists() for name, relative in REPORT_TARGETS.items()}

class PolicyComboBox(QComboBox):
    """Show friendly policy labels while preserving stable config values."""
    def currentText(self):
        return str(self.currentData() or "")
    def setCurrentText(self,value):
        self.setCurrentIndex(max(0,self.findData(value)))

class MainWindow(QMainWindow):
    def __init__(self, startup_status=None):
        super().__init__(); self.setWindowTitle("Crypto Strategy Lab"); self.resize(1280, 860)
        startup_status = startup_status or (lambda _message: None)
        self.market_data_folder=DATA_DIR
        self.settings = QSettings("LongShortCrypto", "Backtester"); self.worker=None; self.thread=None; self.portfolio_worker=None; self.portfolio_thread=None; self.started=0; self.last_summary={}; self.output_dir=Path("output"); self.completed_run_dir=None; self._pending_ui_results=None; self._run_failed=False
        self.tabs=QTabWidget(); self.setCentralWidget(self.tabs)
        self.tabs.setDocumentMode(True); self.tabs.setMovable(False)
        self.setStyleSheet("QGroupBox{font-weight:600;margin-top:10px;padding-top:10px} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px} QPushButton{padding:6px 12px} QTabBar::tab{padding:8px 14px} QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{min-height:24px}")
        startup_status("Building interface...")
        self._build_config(); self._build_profiles(); self._build_summary(); self._build_portfolio_tab(); self._build_log(); self.reset_defaults(); self._restore_settings()
        startup_status("Initializing integrations...")
        self.github_tab=GitHubIntegrationWidget(self, self._git_work_active)
        self.tabs.addTab(self.github_tab,"GitHub")
        self.chatgpt_tab=ChatGPTIntegrationWidget(self.settings, lambda: self.output_folder.text().strip() or "output", self)
        self.tabs.addTab(self.chatgpt_tab,"ChatGPT")

    def start_post_show_tasks(self):
        """Schedule optional integrations after the main window is visible."""
        QTimer.singleShot(0, self.chatgpt_tab.auto_start_connection)

    def _git_work_active(self):
        """Prevent source updates while calculation worker threads are running."""
        return bool((self.thread and self.thread.isRunning()) or
                    (self.portfolio_thread and self.portfolio_thread.isRunning()))

    def closeEvent(self,event):
        self.chatgpt_tab.shutdown()
        event.accept()
    def _build_profiles(self):
        self.profile_editor=StrategyProfilesWidget(); self.tabs.addTab(self.profile_editor,"Strategy Profiles")
        self.profile_editor.changed.connect(self.update_dynamic)
        self.profile_editor.list.currentRowChanged.connect(self.update_dynamic)
    def _line(self, text=""):
        w=QLineEdit(text); return w
    def _spin(self, v, mn=-1e12, mx=1e12, dec=6):
        s=QDoubleSpinBox(); s.setRange(mn,mx); s.setDecimals(dec); s.setValue(v); return s
    def _build_config(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); form=QVBoxLayout(inner); self.config_controls=[]
        toolbar=QHBoxLayout(); toolbar.setContentsMargins(0,0,0,4); self.setup_toolbar=toolbar
        self.new_run_btn=QPushButton("New Run"); self.save_btn=QPushButton("Save Config"); self.load_btn=QPushButton("Load Config")
        for button in (self.new_run_btn,self.save_btn,self.load_btn): toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.run_btn=QPushButton("Run Backtest"); self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setEnabled(False)
        toolbar.addWidget(self.run_btn); toolbar.addWidget(self.cancel_btn); outer.addLayout(toolbar)
        self.new_run_btn.clicked.connect(self.new_run); self.save_btn.clicked.connect(self.save_config); self.load_btn.clicked.connect(self.load_config)
        self.run_btn.clicked.connect(self.run_backtest); self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        def group(title): g=QGroupBox(title); l=QFormLayout(g); form.addWidget(g); return l
        data=group("Data")
        self.market_symbol=QComboBox(); self.market_symbol.setEditable(True); self.market_symbol.addItems(["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]); self.market_symbol.setCurrentText("XRPUSDT"); data.addRow("Trading Pair",self.market_symbol)
        self.strategy_timeframe=QComboBox(); self.strategy_timeframe.addItems(["1m","5m","15m","30m","1h","4h"]); data.addRow("Strategy Timeframe",self.strategy_timeframe)
        self.input_csv=self._line(); self.input_csv.setReadOnly(True); b=QPushButton("Browse"); b.clicked.connect(self.browse_csv); row=QHBoxLayout(); row.addWidget(self.input_csv); row.addWidget(b); data.addRow("Strategy CSV", row)
        self.intrabar_timeframe=QComboBox(); self.intrabar_timeframe.addItems(["1m","5m","15m","30m","1h","4h"])
        self.intrabar_csv=self._line(); self.intrabar_csv.setReadOnly(True); bi=QPushButton("Browse"); bi.clicked.connect(self.browse_intrabar_csv); self.intrabar_csv_row=QHBoxLayout(); self.intrabar_csv_row.addWidget(self.intrabar_csv); self.intrabar_csv_row.addWidget(bi)
        self.input_csv.setPlaceholderText("No matching file in the shared Binance Data Hub folder")
        self.intrabar_csv.setPlaceholderText("No matching file in the shared Binance Data Hub folder")
        self.use_intrabar=QCheckBox("Use lower-timeframe data to resolve exits"); self.use_intrabar.setChecked(True)
        self.data_help=QLabel(); self.data_help.setWordWrap(True)
        data.addRow("",self.use_intrabar); data.addRow("Intrabar Timeframe",self.intrabar_timeframe); data.addRow("Intrabar CSV",self.intrabar_csv_row)
        self.shared_data_note=QLabel(f"Shared candle library: {self.market_data_folder}"); self.shared_data_note.setWordWrap(True); data.addRow("Shared Data",self.shared_data_note)
        self.strategy_timeframe.currentTextChanged.connect(self._timeframe_changed); self.intrabar_timeframe.currentTextChanged.connect(self.update_dynamic); self.use_intrabar.toggled.connect(self.update_dynamic)
        self.market_symbol.currentTextChanged.connect(self._sync_dataset_paths); self.strategy_timeframe.currentTextChanged.connect(self._sync_dataset_paths); self.intrabar_timeframe.currentTextChanged.connect(self._sync_dataset_paths)
        self.use_intrabar.toggled.connect(self._sync_dataset_paths)
        self.run_name=self._line(); self.run_name.setPlaceholderText("Optional run name prefix"); data.addRow("Run Name", self.run_name)
        self.output_folder=self._line(); self.output_folder.setReadOnly(True); bo=QPushButton("Browse"); bo.clicked.connect(self.browse_output); row=QHBoxLayout(); row.addWidget(self.output_folder); row.addWidget(bo); data.addRow("Output Folder", row)
        self.planned_output=QLabel("Output run folder: not calculated yet"); self.planned_output.setWordWrap(True); data.addRow("Next Run Folder", self.planned_output)
        self.dataset_info=QLabel("No CSV loaded."); data.addRow("Dataset Information", self.dataset_info); val=QPushButton("Validate Data"); val.clicked.connect(self.validate_data); data.addRow(val)
        strat=group("Core Strategy")
        self.sl=self._spin(2,0); self.sl.setToolTip("Distance from entry to the protective stop, measured in the selected risk unit."); self.tp=self._spin(3,0); self.entry_mode=QComboBox(); self.entry_mode.addItem("Wait until current trade closes","WAIT_UNTIL_CLOSED"); self.entry_mode.addItem("Check every N candles","EVERY_N_CANDLES"); self.entry_interval=QSpinBox(); self.entry_interval.setRange(1,999999); self.max_pairs=QSpinBox(); self.max_pairs.setRange(1,999999); self.tie=QComboBox(); self.tie.addItem("Conservative (stop first)","PESSIMISTIC"); self.tie.addItem("Optimistic (target first)","OPTIMISTIC")
        self.enable_partial_tp=QCheckBox("Enable Partial Take Profit"); self.tp1_r=self._spin(3.0,0.000001); self.tp1_close_pct=self._spin(50.0,0.000001,99.999999); self.tp2_r=self._spin(12.0,0.000001); self.tp2_close_pct=self._spin(50.0,0.000001,100.0); self.tp2_close_pct.setReadOnly(True); self.tp2_close_pct.setToolTip("Calculated automatically as 100% minus the TP1 percentage."); self.stop_loss_r=self._spin(10.0,0.000001); self.after_tp1_stop_mode=QComboBox(); self.after_tp1_stop_mode.addItems(["KEEP_ORIGINAL_SL","MOVE_TO_ENTRY","MOVE_TO_R_OFFSET"]); self.after_tp1_stop_offset_r=self._spin(0.0,0.0); self.tp2_exit_mode=QComboBox(); self.tp2_exit_mode.addItems(["FIXED_TP2","TRAILING_AFTER_TP1"])
        self.enable_partial_sl=QCheckBox("Enable Partial Stop Loss"); self.sl1_r=self._spin(0.5,0.000001); self.sl1_close_pct=self._spin(50.0,0.000001,99.999999); self.sl2_r=self._spin(8.0,0.000001)
        self.enable_trailing_profit=QCheckBox("Enable Whole-Position Trailing")
        self.enable_trailing_profit.setText("Enable Trailing Stop")
        self.enable_trailing_profit.setToolTip("Tightens the active protective stop while fixed TP2 and SL2 remain available.")
        self.trail_activation_trigger=QComboBox(); self.trail_activation_trigger.addItems(["PRICE_REACHES_R","AFTER_TP1","AFTER_SL1","AFTER_TP1_OR_SL1"])
        self.trail_activation_r=self._spin(3.0,0.000001); self.trail_activation_r.setToolTip("Favourable move, in the trade's existing R, required to activate trailing.")
        self.trail_distance_r=self._spin(1.0,0.000001); self.trail_distance_r.setToolTip("Distance behind the favourable extreme, using the same stored trade R.")
        self.trail_apply_to=QComboBox(); self.trail_apply_to.addItems(["BOTH","LONG_ONLY","SHORT_ONLY"]); self.trail_apply_to.setToolTip("Choose which leg uses whole-position trailing.")
        self.trail_intrabar_mode=QComboBox(); self.trail_intrabar_mode.addItems(["PESSIMISTIC","OPTIMISTIC"]); self.trail_intrabar_mode.setToolTip("Controls same-candle ordering for both whole-position and after-TP1 trailing.")
        self.both_timeout=QCheckBox("Enable Both-Open Timeout"); self.both_timeout_duration=QSpinBox(); self.both_timeout_duration.setRange(1,999999); self.both_timeout_unit=QComboBox(); self.both_timeout_unit.addItems(["Hours","Minutes"]); timeout_row=QHBoxLayout(); timeout_row.addWidget(self.both_timeout_duration); timeout_row.addWidget(self.both_timeout_unit); self.both_timeout_help=QLabel("If both long and short remain open beyond this time, both positions are\nclosed and a new pair may open at the next eligible 15-minute candle.\n\nThis rule does not apply after one leg has already closed."); self.both_timeout_help.setWordWrap(True)
        for lab,w in [("Stop Loss Multiple",self.sl),("Take Profit Multiple",self.tp),("Entry Mode",self.entry_mode),("Entry Interval",self.entry_interval),("Maximum Active Pairs",self.max_pairs),("Tie Policy",self.tie)]: strat.addRow(lab,w)
        partial_sl=group("Partial Stop Loss")
        partial_sl_help=QLabel("Closes part of each leg at SL1. The remainder stays open until SL2 or the active profit exit. This can be combined with Partial Take Profit."); partial_sl_help.setWordWrap(True)
        for lab,w in [("",self.enable_partial_sl),("SL1 Distance (R)",self.sl1_r),("Quantity Closed at SL1 (%)",self.sl1_close_pct),("SL2 Distance (R)",self.sl2_r),("",partial_sl_help)]: partial_sl.addRow(lab,w)
        partial_tp=group("Partial Take Profit")
        partial_tp_help=QLabel("Closes part of each leg at TP1. TP2 remains the final profit target for all quantity still open."); partial_tp_help.setWordWrap(True)
        for lab,w in [("",self.enable_partial_tp),("TP1 Distance (R)",self.tp1_r),("Quantity Closed at TP1 (%)",self.tp1_close_pct),("TP2 Distance (R)",self.tp2_r),("",partial_tp_help)]: partial_tp.addRow(lab,w)
        protective_stop=group("Post-TP1 Protective Stop")
        self.stop_loss_r.setToolTip("Initial full-position stop used only when Partial Take Profit is enabled without Partial Stop Loss.")
        self.after_tp1_stop_mode.setToolTip("Controls the protective stop for whatever quantity remains after TP1.")
        self.after_tp1_stop_offset_r.setToolTip("Favourable R offset used only with MOVE_TO_R_OFFSET.")
        self.protective_stop_help=QLabel(); self.protective_stop_help.setWordWrap(True)
        for lab,w in [
            ("Standalone SL Distance (R)",self.stop_loss_r),
            ("After TP1: Remaining Stop",self.after_tp1_stop_mode),
            ("Profit-Lock Offset (R)",self.after_tp1_stop_offset_r),
            ("",self.protective_stop_help),
        ]: protective_stop.addRow(lab,w)
        trailing=group("Independent Trailing Stop")
        self.trailing_help=QLabel("Trailing tightens the active stop for the quantity still open. Fixed TP2 and SL2 remain final exits."); self.trailing_help.setWordWrap(True)
        for lab,w in [
            ("",self.enable_trailing_profit),
            ("Activation Trigger",self.trail_activation_trigger),
            ("Activation Distance (R)",self.trail_activation_r),
            ("Trailing Distance (R)",self.trail_distance_r),
            ("Apply To",self.trail_apply_to),
            ("Intrabar Resolution",self.trail_intrabar_mode),
            ("",self.trailing_help),
        ]: trailing.addRow(lab,w)
        both_open=group("Both-Open Timeout")
        for lab,w in [("",self.both_timeout),("Maximum Time Open",timeout_row),("",self.both_timeout_help)]: both_open.addRow(lab,w)
        self.entry_mode.currentIndexChanged.connect(lambda:self.entry_interval.setEnabled(self.entry_mode.currentData()=="EVERY_N_CANDLES"))
        self.entry_mode.currentTextChanged.connect(self.update_dynamic)
        vwap_group=group("VWAP Volume Breakout")
        self.vwap_breakout_hours=self._spin(4.0,0.01,168,2); self.vwap_volume_lookback=QSpinBox(); self.vwap_volume_lookback.setRange(1,10000); self.vwap_volume_lookback.setValue(20); self.vwap_volume_multiplier=self._spin(1.5,0.01,100,2); self.vwap_slope_lookback=QSpinBox(); self.vwap_slope_lookback.setRange(1,1000); self.vwap_slope_lookback.setValue(1); self.vwap_atr_min=self._spin(0,0,1,6); self.vwap_atr_max=self._spin(1,0,10,6); self.vwap_confirmation_mode=QComboBox(); self.vwap_confirmation_mode.addItems(["IMMEDIATE","RETEST"]); self.vwap_retest_window=QSpinBox(); self.vwap_retest_window.setRange(1,100); self.vwap_retest_window.setValue(4); self.vwap_retest_tolerance=self._spin(0.25,0,10,3)
        vwap_help=QLabel("Immediate enters at the next candle open. Retest waits for price to revisit the broken level within the selected ATR tolerance, close beyond it, then enters at the following open. A close back inside the old range cancels the signal."); vwap_help.setWordWrap(True)
        for lab,w in [("Breakout Lookback (hours)",self.vwap_breakout_hours),("Volume Average Lookback",self.vwap_volume_lookback),("Minimum Volume Multiple",self.vwap_volume_multiplier),("VWAP Slope Lookback (candles)",self.vwap_slope_lookback),("Minimum ATR / Price",self.vwap_atr_min),("Maximum ATR / Price",self.vwap_atr_max),("Confirmation Mode",self.vwap_confirmation_mode),("Retest Window (candles)",self.vwap_retest_window),("Retest Tolerance (ATR)",self.vwap_retest_tolerance),("",vwap_help)]: vwap_group.addRow(lab,w)
        self.vwap_confirmation_mode.currentTextChanged.connect(self.update_dynamic)
        random_group=group("Random Entry Timing")
        self.enable_random_entry=QCheckBox("Enable Random Entry Timing"); self.entry_timing_mode=QComboBox(); self.entry_timing_mode.addItems(["CURRENT","RANDOM_AFTER_PAIR_CLOSE"]); self.random_probability=self._spin(0.50,0.000001,1.0,6); self.random_seed=QLineEdit("42"); self.random_start_mode=QComboBox(); self.random_start_mode.addItems(["NEXT_CANDLE_AFTER_PAIR_CLOSE","NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"]); self.randomize_first=QCheckBox("Randomize First Entry"); self.randomize_first.setChecked(True); self.max_random_wait=QSpinBox(); self.max_random_wait.setRange(0,999999); self.enable_random_batch=QCheckBox("Enable Random Entry Batch"); self.random_seed_start=QSpinBox(); self.random_seed_start.setRange(-2147483648,2147483647); self.random_seed_count=QSpinBox(); self.random_seed_count.setRange(1,999999)
        for lab,w in [("",self.enable_random_entry),("Entry Timing Mode",self.entry_timing_mode),("Entry Probability",self.random_probability),("Random Seed",self.random_seed),("Random Entry Start Mode",self.random_start_mode),("",self.randomize_first),("Maximum Random Wait Candles",self.max_random_wait),("",self.enable_random_batch),("Random Seed Start",self.random_seed_start),("Random Seed Count",self.random_seed_count)]: random_group.addRow(lab,w)
        self.enable_coin_flip_sizing=QCheckBox("Enable 3:1 Coin-Flip Sizing (1:1 SL/TP)"); self.coin_flip_seed=QLineEdit("42")
        random_group.addRow("",self.enable_coin_flip_sizing); random_group.addRow("Coin Flip Seed",self.coin_flip_seed)
        self.enable_di_direction_sizing=QCheckBox("Enable DI-Direction Selection"); self.flip_filtered_di_direction=QCheckBox("Flip direction after filters pass (Long ↔ Short)"); self.di_direction_long_min_spread=self._spin(30,0,1000,3); self.di_direction_short_min_spread=self._spin(30,0,1000,3); self.di_long_reward_risk_ratio=self._spin(1,0.01,100,3); self.di_short_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_support_resistance_analysis=QCheckBox("Enable Support/Resistance Analysis"); self.sr_pivot_left=QSpinBox(); self.sr_pivot_left.setRange(1,1000); self.sr_pivot_left.setValue(5); self.sr_pivot_right=QSpinBox(); self.sr_pivot_right.setRange(1,1000); self.sr_pivot_right.setValue(5); self.sr_lookback_bars=QSpinBox(); self.sr_lookback_bars.setRange(10,10000); self.sr_lookback_bars.setValue(200); self.sr_zone_width_atr=self._spin(0.5,0.0,10.0,3); self.sr_near_distance_atr=self._spin(0.75,0.0,10.0,3); self.enable_sr_hold_confirmation=QCheckBox("Enable"); self.sr_hold_confirmation_bars=QSpinBox(); self.sr_hold_confirmation_bars.setRange(1,100); self.sr_hold_confirmation_bars.setValue(3); self.sr_hold_confirmation_atr=self._spin(0.25,0.0,10.0,3); self.sr_break_tolerance_atr=self._spin(0.25,0.0,10.0,3); self.sr_break_basis=QComboBox(); self.sr_break_basis.addItems(["CLOSE","WICK"]); self.sr_filter_mode=PolicyComboBox()
        self.sr_filter_mode.addItem("Analysis Only", "ANALYSIS_ONLY")
        self.sr_filter_mode.addItem("Apply Entry Rules", "APPLY_ENTRY_RULES")
        self.sr_long_avoid_near_resistance=QCheckBox("Avoid buying near resistance")
        self.sr_long_require_near_support=QCheckBox("Require price near support")
        self.sr_long_block_broken_support=QCheckBox("Block if support structure is broken")
        self.sr_long_min_room_to_resistance_atr=self._spin(0.0,0.0,1000.0,2)
        self.sr_short_avoid_near_support=QCheckBox("Avoid selling near support")
        self.sr_short_require_near_resistance=QCheckBox("Require price near resistance")
        self.sr_short_block_broken_resistance=QCheckBox("Block if resistance structure is broken")
        self.sr_short_min_room_to_support_atr=self._spin(0.0,0.0,1000.0,2)
        self.enable_di_direction_selection=QCheckBox("Enable DI direction selection"); self.enable_di_direction_selection.setChecked(True)
        self.enable_di_pressure_analysis=QCheckBox("Analyze DI expansion / contraction"); self.enable_di_pressure_analysis.setChecked(True)
        self.di_pressure_lookback=QSpinBox(); self.di_pressure_lookback.setRange(1,100); self.di_pressure_lookback.setValue(3)
        self.di_execution_mode=QComboBox(); self.di_execution_mode.addItems(["BOTH_SIDES","PREFERRED_SIDE_ONLY"])
        self.enable_di_regime_reward_risk=QCheckBox("Enable Regime-Specific Reward/Risk")
        self.di_regime_bear_return_threshold=self._line("-20%")
        self.di_long_bull_reward_risk_ratio=self._spin(2,0.01,100,3); self.di_long_bear_reward_risk_ratio=self._spin(1,0.01,100,3); self.di_long_sideways_reward_risk_ratio=self._spin(2,0.01,100,3)
        self.di_short_bull_reward_risk_ratio=self._spin(1,0.01,100,3); self.di_short_bear_reward_risk_ratio=self._spin(1,0.01,100,3); self.di_short_sideways_reward_risk_ratio=self._spin(2,0.01,100,3)
        self.enable_bull_long_conditional_reward_risk=QCheckBox("Bull Long: Use Conditional Reward/Risk")
        self.bull_long_conditional_bb_width_minimum=self._line("5%")
        self.bull_long_conditional_adx_maximum=self._spin(40,0,1000,3)
        self.bull_long_conditional_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_bull_long_momentum_confirmation=QCheckBox("Bull Long: Require Shorter-Term Momentum Confirmation for Base Target")
        self.bull_long_confirmation_lookback_days=QSpinBox(); self.bull_long_confirmation_lookback_days.setRange(1,3650); self.bull_long_confirmation_lookback_days.setValue(60)
        self.bull_long_confirmation_return_threshold=self._line("20%")
        self.bull_long_unconfirmed_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_bull_long_momentum_target_extension=QCheckBox("Bull Long: Extend Target When Recent Momentum Is Strong")
        self.bull_long_momentum_extension_lookback_days=QSpinBox(); self.bull_long_momentum_extension_lookback_days.setRange(1,3650); self.bull_long_momentum_extension_lookback_days.setValue(30)
        self.bull_long_momentum_extension_return_threshold=self._line("10%")
        self.enable_bull_long_momentum_extension_return_maximum=QCheckBox("Use Maximum Recent-Momentum Return")
        self.bull_long_momentum_extension_return_maximum=self._line("40%")
        self.bull_long_momentum_extended_reward_risk_ratio=self._spin(4,0.01,100,3)
        self.enable_bull_long_structural_confirmation=QCheckBox("Bull Long: Require Long-Term Trend Confirmation")
        self.bull_long_structural_sma_days=QSpinBox(); self.bull_long_structural_sma_days.setRange(1,3650); self.bull_long_structural_sma_days.setValue(200)
        self.bull_long_structural_slope_lookback_days=QSpinBox(); self.bull_long_structural_slope_lookback_days.setRange(1,3650); self.bull_long_structural_slope_lookback_days.setValue(30)
        self.bull_long_structural_unconfirmed_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_bull_long_r_step_trailing=QCheckBox("Bull Long: Enable R-Step Staircase")
        self.bull_long_r_step_activation_r=self._spin(2,0.01,100,2)
        self.bull_long_r_step_distance_r=self._spin(2,0.01,100,2)
        self.bull_long_r_step_size_r=self._spin(1,0.01,100,2)
        self.bull_long_r_step_maximum_r=self._spin(0,0,100,2)
        self.bull_long_r_step_activation_close_pct=self._spin(0,0,99.99,2)
        self.enable_sideways_long_conditional_reward_risk=QCheckBox("Sideways Long: Use Conditional Reward/Risk")
        self.sideways_long_conditional_adx_maximum=self._spin(35,0,1000,3)
        self.sideways_long_conditional_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_sideways_short_conditional_reward_risk=QCheckBox("Sideways Short: Use Conditional Reward/Risk")
        self.sideways_short_conditional_di_spread_minimum=self._spin(35,0,1000,3)
        self.sideways_short_conditional_di_spread_maximum=self._spin(40,0,1000,3)
        self.sideways_short_conditional_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_bear_short_conditional_reward_risk=QCheckBox("Bear Short: Use Conditional Reward/Risk")
        self.bear_short_conditional_di_spread_maximum=self._spin(35,0,1000,3)
        self.bear_short_conditional_reward_risk_ratio=self._spin(1,0.01,100,3)
        self.enable_directional_adx_filter=QCheckBox("Enable Direction-Specific ADX Filter"); self.directional_long_adx_maximum=self._spin(60,0,1000,3); self.directional_short_adx_minimum=self._spin(25,0,1000,3)
        self.enable_atr_checkpoint_tp_extension=QCheckBox("Extend biased TP at ATR checkpoints")
        self.atr_checkpoint_di_spread_min=self._spin(30,0,1000,3)
        self.atr_checkpoint_bb_width_min=self._spin(0.03,0,1000,6)
        self.atr_checkpoint_profit_lock_start=self._spin(3,1,1000,2)
        self.atr_checkpoint_profit_lock_distance=self._spin(1,0.01,1000,2)
        self.enable_biased_short_adx_cap=QCheckBox("Skip biased shorts at high ADX")
        self.biased_short_adx_maximum=self._spin(50,0,1000,3)
        self.biased_short_adx_help=QLabel("Applies only when DI selects SHORT. ADX equal to or above this value rejects the entry; biased longs are unchanged.")
        self.biased_short_adx_help.setWordWrap(True)
        self.enable_short_vwap_distance_filter=QCheckBox("Short: Require Minimum Distance Below UTC Session VWAP")
        self.short_vwap_minimum_distance_atr=self._spin(2,0,1000,3)
        self.enable_long_momentum_filter=QCheckBox("Long: Require Minimum Trailing Return")
        self.long_momentum_lookback_hours=QSpinBox(); self.long_momentum_lookback_hours.setRange(1,87600); self.long_momentum_lookback_hours.setValue(24); self.long_momentum_lookback_hours.setSuffix(" hours")
        self.long_momentum_minimum_return=self._line("6%")
        self.long_momentum_help=QLabel("Applies only when DI selects LONG. Uses completed strategy candles over the configured trailing hours; insufficient warm-up rejects the signal.")
        self.long_momentum_help.setWordWrap(True)
        self.short_vwap_distance_help=QLabel("Applies only when DI selects SHORT. Distance is (UTC session VWAP − completed candle close) ÷ ATR. Long entries are unchanged.")
        self.short_vwap_distance_help.setWordWrap(True)
        self.enable_bear_regime_adx_filter=QCheckBox("Bear Regime: Require Minimum ADX"); self.bear_regime_adx_minimum=self._spin(25,0,1000,3)
        self.enable_bull_regime_short_filter=QCheckBox("Bull Regime: Skip −DI Short Signal"); self.bull_regime_lookback_days=QSpinBox(); self.bull_regime_lookback_days.setRange(1,3650); self.bull_regime_lookback_days.setValue(90); self.bull_regime_return_threshold=self._line("20%")
        self.enable_regime_direction_filter=QCheckBox("Enable Direction Permissions by Market Regime")
        self.allow_bull_long=QCheckBox("Allow Bull Long"); self.allow_bull_long.setChecked(True); self.allow_bull_short=QCheckBox("Allow Bull Short"); self.allow_bull_short.setChecked(True)
        self.allow_bear_long=QCheckBox("Allow Bear Long"); self.allow_bear_long.setChecked(True); self.allow_bear_short=QCheckBox("Allow Bear Short"); self.allow_bear_short.setChecked(True)
        self.allow_sideways_long=QCheckBox("Allow Sideways Long"); self.allow_sideways_long.setChecked(True); self.allow_sideways_short=QCheckBox("Allow Sideways Short"); self.allow_sideways_short.setChecked(True)
        self.enable_directional_di_spread_range=QCheckBox("Enable Directional DI-Spread Ranges"); self.directional_long_di_spread_minimum=self._spin(0,0,1000,3); self.directional_long_di_spread_maximum=self._spin(1000,0,1000,3); self.directional_short_di_spread_minimum=self._spin(0,0,1000,3); self.directional_short_di_spread_maximum=self._spin(1000,0,1000,3)
        self.enable_directional_adx_range=QCheckBox("Enable Directional ADX Ranges"); self.directional_long_adx_minimum=self._spin(0,0,1000,3); self.directional_long_adx_range_maximum=self._spin(1000,0,1000,3); self.directional_short_adx_range_minimum=self._spin(0,0,1000,3); self.directional_short_adx_maximum=self._spin(1000,0,1000,3)
        self.enable_directional_atr_pct_range=QCheckBox("Enable Directional ATR % Ranges"); self.directional_long_atr_pct_minimum=self._line("0%"); self.directional_long_atr_pct_maximum=self._line("100%"); self.directional_short_atr_pct_minimum=self._line("0%"); self.directional_short_atr_pct_maximum=self._line("100%")
        self.enable_directional_rsi_range=QCheckBox("Enable Directional RSI Ranges"); self.directional_rsi_period=QSpinBox(); self.directional_rsi_period.setRange(1,1000); self.directional_rsi_period.setValue(14); self.directional_long_rsi_minimum=self._spin(0,0,100,2); self.directional_long_rsi_maximum=self._spin(100,0,100,2); self.directional_short_rsi_minimum=self._spin(0,0,100,2); self.directional_short_rsi_maximum=self._spin(100,0,100,2)
        self.enable_directional_close_location_range=QCheckBox("Enable Directional Candle Close-Location Ranges"); self.directional_long_close_location_minimum=self._line("0%"); self.directional_long_close_location_maximum=self._line("100%"); self.directional_short_close_location_minimum=self._line("0%"); self.directional_short_close_location_maximum=self._line("100%")
        self.enable_directional_momentum_range=QCheckBox("Enable Directional Trailing-Return Ranges"); self.directional_momentum_lookback_hours=QSpinBox(); self.directional_momentum_lookback_hours.setRange(1,87600); self.directional_momentum_lookback_hours.setValue(24); self.directional_long_momentum_minimum=self._line("-1000%"); self.directional_long_momentum_maximum=self._line("1000%"); self.directional_short_momentum_minimum=self._line("-1000%"); self.directional_short_momentum_maximum=self._line("1000%")
        self.enable_coin_flip_sizing.toggled.connect(lambda checked: self.enable_di_direction_sizing.setChecked(False) if checked else None)
        self.enable_di_direction_sizing.toggled.connect(lambda checked: self.enable_coin_flip_sizing.setChecked(False) if checked else None)
        self.enable_di_direction_sizing.toggled.connect(self.update_dynamic)
        self.enable_di_regime_reward_risk.toggled.connect(self.update_dynamic)
        self.enable_bull_long_conditional_reward_risk.toggled.connect(self.update_dynamic)
        self.enable_bull_long_momentum_target_extension.toggled.connect(self.update_dynamic)
        self.enable_bull_long_momentum_extension_return_maximum.toggled.connect(self.update_dynamic)
        self.enable_bull_long_structural_confirmation.toggled.connect(self.update_dynamic)
        self.enable_bull_long_momentum_confirmation.toggled.connect(self.update_dynamic)
        self.enable_bull_long_r_step_trailing.toggled.connect(self.update_dynamic)
        self.enable_sideways_long_conditional_reward_risk.toggled.connect(self.update_dynamic)
        self.enable_sideways_short_conditional_reward_risk.toggled.connect(self.update_dynamic)
        self.enable_bear_short_conditional_reward_risk.toggled.connect(self.update_dynamic)
        self.enable_directional_adx_filter.toggled.connect(self.update_dynamic)
        self.enable_biased_short_adx_cap.toggled.connect(self.update_dynamic)
        self.enable_short_vwap_distance_filter.toggled.connect(self.update_dynamic)
        self.enable_long_momentum_filter.toggled.connect(self.update_dynamic)
        self.enable_bear_regime_adx_filter.toggled.connect(self.update_dynamic)
        self.di_execution_mode.currentTextChanged.connect(self.update_dynamic)
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
        risk=group("Account & Position Sizing"); self.account_form=risk
        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line("3"); self.max_lev_combined=self._line("5"); self.missing_policy=PolicyComboBox(); self.missing_policy.addItem("Use strategy candle for affected interval","WARN_AND_USE_15M"); self.missing_policy.addItem("Stop the run","ERROR"); self.missing_policy.addItem("Continue with available intrabar candles","WARN_AND_CONTINUE"); self.trade_direction=QComboBox(); self.trade_direction.addItems(["BOTH","LONG_ONLY","SHORT_ONLY","BOTH_INDEPENDENT"]); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("1%")
        self.risk_formula=QLabel(); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        for lab,w in [("Starting Equity",self.equity),("Base Account Risk Per Trade",self.risk_leg),("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Price-Distance Percentage",self.percent_r),("Fixed Risk Distance",self.fixed_r),("Maximum Leverage Per Trade",self.max_lev_leg),("Maximum Portfolio Leverage",self.max_lev_combined),("Formula",self.risk_formula),("Planned Risk",self.risk_warn),("Trade Direction",self.trade_direction)]: risk.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic)
        period=group("Backtest Period"); self.period_form=period
        self.entire_dataset=QCheckBox("Use entire dataset"); self.entire_dataset.setChecked(True)
        self.trading_start.setPlaceholderText("YYYY-MM-DD (optional)"); self.trading_end.setPlaceholderText("YYYY-MM-DD (optional)")
        for lab,w in [("",self.entire_dataset),("Start Date",self.trading_start),("End Date",self.trading_end)]: period.addRow(lab,w)
        self.entire_dataset.toggled.connect(self.update_dynamic)
        intrabar=group("Intrabar Execution Rules"); self.intrabar_form=intrabar
        for lab,w in [("Missing Data Policy",self.missing_policy),("",self.data_help)]: intrabar.addRow(lab,w)
        self.missing_policy.currentIndexChanged.connect(self.update_dynamic)
        trend=group("Trend Filter")
        self.enable_adx=QCheckBox("Enable ADX Filter"); self.adx_period=QSpinBox(); self.adx_period.setRange(1,99999); self.adx_mode=QComboBox(); self.adx_mode.addItems(["Disabled","ADX <= Maximum","ADX >= Minimum","Range"]); self.adx_max=self._spin(25,0); self.adx_min=self._spin(20,0)
        for lab,w in [("",self.enable_adx),("ADX Period",self.adx_period),("Filter Mode",self.adx_mode),("Maximum ADX",self.adx_max),("Minimum ADX",self.adx_min)]: trend.addRow(lab,w)
        self.enable_adx.toggled.connect(self.update_dynamic); self.adx_mode.currentTextChanged.connect(self.update_dynamic)
        compression=group("Market Compression Filters")
        self.enable_bb_width=QCheckBox("Enable Bollinger Width Filter"); self.bb_width_mode=QComboBox(); self.bb_width_mode.addItems(["Disabled","Maximum Width","Minimum Width","Range"]); self.bb_width_min=self._spin(0.012,0); self.bb_width_max=self._spin(0.03,0)
        self.bb_width_help=QLabel("Width values are raw decimals: 0.012 = 1.2%. Use Minimum Width with 0.012 to test the 1.2% entry filter."); self.bb_width_help.setWordWrap(True)
        self.skip_monday_entries=QCheckBox("Skip Monday Entries"); self.skip_monday_timezone=self._line("UTC")
        self.skip_monday_help=QLabel("Rejects new entries whose actual execution timestamp falls on Monday in this timezone. Existing trades continue normally."); self.skip_monday_help.setWordWrap(True)
        self.enable_di_spread=QCheckBox("Enable DI Spread Filter"); self.di_spread_mode=QComboBox(); self.di_spread_mode.addItems(["Disabled","Maximum Spread","Minimum Spread","Range"]); self.di_spread_min=self._spin(0,0); self.di_spread_max=self._spin(10,0)
        for lab,w in [("",self.enable_bb_width),("Bollinger Width Mode",self.bb_width_mode),("Minimum Width (decimal)",self.bb_width_min),("Maximum Width (decimal)",self.bb_width_max),("",self.bb_width_help),("",self.skip_monday_entries),("Monday Filter Timezone",self.skip_monday_timezone),("",self.skip_monday_help),("",self.enable_di_spread),("DI Spread Mode",self.di_spread_mode),("Minimum Spread",self.di_spread_min),("Maximum Spread",self.di_spread_max)]: compression.addRow(lab,w)
        for w in [self.enable_bb_width,self.bb_width_mode,self.skip_monday_entries,self.enable_di_spread,self.di_spread_mode]: w.toggled.connect(self.update_dynamic) if hasattr(w,"toggled") else w.currentTextChanged.connect(self.update_dynamic)
        telemetry=group("Trade Telemetry")
        self.enable_trade_telemetry=QCheckBox("Enable Trade Telemetry"); self.telemetry_interval=QSpinBox(); self.telemetry_interval.setRange(1,999999); self.telemetry_interval.setSuffix(" minutes"); self.save_full_telemetry=QCheckBox("Save Full Telemetry CSV"); self.save_journey_summary=QCheckBox("Save Journey Summary"); self.save_journey_charts=QCheckBox("Save Journey Charts"); self.telemetry_estimate=QLabel("Estimated telemetry rows: calculated after data validation when practical."); self.telemetry_estimate.setWordWrap(True)
        telemetry.addRow(QLabel("Records how ATR, ADX, DI Spread, and Bollinger Band Width change while each trade is active."));
        for lab,w in [("",self.enable_trade_telemetry),("Telemetry Interval",self.telemetry_interval),("",self.save_full_telemetry),("",self.save_journey_summary),("",self.save_journey_charts),("Estimate",self.telemetry_estimate)]: telemetry.addRow(lab,w)
        self.enable_trade_telemetry.toggled.connect(self.update_dynamic); self.telemetry_interval.valueChanged.connect(self.update_dynamic)
        lifecycle=group("Indicator Lifecycle Analysis")
        self.enable_lifecycle=QCheckBox("Enable Indicator Lifecycle Analysis"); self.lifecycle_phases=QSpinBox(); self.lifecycle_phases.setRange(4,4); self.lifecycle_checkpoints=self._line("15,30,60"); self.lifecycle_min_sample=QSpinBox(); self.lifecycle_min_sample.setRange(1,100000); self.lifecycle_charts=QCheckBox("Create lifecycle charts"); self.lifecycle_flat_threshold=self._spin(5.0,0,100,2); self.lifecycle_flat_threshold.setSuffix(" %")
        for lab,w in [("",self.enable_lifecycle),("Lifecycle phases",self.lifecycle_phases),("Early checkpoints (minutes)",self.lifecycle_checkpoints),("Minimum bucket sample",self.lifecycle_min_sample),("",self.lifecycle_charts),("Flat-pattern threshold",self.lifecycle_flat_threshold)]: lifecycle.addRow(lab,w)
        reports=group("Optional Output Reports")
        self.save_feature_reports=QCheckBox("Create trailing/partial-exit diagnostic reports"); self.save_indicator_reports=QCheckBox("Create ADX/BB-width/DI-spread analysis reports"); self.create_standard_charts=QCheckBox("Create standard performance charts")
        reports_help=QLabel("Core Excel report, trade list, equity curve, configuration, and log are always saved."); reports_help.setWordWrap(True); reports.addRow(reports_help)
        for w in [self.save_feature_reports,self.save_indicator_reports,self.create_standard_charts]: reports.addRow(w)
        self.analysis_level=QComboBox(); self.analysis_level.addItems(["Fast","Standard (Recommended)","Research"])
        self.analysis_description=QLabel(); self.analysis_description.setWordWrap(True)
        self.analysis_advanced=QPushButton("Show Advanced Settings"); self.analysis_advanced.setCheckable(True)
        telemetry.insertRow(0,"Analysis Level",self.analysis_level); telemetry.insertRow(1,"",self.analysis_description); telemetry.insertRow(2,"",self.analysis_advanced)
        self.analysis_detail_widgets=[self.enable_trade_telemetry,self.telemetry_interval,self.save_full_telemetry,self.save_journey_summary,self.save_journey_charts,self.telemetry_estimate]
        self.analysis_level.currentTextChanged.connect(self._apply_analysis_preset); self.analysis_advanced.toggled.connect(self._set_analysis_advanced)
        fees=group("Fees and Execution")
        self.maker=self._line("0.02%"); self.taker=self._line("0.05%"); self.maker_entry=QCheckBox("Use Maker Fee for Entry"); self.maker_exit=QCheckBox("Use Maker Fee for Exit"); self.slippage=self._line("0.05%"); self.cost=QLabel(); self.cost.setWordWrap(True)
        for lab,w in [("Maker Fee",self.maker),("Taker Fee",self.taker),("",self.maker_entry),("",self.maker_exit),("Slippage",self.slippage),("Round-trip Cost",self.cost),("",self.zero_cost)]: fees.addRow(lab,w)
        for w in [self.maker,self.taker,self.slippage]: w.textChanged.connect(self.update_dynamic)
        self.maker_entry.toggled.connect(self.update_dynamic); self.maker_exit.toggled.connect(self.update_dynamic)
        be_rule=group("Break-Even After Opposite SL")
        self.be_after_sl=QCheckBox("Enable BE After Opposite SL"); self.be_mode=QComboBox(); self.be_mode.addItems(["ENTRY_PRICE","COST_ADJUSTED","R_OFFSET"]); self.be_offset=self._spin(0,0); self.be_same_candle=QComboBox(); self.be_same_candle.addItems(["NEXT_CANDLE","PESSIMISTIC"]); self.be_help=QLabel("When one leg hits SL, the still-open opposite leg keeps its TP but its SL\nmoves to break-even.\n\nEntry-price break-even does not recover fees or slippage."); self.be_help.setWordWrap(True)
        for lab,w in [("",self.be_after_sl),("BE Mode",self.be_mode),("BE Offset in R",self.be_offset),("Same-Candle BE Policy",self.be_same_candle),("",self.be_help)]: be_rule.addRow(lab,w)
        self.be_mode.currentTextChanged.connect(lambda t:self.be_offset.setEnabled(t=="R_OFFSET"))
        remaining_timeout=group("Remaining Leg Timeout After First SL")
        self.remaining_leg_timeout=QCheckBox("Enable Remaining-Leg Timeout After First SL")
        self.remaining_leg_timeout_duration=QSpinBox(); self.remaining_leg_timeout_duration.setRange(1,999999)
        self.remaining_leg_timeout_unit=QComboBox(); self.remaining_leg_timeout_unit.addItems(["Minutes","Hours"])
        self.remaining_leg_timeout_profit_extension=QCheckBox("Extend When Remaining Leg Is Near TP")
        self.remaining_leg_timeout_profit_threshold_r=self._spin(10.0,0.0,999999.0)
        self.reentry_gate_after_timeout=QCheckBox("Wait for Virtual TP/SL Before Next Entry")
        self.checkpoint_score_extension=QCheckBox("Extend Using Multi-Condition Score")
        self.checkpoint_score_use_profit=QCheckBox("Profit at least (R)"); self.checkpoint_score_min_profit_r=self._spin(0.85,0.0,999999.0)
        self.checkpoint_score_use_atr=QCheckBox("ATR at most (% of price)"); self.checkpoint_score_max_atr_pct=self._spin(0.08,0.0,100.0)
        self.checkpoint_score_use_di=QCheckBox("Directional DI at least"); self.checkpoint_score_min_di=self._spin(2.3,-100.0,100.0)
        self.checkpoint_score_use_bb=QCheckBox("Bollinger width at most (%)"); self.checkpoint_score_max_bb_pct=self._spin(0.349,0.0,100.0)
        self.checkpoint_score_required=QSpinBox(); self.checkpoint_score_required.setRange(1,4); self.checkpoint_score_required.setValue(3)
        self.first_sl_survivor_partial=QCheckBox("Take Partial Profit From Survivor at First SL"); self.first_sl_survivor_partial_pct=self._spin(25.0,0.01,99.99,2)
        self.zero_score_confirmation=QCheckBox("Require Consecutive Zero-Score Confirmations"); self.zero_score_confirmations=QSpinBox(); self.zero_score_confirmations.setRange(2,20); self.zero_score_confirmations.setValue(2)
        self.zero_score_recheck_duration=QSpinBox(); self.zero_score_recheck_duration.setRange(1,999999); self.zero_score_recheck_duration.setValue(2)
        self.zero_score_recheck_unit=QComboBox(); self.zero_score_recheck_unit.addItems(["Minutes","Hours"])
        zero_recheck_row=QHBoxLayout(); zero_recheck_row.addWidget(self.zero_score_recheck_duration); zero_recheck_row.addWidget(self.zero_score_recheck_unit)
        remaining_timeout_row=QHBoxLayout(); remaining_timeout_row.addWidget(self.remaining_leg_timeout_duration); remaining_timeout_row.addWidget(self.remaining_leg_timeout_unit)
        remaining_timeout_help=QLabel("The first-SL option realizes the selected percentage of the surviving leg at market and leaves the remainder on its original TP/SL. At each checkpoint, the score extends when enough conditions pass. Consecutive zero confirmation gives the first zero score a shorter recheck and closes only after the required zero-score streak. ATR and Bollinger values are percentages, so enter 0.08 for 0.08%. The virtual TP/SL gate prevents replacement entries until the saved boundary is touched."); remaining_timeout_help.setWordWrap(True)
        for lab,w in [("",self.remaining_leg_timeout),("Check Every",remaining_timeout_row),("",self.first_sl_survivor_partial),("Partial Close (%)",self.first_sl_survivor_partial_pct),("",self.remaining_leg_timeout_profit_extension),("Keep Open At or Above (R)",self.remaining_leg_timeout_profit_threshold_r),("",self.checkpoint_score_extension),("",self.checkpoint_score_use_profit),("Minimum Profit (R)",self.checkpoint_score_min_profit_r),("",self.checkpoint_score_use_atr),("Maximum ATR (%)",self.checkpoint_score_max_atr_pct),("",self.checkpoint_score_use_di),("Minimum Directional DI",self.checkpoint_score_min_di),("",self.checkpoint_score_use_bb),("Maximum BB Width (%)",self.checkpoint_score_max_bb_pct),("Conditions Required",self.checkpoint_score_required),("",self.zero_score_confirmation),("Zero Scores Required",self.zero_score_confirmations),("Recheck Zero Score After",zero_recheck_row),("",self.reentry_gate_after_timeout),("",remaining_timeout_help)]: remaining_timeout.addRow(lab,w)
        self.remaining_leg_timeout.toggled.connect(self.remaining_leg_timeout_duration.setEnabled)
        self.remaining_leg_timeout.toggled.connect(self.remaining_leg_timeout_unit.setEnabled)
        self.remaining_leg_timeout.toggled.connect(self.remaining_leg_timeout_profit_extension.setEnabled)
        self.remaining_leg_timeout.toggled.connect(self.reentry_gate_after_timeout.setEnabled)
        self.remaining_leg_timeout.toggled.connect(self._update_checkpoint_score_controls)
        self.first_sl_survivor_partial.toggled.connect(lambda checked:self.first_sl_survivor_partial_pct.setEnabled(checked))
        self.first_sl_survivor_partial.toggled.connect(lambda checked:self.enable_partial_tp.setChecked(False) if checked else None)
        self.enable_partial_tp.toggled.connect(lambda checked:self.first_sl_survivor_partial.setChecked(False) if checked else None)
        self.enable_partial_sl.toggled.connect(self.update_dynamic)
        self.enable_partial_tp.toggled.connect(self.update_dynamic)
        self.tp1_close_pct.valueChanged.connect(lambda value:self.tp2_close_pct.setValue(100.0-value))
        self.after_tp1_stop_mode.currentTextChanged.connect(self.update_dynamic)
        self.enable_trailing_profit.toggled.connect(self.update_dynamic)
        self.trail_activation_trigger.currentTextChanged.connect(self.update_dynamic)
        self.remaining_leg_timeout.toggled.connect(lambda _:self.remaining_leg_timeout_profit_threshold_r.setEnabled(self.remaining_leg_timeout.isChecked() and self.remaining_leg_timeout_profit_extension.isChecked()))
        self.remaining_leg_timeout_profit_extension.toggled.connect(lambda _:self.remaining_leg_timeout_profit_threshold_r.setEnabled(self.remaining_leg_timeout.isChecked() and self.remaining_leg_timeout_profit_extension.isChecked()))
        self.remaining_leg_timeout_profit_extension.toggled.connect(lambda checked:self.checkpoint_score_extension.setChecked(False) if checked else None)
        self.checkpoint_score_extension.toggled.connect(lambda checked:self.remaining_leg_timeout_profit_extension.setChecked(False) if checked else None)
        self.checkpoint_score_extension.toggled.connect(self._update_checkpoint_score_controls)
        self.zero_score_confirmation.toggled.connect(self._update_checkpoint_score_controls)
        for control in [self.checkpoint_score_use_profit,self.checkpoint_score_use_atr,self.checkpoint_score_use_di,self.checkpoint_score_use_bb]:
            control.toggled.connect(self._update_checkpoint_score_controls)
        be=group("Break-Even Calculator")
        self.be_label=QLabel(); self.be_label.setWordWrap(True); be.addRow(self.be_label)
        controls=group("Run Status")
        self.progress=QProgressBar(); self.status=QLabel("Ready"); self.elapsed=QLabel("Elapsed: 0s"); controls.addRow(self.progress); controls.addRow(self.status); controls.addRow(self.elapsed)
        for w in [self.run_name,self.output_folder]: w.textChanged.connect(self.update_planned_output)
        for obsolete in (partial_sl,partial_tp,protective_stop,trailing,both_open,vwap_group,random_group,trend,compression,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)
        data.parentWidget().setTitle("Data & Output"); strat.parentWidget().setTitle("Entry Timing & Simulation"); sched.parentWidget().setTitle("Scheduled Entry"); fees.parentWidget().setTitle("Execution Costs"); telemetry.parentWidget().setTitle("Reports & Analysis"); lifecycle.parentWidget().setTitle("Advanced Indicator Analysis"); reports.parentWidget().setTitle("Report Files")
        self.sl.setVisible(False); sl_label=strat.labelForField(self.sl)
        if sl_label: sl_label.setVisible(False)
        self.tp.setVisible(False); tp_label=strat.labelForField(self.tp)
        if tp_label: tp_label.setVisible(False)
        risk.setRowVisible(self.trade_direction,False)
        scroll.setWidget(inner); outer.addWidget(scroll); self.backtest_setup_page=page; self.tabs.addTab(page,"Backtest Setup"); self.config_controls=inner.findChildren(QWidget); self._build_di_strategy_tab(); self._build_support_resistance_tab(); self.update_dynamic()

    def _build_support_resistance_tab(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); layout=QVBoxLayout(inner)

        usage=QGroupBox("S/R Usage"); usage_layout=QVBoxLayout(usage)
        self.enable_support_resistance_analysis.setToolTip("Calculate, store, and report support/resistance context.")
        usage_layout.addWidget(self.enable_support_resistance_analysis)
        usage_layout.addWidget(QLabel("Usage"))
        self.sr_analyze_only=QRadioButton("Analyze Only")
        self.sr_apply_entry_rules=QRadioButton("Apply Entry Rules")
        usage_layout.addWidget(self.sr_analyze_only); usage_layout.addWidget(self.sr_apply_entry_rules)
        self.sr_strategy_status=QLabel(); self.sr_strategy_status.setWordWrap(True)
        status=QGroupBox("S/R Strategy Status"); QVBoxLayout(status).addWidget(self.sr_strategy_status); usage_layout.addWidget(status)
        layout.addWidget(usage)

        entry_box=QGroupBox("Entry Rules"); entry_layout=QVBoxLayout(entry_box)
        columns=QHBoxLayout(); long_box=QGroupBox("LONG"); lf=QFormLayout(long_box); short_box=QGroupBox("SHORT"); sf=QFormLayout(short_box)
        self.sr_long_avoid_near_resistance.setToolTip("Reject LONG entries near resistance.")
        self.sr_long_require_near_support.setToolTip("Allow LONG entries only near support.")
        self.sr_short_avoid_near_support.setToolTip("Reject SHORT entries near support.")
        self.sr_short_require_near_resistance.setToolTip("Allow SHORT entries only near resistance.")
        self.sr_long_min_room_to_resistance_atr.setSuffix(" ATR")
        self.sr_short_min_room_to_support_atr.setSuffix(" ATR")
        lf.addRow(QLabel("Location")); lf.addRow(self.sr_long_avoid_near_resistance); lf.addRow(self.sr_long_require_near_support)
        lf.addRow(QLabel("Structure")); lf.addRow(self.sr_long_block_broken_support)
        lf.addRow("Minimum room to resistance", self.sr_long_min_room_to_resistance_atr)
        sf.addRow(QLabel("Location")); sf.addRow(self.sr_short_avoid_near_support); sf.addRow(self.sr_short_require_near_resistance)
        sf.addRow(QLabel("Structure")); sf.addRow(self.sr_short_block_broken_resistance)
        sf.addRow("Minimum room to support", self.sr_short_min_room_to_support_atr)
        columns.addWidget(long_box); columns.addWidget(short_box); entry_layout.addLayout(columns)
        self.sr_trade_context_note=QLabel("Analysis Only is active. These rules are saved but do not reject trades."); self.sr_trade_context_note.setWordWrap(True); entry_layout.addWidget(self.sr_trade_context_note)
        self.sr_entry_rules_box=entry_box; layout.addWidget(entry_box)

        proximity=QGroupBox("Proximity"); pf=QFormLayout(proximity)
        self.sr_near_distance_atr.setSuffix(" ATR"); self.sr_zone_width_atr.setSuffix(" ATR")
        self.sr_near_distance_atr.setToolTip("Price within this ATR distance is considered near support or resistance.")
        pf.addRow("Near-Level Threshold",self.sr_near_distance_atr); pf.addRow("Zone Width",self.sr_zone_width_atr)
        self.sr_proximity_box=proximity; layout.addWidget(proximity)

        breaks=QGroupBox("Structure Break Detection"); bf=QFormLayout(breaks)
        self.enable_sr_hold_confirmation.setText("Confirm break before marking a level broken")
        self.sr_hold_confirmation_bars.setToolTip("Consecutive candles required to confirm that a level was broken.")
        self.sr_hold_confirmation_atr.setToolTip("Minimum ATR distance beyond the level required to confirm a break.")
        self.sr_break_basis.setToolTip("Use candle closes or intrabar wicks to evaluate structure breaks.")
        self.sr_hold_confirmation_atr.setSuffix(" ATR"); self.sr_break_tolerance_atr.setSuffix(" ATR")
        bf.addRow(self.enable_sr_hold_confirmation); bf.addRow("Confirmation Candles",self.sr_hold_confirmation_bars); bf.addRow("Minimum Break Distance",self.sr_hold_confirmation_atr); bf.addRow("Break Tolerance",self.sr_break_tolerance_atr); bf.addRow("Break Basis",self.sr_break_basis)
        self.sr_break_detection_box=breaks; layout.addWidget(breaks)

        advanced=QGroupBox("Advanced Detection Settings"); advanced.setCheckable(True); advanced.setChecked(False); af=QFormLayout()
        self.sr_detection_preset=QComboBox(); self.sr_detection_preset.addItems(["Conservative","Balanced","Sensitive","Custom"]); self.sr_detection_preset.setCurrentText("Balanced")
        af.addRow("Detection Preset",self.sr_detection_preset); af.addRow("Pivot Left",self.sr_pivot_left); af.addRow("Pivot Right",self.sr_pivot_right); af.addRow("Lookback Bars",self.sr_lookback_bars)
        content=QWidget(); content.setLayout(af); wrapper=QVBoxLayout(advanced); wrapper.addWidget(content); advanced.toggled.connect(content.setVisible); content.setVisible(False)
        self.sr_advanced_box=advanced; layout.addWidget(advanced)

        summary=QGroupBox("Current S/R Rules"); sl=QVBoxLayout(summary); self.sr_summary_label=QLabel(); self.sr_summary_label.setWordWrap(True); sl.addWidget(self.sr_summary_label); layout.addWidget(summary); layout.addStretch(1)
        self._sr_detection_presets={"Conservative":{"pivot_left":8,"pivot_right":8,"lookback":300,"zone_width_atr":0.75,"break_tolerance_atr":0.35},"Balanced":{"pivot_left":5,"pivot_right":5,"lookback":200,"zone_width_atr":0.5,"break_tolerance_atr":0.25},"Sensitive":{"pivot_left":3,"pivot_right":3,"lookback":150,"zone_width_atr":0.35,"break_tolerance_atr":0.15}}
        self.sr_detection_preset.currentTextChanged.connect(self._apply_sr_detection_preset)
        for c in (self.sr_pivot_left,self.sr_pivot_right,self.sr_lookback_bars,self.sr_zone_width_atr,self.sr_break_tolerance_atr): c.valueChanged.connect(self._mark_sr_preset_custom)
        self.sr_analyze_only.toggled.connect(lambda checked: checked and self.sr_filter_mode.setCurrentText("ANALYSIS_ONLY")); self.sr_apply_entry_rules.toggled.connect(lambda checked: checked and self.sr_filter_mode.setCurrentText("APPLY_ENTRY_RULES"))
        for c in (self.enable_support_resistance_analysis,self.enable_sr_hold_confirmation,self.sr_analyze_only,self.sr_apply_entry_rules): c.toggled.connect(self.update_dynamic)
        for c in (self.sr_filter_mode,self.sr_break_basis): c.currentTextChanged.connect(self.update_dynamic)
        for c in (self.sr_near_distance_atr,self.sr_zone_width_atr,self.sr_hold_confirmation_bars,self.sr_hold_confirmation_atr,self.sr_break_tolerance_atr,self.sr_pivot_left,self.sr_pivot_right,self.sr_lookback_bars): c.valueChanged.connect(self.update_dynamic)
        for c in (self.sr_long_avoid_near_resistance,self.sr_long_require_near_support,self.sr_long_block_broken_support,self.sr_short_avoid_near_support,self.sr_short_require_near_resistance,self.sr_short_block_broken_resistance): c.toggled.connect(self.update_dynamic)
        for c in (self.sr_long_min_room_to_resistance_atr,self.sr_short_min_room_to_support_atr): c.valueChanged.connect(self.update_dynamic)
        outer.addWidget(scroll); scroll.setWidget(inner); self.tabs.addTab(page,"Support & Resistance"); self._update_sr_usage_radios(); self._update_sr_tab_state()

    def _update_sr_usage_radios(self):
        analysis=self.sr_filter_mode.currentText()=="ANALYSIS_ONLY"
        for control,value in ((self.sr_analyze_only,analysis),(self.sr_apply_entry_rules,not analysis)):
            control.blockSignals(True); control.setChecked(value); control.blockSignals(False)

    def _apply_sr_detection_preset(self,name):
        preset=self._sr_detection_presets.get(name)
        if not preset: return
        self._applying_sr_preset=True
        try:
            self.sr_pivot_left.setValue(preset["pivot_left"]); self.sr_pivot_right.setValue(preset["pivot_right"]); self.sr_lookback_bars.setValue(preset["lookback"]); self.sr_zone_width_atr.setValue(preset["zone_width_atr"]); self.sr_break_tolerance_atr.setValue(preset["break_tolerance_atr"])
        finally:
            self._applying_sr_preset=False

    def _mark_sr_preset_custom(self,*args):
        if getattr(self,"_applying_sr_preset",False): return
        if self.sr_detection_preset.currentText()!="Custom":
            self.sr_detection_preset.blockSignals(True); self.sr_detection_preset.setCurrentText("Custom"); self.sr_detection_preset.blockSignals(False)

    def _sync_sr_preset_from_values(self):
        current={"pivot_left":self.sr_pivot_left.value(),"pivot_right":self.sr_pivot_right.value(),"lookback":self.sr_lookback_bars.value(),"zone_width_atr":round(self.sr_zone_width_atr.value(),3),"break_tolerance_atr":round(self.sr_break_tolerance_atr.value(),3)}
        matched="Custom"
        for name,preset in self._sr_detection_presets.items():
            if preset=={**preset,**{k:current[k] for k in preset if k in current}} and current==preset:
                matched=name; break
        self._applying_sr_preset=True
        try: self.sr_detection_preset.setCurrentText(matched)
        finally: self._applying_sr_preset=False

    def _update_sr_tab_state(self):
        if not hasattr(self,"sr_summary_label"): return
        self._update_sr_usage_radios()
        enabled=self.enable_support_resistance_analysis.isChecked()
        applying=self.sr_filter_mode.currentText()!="ANALYSIS_ONLY"
        self.sr_analyze_only.setEnabled(enabled); self.sr_apply_entry_rules.setEnabled(enabled)
        for box in (self.sr_proximity_box,self.sr_break_detection_box,self.sr_advanced_box): box.setEnabled(enabled)
        self.sr_entry_rules_box.setEnabled(enabled and applying)
        confirmation=enabled and self.enable_sr_hold_confirmation.isChecked()
        self.sr_hold_confirmation_bars.setEnabled(confirmation); self.sr_hold_confirmation_atr.setEnabled(confirmation)
        if not enabled:
            note="Support/Resistance analysis is disabled."
        elif not applying:
            note="Analysis Only is active. These rules are saved but do not reject trades."
        else:
            note="Apply Entry Rules is active. Selected rules may reject entries."
        self.sr_trade_context_note.setText(note)
        long_rules=[label for c,label in ((self.sr_long_avoid_near_resistance,"Avoid near resistance"),(self.sr_long_require_near_support,"Require near support"),(self.sr_long_block_broken_support,"Block broken support")) if c.isChecked()]
        short_rules=[label for c,label in ((self.sr_short_avoid_near_support,"Avoid near support"),(self.sr_short_require_near_resistance,"Require near resistance"),(self.sr_short_block_broken_resistance,"Block broken resistance")) if c.isChecked()]
        if self.sr_long_min_room_to_resistance_atr.value() > 0: long_rules.append(f"Minimum room: {self.sr_long_min_room_to_resistance_atr.value():.2f} ATR")
        if self.sr_short_min_room_to_support_atr.value() > 0: short_rules.append(f"Minimum room: {self.sr_short_min_room_to_support_atr.value():.2f} ATR")
        long_text="\n".join(f"• {rule}" for rule in long_rules) or "• None"
        short_text="\n".join(f"• {rule}" for rule in short_rules) or "• None"
        impact='APPLYING ENTRY RULES' if enabled and applying else 'NONE'
        self.sr_strategy_status.setText(f"Analysis: {'Enabled' if enabled else 'Disabled'}\nTrading Impact: {impact}")
        self.sr_summary_label.setText(f"LONG\n{long_text}\n\nSHORT\n{short_text}")
    def _build_di_strategy_tab(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); form=QVBoxLayout(inner)
        intro=QLabel("DI-direction strategy settings live here. Shared data, risk, fees, execution, telemetry, and output settings remain on the Configuration tab.")
        intro.setWordWrap(True); form.addWidget(intro)
        selection_box=QGroupBox("DI Direction Selection"); selection=QFormLayout(selection_box)
        for lab,w in [
            ("",self.enable_di_direction_sizing),
            ("",self.flip_filtered_di_direction),
            ("Execution Mode",self.di_execution_mode),
            ("Long Reward/Risk Ratio",self.di_long_reward_risk_ratio),
            ("Short Reward/Risk Ratio",self.di_short_reward_risk_ratio),
        ]: selection.addRow(lab,w)
        form.addWidget(selection_box)
        direction_box=QGroupBox("Direction Selection"); direction_form=QFormLayout(direction_box)
        rule=QLabel("Current Rule\n+DI above -DI → LONG\n-DI above +DI → SHORT"); rule.setWordWrap(True)
        direction_form.addRow("",self.enable_di_direction_selection); direction_form.addRow("",rule); form.addWidget(direction_box)
        pressure_box=QGroupBox("DI Pressure Analysis"); pressure_form=QFormLayout(pressure_box)
        mode=QLabel("Analysis Mode: RECORD ONLY\nDoes not filter or reject trades.")
        help_text=QLabel("DI direction chooses LONG or SHORT from +DI versus -DI. DI Pressure Analysis measures whether directional pressure is strengthening or weakening before entry. It is analysis-only and does not filter trades. DI Spread entry filtering is configured separately under Strategy Profiles → Rules → DI Spread."); help_text.setWordWrap(True)
        pressure_form.addRow("",self.enable_di_pressure_analysis); pressure_form.addRow("Lookback",self.di_pressure_lookback); pressure_form.addRow("",mode); pressure_form.addRow("",help_text); form.addWidget(pressure_box)
        regime_targets_box=QGroupBox("Regime-Specific Reward/Risk"); regime_targets=QFormLayout(regime_targets_box)
        regime_targets_help=QLabel("Bull uses the Bull Return Threshold below. Bear uses the separate bear threshold; returns between them are sideways. Warm-up trades use the base long/short ratios above.")
        regime_targets_help.setWordWrap(True)
        bull_long_conditional_help=QLabel("During bull regimes only: when BB width is at or above the minimum AND ADX is below the maximum, the conditional target replaces Long Bull Reward/Risk. Other bull longs keep the normal bull target.")
        bull_long_conditional_help.setWordWrap(True)
        for lab,w in [
            ("",self.enable_di_regime_reward_risk),
            ("Bear Return Threshold",self.di_regime_bear_return_threshold),
            ("Long Bull Reward/Risk",self.di_long_bull_reward_risk_ratio),
            ("Long Bear Reward/Risk",self.di_long_bear_reward_risk_ratio),
            ("Long Sideways Reward/Risk",self.di_long_sideways_reward_risk_ratio),
            ("Short Bull Reward/Risk",self.di_short_bull_reward_risk_ratio),
            ("Short Bear Reward/Risk",self.di_short_bear_reward_risk_ratio),
            ("Short Sideways Reward/Risk",self.di_short_sideways_reward_risk_ratio),
            ("",self.enable_bull_long_conditional_reward_risk),
            ("Conditional BB Width Minimum",self.bull_long_conditional_bb_width_minimum),
            ("Conditional ADX Maximum",self.bull_long_conditional_adx_maximum),
            ("Conditional Bull Long Reward/Risk",self.bull_long_conditional_reward_risk_ratio),
            ("",bull_long_conditional_help),
            ("",self.enable_bull_long_momentum_confirmation),
            ("Confirmation Lookback Days",self.bull_long_confirmation_lookback_days),
            ("Confirmation Return Threshold",self.bull_long_confirmation_return_threshold),
            ("Unconfirmed Bull Long Reward/Risk",self.bull_long_unconfirmed_reward_risk_ratio),
            ("",self.enable_bull_long_momentum_target_extension),
            ("Momentum Extension Lookback Days",self.bull_long_momentum_extension_lookback_days),
            ("Momentum Extension Return Threshold",self.bull_long_momentum_extension_return_threshold),
            ("",self.enable_bull_long_momentum_extension_return_maximum),
            ("Momentum Extension Return Maximum",self.bull_long_momentum_extension_return_maximum),
            ("Strong-Momentum Bull Long Reward/Risk",self.bull_long_momentum_extended_reward_risk_ratio),
            ("",self.enable_bull_long_structural_confirmation),
            ("Long-Term SMA Days",self.bull_long_structural_sma_days),
            ("SMA Slope Comparison Days",self.bull_long_structural_slope_lookback_days),
            ("Structurally Unconfirmed Bull Long Reward/Risk",self.bull_long_structural_unconfirmed_reward_risk_ratio),
            ("",self.enable_bull_long_r_step_trailing),
            ("Staircase Activation (R)",self.bull_long_r_step_activation_r),
            ("Distance Behind Checkpoint (R)",self.bull_long_r_step_distance_r),
            ("Checkpoint Step Size (R)",self.bull_long_r_step_size_r),
            ("Maximum Target (R; 0 = none)",self.bull_long_r_step_maximum_r),
            ("Close at Activation (%)",self.bull_long_r_step_activation_close_pct),
            ("",self.enable_sideways_long_conditional_reward_risk),
            ("Sideways Long ADX Maximum",self.sideways_long_conditional_adx_maximum),
            ("Conditional Sideways Long Reward/Risk",self.sideways_long_conditional_reward_risk_ratio),
            ("",self.enable_sideways_short_conditional_reward_risk),
            ("Sideways Short DI Spread Minimum",self.sideways_short_conditional_di_spread_minimum),
            ("Sideways Short DI Spread Maximum",self.sideways_short_conditional_di_spread_maximum),
            ("Conditional Sideways Short Reward/Risk",self.sideways_short_conditional_reward_risk_ratio),
            ("",self.enable_bear_short_conditional_reward_risk),
            ("Bear Short DI Spread Maximum",self.bear_short_conditional_di_spread_maximum),
            ("Conditional Bear Short Reward/Risk",self.bear_short_conditional_reward_risk_ratio),
            ("",regime_targets_help),
        ]: regime_targets.addRow(lab,w)
        form.addWidget(regime_targets_box)
        adx_box=QGroupBox("Direction-Specific ADX"); adx=QFormLayout(adx_box)
        for lab,w in [
            ("",self.enable_directional_adx_filter),
            ("Long ADX Maximum",self.directional_long_adx_maximum),
            ("Short ADX Minimum",self.directional_short_adx_minimum),
        ]: adx.addRow(lab,w)
        form.addWidget(adx_box)
        regime_box=QGroupBox("Regime Entry Filters"); regime=QFormLayout(regime_box)
        for lab,w in [
            ("",self.enable_bull_regime_short_filter),
            ("Bull Lookback Days",self.bull_regime_lookback_days),
            ("Bull Return Threshold",self.bull_regime_return_threshold),
            ("",self.enable_bear_regime_adx_filter),
            ("Bear ADX Minimum",self.bear_regime_adx_minimum),
            ("",self.enable_biased_short_adx_cap),
            ("Biased Short ADX Maximum",self.biased_short_adx_maximum),
            ("",self.biased_short_adx_help),
            ("",self.enable_short_vwap_distance_filter),
            ("Short VWAP Distance Minimum (ATR)",self.short_vwap_minimum_distance_atr),
            ("",self.short_vwap_distance_help),
            ("",self.enable_long_momentum_filter),
            ("Long Momentum Lookback",self.long_momentum_lookback_hours),
            ("Long Momentum Minimum Return",self.long_momentum_minimum_return),
            ("",self.long_momentum_help),
            ("",self.enable_regime_direction_filter),("",self.allow_bull_long),("",self.allow_bull_short),("",self.allow_bear_long),("",self.allow_bear_short),("",self.allow_sideways_long),("",self.allow_sideways_short),
            ("",self.enable_directional_di_spread_range),("Long DI Spread Minimum",self.directional_long_di_spread_minimum),("Long DI Spread Maximum",self.directional_long_di_spread_maximum),("Short DI Spread Minimum",self.directional_short_di_spread_minimum),("Short DI Spread Maximum",self.directional_short_di_spread_maximum),
            ("",self.enable_directional_adx_range),("Long ADX Minimum",self.directional_long_adx_minimum),("Long ADX Maximum",self.directional_long_adx_range_maximum),("Short ADX Minimum",self.directional_short_adx_range_minimum),("Short ADX Maximum",self.directional_short_adx_maximum),
            ("",self.enable_directional_atr_pct_range),("Long ATR % Minimum",self.directional_long_atr_pct_minimum),("Long ATR % Maximum",self.directional_long_atr_pct_maximum),("Short ATR % Minimum",self.directional_short_atr_pct_minimum),("Short ATR % Maximum",self.directional_short_atr_pct_maximum),
            ("",self.enable_directional_rsi_range),("RSI Period",self.directional_rsi_period),("Long RSI Minimum",self.directional_long_rsi_minimum),("Long RSI Maximum",self.directional_long_rsi_maximum),("Short RSI Minimum",self.directional_short_rsi_minimum),("Short RSI Maximum",self.directional_short_rsi_maximum),
            ("",self.enable_directional_close_location_range),("Long Close Location Minimum",self.directional_long_close_location_minimum),("Long Close Location Maximum",self.directional_long_close_location_maximum),("Short Close Location Minimum",self.directional_short_close_location_minimum),("Short Close Location Maximum",self.directional_short_close_location_maximum),
            ("",self.enable_directional_momentum_range),("Momentum Lookback",self.directional_momentum_lookback_hours),("Long Return Minimum",self.directional_long_momentum_minimum),("Long Return Maximum",self.directional_long_momentum_maximum),("Short Return Minimum",self.directional_short_momentum_minimum),("Short Return Maximum",self.directional_short_momentum_maximum),
        ]: regime.addRow(lab,w)
        form.addWidget(regime_box)
        checkpoint_box=QGroupBox("ATR Checkpoint TP Extension"); checkpoint=QFormLayout(checkpoint_box)
        for lab,w in [
            ("",self.enable_atr_checkpoint_tp_extension),
            ("Checkpoint DI Spread Minimum",self.atr_checkpoint_di_spread_min),
            ("Checkpoint BB Width Minimum",self.atr_checkpoint_bb_width_min),
            ("Profit Lock Starts At (ATR)",self.atr_checkpoint_profit_lock_start),
            ("Profit Lock Distance (ATR)",self.atr_checkpoint_profit_lock_distance),
        ]: checkpoint.addRow(lab,w)
        form.addWidget(checkpoint_box); form.addStretch(1)
        scroll.setWidget(inner); outer.addWidget(scroll); self.di_strategy_page=page
        self.config_controls += inner.findChildren(QWidget)
        self.tabs.addTab(page,"DI Direction & Pressure")
        self.analysis_level.setCurrentText("Standard (Recommended)"); self._apply_analysis_preset(); self._set_analysis_advanced(False)
    def _build_portfolio_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); box=QGroupBox("Shared-Equity Portfolio"); form=QFormLayout(box)
        self.portfolio_assets=[]; asset_widget=QWidget(); self.portfolio_asset_layout=QVBoxLayout(asset_widget); self.portfolio_asset_layout.setContentsMargins(0,0,0,0); form.addRow("Assets",asset_widget)
        add_asset=QPushButton("Add Asset"); add_asset.clicked.connect(lambda:self._add_portfolio_asset()); form.addRow("",add_asset)
        self.portfolio_initial_equity=self._spin(1000,1,1e12,2); self.portfolio_risk_per_asset=QLineEdit("1%"); self.portfolio_maximum_total_risk=QLineEdit("5%")
        self.portfolio_output_folder=QLineEdit("output"); self.portfolio_output_folder.setReadOnly(True); output_btn=QPushButton("Browse"); output_btn.clicked.connect(self._browse_portfolio_output); output_row=QHBoxLayout(); output_row.addWidget(self.portfolio_output_folder); output_row.addWidget(output_btn)
        self.portfolio_help=QLabel(); self.portfolio_help.setWordWrap(True)
        for label,control in [("Starting Equity",self.portfolio_initial_equity),("Base Risk Per Asset",self.portfolio_risk_per_asset),("Maximum Total Portfolio Risk",self.portfolio_maximum_total_risk),("Output Folder",output_row),("",self.portfolio_help)]: form.addRow(label,control)
        self.portfolio_risk_per_asset.textChanged.connect(self._update_portfolio_help); self.portfolio_maximum_total_risk.textChanged.connect(self._update_portfolio_help)
        for symbol in ("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"): self._add_portfolio_asset(symbol)
        layout.addWidget(box); buttons=QHBoxLayout(); self.portfolio_run_btn=QPushButton("Run Portfolio Backtest"); self.portfolio_run_btn.clicked.connect(self.run_portfolio_backtest); self.portfolio_open_btn=QPushButton("Open Portfolio Output"); self.portfolio_open_btn.clicked.connect(self._open_portfolio_output); buttons.addWidget(self.portfolio_run_btn); buttons.addWidget(self.portfolio_open_btn); layout.addLayout(buttons)
        self.portfolio_progress=QProgressBar(); self.portfolio_status=QLabel("Select configurations for at least two enabled assets."); layout.addWidget(self.portfolio_progress); layout.addWidget(self.portfolio_status)
        self.portfolio_summary_table=QTableWidget(0,2); self.portfolio_summary_table.setHorizontalHeaderLabels(["Portfolio Metric","Value"]); self.portfolio_summary_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.portfolio_summary_table); self.tabs.addTab(page,"Portfolio")
    def _add_portfolio_asset(self,symbol=""):
        row=QWidget(); line=QHBoxLayout(row); line.setContentsMargins(0,0,0,0); enabled=QCheckBox("Include"); enabled.setChecked(True); pair=QComboBox(); pair.setEditable(True); pair.addItems(["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]); pair.setCurrentText(symbol or "BTCUSDT"); config=QLineEdit(); config.setReadOnly(True); config.setPlaceholderText("Select this asset's saved configuration"); browse=QPushButton("Browse"); remove=QPushButton("Remove")
        line.addWidget(enabled); line.addWidget(pair); line.addWidget(config,1); line.addWidget(browse); line.addWidget(remove); entry={"row":row,"enabled":enabled,"pair":pair,"config":config}; self.portfolio_assets.append(entry); self.portfolio_asset_layout.addWidget(row)
        browse.clicked.connect(lambda:self._browse_portfolio_config(config)); remove.clicked.connect(lambda:self._remove_portfolio_asset(entry)); enabled.toggled.connect(self._update_portfolio_help); pair.currentTextChanged.connect(self._update_portfolio_help); self._update_portfolio_help()
    def _remove_portfolio_asset(self,entry):
        if entry not in self.portfolio_assets:return
        self.portfolio_assets.remove(entry); self.portfolio_asset_layout.removeWidget(entry["row"]); entry["row"].deleteLater(); self._update_portfolio_help()
    def _update_portfolio_help(self,*_):
        if not hasattr(self,"portfolio_help"):return
        count=sum(item["enabled"].isChecked() for item in self.portfolio_assets)
        try:risk=parse_percentage(self.portfolio_risk_per_asset.text()); requested=format_percentage(risk*count,2); cap=format_percentage(parse_percentage(self.portfolio_maximum_total_risk.text()),2)
        except Exception:requested=cap="invalid"
        self.portfolio_help.setText(f"{count} assets enabled. One open trade per asset would request approximately {requested} total risk. The hard portfolio limit is {cap}; new entries that would exceed it are blocked and reported. Each asset uses its own saved strategy configuration, while all accepted trades share one account.")
    def _browse_portfolio_config(self,target):
        path,_=QFileDialog.getOpenFileName(self,"Select Saved Strategy Configuration","","JSON (*.json)")
        if path: target.setText(path)
    def _browse_portfolio_output(self):
        path=QFileDialog.getExistingDirectory(self,"Select Portfolio Output Folder")
        if path: self.portfolio_output_folder.setText(path)
    def _open_portfolio_output(self):
        path=getattr(self,"portfolio_output_dir",Path(self.portfolio_output_folder.text() or "output"))
        if Path(path).exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
    def run_portfolio_backtest(self):
        try:
            components=[]; seen=set()
            for item in self.portfolio_assets:
                if not item["enabled"].isChecked():continue
                symbol=item["pair"].currentText().strip().upper().replace("/",""); path=item["config"].text().strip()
                if not symbol:raise ValueError("Every enabled asset needs a trading pair.")
                if symbol in seen:raise ValueError(f"{symbol} is included more than once.")
                if not Path(path).is_file():raise ValueError(f"Select a valid saved configuration for {symbol}.")
                values=load_config_json(path); configured=str(values.get("market_symbol") or self._pair_from_path(values.get("strategy_csv") or values.get("input_csv") or "") or "").upper()
                if configured and configured != symbol:raise ValueError(f"{symbol} row uses a {configured} configuration. Select the matching configuration.")
                seen.add(symbol); components.append((symbol,path))
            if len(components)<2:raise ValueError("Enable at least two assets and select their saved configurations.")
            risk=parse_percentage(self.portfolio_risk_per_asset.text())
            if not 0 < risk < 1: raise ValueError("Risk per asset must be above 0% and below 100%.")
            maximum_total_risk=parse_percentage(self.portfolio_maximum_total_risk.text())
            if not risk <= maximum_total_risk < 1: raise ValueError("Maximum total portfolio risk must be at least the per-asset risk and below 100%.")
            output=self.portfolio_output_folder.text().strip() or "output"; Path(output).mkdir(parents=True,exist_ok=True)
        except Exception as exc: QMessageBox.warning(self,"Portfolio Validation",str(exc)); return
        self.portfolio_thread=QThread(); self.portfolio_worker=PortfolioWorker(components,output,self.portfolio_initial_equity.value(),risk,maximum_total_risk); self.portfolio_worker.moveToThread(self.portfolio_thread); self.portfolio_thread.started.connect(self.portfolio_worker.run); self.portfolio_thread.finished.connect(self._portfolio_thread_finished); self.portfolio_worker.status.connect(self._on_portfolio_status); self.portfolio_worker.log.connect(self.append_log); self.portfolio_worker.finished.connect(self._on_portfolio_finished); self.portfolio_worker.failed.connect(self._on_portfolio_failed); self.portfolio_run_btn.setEnabled(False); self.new_run_btn.setEnabled(False); self.portfolio_progress.setValue(0); self.portfolio_thread.start()
    def _on_portfolio_status(self,text,percent): self.portfolio_status.setText(text); self.portfolio_progress.setValue(percent)
    def _on_portfolio_finished(self,summary,trades,equity,out):
        self.portfolio_output_dir=Path(out); self.portfolio_summary_table.setRowCount(len(summary))
        for row,(key,value) in enumerate(summary.items()): self.portfolio_summary_table.setItem(row,0,QTableWidgetItem(str(key))); self.portfolio_summary_table.setItem(row,1,QTableWidgetItem(str(value)))
        self.portfolio_status.setText(f"Completed: {out}"); self._play_completion_sound(); self._cleanup_portfolio_thread()
    def _on_portfolio_failed(self,message,tb): QMessageBox.critical(self,"Portfolio Backtest Error",message); self.append_log(tb); self._cleanup_portfolio_thread()
    def _cleanup_portfolio_thread(self):
        if self.portfolio_thread is not None: self.portfolio_thread.quit()
        else: self.portfolio_run_btn.setEnabled(True)
    def _portfolio_thread_finished(self):
        thread=self.portfolio_thread; self.portfolio_thread=None; self.portfolio_worker=None; self.portfolio_run_btn.setEnabled(True); self.new_run_btn.setEnabled(not bool(self.thread and self.thread.isRunning()))
        if thread is not None: thread.deleteLater()
    def _build_summary(self):
        page=QScrollArea(); page.setWidgetResizable(True); page.setObjectName("summaryScrollArea")
        content=QWidget(); l=QVBoxLayout(content); l.setAlignment(Qt.AlignTop)
        overview=QGroupBox("Performance Overview"); overview_layout=QGridLayout(overview); self.kpi_labels={}
        kpis=("Ending Equity","Total Return","Total Trades","Win Rate","Profit Factor","Maximum Drawdown","Average Net R","Total Net R","Total Fees","Signals Traded / Evaluated")
        for index,label in enumerate(kpis):
            card=QGroupBox(label); card_layout=QVBoxLayout(card); value=QLabel("—"); value.setAlignment(Qt.AlignCenter); value.setStyleSheet("font-size: 18px; font-weight: 600; padding: 4px;")
            card_layout.addWidget(value); self.kpi_labels[label]=value; overview_layout.addWidget(card,index//5,index%5)
        self.starting_equity_label=QLabel("Starting Equity: —"); overview_layout.addWidget(self.starting_equity_label,2,0,1,5)
        l.addWidget(overview)
        reports_box=QGroupBox("Run Reports"); reports_layout=QGridLayout(reports_box)
        labels={"output":"Open Output Folder","backtest":"Open Backtest Report","indicators":"Open Indicator Analysis","sr":"Open S/R Analysis","trades":"Open Trade List","charts":"Open Charts Folder"}
        self.report_buttons={}
        for index,(name,label) in enumerate(labels.items()):
            button=QPushButton(label); button.setEnabled(False); button.clicked.connect(lambda _checked=False, key=name: self._open_report(key))
            self.report_buttons[name]=button; reports_layout.addWidget(button,index//3,index%3)
        l.addWidget(reports_box)
        self.comparison_box=QGroupBox("Direction / Regime Performance"); comparison_layout=QVBoxLayout(self.comparison_box)
        self.combo_table=QTableWidget(0,9); self.combo_table.setHorizontalHeaderLabels(["Market Regime","Direction","Trades","Wins","Losses","Win Rate","Average Net R","Total Net R","Net PnL"]); self.combo_table.setSortingEnabled(False); self.combo_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); self.combo_table.horizontalHeader().setStretchLastSection(True); self.combo_table.verticalHeader().setVisible(False)
        comparison_layout.addWidget(self.combo_table); l.addWidget(self.comparison_box)
        sr_summary_box=QGroupBox("Support / Resistance"); sr_summary_layout=QVBoxLayout(sr_summary_box)
        self.sr_summary_panel_label=QLabel("No backtest run yet."); self.sr_summary_panel_label.setWordWrap(True)
        sr_summary_layout.addWidget(self.sr_summary_panel_label); l.addWidget(sr_summary_box)
        page.setWidget(content); self.summary_scroll_area=page; self.summary_content=content
        self.tabs.addTab(page,"Summary")

    def _size_summary_table(self):
        height=self.combo_table.horizontalHeader().height()+self.combo_table.frameWidth()*2
        height += sum(self.combo_table.rowHeight(row) for row in range(self.combo_table.rowCount()))
        self.combo_table.setFixedHeight(max(80,height+2))

    def _refresh_report_buttons(self):
        states=report_button_states(self.completed_run_dir) if self.completed_run_dir is not None else {name:False for name in REPORT_TARGETS}
        for name,button in self.report_buttons.items(): button.setEnabled(states[name])

    def _open_report(self,name):
        if self.completed_run_dir is None: return
        target=(self.completed_run_dir/REPORT_TARGETS[name]).resolve()
        if target.exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    def _build_log(self):
        # Keep an internal buffer for diagnostics and saved log files without
        # constructing a large interactive Log tab that the workflow does not use.
        self.log=QTextEdit(readOnly=True)
    @staticmethod
    def _timeframe_minutes(label):
        return int(label[:-1]) * (60 if label.endswith("h") else 1)
    @staticmethod
    def _timeframe_label(minutes):
        return f"{minutes // 60}h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes}m"
    def _timeframe_changed(self):
        strategy_minutes=self._timeframe_minutes(self.strategy_timeframe.currentText())
        if strategy_minutes == 1:
            self.use_intrabar.setChecked(False)
        if hasattr(self,"telemetry_interval") and self.telemetry_interval.value() % strategy_minutes:
            self.telemetry_interval.setValue(strategy_minutes)
        self.update_dynamic()
        self.update_planned_output()

    def _base_values(self):
        return {"strategy_timeframe_minutes":self._timeframe_minutes(self.strategy_timeframe.currentText()),"intrabar_timeframe_minutes":self._timeframe_minutes(self.intrabar_timeframe.currentText()),"enable_indicator_lifecycle_analysis":self.enable_lifecycle.isChecked(),"lifecycle_phases":self.lifecycle_phases.value(),"lifecycle_early_checkpoints":[int(v.strip()) for v in self.lifecycle_checkpoints.text().split(",") if v.strip()],"lifecycle_minimum_bucket_sample":self.lifecycle_min_sample.value(),"create_lifecycle_charts":self.lifecycle_charts.isChecked(),"lifecycle_flat_pattern_threshold_pct":self.lifecycle_flat_threshold.value(),"enable_random_entry":self.enable_random_entry.isChecked(),"entry_timing_mode":self.entry_timing_mode.currentText(),"random_entry_probability":self.random_probability.value(),"random_seed":self.random_seed.text().strip(),"random_entry_start_mode":self.random_start_mode.currentText(),"randomize_first_entry":self.randomize_first.isChecked(),"max_random_wait_candles":self.max_random_wait.value(),"enable_random_entry_batch":self.enable_random_batch.isChecked(),"random_seed_start":self.random_seed_start.value(),"random_seed_count":self.random_seed_count.value(),"run_name":self.run_name.text().strip(),"input_csv":self.input_csv.text(),"strategy_csv":self.input_csv.text(),"intrabar_csv":self.intrabar_csv.text(),"use_intrabar_data":self.use_intrabar.isChecked(),"trading_start_date":self.trading_start.text() or None,"trading_end_date":self.trading_end.text() or None,"max_effective_leverage_per_leg":self.max_lev_leg.text() or None,"max_combined_effective_leverage":self.max_lev_combined.text() or None,"intrabar_missing_policy":self.missing_policy.currentText(),"zero_cost_comparison":self.zero_cost.isChecked(),"trade_direction":self.trade_direction.currentText(),"enable_partial_take_profit":self.enable_partial_tp.isChecked(),"enable_partial_stop_loss":self.enable_partial_sl.isChecked(),"sl1_r":self.sl1_r.value(),"sl1_close_pct":self.sl1_close_pct.value(),"sl2_r":self.sl2_r.value(),"tp1_r":self.tp1_r.value(),"tp1_close_pct":self.tp1_close_pct.value(),"tp2_r":self.tp2_r.value(),"tp2_close_pct":self.tp2_close_pct.value(),"stop_loss_r":self.stop_loss_r.value(),"after_tp1_stop_mode":self.after_tp1_stop_mode.currentText(),"after_tp1_stop_offset_r":self.after_tp1_stop_offset_r.value(),"tp2_exit_mode":"FIXED_TP2","enable_trailing_profit":self.enable_trailing_profit.isChecked(),"trail_activation_trigger":self.trail_activation_trigger.currentText(),"trail_activation_r":self.trail_activation_r.value(),"trail_distance_r":self.trail_distance_r.value(),"trail_apply_to":self.trail_apply_to.currentText(),"trail_intrabar_mode":self.trail_intrabar_mode.currentText(),"output_dir":self.output_folder.text(),"sl_mult":self.sl.value(),"tp_mult":self.tp.value(),"entry_mode":self.entry_mode.currentText(),"entry_interval":self.entry_interval.value(),"enable_daily_entry_schedule":self.enable_daily_schedule.isChecked(),"daily_entry_time":self.daily_entry_time.text().strip(),"daily_entry_timezone":self.daily_entry_timezone.text().strip(),"daily_entry_missed_policy":self.daily_entry_missed_policy.currentText(),"enable_skip_monday_entries":self.skip_monday_entries.isChecked(),"skip_monday_timezone":self.skip_monday_timezone.text().strip(),"max_active_pairs":self.max_pairs.value(),"tie_policy":self.tie.currentText(),"risk_mode":self.risk_mode.currentText(),"atr_period":self.atr_period.value(),"atr_multiplier":self.atr_mult.value(),"percent_r":parse_percentage(self.percent_r.text()),"fixed_r":self.fixed_r.value(),"initial_equity":self.equity.value(),"risk_per_leg":parse_percentage(self.risk_leg.text()),"maker_fee":parse_percentage(self.maker.text()),"taker_fee":parse_percentage(self.taker.text()),"use_maker_entry":self.maker_entry.isChecked(),"use_maker_exit":self.maker_exit.isChecked(),"slippage":parse_percentage(self.slippage.text()),"enable_both_open_timeout":self.both_timeout.isChecked(),"max_both_open_minutes":self.both_timeout_duration.value()*(60 if self.both_timeout_unit.currentText()=="Hours" else 1),"both_open_timeout_unit":self.both_timeout_unit.currentText(),"enable_remaining_leg_timeout_after_first_sl":self.remaining_leg_timeout.isChecked(),"remaining_leg_timeout_after_first_sl_minutes":self.remaining_leg_timeout_duration.value()*(60 if self.remaining_leg_timeout_unit.currentText()=="Hours" else 1),"remaining_leg_timeout_after_first_sl_unit":self.remaining_leg_timeout_unit.currentText(),"enable_remaining_leg_timeout_profit_extension":self.remaining_leg_timeout_profit_extension.isChecked(),"remaining_leg_timeout_profit_threshold_r":self.remaining_leg_timeout_profit_threshold_r.value(),"enable_adx_filter":self.enable_adx.isChecked(),"adx_period":self.adx_period.value(),"adx_filter_mode":self.adx_mode.currentText(),"adx_maximum":self.adx_max.value(),"adx_minimum":self.adx_min.value(),"enable_bb_width_filter":self.enable_bb_width.isChecked(),"bb_width_filter_mode":self.bb_width_mode.currentText(),"bb_width_maximum":self.bb_width_max.value(),"bb_width_minimum":self.bb_width_min.value(),"enable_di_spread_filter":self.enable_di_spread.isChecked(),"di_spread_filter_mode":self.di_spread_mode.currentText(),"di_spread_maximum":self.di_spread_max.value(),"di_spread_minimum":self.di_spread_min.value(),"enable_atr_checkpoint_tp_extension":self.enable_atr_checkpoint_tp_extension.isChecked(),"atr_checkpoint_di_spread_minimum":self.atr_checkpoint_di_spread_min.value(),"atr_checkpoint_bb_width_minimum":self.atr_checkpoint_bb_width_min.value(),"atr_checkpoint_profit_lock_start":self.atr_checkpoint_profit_lock_start.value(),"atr_checkpoint_profit_lock_distance":self.atr_checkpoint_profit_lock_distance.value(),"enable_be_after_opposite_sl":self.be_after_sl.isChecked(),"be_mode":self.be_mode.currentText(),"be_offset_r":self.be_offset.value(),"be_same_candle_policy":self.be_same_candle.currentText(),"enable_trade_telemetry":self.enable_trade_telemetry.isChecked(),"save_full_telemetry_csv":self.save_full_telemetry.isChecked(),"save_trade_journey_summary":self.save_journey_summary.isChecked(),"save_trade_journey_charts":self.save_journey_charts.isChecked(),"telemetry_interval_minutes":self.telemetry_interval.value()}
    def values(self):
        values = self._base_values()
        values["market_symbol"]=self.market_symbol.currentText().strip().upper().replace("/","")
        if self.entire_dataset.isChecked():
            values["trading_start_date"]=None; values["trading_end_date"]=None
        values["analysis_level"]=self.analysis_level.currentText().split(" ",1)[0].upper()
        values.update({"entry_mode":self.entry_mode.currentData(),"tie_policy":self.tie.currentData(),"trade_direction":"BOTH","enable_strategy_profiles":True,"enable_di_direction_sizing":True,"di_execution_mode":"PREFERRED_SIDE_ONLY"})
        values.update({"vwap_breakout_lookback_hours":self.vwap_breakout_hours.value(),"vwap_volume_lookback":self.vwap_volume_lookback.value(),"vwap_volume_multiplier":self.vwap_volume_multiplier.value(),"vwap_slope_lookback":self.vwap_slope_lookback.value(),"vwap_atr_pct_minimum":self.vwap_atr_min.value(),"vwap_atr_pct_maximum":self.vwap_atr_max.value(),"vwap_confirmation_mode":self.vwap_confirmation_mode.currentText(),"vwap_retest_window_candles":self.vwap_retest_window.value(),"vwap_retest_tolerance_atr":self.vwap_retest_tolerance.value()})
        values.update({"enable_coin_flip_sizing":self.enable_coin_flip_sizing.isChecked(),"coin_flip_seed":self.coin_flip_seed.text().strip(),"coin_flip_large_multiplier":3.0,"coin_flip_small_multiplier":1.0})
        values.update({"enable_di_direction_sizing":self.enable_di_direction_sizing.isChecked(),"flip_filtered_di_direction":self.flip_filtered_di_direction.isChecked(),"di_direction_minimum_spread":self.di_direction_long_min_spread.value(),"di_direction_long_minimum_spread":self.di_direction_long_min_spread.value(),"di_direction_short_minimum_spread":self.di_direction_short_min_spread.value(),"di_execution_mode":self.di_execution_mode.currentText(),"di_reward_risk_ratio":self.di_long_reward_risk_ratio.value(),"di_long_reward_risk_ratio":self.di_long_reward_risk_ratio.value(),"di_short_reward_risk_ratio":self.di_short_reward_risk_ratio.value()})
        values.update({"enable_support_resistance_analysis":self.enable_support_resistance_analysis.isChecked(),"sr_pivot_left":self.sr_pivot_left.value(),"sr_pivot_right":self.sr_pivot_right.value(),"sr_lookback_bars":self.sr_lookback_bars.value(),"sr_zone_width_atr":self.sr_zone_width_atr.value(),"sr_near_distance_atr":self.sr_near_distance_atr.value(),"enable_sr_hold_confirmation":self.enable_sr_hold_confirmation.isChecked(),"sr_hold_confirmation_bars":self.sr_hold_confirmation_bars.value(),"sr_hold_confirmation_atr":self.sr_hold_confirmation_atr.value(),"sr_break_tolerance_atr":self.sr_break_tolerance_atr.value(),"sr_break_basis":self.sr_break_basis.currentText(),"sr_filter_mode":self.sr_filter_mode.currentData(),"sr_long_avoid_near_resistance":self.sr_long_avoid_near_resistance.isChecked(),"sr_long_require_near_support":self.sr_long_require_near_support.isChecked(),"sr_long_block_broken_support":self.sr_long_block_broken_support.isChecked(),"sr_long_min_room_to_resistance_atr":self.sr_long_min_room_to_resistance_atr.value(),"sr_short_avoid_near_support":self.sr_short_avoid_near_support.isChecked(),"sr_short_require_near_resistance":self.sr_short_require_near_resistance.isChecked(),"sr_short_block_broken_resistance":self.sr_short_block_broken_resistance.isChecked(),"sr_short_min_room_to_support_atr":self.sr_short_min_room_to_support_atr.value()})
        values.update({"enable_di_direction_selection":self.enable_di_direction_selection.isChecked(),"enable_di_pressure_analysis":self.enable_di_pressure_analysis.isChecked(),"di_pressure_lookback":self.di_pressure_lookback.value()})
        values.update({"enable_di_regime_reward_risk":self.enable_di_regime_reward_risk.isChecked(),"di_regime_bear_return_threshold":parse_percentage(self.di_regime_bear_return_threshold.text()),"di_long_bull_reward_risk_ratio":self.di_long_bull_reward_risk_ratio.value(),"di_long_bear_reward_risk_ratio":self.di_long_bear_reward_risk_ratio.value(),"di_long_sideways_reward_risk_ratio":self.di_long_sideways_reward_risk_ratio.value(),"di_short_bull_reward_risk_ratio":self.di_short_bull_reward_risk_ratio.value(),"di_short_bear_reward_risk_ratio":self.di_short_bear_reward_risk_ratio.value(),"di_short_sideways_reward_risk_ratio":self.di_short_sideways_reward_risk_ratio.value()})
        values.update({"enable_bull_long_conditional_reward_risk":self.enable_bull_long_conditional_reward_risk.isChecked(),"bull_long_conditional_bb_width_minimum":parse_percentage(self.bull_long_conditional_bb_width_minimum.text()),"bull_long_conditional_adx_maximum":self.bull_long_conditional_adx_maximum.value(),"bull_long_conditional_reward_risk_ratio":self.bull_long_conditional_reward_risk_ratio.value()})
        values.update({"enable_bull_long_momentum_confirmation":self.enable_bull_long_momentum_confirmation.isChecked(),"bull_long_confirmation_lookback_days":self.bull_long_confirmation_lookback_days.value(),"bull_long_confirmation_return_threshold":parse_percentage(self.bull_long_confirmation_return_threshold.text()),"bull_long_unconfirmed_reward_risk_ratio":self.bull_long_unconfirmed_reward_risk_ratio.value()})
        values.update({"enable_bull_long_momentum_target_extension":self.enable_bull_long_momentum_target_extension.isChecked(),"bull_long_momentum_extension_lookback_days":self.bull_long_momentum_extension_lookback_days.value(),"bull_long_momentum_extension_return_threshold":parse_percentage(self.bull_long_momentum_extension_return_threshold.text()),"enable_bull_long_momentum_extension_return_maximum":self.enable_bull_long_momentum_extension_return_maximum.isChecked(),"bull_long_momentum_extension_return_maximum":parse_percentage(self.bull_long_momentum_extension_return_maximum.text()),"bull_long_momentum_extended_reward_risk_ratio":self.bull_long_momentum_extended_reward_risk_ratio.value()})
        values.update({"enable_bull_long_structural_confirmation":self.enable_bull_long_structural_confirmation.isChecked(),"bull_long_structural_sma_days":self.bull_long_structural_sma_days.value(),"bull_long_structural_slope_lookback_days":self.bull_long_structural_slope_lookback_days.value(),"bull_long_structural_unconfirmed_reward_risk_ratio":self.bull_long_structural_unconfirmed_reward_risk_ratio.value()})
        values.update({"enable_bull_long_r_step_trailing":self.enable_bull_long_r_step_trailing.isChecked(),"bull_long_r_step_activation_r":self.bull_long_r_step_activation_r.value(),"bull_long_r_step_distance_r":self.bull_long_r_step_distance_r.value(),"bull_long_r_step_size_r":self.bull_long_r_step_size_r.value(),"bull_long_r_step_maximum_r":self.bull_long_r_step_maximum_r.value(),"bull_long_r_step_activation_close_pct":self.bull_long_r_step_activation_close_pct.value()})
        values.update({"enable_sideways_long_conditional_reward_risk":self.enable_sideways_long_conditional_reward_risk.isChecked(),"sideways_long_conditional_adx_maximum":self.sideways_long_conditional_adx_maximum.value(),"sideways_long_conditional_reward_risk_ratio":self.sideways_long_conditional_reward_risk_ratio.value(),"enable_sideways_short_conditional_reward_risk":self.enable_sideways_short_conditional_reward_risk.isChecked(),"sideways_short_conditional_di_spread_minimum":self.sideways_short_conditional_di_spread_minimum.value(),"sideways_short_conditional_di_spread_maximum":self.sideways_short_conditional_di_spread_maximum.value(),"sideways_short_conditional_reward_risk_ratio":self.sideways_short_conditional_reward_risk_ratio.value(),"enable_bear_short_conditional_reward_risk":self.enable_bear_short_conditional_reward_risk.isChecked(),"bear_short_conditional_di_spread_maximum":self.bear_short_conditional_di_spread_maximum.value(),"bear_short_conditional_reward_risk_ratio":self.bear_short_conditional_reward_risk_ratio.value()})
        values.update({"enable_directional_adx_filter":self.enable_directional_adx_filter.isChecked(),"directional_long_adx_maximum":self.directional_long_adx_maximum.value(),"directional_short_adx_minimum":self.directional_short_adx_minimum.value()})
        values.update({"enable_biased_short_adx_cap":self.enable_biased_short_adx_cap.isChecked(),"biased_short_adx_maximum":self.biased_short_adx_maximum.value()})
        values.update({"enable_short_vwap_distance_filter":self.enable_short_vwap_distance_filter.isChecked(),"short_vwap_minimum_distance_atr":self.short_vwap_minimum_distance_atr.value()})
        values.update({"enable_long_momentum_filter":self.enable_long_momentum_filter.isChecked(),"long_momentum_lookback_hours":self.long_momentum_lookback_hours.value(),"long_momentum_minimum_return":parse_percentage(self.long_momentum_minimum_return.text())})
        values.update({"enable_regime_direction_filter":self.enable_regime_direction_filter.isChecked(),"allow_bull_long":self.allow_bull_long.isChecked(),"allow_bull_short":self.allow_bull_short.isChecked(),"allow_bear_long":self.allow_bear_long.isChecked(),"allow_bear_short":self.allow_bear_short.isChecked(),"allow_sideways_long":self.allow_sideways_long.isChecked(),"allow_sideways_short":self.allow_sideways_short.isChecked(),"enable_directional_di_spread_range":self.enable_directional_di_spread_range.isChecked(),"directional_long_di_spread_minimum":self.directional_long_di_spread_minimum.value(),"directional_long_di_spread_maximum":self.directional_long_di_spread_maximum.value(),"directional_short_di_spread_minimum":self.directional_short_di_spread_minimum.value(),"directional_short_di_spread_maximum":self.directional_short_di_spread_maximum.value(),"enable_directional_adx_range":self.enable_directional_adx_range.isChecked(),"directional_long_adx_minimum":self.directional_long_adx_minimum.value(),"directional_long_adx_range_maximum":self.directional_long_adx_range_maximum.value(),"directional_short_adx_range_minimum":self.directional_short_adx_range_minimum.value(),"directional_short_adx_maximum":self.directional_short_adx_maximum.value(),"enable_directional_atr_pct_range":self.enable_directional_atr_pct_range.isChecked(),"directional_long_atr_pct_minimum":parse_percentage(self.directional_long_atr_pct_minimum.text()),"directional_long_atr_pct_maximum":parse_percentage(self.directional_long_atr_pct_maximum.text()),"directional_short_atr_pct_minimum":parse_percentage(self.directional_short_atr_pct_minimum.text()),"directional_short_atr_pct_maximum":parse_percentage(self.directional_short_atr_pct_maximum.text()),"enable_directional_rsi_range":self.enable_directional_rsi_range.isChecked(),"directional_rsi_period":self.directional_rsi_period.value(),"directional_long_rsi_minimum":self.directional_long_rsi_minimum.value(),"directional_long_rsi_maximum":self.directional_long_rsi_maximum.value(),"directional_short_rsi_minimum":self.directional_short_rsi_minimum.value(),"directional_short_rsi_maximum":self.directional_short_rsi_maximum.value(),"enable_directional_close_location_range":self.enable_directional_close_location_range.isChecked(),"directional_long_close_location_minimum":parse_percentage(self.directional_long_close_location_minimum.text()),"directional_long_close_location_maximum":parse_percentage(self.directional_long_close_location_maximum.text()),"directional_short_close_location_minimum":parse_percentage(self.directional_short_close_location_minimum.text()),"directional_short_close_location_maximum":parse_percentage(self.directional_short_close_location_maximum.text()),"enable_directional_momentum_range":self.enable_directional_momentum_range.isChecked(),"directional_momentum_lookback_hours":self.directional_momentum_lookback_hours.value(),"directional_long_momentum_minimum":parse_percentage(self.directional_long_momentum_minimum.text()),"directional_long_momentum_maximum":parse_percentage(self.directional_long_momentum_maximum.text()),"directional_short_momentum_minimum":parse_percentage(self.directional_short_momentum_minimum.text()),"directional_short_momentum_maximum":parse_percentage(self.directional_short_momentum_maximum.text())})
        values.update({"enable_bull_regime_short_filter":self.enable_bull_regime_short_filter.isChecked(),"bull_regime_lookback_days":self.bull_regime_lookback_days.value(),"bull_regime_return_threshold":parse_percentage(self.bull_regime_return_threshold.text())})
        values.update({"enable_bear_regime_adx_filter":self.enable_bear_regime_adx_filter.isChecked(),"bear_regime_adx_minimum":self.bear_regime_adx_minimum.value()})
        values.update({"enable_partial_stop_loss":self.enable_partial_sl.isChecked(),"sl1_r":self.sl1_r.value(),"sl1_close_pct":self.sl1_close_pct.value(),"sl2_r":self.sl2_r.value()})
        values["enable_reentry_gate_after_remaining_leg_timeout"] = self.reentry_gate_after_timeout.isChecked()
        values.update({
            "enable_remaining_leg_checkpoint_score_extension":self.checkpoint_score_extension.isChecked(),
            "checkpoint_score_use_profit":self.checkpoint_score_use_profit.isChecked(),
            "checkpoint_score_min_profit_r":self.checkpoint_score_min_profit_r.value(),
            "checkpoint_score_use_atr_pct":self.checkpoint_score_use_atr.isChecked(),
            "checkpoint_score_max_atr_pct":self.checkpoint_score_max_atr_pct.value(),
            "checkpoint_score_use_directional_di":self.checkpoint_score_use_di.isChecked(),
            "checkpoint_score_min_directional_di":self.checkpoint_score_min_di.value(),
            "checkpoint_score_use_bb_width_pct":self.checkpoint_score_use_bb.isChecked(),
            "checkpoint_score_max_bb_width_pct":self.checkpoint_score_max_bb_pct.value(),
            "checkpoint_score_min_conditions":self.checkpoint_score_required.value(),
            "enable_first_sl_survivor_partial_close":self.first_sl_survivor_partial.isChecked(),
            "first_sl_survivor_partial_close_pct":self.first_sl_survivor_partial_pct.value(),
            "enable_checkpoint_zero_score_confirmation":self.zero_score_confirmation.isChecked(),
            "checkpoint_zero_score_confirmations_required":self.zero_score_confirmations.value(),
            "checkpoint_zero_score_recheck_minutes":self.zero_score_recheck_duration.value()*(60 if self.zero_score_recheck_unit.currentText()=="Hours" else 1),
            "checkpoint_zero_score_recheck_unit":self.zero_score_recheck_unit.currentText(),
        })
        values.update(self.profile_editor.values())
        return values

    def _update_checkpoint_score_controls(self,*_):
        enabled=self.remaining_leg_timeout.isChecked() and self.checkpoint_score_extension.isChecked()
        self.checkpoint_score_extension.setEnabled(self.remaining_leg_timeout.isChecked())
        for control in [self.checkpoint_score_use_profit,self.checkpoint_score_use_atr,self.checkpoint_score_use_di,self.checkpoint_score_use_bb,self.checkpoint_score_required]:
            control.setEnabled(enabled)
        self.checkpoint_score_min_profit_r.setEnabled(enabled and self.checkpoint_score_use_profit.isChecked())
        self.checkpoint_score_max_atr_pct.setEnabled(enabled and self.checkpoint_score_use_atr.isChecked())
        self.checkpoint_score_min_di.setEnabled(enabled and self.checkpoint_score_use_di.isChecked())
        self.checkpoint_score_max_bb_pct.setEnabled(enabled and self.checkpoint_score_use_bb.isChecked())
        self.zero_score_confirmation.setEnabled(enabled)
        confirmation_enabled=enabled and self.zero_score_confirmation.isChecked()
        self.zero_score_confirmations.setEnabled(confirmation_enabled)
        self.zero_score_recheck_duration.setEnabled(confirmation_enabled)
        self.zero_score_recheck_unit.setEnabled(confirmation_enabled)

    def _apply_analysis_preset(self,*_):
        level=self.analysis_level.currentText()
        fast=level=="Fast"; research=level=="Research"
        self.enable_trade_telemetry.setChecked(research); self.save_full_telemetry.setChecked(research); self.save_journey_summary.setChecked(research); self.save_journey_charts.setChecked(research)
        self.enable_lifecycle.setChecked(research); self.lifecycle_charts.setChecked(research)
        self.save_feature_reports.setChecked(research); self.save_indicator_reports.setChecked(not fast); self.create_standard_charts.setChecked(not fast)
        descriptions={"Fast":"Core results only. Best for quick parameter checks.","Standard (Recommended)":"Performance charts and indicator summaries without heavy candle-by-candle telemetry.","Research":"Full telemetry, trade journeys, lifecycle analysis, diagnostics, and all charts. Slowest and produces the most files."}
        self.analysis_description.setText(descriptions[level])

    def _set_analysis_advanced(self,shown):
        self.analysis_advanced.setChecked(bool(shown)); self.analysis_advanced.setText("Hide Advanced Settings" if shown else "Show Advanced Settings")
        for widget in self.analysis_detail_widgets:
            widget.setVisible(shown); label=widget.parentWidget().layout().labelForField(widget) if isinstance(widget.parentWidget().layout(),QFormLayout) else None
            if label: label.setVisible(shown)
        self.enable_lifecycle.parentWidget().setVisible(shown); self.save_feature_reports.parentWidget().setVisible(shown)

    def reset_defaults(self):
        defaults=default_gui_config()
        defaults.update({"enable_di_direction_sizing":True,"enable_di_direction_selection":True,"enable_di_pressure_analysis":True,"di_pressure_lookback":3})
        self.apply_values(defaults)

    def new_run(self):
        """Confirm and prepare a fresh configuration without touching persisted data."""
        if self._git_work_active(): return
        if not self._confirm_new_run(): return
        self.apply_values(default_gui_config())
        self._clear_displayed_results()

    def _confirm_new_run(self):
        prompt=QMessageBox(self); prompt.setWindowTitle("Start a new run?")
        prompt.setText("Start a new run?")
        prompt.setInformativeText(
            "This will reset the backtest setup and strategy settings\n"
            "to their default values.\n\n"
            "Existing backtest results and market data will not be deleted.")
        prompt.addButton(QMessageBox.Cancel)
        confirm=prompt.addButton("New Run",QMessageBox.AcceptRole)
        prompt.setDefaultButton(QMessageBox.Cancel); prompt.exec()
        return prompt.clickedButton() is confirm

    def _clear_displayed_results(self):
        """Clear in-memory result presentation, never persisted run artifacts."""
        self.last_summary={}; self._pending_ui_results=None; self.completed_run_dir=None
        self._refresh_report_buttons()
        self.populate_summary({},pd.DataFrame())
        self.sr_summary_panel_label.setText("No backtest run yet.")
        self.progress.setValue(0); self.status.setText("Ready"); self.elapsed.setText("Elapsed: 0s")
        self.update_dynamic(); self.update_planned_output()
    def _restore_settings(self):
        self.output_folder.setText(self.settings.value("last_output", self.output_folder.text())); self._sync_dataset_paths()
    def browse_csv(self):
        p,_=QFileDialog.getOpenFileName(self,"Select CSV",self.input_csv.text(),"CSV files (*.csv)");
        if p:
            self.input_csv.setText(p); self.settings.setValue("last_csv",p); pair=self._pair_from_path(p)
            if pair: self.market_symbol.setCurrentText(pair)
            self.validate_data()
    def browse_intrabar_csv(self):
        p,_=QFileDialog.getOpenFileName(self,"Select Intrabar CSV",self.intrabar_csv.text(),"CSV files (*.csv)");
        if p: self.intrabar_csv.setText(p)
    @staticmethod
    def _pair_from_path(path):
        match=re.search(r"([A-Z0-9]+USDT)(?:[_-]|$)",Path(path).stem.upper())
        return match.group(1) if match else None
    def _sync_dataset_paths(self,*_):
        if getattr(self,"_applying_values",False): return
        symbol=self.market_symbol.currentText().strip().upper().replace("/","")
        def matching_file(timeframe):
            expected=self.market_data_folder/f"{symbol}_{timeframe}.csv"
            if expected.exists(): return str(expected.resolve())
            if self.market_data_folder.is_dir():
                match=next((path for path in self.market_data_folder.glob("*.csv") if path.name.lower()==expected.name.lower()),None)
                if match: return str(match.resolve())
            return ""
        self.input_csv.setText(matching_file(self.strategy_timeframe.currentText()))
        self.intrabar_csv.setText(matching_file(self.intrabar_timeframe.currentText()) if self.use_intrabar.isChecked() else "")
        if hasattr(self,"dataset_info"): self.dataset_info.setText("Matching shared dataset selected." if self.input_csv.text() else f"No matching dataset in {self.market_data_folder}. Open Binance Data Hub to download it.")
        if hasattr(self,"planned_output"): self.update_planned_output()
    def browse_output(self):
        p=QFileDialog.getExistingDirectory(self,"Select Output Folder",self.output_folder.text());
        if p: self.output_folder.setText(p); self.settings.setValue("last_output",p)
    def validate_data(self):
        try:
            strategy_pair=self._pair_from_path(self.input_csv.text()); intrabar_pair=self._pair_from_path(self.intrabar_csv.text()) if self.use_intrabar.isChecked() else None; selected=self.market_symbol.currentText().strip().upper().replace("/","")
            if strategy_pair and intrabar_pair and strategy_pair != intrabar_pair: raise ValueError(f"Dataset pair mismatch: strategy file is {strategy_pair}, but intrabar file is {intrabar_pair}.")
            if strategy_pair and selected and strategy_pair != selected: raise ValueError(f"Selected pair is {selected}, but the strategy filename identifies {strategy_pair}.")
            df=load_ohlcv_csv(self.input_csv.text(), expected_timeframe_minutes=self._timeframe_minutes(self.strategy_timeframe.currentText()), label="Strategy data", strict_timeframe=True); self._validated_strategy_data=df; sm=df.attrs.get("summary"); miss=sm.missing_candles; tf=f"{sm.detected_timeframe_minutes} minutes"; self.dataset_info.setText(f"Total candles: {len(df):,}\nStart date: {df.timestamp.min()}\nEnd date: {df.timestamp.max()}\nDetected timeframe: {tf}\nMissing candles: {miss}\nRows removed: see log/console\nDuplicate candles removed: see log/console"); self.append_log("Data validation passed."); return True
        except Exception as e: QMessageBox.warning(self,"Invalid CSV",str(e)); self.append_log(traceback.format_exc()); return False
    def update_planned_output(self):
        try:
            cfg=build_backtest_config(self.values(), require_paths=False); self.planned_output.setText(str(planned_run_dir(cfg).resolve()))
        except Exception:
            self.planned_output.setText("Output run folder: unavailable until configuration is valid")
    def update_dynamic(self):
        self.entry_interval.setEnabled(self.entry_mode.currentData()=="EVERY_N_CANDLES")
        self.max_pairs.setEnabled(self.entry_mode.currentData()=="EVERY_N_CANDLES")
        self._update_sr_tab_state()
        if hasattr(self,"strategy_timeframe"):
            strategy=self._timeframe_minutes(self.strategy_timeframe.currentText())
            intrabar=self._timeframe_minutes(self.intrabar_timeframe.currentText())
            available=strategy > 1
            self.use_intrabar.setEnabled(available)
            intrabar_enabled=available and self.use_intrabar.isChecked()
            self.intrabar_timeframe.setEnabled(intrabar_enabled)
            self.intrabar_csv.setEnabled(intrabar_enabled)
        self.missing_policy.setEnabled(intrabar_enabled)
        policy_help={
            "WARN_AND_USE_15M":f"If {self.intrabar_timeframe.currentText()} data is incomplete, that affected interval is evaluated using its {self.strategy_timeframe.currentText()} strategy candle.",
            "ERROR":f"The run stops if any required {self.intrabar_timeframe.currentText()} candle is missing during an open trade.",
            "WARN_AND_CONTINUE":f"Available {self.intrabar_timeframe.currentText()} candles are evaluated and missing portions are skipped.",
        }.get(self.missing_policy.currentData(),"")
        self.data_help.setText(f"ATR, entry price, SL, and TP are calculated from {self.strategy_timeframe.currentText()} candles.\n" + (f"{self.intrabar_timeframe.currentText()} candles determine the exact exit sequence. {policy_help}\n" if self.use_intrabar.isChecked() else "Intrabar exit resolution is disabled.\n") + "Fees are charged on full notional, not margin; leverage changes required margin but does not reduce trading fees.")
        m=getattr(self,'risk_mode',None) and self.risk_mode.currentText(); self.atr_period.setVisible(m=="ATR"); self.atr_mult.setVisible(m=="ATR"); self.percent_r.setVisible(m=="PERCENT"); self.fixed_r.setVisible(m=="FIXED"); self.risk_formula.setText({"ATR":"R = ATR × ATR Multiplier","PERCENT":"R = Entry Price × Percentage","FIXED":"R = Fixed Price Distance"}.get(m,""));
        if hasattr(self,"account_form"):
            self.account_form.setRowVisible(self.atr_period,m=="ATR"); self.account_form.setRowVisible(self.atr_mult,m=="ATR")
            self.account_form.setRowVisible(self.percent_r,m=="PERCENT"); self.account_form.setRowVisible(self.fixed_r,m=="FIXED")
        if hasattr(self,"period_form"):
            custom_period=not self.entire_dataset.isChecked()
            self.period_form.setRowVisible(self.trading_start,custom_period); self.period_form.setRowVisible(self.trading_end,custom_period)
        try:
            r=parse_percentage(self.risk_leg.text()); multiplier=1.0; profile_name="Selected profile"
            if hasattr(self,"profile_editor"):
                profile_name=self.profile_editor.current.replace("_"," ").title()
                multiplier=float(self.profile_editor.profiles[self.profile_editor.current].risk_multiplier)
            planned=r*multiplier
            self.risk_warn.setText(f"Base {format_percentage(r,2)} × {profile_name} {multiplier:g} = {format_percentage(planned,2)} per trade" + (" — warning: exceeds 5%." if planned>0.05 else ""))
        except Exception: pass
        if hasattr(self,"enable_daily_schedule"):
            en=self.enable_daily_schedule.isChecked(); self.daily_entry_time.setEnabled(en); self.daily_entry_timezone.setEnabled(en); self.daily_entry_missed_policy.setEnabled(en); self.next_entry_summary.setText(f"Next eligible entry time: {self.daily_entry_time.text() or '00:00'} {self.daily_entry_timezone.text() or 'UTC'}" if en else "Daily schedule disabled; existing entry mode controls entries.")
        if hasattr(self,"vwap_confirmation_mode"):
            retest=self.entry_mode.currentData()=="VWAP_VOLUME_BREAKOUT" and self.vwap_confirmation_mode.currentText()=="RETEST"
            self.vwap_retest_window.setEnabled(retest); self.vwap_retest_tolerance.setEnabled(retest)
        if hasattr(self,"enable_atr_checkpoint_tp_extension"):
            checkpoint_enabled=self.enable_atr_checkpoint_tp_extension.isChecked() and self.enable_di_direction_sizing.isChecked()
            self.enable_atr_checkpoint_tp_extension.setEnabled(self.enable_di_direction_sizing.isChecked())
            for control in (self.atr_checkpoint_di_spread_min,self.atr_checkpoint_bb_width_min,self.atr_checkpoint_profit_lock_start,self.atr_checkpoint_profit_lock_distance):
                control.setEnabled(checkpoint_enabled)
        if hasattr(self,"enable_biased_short_adx_cap"):
            di_enabled=self.enable_di_direction_sizing.isChecked()
            self.di_long_reward_risk_ratio.setEnabled(di_enabled)
            self.di_short_reward_risk_ratio.setEnabled(di_enabled)
            self.enable_di_regime_reward_risk.setEnabled(di_enabled)
            regime_rr_enabled=di_enabled and self.enable_di_regime_reward_risk.isChecked()
            for control in (self.di_regime_bear_return_threshold,self.di_long_bull_reward_risk_ratio,self.di_long_bear_reward_risk_ratio,self.di_long_sideways_reward_risk_ratio,self.di_short_bull_reward_risk_ratio,self.di_short_bear_reward_risk_ratio,self.di_short_sideways_reward_risk_ratio):
                control.setEnabled(regime_rr_enabled)
            self.enable_bull_long_conditional_reward_risk.setEnabled(regime_rr_enabled)
            conditional_bull_long_enabled=regime_rr_enabled and self.enable_bull_long_conditional_reward_risk.isChecked()
            for control in (self.bull_long_conditional_bb_width_minimum,self.bull_long_conditional_adx_maximum,self.bull_long_conditional_reward_risk_ratio):
                control.setEnabled(conditional_bull_long_enabled)
            self.enable_bull_long_momentum_confirmation.setEnabled(regime_rr_enabled)
            momentum_confirmation_enabled=regime_rr_enabled and self.enable_bull_long_momentum_confirmation.isChecked()
            for control in (self.bull_long_confirmation_lookback_days,self.bull_long_confirmation_return_threshold,self.bull_long_unconfirmed_reward_risk_ratio):
                control.setEnabled(momentum_confirmation_enabled)
            self.enable_bull_long_momentum_target_extension.setEnabled(regime_rr_enabled)
            momentum_extension_enabled=regime_rr_enabled and self.enable_bull_long_momentum_target_extension.isChecked()
            for control in (self.bull_long_momentum_extension_lookback_days,self.bull_long_momentum_extension_return_threshold,self.enable_bull_long_momentum_extension_return_maximum,self.bull_long_momentum_extended_reward_risk_ratio):
                control.setEnabled(momentum_extension_enabled)
            self.bull_long_momentum_extension_return_maximum.setEnabled(momentum_extension_enabled and self.enable_bull_long_momentum_extension_return_maximum.isChecked())
            self.enable_bull_long_structural_confirmation.setEnabled(regime_rr_enabled)
            structural_confirmation_enabled=regime_rr_enabled and self.enable_bull_long_structural_confirmation.isChecked()
            for control in (self.bull_long_structural_sma_days,self.bull_long_structural_slope_lookback_days,self.bull_long_structural_unconfirmed_reward_risk_ratio):
                control.setEnabled(structural_confirmation_enabled)
            self.enable_bull_long_r_step_trailing.setEnabled(regime_rr_enabled)
            staircase_enabled=regime_rr_enabled and self.enable_bull_long_r_step_trailing.isChecked()
            for control in (self.bull_long_r_step_activation_r,self.bull_long_r_step_distance_r,self.bull_long_r_step_size_r,self.bull_long_r_step_maximum_r,self.bull_long_r_step_activation_close_pct):
                control.setEnabled(staircase_enabled)
            for checkbox, controls in (
                (self.enable_sideways_long_conditional_reward_risk,(self.sideways_long_conditional_adx_maximum,self.sideways_long_conditional_reward_risk_ratio)),
                (self.enable_sideways_short_conditional_reward_risk,(self.sideways_short_conditional_di_spread_minimum,self.sideways_short_conditional_di_spread_maximum,self.sideways_short_conditional_reward_risk_ratio)),
                (self.enable_bear_short_conditional_reward_risk,(self.bear_short_conditional_di_spread_maximum,self.bear_short_conditional_reward_risk_ratio)),
            ):
                checkbox.setEnabled(regime_rr_enabled)
                for control in controls:
                    control.setEnabled(regime_rr_enabled and checkbox.isChecked())
            self.enable_directional_adx_filter.setEnabled(di_enabled)
            directional_adx_enabled=di_enabled and self.enable_directional_adx_filter.isChecked()
            self.directional_long_adx_maximum.setEnabled(directional_adx_enabled)
            self.directional_short_adx_minimum.setEnabled(directional_adx_enabled)
            self.enable_biased_short_adx_cap.setEnabled(di_enabled)
            self.biased_short_adx_maximum.setEnabled(di_enabled and self.enable_biased_short_adx_cap.isChecked())
            self.enable_short_vwap_distance_filter.setEnabled(di_enabled)
            self.short_vwap_minimum_distance_atr.setEnabled(di_enabled and self.enable_short_vwap_distance_filter.isChecked())
            self.enable_long_momentum_filter.setEnabled(di_enabled)
            long_momentum_enabled=di_enabled and self.enable_long_momentum_filter.isChecked()
            self.long_momentum_lookback_hours.setEnabled(long_momentum_enabled)
            self.long_momentum_minimum_return.setEnabled(long_momentum_enabled)
            self.enable_bear_regime_adx_filter.setEnabled(di_enabled)
            self.bear_regime_adx_minimum.setEnabled(di_enabled and self.enable_bear_regime_adx_filter.isChecked())
        if hasattr(self,"enable_trade_telemetry"):
            enabled=self.enable_trade_telemetry.isChecked(); self.telemetry_interval.setEnabled(enabled); self.save_full_telemetry.setEnabled(enabled); self.save_journey_summary.setEnabled(enabled); self.save_journey_charts.setEnabled(enabled)
        if hasattr(self,"enable_partial_sl"):
            partial_sl_enabled=self.enable_partial_sl.isChecked()
            for control in (self.sl1_r,self.sl1_close_pct,self.sl2_r): control.setEnabled(partial_sl_enabled)
            partial_tp_enabled=self.enable_partial_tp.isChecked()
            for control in (self.tp1_r,self.tp1_close_pct,self.tp2_r,self.after_tp1_stop_mode): control.setEnabled(partial_tp_enabled)
            self.stop_loss_r.setEnabled(partial_tp_enabled and not partial_sl_enabled)
            self.tp2_close_pct.setEnabled(False)
            self.after_tp1_stop_offset_r.setEnabled(partial_tp_enabled and self.after_tp1_stop_mode.currentText()=="MOVE_TO_R_OFFSET")
            self.sl.setEnabled(not partial_sl_enabled and not partial_tp_enabled)
            self.tp.setEnabled(not partial_tp_enabled)
            trailing_enabled=self.enable_trailing_profit.isChecked()
            self.trail_activation_trigger.setEnabled(trailing_enabled)
            self.trail_activation_r.setEnabled(trailing_enabled and self.trail_activation_trigger.currentText()=="PRICE_REACHES_R")
            for control in (self.trail_distance_r,self.trail_intrabar_mode): control.setEnabled(trailing_enabled)
            self.trail_apply_to.setEnabled(trailing_enabled)
            if partial_tp_enabled and partial_sl_enabled:
                if self.after_tp1_stop_mode.currentText()=="KEEP_ORIGINAL_SL":
                    message="SL1 and SL2 control protection. After TP1, the pending SL1 → SL2 ladder remains active for the remaining quantity."
                elif self.after_tp1_stop_mode.currentText()=="MOVE_TO_ENTRY":
                    message="SL1 and SL2 protect the position before TP1. After TP1, their pending levels are replaced by one stop at the entry price."
                else:
                    message="SL1 and SL2 protect the position before TP1. After TP1, their pending levels are replaced by one stop at the configured favourable R offset."
            elif partial_tp_enabled:
                if self.after_tp1_stop_mode.currentText()=="KEEP_ORIGINAL_SL":
                    message="The standalone SL protects 100% before TP1 and continues protecting all remaining quantity at the same price after TP1."
                elif self.after_tp1_stop_mode.currentText()=="MOVE_TO_ENTRY":
                    message="The standalone SL protects 100% before TP1. After TP1, the remaining stop moves to the entry price."
                else:
                    message="The standalone SL protects 100% before TP1. After TP1, the remaining stop moves to the configured favourable R offset."
            else:
                message="Enable Partial Take Profit to configure how the remaining quantity is protected after TP1."
            self.protective_stop_help.setText(message)
            if trailing_enabled:
                trigger=self.trail_activation_trigger.currentText()
                trigger_text={"PRICE_REACHES_R":"the configured favourable R distance","AFTER_TP1":"TP1 fills","AFTER_SL1":"SL1 fills","AFTER_TP1_OR_SL1":"either TP1 or SL1 fills"}[trigger]
                self.trailing_help.setText(f"Trailing activates when {trigger_text}. It tightens the active stop for remaining quantity; fixed TP2 and SL2 stay active.")
            else:
                self.trailing_help.setText("Enable trailing to tighten the active protective stop independently. Fixed TP2 and SL2 remain final exits.")
        if hasattr(self,"adx_mode"):
            enabled=self.enable_adx.isChecked() and self.adx_mode.currentText() != "Disabled"
            self.adx_period.setEnabled(self.enable_adx.isChecked())
            self.adx_mode.setEnabled(self.enable_adx.isChecked())
            self.adx_max.setEnabled(enabled and self.adx_mode.currentText() in ("ADX <= Maximum","Range"))
            self.adx_min.setEnabled(enabled and self.adx_mode.currentText() in ("ADX >= Minimum","Range"))
        if hasattr(self,"bb_width_mode"):
            bben=self.enable_bb_width.isChecked() and self.bb_width_mode.currentText() != "Disabled"
            self.bb_width_mode.setEnabled(self.enable_bb_width.isChecked()); self.bb_width_max.setEnabled(bben and self.bb_width_mode.currentText() in ("Maximum Width","Range")); self.bb_width_min.setEnabled(bben and self.bb_width_mode.currentText() in ("Minimum Width","Range"))
            self.skip_monday_timezone.setEnabled(self.skip_monday_entries.isChecked())
            dien=self.enable_di_spread.isChecked() and self.di_spread_mode.currentText() != "Disabled"
            self.di_spread_mode.setEnabled(self.enable_di_spread.isChecked()); self.di_spread_max.setEnabled(dien and self.di_spread_mode.currentText() in ("Maximum Spread","Range")); self.di_spread_min.setEnabled(dien and self.di_spread_mode.currentText() in ("Minimum Spread","Range"))
        try:
            maker=parse_percentage(self.maker.text()); taker=parse_percentage(self.taker.text()); slip=parse_percentage(self.slippage.text())
            entry_fee=maker if self.maker_entry.isChecked() else taker; exit_fee=maker if self.maker_exit.isChecked() else taker
            fees=entry_fee+exit_fee; slippage_cost=slip*2; cost=fees+slippage_cost
            self.cost.setText(f"Estimated cost for one trade (entry + final exit): {format_percentage(cost,4)} of notional — fees {format_percentage(fees,4)} + slippage {format_percentage(slippage_cost,4)}. Partial exits and changing exit value can alter the actual cost.")
        except Exception: self.cost.setText("Invalid execution-cost input")
        try: be=theoretical_break_even(self.sl.value(),self.tp.value()); actual=self.last_summary.get('win_rate'); diff="n/a" if actual is None else format_percentage(actual-be,2); self.be_label.setText(f"Theoretical break-even before fees: {format_percentage(be,2)}\nActual backtest win rate: {format_percentage(actual,2) if actual is not None else 'n/a'}\nDifference from break-even: {diff}\nThe theoretical value assumes every winner is exactly one TP and one SL. Fees, slippage, end-of-data exits, and other outcomes increase the actual required win rate.")
        except Exception: pass
    def run_backtest(self):
        try: vals=self.values(); cfg=build_backtest_config(vals); cfg=replace(cfg, save_feature_analysis_reports=self.save_feature_reports.isChecked(), save_indicator_analysis_reports=self.save_indicator_reports.isChecked(), create_standard_charts=self.create_standard_charts.isChecked()); Path(vals['output_dir']).mkdir(parents=True,exist_ok=True); cfg=replace(cfg, output_run_dir=planned_run_dir(cfg)); self.planned_output.setText(str(cfg.output_run_dir.resolve()))
        except Exception as e: QMessageBox.warning(self,"Validation Problems",str(e)); return
        if not self.validate_data(): return
        self._run_failed=False; self._pending_ui_results=None; self.output_dir=cfg.output_run_dir; self.thread=QThread(); self.worker=BacktestWorker(cfg, self._validated_strategy_data); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.thread.finished.connect(self._thread_finished); self.worker.status.connect(self.on_status); self.worker.log.connect(self.append_log); self.worker.finished.connect(self.on_finished); self.worker.failed.connect(self.on_failed); self.started=time.time(); self._set_backtest_running(True); self.thread.start()
    def _set_backtest_running(self,running):
        """Keep setup actions consistent with the single-backtest worker state."""
        self.run_btn.setEnabled(not running)
        self.run_btn.setText("Running..." if running else "Run Backtest")
        self.cancel_btn.setEnabled(running)
        self.new_run_btn.setEnabled(not running and not bool(self.portfolio_thread and self.portfolio_thread.isRunning()))
        self.load_btn.setEnabled(not running)
    def on_status(self,s,p): self.status.setText(s); self.progress.setValue(p); self.elapsed.setText(f"Elapsed: {int(time.time()-self.started)}s")
    def on_finished(self,summary,trades,equity,out):
        self.last_summary=summary; self.output_dir=Path(out); self.completed_run_dir=self.output_dir; self._pending_ui_results=(summary,trades,equity,out)
        self._refresh_report_buttons()
        self.cleanup_thread()
        # The backtest and all output files are complete at this point.  Do not
        # hold the run at 99% while optional GUI views are being refreshed.
        self.progress.setValue(100); self.status.setText(f"Completed | Results saved to {self.output_dir}"); self._play_completion_sound()
        QTimer.singleShot(0,self._finish_summary_view)

    @staticmethod
    def _play_completion_sound():
        """Play the operating system's standard notification sound."""
        try:
            QApplication.beep()
        except Exception:
            # Audio availability must never turn a successful backtest into an error.
            pass
    def _finish_summary_view(self):
        if self._pending_ui_results is None: return
        summary,trades,_,_=self._pending_ui_results
        try:
            self.populate_summary(summary,trades)
        except Exception:
            self.append_log("Results display warning (summary):\n"+traceback.format_exc())
        try:
            self._update_sr_summary_panel(trades)
        except Exception:
            self.append_log("Results display warning (S/R summary):\n"+traceback.format_exc())
        QTimer.singleShot(0,self._finish_results_view)
    def _finish_results_view(self):
        if self._pending_ui_results is None: return
        try:
            self.update_dynamic()
        except Exception:
            self.append_log("Results display warning (chart/window):\n"+traceback.format_exc())
        finally:
            self._pending_ui_results=None
            self.progress.setValue(100); self.status.setText(f"Completed | Results saved to {self.output_dir}")
            if self.thread is None: self.run_btn.setEnabled(True)
    def on_failed(self,msg,tb): self._run_failed=True; QMessageBox.critical(self,"Backtest Error",msg); self.append_log(tb); self.cleanup_thread()
    def cleanup_thread(self):
        self.cancel_btn.setEnabled(False)
        if self.thread is None:
            self.run_btn.setEnabled(True)
            return
        self.thread.quit()

    def _thread_finished(self):
        thread=self.thread
        self.thread=None; self.worker=None
        self._set_backtest_running(False)
        if self._pending_ui_results is None:
            self.run_btn.setEnabled(True)
            if self._run_failed: self.status.setText("Backtest failed; see the Log tab for details.")
        if thread is not None: thread.deleteLater()
    def _update_sr_summary_panel(self,trades):
        mode=self.sr_filter_mode.currentText() if hasattr(self,"sr_filter_mode") else "Analysis Only"
        mode_note="\nNo trades filtered; support/resistance was measured for analysis only." if mode == "Analysis Only" else ""
        if trades is None or trades.empty or ("long_sr_context" not in trades.columns and "short_sr_context" not in trades.columns):
            self.sr_summary_panel_label.setText(f"Mode: {mode}{mode_note}\n\nSupport/Resistance analysis was not enabled for this run.")
            return
        report=build_sr_event_context_summary(trades)
        candidates=report[report["trade_count"]>=3] if not report.empty else report
        if candidates.empty:
            self.sr_summary_panel_label.setText(f"Mode: {mode}{mode_note}\n\nNot enough trades per S/R context yet for a reliable best/weakest comparison (need at least 3 per context).")
            return
        ranked=candidates.dropna(subset=["win_rate"])
        best=ranked.sort_values("win_rate",ascending=False).iloc[0]
        worst=ranked.sort_values("win_rate",ascending=True).iloc[0]
        def describe(row):
            context=str(row["context"]).replace("_"," ").title()
            r_value=row.get("avg_r")
            r_text=f"{r_value:+.2f}R" if r_value == r_value else "n/a"
            return f"{row['direction']} {context} — {format_percentage(row['win_rate'],1)} WR, {r_text}"
        self.sr_summary_panel_label.setText(
            f"Mode: {mode}{mode_note}\n\nBest S/R Context: {describe(best)}\nWeakest S/R Context: {describe(worst)}"
        )

    @staticmethod
    def _money(value):
        return "—" if value is None else f"{float(value):,.2f}"

    def populate_summary(self,s,trades=None):
        percentage=lambda value: "—" if value is None else format_percentage(value,2)
        number=lambda value: "—" if value is None else f"{float(value):.2f}"
        r_value=lambda value: "—" if value is None else f"{float(value):.2f}R"
        values={
            "Ending Equity":self._money(s.get("ending_equity")), "Total Return":percentage(s.get("total_return_percentage")),
            "Total Trades":f"{int(s.get('total_trades',s.get('total_pairs',0)) or 0):,}", "Win Rate":percentage(s.get("win_rate")),
            "Profit Factor":number(s.get("profit_factor")), "Maximum Drawdown":percentage(s.get("maximum_drawdown_percentage")),
            "Average Net R":r_value(s.get("average_net_r")), "Total Net R":r_value(s.get("total_net_r")),
            "Total Fees":self._money(s.get("total_fees")),
            "Signals Traded / Evaluated":f"{int(s.get('signals_traded',0)):,} / {int(s.get('signals_evaluated',0)):,}" if s.get("signals_traded") is not None or s.get("signals_evaluated") is not None else "—",
        }
        for label,text in values.items(): self.kpi_labels[label].setText(text)
        self.starting_equity_label.setText(f"Starting Equity: {self._money(self.equity.value())}")
        profiles=s.get("isolated_profile_comparison",[])
        if profiles:
            self.comparison_box.setTitle("Profile Performance")
            self.combo_table.setColumnCount(5)
            self.combo_table.setHorizontalHeaderLabels(["Profile","Trades","Win Rate","Profit Factor","Net Profit"]); self.combo_table.setRowCount(len(profiles))
            for row,item in enumerate(profiles):
                values=[item.get("profile","").replace("_"," ").title(),item.get("trades",0),format_percentage(item.get("win_rate",0),2),f"{float(item.get('profit_factor',0)):.2f}",self._money(item.get("net_profit"))]
                for column,value in enumerate(values): self.combo_table.setItem(row,column,QTableWidgetItem(str(value)))
        else:
            self.comparison_box.setTitle("Direction / Regime Performance")
            self.combo_table.setColumnCount(9); self.combo_table.setHorizontalHeaderLabels(["Market Regime","Direction","Trades","Wins","Losses","Win Rate","Average Net R","Total Net R","Net PnL"])
            _,breakdown=build_performance_breakdowns(trades if trades is not None else pd.DataFrame())
            lookup={(str(item.market_regime).upper(),str(item.direction).upper()):item for item in breakdown.itertuples()}
            rows=[(regime,direction) for regime in ("BULL","BEAR","SIDEWAYS") for direction in ("LONG","SHORT")]; self.combo_table.setRowCount(len(rows))
            for row,(regime,direction) in enumerate(rows):
                item=lookup.get((regime,direction)); raw=[regime.title(),direction.title(),getattr(item,"trades",0),getattr(item,"wins",0),getattr(item,"losses",0),format_percentage(getattr(item,"win_rate",0),2),f"{getattr(item,'average_r',0):.2f}R",f"{getattr(item,'total_r',0):.2f}R",self._money(getattr(item,"net_pnl",0))]
                for column,text in enumerate(raw): self.combo_table.setItem(row,column,QTableWidgetItem(str(text)))
        self.combo_table.resizeRowsToContents(); self._size_summary_table()
    def save_config(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Configuration","backtest_config.json","JSON (*.json)");
        if p:
            values=self.values(); values.update({"save_feature_analysis_reports":self.save_feature_reports.isChecked(),"save_indicator_analysis_reports":self.save_indicator_reports.isChecked(),"create_standard_charts":self.create_standard_charts.isChecked()}); save_config_json(p,values)
    def load_config(self):
        if self.thread and self.thread.isRunning(): return
        p,_=QFileDialog.getOpenFileName(self,"Load Configuration","","JSON (*.json)");
        if p: self.apply_values(load_config_json(p))
    def apply_values(self,d):
        self._applying_values=True
        values = {**default_gui_config(), **d}
        self.profile_editor.apply_values(values)
        self.market_symbol.setCurrentText(str(values.get("market_symbol") or self._pair_from_path(values.get("input_csv","")) or "XRPUSDT"))
        self.run_name.setText(str(values.get("run_name", "")))
        self.strategy_timeframe.setCurrentText(self._timeframe_label(int(values["strategy_timeframe_minutes"])))
        self.intrabar_timeframe.setCurrentText(self._timeframe_label(int(values["intrabar_timeframe_minutes"])))
        self.input_csv.setText(str(values["input_csv"]))
        self.intrabar_csv.setText(str(values["intrabar_csv"]))
        self.use_intrabar.setChecked(bool(values["use_intrabar_data"]) and int(values["strategy_timeframe_minutes"]) > 1)
        self.output_folder.setText(str(values["output_dir"]))
        self.sl.setValue(float(values["sl_mult"]))
        self.tp.setValue(float(values["tp_mult"]))
        self.entry_mode.setCurrentIndex(max(0,self.entry_mode.findData(values["entry_mode"])))
        self.entry_interval.setValue(int(values["entry_interval"]))
        self.vwap_breakout_hours.setValue(float(values.get("vwap_breakout_lookback_hours",4.0))); self.vwap_volume_lookback.setValue(int(values.get("vwap_volume_lookback",20))); self.vwap_volume_multiplier.setValue(float(values.get("vwap_volume_multiplier",1.5))); self.vwap_slope_lookback.setValue(int(values.get("vwap_slope_lookback",1))); self.vwap_atr_min.setValue(float(values.get("vwap_atr_pct_minimum",0))); self.vwap_atr_max.setValue(float(values.get("vwap_atr_pct_maximum",1))); self.vwap_confirmation_mode.setCurrentText(str(values.get("vwap_confirmation_mode","IMMEDIATE"))); self.vwap_retest_window.setValue(int(values.get("vwap_retest_window_candles",4))); self.vwap_retest_tolerance.setValue(float(values.get("vwap_retest_tolerance_atr",0.25)))
        self.enable_random_entry.setChecked(bool(values.get("enable_random_entry",False))); self.entry_timing_mode.setCurrentText(str(values.get("entry_timing_mode","CURRENT"))); self.random_probability.setValue(float(values.get("random_entry_probability",0.5))); self.random_seed.setText(str(values.get("random_seed",42))); self.random_start_mode.setCurrentText(str(values.get("random_entry_start_mode","NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"))); self.randomize_first.setChecked(bool(values.get("randomize_first_entry",True))); self.max_random_wait.setValue(int(values.get("max_random_wait_candles",0))); self.enable_random_batch.setChecked(bool(values.get("enable_random_entry_batch",False))); self.random_seed_start.setValue(int(values.get("random_seed_start",1))); self.random_seed_count.setValue(int(values.get("random_seed_count",100)))
        self.enable_coin_flip_sizing.setChecked(bool(values.get("enable_coin_flip_sizing",False))); self.coin_flip_seed.setText(str(values.get("coin_flip_seed",42)))
        legacy_di_minimum=float(values.get("di_direction_minimum_spread",30.0)); legacy_di_ratio=float(values.get("di_reward_risk_ratio",1.0)); self.enable_di_direction_sizing.setChecked(bool(values.get("enable_di_direction_sizing",False))); self.flip_filtered_di_direction.setChecked(bool(values.get("flip_filtered_di_direction",False))); self.di_direction_long_min_spread.setValue(float(values.get("di_direction_long_minimum_spread",legacy_di_minimum))); self.di_direction_short_min_spread.setValue(float(values.get("di_direction_short_minimum_spread",legacy_di_minimum))); self.di_execution_mode.setCurrentText(str(values.get("di_execution_mode","BOTH_SIDES"))); self.di_long_reward_risk_ratio.setValue(float(values.get("di_long_reward_risk_ratio",legacy_di_ratio))); self.di_short_reward_risk_ratio.setValue(float(values.get("di_short_reward_risk_ratio",legacy_di_ratio)))
        self.enable_support_resistance_analysis.setChecked(bool(values.get("enable_support_resistance_analysis",False))); self.sr_pivot_left.setValue(int(values.get("sr_pivot_left",5))); self.sr_pivot_right.setValue(int(values.get("sr_pivot_right",5))); self.sr_lookback_bars.setValue(int(values.get("sr_lookback_bars",200))); self.sr_zone_width_atr.setValue(float(values.get("sr_zone_width_atr",0.5))); self.sr_near_distance_atr.setValue(float(values.get("sr_near_distance_atr",0.75))); self.enable_sr_hold_confirmation.setChecked(bool(values.get("enable_sr_hold_confirmation",False))); self.sr_hold_confirmation_bars.setValue(int(values.get("sr_hold_confirmation_bars",3))); self.sr_hold_confirmation_atr.setValue(float(values.get("sr_hold_confirmation_atr",0.25))); self.sr_break_tolerance_atr.setValue(float(values.get("sr_break_tolerance_atr",0.25))); self.sr_break_basis.setCurrentText(str(values.get("sr_break_basis","CLOSE"))); self.sr_filter_mode.setCurrentIndex(max(0,self.sr_filter_mode.findData(str(values.get("sr_filter_mode","ANALYSIS_ONLY")))))
        self.sr_long_avoid_near_resistance.setChecked(bool(values.get("sr_long_avoid_near_resistance",False))); self.sr_long_require_near_support.setChecked(bool(values.get("sr_long_require_near_support",False))); self.sr_long_block_broken_support.setChecked(bool(values.get("sr_long_block_broken_support",False))); self.sr_long_min_room_to_resistance_atr.setValue(float(values.get("sr_long_min_room_to_resistance_atr",0.0))); self.sr_short_avoid_near_support.setChecked(bool(values.get("sr_short_avoid_near_support",False))); self.sr_short_require_near_resistance.setChecked(bool(values.get("sr_short_require_near_resistance",False))); self.sr_short_block_broken_resistance.setChecked(bool(values.get("sr_short_block_broken_resistance",False))); self.sr_short_min_room_to_support_atr.setValue(float(values.get("sr_short_min_room_to_support_atr",0.0)))
        if hasattr(self,"sr_detection_preset"): self._sync_sr_preset_from_values()
        self.enable_di_direction_selection.setChecked(bool(values.get("enable_di_direction_selection",True))); self.enable_di_pressure_analysis.setChecked(bool(values.get("enable_di_pressure_analysis",True))); self.di_pressure_lookback.setValue(int(values.get("di_pressure_lookback",3)))
        self.enable_di_regime_reward_risk.setChecked(bool(values.get("enable_di_regime_reward_risk",False))); self.di_regime_bear_return_threshold.setText(format_percentage(float(values.get("di_regime_bear_return_threshold",-0.20)),2)); self.di_long_bull_reward_risk_ratio.setValue(float(values.get("di_long_bull_reward_risk_ratio",2.0))); self.di_long_bear_reward_risk_ratio.setValue(float(values.get("di_long_bear_reward_risk_ratio",1.0))); self.di_long_sideways_reward_risk_ratio.setValue(float(values.get("di_long_sideways_reward_risk_ratio",2.0))); self.di_short_bull_reward_risk_ratio.setValue(float(values.get("di_short_bull_reward_risk_ratio",1.0))); self.di_short_bear_reward_risk_ratio.setValue(float(values.get("di_short_bear_reward_risk_ratio",1.0))); self.di_short_sideways_reward_risk_ratio.setValue(float(values.get("di_short_sideways_reward_risk_ratio",2.0)))
        self.enable_bull_long_conditional_reward_risk.setChecked(bool(values.get("enable_bull_long_conditional_reward_risk",False))); self.bull_long_conditional_bb_width_minimum.setText(format_percentage(float(values.get("bull_long_conditional_bb_width_minimum",0.05)),2)); self.bull_long_conditional_adx_maximum.setValue(float(values.get("bull_long_conditional_adx_maximum",40.0))); self.bull_long_conditional_reward_risk_ratio.setValue(float(values.get("bull_long_conditional_reward_risk_ratio",1.0)))
        self.enable_bull_long_momentum_confirmation.setChecked(bool(values.get("enable_bull_long_momentum_confirmation",False))); self.bull_long_confirmation_lookback_days.setValue(int(values.get("bull_long_confirmation_lookback_days",60))); self.bull_long_confirmation_return_threshold.setText(format_percentage(float(values.get("bull_long_confirmation_return_threshold",0.20)),2)); self.bull_long_unconfirmed_reward_risk_ratio.setValue(float(values.get("bull_long_unconfirmed_reward_risk_ratio",1.0)))
        self.enable_bull_long_momentum_target_extension.setChecked(bool(values.get("enable_bull_long_momentum_target_extension",False))); self.bull_long_momentum_extension_lookback_days.setValue(int(values.get("bull_long_momentum_extension_lookback_days",30))); self.bull_long_momentum_extension_return_threshold.setText(format_percentage(float(values.get("bull_long_momentum_extension_return_threshold",0.10)),2)); self.enable_bull_long_momentum_extension_return_maximum.setChecked(bool(values.get("enable_bull_long_momentum_extension_return_maximum",False))); self.bull_long_momentum_extension_return_maximum.setText(format_percentage(float(values.get("bull_long_momentum_extension_return_maximum",0.40)),2)); self.bull_long_momentum_extended_reward_risk_ratio.setValue(float(values.get("bull_long_momentum_extended_reward_risk_ratio",4.0)))
        self.enable_bull_long_structural_confirmation.setChecked(bool(values.get("enable_bull_long_structural_confirmation",False))); self.bull_long_structural_sma_days.setValue(int(values.get("bull_long_structural_sma_days",200))); self.bull_long_structural_slope_lookback_days.setValue(int(values.get("bull_long_structural_slope_lookback_days",30))); self.bull_long_structural_unconfirmed_reward_risk_ratio.setValue(float(values.get("bull_long_structural_unconfirmed_reward_risk_ratio",1.0)))
        self.enable_bull_long_r_step_trailing.setChecked(bool(values.get("enable_bull_long_r_step_trailing",False))); self.bull_long_r_step_activation_r.setValue(float(values.get("bull_long_r_step_activation_r",2.0))); self.bull_long_r_step_distance_r.setValue(float(values.get("bull_long_r_step_distance_r",2.0))); self.bull_long_r_step_size_r.setValue(float(values.get("bull_long_r_step_size_r",1.0))); self.bull_long_r_step_maximum_r.setValue(float(values.get("bull_long_r_step_maximum_r",0.0))); self.bull_long_r_step_activation_close_pct.setValue(float(values.get("bull_long_r_step_activation_close_pct",0.0)))
        self.enable_sideways_long_conditional_reward_risk.setChecked(bool(values.get("enable_sideways_long_conditional_reward_risk",False))); self.sideways_long_conditional_adx_maximum.setValue(float(values.get("sideways_long_conditional_adx_maximum",35.0))); self.sideways_long_conditional_reward_risk_ratio.setValue(float(values.get("sideways_long_conditional_reward_risk_ratio",1.0)))
        self.enable_sideways_short_conditional_reward_risk.setChecked(bool(values.get("enable_sideways_short_conditional_reward_risk",False))); self.sideways_short_conditional_di_spread_minimum.setValue(float(values.get("sideways_short_conditional_di_spread_minimum",35.0))); self.sideways_short_conditional_di_spread_maximum.setValue(float(values.get("sideways_short_conditional_di_spread_maximum",40.0))); self.sideways_short_conditional_reward_risk_ratio.setValue(float(values.get("sideways_short_conditional_reward_risk_ratio",1.0)))
        self.enable_bear_short_conditional_reward_risk.setChecked(bool(values.get("enable_bear_short_conditional_reward_risk",False))); self.bear_short_conditional_di_spread_maximum.setValue(float(values.get("bear_short_conditional_di_spread_maximum",35.0))); self.bear_short_conditional_reward_risk_ratio.setValue(float(values.get("bear_short_conditional_reward_risk_ratio",1.0)))
        self.enable_directional_adx_filter.setChecked(bool(values.get("enable_directional_adx_filter",False))); self.directional_long_adx_maximum.setValue(float(values.get("directional_long_adx_maximum",60.0))); self.directional_short_adx_minimum.setValue(float(values.get("directional_short_adx_minimum",25.0)))
        self.enable_biased_short_adx_cap.setChecked(bool(values.get("enable_biased_short_adx_cap",False))); self.biased_short_adx_maximum.setValue(float(values.get("biased_short_adx_maximum",50.0)))
        self.enable_short_vwap_distance_filter.setChecked(bool(values.get("enable_short_vwap_distance_filter",False))); self.short_vwap_minimum_distance_atr.setValue(float(values.get("short_vwap_minimum_distance_atr",2.0)))
        self.enable_long_momentum_filter.setChecked(bool(values.get("enable_long_momentum_filter",False))); self.long_momentum_lookback_hours.setValue(int(values.get("long_momentum_lookback_hours",24))); self.long_momentum_minimum_return.setText(format_percentage(float(values.get("long_momentum_minimum_return",0.06)),2))
        for name in ("allow_bull_long","allow_bull_short","allow_bear_long","allow_bear_short","allow_sideways_long","allow_sideways_short"): getattr(self,name).setChecked(bool(values.get(name,True)))
        for name in ("enable_regime_direction_filter","enable_directional_di_spread_range","enable_directional_adx_range","enable_directional_atr_pct_range","enable_directional_rsi_range","enable_directional_close_location_range","enable_directional_momentum_range"): getattr(self,name).setChecked(bool(values.get(name,False)))
        for name,default in (("directional_long_di_spread_minimum",0),("directional_long_di_spread_maximum",1000),("directional_short_di_spread_minimum",0),("directional_short_di_spread_maximum",1000),("directional_long_rsi_minimum",0),("directional_long_rsi_maximum",100),("directional_short_rsi_minimum",0),("directional_short_rsi_maximum",100)): getattr(self,name).setValue(float(values.get(name,default)))
        for name,default in (("directional_long_adx_minimum",0),("directional_long_adx_range_maximum",1000),("directional_short_adx_range_minimum",0),("directional_short_adx_maximum",1000)): getattr(self,name).setValue(float(values.get(name,default)))
        self.directional_rsi_period.setValue(int(values.get("directional_rsi_period",14))); self.directional_momentum_lookback_hours.setValue(int(values.get("directional_momentum_lookback_hours",24)))
        for name,default in (("directional_long_atr_pct_minimum",0),("directional_long_atr_pct_maximum",1),("directional_short_atr_pct_minimum",0),("directional_short_atr_pct_maximum",1),("directional_long_close_location_minimum",0),("directional_long_close_location_maximum",1),("directional_short_close_location_minimum",0),("directional_short_close_location_maximum",1),("directional_long_momentum_minimum",-10),("directional_long_momentum_maximum",10),("directional_short_momentum_minimum",-10),("directional_short_momentum_maximum",10)): getattr(self,name).setText(format_percentage(float(values.get(name,default)),2))
        self.enable_bull_regime_short_filter.setChecked(bool(values.get("enable_bull_regime_short_filter",False))); self.bull_regime_lookback_days.setValue(int(values.get("bull_regime_lookback_days",90))); self.bull_regime_return_threshold.setText(format_percentage(float(values.get("bull_regime_return_threshold",0.20)),2))
        self.enable_bear_regime_adx_filter.setChecked(bool(values.get("enable_bear_regime_adx_filter",False))); self.bear_regime_adx_minimum.setValue(float(values.get("bear_regime_adx_minimum",25.0)))
        self.enable_daily_schedule.setChecked(bool(values.get("enable_daily_entry_schedule", False)))
        self.daily_entry_time.setText(str(values.get("daily_entry_time", "00:00")))
        self.daily_entry_timezone.setText(str(values.get("daily_entry_timezone", "UTC")))
        self.daily_entry_missed_policy.setCurrentText(str(values.get("daily_entry_missed_policy", "SKIP_DAY")))
        self.max_pairs.setValue(int(values["max_active_pairs"]))
        self.tie.setCurrentIndex(max(0,self.tie.findData(values["tie_policy"])))
        self.risk_mode.setCurrentText(values["risk_mode"])
        self.atr_period.setValue(int(values["atr_period"]))
        self.atr_mult.setValue(float(values["atr_multiplier"]))
        self.trading_start.setText(str(values["trading_start_date"] or ""))
        self.trading_end.setText(str(values["trading_end_date"] or ""))
        self.entire_dataset.setChecked(not values["trading_start_date"] and not values["trading_end_date"])
        self.max_lev_leg.setText(str(values["max_effective_leverage_per_leg"] or ""))
        self.max_lev_combined.setText(str(values["max_combined_effective_leverage"] or ""))
        self.missing_policy.setCurrentText(values["intrabar_missing_policy"])
        self.enable_partial_tp.setChecked(bool(values.get("enable_partial_take_profit",False))); self.tp1_r.setValue(float(values.get("tp1_r",3))); self.tp1_close_pct.setValue(float(values.get("tp1_close_pct",50))); self.tp2_r.setValue(float(values.get("tp2_r",12))); self.tp2_close_pct.setValue(float(values.get("tp2_close_pct",50))); self.stop_loss_r.setValue(float(values.get("stop_loss_r",10))); self.after_tp1_stop_mode.setCurrentText(str(values.get("after_tp1_stop_mode","KEEP_ORIGINAL_SL"))); self.after_tp1_stop_offset_r.setValue(float(values.get("after_tp1_stop_offset_r",0))); self.tp2_exit_mode.setCurrentText(str(values.get("tp2_exit_mode","FIXED_TP2")));
        self.enable_partial_sl.setChecked(bool(values.get("enable_partial_stop_loss",False))); self.sl1_r.setValue(float(values.get("sl1_r",0.5))); self.sl1_close_pct.setValue(float(values.get("sl1_close_pct",50))); self.sl2_r.setValue(float(values.get("sl2_r",8)))
        self.zero_cost.setChecked(bool(values["zero_cost_comparison"])); self.trade_direction.setCurrentText(str(values.get("trade_direction", "BOTH"))); self.enable_trailing_profit.setChecked(bool(values.get("enable_trailing_profit",False) or values.get("tp2_exit_mode")=="TRAILING_AFTER_TP1")); self.trail_activation_trigger.setCurrentText(str(values.get("trail_activation_trigger","AFTER_TP1" if values.get("tp2_exit_mode")=="TRAILING_AFTER_TP1" else "PRICE_REACHES_R"))); self.trail_activation_r.setValue(float(values.get("trail_activation_r",3))); self.trail_distance_r.setValue(float(values.get("trail_distance_r",1))); self.trail_apply_to.setCurrentText(str(values.get("trail_apply_to","BOTH"))); self.trail_intrabar_mode.setCurrentText(str(values.get("trail_intrabar_mode","PESSIMISTIC")))
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
        self.enable_bb_width.setChecked(bool(values.get("enable_bb_width_filter", False))); self.bb_width_mode.setCurrentText(values.get("bb_width_filter_mode", "Disabled")); self.bb_width_max.setValue(float(values.get("bb_width_maximum", 0.03))); self.bb_width_min.setValue(float(values.get("bb_width_minimum", 0.012)))
        self.skip_monday_entries.setChecked(bool(values.get("enable_skip_monday_entries", False))); self.skip_monday_timezone.setText(str(values.get("skip_monday_timezone", "UTC")))
        self.enable_di_spread.setChecked(bool(values.get("enable_di_spread_filter", False))); self.di_spread_mode.setCurrentText(values.get("di_spread_filter_mode", "Disabled")); self.di_spread_max.setValue(float(values.get("di_spread_maximum", 10.0))); self.di_spread_min.setValue(float(values.get("di_spread_minimum", 0.0)))
        self.enable_atr_checkpoint_tp_extension.setChecked(bool(values.get("enable_atr_checkpoint_tp_extension",False))); self.atr_checkpoint_di_spread_min.setValue(float(values.get("atr_checkpoint_di_spread_minimum",30.0))); self.atr_checkpoint_bb_width_min.setValue(float(values.get("atr_checkpoint_bb_width_minimum",0.03))); self.atr_checkpoint_profit_lock_start.setValue(float(values.get("atr_checkpoint_profit_lock_start",3.0))); self.atr_checkpoint_profit_lock_distance.setValue(float(values.get("atr_checkpoint_profit_lock_distance",1.0)))
        self.both_timeout.setChecked(bool(values.get("enable_both_open_timeout", False)))
        mins=int(values.get("max_both_open_minutes", 480)); unit=values.get("both_open_timeout_unit") or ("Hours" if mins % 60 == 0 else "Minutes")
        self.both_timeout_unit.setCurrentText(unit); self.both_timeout_duration.setValue(max(1, mins//60 if unit=="Hours" else mins))
        self.both_timeout_duration.setEnabled(self.both_timeout.isChecked()); self.both_timeout_unit.setEnabled(self.both_timeout.isChecked())
        self.remaining_leg_timeout.setChecked(bool(values.get("enable_remaining_leg_timeout_after_first_sl", False)))
        remaining_mins=int(values.get("remaining_leg_timeout_after_first_sl_minutes", 240)); remaining_unit=values.get("remaining_leg_timeout_after_first_sl_unit") or ("Hours" if remaining_mins % 60 == 0 else "Minutes")
        self.remaining_leg_timeout_unit.setCurrentText(remaining_unit); self.remaining_leg_timeout_duration.setValue(max(1, remaining_mins//60 if remaining_unit=="Hours" else remaining_mins))
        self.remaining_leg_timeout_duration.setEnabled(self.remaining_leg_timeout.isChecked()); self.remaining_leg_timeout_unit.setEnabled(self.remaining_leg_timeout.isChecked())
        self.remaining_leg_timeout_profit_extension.setChecked(bool(values.get("enable_remaining_leg_timeout_profit_extension", False)))
        self.remaining_leg_timeout_profit_threshold_r.setValue(float(values.get("remaining_leg_timeout_profit_threshold_r", 10.0)))
        self.reentry_gate_after_timeout.setChecked(bool(values.get("enable_reentry_gate_after_remaining_leg_timeout", False)))
        self.checkpoint_score_use_profit.setChecked(bool(values.get("checkpoint_score_use_profit", True))); self.checkpoint_score_min_profit_r.setValue(float(values.get("checkpoint_score_min_profit_r", 0.85)))
        self.checkpoint_score_use_atr.setChecked(bool(values.get("checkpoint_score_use_atr_pct", True))); self.checkpoint_score_max_atr_pct.setValue(float(values.get("checkpoint_score_max_atr_pct", 0.08)))
        self.checkpoint_score_use_di.setChecked(bool(values.get("checkpoint_score_use_directional_di", True))); self.checkpoint_score_min_di.setValue(float(values.get("checkpoint_score_min_directional_di", 2.3)))
        self.checkpoint_score_use_bb.setChecked(bool(values.get("checkpoint_score_use_bb_width_pct", True))); self.checkpoint_score_max_bb_pct.setValue(float(values.get("checkpoint_score_max_bb_width_pct", 0.349)))
        self.checkpoint_score_required.setValue(int(values.get("checkpoint_score_min_conditions", 3))); self.checkpoint_score_extension.setChecked(bool(values.get("enable_remaining_leg_checkpoint_score_extension", False)))
        self.first_sl_survivor_partial.setChecked(bool(values.get("enable_first_sl_survivor_partial_close", False))); self.first_sl_survivor_partial_pct.setValue(float(values.get("first_sl_survivor_partial_close_pct", 25.0))); self.first_sl_survivor_partial_pct.setEnabled(self.first_sl_survivor_partial.isChecked())
        self.zero_score_confirmations.setValue(int(values.get("checkpoint_zero_score_confirmations_required", 2)))
        zero_minutes=int(values.get("checkpoint_zero_score_recheck_minutes", 120)); zero_unit=values.get("checkpoint_zero_score_recheck_unit") or ("Hours" if zero_minutes % 60 == 0 else "Minutes")
        self.zero_score_recheck_unit.setCurrentText(zero_unit); self.zero_score_recheck_duration.setValue(max(1,zero_minutes//60 if zero_unit=="Hours" else zero_minutes)); self.zero_score_confirmation.setChecked(bool(values.get("enable_checkpoint_zero_score_confirmation", False)))
        self.remaining_leg_timeout_profit_extension.setEnabled(self.remaining_leg_timeout.isChecked()); self.remaining_leg_timeout_profit_threshold_r.setEnabled(self.remaining_leg_timeout.isChecked() and self.remaining_leg_timeout_profit_extension.isChecked()); self.reentry_gate_after_timeout.setEnabled(self.remaining_leg_timeout.isChecked())
        self._update_checkpoint_score_controls()
        level=str(values.get("analysis_level","STANDARD")).upper(); self.analysis_level.setCurrentText({"FAST":"Fast","RESEARCH":"Research"}.get(level,"Standard (Recommended)"))
        self.enable_trade_telemetry.setChecked(bool(values.get("enable_trade_telemetry", False))); self.telemetry_interval.setValue(int(values.get("telemetry_interval_minutes", 15))); self.save_full_telemetry.setChecked(bool(values.get("save_full_telemetry_csv", False))); self.save_journey_summary.setChecked(bool(values.get("save_trade_journey_summary", False))); self.save_journey_charts.setChecked(bool(values.get("save_trade_journey_charts", False)))
        self.enable_lifecycle.setChecked(bool(values.get("enable_indicator_lifecycle_analysis",False))); self.lifecycle_phases.setValue(int(values.get("lifecycle_phases",4))); self.lifecycle_checkpoints.setText(",".join(str(v) for v in values.get("lifecycle_early_checkpoints",[15,30,60]))); self.lifecycle_min_sample.setValue(int(values.get("lifecycle_minimum_bucket_sample",20))); self.lifecycle_charts.setChecked(bool(values.get("create_lifecycle_charts",False))); self.lifecycle_flat_threshold.setValue(float(values.get("lifecycle_flat_pattern_threshold_pct",5.0)))
        self.save_feature_reports.setChecked(bool(values.get("save_feature_analysis_reports",False))); self.save_indicator_reports.setChecked(bool(values.get("save_indicator_analysis_reports",False))); self.create_standard_charts.setChecked(bool(values.get("create_standard_charts",False)))
        self.be_after_sl.setChecked(bool(values.get("enable_be_after_opposite_sl", False)))
        self.be_mode.setCurrentText(values.get("be_mode", "ENTRY_PRICE")); self.be_offset.setValue(float(values.get("be_offset_r", 0.0))); self.be_same_candle.setCurrentText(values.get("be_same_candle_policy", "NEXT_CANDLE")); self.be_offset.setEnabled(self.be_mode.currentText()=="R_OFFSET")
        self._applying_values=False; self.update_dynamic()
        self.update_planned_output()
    def append_log(self,t): self.log.append(str(t))
    def save_log(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Log","backtest.log","Log (*.log *.txt)");
        if p: Path(p).write_text(self.log.toPlainText())
