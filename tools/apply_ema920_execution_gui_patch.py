from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch target not found: {label}")
    return text.replace(old, new, 1)


workspace_path = Path("crypto_strategy_lab/gui/risk_execution_workspace.py")
text = workspace_path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''        layout.addWidget(self.plan_box)\n\n        self.account_card = FormCard(\n            "1. Account Risk & Position Sizing",\n            note="These controls define the account risk budget and how many positions may be open at once.",\n        )''',
    '''        layout.addWidget(self.plan_box)\n\n        self.entry_card = FormCard(\n            "1. Entry Execution",\n            note=(\n                "Choose when a completed strategy signal becomes an executable fill. "\n                "Next Candle Open is the causal default for EMA 9/20 scalping."\n            ),\n        )\n        self.entry_card.add_field(\n            "entry_timing_mode", "Entry Fill Timing", self.account["entry_timing_mode"]\n        )\n        layout.addWidget(self.entry_card)\n\n        self.account_card = FormCard(\n            "2. Account Risk & Position Sizing",\n            note="These controls define the account risk budget and how many positions may be open at once.",\n        )''',
    "entry card",
)
text = text.replace('"2. Stop & Position Sizing"', '"3. Stop & Position Sizing"', 1)
text = text.replace('"3. Profit Target"', '"4. Profit Target"', 1)
text = text.replace('"4. Trade Management"', '"5. Trade Management"', 1)

text = replace_once(
    text,
    '''        self.stop_card.add_field("stop_loss_multiple", "Stop Multiplier", self.trade["stop_loss_multiple"])\n        layout.addWidget(self.stop_card)''',
    '''        self.stop_card.add_field("stop_loss_multiple", "Stop Multiplier", self.trade["stop_loss_multiple"])\n\n        self.ema_stop_method = QLabel("EMA 9/20 Micro-Swing — Automatic")\n        self.ema_stop_method.setStyleSheet("font-weight:600")\n        self.ema_stop_confirmation = QLabel("2 left / 2 right")\n        self.ema_stop_lookback = QLabel("20 bars")\n        self.ema_stop_buffer = QLabel("0.05 × ATR")\n        self.ema_stop_maximum = QLabel("1.50 × ATR")\n        self.stop_card.add_field("ema_920_stop_method", "Stop Method", self.ema_stop_method)\n        self.stop_card.add_field("ema_920_stop_confirmation", "Swing Confirmation", self.ema_stop_confirmation)\n        self.stop_card.add_field("ema_920_stop_lookback", "Swing Lookback", self.ema_stop_lookback)\n        self.stop_card.add_field("ema_920_stop_buffer", "Stop Buffer", self.ema_stop_buffer)\n        self.stop_card.add_field("ema_920_stop_maximum", "Maximum Stop", self.ema_stop_maximum)\n        layout.addWidget(self.stop_card)''',
    "EMA stop display",
)

text = replace_once(
    text,
    '''        self.target_card.add_field("sr_take_profit_no_level_policy", "If No Opposing S/R Exists", self.account["sr_take_profit_no_level_policy"])\n        self.sr_dependency_note = QLabel(''',
    '''        self.target_card.add_field("sr_take_profit_no_level_policy", "If No Opposing S/R Exists", self.account["sr_take_profit_no_level_policy"])\n        self.ema_target_method = QLabel("EMA 9/20 Fixed 1R — Automatic")\n        self.ema_target_method.setStyleSheet("font-weight:600")\n        self.ema_target_value = QLabel("1.00 R")\n        self.target_card.add_field("ema_920_target_method", "Target Method", self.ema_target_method)\n        self.target_card.add_field("ema_920_target_value", "Profit Target", self.ema_target_value)\n        self.sr_dependency_note = QLabel(''',
    "EMA target display",
)

text = replace_once(
    text,
    '''        self.account["risk_mode"].currentIndexChanged.connect(self.refresh_visibility)\n        self.account["sr_take_profit_mode"].currentIndexChanged.connect(self.refresh_visibility)''',
    '''        self.account["risk_mode"].currentIndexChanged.connect(self.refresh_visibility)\n        self.account["sr_take_profit_mode"].currentIndexChanged.connect(self.refresh_visibility)\n        self.account["entry_timing_mode"].currentIndexChanged.connect(self.refresh_summary_from_widgets)\n        builder = getattr(self.window, "rule_builder", None)\n        if builder is not None:\n            builder.direction_mode.currentIndexChanged.connect(self.refresh_visibility)''',
    "strategy-aware refresh hooks",
)

marker = '''    def refresh_visibility(self, *_args) -> None:\n'''
helper = '''    def _signal_strategy_mode(self) -> str:\n        builder = getattr(self.window, "rule_builder", None)\n        if builder is None:\n            return "DI"\n        return str(builder.direction_mode.currentData() or "DI").upper()\n\n    def _ema_920_selected(self) -> bool:\n        return self._signal_strategy_mode() == "EMA_9_20_PULLBACK"\n\n'''
if helper not in text:
    text = replace_once(text, marker, helper + marker, "strategy helper")

old_visibility = '''    def refresh_visibility(self, *_args) -> None:\n        mode = str(self.account["risk_mode"].currentData() or "ATR")\n        structural_stop = mode == "SR_STRUCTURE"\n        self.stop_card.set_row_visible("atr_multiplier", mode == "ATR")\n        self.stop_card.set_row_visible("percent_r", mode == "PERCENT")\n        self.stop_card.set_row_visible("fixed_r", mode == "FIXED")\n        for name in (\n            "sr_stop_timeframe_minutes", "sr_stop_buffer_atr",\n            "sr_stop_maximum_atr", "sr_stop_no_level_policy",\n        ):\n            self.stop_card.set_row_visible(name, structural_stop)\n        # Structural mode owns the full initial stop distance. The legacy stop\n        # multiplier remains preserved in the profile but is not a user-facing\n        # input for the final structural stop.\n        self.stop_card.set_row_visible("stop_loss_multiple", not structural_stop)\n\n        target_mode = str(self.account["sr_take_profit_mode"].currentData() or "FIXED_R")\n        sr_target = target_mode in ("SR_CAPPED_R", "SR_LEVEL")\n        for name in (\n            "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",\n            "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",\n            "sr_take_profit_no_level_policy",\n        ):\n            self.target_card.set_row_visible(name, sr_target)\n        self.sr_dependency_note.setVisible(structural_stop or sr_target)\n'''
new_visibility = '''    def refresh_visibility(self, *_args) -> None:\n        ema_920 = self._ema_920_selected()\n        mode = str(self.account["risk_mode"].currentData() or "ATR")\n        structural_stop = mode == "SR_STRUCTURE"\n\n        generic_stop_fields = (\n            "risk_mode", "atr_multiplier", "percent_r", "fixed_r",\n            "sr_stop_timeframe_minutes", "sr_stop_buffer_atr",\n            "sr_stop_maximum_atr", "sr_stop_no_level_policy", "stop_loss_multiple",\n        )\n        ema_stop_fields = (\n            "ema_920_stop_method", "ema_920_stop_confirmation",\n            "ema_920_stop_lookback", "ema_920_stop_buffer", "ema_920_stop_maximum",\n        )\n        for name in ema_stop_fields:\n            self.stop_card.set_row_visible(name, ema_920)\n        if ema_920:\n            for name in generic_stop_fields:\n                self.stop_card.set_row_visible(name, False)\n        else:\n            self.stop_card.set_row_visible("risk_mode", True)\n            self.stop_card.set_row_visible("atr_multiplier", mode == "ATR")\n            self.stop_card.set_row_visible("percent_r", mode == "PERCENT")\n            self.stop_card.set_row_visible("fixed_r", mode == "FIXED")\n            for name in (\n                "sr_stop_timeframe_minutes", "sr_stop_buffer_atr",\n                "sr_stop_maximum_atr", "sr_stop_no_level_policy",\n            ):\n                self.stop_card.set_row_visible(name, structural_stop)\n            # Structural mode owns the full initial stop distance. The legacy stop\n            # multiplier remains preserved in the profile but is not a user-facing\n            # input for the final structural stop.\n            self.stop_card.set_row_visible("stop_loss_multiple", not structural_stop)\n\n        target_mode = str(self.account["sr_take_profit_mode"].currentData() or "FIXED_R")\n        sr_target = target_mode in ("SR_CAPPED_R", "SR_LEVEL")\n        ema_target_fields = ("ema_920_target_method", "ema_920_target_value")\n        for name in ema_target_fields:\n            self.target_card.set_row_visible(name, ema_920)\n        if ema_920:\n            self.target_card.set_row_visible("sr_take_profit_mode", False)\n            self.target_card.set_row_visible("reward_risk_ratio", False)\n            for name in (\n                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",\n                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",\n                "sr_take_profit_no_level_policy",\n            ):\n                self.target_card.set_row_visible(name, False)\n            self.sr_dependency_note.setVisible(False)\n        else:\n            self.target_card.set_row_visible("sr_take_profit_mode", True)\n            self.target_card.set_row_visible("reward_risk_ratio", True)\n            for name in (\n                "sr_take_profit_timeframe_minutes", "sr_take_profit_minimum_r",\n                "sr_take_profit_maximum_r", "sr_take_profit_buffer_r",\n                "sr_take_profit_no_level_policy",\n            ):\n                self.target_card.set_row_visible(name, sr_target)\n            self.sr_dependency_note.setVisible(structural_stop or sr_target)\n'''
text = replace_once(text, old_visibility, new_visibility, "strategy-aware visibility")

start = text.index('    def update_summary(self, execution, base) -> None:\n')
end = text.index('    def refresh_summary_from_widgets(self) -> None:\n', start)
new_summary = '''    def update_summary(self, execution, base) -> None:\n        effective_risk = float(execution.risk_per_leg) * float(base.risk_multiplier)\n        risk_dollars = float(execution.initial_equity) * effective_risk\n        stop_mult = float(base.sl2_r if base.partial_stop_enabled else base.stop_loss_multiple)\n        ema_920 = self._ema_920_selected()\n\n        timing = str(getattr(execution, "entry_timing_mode", "SIGNAL_CLOSE")).upper()\n        entry_fill = (\n            "Next Candle Open — Causal"\n            if timing == "NEXT_CANDLE_OPEN"\n            else "Signal Candle Close — Legacy"\n        )\n\n        if ema_920:\n            target = "automatic fixed 1.00R target"\n        else:\n            target_mode = str(execution.sr_take_profit_mode).upper()\n            if target_mode == "SR_CAPPED_R":\n                timeframe = self._timeframe_description(\n                    execution.sr_take_profit_timeframe_minutes, primary=True\n                )\n                target = (\n                    f"S/R-constrained target from {timeframe} (base {base.reward_risk_ratio:g}R, "\n                    f"minimum {execution.sr_take_profit_minimum_r:g}R, "\n                    f"cap {execution.sr_take_profit_maximum_r:g}R)"\n                )\n            elif target_mode == "SR_LEVEL":\n                timeframe = self._timeframe_description(\n                    execution.sr_take_profit_timeframe_minutes, primary=True\n                )\n                target = (\n                    f"structural S/R target from {timeframe} "\n                    f"(minimum {execution.sr_take_profit_minimum_r:g}R, "\n                    f"safety cap {execution.sr_take_profit_maximum_r:g}R)"\n                )\n            else:\n                target = f"fixed {base.reward_risk_ratio:g}R target"\n\n        multiplier = (\n            f" · risk multiplier {base.risk_multiplier:g}×"\n            if abs(float(base.risk_multiplier) - 1.0) > 1e-12\n            else ""\n        )\n        if ema_920:\n            stop_description = (\n                "Stop: EMA 9/20 confirmed micro-swing (2-left / 2-right, "\n                "20-bar lookback, 0.05× ATR buffer, maximum 1.50× ATR). "\n            )\n        elif str(execution.risk_mode).upper() == "SR_STRUCTURE":\n            stop_description = f"Stop distance uses {self._distance_description(execution)}. "\n        else:\n            stop_description = (\n                f"Stop distance uses {self._distance_description(execution)} "\n                f"with a {stop_mult:g}× stop multiplier. "\n            )\n\n        self.summary_label.setText(\n            f"${execution.initial_equity:,.2f} equity · base risk {execution.risk_per_leg * 100:.2f}%"\n            f"{multiplier} → effective risk budget {effective_risk * 100:.2f}% (${risk_dollars:,.2f}). "\n            f"Entry fill: {entry_fill}. "\n            f"{stop_description}"\n            f"Profit policy: {target}. Maximum active trades: {execution.max_active_pairs}. "\n            f"Management: {self._management_description(base)}."\n        )\n\n'''
text = text[:start] + new_summary + text[end:]
workspace_path.write_text(text, encoding="utf-8")


install_path = Path("crypto_strategy_lab/gui/risk_execution_install.py")
text = install_path.read_text(encoding="utf-8")
old = '''        target_value = str(target_mode.currentData() or "FIXED_R")\n        stop_value = str(stop_mode.currentData() or "ATR")\n        required_by_target = target_value in {"SR_CAPPED_R", "SR_LEVEL"}\n        required_by_stop = stop_value == "SR_STRUCTURE"\n        required_by_execution = required_by_target or required_by_stop\n'''
new = '''        target_value = str(target_mode.currentData() or "FIXED_R")\n        stop_value = str(stop_mode.currentData() or "ATR")\n        builder = getattr(window, "rule_builder", None)\n        strategy_mode = (\n            str(builder.direction_mode.currentData() or "DI").upper()\n            if builder is not None\n            else "DI"\n        )\n        ema_920_override = strategy_mode == "EMA_9_20_PULLBACK"\n        required_by_target = (not ema_920_override) and target_value in {"SR_CAPPED_R", "SR_LEVEL"}\n        required_by_stop = (not ema_920_override) and stop_value == "SR_STRUCTURE"\n        required_by_execution = required_by_target or required_by_stop\n'''
text = replace_once(text, old, new, "EMA S/R dependency override")
install_path.write_text(text, encoding="utf-8")


test_path = Path("tests/test_risk_execution_workspace.py")
text = test_path.read_text(encoding="utf-8")
text = text.replace('assert "1. Account Risk & Position Sizing" in titles', 'assert "1. Entry Execution" in titles\n        assert "2. Account Risk & Position Sizing" in titles', 1)
text = text.replace('assert "2. Stop & Position Sizing" in titles', 'assert "3. Stop & Position Sizing" in titles', 1)
text = text.replace('assert "3. Profit Target" in titles', 'assert "4. Profit Target" in titles', 1)
text = text.replace('assert "4. Trade Management" in titles', 'assert "5. Trade Management" in titles', 1)

addition = r'''


def test_ema_920_execution_plan_is_explicit_and_generic_stop_target_controls_are_hidden():
    app, window = _window()
    try:
        workspace = window.risk_execution_workspace
        selector = window.rule_builder.direction_mode
        timing = window.execution_form.widgets["entry_timing_mode"]
        risk_mode = window.execution_form.widgets["risk_mode"]
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]
        base_target = window.base_execution_form.widgets["reward_risk_ratio"]

        ema_index = selector.findData("EMA_9_20_PULLBACK")
        selector.setCurrentIndex(ema_index)
        selector.activated.emit(ema_index)
        app.processEvents()
        workspace.refresh_visibility()

        assert timing.currentData() == "NEXT_CANDLE_OPEN"
        assert not timing.isHidden()
        assert risk_mode.isHidden()
        assert target_mode.isHidden()
        assert base_target.isHidden()
        assert not workspace.ema_stop_method.isHidden()
        assert workspace.ema_stop_method.text() == "EMA 9/20 Micro-Swing — Automatic"
        assert workspace.ema_stop_confirmation.text() == "2 left / 2 right"
        assert workspace.ema_stop_lookback.text() == "20 bars"
        assert workspace.ema_stop_buffer.text() == "0.05 × ATR"
        assert workspace.ema_stop_maximum.text() == "1.50 × ATR"
        assert not workspace.ema_target_method.isHidden()
        assert workspace.ema_target_method.text() == "EMA 9/20 Fixed 1R — Automatic"
        assert workspace.ema_target_value.text() == "1.00 R"
        assert "Next Candle Open — Causal" in workspace.summary_label.text()
        assert "confirmed micro-swing" in workspace.summary_label.text()
        assert "automatic fixed 1.00R target" in workspace.summary_label.text()

        # Entry timing remains deliberately editable for A/B execution testing.
        legacy_index = timing.findData("SIGNAL_CLOSE")
        timing.setCurrentIndex(legacy_index)
        app.processEvents()
        assert timing.currentData() == "SIGNAL_CLOSE"
        assert "Signal Candle Close — Legacy" in workspace.summary_label.text()

        # Returning to a normal strategy restores the generic stop/target controls.
        di_index = selector.findData("DI")
        selector.setCurrentIndex(di_index)
        selector.activated.emit(di_index)
        app.processEvents()
        workspace.refresh_visibility()
        assert not risk_mode.isHidden()
        assert not target_mode.isHidden()
        assert not base_target.isHidden()
        assert workspace.ema_stop_method.isHidden()
        assert workspace.ema_target_method.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_ema_920_ignores_hidden_generic_sr_policy_dependency():
    app, window = _window()
    try:
        selector = window.rule_builder.direction_mode
        stop_mode = window.execution_form.widgets["risk_mode"]
        target_mode = window.execution_form.widgets["sr_take_profit_mode"]
        sr_toggle = window.feature_form.widgets["enable_support_resistance_analysis"]

        stop_mode.setCurrentIndex(stop_mode.findData("SR_STRUCTURE"))
        target_mode.setCurrentIndex(target_mode.findData("SR_LEVEL"))
        app.processEvents()
        assert sr_toggle.isChecked() is True
        assert sr_toggle.isEnabled() is False

        ema_index = selector.findData("EMA_9_20_PULLBACK")
        selector.setCurrentIndex(ema_index)
        selector.activated.emit(ema_index)
        app.processEvents()

        # The EMA engine owns stop + TP internally, so hidden generic S/R policy
        # values must not force S/R calculation unless the strategy rules need it.
        assert sr_toggle.isEnabled() is True
        assert sr_toggle.isChecked() is False
    finally:
        window.close()
        app.processEvents()
'''
if "test_ema_920_execution_plan_is_explicit" not in text:
    text += addition

test_path.write_text(text, encoding="utf-8")
