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
from .portfolio_worker import PortfolioWorker
from output_manager import planned_run_dir

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Long-Short Crypto Backtester"); self.resize(1200, 800)
        self.settings = QSettings("LongShortCrypto", "Backtester"); self.worker=None; self.thread=None; self.portfolio_worker=None; self.portfolio_thread=None; self.started=0; self.last_summary={}; self.output_dir=Path("output")
        self.tabs=QTabWidget(); self.setCentralWidget(self.tabs)
        self._build_config(); self._build_summary(); self._build_portfolio_tab(); self._build_trades(); self._build_charts(); self._build_log(); self.reset_defaults(); self._restore_settings()
    def _line(self, text=""):
        w=QLineEdit(text); return w
    def _spin(self, v, mn=-1e12, mx=1e12, dec=6):
        s=QDoubleSpinBox(); s.setRange(mn,mx); s.setDecimals(dec); s.setValue(v); return s
    def _build_config(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); form=QVBoxLayout(inner); self.config_controls=[]
        def group(title): g=QGroupBox(title); l=QFormLayout(g); form.addWidget(g); return l
        data=group("Data")
        self.strategy_timeframe=QComboBox(); self.strategy_timeframe.addItems(["1m","5m","15m","30m","1h","4h"]); data.addRow("Strategy Timeframe",self.strategy_timeframe)
        self.input_csv=self._line(); self.input_csv.setReadOnly(True); b=QPushButton("Browse"); b.clicked.connect(self.browse_csv); row=QHBoxLayout(); row.addWidget(self.input_csv); row.addWidget(b); data.addRow("Strategy CSV", row)
        self.intrabar_timeframe=QComboBox(); self.intrabar_timeframe.addItems(["1m","5m","15m","30m","1h","4h"]); data.addRow("Intrabar Timeframe",self.intrabar_timeframe)
        self.intrabar_csv=self._line(); self.intrabar_csv.setReadOnly(True); bi=QPushButton("Browse"); bi.clicked.connect(self.browse_intrabar_csv); row=QHBoxLayout(); row.addWidget(self.intrabar_csv); row.addWidget(bi); data.addRow("Intrabar CSV", row)
        self.use_intrabar=QCheckBox("Use intrabar data for exit resolution"); self.use_intrabar.setChecked(True); data.addRow("", self.use_intrabar)
        self.data_help=QLabel(); self.data_help.setWordWrap(True); data.addRow(self.data_help)
        self.strategy_timeframe.currentTextChanged.connect(self._timeframe_changed); self.intrabar_timeframe.currentTextChanged.connect(self.update_dynamic); self.use_intrabar.toggled.connect(self.update_dynamic)
        self.run_name=self._line(); self.run_name.setPlaceholderText("Optional run name prefix"); data.addRow("Run Name", self.run_name)
        self.output_folder=self._line(); self.output_folder.setReadOnly(True); bo=QPushButton("Browse"); bo.clicked.connect(self.browse_output); row=QHBoxLayout(); row.addWidget(self.output_folder); row.addWidget(bo); data.addRow("Output Folder", row)
        self.planned_output=QLabel("Output run folder: not calculated yet"); self.planned_output.setWordWrap(True); data.addRow("Next Run Folder", self.planned_output)
        self.dataset_info=QLabel("No CSV loaded."); data.addRow("Dataset Information", self.dataset_info); val=QPushButton("Validate Data"); val.clicked.connect(self.validate_data); data.addRow(val)
        strat=group("Core Strategy")
        self.sl=self._spin(2,0); self.sl.setToolTip("Used only when Partial Stop Loss and Partial Take Profit are disabled."); self.tp=self._spin(3,0); self.entry_mode=QComboBox(); self.entry_mode.addItems(["WAIT_UNTIL_CLOSED","EVERY_N_CANDLES","CUSTOM"]); self.entry_interval=QSpinBox(); self.entry_interval.setRange(1,999999); self.max_pairs=QSpinBox(); self.max_pairs.setRange(1,999999); self.tie=QComboBox(); self.tie.addItems(["PESSIMISTIC","OPTIMISTIC"])
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
        self.entry_mode.currentTextChanged.connect(lambda t:self.entry_interval.setEnabled(t=="EVERY_N_CANDLES"))
        random_group=group("Random Entry Timing")
        self.enable_random_entry=QCheckBox("Enable Random Entry Timing"); self.entry_timing_mode=QComboBox(); self.entry_timing_mode.addItems(["CURRENT","RANDOM_AFTER_PAIR_CLOSE"]); self.random_probability=self._spin(0.50,0.000001,1.0,6); self.random_seed=QLineEdit("42"); self.random_start_mode=QComboBox(); self.random_start_mode.addItems(["NEXT_CANDLE_AFTER_PAIR_CLOSE","NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"]); self.randomize_first=QCheckBox("Randomize First Entry"); self.randomize_first.setChecked(True); self.max_random_wait=QSpinBox(); self.max_random_wait.setRange(0,999999); self.enable_random_batch=QCheckBox("Enable Random Entry Batch"); self.random_seed_start=QSpinBox(); self.random_seed_start.setRange(-2147483648,2147483647); self.random_seed_count=QSpinBox(); self.random_seed_count.setRange(1,999999)
        for lab,w in [("",self.enable_random_entry),("Entry Timing Mode",self.entry_timing_mode),("Entry Probability",self.random_probability),("Random Seed",self.random_seed),("Random Entry Start Mode",self.random_start_mode),("",self.randomize_first),("Maximum Random Wait Candles",self.max_random_wait),("",self.enable_random_batch),("Random Seed Start",self.random_seed_start),("Random Seed Count",self.random_seed_count)]: random_group.addRow(lab,w)
        self.enable_coin_flip_sizing=QCheckBox("Enable 3:1 Coin-Flip Sizing (1:1 SL/TP)"); self.coin_flip_seed=QLineEdit("42")
        random_group.addRow("",self.enable_coin_flip_sizing); random_group.addRow("Coin Flip Seed",self.coin_flip_seed)
        self.enable_di_direction_sizing=QCheckBox("Enable DI-Direction Selection"); self.di_direction_long_min_spread=self._spin(30,0,1000,3); self.di_direction_short_min_spread=self._spin(30,0,1000,3); self.di_long_reward_risk_ratio=self._spin(1,0.01,100,3); self.di_short_reward_risk_ratio=self._spin(1,0.01,100,3)
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
        self.enable_bull_regime_short_filter=QCheckBox("Bull Regime: Skip −DI Short Signal"); self.bull_regime_lookback_days=QSpinBox(); self.bull_regime_lookback_days.setRange(1,3650); self.bull_regime_lookback_days.setValue(90); self.bull_regime_return_threshold=self._line("20%")
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
        risk=group("Risk and Position Sizing")
        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line(); self.max_lev_combined=self._line(); self.missing_policy=QComboBox(); self.missing_policy.addItems(["ERROR","WARN_AND_USE_15M","WARN_AND_CONTINUE"]); self.trade_direction=QComboBox(); self.trade_direction.addItems(["BOTH","LONG_ONLY","SHORT_ONLY","BOTH_INDEPENDENT"]); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("0.5%")
        self.risk_formula=QLabel(); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        for lab,w in [("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Trading Start Date",self.trading_start),("Trading End Date",self.trading_end),("Maximum Leverage Per Leg",self.max_lev_leg),("Maximum Combined Leverage",self.max_lev_combined),("Missing Intrabar Policy",self.missing_policy),("Trade Direction",self.trade_direction),("",self.zero_cost),("R Percentage",self.percent_r),("Fixed R Distance",self.fixed_r),("Starting Equity",self.equity),("Risk Per Leg / Selected Trade",self.risk_leg),("Formula",self.risk_formula),("Sizing",QLabel("Two-sided mode: risk is applied per leg.\nPreferred-side-only mode: risk is applied directly to the selected trade.")),("Planned Risk",self.risk_warn)]: risk.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic)
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
        fees=group("Fees and Execution")
        self.maker=self._line("0.02%"); self.taker=self._line("0.05%"); self.maker_entry=QCheckBox("Use Maker Fee for Entry"); self.maker_exit=QCheckBox("Use Maker Fee for Exit"); self.slippage=self._line("0.01%"); self.cost=QLabel()
        for lab,w in [("Maker Fee",self.maker),("Taker Fee",self.taker),("",self.maker_entry),("",self.maker_exit),("Slippage",self.slippage),("Round-trip Cost",self.cost)]: fees.addRow(lab,w)
        for w in [self.maker,self.taker,self.slippage]: w.textChanged.connect(self.update_dynamic)
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
        controls=group("Backtest Controls")
        self.run_btn=QPushButton("Run Backtest"); self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setEnabled(False); self.open_btn=QPushButton("Open Output Folder"); self.save_btn=QPushButton("Save Configuration"); self.load_btn=QPushButton("Load Configuration"); self.reset_btn=QPushButton("Reset Defaults")
        for w in [self.run_btn,self.cancel_btn,self.open_btn,self.save_btn,self.load_btn,self.reset_btn]: controls.addRow(w)
        self.progress=QProgressBar(); self.status=QLabel("Ready"); self.elapsed=QLabel("Elapsed: 0s"); controls.addRow(self.progress); controls.addRow(self.status); controls.addRow(self.elapsed)
        for w in [self.run_name,self.output_folder]: w.textChanged.connect(self.update_planned_output)
        self.run_btn.clicked.connect(self.run_backtest); self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel()); self.open_btn.clicked.connect(lambda: os.startfile(str(self.output_dir)) if sys.platform.startswith("win") else os.system(f'xdg-open "{self.output_dir}"'))
        self.save_btn.clicked.connect(self.save_config); self.load_btn.clicked.connect(self.load_config); self.reset_btn.clicked.connect(self.reset_defaults)
        scroll.setWidget(inner); outer.addWidget(scroll); self.tabs.addTab(page,"Configuration"); self.config_controls=inner.findChildren(QWidget); self._build_di_strategy_tab(); self.update_dynamic()
    def _build_di_strategy_tab(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); form=QVBoxLayout(inner)
        intro=QLabel("DI-direction strategy settings live here. Shared data, risk, fees, execution, telemetry, and output settings remain on the Configuration tab.")
        intro.setWordWrap(True); form.addWidget(intro)
        selection_box=QGroupBox("DI Direction Selection"); selection=QFormLayout(selection_box)
        for lab,w in [
            ("",self.enable_di_direction_sizing),
            ("Execution Mode",self.di_execution_mode),
            ("Long Minimum DI Spread",self.di_direction_long_min_spread),
            ("Short Minimum DI Spread",self.di_direction_short_min_spread),
            ("Long Reward/Risk Ratio",self.di_long_reward_risk_ratio),
            ("Short Reward/Risk Ratio",self.di_short_reward_risk_ratio),
        ]: selection.addRow(lab,w)
        form.addWidget(selection_box)
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
        regime_box=QGroupBox("Short-Side Regime Filters"); regime=QFormLayout(regime_box)
        for lab,w in [
            ("",self.enable_bull_regime_short_filter),
            ("Bull Lookback Days",self.bull_regime_lookback_days),
            ("Bull Return Threshold",self.bull_regime_return_threshold),
            ("",self.enable_biased_short_adx_cap),
            ("Biased Short ADX Maximum",self.biased_short_adx_maximum),
            ("",self.biased_short_adx_help),
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
        scroll.setWidget(inner); outer.addWidget(scroll); self.tabs.addTab(page,"DI Direction Strategy")
        self.config_controls += inner.findChildren(QWidget)
    def _build_portfolio_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); box=QGroupBox("Shared-Equity BTC + ETH Portfolio"); form=QFormLayout(box)
        self.portfolio_btc_config=QLineEdit(); self.portfolio_btc_config.setReadOnly(True); btc_btn=QPushButton("Browse"); btc_btn.clicked.connect(lambda:self._browse_portfolio_config(self.portfolio_btc_config)); btc_row=QHBoxLayout(); btc_row.addWidget(self.portfolio_btc_config); btc_row.addWidget(btc_btn)
        self.portfolio_eth_config=QLineEdit(); self.portfolio_eth_config.setReadOnly(True); eth_btn=QPushButton("Browse"); eth_btn.clicked.connect(lambda:self._browse_portfolio_config(self.portfolio_eth_config)); eth_row=QHBoxLayout(); eth_row.addWidget(self.portfolio_eth_config); eth_row.addWidget(eth_btn)
        self.portfolio_initial_equity=self._spin(1000,1,1e12,2); self.portfolio_risk_per_asset=QLineEdit("1%")
        self.portfolio_output_folder=QLineEdit("output"); self.portfolio_output_folder.setReadOnly(True); output_btn=QPushButton("Browse"); output_btn.clicked.connect(self._browse_portfolio_output); output_row=QHBoxLayout(); output_row.addWidget(self.portfolio_output_folder); output_row.addWidget(output_btn)
        help_text=QLabel("Each asset uses its own saved configuration and one shared account. At 1% per asset, simultaneous BTC and ETH positions create approximately 2% configured open risk. Hourly telemetry is used for mark-to-market drawdown."); help_text.setWordWrap(True)
        for label,control in [("BTC Configuration",btc_row),("ETH Configuration",eth_row),("Starting Equity",self.portfolio_initial_equity),("Risk Per Asset",self.portfolio_risk_per_asset),("Output Folder",output_row),("",help_text)]: form.addRow(label,control)
        layout.addWidget(box); buttons=QHBoxLayout(); self.portfolio_run_btn=QPushButton("Run BTC + ETH Portfolio"); self.portfolio_run_btn.clicked.connect(self.run_portfolio_backtest); self.portfolio_open_btn=QPushButton("Open Portfolio Output"); self.portfolio_open_btn.clicked.connect(self._open_portfolio_output); buttons.addWidget(self.portfolio_run_btn); buttons.addWidget(self.portfolio_open_btn); layout.addLayout(buttons)
        self.portfolio_progress=QProgressBar(); self.portfolio_status=QLabel("Select both saved configurations."); layout.addWidget(self.portfolio_progress); layout.addWidget(self.portfolio_status)
        self.portfolio_summary_table=QTableWidget(0,2); self.portfolio_summary_table.setHorizontalHeaderLabels(["Portfolio Metric","Value"]); self.portfolio_summary_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.portfolio_summary_table); self.tabs.addTab(page,"Portfolio")
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
            btc=self.portfolio_btc_config.text().strip(); eth=self.portfolio_eth_config.text().strip()
            if not Path(btc).is_file() or not Path(eth).is_file(): raise ValueError("Select valid BTC and ETH configuration files.")
            risk=parse_percentage(self.portfolio_risk_per_asset.text())
            if not 0 < risk < 1: raise ValueError("Risk per asset must be above 0% and below 100%.")
            output=self.portfolio_output_folder.text().strip() or "output"; Path(output).mkdir(parents=True,exist_ok=True)
        except Exception as exc: QMessageBox.warning(self,"Portfolio Validation",str(exc)); return
        self.portfolio_thread=QThread(); self.portfolio_worker=PortfolioWorker([("BTC",btc),("ETH",eth)],output,self.portfolio_initial_equity.value(),risk); self.portfolio_worker.moveToThread(self.portfolio_thread); self.portfolio_thread.started.connect(self.portfolio_worker.run); self.portfolio_worker.status.connect(self._on_portfolio_status); self.portfolio_worker.log.connect(self.append_log); self.portfolio_worker.finished.connect(self._on_portfolio_finished); self.portfolio_worker.failed.connect(self._on_portfolio_failed); self.portfolio_run_btn.setEnabled(False); self.portfolio_progress.setValue(0); self.portfolio_thread.start()
    def _on_portfolio_status(self,text,percent): self.portfolio_status.setText(text); self.portfolio_progress.setValue(percent)
    def _on_portfolio_finished(self,summary,trades,equity,out):
        self.portfolio_output_dir=Path(out); self.portfolio_summary_table.setRowCount(len(summary))
        for row,(key,value) in enumerate(summary.items()): self.portfolio_summary_table.setItem(row,0,QTableWidgetItem(str(key))); self.portfolio_summary_table.setItem(row,1,QTableWidgetItem(str(value)))
        self.portfolio_status.setText(f"Completed: {out}"); self._cleanup_portfolio_thread()
    def _on_portfolio_failed(self,message,tb): QMessageBox.critical(self,"Portfolio Backtest Error",message); self.append_log(tb); self._cleanup_portfolio_thread()
    def _cleanup_portfolio_thread(self):
        self.portfolio_run_btn.setEnabled(True)
        if self.portfolio_thread is not None: self.portfolio_thread.quit(); self.portfolio_thread.wait()
        self.portfolio_thread=None; self.portfolio_worker=None
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

    def _base_values(self):
        return {"strategy_timeframe_minutes":self._timeframe_minutes(self.strategy_timeframe.currentText()),"intrabar_timeframe_minutes":self._timeframe_minutes(self.intrabar_timeframe.currentText()),"enable_indicator_lifecycle_analysis":self.enable_lifecycle.isChecked(),"lifecycle_phases":self.lifecycle_phases.value(),"lifecycle_early_checkpoints":[int(v.strip()) for v in self.lifecycle_checkpoints.text().split(",") if v.strip()],"lifecycle_minimum_bucket_sample":self.lifecycle_min_sample.value(),"create_lifecycle_charts":self.lifecycle_charts.isChecked(),"lifecycle_flat_pattern_threshold_pct":self.lifecycle_flat_threshold.value(),"enable_random_entry":self.enable_random_entry.isChecked(),"entry_timing_mode":self.entry_timing_mode.currentText(),"random_entry_probability":self.random_probability.value(),"random_seed":self.random_seed.text().strip(),"random_entry_start_mode":self.random_start_mode.currentText(),"randomize_first_entry":self.randomize_first.isChecked(),"max_random_wait_candles":self.max_random_wait.value(),"enable_random_entry_batch":self.enable_random_batch.isChecked(),"random_seed_start":self.random_seed_start.value(),"random_seed_count":self.random_seed_count.value(),"run_name":self.run_name.text().strip(),"input_csv":self.input_csv.text(),"strategy_csv":self.input_csv.text(),"intrabar_csv":self.intrabar_csv.text(),"use_intrabar_data":self.use_intrabar.isChecked(),"trading_start_date":self.trading_start.text() or None,"trading_end_date":self.trading_end.text() or None,"max_effective_leverage_per_leg":self.max_lev_leg.text() or None,"max_combined_effective_leverage":self.max_lev_combined.text() or None,"intrabar_missing_policy":self.missing_policy.currentText(),"zero_cost_comparison":self.zero_cost.isChecked(),"trade_direction":self.trade_direction.currentText(),"enable_partial_take_profit":self.enable_partial_tp.isChecked(),"enable_partial_stop_loss":self.enable_partial_sl.isChecked(),"sl1_r":self.sl1_r.value(),"sl1_close_pct":self.sl1_close_pct.value(),"sl2_r":self.sl2_r.value(),"tp1_r":self.tp1_r.value(),"tp1_close_pct":self.tp1_close_pct.value(),"tp2_r":self.tp2_r.value(),"tp2_close_pct":self.tp2_close_pct.value(),"stop_loss_r":self.stop_loss_r.value(),"after_tp1_stop_mode":self.after_tp1_stop_mode.currentText(),"after_tp1_stop_offset_r":self.after_tp1_stop_offset_r.value(),"tp2_exit_mode":"FIXED_TP2","enable_trailing_profit":self.enable_trailing_profit.isChecked(),"trail_activation_trigger":self.trail_activation_trigger.currentText(),"trail_activation_r":self.trail_activation_r.value(),"trail_distance_r":self.trail_distance_r.value(),"trail_apply_to":self.trail_apply_to.currentText(),"trail_intrabar_mode":self.trail_intrabar_mode.currentText(),"output_dir":self.output_folder.text(),"sl_mult":self.sl.value(),"tp_mult":self.tp.value(),"entry_mode":self.entry_mode.currentText(),"entry_interval":self.entry_interval.value(),"enable_daily_entry_schedule":self.enable_daily_schedule.isChecked(),"daily_entry_time":self.daily_entry_time.text().strip(),"daily_entry_timezone":self.daily_entry_timezone.text().strip(),"daily_entry_missed_policy":self.daily_entry_missed_policy.currentText(),"enable_skip_monday_entries":self.skip_monday_entries.isChecked(),"skip_monday_timezone":self.skip_monday_timezone.text().strip(),"max_active_pairs":self.max_pairs.value(),"tie_policy":self.tie.currentText(),"risk_mode":self.risk_mode.currentText(),"atr_period":self.atr_period.value(),"atr_multiplier":self.atr_mult.value(),"percent_r":parse_percentage(self.percent_r.text()),"fixed_r":self.fixed_r.value(),"initial_equity":self.equity.value(),"risk_per_leg":parse_percentage(self.risk_leg.text()),"maker_fee":parse_percentage(self.maker.text()),"taker_fee":parse_percentage(self.taker.text()),"use_maker_entry":self.maker_entry.isChecked(),"use_maker_exit":self.maker_exit.isChecked(),"slippage":parse_percentage(self.slippage.text()),"enable_both_open_timeout":self.both_timeout.isChecked(),"max_both_open_minutes":self.both_timeout_duration.value()*(60 if self.both_timeout_unit.currentText()=="Hours" else 1),"both_open_timeout_unit":self.both_timeout_unit.currentText(),"enable_remaining_leg_timeout_after_first_sl":self.remaining_leg_timeout.isChecked(),"remaining_leg_timeout_after_first_sl_minutes":self.remaining_leg_timeout_duration.value()*(60 if self.remaining_leg_timeout_unit.currentText()=="Hours" else 1),"remaining_leg_timeout_after_first_sl_unit":self.remaining_leg_timeout_unit.currentText(),"enable_remaining_leg_timeout_profit_extension":self.remaining_leg_timeout_profit_extension.isChecked(),"remaining_leg_timeout_profit_threshold_r":self.remaining_leg_timeout_profit_threshold_r.value(),"enable_adx_filter":self.enable_adx.isChecked(),"adx_period":self.adx_period.value(),"adx_filter_mode":self.adx_mode.currentText(),"adx_maximum":self.adx_max.value(),"adx_minimum":self.adx_min.value(),"enable_bb_width_filter":self.enable_bb_width.isChecked(),"bb_width_filter_mode":self.bb_width_mode.currentText(),"bb_width_maximum":self.bb_width_max.value(),"bb_width_minimum":self.bb_width_min.value(),"enable_di_spread_filter":self.enable_di_spread.isChecked(),"di_spread_filter_mode":self.di_spread_mode.currentText(),"di_spread_maximum":self.di_spread_max.value(),"di_spread_minimum":self.di_spread_min.value(),"enable_atr_checkpoint_tp_extension":self.enable_atr_checkpoint_tp_extension.isChecked(),"atr_checkpoint_di_spread_minimum":self.atr_checkpoint_di_spread_min.value(),"atr_checkpoint_bb_width_minimum":self.atr_checkpoint_bb_width_min.value(),"atr_checkpoint_profit_lock_start":self.atr_checkpoint_profit_lock_start.value(),"atr_checkpoint_profit_lock_distance":self.atr_checkpoint_profit_lock_distance.value(),"enable_be_after_opposite_sl":self.be_after_sl.isChecked(),"be_mode":self.be_mode.currentText(),"be_offset_r":self.be_offset.value(),"be_same_candle_policy":self.be_same_candle.currentText(),"enable_trade_telemetry":self.enable_trade_telemetry.isChecked(),"save_full_telemetry_csv":self.save_full_telemetry.isChecked(),"save_trade_journey_summary":self.save_journey_summary.isChecked(),"save_trade_journey_charts":self.save_journey_charts.isChecked(),"telemetry_interval_minutes":self.telemetry_interval.value()}
    def values(self):
        values = self._base_values()
        values.update({"enable_coin_flip_sizing":self.enable_coin_flip_sizing.isChecked(),"coin_flip_seed":self.coin_flip_seed.text().strip(),"coin_flip_large_multiplier":3.0,"coin_flip_small_multiplier":1.0})
        values.update({"enable_di_direction_sizing":self.enable_di_direction_sizing.isChecked(),"di_direction_minimum_spread":self.di_direction_long_min_spread.value(),"di_direction_long_minimum_spread":self.di_direction_long_min_spread.value(),"di_direction_short_minimum_spread":self.di_direction_short_min_spread.value(),"di_execution_mode":self.di_execution_mode.currentText(),"di_reward_risk_ratio":self.di_long_reward_risk_ratio.value(),"di_long_reward_risk_ratio":self.di_long_reward_risk_ratio.value(),"di_short_reward_risk_ratio":self.di_short_reward_risk_ratio.value()})
        values.update({"enable_di_regime_reward_risk":self.enable_di_regime_reward_risk.isChecked(),"di_regime_bear_return_threshold":parse_percentage(self.di_regime_bear_return_threshold.text()),"di_long_bull_reward_risk_ratio":self.di_long_bull_reward_risk_ratio.value(),"di_long_bear_reward_risk_ratio":self.di_long_bear_reward_risk_ratio.value(),"di_long_sideways_reward_risk_ratio":self.di_long_sideways_reward_risk_ratio.value(),"di_short_bull_reward_risk_ratio":self.di_short_bull_reward_risk_ratio.value(),"di_short_bear_reward_risk_ratio":self.di_short_bear_reward_risk_ratio.value(),"di_short_sideways_reward_risk_ratio":self.di_short_sideways_reward_risk_ratio.value()})
        values.update({"enable_bull_long_conditional_reward_risk":self.enable_bull_long_conditional_reward_risk.isChecked(),"bull_long_conditional_bb_width_minimum":parse_percentage(self.bull_long_conditional_bb_width_minimum.text()),"bull_long_conditional_adx_maximum":self.bull_long_conditional_adx_maximum.value(),"bull_long_conditional_reward_risk_ratio":self.bull_long_conditional_reward_risk_ratio.value()})
        values.update({"enable_bull_long_momentum_confirmation":self.enable_bull_long_momentum_confirmation.isChecked(),"bull_long_confirmation_lookback_days":self.bull_long_confirmation_lookback_days.value(),"bull_long_confirmation_return_threshold":parse_percentage(self.bull_long_confirmation_return_threshold.text()),"bull_long_unconfirmed_reward_risk_ratio":self.bull_long_unconfirmed_reward_risk_ratio.value()})
        values.update({"enable_bull_long_momentum_target_extension":self.enable_bull_long_momentum_target_extension.isChecked(),"bull_long_momentum_extension_lookback_days":self.bull_long_momentum_extension_lookback_days.value(),"bull_long_momentum_extension_return_threshold":parse_percentage(self.bull_long_momentum_extension_return_threshold.text()),"enable_bull_long_momentum_extension_return_maximum":self.enable_bull_long_momentum_extension_return_maximum.isChecked(),"bull_long_momentum_extension_return_maximum":parse_percentage(self.bull_long_momentum_extension_return_maximum.text()),"bull_long_momentum_extended_reward_risk_ratio":self.bull_long_momentum_extended_reward_risk_ratio.value()})
        values.update({"enable_bull_long_structural_confirmation":self.enable_bull_long_structural_confirmation.isChecked(),"bull_long_structural_sma_days":self.bull_long_structural_sma_days.value(),"bull_long_structural_slope_lookback_days":self.bull_long_structural_slope_lookback_days.value(),"bull_long_structural_unconfirmed_reward_risk_ratio":self.bull_long_structural_unconfirmed_reward_risk_ratio.value()})
        values.update({"enable_bull_long_r_step_trailing":self.enable_bull_long_r_step_trailing.isChecked(),"bull_long_r_step_activation_r":self.bull_long_r_step_activation_r.value(),"bull_long_r_step_distance_r":self.bull_long_r_step_distance_r.value(),"bull_long_r_step_size_r":self.bull_long_r_step_size_r.value(),"bull_long_r_step_maximum_r":self.bull_long_r_step_maximum_r.value(),"bull_long_r_step_activation_close_pct":self.bull_long_r_step_activation_close_pct.value()})
        values.update({"enable_sideways_long_conditional_reward_risk":self.enable_sideways_long_conditional_reward_risk.isChecked(),"sideways_long_conditional_adx_maximum":self.sideways_long_conditional_adx_maximum.value(),"sideways_long_conditional_reward_risk_ratio":self.sideways_long_conditional_reward_risk_ratio.value(),"enable_sideways_short_conditional_reward_risk":self.enable_sideways_short_conditional_reward_risk.isChecked(),"sideways_short_conditional_di_spread_minimum":self.sideways_short_conditional_di_spread_minimum.value(),"sideways_short_conditional_di_spread_maximum":self.sideways_short_conditional_di_spread_maximum.value(),"sideways_short_conditional_reward_risk_ratio":self.sideways_short_conditional_reward_risk_ratio.value(),"enable_bear_short_conditional_reward_risk":self.enable_bear_short_conditional_reward_risk.isChecked(),"bear_short_conditional_di_spread_maximum":self.bear_short_conditional_di_spread_maximum.value(),"bear_short_conditional_reward_risk_ratio":self.bear_short_conditional_reward_risk_ratio.value()})
        values.update({"enable_directional_adx_filter":self.enable_directional_adx_filter.isChecked(),"directional_long_adx_maximum":self.directional_long_adx_maximum.value(),"directional_short_adx_minimum":self.directional_short_adx_minimum.value()})
        values.update({"enable_biased_short_adx_cap":self.enable_biased_short_adx_cap.isChecked(),"biased_short_adx_maximum":self.biased_short_adx_maximum.value()})
        values.update({"enable_bull_regime_short_filter":self.enable_bull_regime_short_filter.isChecked(),"bull_regime_lookback_days":self.bull_regime_lookback_days.value(),"bull_regime_return_threshold":parse_percentage(self.bull_regime_return_threshold.text())})
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
            df=load_ohlcv_csv(self.input_csv.text(), expected_timeframe_minutes=self._timeframe_minutes(self.strategy_timeframe.currentText()), label="Strategy data", strict_timeframe=True); self._validated_strategy_data=df; sm=df.attrs.get("summary"); miss=sm.missing_candles; tf=f"{sm.detected_timeframe_minutes} minutes"; self.dataset_info.setText(f"Total candles: {len(df):,}\nStart date: {df.timestamp.min()}\nEnd date: {df.timestamp.max()}\nDetected timeframe: {tf}\nMissing candles: {miss}\nRows removed: see log/console\nDuplicate candles removed: see log/console"); self.append_log("Data validation passed."); return True
        except Exception as e: QMessageBox.warning(self,"Invalid CSV",str(e)); self.append_log(traceback.format_exc()); return False
    def update_planned_output(self):
        try:
            cfg=build_backtest_config(self.values(), require_paths=False); self.planned_output.setText(str(planned_run_dir(cfg).resolve()))
        except Exception:
            self.planned_output.setText("Output run folder: unavailable until configuration is valid")
    def update_dynamic(self):
        if hasattr(self,"strategy_timeframe"):
            strategy=self._timeframe_minutes(self.strategy_timeframe.currentText())
            intrabar=self._timeframe_minutes(self.intrabar_timeframe.currentText())
            available=strategy > 1
            self.use_intrabar.setEnabled(available)
            self.intrabar_timeframe.setEnabled(available and self.use_intrabar.isChecked())
            self.intrabar_csv.setEnabled(available and self.use_intrabar.isChecked())
            self.data_help.setText(f"ATR, entry price, SL, and TP are calculated from {self.strategy_timeframe.currentText()} candles.\n" + (f"{self.intrabar_timeframe.currentText()} candles are used only to determine the exact exit sequence.\n" if self.use_intrabar.isChecked() else "Intrabar exit resolution is disabled.\n") + "Fees are charged on full notional, not margin; leverage changes required margin but does not reduce trading fees.")
        m=getattr(self,'risk_mode',None) and self.risk_mode.currentText(); self.atr_period.setVisible(m=="ATR"); self.atr_mult.setVisible(m=="ATR"); self.percent_r.setVisible(m=="PERCENT"); self.fixed_r.setVisible(m=="FIXED"); self.risk_formula.setText({"ATR":"R = ATR × ATR Multiplier","PERCENT":"R = Entry Price × Percentage","FIXED":"R = Fixed Price Distance"}.get(m,""));
        try:
            r=parse_percentage(self.risk_leg.text())
            preferred_only = hasattr(self, "di_execution_mode") and self.enable_di_direction_sizing.isChecked() and self.di_execution_mode.currentText()=="PREFERRED_SIDE_ONLY"
            planned = r if preferred_only else r*2
            label = "Selected Trade Risk" if preferred_only else "Combined Risk Per Pair"
            self.risk_warn.setText(f"{label} = {format_percentage(planned,2)}" + (" WARNING: exceeds 5%." if planned>0.05 else ""))
        except Exception: pass
        if hasattr(self,"enable_daily_schedule"):
            en=self.enable_daily_schedule.isChecked(); self.daily_entry_time.setEnabled(en); self.daily_entry_timezone.setEnabled(en); self.daily_entry_missed_policy.setEnabled(en); self.next_entry_summary.setText(f"Next eligible entry time: {self.daily_entry_time.text() or '00:00'} {self.daily_entry_timezone.text() or 'UTC'}" if en else "Daily schedule disabled; existing entry mode controls entries.")
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
        try: cost=(parse_percentage(self.maker.text())+parse_percentage(self.taker.text()))*2; self.cost.setText(f"Approx. long entry + long exit + short entry + short exit: {format_percentage(cost,4)}. Actual cost varies based on exit price and quantity.")
        except Exception: pass
        try: be=theoretical_break_even(self.sl.value(),self.tp.value()); actual=self.last_summary.get('win_rate'); diff="n/a" if actual is None else format_percentage(actual-be,2); self.be_label.setText(f"Theoretical break-even before fees: {format_percentage(be,2)}\nActual backtest win rate: {format_percentage(actual,2) if actual is not None else 'n/a'}\nDifference from break-even: {diff}\nThe theoretical value assumes every winner is exactly one TP and one SL. Fees, slippage, end-of-data exits, and other outcomes increase the actual required win rate.")
        except Exception: pass
    def run_backtest(self):
        try: vals=self.values(); cfg=build_backtest_config(vals); Path(vals['output_dir']).mkdir(parents=True,exist_ok=True); cfg=replace(cfg, output_run_dir=planned_run_dir(cfg)); self.planned_output.setText(str(cfg.output_run_dir.resolve()))
        except Exception as e: QMessageBox.warning(self,"Validation Problems",str(e)); return
        if not self.validate_data(): return
        self.output_dir=cfg.output_run_dir; self.thread=QThread(); self.worker=BacktestWorker(cfg, self._validated_strategy_data); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.status.connect(self.on_status); self.worker.log.connect(self.append_log); self.worker.finished.connect(self.on_finished); self.worker.failed.connect(self.on_failed); self.started=time.time(); self.cancel_btn.setEnabled(True); self.run_btn.setEnabled(False); self.thread.start()
    def on_status(self,s,p): self.status.setText(s); self.progress.setValue(p); self.elapsed.setText(f"Elapsed: {int(time.time()-self.started)}s")
    def on_finished(self,summary,trades,equity,out): self.last_summary=summary; self.output_dir=Path(out); self.populate_summary(summary); self.trade_model.set_dataframe(trades); self.refresh_chart(); self.cleanup_thread(); self.update_dynamic()
    def on_failed(self,msg,tb): QMessageBox.critical(self,"Backtest Error",msg); self.append_log(tb); self.cleanup_thread()
    def cleanup_thread(self): self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False); self.thread.quit(); self.thread.wait(); self.thread=None; self.worker=None
    def populate_summary(self,s):
        keys=["trade_direction","total_pairs","total_trades","wins","losses","flat_pairs","win_rate","loss_rate","average_net_r","median_net_r","total_net_r","profit_factor","ending_equity","total_return_percentage","maximum_drawdown","maximum_drawdown_percentage","maximum_consecutive_wins","maximum_consecutive_losses","average_holding_time","expectancy","average_winner","average_loser","total_fees","ambiguous_event_count","average_combined_effective_leverage","maximum_combined_effective_leverage","total_fees","pairs_closed_by_both_open_timeout","pairs_where_remaining_leg_timeout_started","pairs_closed_by_remaining_leg_timeout","remaining_legs_reaching_tp_before_timeout","remaining_legs_hitting_sl_or_be_before_timeout","average_pnl_of_remaining_leg_timeout_pairs","total_pnl_of_remaining_leg_timeout_pairs","profitable_remaining_leg_timeout_pairs","losing_remaining_leg_timeout_pairs","pairs_where_be_was_triggered","remaining_legs_stopped_at_be","remaining_legs_reaching_tp_after_be_move","average_pnl_of_be_triggered_pairs","total_pnl_of_be_triggered_pairs","double_sl_count_prevented","be_same_candle_ambiguity_count","average_timeout_pair_pnl","total_timeout_pair_pnl","timeout_pairs_profitable","timeout_pairs_losing","average_fees_as_percentage_of_expected_winning_profit","scheduled_entry_opportunities","trades_opened_on_schedule","scheduled_entries_skipped_because_trade_was_open","scheduled_entries_skipped_by_filters","scheduled_entries_skipped_due_to_missing_data","average_entry_delay","maximum_entry_delay","days_with_trades","days_without_trades","signals_evaluated","signals_skipped_by_adx","signals_skipped_by_filters","signals_traded","average_adx_of_winning_trades","average_adx_of_losing_trades","average_plus_di_of_winners","average_plus_di_of_losers","average_minus_di_of_winners","average_minus_di_of_losers"]
        extension_metrics=["pairs_with_remaining_leg_timeout_extension","remaining_leg_timeout_checkpoint_count","remaining_leg_timeout_extension_count","remaining_legs_reaching_tp_after_extension","first_sl_survivor_partial_closes","first_sl_survivor_partial_net_pnl","checkpoint_zero_score_confirmed_closes","checkpoint_reentry_gates_started","checkpoint_reentry_gates_released_by_tp","checkpoint_reentry_gates_released_by_sl","checkpoint_reentry_gates_released_by_tp_and_sl","checkpoint_reentry_gates_unreleased_at_end"]
        keys[keys.index("pairs_where_be_was_triggered"):keys.index("pairs_where_be_was_triggered")]=extension_metrics
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
        self.strategy_timeframe.setCurrentText(self._timeframe_label(int(values["strategy_timeframe_minutes"])))
        self.intrabar_timeframe.setCurrentText(self._timeframe_label(int(values["intrabar_timeframe_minutes"])))
        self.input_csv.setText(str(values["input_csv"]))
        self.intrabar_csv.setText(str(values["intrabar_csv"]))
        self.use_intrabar.setChecked(bool(values["use_intrabar_data"]) and int(values["strategy_timeframe_minutes"]) > 1)
        self.output_folder.setText(str(values["output_dir"]))
        self.sl.setValue(float(values["sl_mult"]))
        self.tp.setValue(float(values["tp_mult"]))
        self.entry_mode.setCurrentText(values["entry_mode"])
        self.entry_interval.setValue(int(values["entry_interval"]))
        self.enable_random_entry.setChecked(bool(values.get("enable_random_entry",False))); self.entry_timing_mode.setCurrentText(str(values.get("entry_timing_mode","CURRENT"))); self.random_probability.setValue(float(values.get("random_entry_probability",0.5))); self.random_seed.setText(str(values.get("random_seed",42))); self.random_start_mode.setCurrentText(str(values.get("random_entry_start_mode","NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"))); self.randomize_first.setChecked(bool(values.get("randomize_first_entry",True))); self.max_random_wait.setValue(int(values.get("max_random_wait_candles",0))); self.enable_random_batch.setChecked(bool(values.get("enable_random_entry_batch",False))); self.random_seed_start.setValue(int(values.get("random_seed_start",1))); self.random_seed_count.setValue(int(values.get("random_seed_count",100)))
        self.enable_coin_flip_sizing.setChecked(bool(values.get("enable_coin_flip_sizing",False))); self.coin_flip_seed.setText(str(values.get("coin_flip_seed",42)))
        legacy_di_minimum=float(values.get("di_direction_minimum_spread",30.0)); legacy_di_ratio=float(values.get("di_reward_risk_ratio",1.0)); self.enable_di_direction_sizing.setChecked(bool(values.get("enable_di_direction_sizing",False))); self.di_direction_long_min_spread.setValue(float(values.get("di_direction_long_minimum_spread",legacy_di_minimum))); self.di_direction_short_min_spread.setValue(float(values.get("di_direction_short_minimum_spread",legacy_di_minimum))); self.di_execution_mode.setCurrentText(str(values.get("di_execution_mode","BOTH_SIDES"))); self.di_long_reward_risk_ratio.setValue(float(values.get("di_long_reward_risk_ratio",legacy_di_ratio))); self.di_short_reward_risk_ratio.setValue(float(values.get("di_short_reward_risk_ratio",legacy_di_ratio)))
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
        self.enable_bull_regime_short_filter.setChecked(bool(values.get("enable_bull_regime_short_filter",False))); self.bull_regime_lookback_days.setValue(int(values.get("bull_regime_lookback_days",90))); self.bull_regime_return_threshold.setText(format_percentage(float(values.get("bull_regime_return_threshold",0.20)),2))
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
        self.enable_trade_telemetry.setChecked(bool(values.get("enable_trade_telemetry", True))); self.telemetry_interval.setValue(int(values.get("telemetry_interval_minutes", 15))); self.save_full_telemetry.setChecked(bool(values.get("save_full_telemetry_csv", True))); self.save_journey_summary.setChecked(bool(values.get("save_trade_journey_summary", True))); self.save_journey_charts.setChecked(bool(values.get("save_trade_journey_charts", True)))
        self.enable_lifecycle.setChecked(bool(values.get("enable_indicator_lifecycle_analysis",True))); self.lifecycle_phases.setValue(int(values.get("lifecycle_phases",4))); self.lifecycle_checkpoints.setText(",".join(str(v) for v in values.get("lifecycle_early_checkpoints",[15,30,60]))); self.lifecycle_min_sample.setValue(int(values.get("lifecycle_minimum_bucket_sample",20))); self.lifecycle_charts.setChecked(bool(values.get("create_lifecycle_charts",True))); self.lifecycle_flat_threshold.setValue(float(values.get("lifecycle_flat_pattern_threshold_pct",5.0)))
        self.be_after_sl.setChecked(bool(values.get("enable_be_after_opposite_sl", False)))
        self.be_mode.setCurrentText(values.get("be_mode", "ENTRY_PRICE")); self.be_offset.setValue(float(values.get("be_offset_r", 0.0))); self.be_same_candle.setCurrentText(values.get("be_same_candle_policy", "NEXT_CANDLE")); self.be_offset.setEnabled(self.be_mode.currentText()=="R_OFFSET")
        self.update_dynamic()
        self.update_planned_output()
    def append_log(self,t): self.log.append(str(t))
    def save_log(self):
        p,_=QFileDialog.getSaveFileName(self,"Save Log","backtest.log","Log (*.log *.txt)");
        if p: Path(p).write_text(self.log.toPlainText())
