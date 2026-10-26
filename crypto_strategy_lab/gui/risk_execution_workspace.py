"""Researcher-facing Risk & Execution composition.

The native ExecutionConfig and ExecutionProfileConfig forms remain authoritative.
This module only reorganizes their existing widgets into a mode-aware workspace so
researchers see the controls that matter for the selected execution plan.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class FormCard(QGroupBox):
    """Small card that can hide individual form rows without replacing widgets."""

    def __init__(self, title: str, *, note: str = "", parent=None):
        super().__init__(title, parent)
        outer = QVBoxLayout(self)
        if note:
            note_label = QLabel(note)
            note_label.setWordWrap(True)
            note_label.setStyleSheet("color:#52606d")
            outer.addWidget(note_label)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(8, 4, 8, 4)
        outer.addWidget(self.body)
        self.rows: dict[str, tuple[QLabel | None, QWidget]] = {}

    def add_field(self, name: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label)
        self.form.addRow(label_widget, widget)
        self.rows[name] = (label_widget, widget)

    def add_control(self, name: str, widget: QWidget) -> None:
        self.form.addRow(widget)
        self.rows[name] = (None, widget)

    def set_row_visible(self, name: str, visible: bool) -> None:
        row = self.rows.get(name)
        if row is None:
            return
        label, widget = row
        if label is not None:
            label.setVisible(visible)
        widget.setVisible(visible)


class DisclosureCard(QGroupBox):
    """Advanced settings card collapsed by default."""

    def __init__(self, title: str, *, note: str, expanded: bool = False, parent=None):
        super().__init__(title, parent)
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        explanation = QLabel(note)
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color:#52606d")
        top.addWidget(explanation, 1)
        self.toggle = QToolButton()
        self.toggle.setText("Show settings")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        top.addWidget(self.toggle)
        outer.addLayout(top)

        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(8, 4, 8, 4)
        outer.addWidget(self.body)
        self.rows: dict[str, tuple[QLabel | None, QWidget]] = {}
        self.toggle.toggled.connect(self._toggle_body)
        self._toggle_body(expanded)

    def _toggle_body(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle.setText("Hide settings" if checked else "Show settings")

    def add_field(self, name: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label)
        self.form.addRow(label_widget, widget)
        self.rows[name] = (label_widget, widget)

    def add_control(self, name: str, widget: QWidget) -> None:
        self.form.addRow(widget)
        self.rows[name] = (None, widget)

    def set_row_visible(self, name: str, visible: bool) -> None:
        row = self.rows.get(name)
        if row is None:
            return
        label, widget = row
        if label is not None:
            label.setVisible(visible)
        widget.setVisible(visible)


class RiskExecutionWorkspace(QWidget):
    """Friendly composition over the two authoritative execution dataclass forms."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.execution_form = window.execution_form
        self.base_form = window.base_execution_form
        self.account = self.execution_form.widgets
        self.trade = self.base_form.widgets

        # Keep the authoritative forms alive for build/apply/round-trip behavior,
        # but remove their old long-form presentation from the active page.
        self.execution_form.setParent(window)
        self.base_form.setParent(window)
        self.execution_form.hide()
        self.base_form.hide()

        self._prepare_widgets()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.plan_box = QGroupBox("Effective Plan")
        plan_layout = QVBoxLayout(self.plan_box)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "font-size:13px; background:#f7f9fb; padding:10px; border:1px solid #d9e2ec"
        )
        plan_layout.addWidget(self.summary_label)
        layout.addWidget(self.plan_box)

        self.ema_gap_card = FormCard("EMA 100/300 trade settings", note="Skip clustered EMAs. ATR measures recent candle volatility; 0 disables this filter.")
        self.account["ema_reversal_min_gap_atr"].setRange(0., 100.)
        self.account["ema_reversal_min_gap_atr"].setSuffix(" × ATR")
        self.ema_gap_card.add_field("ema_reversal_min_gap_atr", "Minimum EMA gap", self.account["ema_reversal_min_gap_atr"])
        self.account["ema_reversal_min_entry_ema300_atr"].setRange(0., 100.)
        self.account["ema_reversal_min_entry_ema300_atr"].setSuffix(" × ATR")
        self.account["ema_reversal_min_entry_ema300_atr"].setToolTip("Minimum distance from the actual next-open entry price, including slippage, to the last completed candle's EMA 300 (high). Set 0 to disable.")
        self.ema_gap_card.add_field("ema_reversal_min_entry_ema300_atr", "Minimum entry distance from EMA 300", self.account["ema_reversal_min_entry_ema300_atr"])
        self.account["ema_reversal_target_r"].setRange(0.01, 100.)
        self.account["ema_reversal_target_r"].setSuffix(" R")
        self.account["ema_reversal_target_r"].setToolTip("TP stays at EMA 100. SL distance = entry-to-TP distance divided by this ratio. 2R halves SL distance; 3R uses one-third.")
        self.ema_gap_card.add_field("ema_reversal_target_r", "Reward / risk (TP stays at EMA 100)", self.account["ema_reversal_target_r"])
        layout.addWidget(self.ema_gap_card)

        self.sd_card = FormCard("Supply & demand retest", note="Strategy-owned stop and target. See the Effective Plan for entry conditions. 0 stop buffer uses the exact defended boundary.")
        for name,label in (("sd_swing_strength","Swing candles on each side"),("sd_stop_buffer_atr","Stop buffer beyond zone (ATR)"),("sd_minimum_r","Minimum reward / risk")):
            self.sd_card.add_field(name,label,self.account[name])
        for name,label in (("photon_confirmation_minutes","Photon context / confirmation expiry (minutes)"),("photon_retest_minutes","Photon origin retest expiry (minutes)")):
            self.sd_card.add_field(name,label,self.account[name])
            self.account[name].setRange(1,10080)
        self.account["photon_zone_reversal"].setText("Daily / 4H zone reversal → 15m change → pullback → 1m internal change → retest entry")
        self.sd_card.add_control("photon_zone_reversal", self.account["photon_zone_reversal"])
        self.account["photon_exit_on_15m_change"].setText("Close when the 15m trend changes against the trade")
        self.sd_card.add_control("photon_exit_on_15m_change", self.account["photon_exit_on_15m_change"])
        self.account["photon_target_4h"].setText("Target 4H swing instead of the first 15m swing objective")
        self.sd_card.add_control("photon_target_4h",self.account["photon_target_4h"])
        self.account["photon_flexible_entries"].setText("Flexible candidates — show value and structure mismatches for manual review")
        self.sd_card.add_control("photon_flexible_entries",self.account["photon_flexible_entries"])
        self.sd_card.add_field("ny_range_target_r", "New York range target (R)", self.account["ny_range_target_r"])
        self.account["ny_range_target_r"].setRange(2.,100.)
        self.sd_card.add_field("ny_range_overshoot_policy", "When target extends too far", self.account["ny_range_overshoot_policy"])
        policy=self.account["ny_range_overshoot_policy"]
        for value,label in (("DEFAULT","1. Default - keep breakout stop"),("SKIP","2. Ignore oversized setup"),("SR_STOP","3. Use a confirmed S/R stop")):
            policy.setItemText(policy.findData(value),label)
        self.sd_card.add_field("ny_range_max_extension_pct", "Allowed target beyond range (% of 4h height)", self.account["ny_range_max_extension_pct"])
        self.account["ny_range_max_extension_pct"].setRange(0.,1000.)
        self.account["ny_range_max_extension_pct"].setSuffix(" %")
        self.account["ny_range_max_extension_pct"].setToolTip("Long target ceiling = 4h high + this percentage of the 4h range height. Short floor = 4h low minus the same allowance. 0 keeps the target within the opening range.")
        self.sd_card.add_field("ny_range_sr_buffer_atr", "Buffer beyond S/R (entry ATR)", self.account["ny_range_sr_buffer_atr"])
        self.account["ny_range_sr_buffer_atr"].setRange(0.,100.)
        policy.currentIndexChanged.connect(self.refresh_visibility)

        self.sd_card.add_field("io_entry_model", "Imbalance entry model", self.account["io_entry_model"])
        model=self.account["io_entry_model"]
        model.setItemText(model.findData("ORIGIN_REJECTION"), "Origin rejection (original)")
        model.setItemText(model.findData("INDUCEMENT_CONFIRMATION"), "Inducement + structure confirmation")
        self.sd_card.add_field("io_context_minutes", "Zone timeframe (minutes)", self.account["io_context_minutes"])
        self.account["io_context_minutes"].setRange(1,10080)
        model.currentIndexChanged.connect(self.refresh_visibility)
        model.activated.connect(self._apply_imbalance_entry_timeframe)
        self.account["sd_swing_strength"].setRange(1,20)
        self.account["sd_stop_buffer_atr"].setRange(0.,100.)
        self.account["sd_minimum_r"].setRange(.01,100.)
        for name,label in (("ls_equal_tolerance_atr","Equal-high/low tolerance (ATR)"),("ls_displacement_atr","Minimum displacement body (ATR)"),("ls_base_bars","Maximum zone base candles"),("ls_max_wait_bars","Maximum wait per stage (candles)")):
            self.sd_card.add_field(name,label,self.account[name])
        for name,label in (("tc_require_live_confirmations","Cancel if confirmed structure / IFVG fails before entry"),
                           ("tc_require_structure","Require close beyond structure"),
                           ("tc_require_ifvg","Require inversion of an opposing FVG"),
                           ("tc_require_equilibrium","Require discount / premium overlap")):
            self.account[name].setText(label)
            self.sd_card.add_control(name,self.account[name])
        for name,label in (("tc_min_sweep_atr","Minimum sweep depth (ATR; 0 disables)"),
                           ("tc_displacement_atr","Minimum FVG middle body (ATR)"),
                           ("tc_max_wait_bars","Maximum candles from sweep"),
                           ("tc_fvg_lookback","Swing / opposing FVG lookback (candles)"),
                           ("tc_min_reversal_body_percent","Minimum reversal body (% of range)"),
                           ("tc_target_r","Final target (R)")):
            self.sd_card.add_field(name,label,self.account[name])
        self.account["tc_min_sweep_atr"].setRange(0.,100.)
        self.account["tc_require_live_confirmations"].setToolTip("After confirmation, cancel a long on a close below its structure level or inverted FVG bottom; reverse for shorts. Recheck the actual next-open entry too. Only required confirmations are enforced.")
        self.account["tc_displacement_atr"].setRange(.01,100.)
        self.account["tc_max_wait_bars"].setRange(1,500)
        self.account["tc_fvg_lookback"].setRange(1,500)
        self.account["tc_min_reversal_body_percent"].setRange(0.,100.)
        self.account["tc_min_reversal_body_percent"].setSuffix("%")
        self.account["tc_target_r"].setRange(.01,100.)
        self.account["tc_target_r"].setSuffix(" R")
        self.account["ls_equal_tolerance_atr"].setRange(0.,10.)
        self.account["ls_displacement_atr"].setRange(.01,100.)
        self.account["ls_base_bars"].setRange(1,20)
        self.account["ls_max_wait_bars"].setRange(1,500)
        self.account["sp_minimum_r_enabled"].setText("Require minimum reward / risk")
        self.account["sp_minimum_r_enabled"].setToolTip("Reject a breakout when the distance to TP divided by the distance to SL is below Minimum reward / risk. Checked at the executable entry including configured slippage; TP and SL stay unchanged.")
        self.sd_card.add_control("sp_minimum_r_enabled", self.account["sp_minimum_r_enabled"])
        self.account["sp_minimum_r_enabled"].toggled.connect(self.refresh_visibility)
        self.account["sp_recent_swings_enabled"].setText("Also test recent confirmed swing highs / lows")
        self.account["sp_recent_swings_enabled"].setToolTip("Adds the latest confirmed high/low formed since the start of the previous UTC day. Previous-day levels remain active; SL stays beyond the older outside swing and TP stays at the opposite previous-day boundary.")
        self.sd_card.add_control("sp_recent_swings_enabled", self.account["sp_recent_swings_enabled"])
        self.account["sp_require_level_reclaim"].setText("Require rejection: reversal closes back across tested level")
        self.account["sp_require_level_reclaim"].setToolTip("Long: green reversal closes strictly above the tested level. Short: red reversal closes strictly below it. Non-qualifying candles can wait within the existing confirmation window. No pin-bar or engulfing shape is required.")
        self.sd_card.add_control("sp_require_level_reclaim", self.account["sp_require_level_reclaim"])
        self.account["sp_cost_cover_enabled"].setText("At 1R cover costs with a partial close, then move SL to entry")
        self.account["sp_cost_cover_enabled"].setToolTip("Widen the swing-based stop only when necessary to cover estimated fees and slippage. Keep the previous-day TP and recheck minimum R. Funding and stop gaps are excluded.")
        self.sd_card.add_control("sp_cost_cover_enabled", self.account["sp_cost_cover_enabled"])
        self.sd_card.add_field("sp_cost_cover_close_pct", "Close at 1R", self.account["sp_cost_cover_close_pct"])
        self.account["sp_cost_cover_close_pct"].setRange(.01,99.99)
        self.account["sp_cost_cover_close_pct"].setSuffix("%")
        self.account["sp_cost_cover_enabled"].toggled.connect(self.refresh_visibility)
        for name,label in (("sp_level_tolerance_atr","Distance to level (ATR)"),("sp_body_atr","Minimum initial body (ATR)"),("sp_min_body_percent","Minimum body (% of candle range)"),("sp_confirmation_bars","Wait for reversal (candles)"),("sp_hold_minutes","Maximum hold from setup (minutes)")):
            self.sd_card.add_field(name,label,self.account[name])
        self.account["sp_level_tolerance_atr"].setRange(0.,10.)
        self.account["sp_body_atr"].setRange(.01,100.)
        self.account["sp_min_body_percent"].setRange(0.,100.)
        self.account["sp_min_body_percent"].setSuffix("%")
        self.account["sp_min_body_percent"].setToolTip("Body size as a percentage of high minus low. 50% preserves the original rule; 0% disables only this percentage check. Minimum initial body (ATR) still applies.")
        self.account["sp_confirmation_bars"].setRange(1,20)
        self.account["sp_hold_minutes"].setRange(75,100000)
        layout.addWidget(self.sd_card)

        self.entry_card = FormCard(
            "1. Entry Execution",
            note=(
                "Choose when a completed strategy signal becomes an executable fill. "
                "Next Candle Open is the causal default for EMA 9/20, FVG and Fib reaction entries."
            ),
        )
        self.entry_card.add_field(
            "entry_timing_mode", "Entry Fill Timing", self.account["entry_timing_mode"]
        )
        self.entry_card.add_field(
            "ema_920_trade_plan", "EMA 9/20 Trade Plan", self.account["ema_920_trade_plan"]
        )
        self.entry_card.add_control("ema_320_flip_signals", self.account["ema_320_flip_signals"])
        self.entry_card.add_field("ema_320_exit_mode", "EMA 320 Exit Policy", self.account["ema_320_exit_mode"])
        self.entry_card.add_control("ema_cross_cost_cycle_enabled", self.account["ema_cross_cost_cycle_enabled"])
        self.entry_card.add_control("ema_cross_initial_phantom_enabled", self.account["ema_cross_initial_phantom_enabled"])
        self.entry_card.add_control("ema_cross_reentry_widening_enabled", self.account["ema_cross_reentry_widening_enabled"])
        self.entry_card.add_control(
            "ema_cross_entry_confirmation_enabled",
            self.account["ema_cross_entry_confirmation_enabled"],
        )
        self.entry_card.add_field(
            "ema_cross_entry_confirmation_r",
            "Confirmation Distance",
            self.account["ema_cross_entry_confirmation_r"],
        )
        self.entry_card.add_control(
            "fvg_confirmation_enabled", self.account["fvg_confirmation_enabled"]
        )
        self.entry_card.add_field(
            "fvg_confirmation_minutes", "First Confirmation Candle", self.account["fvg_confirmation_minutes"]
        )
        self.account["fib_entry_50_618_only"].setText("Only enter inside the 50%–61.8% Fib zone")
        self.account["fib_entry_50_618_only"].setToolTip("Require the actual entry price after slippage to be strictly between the selected swing's 50% and 61.8% prices. Applies to both directions and deeper limit fills. Other entry rules still apply.")
        self.entry_card.add_control("fib_entry_50_618_only", self.account["fib_entry_50_618_only"])
        self.first_minute_confirmation = QToolButton()
        self.first_minute_confirmation.setText("Use first 1m confirmation")
        self.first_minute_confirmation.clicked.connect(self._use_first_minute_confirmation)
        self.entry_card.add_control("first_minute_confirmation", self.first_minute_confirmation)
        self.fvg_confirmation_note = QLabel(
            "Check only the first completed confirmation candle after the normal entry time. "
            "Long: close above open. Short: close below open. Enter at its close; "
            "skip an opposite or doji candle without waiting for another. "
            "The existing stop and target-room checks still apply. "
            "The 1m shortcut also selects 1m intrabar data in Setup."
        )
        self.fvg_confirmation_note.setWordWrap(True)
        self.entry_card.add_control("fvg_confirmation_note", self.fvg_confirmation_note)
        self.entry_card.add_control(
            "fvg_context_enabled", self.account["fvg_context_enabled"]
        )
        self.entry_card.add_field(
            "fvg_context_timeframe_minutes", "FVG Context Timeframe", self.account["fvg_context_timeframe_minutes"]
        )
        self.entry_card.add_field(
            "fvg_structure_swing_strength",
            "FVG Structure Swing Strength",
            self.account["fvg_structure_swing_strength"],
        )
        layout.addWidget(self.entry_card)
        self.entry_card.add_field("fvg_min_clear_bars", "FVG Minimum Clear Candles", self.account["fvg_min_clear_bars"])
        self.account["fvg_min_clear_bars"].setToolTip("Six-factor FVG only. Completed candles strictly between formation and first touch; 0 disables this filter.")
        self.entry_card.add_field("fvg_min_move_away_atr", "FVG Minimum Move-away (ATR)", self.account["fvg_min_move_away_atr"])
        self.account["fvg_min_move_away_atr"].setToolTip("Six-factor FVG only. Furthest wick distance away from the near gap edge, on intervening candles, divided by formation ATR. Excludes formation and revisit. 0 disables this filter.")

        # Strategy-specific signal controls are grouped by pipeline stage.
        # The underlying widgets stay authoritative; no duplicate state is introduced.
        self.ema320_candle_card = DisclosureCard(
            "Confirmation • EMA 320", note="ANY enabled pattern on a completed entry candle.",
            expanded=False,
        )
        for field, label in (
            ("ema_320_candle_confirmation_enabled", "Require Candle Confirmation"),
            ("ema_320_candle_strong_close", "Strong Bullish / Bearish Close"),
            ("ema_320_candle_engulfing", "Bullish / Bearish Engulfing"),
            ("ema_320_candle_wick_rejection", "Hammer / Shooting Star"),
            ("ema_320_candle_star", "Morning / Evening Star"),
        ):
            widget = self.window.feature_form.widgets[field]
            if isinstance(widget, QCheckBox):
                widget.setText(label)
            self.ema320_candle_card.add_control(field, widget)
        layout.addWidget(self.ema320_candle_card)

        fib_controls = self.window.feature_form.widgets
        self.fib_stage_cards = []
        fib_stages = (
            ("Signal • Fibonacci Structure", "Choose which impulse structures qualify.",
             (("fib_structure_quality_mode", "Impulse Quality"),)),
            ("Entry • Fibonacci Holds", "Choose how a confirmed Fib setup triggers an entry.",
             (("fib_half_swing_mode", "0.5 First Hold — Swing Stop / Impulse Target"),
              ("fib_inherited_first_held", "Inherit First Hold After Impulse Extension"),
              ("fib_first_0786_held", "Allow First Held at 0.786"),
              ("fib_third_retest_entry", "After Two Holds — Enter One Fib Deeper"),
              ("fib_first_zone_hold_entry", "First Hold in Halfway Fib Zone — No Line Touch"))),
            ("Context • Fibonacci EMA", "EMA filters may select Fib candidates or veto their entries.",
             (("fib_ema_trend_gate", "Require EMA 320/1600 Trend + Stop Beyond EMA 320"),
              ("fib_candidate_context_selection", "Select Fib Using EMA 320/1600 Trend + Stop"))),
            ("Confirmation • Fibonacci Candles", "Entry requires ANY selected directional candle pattern when enabled.",
             (("fib_candle_confirmation_enabled", "Require Candle Confirmation"),
              ("fib_candle_strong_close", "Strong Bullish / Bearish Close"),
              ("fib_candle_engulfing", "Bullish / Bearish Engulfing"),
              ("fib_candle_wick_rejection", "Hammer / Shooting Star"),
              ("fib_candle_star", "Morning / Evening Star"))),
        )
        for title, note, controls in fib_stages:
            card = DisclosureCard(title, note=note, expanded=False)
            for field, label in controls:
                widget = fib_controls[field]
                if isinstance(widget, QCheckBox):
                    widget.setText(label)
                if field == "fib_structure_quality_mode":
                    card.add_field(field, label, widget)
                else:
                    card.add_control(field, widget)
            layout.addWidget(card)
            self.fib_stage_cards.append(card)

        self.account_card = FormCard(
            "2. Account Risk & Position Sizing",
            note=(
                "The sizing budget determines quantity. With the optional separate sizing stop, "
                "the actual stop loss can be smaller than this budget."
            ),
        )
        self.account_card.add_field("initial_equity", "Starting Equity", self.account["initial_equity"])
        self.account_card.add_field("risk_per_leg", "Sizing Budget Per Trade", self.account["risk_per_leg"])
        self.account_card.add_field("max_active_pairs", "Maximum Active Trades", self.account["max_active_pairs"])
        layout.addWidget(self.account_card)

        self.stop_card = FormCard(
            "3. Stop & Position Sizing",
            note="The visible controls always reflect the stop logic actually used by the selected strategy.",
        )
        self.stop_card.add_field("risk_mode", "Stop Distance Method", self.account["risk_mode"])
        self.stop_card.add_field("atr_multiplier", "ATR Distance Multiplier", self.account["atr_multiplier"])
        self.stop_card.add_field("percent_r", "Price Distance", self.account["percent_r"])
        self.stop_card.add_field("fixed_r", "Fixed Price Distance", self.account["fixed_r"])
        self.stop_card.add_field("sr_stop_timeframe_minutes", "S/R Stop Timeframe", self.account["sr_stop_timeframe_minutes"])
        self.stop_card.add_field("sr_stop_buffer_atr", "Buffer Beyond S/R", self.account["sr_stop_buffer_atr"])
        self.stop_card.add_field("sr_stop_maximum_atr", "Maximum Structural Stop", self.account["sr_stop_maximum_atr"])
        self.stop_card.add_field("sr_stop_no_level_policy", "If No Valid S/R Exists", self.account["sr_stop_no_level_policy"])
        self.stop_card.add_field("stop_loss_multiple", "Actual Stop Multiplier", self.trade["stop_loss_multiple"])
        self.stop_card.add_control(
            "position_sizing_stop_override_enabled",
            self.trade["position_sizing_stop_override_enabled"],
        )
        self.stop_card.add_field(
            "position_sizing_stop_multiple",
            "Position-Sizing Stop Multiplier",
            self.trade["position_sizing_stop_multiple"],
        )
        self.stop_card.add_field(
            "ema_cross_stop_buffer_atr",
            "Stop vs EMA 100",
            self.trade["ema_cross_stop_buffer_atr"],
        )
        self.stop_card.add_field(
            "ema_cross_stop_multiplier",
            "EMA Cross Actual Stop Distance",
            self.trade["ema_cross_stop_multiplier"],
        )

        self.ema_stop_method = QLabel("EMA 9/20 Micro-Swing — Automatic")
        self.ema_stop_method.setStyleSheet("font-weight:600")
        self.ema_stop_confirmation = QLabel("2 left / 2 right")
        self.ema_stop_lookback = QLabel("20 bars")
        self.ema_stop_buffer = QLabel("0.05 × ATR")
        self.ema_stop_maximum = QLabel("1.50 × ATR")
        self.stop_card.add_field("ema_920_stop_method", "Stop Method", self.ema_stop_method)
        self.stop_card.add_field("ema_920_stop_confirmation", "Swing Confirmation", self.ema_stop_confirmation)
        self.stop_card.add_field("ema_920_stop_lookback", "Swing Lookback", self.ema_stop_lookback)
        self.stop_card.add_field("ema_920_stop_buffer", "Stop Buffer", self.ema_stop_buffer)
        self.stop_card.add_field("ema_920_stop_maximum", "Maximum Stop", self.ema_stop_maximum)
        self.fvg_stop_method = QLabel("FVG Box Boundary — Automatic")
        self.fvg_stop_buffer = QLabel("0.05 × signal ATR beyond the far edge")
        self.stop_card.add_field("fvg_stop_method", "Stop Method", self.fvg_stop_method)
        self.stop_card.add_field("fvg_stop_buffer", "Stop Buffer", self.fvg_stop_buffer)
        self.fib_stop_method = QLabel("Next Deeper Fib Level — Automatic")
        self.fib_stop_method.setStyleSheet("font-weight:600")
        self.stop_card.add_field("fib_stop_method", "Stop Method", self.fib_stop_method)
        self.stop_card.add_field(
            "fib_stop_buffer_atr", "Stop Buffer", self.account["fib_stop_buffer_atr"]
        )
        layout.addWidget(self.stop_card)

        self.target_card = FormCard(
            "4. Profit Target",
            note="The visible controls always reflect the target logic actually used by the selected strategy.",
        )
        self.target_card.add_field("sr_take_profit_mode", "Target Policy", self.account["sr_take_profit_mode"])
        self.target_card.add_field("reward_risk_ratio", "Base Profit Target", self.trade["reward_risk_ratio"])
        self.target_card.add_field("sr_take_profit_timeframe_minutes", "S/R Target Timeframe", self.account["sr_take_profit_timeframe_minutes"])
        self.target_card.add_field("sr_take_profit_minimum_r", "Minimum Acceptable Target", self.account["sr_take_profit_minimum_r"])
        self.target_card.add_field("sr_take_profit_maximum_r", "Maximum S/R Target Cap", self.account["sr_take_profit_maximum_r"])
        self.target_card.add_field("sr_take_profit_buffer_r", "Buffer Before S/R", self.account["sr_take_profit_buffer_r"])
        self.target_card.add_field("sr_take_profit_no_level_policy", "If No Opposing S/R Exists", self.account["sr_take_profit_no_level_policy"])
        self.ema_target_method = QLabel("EMA 9/20 Fixed 1R — Automatic")
        self.ema_target_method.setStyleSheet("font-weight:600")
        self.ema_target_value = QLabel("1.00 R")
        self.target_card.add_field("ema_920_target_method", "Target Method", self.ema_target_method)
        self.target_card.add_field("ema_920_target_value", "Profit Target", self.ema_target_value)
        self.fvg_target_method = QLabel("Configured R before FVG move high / low")
        self.fvg_target_method.setStyleSheet("font-weight:600")
        self.target_card.add_field("fvg_target_mode", "FVG Target Method", self.account["fvg_target_mode"])
        self.account["fvg_reject_ema100_in_tp"].setText("Reject trades with EMA 100 between entry and TP")
        self.account["fvg_reject_ema100_in_tp"].setToolTip(
            "Uses EMA 100 from the last completed strategy candle. Rejects longs and shorts "
            "when EMA is inside the actual entry-to-final-TP price range, including its edges. "
            "Checked after confirmation using the selected target mode."
        )
        self.target_card.add_control("fvg_reject_ema100_in_tp", self.account["fvg_reject_ema100_in_tp"])
        self.target_card.add_field("fvg_target_method", "Target Rule", self.fvg_target_method)
        for name, label in (
            ("fvg_target_timeframe_minutes", "Target FVG Timeframe"),
            ("fvg_target_minimum_r", "Minimum Target Reward / Risk"),
            ("fvg_target_no_level_policy", "If No Opposing FVG Exists"),
        ):
            self.target_card.add_field(name, label, self.account[name])
        self.fvg_target_note = QLabel(
            "Use the nearest untouched opposing FVG from completed higher-timeframe candles. "
            "TP sits just before its near edge and stays fixed after entry. "
            "Skip if that target is too close; the missing-FVG fallback applies only when no target exists."
        )
        self.fvg_target_note.setWordWrap(True)
        self.target_card.add_control("fvg_target_note", self.fvg_target_note)
        self.target_card.add_field(
            "fvg_target_buffer_atr", "Buffer Before Target Level", self.account["fvg_target_buffer_atr"]
        )
        self.fib_target_method = self.account["fib_target_mode"]
        self.target_card.add_field("fib_target_method", "Target Method", self.fib_target_method)
        self.target_card.add_field(
            "fib_fixed_target_r", "Fixed Profit Target", self.account["fib_fixed_target_r"]
        )
        self.target_card.add_field(
            "fib_target_buffer_atr", "Impulse-Extreme Room Buffer", self.account["fib_target_buffer_atr"]
        )
        self.target_card.add_field(
            "fib_minimum_target_r", "Minimum Target Room", self.account["fib_minimum_target_r"]
        )
        self.sr_dependency_note = QLabel(
            "Structural S/R stop/target policies automatically require causal Support / Resistance calculation; no separate enable step is needed."
        )
        self.sr_dependency_note.setWordWrap(True)
        self.sr_dependency_note.setStyleSheet("color:#52606d; margin:2px 8px 6px 8px")
        self.target_card.layout().addWidget(self.sr_dependency_note)
        layout.addWidget(self.target_card)

        self.ladder_card = FormCard(
            "5. DI Ladder / Reversal Filters",
            note=(
                "Optional opposite-side ladder linked to one initial DI trade. "
                "Level size is measured in the initial trade's sizing-R. "
                "Each layer can contain positive continuation-entry rules; if they fail, that layer is skipped while deeper layers remain eligible."
            ),
        )
        self.ladder_card.add_control(
            "di_ladder_enabled", self.account["di_ladder_enabled"]
        )
        self.ladder_card.add_field(
            "di_ladder_mode", "Execution Mode", self.account["di_ladder_mode"]
        )
        self.ladder_card.add_field(
            "di_reversal_target_r", "DI Reversal Target R", self.account["di_reversal_target_r"]
        )
        self.ladder_card.add_field(
            "di_ladder_level_r", "Ladder Level Size", self.account["di_ladder_level_r"]
        )
        self.ladder_card.add_field(
            "di_ladder_layers", "Layer Definitions", self.account["di_ladder_layers"]
        )
        layout.addWidget(self.ladder_card)

        self.management_card = FormCard(
            "6. Trade Management",
            note="Optional management stays compact while disabled. Enabling a feature reveals only its relevant settings.",
        )
        self.management_card.add_control("break_even_enabled", self.trade["break_even_enabled"])
        self.management_card.add_field("break_even_activation_r", "Break-even Activation", self.trade["break_even_activation_r"])
        self.management_card.add_field("break_even_offset_r", "Break-even Offset", self.trade["break_even_offset_r"])

        self.management_card.add_control("trailing_enabled", self.trade["trailing_enabled"])
        self.management_card.add_field("trailing_activation_r", "Trailing Activation", self.trade["trailing_activation_r"])
        self.management_card.add_field("trailing_distance_r", "Trailing Distance", self.trade["trailing_distance_r"])

        self.management_card.add_control("di_partial_1r_enabled", self.trade["di_partial_1r_enabled"])
        self.management_card.add_field("di_partial_1r_close_pct", "Close at 1R", self.trade["di_partial_1r_close_pct"])
        self.management_card.add_control("di_partial_cost_atr_enabled", self.trade["di_partial_cost_atr_enabled"])
        self.trade["di_partial_1r_close_pct"].setRange(.01,99.99)
        self.trade["di_partial_1r_close_pct"].setSuffix("%")
        self.management_card.add_control("partial_profit_enabled", self.trade["partial_profit_enabled"])
        self.management_card.add_field("tp1_r", "First Profit Level", self.trade["tp1_r"])
        self.management_card.add_field("tp1_close_pct", "First Profit Close", self.trade["tp1_close_pct"])
        self.management_card.add_field("tp2_r", "Final Profit Level", self.trade["tp2_r"])

        self.management_card.add_control("partial_stop_enabled", self.trade["partial_stop_enabled"])
        self.management_card.add_field("sl1_r", "First Stop Level", self.trade["sl1_r"])
        self.management_card.add_field("sl1_close_pct", "First Stop Close", self.trade["sl1_close_pct"])
        self.management_card.add_field("sl2_r", "Final Stop Level", self.trade["sl2_r"])

        self.management_card.add_control("timeout_enabled", self.trade["timeout_enabled"])
        self.management_card.add_field("timeout_minutes", "Maximum Holding Time", self.trade["timeout_minutes"])
        layout.addWidget(self.management_card)

        self.advanced_card = DisclosureCard(
            "Advanced Trade Management",
            note="Less-common research controls: risk override, R-step trailing and ATR-checkpoint target extension.",
            expanded=False,
        )
        self.advanced_card.add_field("risk_multiplier", "Risk Multiplier", self.trade["risk_multiplier"])
        self.advanced_card.add_control("r_step_trailing_enabled", self.trade["r_step_trailing_enabled"])
        self.advanced_card.add_field("r_step_activation_r", "R-step Activation", self.trade["r_step_activation_r"])
        self.advanced_card.add_field("r_step_distance_r", "R-step Distance", self.trade["r_step_distance_r"])
        self.advanced_card.add_field("r_step_size_r", "R-step Size", self.trade["r_step_size_r"])
        self.advanced_card.add_field("r_step_maximum_r", "R-step Maximum", self.trade["r_step_maximum_r"])
        self.advanced_card.add_field("r_step_activation_close_pct", "Activation Close %", self.trade["r_step_activation_close_pct"])
        self.advanced_card.add_control("atr_checkpoint_tp_extension_enabled", self.trade["atr_checkpoint_tp_extension_enabled"])
        self.advanced_card.add_field("atr_checkpoint_di_spread_minimum", "Checkpoint Minimum DI Spread", self.trade["atr_checkpoint_di_spread_minimum"])
        self.advanced_card.add_field("atr_checkpoint_bb_width_minimum", "Checkpoint Minimum BB Width", self.trade["atr_checkpoint_bb_width_minimum"])
        self.advanced_card.add_field("atr_checkpoint_profit_lock_start", "Profit Lock Start", self.trade["atr_checkpoint_profit_lock_start"])
        self.advanced_card.add_field("atr_checkpoint_profit_lock_distance", "Profit Lock Distance", self.trade["atr_checkpoint_profit_lock_distance"])
        layout.addWidget(self.advanced_card)

        self.costs_card = DisclosureCard(
            "Exposure & Costs",
            note="Safety limits and execution assumptions are important, but normally do not need to occupy the main workflow.",
            expanded=False,
        )
        self.costs_card.add_field("max_effective_leverage_per_leg", "Maximum Effective Leverage Per Trade", self.account["max_effective_leverage_per_leg"])
        self.costs_card.add_field("max_combined_effective_leverage", "Maximum Combined Effective Leverage", self.account["max_combined_effective_leverage"])
        self.costs_card.add_field("maker_fee", "Maker Fee", self.account["maker_fee"])
        self.costs_card.add_field("taker_fee", "Taker Fee", self.account["taker_fee"])
        self.costs_card.add_control("use_maker_entry", self.account["use_maker_entry"])
        self.costs_card.add_control("use_maker_exit", self.account["use_maker_exit"])
        self.costs_card.add_field("slippage", "Slippage", self.account["slippage"])
        self.costs_card.add_field("tie_policy", "Same-bar Resolution", self.account["tie_policy"])
        self.costs_card.add_control("zero_cost_comparison", self.account["zero_cost_comparison"])
        layout.addWidget(self.costs_card)
        layout.addStretch()

        self.account["risk_mode"].currentIndexChanged.connect(self.refresh_visibility)
        self.trade["di_partial_1r_close_pct"].valueChanged.connect(self.refresh_summary_from_widgets)
        self.account["sr_take_profit_mode"].currentIndexChanged.connect(self.refresh_visibility)
        self.account["entry_timing_mode"].currentIndexChanged.connect(self.refresh_summary_from_widgets)
        self.account["ema_920_trade_plan"].currentIndexChanged.connect(self.refresh_visibility)
        self.account["ema_cross_cost_cycle_enabled"].toggled.connect(self.refresh_visibility)
        self.account["ema_cross_initial_phantom_enabled"].toggled.connect(self.refresh_visibility)
        self.account["ema_cross_reentry_widening_enabled"].toggled.connect(self.refresh_summary_from_widgets)
        self.account["ema_cross_entry_confirmation_enabled"].toggled.connect(self.refresh_visibility)
        self.account["fvg_confirmation_enabled"].toggled.connect(self.refresh_visibility)
        self.account["fvg_confirmation_minutes"].valueChanged.connect(self.refresh_summary_from_widgets)
        self.account["fvg_target_mode"].currentIndexChanged.connect(self.refresh_visibility)
        self.account["fvg_target_no_level_policy"].currentIndexChanged.connect(self.refresh_visibility)
        self.account["di_ladder_enabled"].toggled.connect(self.refresh_visibility)
        self.account["di_ladder_mode"].currentIndexChanged.connect(self.refresh_visibility)
        builder = getattr(self.window, "rule_builder", None)
        if builder is not None:
            builder.direction_mode.currentIndexChanged.connect(self.refresh_visibility)
        for name in (
            "position_sizing_stop_override_enabled", "di_partial_1r_enabled", "di_partial_cost_atr_enabled",
            "break_even_enabled", "trailing_enabled", "partial_profit_enabled",
            "partial_stop_enabled", "timeout_enabled", "r_step_trailing_enabled",
            "atr_checkpoint_tp_extension_enabled",
        ):
            self.trade[name].toggled.connect(self.refresh_visibility)

        self.refresh_visibility()
        self.refresh_summary_from_widgets()

    def _use_first_minute_confirmation(self) -> None:
        self.window.intrabar_tf.setCurrentText("1m")
        self.account["fvg_confirmation_minutes"].setValue(1)
        timing = self.account["entry_timing_mode"]
        timing.setCurrentIndex(timing.findData("NEXT_CANDLE_OPEN"))
        self.account["fvg_confirmation_enabled"].setChecked(True)
        self.refresh_visibility()

    def _prepare_widgets(self) -> None:
        for name, text in {
            "position_sizing_stop_override_enabled": "Use separate position-sizing stop",
            "break_even_enabled": "Enable break-even",
            "trailing_enabled": "Enable trailing stop",
            "di_partial_1r_enabled": "DI: close partial at 1R and move SL to entry",
            "di_partial_cost_atr_enabled": "Increase ATR distance so the 1R partial covers estimated costs",
            "partial_profit_enabled": "Enable partial profit-taking",
            "partial_stop_enabled": "Enable staged stop-loss",
            "timeout_enabled": "Enable maximum holding time",
            "r_step_trailing_enabled": "Enable R-step trailing",
            "atr_checkpoint_tp_extension_enabled": "Enable ATR-checkpoint target extension",
            "use_maker_entry": "Assume maker entry",
            "use_maker_exit": "Assume maker exit",
            "zero_cost_comparison": "Also calculate zero-cost comparison",
            "di_ladder_enabled": "Enable DI ladder / reversal-filter execution",
            "fvg_confirmation_enabled": "Require directional FVG confirmation before entry",
            "fvg_context_enabled": "Require the execution-timeframe FVG to overlap an active higher-timeframe FVG",
            "ema_cross_initial_phantom_enabled": "Initial entry + 1R phantom; enter from 2R when EMA gap widens versus previous checkpoint",
            "ema_cross_cost_cycle_enabled": "At 1R cover costs + break-even; repeat re-entry while EMA trend holds",
            "ema_cross_reentry_widening_enabled": "Re-enter only with a wider EMA gap; track phantom checkpoints otherwise",
            "ema_cross_entry_confirmation_enabled": "Wait for confirmation distance before EMA-cross entry",
            "ema_320_flip_signals": "Flip EMA 320 Signals (Long ↔ Short)",
        }.items():
            widget = self.trade.get(name) or self.account.get(name)
            if isinstance(widget, QCheckBox):
                widget.setText(text)

        # These suffixes describe the composition better than the old generic
        # "distance units" wording and do not affect stored native values.
        if hasattr(self.trade["stop_loss_multiple"], "setSuffix"):
            self.trade["stop_loss_multiple"].setSuffix(" ×")
        if hasattr(self.trade["position_sizing_stop_multiple"], "setSuffix"):
            self.trade["position_sizing_stop_multiple"].setSuffix(" ×")
        if hasattr(self.trade["ema_cross_stop_buffer_atr"], "setSuffix"):
            self.trade["ema_cross_stop_buffer_atr"].setSuffix(" × signal ATR")
        if hasattr(self.account["atr_multiplier"], "setSuffix"):
            self.account["atr_multiplier"].setSuffix(" × ATR")
        if hasattr(self.account["fvg_target_buffer_atr"], "setSuffix"):
            self.account["fvg_target_buffer_atr"].setSuffix(" × signal ATR")
        self.account["fvg_target_minimum_r"].setSuffix(" R")
        if hasattr(self.account["fvg_confirmation_minutes"], "setSuffix"):
            self.account["fvg_confirmation_minutes"].setSuffix(" min")
        if hasattr(self.account["ema_cross_entry_confirmation_r"], "setSuffix"):
            self.account["ema_cross_entry_confirmation_r"].setSuffix(" R")
        if hasattr(self.account["di_ladder_level_r"], "setSuffix"):
            self.account["di_ladder_level_r"].setSuffix(" R")
        if hasattr(self.account["di_reversal_target_r"], "setSuffix"):
            self.account["di_reversal_target_r"].setSuffix(" R")
        if hasattr(self.account["di_ladder_layers"], "setMaximumHeight"):
            self.account["di_ladder_layers"].setMaximumHeight(260)

    def _signal_strategy_mode(self) -> str:
        builder = getattr(self.window, "rule_builder", None)
        if builder is None:
            return "DI"
        return str(builder.direction_mode.currentData() or "DI").upper()

    def _ema_920_selected(self) -> bool:
        return self._signal_strategy_mode() == "EMA_9_20_PULLBACK"

    def refresh_visibility(self, *_args) -> None:
        ema_920 = self._ema_920_selected()
        fvg = self._signal_strategy_mode() in {"FAIR_VALUE_GAP", "FVG_SIX_FACTOR"}
        self.fvg_stop_method.setText(
            "Displacement Candle Boundary - Automatic"
            if self._signal_strategy_mode() == "FVG_SIX_FACTOR"
            else "FVG Box Boundary - Automatic"
        )
        fib = self._signal_strategy_mode() == "FIB_RETRACEMENT"
        for card in self.fib_stage_cards:
            card.setVisible(fib)
        self.ema320_candle_card.setVisible(self._signal_strategy_mode() == "EMA_320_CLOSE_CROSS")
        cross_mode = {
            "EMA_20_100_CROSS": "LONG",
            "EMA_20_100_CROSS_SHORT": "SHORT",
            "EMA_20_100_CROSS_BOTH": "BOTH",
        }.get(self.account["ema_920_trade_plan"].currentData())
        cross_plan = ema_920 and cross_mode is not None
        self.entry_card.set_row_visible("ema_920_trade_plan", ema_920)
        self.entry_card.set_row_visible("ema_320_flip_signals", self._signal_strategy_mode() == "EMA_320_CLOSE_CROSS")
        self.entry_card.set_row_visible("ema_320_exit_mode", self._signal_strategy_mode() == "EMA_320_CLOSE_CROSS")
        self.entry_card.set_row_visible("ema_cross_cost_cycle_enabled", cross_plan)
        initial_phantom = cross_plan and self.account["ema_cross_cost_cycle_enabled"].isChecked() and self.account["ema_cross_initial_phantom_enabled"].isChecked()
        self.entry_card.set_row_visible("ema_cross_initial_phantom_enabled", cross_plan and self.account["ema_cross_cost_cycle_enabled"].isChecked())
        self.account["ema_cross_entry_confirmation_enabled"].setEnabled(not initial_phantom)
        if initial_phantom and self.account["ema_cross_entry_confirmation_enabled"].isChecked():
            self.account["ema_cross_entry_confirmation_enabled"].setChecked(False)
        self.entry_card.set_row_visible("ema_cross_reentry_widening_enabled", cross_plan and self.account["ema_cross_cost_cycle_enabled"].isChecked())
        self.entry_card.set_row_visible("ema_cross_entry_confirmation_enabled", cross_plan)
        self.entry_card.set_row_visible(
            "ema_cross_entry_confirmation_r",
            cross_plan and self.account["ema_cross_entry_confirmation_enabled"].isChecked(),
        )
        self.entry_card.set_row_visible("fvg_confirmation_enabled", fvg)
        self.entry_card.set_row_visible("first_minute_confirmation", fvg)
        self.entry_card.set_row_visible("fvg_confirmation_note", fvg)
        self.entry_card.set_row_visible("fvg_structure_swing_strength", fvg)
        for field in ("fvg_min_clear_bars", "fvg_min_move_away_atr"):
            self.entry_card.set_row_visible(field, self._signal_strategy_mode() == "FVG_SIX_FACTOR")
        self.entry_card.set_row_visible(
            "fvg_confirmation_minutes",
            fvg and self.account["fvg_confirmation_enabled"].isChecked(),
        )
        self.ema_stop_method.setText(
            "EMA 100 at Signal Close — Automatic" if cross_plan else "EMA 9/20 Micro-Swing — Automatic"
        )
        self.ema_stop_buffer.setText("0.05 × ATR")
        self.stop_card.rows["ema_920_stop_buffer"][0].setText("Stop Buffer")
        target_method = {
            "LONG": "EMA 20/100 Bearish Cross — Next Candle Open",
            "SHORT": "EMA 20/100 Bullish Cross — Next Candle Open",
            "BOTH": "Opposite EMA 20/100 Cross — Next Candle Open",
        }.get(cross_mode, "EMA 9/20 Fixed 1R — Automatic")
        self.ema_target_method.setText(target_method)
        self.ema_target_value.setText(
            "Optional partial at sizing-R; runner exits on opposite cross"
            if cross_plan else "1.00 R"
        )
        mode = str(self.account["risk_mode"].currentData() or "ATR")
        structural_stop = mode == "SR_STRUCTURE"
        ladder_enabled = bool(self.account["di_ladder_enabled"].isChecked())
        ladder_mode = str(self.account["di_ladder_mode"].currentData() or "PRICE_LEVELS")
        reversal_mode = ladder_mode == "DI_REVERSAL"
        price_level_mode = ladder_mode == "PRICE_LEVELS"
        self.ladder_card.set_row_visible("di_ladder_mode", ladder_enabled)
        self.ladder_card.set_row_visible(
            "di_reversal_target_r", ladder_enabled and reversal_mode
        )
        self.ladder_card.set_row_visible(
            "di_ladder_level_r", ladder_enabled and price_level_mode
        )
        self.ladder_card.set_row_visible(
            "di_ladder_layers", ladder_enabled and price_level_mode
        )
        ladder_button = getattr(self.window, "ladder_rule_open_button", None)
        if ladder_button is not None:
            ladder_button.setVisible(ladder_enabled and price_level_mode)

        ema_stop_fields = (
            "ema_920_stop_method", "ema_920_stop_confirmation",
            "ema_920_stop_lookback", "ema_920_stop_buffer", "ema_920_stop_maximum",
        )
        for name in ema_stop_fields:
            self.stop_card.set_row_visible(name, ema_920 and not cross_plan)
        self.stop_card.set_row_visible("ema_920_stop_method", ema_920)
        self.stop_card.set_row_visible("fvg_stop_method", fvg)
        self.stop_card.set_row_visible("fvg_stop_buffer", fvg)
        self.stop_card.set_row_visible("fib_stop_method", fib)
        self.stop_card.set_row_visible("fib_stop_buffer_atr", fib)
        for name in ("ema_920_stop_confirmation", "ema_920_stop_lookback", "ema_920_stop_maximum"):
            self.stop_card.set_row_visible(name, ema_920 and not cross_plan)
        if ema_920 or fvg or fib:
            for name in (
                "risk_mode", "atr_multiplier", "percent_r", "fixed_r",
                "sr_stop_timeframe_minutes", "sr_stop_buffer_atr",
                "sr_stop_maximum_atr", "sr_stop_no_level_policy", "stop_loss_multiple",
            ):
                self.stop_card.set_row_visible(name, False)
            self.stop_card.set_row_visible(
                "position_sizing_stop_override_enabled", cross_plan
            )
            self.stop_card.set_row_visible(
                "position_sizing_stop_multiple",
                cross_plan
                and self.trade["position_sizing_stop_override_enabled"].isChecked(),
            )
            self.stop_card.set_row_visible("ema_cross_stop_buffer_atr", cross_plan)
            self.stop_card.set_row_visible("ema_cross_stop_multiplier", cross_plan)
        else:
            self.stop_card.set_row_visible("risk_mode", True)
            self.stop_card.set_row_visible("atr_multiplier", mode == "ATR")
            self.stop_card.set_row_visible("percent_r", mode == "PERCENT")
            self.stop_card.set_row_visible("fixed_r", mode == "FIXED")
            for name in (
                "sr_stop_timeframe_minutes", "sr_stop_buffer_atr",
                "sr_stop_maximum_atr", "sr_stop_no_level_policy",
            ):
                self.stop_card.set_row_visible(name, structural_stop)
            # Structural mode owns the full initial stop distance. The legacy stop
            # multiplier remains preserved in the profile but is not a user-facing
            # input for the final structural stop.
            self.stop_card.set_row_visible("stop_loss_multiple", not structural_stop)
            sizing_override_available = not structural_stop
            self.stop_card.set_row_visible(
                "position_sizing_stop_override_enabled",
                sizing_override_available,
            )
            self.stop_card.set_row_visible(
                "position_sizing_stop_multiple",
                sizing_override_available
                and self.trade["position_sizing_stop_override_enabled"].isChecked(),
            )
            self.stop_card.set_row_visible("ema_cross_stop_buffer_atr", False)
            self.stop_card.set_row_visible("ema_cross_stop_multiplier", False)

        sizing_override_active = bool(
            self.trade["position_sizing_stop_override_enabled"].isChecked()
            and (
                cross_plan
                or (not ema_920 and not fvg and not fib and not structural_stop)
            )
        )
        if (
            ((ema_920 and not cross_plan) or fvg or fib or structural_stop)
            and self.trade["position_sizing_stop_override_enabled"].isChecked()
        ):
            self.trade["position_sizing_stop_override_enabled"].setChecked(False)
            sizing_override_active = False

        incompatible_toggles = (
            "break_even_enabled",
            "trailing_enabled",
            "partial_profit_enabled",
            "partial_stop_enabled",
            "r_step_trailing_enabled",
            "atr_checkpoint_tp_extension_enabled",
        )
        for name in incompatible_toggles:
            widget = self.trade[name]
            cross_partial_compatible = cross_plan and name == "partial_profit_enabled"
            if sizing_override_active and widget.isChecked() and not cross_partial_compatible:
                widget.setChecked(False)
            widget.setEnabled(not sizing_override_active or cross_partial_compatible)

        if cross_plan:
            # EMA-cross supports one partial take-profit runner. Staged stops and
            # target-extension modes remain incompatible.
            self.trade["partial_profit_enabled"].setEnabled(True)
            for name in ("partial_stop_enabled", "r_step_trailing_enabled", "atr_checkpoint_tp_extension_enabled"):
                widget = self.trade[name]
                if widget.isChecked():
                    widget.setChecked(False)
                widget.setEnabled(False)

        target_mode = str(self.account["sr_take_profit_mode"].currentData() or "FIXED_R")
        if sizing_override_active and target_mode != "FIXED_R":
            fixed_index = self.account["sr_take_profit_mode"].findData("FIXED_R")
            self.account["sr_take_profit_mode"].setCurrentIndex(fixed_index)
            target_mode = "FIXED_R"
        self.account["sr_take_profit_mode"].setEnabled(not sizing_override_active)
        target_label = self.target_card.rows["reward_risk_ratio"][0]
        if target_label is not None:
            target_label.setText(
                "Profit Target (Sizing-R)"
                if sizing_override_active
                else "Base Profit Target"
            )
        sr_target = target_mode in ("SR_CAPPED_R", "SR_LEVEL")
        for name in ("ema_920_target_method", "ema_920_target_value"):
            self.target_card.set_row_visible(name, ema_920)
        self.target_card.set_row_visible("fvg_target_method", fvg)
        self.target_card.set_row_visible("fvg_target_mode", fvg)
        self.target_card.set_row_visible("fvg_reject_ema100_in_tp", fvg)
        htf_fvg = fvg and self.account["fvg_target_mode"].currentData() == "HTF_OPPOSING_FVG"
        for name in ("fvg_target_timeframe_minutes", "fvg_target_minimum_r", "fvg_target_no_level_policy", "fvg_target_note"):
            self.target_card.set_row_visible(name, htf_fvg)
        self.fvg_target_method.setText(
            "Nearest opposing HTF FVG near edge — fixed at entry" if htf_fvg
            else "Configured R before FVG move high / low"
        )
        self.target_card.set_row_visible("fvg_target_buffer_atr", fvg)
        self.entry_card.set_row_visible("fib_entry_50_618_only", fib)
        fib_target_mode = str(self.account["fib_target_mode"].currentData() or "IMPULSE_EXTREME")
        self.target_card.set_row_visible("fib_target_method", fib)
        self.target_card.set_row_visible("fib_fixed_target_r", fib and fib_target_mode == "FIXED_R")
        self.target_card.set_row_visible("fib_target_buffer_atr", fib and fib_target_mode != "FIXED_R")
        self.target_card.set_row_visible("fib_minimum_target_r", fib and fib_target_mode != "FIXED_R")
        if ema_920:
            self.target_card.set_row_visible("sr_take_profit_mode", False)
            self.target_card.set_row_visible("reward_risk_ratio", False)
            for name in (                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",
                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",
                "sr_take_profit_no_level_policy",
            ):
                self.target_card.set_row_visible(name, False)
            self.sr_dependency_note.setVisible(False)
        elif fvg:
            self.target_card.set_row_visible("sr_take_profit_mode", False)
            self.target_card.set_row_visible("reward_risk_ratio", not htf_fvg or self.account["fvg_target_no_level_policy"].currentData() == "USE_FIXED_TP")
            if target_label is not None:
                target_label.setText("FVG Profit Target")
            for name in (
                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",
                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",
                "sr_take_profit_no_level_policy",
            ):
                self.target_card.set_row_visible(name, False)
            self.sr_dependency_note.setVisible(False)
        elif fib:
            self.target_card.set_row_visible("sr_take_profit_mode", False)
            self.target_card.set_row_visible("reward_risk_ratio", False)
            for name in (
                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",
                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",
                "sr_take_profit_no_level_policy",
            ):
                self.target_card.set_row_visible(name, False)
            self.sr_dependency_note.setVisible(False)
        else:
            self.target_card.set_row_visible("sr_take_profit_mode", True)
            self.target_card.set_row_visible("reward_risk_ratio", True)
            for name in (
                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",
                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",
                "sr_take_profit_no_level_policy",
            ):
                self.target_card.set_row_visible(name, sr_target)
            self.sr_dependency_note.setVisible(structural_stop or sr_target)

        toggles = {
            "break_even_enabled": ("break_even_activation_r", "break_even_offset_r"),
            "trailing_enabled": ("trailing_activation_r", "trailing_distance_r"),
            "partial_profit_enabled": ("tp1_r", "tp1_close_pct", "tp2_r"),
            "partial_stop_enabled": ("sl1_r", "sl1_close_pct", "sl2_r"),
            "timeout_enabled": ("timeout_minutes",),
        }
        for controller, fields in toggles.items():
            enabled = self.trade[controller].isChecked()
            for name in fields:
                self.management_card.set_row_visible(name, enabled)
        if cross_plan and self.trade["partial_profit_enabled"].isChecked():
            # There is no fixed final target in EMA-cross mode; TP1 takes a
            # partial and the rest runs to the opposite crossover.
            self.management_card.set_row_visible("tp2_r", False)

        advanced = {
            "r_step_trailing_enabled": (
                "r_step_activation_r", "r_step_distance_r", "r_step_size_r",
                "r_step_maximum_r", "r_step_activation_close_pct",
            ),
            "atr_checkpoint_tp_extension_enabled": (
                "atr_checkpoint_di_spread_minimum", "atr_checkpoint_bb_width_minimum",
                "atr_checkpoint_profit_lock_start", "atr_checkpoint_profit_lock_distance",
            ),
        }
        for controller, fields in advanced.items():
            enabled = self.trade[controller].isChecked()
            for name in fields:
                self.advanced_card.set_row_visible(name, enabled)
        cost_cycle = cross_plan and self.account["ema_cross_cost_cycle_enabled"].isChecked()
        self.trade["timeout_enabled"].setEnabled(not cost_cycle)
        for name in ("break_even_enabled", "trailing_enabled", "partial_profit_enabled", "timeout_enabled"):
            if cost_cycle:
                self.trade[name].setEnabled(False)
                for field in toggles[name]:
                    self.management_card.set_row_visible(field, False)
        di_mode = self._signal_strategy_mode() == "DI"
        self.trade["position_sizing_stop_override_enabled"].setEnabled(True)
        di_partial = di_mode and self.trade["di_partial_1r_enabled"].isChecked()
        self.management_card.set_row_visible("di_partial_1r_enabled", di_mode)
        self.management_card.set_row_visible("di_partial_1r_close_pct", di_partial)
        self.management_card.set_row_visible("di_partial_cost_atr_enabled", di_partial)
        atr_risk = str(self.account["risk_mode"].currentData()) == "ATR"
        self.trade["di_partial_cost_atr_enabled"].setEnabled(atr_risk)
        if di_partial and not atr_risk and self.trade["di_partial_cost_atr_enabled"].isChecked():
            self.trade["di_partial_cost_atr_enabled"].setChecked(False)
        if di_partial:
            self.account["sr_take_profit_mode"].setCurrentIndex(self.account["sr_take_profit_mode"].findData("FIXED_R"))
            self.account["sr_take_profit_mode"].setEnabled(False)
            for name in incompatible_toggles:
                if self.trade[name].isChecked():
                    self.trade[name].setChecked(False)
                self.trade[name].setEnabled(False)
                for field in toggles.get(name, advanced.get(name, ())):
                    (self.advanced_card if name in advanced else self.management_card).set_row_visible(field, False)
            if self.trade["di_partial_cost_atr_enabled"].isChecked():
                if self.trade["position_sizing_stop_override_enabled"].isChecked():
                    self.trade["position_sizing_stop_override_enabled"].setChecked(False)
                self.trade["position_sizing_stop_override_enabled"].setEnabled(False)
        sp_cost = self._signal_strategy_mode() == "SNEAKY_PIVOT" and self.account["sp_cost_cover_enabled"].isChecked()
        if sp_cost:
            for name in incompatible_toggles:
                if self.trade[name].isChecked():
                    self.trade[name].setChecked(False)
                self.trade[name].setEnabled(False)
                for field in toggles.get(name, advanced.get(name, ())):
                    (self.advanced_card if name in advanced else self.management_card).set_row_visible(field, False)
            self.trade["position_sizing_stop_override_enabled"].setChecked(False)
            self.trade["position_sizing_stop_override_enabled"].setEnabled(False)
        automatic_reversal = self._signal_strategy_mode() == "EMA_100_300_REVERSAL"
        ny_range = self._signal_strategy_mode() == "NY_OPENING_RANGE_REVERSAL"
        imbalance = self._signal_strategy_mode() == "IMBALANCE_ORIGIN_RETEST"
        liquidity = self._signal_strategy_mode() == "LIQUIDITY_SWEEP_RETEST"
        confluence = self._signal_strategy_mode() == "TJR_CONFLUENCE"
        sneaky = self._signal_strategy_mode() == "SNEAKY_PIVOT"
        photon = self._signal_strategy_mode() == "PHOTON_4H_TREND"
        supply_demand = photon or self._signal_strategy_mode() in {"NY_OPENING_RANGE_REVERSAL","IMBALANCE_ORIGIN_RETEST", "SUPPLY_DEMAND_RETEST","LIQUIDITY_SWEEP_RETEST","SNEAKY_PIVOT","TJR_CONFLUENCE"}
        zone_reversal = photon and self.account["photon_zone_reversal"].isChecked()
        for name in ("photon_confirmation_minutes", "photon_retest_minutes", "photon_zone_reversal"):
            self.sd_card.set_row_visible(name, photon)
        self.sd_card.set_row_visible("photon_exit_on_15m_change", zone_reversal)
        for name in ("photon_target_4h", "photon_flexible_entries"):
            self.sd_card.set_row_visible(name, photon and not zone_reversal)
        self.sd_card.setTitle("Photon — Daily / 4H zone reversal" if zone_reversal else "Liquidity sweep — trend + zone retest" if liquidity else "Supply & demand retest")
        for name in ("ls_equal_tolerance_atr","ls_displacement_atr","ls_base_bars","ls_max_wait_bars"):
            self.sd_card.set_row_visible(name,liquidity or (imbalance and name in {"ls_displacement_atr","ls_max_wait_bars"}))
        self.sd_card.set_row_visible("sp_cost_cover_close_pct", sp_cost)
        for name in ("tc_require_live_confirmations","tc_min_sweep_atr","tc_require_structure","tc_require_ifvg","tc_require_equilibrium","tc_displacement_atr",
                     "tc_max_wait_bars","tc_fvg_lookback","tc_min_reversal_body_percent","tc_target_r"):
            self.sd_card.set_row_visible(name,confluence)
        self.sd_card.set_row_visible("io_entry_model",imbalance)
        self.sd_card.set_row_visible("io_context_minutes",imbalance and self.account["io_entry_model"].currentData()=="INDUCEMENT_CONFIRMATION")
        if imbalance:self.sd_card.setTitle("Imbalance origin retest")
        if confluence:self.sd_card.setTitle("Confluence - sweep, structure and FVG")
        if sneaky:self.sd_card.setTitle("Sneaky Pivot — all day")
        self.sd_card.set_row_visible("sd_minimum_r",not sneaky or self.account["sp_minimum_r_enabled"].isChecked())
        self.sd_card.set_row_visible("sd_stop_buffer_atr",not ny_range)
        self.sd_card.rows["sd_stop_buffer_atr"][0].setText("Stop buffer beyond sweep (ATR)" if confluence else "Stop buffer beyond swing (ATR)" if sneaky else "Stop buffer beyond zone (ATR)")
        for name in ("sp_minimum_r_enabled","sp_recent_swings_enabled","sp_require_level_reclaim","sp_cost_cover_enabled","sp_level_tolerance_atr","sp_body_atr","sp_min_body_percent","sp_confirmation_bars","sp_hold_minutes"):
            self.sd_card.set_row_visible(name,sneaky)
        self.sd_card.set_row_visible("sd_swing_strength",not ny_range)
        if photon:
            self.sd_card.setTitle("Photon — 4H trend / 1m confirmation")
            self.sd_card.set_row_visible("sd_swing_strength",False)
            self.sd_card.rows["sd_stop_buffer_atr"][0].setText("Stop buffer beyond 1m reaction extreme (ATR)")
        self.sd_card.set_row_visible("ny_range_target_r",ny_range)
        policy=self.account["ny_range_overshoot_policy"].currentData()
        self.sd_card.set_row_visible("ny_range_overshoot_policy",ny_range)
        self.sd_card.set_row_visible("ny_range_max_extension_pct",ny_range and policy!="DEFAULT")
        self.sd_card.set_row_visible("ny_range_sr_buffer_atr",ny_range and policy=="SR_STOP")
        if ny_range:
            self.sd_card.setTitle("New York opening 4h range reversal")
            for name in ("sd_swing_strength","sd_minimum_r","sd_stop_buffer_atr"):
                self.sd_card.set_row_visible(name,False)
        self.sd_card.setVisible(supply_demand)
        self.ema_gap_card.setVisible(automatic_reversal)
        for card in (self.entry_card, self.stop_card, self.target_card, self.ladder_card,
                     self.management_card, self.advanced_card):
            card.setVisible(not automatic_reversal and not supply_demand)
        self.refresh_summary_from_widgets()

    @staticmethod
    def _timeframe_description(minutes: int, *, primary: bool = False) -> str:
        minutes = int(minutes)
        if primary and minutes == -1:
            return "primary S/R context"
        if minutes == 0:
            return "strategy timeframe"
        if minutes % 1440 == 0:
            return f"{minutes // 1440}d"
        if minutes % 60 == 0:
            return f"{minutes // 60}h"
        return f"{minutes}m"

    @classmethod
    def _distance_description(cls, execution) -> str:
        mode = str(execution.risk_mode).upper()
        if mode == "ATR":
            return f"{execution.atr_multiplier:g}× ATR distance unit"
        if mode == "PERCENT":
            return f"{execution.percent_r * 100:g}% of price distance unit"
        if mode == "SR_STRUCTURE":
            timeframe = cls._timeframe_description(execution.sr_stop_timeframe_minutes)
            return (
                f"structural S/R on {timeframe}, {execution.sr_stop_buffer_atr:g}× ATR "
                f"beyond the zone, maximum {execution.sr_stop_maximum_atr:g}× ATR"
            )
        return f"{execution.fixed_r:g} fixed-price distance unit"

    @staticmethod
    def _management_description(base) -> str:
        if getattr(base, "di_partial_1r_enabled", False):
            return f"DI: close {base.di_partial_1r_close_pct:g}% at 1R, then SL to entry" + ("; increase ATR only as needed to cover estimated costs" if base.di_partial_cost_atr_enabled else "")
        enabled = []
        if base.break_even_enabled:
            enabled.append("break-even")
        if base.trailing_enabled:
            enabled.append("trailing")
        if base.partial_profit_enabled:
            enabled.append("partial profit")
        if base.partial_stop_enabled:
            enabled.append("staged stop")
        if base.timeout_enabled:
            enabled.append("timeout")
        if base.r_step_trailing_enabled:
            enabled.append("R-step trailing")
        if base.atr_checkpoint_tp_extension_enabled:
            enabled.append("ATR-checkpoint extension")
        return ", ".join(enabled) if enabled else "no optional trade management"

    def _apply_imbalance_entry_timeframe(self, *_args):
        if self._signal_strategy_mode() != "IMBALANCE_ORIGIN_RETEST" or self.account["io_entry_model"].currentData() != "INDUCEMENT_CONFIRMATION":
            return
        from .v2_main_window import timeframe_minutes
        if timeframe_minutes(self.window.strategy_tf.currentData()) >= self.account["io_context_minutes"].value():
            self.window.strategy_tf.setCurrentIndex(self.window.strategy_tf.findData("15m"))

    def update_summary(self, execution, base) -> None:
        if self._signal_strategy_mode() == "PHOTON_4H_TREND":
            if execution.photon_zone_reversal:
                exit_note = "Close at the next 1m open after an opposing 15m trend change." if execution.photon_exit_on_15m_change else "Exit at SL or TP."
                self.summary_label.setText(f"Photon zone reversal: actual 1m candles. Touch Daily / 4H demand in 4H discount or supply in premium; wait for a fresh 15m trend change, a pullback into 15m value, then a fresh 1m internal CHoCH. Enter only on a later retest of the last opposing 1m candle before that change. SL beyond the nested 15m zone, or the touch excursion extreme, plus {execution.sd_stop_buffer_atr:g} ATR. Freeze TP at the 4H midpoint; minimum {execution.sd_minimum_r:g}R is checked again at the fill. {exit_note} Context expires after {execution.photon_confirmation_minutes} minutes; entry retest expires after {execution.photon_retest_minutes} minutes. Simulated backtest trades.")
                return
            target="4H" if execution.photon_target_4h else "15m"
            mode=("Flexible candidates: existing 15m swing alignment or aligned internal structure is accepted; value mismatches are saved for manual review. A later 1m CHoCH and origin retest remain required." if execution.photon_flexible_entries else "Strict: 4H value reaction, fresh aligned 15m confirmation, later pullback within both value halves, then 1m CHoCH and origin retest.")
            self.summary_label.setText(f"Photon: actual 1m candles; only with the 4H swing. {mode} SL beyond reaction + {execution.sd_stop_buffer_atr:g} ATR; frozen {target} swing target; minimum {execution.sd_minimum_r:g}R. Context expiry {execution.photon_confirmation_minutes} minutes; retest {execution.photon_retest_minutes}. Backtest fills are simulated; use replay to confirm or skip manually. No partials, trailing or counter-4H trades.")
            return
        if self._signal_strategy_mode() == "NY_OPENING_RANGE_REVERSAL":
            policy=execution.ny_range_overshoot_policy
            oversized=("Default: keep the breakout stop regardless of target extension." if policy=="DEFAULT" else
                f"Target limit: {execution.ny_range_max_extension_pct:g}% of 4h height beyond the opposite boundary; " +
                ("ignore oversized setups." if policy=="SKIP" else f"try a nearer confirmed S/R boundary with {execution.ny_range_sr_buffer_atr:g} entry ATR buffer; skip if absent/broken, not nearer, or target still exceeds the limit. Uses the configured S/R context."))
            self.summary_label.setText(f"New York range reversal: 5m candles; first four elapsed hours from America/New_York midnight. Wait for all 48 candles to close before using the range. Close above high then strictly inside = short; below low then inside = long. Wicks alone cannot arm. Enter next open on the same NY day and still inside range. Exact stop at the full breakout excursion extreme (including re-entry candle); TP {execution.ny_range_target_r:g}R from actual fill. Fresh excursions can trade again that day; existing portfolio limits apply. Missing opening candles invalidate that day's range; later gaps reset the excursion. No inherited supply/demand minimum-R filter. Open trades retain SL/TP overnight. {oversized}")
            return
        if self._signal_strategy_mode() == "IMBALANCE_ORIGIN_RETEST" and execution.io_entry_model == "INDUCEMENT_CONFIRMATION":
            self.summary_label.setText(f"Inducement confirmation: completed {execution.io_context_minutes}m zones, entry candles on the strategy timeframe (must divide the zone timeframe). Confirmed HH/HL or LH/LL trend; displacement >= {execution.ls_displacement_atr:g} HTF ATR closes through an unbroken swing and leaves a gap. Skip shallow origins above/below an open deeper origin. Full fill into origin; a sweep must close back inside. Then confirmed lower-timeframe swing break, later retest of its opposing origin and directional rejection; enter next open. SL beyond reversal extreme +{execution.sd_stop_buffer_atr:g} entry ATR; TP known displacement/formation extreme, frozen before pullback; minimum {execution.sd_minimum_r:g}R. Expire {execution.ls_max_wait_bars} zone candles after formation. Research interpretation, not order-book evidence.")
            return
        if self._signal_strategy_mode() == "IMBALANCE_ORIGIN_RETEST":
            self.summary_label.setText(f"Origin retest: displacement body >= {execution.ls_displacement_atr:g} ATR breaking the previous {2*execution.sd_swing_strength+1} bars; three-candle gap. Full fill into opposing/doji origin candle and directional close away. Enter next open; SL beyond origin +{execution.sd_stop_buffer_atr:g} ATR; target frozen impulse extreme; minimum {execution.sd_minimum_r:g}R. Expire after {execution.ls_max_wait_bars} candles. Wick through origin cancels. JeaFx-inspired research preset.")
            return
        if self._signal_strategy_mode() == "SNEAKY_PIVOT":
            self.summary_label.setText(f"All-day 15m Sneaky Pivot; test the previous complete UTC-day low/high{' plus the latest recent confirmed swings' if execution.sp_recent_swings_enabled else ''}. Initial body ≥{execution.sp_min_body_percent:g}% of range and {execution.sp_body_atr:g} ATR; wick must touch the selected level within {execution.sp_level_tolerance_atr:g} ATR. First reversal within {execution.sp_confirmation_bars} candles{' closing back across the tested level' if execution.sp_require_level_reclaim else ''}; break its high/low during the next candle using 1m data. SL {execution.sd_stop_buffer_atr:g} ATR beyond the older confirmed swing low/high; skip if unavailable or breached. TP opposite prior-day boundary. Hold cap {execution.sp_hold_minutes} minutes from setup. One open trade; no session restriction. Cost-cover partial {str(execution.sp_cost_cover_close_pct) + '% at 1R, then SL to entry; widen swing stop only as needed' if execution.sp_cost_cover_enabled else 'off'}. Minimum-R filter {str(execution.sd_minimum_r) + 'R' if execution.sp_minimum_r_enabled else 'off'}.")
            return
        if self._signal_strategy_mode() == "TJR_CONFLUENCE":
            self.summary_label.setText(
                f"Confluence research preset: sweep and reclaim a confirmed swing; {execution.sd_swing_strength} candles each side. "
                f"Minimum sweep {execution.tc_min_sweep_atr:g} ATR; cancel failed confirmations {'on' if execution.tc_require_live_confirmations else 'off'}. "
                f"Structure close {'required' if execution.tc_require_structure else 'optional'}; opposing FVG inversion {'required' if execution.tc_require_ifvg else 'optional'}. "
                f"New directional FVG with middle body >= {execution.tc_displacement_atr:g} ATR; discount/premium overlap {'required' if execution.tc_require_equilibrium else 'optional'}. "
                f"Later directional retest candle body >= {execution.tc_min_reversal_body_percent:g}% of range; enter next open, recheck equilibrium and SL geometry. "
                f"SL beyond sweep +{execution.sd_stop_buffer_atr:g} ATR frozen at sweep; TP {execution.tc_target_r:g}R; minimum {execution.sd_minimum_r:g}R. "
                f"Expire after {execution.tc_max_wait_bars} candles from sweep; lookback {execution.tc_fvg_lookback} candles. No session restriction. "
                "Mechanical interpretation of the five concepts; not the creator's complete discretionary system.")
            return
        if self._signal_strategy_mode() == "LIQUIDITY_SWEEP_RETEST":
            self.summary_label.setText(
                f"Liquidity sweep: confirmed HH/HL trend for longs, LH/LL for shorts; {execution.sd_swing_strength} swing candles each side. "
                f"Two equal lows/highs within {execution.ls_equal_tolerance_atr:g} × ATR; sweep and reclaim against the trend. "
                f"Then a directional body ≥ {execution.ls_displacement_atr:g} × ATR closing beyond up to {execution.ls_base_bars} preceding base candles. "
                f"Retest that zone with a directional candle, then enter at next open. Wait at most {execution.ls_max_wait_bars} candles per stage. "
                f"SL beyond zone + {execution.sd_stop_buffer_atr:g} × ATR; fixed TP at the pre-sweep trend extreme; minimum {execution.sd_minimum_r:g}R. "
                "One attempt per swept pool/zone; consolidation alone cannot enter."
            )
            return
        if self._signal_strategy_mode() == "SUPPLY_DEMAND_RETEST":
            self.summary_label.setText(
                f"Supply & demand — 1h swing retest. Confirm swings with {execution.sd_swing_strength} completed candles on each side. "
                "Use each swing candle's full high/low range as its zone. Wait for a subsequent touch, close away, then a later retest with a directional candle. "
                "Entry: next open. SL: beyond the entry zone. TP: opposing confirmed swing extreme, fixed at entry. "
                f"Stop buffer: {execution.sd_stop_buffer_atr:g} × ATR; minimum reward/risk: {execution.sd_minimum_r:g}R. "
                "Only the latest zone per side is considered. Broken zones and missing hours reset setups. "
                "Each zone has one qualifying retest attempt; skipped attempts are not retried. Optional trade management does not apply."
            )
            return
        if self._signal_strategy_mode() == "EMA_100_300_REVERSAL":
            self.summary_label.setText(
                f"EMA 100 (low) / EMA 300 (high) — automatic {execution.ema_reversal_target_r:g}R plan. "
                "Short: EMA 300 > EMA 100, green → red → red → red; enter above both EMAs. "
                "Long: EMA 300 < EMA 100, red → green → green → green; enter below both EMAs. "
                f"Minimum EMA gap: {execution.ema_reversal_min_gap_atr:g} × ATR (0 = off). "
                f"Minimum entry distance from EMA 300: {execution.ema_reversal_min_entry_ema300_atr:g} × ATR (0 = off). "
                "Entry: next candle open. TP: last completed candle's EMA 100 (low), fixed at entry. "
                f"SL distance: entry-to-TP distance ÷ {execution.ema_reversal_target_r:g}, in the opposite direction. Wrong-side targets are skipped. "
                f"Account risk: {execution.risk_per_leg * base.risk_multiplier:.2%} per trade before costs. "
                "Stop multipliers, separate sizing stops and optional trade management do not apply."
            )
            return
        effective_risk = float(execution.risk_per_leg) * float(base.risk_multiplier)
        risk_dollars = float(execution.initial_equity) * effective_risk
        stop_mult = float(base.sl2_r if base.partial_stop_enabled else base.stop_loss_multiple)
        ema_920 = self._ema_920_selected()
        fvg = self._signal_strategy_mode() in {"FAIR_VALUE_GAP", "FVG_SIX_FACTOR"}
        fib = self._signal_strategy_mode() == "FIB_RETRACEMENT"
        cross_mode = {
            "EMA_20_100_CROSS": "LONG",
            "EMA_20_100_CROSS_SHORT": "SHORT",
            "EMA_20_100_CROSS_BOTH": "BOTH",
        }.get(execution.ema_920_trade_plan)
        cross_plan = bool(ema_920 and cross_mode is not None)
        sizing_override = bool(
            base.position_sizing_stop_override_enabled
            and (
                cross_plan
                or (
                    not ema_920 and not fvg and not fib
                    and str(execution.risk_mode).upper() != "SR_STRUCTURE"
                )
            )
        )
        sizing_stop_mult = (
            float(base.position_sizing_stop_multiple)
            if sizing_override
            else stop_mult
        )
        if base.partial_stop_enabled:
            first_fraction = float(base.sl1_close_pct) / 100.0
            gross_stop_mult = (
                first_fraction * float(base.sl1_r)
                + (1.0 - first_fraction) * float(base.sl2_r)
            )
        else:
            gross_stop_mult = stop_mult
        gross_stop_exposure = (
            effective_risk * gross_stop_mult / sizing_stop_mult
            if sizing_stop_mult > 0
            else effective_risk
        )

        timing = str(getattr(execution, "entry_timing_mode", "SIGNAL_CLOSE")).upper()
        ema_cross_confirmation = bool(
            cross_plan
            and getattr(execution, "ema_cross_entry_confirmation_enabled", False)
        )
        entry_fill = (
            (
                f"EMA cross arms setup; wait for "
                f"{float(execution.ema_cross_entry_confirmation_r):g}R confirmation "
                "from the original hypothetical next-open entry"
            )
            if ema_cross_confirmation
            else (
                f"First {int(execution.fvg_confirmation_minutes)}m candle only — "
                "long close > open / short close < open; fill at confirmation close, "
                "otherwise skip (no waiting)"
            )
            if fvg and execution.fvg_confirmation_enabled
            else "Next Candle Open — Causal"
            if timing == "NEXT_CANDLE_OPEN"
            else "Signal Candle Close — Legacy"
        )

        if ema_920:
            cross_target = {
                "EMA_20_100_CROSS": (
                    "long on EMA 20 crossing above EMA 100; exit at the next candle open after "
                    "EMA 20 crosses below EMA 100 (protective EMA 100 stop stays active)"
                ),
                "EMA_20_100_CROSS_SHORT": (
                    "short on EMA 20 crossing below EMA 100; exit at the next candle open after "
                    "EMA 20 crosses above EMA 100 (protective EMA 100 stop stays active)"
                ),
                "EMA_20_100_CROSS_BOTH": (
                    "trade both directions: bullish cross opens long and bearish cross opens short; "
                    "the opposite cross exits/reverses at the next candle open "
                    "(protective EMA 100 stop stays active)"
                ),
            }.get(execution.ema_920_trade_plan)
            target = cross_target or "automatic fixed 1.00R target"
            if cross_target and ema_cross_confirmation:
                confirm_r = float(execution.ema_cross_entry_confirmation_r)
                target = (
                    f"EMA 20/100 crossover arms the {cross_mode.lower()} setup; "
                    f"enter only after price travels {confirm_r:g}R in the crossover direction "
                    "from the original hypothetical next-open entry; "
                    + target
                )
            if cross_target and base.partial_profit_enabled:
                target += (
                    f"; take {base.tp1_close_pct:g}% at {base.tp1_r:g} sizing-R, "
                    "then leave the remainder to the opposite crossover"
                )
        elif fvg:
            target = (
                f"nearest opposing {self._timeframe_description(execution.fvg_target_timeframe_minutes)} FVG; "
                f"TP {execution.fvg_target_buffer_atr:g}× signal ATR before its near edge; "
                f"minimum {execution.fvg_target_minimum_r:g}R; fixed at entry; "
                + ("skip if none" if execution.fvg_target_no_level_policy == "REJECT_TRADE" else "fixed-R swing-room fallback if none")
            ) if execution.fvg_target_mode == "HTF_OPPOSING_FVG" else (
                f"configured {base.reward_risk_ratio:g}R target; it must fit "
                f"{execution.fvg_target_buffer_atr:g}× signal ATR before the FVG move high "
                "for long or move low for short, otherwise reject"
            )
        elif fib:
            fib_target_mode = str(execution.fib_target_mode).upper()
            room_gate = (
                f"prior impulse extreme room is measured with a {execution.fib_target_buffer_atr:g}× "
                f"signal ATR buffer and must provide at least {execution.fib_minimum_target_r:g}R"
            )
            if fib_target_mode == "FIXED_R":
                target = (
                    f"fixed {execution.fib_fixed_target_r:g}R actual take-profit from the actual Fib stop; "
                    "prior impulse room does not veto this target"
                )
            else:
                target = (
                    "prior impulse extreme (0.0 Fib): previous swing high for long or previous swing low "
                    f"for short; {room_gate}"
                )
            if execution.fib_entry_50_618_only:
                target += "; actual entries must be strictly inside the 50%–61.8% retracement zone"
        else:
            target_mode = str(execution.sr_take_profit_mode).upper()
            if target_mode == "SR_CAPPED_R":
                timeframe = self._timeframe_description(
                    execution.sr_take_profit_timeframe_minutes, primary=True
                )
                target = (
                    f"S/R-constrained target from {timeframe} (base {base.reward_risk_ratio:g}R, "
                    f"minimum {execution.sr_take_profit_minimum_r:g}R, "
                    f"cap {execution.sr_take_profit_maximum_r:g}R)"
                )
            elif target_mode == "SR_LEVEL":
                timeframe = self._timeframe_description(
                    execution.sr_take_profit_timeframe_minutes, primary=True
                )
                target = (
                    f"structural S/R target from {timeframe} "
                    f"(minimum {execution.sr_take_profit_minimum_r:g}R, "
                    f"safety cap {execution.sr_take_profit_maximum_r:g}R)"
                )
            else:
                target = (
                    f"fixed {base.reward_risk_ratio:g} sizing-R target"
                    if sizing_override
                    else f"fixed {base.reward_risk_ratio:g}R target"
                )

        if fvg and execution.fvg_reject_ema100_in_tp:
            target += "; reject EMA 100 inside entry-to-TP box (completed strategy candle)"
        multiplier = (
            f" · risk multiplier {base.risk_multiplier:g}×"
            if abs(float(base.risk_multiplier) - 1.0) > 1e-12
            else ""
        )
        if ema_920:
            cross_stop = {
                "EMA_20_100_CROSS": (
                    f"Stop: base stop is signal-candle EMA 100 minus {base.ema_cross_stop_buffer_atr:g}× signal ATR; "
                    f"actual stop distance = {base.ema_cross_stop_multiplier:g}× base distance, "
                    + (
                        f"while quantity is sized from a separate "
                        f"{base.position_sizing_stop_multiple:g}× base-distance reference. "
                        if sizing_override
                        else "while quantity remains sized from the base stop. "
                    )
                ),
                "EMA_20_100_CROSS_SHORT": (
                    f"Stop: base stop is signal-candle EMA 100 plus {base.ema_cross_stop_buffer_atr:g}× signal ATR; "
                    f"actual stop distance = {base.ema_cross_stop_multiplier:g}× base distance, "
                    + (
                        f"while quantity is sized from a separate "
                        f"{base.position_sizing_stop_multiple:g}× base-distance reference. "
                        if sizing_override
                        else "while quantity remains sized from the base stop. "
                    )
                ),
                "EMA_20_100_CROSS_BOTH": (
                    f"Stop: base stop is signal-candle EMA 100 with a {base.ema_cross_stop_buffer_atr:g}× signal ATR buffer; "
                    f"actual stop distance = {base.ema_cross_stop_multiplier:g}× base distance, "
                    + (
                        f"while quantity is sized from a separate "
                        f"{base.position_sizing_stop_multiple:g}× base-distance reference. "
                        if sizing_override
                        else "while quantity remains sized from the base stop. "
                    )
                ),
            }.get(execution.ema_920_trade_plan)
            stop_description = cross_stop or (
                "Stop: EMA 9/20 confirmed micro-swing (2-left / 2-right, "
                "20-bar lookback, 0.05× ATR buffer, maximum 1.50× ATR). "
            )
        elif fvg:
            stop_description = (
                ("Stop: beyond the displacement candle (middle candle of the gap), "
                 if self._signal_strategy_mode() == "FVG_SIX_FACTOR"
                 else "Stop: beyond the selected FVG box (below bullish / above bearish), ") +
                "with a 0.05× signal ATR buffer; size from the full stop distance. "
            )
        elif fib:
            stop_description = (
                "Stop: beyond the next deeper Fib level (0.382→0.500, 0.500→0.618, "
                f"0.618→0.786) with a {execution.fib_stop_buffer_atr:g}× signal ATR buffer; "
                "size from the full stop distance. "
            )
        elif str(execution.risk_mode).upper() == "SR_STRUCTURE":
            stop_description = f"Stop distance uses {self._distance_description(execution)}. "
        else:
            stop_description = (
                f"Stop distance uses {self._distance_description(execution)} "
                f"with a {stop_mult:g}× stop multiplier. "
            )

        sizing_description = ""
        if cross_plan:
            sizing_multiple = (
                float(base.position_sizing_stop_multiple)
                if sizing_override else 1.0
            )
            cross_exposure = (
                effective_risk
                * float(base.ema_cross_stop_multiplier)
                / sizing_multiple
            )
            actual_as_sizing_r = (
                float(base.ema_cross_stop_multiplier) / sizing_multiple
            )
            sizing_description = (
                (
                    f" Position size uses a separate {sizing_multiple:g}× base-stop "
                    f"reference; actual EMA100 stop = {actual_as_sizing_r:.2f} sizing-R. "
                )
                if sizing_override
                else " Base EMA100 stop = 1.00 sizing-R. "
            ) + (
                f"Gross stop exposure is about {cross_exposure * 100:.2f}% "
                "before fees/slippage."
            )
        elif sizing_override:
            gross_stop_dollars = float(execution.initial_equity) * gross_stop_exposure
            stop_as_sizing_r = stop_mult / sizing_stop_mult
            geometry = (
                f" Actual full stop = {stop_as_sizing_r:.2f} sizing-R."
            )
            if (
                not base.partial_profit_enabled
                and str(execution.sr_take_profit_mode).upper() == "FIXED_R"
            ):
                target_as_sizing_r = float(base.reward_risk_ratio)
                physical_ratio = (
                    target_as_sizing_r * sizing_stop_mult / stop_mult
                    if stop_mult > 0
                    else float("nan")
                )
                geometry += (
                    f" Fixed target = {target_as_sizing_r:.2f} sizing-R; "
                    f"physical target:stop = {physical_ratio:g}:1."
                )
            sizing_description = (
                f" Position size uses a separate {sizing_stop_mult:g}× reference stop; "
                f"the configured actual stop implies about {gross_stop_exposure * 100:.2f}% "
                f"(${gross_stop_dollars:,.2f}) gross stop exposure before fees/slippage."
                f"{geometry}"
            )

        self.summary_label.setText(
            f"${execution.initial_equity:,.2f} equity · sizing budget {execution.risk_per_leg * 100:.2f}%"
            f"{multiplier} → effective sizing budget {effective_risk * 100:.2f}% (${risk_dollars:,.2f}). "
            f"Entry fill: {entry_fill}. "
            f"{stop_description}"
            f"{sizing_description}"
            f" Profit policy: {target}. Maximum active trades: {execution.max_active_pairs}. "
            + (
                (
                    f"DI reversal hedge enabled: fresh opposite 15m DI crosses, "
                    f"{execution.di_reversal_target_r:g}R child target, parent TP as child stop. "
                    if execution.di_ladder_mode == "DI_REVERSAL"
                    else
                    f"DI ladder enabled at {execution.di_ladder_level_r:g} sizing-R per level with "
                    f"{sum(1 for layer in execution.di_ladder_layers if layer.get('enabled', True))} enabled layers. "
                )
                if execution.di_ladder_enabled else
                "DI ladder disabled. "
            )
            + (
                "Initial entry and 1R are phantom; from 2R compare EMA gap with the immediately previous checkpoint, entering only if wider with SL one checkpoint behind. "
                if cross_plan and getattr(execution, "ema_cross_cost_cycle_enabled", False) and getattr(execution, "ema_cross_initial_phantom_enabled", False) else ""
            )
            + (
                "Re-entry filter: EMA 20/100 gap must exceed the previous actual entry gap; otherwise record phantom 1R checkpoints, with SL one checkpoint behind. "
                if cross_plan and getattr(execution, "ema_cross_cost_cycle_enabled", False) and getattr(execution, "ema_cross_reentry_widening_enabled", False) else ""
            )
            + (
                "Management: at 1R cover costs and move SL to entry; after a BE stop, repeat re-entry at the eligible R checkpoint with SL one checkpoint behind while EMA alignment holds; runner exits on the opposite cross."
                if cross_plan and getattr(execution, "ema_cross_cost_cycle_enabled", False)
                else f"Management: {self._management_description(base)}."
            )
        )

    def refresh_summary_from_widgets(self) -> None:
        try:
            execution = self.execution_form.value()
            base = self.base_form.value()
        except (TypeError, ValueError):
            return
        self.update_summary(execution, base)
