"""Temporary Stage 19 migration helper. Remove after the PR is validated."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[:i] + replacement + text[j:]


def replace_line_containing(text: str, needle: str, replacement: str = "") -> str:
    lines = text.splitlines(True)
    matches = [i for i, line in enumerate(lines) if needle in line]
    if len(matches) != 1:
        raise RuntimeError(f"expected one line containing {needle!r}, found {len(matches)}")
    lines[matches[0]] = replacement + ("\n" if replacement and not replacement.endswith("\n") else "")
    return "".join(lines)


# --- Main window: remove hidden widgets and hidden values entirely. ---
path = ROOT / "crypto_strategy_lab/gui/main_window.py"
text = path.read_text(encoding="utf-8")
text = replace_line_containing(
    text,
    "self.sl=self._spin(2,0)",
    "        self.entry_mode=QComboBox(); self.entry_mode.addItem(\"Wait until current trade closes\",\"WAIT_UNTIL_CLOSED\"); self.entry_mode.addItem(\"Check every N candles\",\"EVERY_N_CANDLES\"); self.entry_interval=QSpinBox(); self.entry_interval.setRange(1,999999); self.max_pairs=QSpinBox(); self.max_pairs.setRange(1,999999); self.tie=QComboBox(); self.tie.addItem(\"Conservative (stop first)\",\"PESSIMISTIC\"); self.tie.addItem(\"Optimistic (target first)\",\"OPTIMISTIC\")",
)
text = replace_line_containing(
    text,
    'for lab,w in [("Stop Loss Multiple",self.sl)',
    '        for lab,w in [("Entry Mode",self.entry_mode),("Entry Interval",self.entry_interval),("Maximum Active Pairs",self.max_pairs),("Tie Policy",self.tie)]: strat.addRow(lab,w)',
)
text = text.replace('        self.di_execution_mode=QComboBox(); self.di_execution_mode.addItems(["BOTH_SIDES","PREFERRED_SIDE_ONLY"])\n        self.di_execution_mode.currentTextChanged.connect(self.update_dynamic)\n', '')
text = replace_line_containing(
    text,
    "self.trade_direction=QComboBox()",
    '        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line("3"); self.max_lev_combined=self._line("5"); self.missing_policy=PolicyComboBox(); self.missing_policy.addItem("Use strategy candle for affected interval","WARN_AND_USE_15M"); self.missing_policy.addItem("Stop the run","ERROR"); self.missing_policy.addItem("Continue with available intrabar candles","WARN_AND_CONTINUE"); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("1%")',
)
text = replace_line_containing(
    text,
    '("Trade Direction",self.trade_direction)',
    '        for lab,w in [("Starting Equity",self.equity),("Base Account Risk Per Trade",self.risk_leg),("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Price-Distance Percentage",self.percent_r),("Fixed Risk Distance",self.fixed_r),("Maximum Leverage Per Trade",self.max_lev_leg),("Maximum Portfolio Leverage",self.max_lev_combined),("Formula",self.risk_formula),("Planned Risk",self.risk_warn)]: risk.addRow(lab,w)',
)
text = replace_between(
    text,
    '        self.sl.setVisible(False); sl_label=strat.labelForField(self.sl)\n',
    '        scroll.setWidget(inner); outer.addWidget(scroll);',
    '        scroll.setWidget(inner); outer.addWidget(scroll);',
)
base = '''    def _base_values(self):
        return {
            "config_version": 2,
            "strategy_timeframe_minutes": self._timeframe_minutes(self.strategy_timeframe.currentText()),
            "intrabar_timeframe_minutes": self._timeframe_minutes(self.intrabar_timeframe.currentText()),
            "enable_indicator_lifecycle_analysis": self.enable_lifecycle.isChecked(),
            "lifecycle_phases": self.lifecycle_phases.value(),
            "lifecycle_early_checkpoints": [int(v.strip()) for v in self.lifecycle_checkpoints.text().split(",") if v.strip()],
            "lifecycle_minimum_bucket_sample": self.lifecycle_min_sample.value(),
            "create_lifecycle_charts": self.lifecycle_charts.isChecked(),
            "lifecycle_flat_pattern_threshold_pct": self.lifecycle_flat_threshold.value(),
            "run_name": self.run_name.text().strip(),
            "input_csv": self.input_csv.text(), "strategy_csv": self.input_csv.text(),
            "intrabar_csv": self.intrabar_csv.text(), "use_intrabar_data": self.use_intrabar.isChecked(),
            "trading_start_date": self.trading_start.text() or None, "trading_end_date": self.trading_end.text() or None,
            "max_effective_leverage_per_leg": self.max_lev_leg.text() or None,
            "max_combined_effective_leverage": self.max_lev_combined.text() or None,
            "intrabar_missing_policy": self.missing_policy.currentText(), "zero_cost_comparison": self.zero_cost.isChecked(),
            "output_dir": self.output_folder.text(), "entry_mode": self.entry_mode.currentData(), "entry_interval": self.entry_interval.value(),
            "enable_daily_entry_schedule": self.enable_daily_schedule.isChecked(), "daily_entry_time": self.daily_entry_time.text().strip(),
            "daily_entry_timezone": self.daily_entry_timezone.text().strip(), "daily_entry_missed_policy": self.daily_entry_missed_policy.currentText(),
            "max_active_pairs": self.max_pairs.value(), "tie_policy": self.tie.currentData(),
            "risk_mode": self.risk_mode.currentText(), "atr_period": self.atr_period.value(), "atr_multiplier": self.atr_mult.value(),
            "percent_r": parse_percentage(self.percent_r.text()), "fixed_r": self.fixed_r.value(), "initial_equity": self.equity.value(),
            "risk_per_leg": parse_percentage(self.risk_leg.text()), "maker_fee": parse_percentage(self.maker.text()),
            "taker_fee": parse_percentage(self.taker.text()), "use_maker_entry": self.maker_entry.isChecked(),
            "use_maker_exit": self.maker_exit.isChecked(), "slippage": parse_percentage(self.slippage.text()),
            "adx_period": self._shared_adx_period,
            "enable_trade_telemetry": self.enable_trade_telemetry.isChecked(), "save_full_telemetry_csv": self.save_full_telemetry.isChecked(),
            "save_trade_journey_summary": self.save_journey_summary.isChecked(), "save_trade_journey_charts": self.save_journey_charts.isChecked(),
            "telemetry_interval_minutes": self.telemetry_interval.value(),
        }
'''
text = replace_between(text, '    def _base_values(self):\n', '    def values(self):\n', base)
text = text.replace('        values.update({"entry_mode":self.entry_mode.currentData(),"tie_policy":self.tie.currentData(),"trade_direction":"BOTH","enable_strategy_profiles":True,"enable_di_direction_sizing":True,"di_execution_mode":"PREFERRED_SIDE_ONLY"})\n', '')
text = text.replace('        values.update({"vwap_breakout_lookback_hours":4.0,"vwap_volume_lookback":20,"vwap_volume_multiplier":1.5,"vwap_slope_lookback":1,"vwap_atr_pct_minimum":0.0,"vwap_atr_pct_maximum":1.0,"vwap_confirmation_mode":"IMMEDIATE","vwap_retest_window_candles":4,"vwap_retest_tolerance_atr":0.25})\n', '')
text = text.replace('        values.update({"enable_coin_flip_sizing":False,"coin_flip_seed":42,"coin_flip_large_multiplier":3.0,"coin_flip_small_multiplier":1.0})\n', '')
text = replace_between(
    text,
    '        values.update({\n            "enable_reentry_gate_after_remaining_leg_timeout":False,\n',
    '        values.update(self.profile_editor.values())\n',
    '        values.update(self.profile_editor.values())\n',
)
text = text.replace('    def reset_defaults(self):\n        defaults=default_gui_config()\n        defaults.update({"enable_di_direction_sizing":True,"enable_di_direction_selection":True,"enable_di_pressure_analysis":True,"di_pressure_lookback":3})\n        self.apply_values(defaults)\n', '    def reset_defaults(self):\n        self.apply_values(default_gui_config())\n')
text = text.replace('        self.sl.setValue(float(values["sl_mult"]))\n        self.tp.setValue(float(values["tp_mult"]))\n', '')
text = text.replace('        self.zero_cost.setChecked(bool(values["zero_cost_comparison"])); self.trade_direction.setCurrentText(str(values.get("trade_direction", "BOTH")))\n', '        self.zero_cost.setChecked(bool(values["zero_cost_comparison"]))\n')
path.write_text(text, encoding="utf-8")


# --- Profile editor: current schema only. ---
path = ROOT / "crypto_strategy_lab/gui/profile_editor.py"
text = path.read_text(encoding="utf-8")
text = text.replace('from copy import deepcopy\n', 'from copy import deepcopy\nfrom dataclasses import replace\n')
text = text.replace('                self.profiles[key].entry_rules=deepcopy(current_rules)\n', '                self.profiles[key]=replace(self.profiles[key], entry_rules=deepcopy(current_rules))\n')
text = replace_line_containing(
    text,
    'def values(self): return {"enable_strategy_profiles"',
    '    def values(self): return {"strategy_profile_run_mode":self.mode.currentData(),"market_regime_method":self.regime_method.currentData(),"structural_regime_sma_days":self.structural_sma_days.value(),"structural_regime_slope_lookback_days":self.structural_slope_days.value(),"bull_regime_lookback_days":self.regime_lookback.value(),"bull_regime_return_threshold":self.bull_threshold.value()/100.0,"adx_period":self.adx_period.value(),"bb_period":self.bb_period.value(),"bb_stddevs":self.bb_stddevs.value(),"strategy_profiles":profiles_to_dict(self.profiles)}',
)
text = text.replace('self.bear_threshold.setValue(float(values.get("di_regime_bear_return_threshold",-.20))*100); ', '')
path.write_text(text, encoding="utf-8")


# --- Engine: generic entry rules are the only profile-filter contract. ---
path = ROOT / "crypto_strategy_lab/engine.py"
text = path.read_text(encoding="utf-8")
new_filter = '''    def _strategy_profile_filter_result(self, i, execution_i=None):
        context=self._profile_context(i)
        if context is None:
            plus=float(self.plus_di_values[i]); minus=float(self.minus_di_values[i]); regime=self._regime_at(i)
            if not all(np.isfinite(v) for v in (plus,minus)) or regime is None:
                return False,"Strategy profile classification indicator warm-up incomplete"
            return False,"Strategy profile direction unavailable"
        regime,direction,key,profile=context
        if not profile.enabled: return False,f"Strategy profile {key} is disabled"
        if profile.entry_rules:
            rejected=self._strategy_profile_rule_group_match(i,direction,profile,"REJECT",profile.reject_rule_match_mode)
            if rejected: return False,f"Strategy profile {key} rejected by entry rules"
            flipped=self._strategy_profile_rule_group_match(i,direction,profile,"FLIP",profile.flip_rule_match_mode)
            action="will be flipped" if flipped else "will trade in its normal direction"
            return True,f"Strategy profile {key} passed; flip rules {'matched' if flipped else 'did not match'}: entry {action}"
        return True,f"Strategy profile {key} passed"

'''
text = replace_between(text, '    def _strategy_profile_filter_result(self, i, execution_i=None):\n', '    def _strategy_profile_flip_match(self, i, direction, profile):\n', new_filter)
old = '''        if active_profile and active_profile.entry_rules:
            profile_filter_flip=self._strategy_profile_rule_group_match(ind_i,original_di_direction,active_profile,"FLIP",active_profile.flip_rule_match_mode)
        else:
            profile_filter_flip = bool(active_profile and active_profile.filter_action == "FLIP" and self._strategy_profile_conditional_flip_match(ind_i, original_di_direction, active_profile))
'''
new = '''        profile_filter_flip=bool(active_profile and active_profile.entry_rules and self._strategy_profile_rule_group_match(ind_i,original_di_direction,active_profile,"FLIP",active_profile.flip_rule_match_mode))
'''
if old not in text:
    raise RuntimeError("engine profile flip block not found")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")

print("Stage 19 current-contract migration applied")
