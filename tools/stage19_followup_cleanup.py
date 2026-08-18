"""Temporary Stage 19 follow-up cleanup. Remove before merge."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def remove_between(text: str, start: str, end: str, label: str) -> str:
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{label}: start not found")
    j = text.find(end, i)
    if j < 0:
        raise RuntimeError(f"{label}: end not found")
    return text[:i] + text[j:]


# main_window.py: remove migration duplicates.
path = ROOT / "crypto_strategy_lab/gui/main_window.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        scroll.setWidget(inner); outer.addWidget(scroll);        scroll.setWidget(inner); outer.addWidget(scroll); self.backtest_setup_page=page;",
    "        scroll.setWidget(inner); outer.addWidget(scroll); self.backtest_setup_page=page;",
    "duplicate scroll insertion",
)
text = replace_once(
    text,
    "        values.update(self.profile_editor.values())\n        values.update(self.profile_editor.values())\n",
    "        values.update(self.profile_editor.values())\n",
    "duplicate profile values update",
)
path.write_text(text, encoding="utf-8")


# profile_editor.py: remove the inert asymmetric bear threshold and legacy wording.
path = ROOT / "crypto_strategy_lab/gui/profile_editor.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'self.regime_method.addItem("Asset trailing return (legacy)","ASSET_RETURN")', 'self.regime_method.addItem("Asset trailing return","ASSET_RETURN")', "asset return label")
text = replace_once(
    text,
    '        self.bear_threshold=QDoubleSpinBox(); self.bear_threshold.setRange(-99.99,10000); self.bear_threshold.setSuffix(" %"); self.bear_threshold.setDecimals(2)\n',
    '',
    "bear threshold construction",
)
text = replace_once(
    text,
    '(("Regime method",self.regime_method),("Trend average",self.structural_sma_days),("Average slope",self.structural_slope_days),("Return lookback",self.regime_lookback),("Bull starts at",self.bull_threshold),("Bear starts at or below",self.bear_threshold),("ADX period",self.adx_period),("Bollinger period",self.bb_period),("Bollinger deviations",self.bb_stddevs))',
    '(("Regime method",self.regime_method),("Trend average",self.structural_sma_days),("Average slope",self.structural_slope_days),("Return lookback",self.regime_lookback),("Bull/Bear threshold magnitude",self.bull_threshold),("ADX period",self.adx_period),("Bollinger period",self.bb_period),("Bollinger deviations",self.bb_stddevs))',
    "regime definition rows",
)
text = replace_once(
    text,
    'for widget in (self.regime_lookback,self.bull_threshold,self.bear_threshold,self.structural_sma_days,self.structural_slope_days,self.adx_period,self.bb_period,self.bb_stddevs): widget.valueChanged.connect(self.changed)',
    'for widget in (self.regime_lookback,self.bull_threshold,self.structural_sma_days,self.structural_slope_days,self.adx_period,self.bb_period,self.bb_stddevs): widget.valueChanged.connect(self.changed)',
    "regime changed connections",
)
text = replace_once(
    text,
    '        for widget in (self.regime_lookback,self.bull_threshold,self.bear_threshold): self.definition_form.setRowVisible(widget,not structural)\n',
    '        for widget in (self.regime_lookback,self.bull_threshold): self.definition_form.setRowVisible(widget,not structural)\n',
    "regime control visibility",
)
path.write_text(text, encoding="utf-8")


# engine.py: remove dead StrategyProfile compatibility helpers that reference
# fields deleted from the current profile schema.
path = ROOT / "crypto_strategy_lab/engine.py"
text = path.read_text(encoding="utf-8")
text = remove_between(
    text,
    "    def _strategy_profile_flip_match(self, i, direction, profile):\n",
    "    def _strategy_profile_rule_value(self, i, direction, profile, indicator):\n",
    "legacy profile flip helpers",
)
text = remove_between(
    text,
    "    def _strategy_profile_additional_flip_match(self, i, direction, profile):\n",
    "    def _adx_filter_result(self, i):\n",
    "legacy additional flip helpers",
)
path.write_text(text, encoding="utf-8")

print("Stage 19 follow-up cleanup applied")
