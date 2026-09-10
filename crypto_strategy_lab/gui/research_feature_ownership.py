"""Researcher-facing composition for the Research Features workspace.

The native v3 feature configuration is intentionally left authoritative. This
module reorganizes those existing controls around how researchers think about
features:

* core strategy dependencies are automatic/required rather than user toggles;
* lightweight futures context stays automatic when local source coverage exists
  and becomes trade-affecting only through explicit Entry/Veto rules;
* optional or expensive research blocks have explicit controls;
* settings are collapsed until they are useful;
* Strategy Builder remains focused on entry/veto semantics.

No feature formula, causal timing rule, or strategy decision semantic is changed.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.strategy_rule_model import (
    uses_mean_reversion_rules,
    uses_support_resistance_rules,
)


FRIENDLY_LABELS = {
    "atr_period": "ATR period",
    "bb_period": "Bollinger period",
    "bb_stddevs": "Bollinger deviation",
    "adx_period": "DI / ADX period",
    "di_pressure_lookback": "DI pressure lookback",
    "mean_reversion_period": "Mean period",
    "mean_reversion_mean_type": "Mean type",
    "mean_reversion_bb_stddevs": "Bollinger deviation",
    "mean_reversion_rsi_period": "RSI period",
    "mean_reversion_rsi_oversold": "RSI oversold",
    "mean_reversion_rsi_overbought": "RSI overbought",
    "mean_reversion_require_reentry": "Require re-entry",
    "mean_reversion_track_atr_distance": "Track ATR distance",
    "mean_reversion_track_motion": "Track motion",
    "market_regime_method": "Regime model",
    "structural_regime_sma_days": "SMA period",
    "structural_regime_slope_lookback_days": "SMA slope lookback",
    "bull_regime_lookback_days": "Return lookback",
    "bull_regime_return_threshold": "Bull / bear threshold",
    "sr_timeframe_minutes": "Primary S/R timeframe (legacy)",
    "sr_pivot_left": "Pivot bars left",
    "sr_pivot_right": "Pivot bars right",
    "sr_lookback_bars": "Lookback bars",
    "sr_15m_pivot_left": "15m pivot left",
    "sr_15m_pivot_right": "15m pivot right",
    "sr_15m_lookback_bars": "15m lookback",
    "sr_1h_pivot_left": "1h pivot left",
    "sr_1h_pivot_right": "1h pivot right",
    "sr_1h_lookback_bars": "1h lookback",
    "sr_4h_pivot_left": "4h pivot left",
    "sr_4h_pivot_right": "4h pivot right",
    "sr_4h_lookback_bars": "4h lookback",
    "sr_1d_pivot_left": "1d pivot left",
    "sr_1d_pivot_right": "1d pivot right",
    "sr_1d_lookback_bars": "1d lookback",
    "sr_zone_width_atr": "Zone width",
    "sr_near_distance_atr": "Near-zone distance",
    "enable_sr_hold_confirmation": "Confirm level hold",
    "sr_hold_confirmation_bars": "Hold confirmation bars",
    "sr_hold_confirmation_atr": "Hold confirmation distance",
    "sr_break_tolerance_atr": "Break tolerance",
    "sr_break_basis": "Break basis",
    "oi_zscore_window_days": "OI z-score window",
    "oi_zscore_min_samples": "OI minimum samples",
    "funding_zscore_window_days": "Funding z-score window",
    "funding_zscore_min_samples": "Funding minimum samples",
    "funding_extreme_zscore": "Extreme funding z-score",
    "basis_zscore_window_days": "Basis z-score window",
    "taker_flow_interval": "Source interval",
    "trade_flow_source": "Raw trade source",
    "trade_flow_windows": "Research windows",
    "large_trade_quote_threshold": "Large-trade threshold",
    "book_ticker_max_age_seconds": "Book ticker maximum age",
    "book_depth_max_age_seconds": "Book depth maximum age",
}


class FeatureCard(QGroupBox):
    """Compact feature card with status, optional enable control and settings."""

    def __init__(
        self,
        title: str,
        *,
        status: str,
        note: str,
        enable: QCheckBox | None = None,
        expandable: bool = False,
        expanded: bool = True,
        parent=None,
    ):
        super().__init__(title, parent)
        self.enable = enable
        self._expandable = expandable
        self._field_rows: dict[str, tuple[QLabel, QWidget]] = {}

        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        if enable is not None:
            top.addWidget(enable)
        self.status = QLabel(status)
        self.status.setObjectName("featureStatus")
        self.status.setStyleSheet(
            "font-weight:600; background:#eef5fb; padding:3px 7px; "
            "border:1px solid #c8d9e8"
        )
        top.addWidget(self.status)
        self.note = QLabel(note)
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#52606d")
        top.addWidget(self.note, 1)
        self.settings_button = None
        if expandable:
            self.settings_button = QToolButton()
            self.settings_button.setText("Settings")
            self.settings_button.setCheckable(True)
            self.settings_button.setChecked(expanded)
            top.addWidget(self.settings_button)
        outer.addLayout(top)

        self.settings = QWidget()
        self.form = QFormLayout(self.settings)
        self.form.setContentsMargins(8, 4, 8, 4)
        outer.addWidget(self.settings)

        if self.settings_button is not None:
            self.settings_button.toggled.connect(self._refresh_settings_visibility)
        if self.enable is not None:
            self.enable.toggled.connect(self._refresh_settings_visibility)
        self._refresh_settings_visibility()

    def add_field(self, name: str, widget: QWidget, label: str) -> None:
        label_widget = QLabel(label)
        self.form.addRow(label_widget, widget)
        self._field_rows[name] = (label_widget, widget)

    def set_field_visible(self, name: str, visible: bool) -> None:
        row = self._field_rows.get(name)
        if row is None:
            return
        label, widget = row
        label.setVisible(visible)
        widget.setVisible(visible)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _refresh_settings_visibility(self, *_args) -> None:
        enabled = self.enable is None or self.enable.isChecked()
        expanded = (
            self.settings_button is None or self.settings_button.isChecked()
        )
        self.settings.setVisible(enabled and expanded)
        if self.settings_button is not None:
            self.settings_button.setEnabled(enabled)


class ResearchFeaturesPanel(QWidget):
    """Friendly organization over the existing authoritative FeatureConfig form."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.form = window.feature_form
        self.widgets = self.form.widgets
        self.builder = window.rule_builder
        self._applying_preset = False

        self._prepare_existing_widgets()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        intro = QGroupBox("Research Load")
        intro_layout = QVBoxLayout(intro)
        intro_text = QLabel(
            "Core strategy dependencies stay automatic. Lightweight Binance futures "
            "context is attached automatically when local coverage exists. Support / "
            "Resistance, detailed Trade Flow and Order Book are explicit because they "
            "can add preparation work."
        )
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet(
            "background:#f7f9fb; padding:8px; border:1px solid #d9e2ec"
        )
        intro_layout.addWidget(intro_text)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Research depth"))
        self.preset = QComboBox()
        self.preset.addItem("Fast — core + lightweight automatic context", "FAST")
        self.preset.addItem("Standard — recommended", "STANDARD")
        self.preset.addItem(
            "Deep Research — includes S/R, Trade Flow and Order Book", "DEEP"
        )
        self.preset.addItem("Custom", "CUSTOM")
        self.apply_preset = QPushButton("Apply")
        self.apply_preset.clicked.connect(self._apply_selected_preset)
        preset_row.addWidget(self.preset, 1)
        preset_row.addWidget(self.apply_preset)
        intro_layout.addLayout(preset_row)
        layout.addWidget(intro)

        self._section(layout, "Core Strategy Context")
        self.price_card = FeatureCard(
            "Price & Volatility",
            status="AUTOMATIC",
            note="Calculated when required by strategy rules, ATR-based execution or research dependencies.",
        )
        self._add_fields(
            self.price_card,
            ("atr_period", "bb_period", "bb_stddevs"),
        )
        layout.addWidget(self.price_card)

        self.di_card = FeatureCard(
            "Directional Movement",
            status="REQUIRED BY STRATEGY",
            note="DI direction is the current candidate-side model; these settings also support DI rule evidence.",
        )
        self._add_fields(self.di_card, ("adx_period", "di_pressure_lookback"))
        layout.addWidget(self.di_card)

        self.regime_card = FeatureCard(
            "Market Regime",
            status="REQUIRED BY STRATEGY",
            note="Bull / Bear / Sideways permissions depend on this causal completed-state model.",
        )
        self._add_fields(
            self.regime_card,
            (
                "market_regime_method",
                "structural_regime_sma_days",
                "structural_regime_slope_lookback_days",
                "bull_regime_lookback_days",
                "bull_regime_return_threshold",
            ),
        )
        self.regime_detail = QLabel()
        self.regime_detail.setWordWrap(True)
        self.regime_detail.setStyleSheet("color:#52606d; margin:4px 8px")
        self.regime_card.layout().addWidget(self.regime_detail)
        layout.addWidget(self.regime_card)

        self._section(layout, "Technical Research")
        self.builder.enable_mr.setText("Include Mean Reversion research")
        self.mr_card = FeatureCard(
            "Mean Reversion",
            status="RULE-READY",
            note="Adds MR context to reports. Any explicit MR Entry/Veto/Flip rule automatically makes it a required strategy dependency.",
            enable=self.builder.enable_mr,
            expandable=True,
            expanded=True,
        )
        self._add_fields(
            self.mr_card,
            (
                "mean_reversion_period",
                "mean_reversion_mean_type",
                "mean_reversion_bb_stddevs",
                "mean_reversion_rsi_period",
                "mean_reversion_rsi_oversold",
                "mean_reversion_rsi_overbought",
                "mean_reversion_require_reentry",
                "mean_reversion_track_atr_distance",
                "mean_reversion_track_motion",
            ),
        )
        layout.addWidget(self.mr_card)

        self.sr_enable = self.widgets["enable_support_resistance_analysis"]
        self.sr_enable.setText("Include Support / Resistance research")
        self.sr_card = FeatureCard(
            "Support / Resistance",
            status="OFF / RESEARCH ONLY",
            note=(
                "Calculates independent Strategy-TF and compatible higher-timeframe "
                "S/R contexts. Choose the timeframe on each S/R Entry/Veto/Flip "
                "condition; no combined S/R score is created."
            ),
            enable=self.sr_enable,
            expandable=True,
            expanded=False,
        )

        self.sr_prepared_timeframes = QLabel()
        self.sr_prepared_timeframes.setWordWrap(True)
        self.sr_prepared_timeframes.setStyleSheet(
            "color:#334e68; background:#f7f9fb; padding:7px 9px; "
            "border:1px solid #d9e2ec; margin:2px 8px 4px 8px"
        )
        # Keep the prepared-context summary visible even while detailed S/R
        # settings are collapsed.
        self.sr_card.layout().insertWidget(1, self.sr_prepared_timeframes)

        self.sr_detection_box = QGroupBox("Detection sensitivity by timeframe")
        detection = QGridLayout(self.sr_detection_box)
        detection.addWidget(QLabel("Context"), 0, 0)
        detection.addWidget(QLabel("Pivot left"), 0, 1)
        detection.addWidget(QLabel("Pivot right"), 0, 2)
        detection.addWidget(QLabel("Lookback bars"), 0, 3)
        detection_rows = (
            ("Shared fallback", "sr_pivot_left", "sr_pivot_right", "sr_lookback_bars", False),
            ("15m", "sr_15m_pivot_left", "sr_15m_pivot_right", "sr_15m_lookback_bars", True),
            ("1h", "sr_1h_pivot_left", "sr_1h_pivot_right", "sr_1h_lookback_bars", True),
            ("4h", "sr_4h_pivot_left", "sr_4h_pivot_right", "sr_4h_lookback_bars", True),
            ("1d", "sr_1d_pivot_left", "sr_1d_pivot_right", "sr_1d_lookback_bars", True),
        )
        for row, (label, left_name, right_name, lookback_name, override) in enumerate(
            detection_rows, 1
        ):
            detection.addWidget(QLabel(label), row, 0)
            for column, name in enumerate((left_name, right_name, lookback_name), 1):
                widget = self.widgets[name]
                if override and hasattr(widget, "setSpecialValueText"):
                    widget.setMinimum(0)
                    widget.setSpecialValueText("Shared")
                    widget.setToolTip(
                        "0/Shared inherits the shared fallback. Set a positive value only when "
                        "this timeframe needs a different structural horizon."
                    )
                detection.addWidget(widget, row, column)
        detection_note = QLabel(
            "Bar counts are timeframe-specific: 5 confirmation bars means 75 minutes on 15m, "
            "5 hours on 1h, 20 hours on 4h and 5 days on 1d. Leave an override on Shared "
            "until research justifies changing it."
        )
        detection_note.setWordWrap(True)
        detection_note.setStyleSheet("color:#52606d")
        detection.addWidget(detection_note, 6, 0, 1, 4)
        self.sr_card.form.addRow(self.sr_detection_box)

        interaction_note = QLabel(
            "Level hold confirmation is always calculated as S/R evidence. It does not filter "
            "trades by itself; Entry/Veto/Flip rules decide whether the held/state evidence matters."
        )
        interaction_note.setWordWrap(True)
        interaction_note.setStyleSheet("color:#52606d")
        self.sr_card.form.addRow(interaction_note)
        self._add_fields(
            self.sr_card,
            (
                "sr_zone_width_atr",
                "sr_near_distance_atr",
                "sr_hold_confirmation_bars",
                "sr_hold_confirmation_atr",
                "sr_break_tolerance_atr",
                "sr_break_basis",
            ),
        )

        # The old single-timeframe selector still owns the unprefixed primary
        # S/R context for saved-config compatibility. It is not the way new
        # multi-timeframe rules select evidence, so keep it out of the normal
        # settings surface and expose it only under an explicit legacy section.
        self.sr_legacy_section = QWidget()
        sr_legacy_layout = QVBoxLayout(self.sr_legacy_section)
        sr_legacy_layout.setContentsMargins(0, 4, 0, 0)
        self.sr_legacy_toggle = QToolButton()
        self.sr_legacy_toggle.setText("Advanced / Legacy primary S/R timeframe")
        self.sr_legacy_toggle.setCheckable(True)
        self.sr_legacy_toggle.setChecked(False)
        sr_legacy_layout.addWidget(self.sr_legacy_toggle)

        self.sr_legacy_body = QWidget()
        sr_legacy_form = QFormLayout(self.sr_legacy_body)
        sr_legacy_form.setContentsMargins(8, 2, 0, 2)
        sr_legacy_note = QLabel(
            "Compatibility setting for the historical unprefixed S/R context. "
            "New S/R rules select Strategy TF, 1h, 4h or 1d independently in "
            "the Strategy Builder."
        )
        sr_legacy_note.setWordWrap(True)
        sr_legacy_note.setStyleSheet("color:#52606d")
        sr_legacy_form.addRow(sr_legacy_note)
        sr_legacy_form.addRow(
            "Primary S/R timeframe (legacy)",
            self.widgets["sr_timeframe_minutes"],
        )
        self.sr_legacy_body.setVisible(False)
        self.sr_legacy_toggle.toggled.connect(self.sr_legacy_body.setVisible)
        sr_legacy_layout.addWidget(self.sr_legacy_body)
        self.sr_card.form.addRow(self.sr_legacy_section)

        layout.addWidget(self.sr_card)

        self._section(layout, "Futures Market Research — automatic when data is available")
        futures_note = QLabel(
            "These source-native blocks attach automatically when local data exists. They are research-only by default, but explicit Entry/Veto rules can make them trade-affecting. REQUIRED rules reject when their selected futures evidence is missing; missing VETO evidence does not reject."
        )
        futures_note.setWordWrap(True)
        futures_note.setStyleSheet("color:#52606d; margin:0 4px 4px 4px")
        layout.addWidget(futures_note)

        self.oi_card = FeatureCard(
            "Open Interest & Positioning",
            status="AUTO · RULE-READY",
            note="Binance futures metrics: OI changes/z-score plus trader and account positioning ratios.",
            expandable=True,
            expanded=False,
        )
        self._add_fields(self.oi_card, ("oi_zscore_window_days", "oi_zscore_min_samples"))
        layout.addWidget(self.oi_card)

        self.funding_card = FeatureCard(
            "Funding Rate",
            status="AUTO · RULE-READY",
            note="Funding event context and extremes, aligned causally to the strategy decision time.",
            expandable=True,
            expanded=False,
        )
        self._add_fields(
            self.funding_card,
            (
                "funding_zscore_window_days",
                "funding_zscore_min_samples",
                "funding_extreme_zscore",
            ),
        )
        layout.addWidget(self.funding_card)

        self.basis_card = FeatureCard(
            "Basis / Premium",
            status="AUTO · RULE-READY",
            note="Mark-price versus index-price basis/premium research; kept separate from positioning.",
            expandable=True,
            expanded=False,
        )
        self._add_fields(self.basis_card, ("basis_zscore_window_days",))
        layout.addWidget(self.basis_card)

        self.taker_card = FeatureCard(
            "Taker Buy / Sell Flow",
            status="AUTO · RULE-READY",
            note="Uses candle taker-buy information; this is lightweight and distinct from raw detailed Trade Flow.",
            expandable=True,
            expanded=False,
        )
        self._add_fields(self.taker_card, ("taker_flow_interval",))
        layout.addWidget(self.taker_card)

        self._section(layout, "High-Resolution Research")
        high_res_note = QLabel(
            "These can materially increase first-run preparation time. Cached prepared results are reused on later matching runs."
        )
        high_res_note.setWordWrap(True)
        high_res_note.setStyleSheet("color:#52606d; margin:0 4px 4px 4px")
        layout.addWidget(high_res_note)

        self.trade_enable = self.widgets["trade_flow_enabled"]
        self.trade_enable.setText("Include detailed Trade Flow")
        self.trade_card = FeatureCard(
            "Detailed Trade Flow",
            status="HEAVY · OFF",
            note="Processes raw aggTrades/trades into reusable minute aggregates and multi-window flow context.",
            enable=self.trade_enable,
            expandable=True,
            expanded=False,
        )
        self._add_fields(
            self.trade_card,
            ("trade_flow_source", "trade_flow_windows", "large_trade_quote_threshold"),
        )
        layout.addWidget(self.trade_card)

        self.book_enable = self.widgets["order_book_enabled"]
        self.book_enable.setText("Include historical Order Book research")
        self.book_card = FeatureCard(
            "Historical Order Book",
            status="HEAVY · OFF",
            note="Uses Book Ticker / Depth snapshots when available. Keep off unless order-book research is part of the experiment.",
            enable=self.book_enable,
            expandable=True,
            expanded=False,
        )
        self._add_fields(
            self.book_card,
            ("book_ticker_max_age_seconds", "book_depth_max_age_seconds"),
        )
        layout.addWidget(self.book_card)
        layout.addStretch()

        self.widgets["market_regime_method"].currentIndexChanged.connect(
            lambda _index: self.refresh_visibility()
        )
        strategy_tf = getattr(self.window, "strategy_tf", None)
        if strategy_tf is not None and hasattr(strategy_tf, "currentIndexChanged"):
            strategy_tf.currentIndexChanged.connect(
                lambda _index: self._refresh_sr_timeframe_summary()
            )
        self.sr_enable.toggled.connect(lambda _checked: self.refresh_visibility())
        self.trade_enable.toggled.connect(lambda _checked: self.refresh_visibility())
        self.book_enable.toggled.connect(lambda _checked: self.refresh_visibility())
        self.builder.enable_mr.toggled.connect(lambda _checked: self._mark_custom())
        self.sr_enable.toggled.connect(lambda _checked: self._mark_custom())
        self.trade_enable.toggled.connect(lambda _checked: self._mark_custom())
        self.book_enable.toggled.connect(lambda _checked: self._mark_custom())
        self.builder.changed.connect(self._sync_mr_requirement)
        self.builder.changed.connect(self._sync_sr_requirement)
        self.form.changed.connect(self.refresh_visibility)

        self._sync_mr_requirement()
        self._sync_sr_requirement()
        self.refresh_visibility()
        self._infer_preset()

    def _prepare_existing_widgets(self) -> None:
        timeframe = self.widgets.get("sr_timeframe_minutes")
        if timeframe is not None and hasattr(timeframe, "setSpecialValueText"):
            timeframe.setMinimum(0)
            timeframe.setSpecialValueText("Same as strategy")
        threshold = self.widgets.get("large_trade_quote_threshold")
        if threshold is not None and hasattr(threshold, "setPlaceholderText"):
            threshold.setPlaceholderText("Auto / disabled")
        hold_confirmation = self.widgets.get("enable_sr_hold_confirmation")
        if hold_confirmation is not None:
            hold_confirmation.setChecked(True)
            hold_confirmation.setEnabled(False)
            hold_confirmation.hide()
        windows = self.widgets.get("trade_flow_windows")
        if windows is not None and hasattr(windows, "setMaximumHeight"):
            windows.setMaximumHeight(80)

    @staticmethod
    def _section(layout: QVBoxLayout, title: str) -> None:
        label = QLabel(title)
        label.setStyleSheet("font-size:15px; font-weight:700; margin:10px 4px 2px 4px")
        layout.addWidget(label)

    def _add_fields(self, card: FeatureCard, names: tuple[str, ...]) -> None:
        for name in names:
            widget = self.widgets[name]
            card.add_field(name, widget, FRIENDLY_LABELS.get(name, name.replace("_", " ").title()))

    def _strategy_timeframe_context(self) -> tuple[int | None, str]:
        selector = getattr(self.window, "strategy_tf", None)
        if selector is None:
            return None, "Strategy TF"
        raw = selector.currentData() if hasattr(selector, "currentData") else None
        if raw in (None, "") and hasattr(selector, "currentText"):
            raw = selector.currentText()
        text = str(raw or "").strip().lower()
        known = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        minutes = known.get(text)
        return minutes, (text if minutes is not None else "Strategy TF")

    def _refresh_sr_timeframe_summary(self) -> None:
        minutes, label = self._strategy_timeframe_context()
        if minutes is None:
            text = (
                "Prepared S/R timeframes: Strategy TF + compatible higher TFs. "
                "Each context stays separate and is selected per S/R rule."
            )
        else:
            contexts = [f"Strategy TF ({label})"]
            for higher_minutes, higher_label in (
                (60, "1h"),
                (240, "4h"),
                (1440, "1d"),
            ):
                if higher_minutes > minutes and higher_minutes % minutes == 0:
                    contexts.append(higher_label)
            text = (
                "Prepared S/R timeframes: "
                + " · ".join(contexts)
                + ". Each context stays separate; select the timeframe on each S/R rule."
            )
        self.sr_prepared_timeframes.setText(text)

    def _mark_custom(self, *_args) -> None:
        if self._applying_preset:
            return
        index = self.preset.findData("CUSTOM")
        if index >= 0:
            self.preset.setCurrentIndex(index)

    def _apply_selected_preset(self) -> None:
        preset = self.preset.currentData()
        if preset == "CUSTOM":
            return
        self._applying_preset = True
        try:
            values = {
                "FAST": (False, False, False, False),
                "STANDARD": (True, True, False, False),
                "DEEP": (True, True, True, True),
            }[preset]
            mr, sr, trade, book = values
            self.builder.enable_mr.setChecked(mr)
            self.sr_enable.setChecked(sr)
            self.trade_enable.setChecked(trade)
            self.book_enable.setChecked(book)
        finally:
            self._applying_preset = False
        self._sync_mr_requirement()
        self._sync_sr_requirement()
        self.refresh_visibility()

    def _infer_preset(self) -> None:
        state = (
            self.builder.enable_mr.isChecked(),
            self.sr_enable.isChecked(),
            self.trade_enable.isChecked(),
            self.book_enable.isChecked(),
        )
        native = {
            (False, False, False, False): "FAST",
            (True, True, False, False): "STANDARD",
            (True, True, True, True): "DEEP",
        }.get(state, "CUSTOM")
        index = self.preset.findData(native)
        if index >= 0:
            self.preset.setCurrentIndex(index)

    def _sync_mr_requirement(self, *_args) -> None:
        try:
            required = uses_mean_reversion_rules(
                self.builder.required_rules.rules(),
                self.builder.veto_rules.rules(),
                self.builder.flip_rules.rules(),
            )
        except (AttributeError, TypeError, ValueError):
            required = False
        if required:
            if not self.builder.enable_mr.isChecked():
                self.builder.enable_mr.setChecked(True)
            self.builder.enable_mr.setEnabled(False)
            self.builder.enable_mr.setText("Mean Reversion calculation required by strategy rule")
            self.mr_card.set_status("REQUIRED BY STRATEGY")
        else:
            self.builder.enable_mr.setEnabled(True)
            self.builder.enable_mr.setText("Include Mean Reversion research")
            self.mr_card.set_status(
                "RULE-READY" if self.builder.enable_mr.isChecked() else "OFF · RULE-READY"
            )
        self.refresh_visibility()

    def _sync_sr_requirement(self, *_args) -> None:
        try:
            required = uses_support_resistance_rules(
                self.builder.required_rules.rules(),
                self.builder.veto_rules.rules(),
                self.builder.flip_rules.rules(),
            )
        except (AttributeError, TypeError, ValueError):
            required = False
        if required:
            if not self.sr_enable.isChecked():
                self.sr_enable.setChecked(True)
            self.sr_enable.setEnabled(False)
            self.sr_enable.setText("Support / Resistance calculation required by strategy rule")
            self.sr_card.set_status("REQUIRED BY STRATEGY")
        else:
            self.sr_enable.setEnabled(True)
            self.sr_enable.setText("Include Support / Resistance research")
            self.sr_card.set_status(
                "RESEARCH ONLY" if self.sr_enable.isChecked() else "OFF / RESEARCH ONLY"
            )
        self.refresh_visibility()

    def refresh_visibility(self, *_args) -> None:
        self._refresh_sr_timeframe_summary()
        method = self.widgets["market_regime_method"].currentData()
        structural = method in {"BTC_STRUCTURAL", "ASSET_STRUCTURAL"}
        for name in (
            "structural_regime_sma_days",
            "structural_regime_slope_lookback_days",
        ):
            self.regime_card.set_field_visible(name, structural)
        for name in ("bull_regime_lookback_days", "bull_regime_return_threshold"):
            self.regime_card.set_field_visible(name, method == "ASSET_RETURN")
        if method == "BTC_STRUCTURAL":
            self.regime_detail.setText(
                "BTC Structural Trend uses completed BTCUSDT daily state derived from the 1h benchmark; "
                "the Setup readiness check includes the required structural warm-up."
            )
        elif method == "ASSET_STRUCTURAL":
            self.regime_detail.setText(
                "Asset Structural Trend applies the completed structural state to the selected asset."
            )
        else:
            self.regime_detail.setText(
                "Asset Return classifies Bull / Bear / Sideways from the causal trailing return and symmetric threshold."
            )

        # The compatibility flag is intentionally normalized to ON in the GUI.
        # Hold/state evidence is calculated regardless of whether a strategy rule uses it.
        hold_widget = self.widgets["enable_sr_hold_confirmation"]
        if not hold_widget.isChecked():
            hold_widget.blockSignals(True)
            hold_widget.setChecked(True)
            hold_widget.blockSignals(False)
        for name in ("sr_hold_confirmation_bars", "sr_hold_confirmation_atr"):
            self.sr_card.set_field_visible(name, True)

        if self.builder.enable_mr.isEnabled():
            self.mr_card.set_status(
                "RULE-READY" if self.builder.enable_mr.isChecked() else "OFF · RULE-READY"
            )
        if self.sr_enable.isEnabled():
            self.sr_card.set_status(
                "RESEARCH ONLY" if self.sr_enable.isChecked() else "OFF / RESEARCH ONLY"
            )
        self.trade_card.set_status(
            "HEAVY · ENABLED" if self.trade_enable.isChecked() else "HEAVY · OFF"
        )
        self.book_card.set_status(
            "HEAVY · ENABLED" if self.book_enable.isChecked() else "HEAVY · OFF"
        )
        self.mr_card._refresh_settings_visibility()
        self.sr_card._refresh_settings_visibility()
        self.trade_card._refresh_settings_visibility()
        self.book_card._refresh_settings_visibility()


