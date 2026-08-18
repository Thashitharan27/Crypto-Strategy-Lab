"""Temporary Stage 22 migration: clarify account risk, distance units, and trade-R semantics."""
from pathlib import Path


def read(path):
    return Path(path).read_text(encoding="utf-8")


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Stage 22 expected fragment missing: {label}")
    return text.replace(old, new, 1)


# 1) Backtest Setup: split account risk from price-distance basis and show live summaries.
path = "crypto_strategy_lab/gui/main_window.py"
text = read(path)
old = '''        risk=group("Account & Position Sizing"); self.account_form=risk
        self.risk_mode=QComboBox(); self.risk_mode.addItems(["ATR","PERCENT","FIXED"]); self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line("3"); self.max_lev_combined=self._line("5"); self.missing_policy=PolicyComboBox(); self.missing_policy.addItem("Use strategy candle for affected interval","WARN_AND_USE_15M"); self.missing_policy.addItem("Stop the run","ERROR"); self.missing_policy.addItem("Continue with available intrabar candles","WARN_AND_CONTINUE"); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("1%")
        self.risk_formula=QLabel(); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        for lab,w in [("Starting Equity",self.equity),("Base Account Risk Per Trade",self.risk_leg),("Risk Mode",self.risk_mode),("ATR Period",self.atr_period),("ATR Multiplier",self.atr_mult),("Price-Distance Percentage",self.percent_r),("Fixed Risk Distance",self.fixed_r),("Maximum Leverage Per Trade",self.max_lev_leg),("Maximum Portfolio Leverage",self.max_lev_combined),("Formula",self.risk_formula),("Planned Risk",self.risk_warn)]: risk.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic)
'''
new = '''        risk=group("Account Risk & Leverage"); self.account_form=risk
        self.risk_mode=PolicyComboBox(); self.risk_mode.addItem("ATR volatility","ATR"); self.risk_mode.addItem("Percent of price","PERCENT"); self.risk_mode.addItem("Fixed price distance","FIXED")
        self.trading_start=self._line(); self.trading_end=self._line(); self.max_lev_leg=self._line("3"); self.max_lev_combined=self._line("5"); self.missing_policy=PolicyComboBox(); self.missing_policy.addItem("Use strategy candle for affected interval","WARN_AND_USE_15M"); self.missing_policy.addItem("Stop the run","ERROR"); self.missing_policy.addItem("Continue with available intrabar candles","WARN_AND_CONTINUE"); self.zero_cost=QCheckBox("Run Zero-Cost Comparison"); self.atr_period=QSpinBox(); self.atr_period.setRange(1,99999); self.atr_mult=self._spin(1,0); self.percent_r=self._line("0.20%"); self.fixed_r=self._spin(100,0); self.equity=self._spin(1000,0,1e12,2); self.risk_leg=self._line("1%")
        self.risk_formula=QLabel(); self.risk_formula.setWordWrap(True); self.risk_warn=QLabel(); self.risk_warn.setWordWrap(True)
        self.account_risk_help=QLabel("Account risk controls how many dollars are planned to be lost at the initial full stop. The selected Strategy Profile can scale this with its Profile Risk Multiplier."); self.account_risk_help.setWordWrap(True)
        for lab,w in [("Starting Equity",self.equity),("Base Risk Per Trade",self.risk_leg),("Effective Account Risk",self.risk_warn),("Maximum Leverage Per Trade",self.max_lev_leg),("Maximum Portfolio Leverage",self.max_lev_combined),("",self.account_risk_help)]: risk.addRow(lab,w)
        basis=group("Stop Distance Basis"); self.distance_basis_form=basis
        self.distance_basis_help=QLabel("This defines one price-distance unit. Strategy Profile stop distances multiply this unit; it does not change the account-risk percentage by itself."); self.distance_basis_help.setWordWrap(True)
        for lab,w in [("Distance Basis",self.risk_mode),("ATR Period",self.atr_period),("ATR Unit Multiplier",self.atr_mult),("Percentage Distance Unit",self.percent_r),("Fixed Distance Unit",self.fixed_r),("Distance Unit",self.risk_formula),("",self.distance_basis_help)]: basis.addRow(lab,w)
        self.risk_mode.currentTextChanged.connect(self.update_dynamic); self.risk_leg.textChanged.connect(self.update_dynamic); self.equity.valueChanged.connect(self.update_dynamic); self.atr_period.valueChanged.connect(self.update_dynamic); self.atr_mult.valueChanged.connect(self.update_dynamic); self.percent_r.textChanged.connect(self.update_dynamic); self.fixed_r.valueChanged.connect(self.update_dynamic)
'''
text = replace_once(text, old, new, "Backtest Setup risk block")
old = '''        m=getattr(self,'risk_mode',None) and self.risk_mode.currentText(); self.atr_period.setVisible(m=="ATR"); self.atr_mult.setVisible(m=="ATR"); self.percent_r.setVisible(m=="PERCENT"); self.fixed_r.setVisible(m=="FIXED"); self.risk_formula.setText({"ATR":"R = ATR × ATR Multiplier","PERCENT":"R = Entry Price × Percentage","FIXED":"R = Fixed Price Distance"}.get(m,""));
        if hasattr(self,"account_form"):
            self.account_form.setRowVisible(self.atr_period,m=="ATR"); self.account_form.setRowVisible(self.atr_mult,m=="ATR")
            self.account_form.setRowVisible(self.percent_r,m=="PERCENT"); self.account_form.setRowVisible(self.fixed_r,m=="FIXED")
'''
new = '''        m=getattr(self,'risk_mode',None) and self.risk_mode.currentText(); self.atr_period.setVisible(m=="ATR"); self.atr_mult.setVisible(m=="ATR"); self.percent_r.setVisible(m=="PERCENT"); self.fixed_r.setVisible(m=="FIXED")
        try:
            distance_text={
                "ATR":f"1 volatility unit = ATR({self.atr_period.value()}) × {self.atr_mult.value():g}",
                "PERCENT":f"1 distance unit = Entry Price × {format_percentage(parse_percentage(self.percent_r.text()),2)}",
                "FIXED":f"1 distance unit = {self.fixed_r.value():g} price units",
            }.get(m,"")
            self.risk_formula.setText(distance_text)
        except Exception:
            self.risk_formula.setText("Distance unit unavailable until the value is valid")
        if hasattr(self,"distance_basis_form"):
            self.distance_basis_form.setRowVisible(self.atr_period,m=="ATR"); self.distance_basis_form.setRowVisible(self.atr_mult,m=="ATR")
            self.distance_basis_form.setRowVisible(self.percent_r,m=="PERCENT"); self.distance_basis_form.setRowVisible(self.fixed_r,m=="FIXED")
'''
text = replace_once(text, old, new, "dynamic distance-basis block")
old = '''            planned=r*multiplier
            self.risk_warn.setText(f"Base {format_percentage(r,2)} × {profile_name} {multiplier:g} = {format_percentage(planned,2)} per trade" + (" — warning: exceeds 5%." if planned>0.05 else ""))
'''
new = '''            planned=r*multiplier; planned_cash=self.equity.value()*planned
            self.risk_warn.setText(f"Base {format_percentage(r,2)} × {profile_name} {multiplier:g}x = {format_percentage(planned,2)} account risk (${planned_cash:,.2f} at ${self.equity.value():,.2f} equity)" + (" — warning: exceeds 5%." if planned>0.05 else ""))
'''
text = replace_once(text, old, new, "effective account-risk summary")
write(path, text)