def _page_with_title(window, title: str):
    pages = getattr(window, "pages", None)
    if pages is None:
        return None
    for index in range(pages.count()):
        page = pages.widget(index)
        if any(label.text() == title for label in page.findChildren(QLabel)):
            return page
    return None


def _feature_scroll(page, feature_form):
    if page is None:
        return None
    for scroll in page.findChildren(QScrollArea):
        if scroll.widget() is feature_form:
            return scroll
    return None


def apply_research_feature_ownership(window) -> None:
    """Install the organized Research Features workstation on the active GUI."""
    builder = getattr(window, "rule_builder", None)
    feature_form = getattr(window, "feature_form", None)
    if builder is None or feature_form is None or not hasattr(builder, "enable_mr"):
        return
    if getattr(window, "research_features_panel", None) is not None:
        return

    feature_page = _page_with_title(window, "Research Features")
    scroll = _feature_scroll(feature_page, feature_form)
    if scroll is None:
        return

    # Keep the authoritative DataclassForm alive because build_config/apply_config
    # and all existing signal connections depend on it. Only its widgets are
    # re-parented into the researcher-facing composition below.
    old_form = scroll.takeWidget()
    panel = ResearchFeaturesPanel(window)
    old_form.setParent(panel)
    old_form.hide()
    scroll.setWidget(panel)
    window.research_features_panel = panel
    window.mean_reversion_research_box = panel.mr_card

    # Strategy Builder should contain only trade-affecting authoring controls.
    for box in builder.findChildren(QGroupBox):
        if box.title() == "4. Research-only Evidence":
            box.hide()
            break
    advanced = getattr(builder, "advanced", None)
    if isinstance(advanced, QGroupBox):
        advanced.setTitle("4. Advanced")