# 2) Strategy Profile editor: distinguish distance units from true trade R.
path = "crypto_strategy_lab/gui/profile_editor.py"
text = read(path)
text = replace_once(text, 'self.form.labelForField(self.controls["risk_multiplier"]).setText("Position risk multiplier")', 'self.form.labelForField(self.controls["risk_multiplier"]).setText("Profile Risk Multiplier")\n        self.controls["risk_multiplier"].setSuffix(" x")', "profile risk label")
text = replace_once(text, 'self.controls["risk_multiplier"].setToolTip("Scales the configured account risk for this profile. 1.0 uses the normal risk.")', 'self.controls["risk_multiplier"].setToolTip("Scales Base Risk Per Trade for this profile. 1.0x uses the base account risk; 0.5x uses half; 2.0x uses double.")', "profile risk tooltip")
text = replace_once(text, 'self.form.labelForField(self.controls["stop_loss_multiple"]).setText("Initial stop distance")', 'self.form.labelForField(self.controls["stop_loss_multiple"]).setText("Stop Distance")', "base stop label")
text = replace_once(text, 'self.form.labelForField(self.controls["reward_risk_ratio"]).setText("Reward / risk target")', 'self.form.labelForField(self.controls["reward_risk_ratio"]).setText("Profit Target")', "profit target label")
text = replace_once(text, 'self.controls["stop_loss_multiple"].setSuffix(" R")', 'self.controls["stop_loss_multiple"].setSuffix(" distance units")', "base stop suffix")
text = replace_once(text, 'self.controls["stop_loss_multiple"].setToolTip("Distance from entry measured in the strategy\'s risk unit (R).")', 'self.controls["stop_loss_multiple"].setToolTip("Distance from entry measured in the Backtest Setup distance unit. With ATR basis, 2.0 means 2 × the configured ATR volatility unit.")', "base stop tooltip")
text = replace_once(text, 'self.controls["reward_risk_ratio"].setToolTip("Fixed final target as a multiple of the initial stop distance. Disabled while partial take-profit is active.")', 'self.controls["reward_risk_ratio"].setSuffix(" x stop (R)")\n        self.controls["reward_risk_ratio"].setToolTip("Fixed final target as a multiple of the full initial stop distance. 1R equals the initial full stop distance. Disabled while partial take-profit is active.")', "profit target tooltip")
text = replace_once(text, '''        for key in ("sl1_r","sl2_r"):
            self.controls[key].setDecimals(3)
            self.controls[key].setSuffix(" R")
''', '''        for key in ("sl1_r","sl2_r"):
            self.controls[key].setDecimals(3)
            self.controls[key].setSuffix(" distance units")
''', "partial stop suffixes")
text = replace_once(text, 'self._subsection("Profit Taking","Choose staged profit-taking only when you need more than the fixed reward/risk target.")', 'self._subsection("Profit Taking","Profit targets use trade R, where 1R equals the full initial stop distance.")', "profit taking help")
text = replace_once(text, 'self.controls["tp1_close_pct"].setToolTip("The remaining position exits at the final profit target.")', 'self.controls["tp1_close_pct"].setToolTip("The remaining position exits at the final profit target. TP1 and TP2 are measured in trade R (1R = full initial stop distance).")', "partial profit tooltip")
text = replace_once(text, 'self._subsection("Protection","Optional rules that protect an open winner.")', 'self._subsection("Protection","Protection thresholds use trade R, where 1R equals the full initial stop distance.")', "protection help")
text = replace_once(text, 'self._check("atr_checkpoint_tp_extension_enabled","ATR checkpoint TP extension")', 'self._check("atr_checkpoint_tp_extension_enabled","Distance-unit checkpoint TP extension")', "checkpoint label")
text = replace_once(text, 'self.controls["atr_checkpoint_tp_extension_enabled"].setToolTip("Extends profit management when the configured DI and Bollinger checkpoint conditions are met.")', 'self.controls["atr_checkpoint_tp_extension_enabled"].setToolTip("Advanced extension measured in the configured price-distance unit, not trade R. Extends profit management when DI and Bollinger checkpoint conditions are met.")', "checkpoint tooltip")
text = replace_once(text, '''        for key in ("r_step_activation_r","r_step_distance_r","r_step_size_r","r_step_maximum_r","atr_checkpoint_profit_lock_start","atr_checkpoint_profit_lock_distance"):
            self.controls[key].setSuffix(" R")
''', '''        for key in ("r_step_activation_r","r_step_distance_r","r_step_size_r","r_step_maximum_r"):
            self.controls[key].setSuffix(" R")
        for key in ("atr_checkpoint_profit_lock_start","atr_checkpoint_profit_lock_distance"):
            self.controls[key].setSuffix(" distance units")
''', "advanced suffix split")
write(path, text)


# 3) Position model: risk now means full trade-R price distance; keep the raw distance unit separately.
path = "crypto_strategy_lab/trade.py"
text = read(path)
text = replace_once(text, '    uncapped_quantity: float = 0.0; effective_leverage: float = 0.0; entry_fee: float = 0.0; exit_fee: float = 0.0\n', '    uncapped_quantity: float = 0.0; effective_leverage: float = 0.0; distance_unit: float = 0.0; entry_fee: float = 0.0; exit_fee: float = 0.0\n', "Position distance_unit")
write(path, text)


# 4) Engine semantics: 1R = initial full stop distance. Checkpoint extension stays distance-unit based.
path = "crypto_strategy_lab/engine.py"
text = read(path)
old = '''        pos = Position(
            side, self._execution_time(i), i, entry, r, sl, tp, qty, risk_amt, entry * qty,
            float(self.atr_values[ind_i]), uncapped, qty * entry / self.current_equity,
            entry_fee=entry_fee, fees=entry_fee, original_sl=sl,
'''
new = '''        pos = Position(
            side, self._execution_time(i), i, entry, stop, sl, tp, qty, risk_amt, entry * qty,
            float(self.atr_values[ind_i]), uncapped, qty * entry / self.current_equity,
            distance_unit=r, entry_fee=entry_fee, fees=entry_fee, original_sl=sl,
'''
text = replace_once(text, old, new, "Position trade-R distance")
text = replace_once(text, '        favourable_r=((high-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-low))/pos.risk\n', '        unit=pos.distance_unit or pos.risk\n        favourable_r=((high-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-low))/unit\n', "checkpoint favourable distance")
text = replace_once(text, '            pos.tp=pos.entry_price+direction*new_tp_r*pos.risk\n', '            pos.tp=pos.entry_price+direction*new_tp_r*unit\n', "checkpoint TP distance")
text = replace_once(text, '                candidate=pos.entry_price+direction*lock_r*pos.risk\n', '                candidate=pos.entry_price+direction*lock_r*unit\n', "checkpoint stop distance")
old = '''        if partial_tp:
            winning_price_r = stop_mult * ((tp1_pct/100.0) * tp1_r + (1-tp1_pct/100.0) * tp2_r)
        else:
            winning_price_r = stop_mult * applied_rr if np.isfinite(applied_rr) else np.nan
        expected_profit = winning_price_r * primary.risk * primary.quantity if np.isfinite(winning_price_r) else np.nan
'''
new = '''        if partial_tp:
            winning_trade_r = (tp1_pct/100.0) * tp1_r + (1-tp1_pct/100.0) * tp2_r
        else:
            winning_trade_r = applied_rr if np.isfinite(applied_rr) else np.nan
        expected_profit = winning_trade_r * primary.risk * primary.quantity if np.isfinite(winning_trade_r) else np.nan
'''
text = replace_once(text, old, new, "expected winning profit normalization")
text = text.replace('            "stop_loss_multiple": stop_mult,\n', '            "stop_distance_units": stop_mult,\n', 1)
text = text.replace('            "sl1_r": sl1_r,\n', '            "sl1_distance_units": sl1_r,\n', 1)
text = text.replace('            "sl2_r": sl2_r,\n', '            "sl2_distance_units": sl2_r,\n', 1)
text = text.replace('            "configured_price_risk_percentage": self.config.risk_per_leg,\n', '            "configured_account_risk_percentage": self.config.risk_per_leg,\n', 1)
text = text.replace('            "r_distance": primary.risk,\n', '            "distance_unit_price": primary.distance_unit,\n            "trade_r_price_distance": primary.risk,\n', 1)
text = text.replace('f"{prefix}_existing_r":pos.risk,', 'f"{prefix}_trade_r_price_distance":pos.risk,f"{prefix}_distance_unit_price":pos.distance_unit,', 1)
text = text.replace('f"{prefix}_configured_price_risk_percentage":self.config.risk_per_leg,', 'f"{prefix}_configured_account_risk_percentage":self.config.risk_per_leg,', 1)
write(path, text)


# 5) Run info and trade-list metadata: explain the new unambiguous terminology.
path = "crypto_strategy_lab/output_manager.py"
text = read(path)
text = replace_once(text, '        f"Risk mode: {config.risk_mode.value}",\n        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",\n', '        f"Stop distance basis: {config.risk_mode.value}",\n        f"Base account risk per trade: {config.risk_per_leg * 100:g}%",\n        f"ATR distance-unit period/multiplier: {config.atr_period} / {config.atr_multiplier}",\n', "run-info risk labels")
text = replace_once(text, '''TRADE_R_COLUMN_METADATA = {
    "r_distance": "Price-distance R selected by the configured risk mode before SL/TP multiples.",
    "configured_price_risk_percentage": "Configured account-equity percentage used as the price-risk budget per leg before fees and slippage.",
    "estimated_all_in_stop_risk_percentage": "Estimated per-leg account-equity loss at stop after entry fee, stop-exit fee, and configured slippage.",
    "*_price_r": "Realized price movement divided by r_distance; excludes quantity, fees, and account equity.",
''', '''TRADE_R_COLUMN_METADATA = {
    "distance_unit_price": "Entry-time price-distance unit selected by the configured distance basis (for example ATR × multiplier).",
    "trade_r_price_distance": "Full initial stop distance in price units. This is the price meaning of 1 trade R.",
    "configured_account_risk_percentage": "Configured account-equity percentage planned to be lost at the initial full stop before fees and slippage.",
    "estimated_all_in_stop_risk_percentage": "Estimated account-equity loss at stop after entry fee, stop-exit fee, and configured slippage.",
    "*_price_r": "Realized price movement divided by the full initial stop distance; 1.0 means one trade R of favourable price movement.",
''', "trade-R metadata header")
text = text.replace('    "*_account_r": "Alias for leg net_r retained for backward-compatible account-risk reporting.",\n', '    "*_account_r": "Cash PnL normalized by planned account risk for the leg.",\n')
text = text.replace('    "pair_price_r": "Sum of long_price_r and short_price_r; a price-distance measure, not cash risk.",\n', '    "pair_price_r": "Realized pair price movement expressed in trade R, where 1R is the full initial stop distance.",\n')
write(path, text)


# 6) GUI regression expectations and Stage 22 semantic tests.
path = "tests/test_gui_main_window.py"
text = read(path)
text = text.replace('assert window.account_form.parentWidget().title()=="Account & Position Sizing"', 'assert window.account_form.parentWidget().title()=="Account Risk & Leverage"')
text = text.replace('assert window.account_form.isRowVisible(window.atr_period)', 'assert window.distance_basis_form.parentWidget().title()=="Stop Distance Basis"\n        assert window.distance_basis_form.isRowVisible(window.atr_period)')
text = text.replace('assert not window.account_form.isRowVisible(window.percent_r)', 'assert not window.distance_basis_form.isRowVisible(window.percent_r)')
text = text.replace('assert not window.account_form.isRowVisible(window.atr_period)', 'assert not window.distance_basis_form.isRowVisible(window.atr_period)')
text = text.replace('assert window.account_form.isRowVisible(window.percent_r)', 'assert window.distance_basis_form.isRowVisible(window.percent_r)')
append = '''\n\ndef test_risk_ui_separates_account_risk_distance_units_and_trade_r():
    app(); window=MainWindow()
    try:
        assert window.account_form.parentWidget().title()=="Account Risk & Leverage"
        assert window.distance_basis_form.parentWidget().title()=="Stop Distance Basis"
        assert window.account_form.labelForField(window.risk_leg).text()=="Base Risk Per Trade"
        assert window.distance_basis_form.labelForField(window.risk_mode).text()=="Distance Basis"
        assert window.risk_mode.itemText(0)=="ATR volatility"
        assert window.risk_mode.currentText()=="ATR"
        assert "1 volatility unit = ATR(14)" in window.risk_formula.text()
        assert "1.00% account risk" in window.risk_warn.text()
        assert "$10.00" in window.risk_warn.text()
        editor=window.profile_editor; controls=editor.controls
        assert editor.control_forms["risk_multiplier"].labelForField(controls["risk_multiplier"]).text()=="Profile Risk Multiplier"
        assert controls["risk_multiplier"].suffix().strip()=="x"
        assert editor.control_forms["stop_loss_multiple"].labelForField(controls["stop_loss_multiple"]).text()=="Stop Distance"
        assert "distance units" in controls["stop_loss_multiple"].suffix()
        assert editor.control_forms["reward_risk_ratio"].labelForField(controls["reward_risk_ratio"]).text()=="Profit Target"
        assert "stop (R)" in controls["reward_risk_ratio"].suffix()
        assert "distance units" in controls["sl1_r"].suffix()
        assert controls["tp1_r"].suffix().strip()=="R"
        assert controls["break_even_activation_r"].suffix().strip()=="R"
        assert controls["atr_checkpoint_profit_lock_start"].suffix().strip()=="distance units"
    finally: window.close()
'''
if "test_risk_ui_separates_account_risk_distance_units_and_trade_r" not in text:
    text += append
write(path, text)

path = "tests/test_stage22_risk_semantics.py"
write(path, '''import pandas as pd\nimport pytest\n\nfrom crypto_strategy_lab.config import BacktestConfig, RiskMode\nfrom crypto_strategy_lab.engine import BacktestEngine\nfrom crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles\n\n\ndef candles():\n    return pd.DataFrame([\n        {"timestamp":pd.Timestamp("2024-01-01T00:00:00Z"),"open":100,"high":100,"low":100,"close":100,"volume":1},\n        {"timestamp":pd.Timestamp("2024-01-01T00:15:00Z"),"open":100,"high":100,"low":100,"close":100,"volume":1},\n    ])\n\n\ndef engine_with_profile(profile):\n    profiles=default_profiles(); profiles["sideways_long"]=profile\n    cfg=BacktestConfig(risk_mode=RiskMode.FIXED,fixed_r=10,use_intrabar_data=False,enable_trade_telemetry=False,strategy_profiles=profiles,maker_fee=0,taker_fee=0,slippage=0)\n    engine=BacktestEngine(candles(),cfg)\n    engine.market_regime_values[:]=\"SIDEWAYS\"; engine.plus_di_values[:]=50; engine.minus_di_values[:]=10; engine.di_spread[:]=40\n    return engine\n\n\ndef test_trade_r_is_full_initial_stop_distance_for_base_exit_and_break_even():\n    profile=StrategyProfile(enabled=True,stop_loss_multiple=2,reward_risk_ratio=1,break_even_enabled=True,break_even_activation_r=1,break_even_offset_r=0)\n    engine=engine_with_profile(profile); engine._open_pair(0); pos=engine.active_pairs[0].long\n    assert pos is not None\n    assert pos.distance_unit==pytest.approx(10)\n    assert pos.risk==pytest.approx(20)\n    assert pos.sl==pytest.approx(80)\n    assert pos.tp==pytest.approx(120)\n    assert not engine._maybe_activate_break_even(pos,119.9,100,pd.Timestamp("2024-01-01T00:15:00Z"))\n    assert engine._maybe_activate_break_even(pos,120,100,pd.Timestamp("2024-01-01T00:15:00Z"))\n    assert pos.sl==pytest.approx(100)\n\n\ndef test_partial_profit_and_trailing_use_full_trade_r():\n    profile=StrategyProfile(enabled=True,stop_loss_multiple=2,partial_profit_enabled=True,tp1_r=1,tp1_close_pct=50,tp2_r=2,trailing_enabled=True,trailing_activation_r=1,trailing_distance_r=.5)\n    engine=engine_with_profile(profile); engine._open_pair(0); pos=engine.active_pairs[0].long\n    assert pos.tp1_price==pytest.approx(120)\n    assert pos.tp2_price==pytest.approx(140)\n    assert pos.trailing_activation_price==pytest.approx(120)\n    assert pos.trailing_distance_r==pytest.approx(.5)\n\n\ndef test_distance_unit_checkpoint_extension_remains_distance_unit_based():\n    profile=StrategyProfile(enabled=True,stop_loss_multiple=2,reward_risk_ratio=1,atr_checkpoint_tp_extension_enabled=True,atr_checkpoint_di_spread_minimum=0,atr_checkpoint_bb_width_minimum=0)\n    engine=engine_with_profile(profile); engine.bb_width[:]=1; engine._open_pair(0); pos=engine.active_pairs[0].long\n    assert pos.risk==pytest.approx(20)\n    assert pos.distance_unit==pytest.approx(10)\n    engine._apply_atr_checkpoint_extensions(pos,110,100,pd.Timestamp("2024-01-01T00:15:00Z"))\n    assert pos.tp==pytest.approx(130)\n\n\ndef test_trade_list_exports_unambiguous_risk_distance_columns():\n    profile=StrategyProfile(enabled=True,stop_loss_multiple=2,reward_risk_ratio=1)\n    engine=engine_with_profile(profile); engine._open_pair(0); pos=engine.active_pairs[0].long\n    engine._close_position(pos,1,120,engine.ExitReason.TP if hasattr(engine,'ExitReason') else None)\n''')
# Remove the intentionally incomplete last test body; output columns are covered by full engine tests after run.
text = read(path)
marker='\ndef test_trade_list_exports_unambiguous_risk_distance_columns():'
if marker in text:
    text=text.split(marker,1)[0].rstrip()+"\n"
write(path,text)
