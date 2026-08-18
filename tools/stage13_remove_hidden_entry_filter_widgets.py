from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main_path.read_text(encoding="utf-8")

# Keep the shared ADX calculation period as non-widget state. The profile model
# owns ADX thresholds, but its calculations still use the shared BacktestConfig
# adx_period.
needle = "        self.settings = QSettings(\"LongShortCrypto\", \"Backtester\"); self.worker=None; self.thread=None; self.portfolio_worker=None; self.portfolio_thread=None; self.started=0; self.last_summary={}; self.output_dir=Path(\"output\"); self.completed_run_dir=None; self._pending_ui_results=None; self._run_failed=False\n"
replacement = needle + "        self._shared_adx_period = int(DEFAULT_GUI_CONFIG[\"adx_period\"])\n"
if needle not in text:
    raise RuntimeError("Stage 13 could not find MainWindow state initialization")
text = text.replace(needle, replacement, 1)

# Remove the two completely hidden legacy entry-filter groups. Strategy Profiles
# now own ADX/BB-width/DI-spread entry rules; the Monday one-off was also hidden
# and is intentionally left disabled by the profile-only GUI.
pattern = re.compile(
    r'        trend=group\("Trend Filter"\)\n'
    r'.*?'
    r'        for w in \[self\.enable_bb_width,self\.bb_width_mode,self\.skip_monday_entries,self\.enable_di_spread,self\.di_spread_mode\]: w\.toggled\.connect\(self\.update_dynamic\) if hasattr\(w,"toggled"\) else w\.currentTextChanged\.connect\(self\.update_dynamic\)\n',
    re.S,
)
text, count = pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 13 could not find hidden Trend/Compression groups")

old_obsolete = "        for obsolete in (partial_sl,partial_tp,protective_stop,trailing,both_open,vwap_group,random_group,trend,compression,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
new_obsolete = "        for obsolete in (partial_sl,partial_tp,protective_stop,trailing,both_open,vwap_group,random_group,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
if old_obsolete not in text:
    raise RuntimeError("Stage 13 could not find hidden-group visibility list")
text = text.replace(old_obsolete, new_obsolete, 1)

old_runtime = '"enable_adx_filter":self.enable_adx.isChecked(),"adx_period":self.adx_period.value(),"adx_filter_mode":self.adx_mode.currentText(),"adx_maximum":self.adx_max.value(),"adx_minimum":self.adx_min.value(),"enable_bb_width_filter":self.enable_bb_width.isChecked(),"bb_width_filter_mode":self.bb_width_mode.currentText(),"bb_width_maximum":self.bb_width_max.value(),"bb_width_minimum":self.bb_width_min.value(),"enable_di_spread_filter":self.enable_di_spread.isChecked(),"di_spread_filter_mode":self.di_spread_mode.currentText(),"di_spread_maximum":self.di_spread_max.value(),"di_spread_minimum":self.di_spread_min.value(),'
new_runtime = '"enable_adx_filter":False,"adx_period":self._shared_adx_period,"adx_filter_mode":"Disabled","adx_maximum":25.0,"adx_minimum":20.0,"enable_bb_width_filter":False,"bb_width_filter_mode":"Disabled","bb_width_maximum":0.03,"bb_width_minimum":0.012,"enable_di_spread_filter":False,"di_spread_filter_mode":"Disabled","di_spread_maximum":10.0,"di_spread_minimum":0.0,'
if old_runtime not in text:
    raise RuntimeError("Stage 13 could not find hidden filter runtime values")
text = text.replace(old_runtime, new_runtime, 1)

old_skip = '"enable_skip_monday_entries":self.skip_monday_entries.isChecked(),"skip_monday_timezone":self.skip_monday_timezone.text().strip(),'
new_skip = '"enable_skip_monday_entries":False,"skip_monday_timezone":"UTC",'
if old_skip not in text:
    raise RuntimeError("Stage 13 could not find hidden Monday runtime values")
text = text.replace(old_skip, new_skip, 1)

apply_lines = [
    '        self.enable_adx.setChecked(bool(values.get("enable_adx_filter", False))); self.adx_period.setValue(int(values.get("adx_period", 14))); self.adx_mode.setCurrentText(values.get("adx_filter_mode", "Disabled")); self.adx_max.setValue(float(values.get("adx_maximum", 25.0))); self.adx_min.setValue(float(values.get("adx_minimum", 20.0)))\n',
    '        self.enable_bb_width.setChecked(bool(values.get("enable_bb_width_filter", False))); self.bb_width_mode.setCurrentText(values.get("bb_width_filter_mode", "Disabled")); self.bb_width_max.setValue(float(values.get("bb_width_maximum", 0.03))); self.bb_width_min.setValue(float(values.get("bb_width_minimum", 0.012)))\n',
    '        self.skip_monday_entries.setChecked(bool(values.get("enable_skip_monday_entries", False))); self.skip_monday_timezone.setText(str(values.get("skip_monday_timezone", "UTC")))\n',
    '        self.enable_di_spread.setChecked(bool(values.get("enable_di_spread_filter", False))); self.di_spread_mode.setCurrentText(values.get("di_spread_filter_mode", "Disabled")); self.di_spread_max.setValue(float(values.get("di_spread_maximum", 10.0))); self.di_spread_min.setValue(float(values.get("di_spread_minimum", 0.0)))\n',
]
for line in apply_lines:
    if line not in text:
        raise RuntimeError(f"Stage 13 could not find apply_values legacy line: {line.strip()[:50]}")
    text = text.replace(line, "", 1)
anchor = '        self.slippage.setText(format_percentage(float(values["slippage"])))\n'
if anchor not in text:
    raise RuntimeError("Stage 13 could not find apply_values ADX-period anchor")
text = text.replace(anchor, anchor + '        self._shared_adx_period = int(values.get("adx_period", 14))\n', 1)

# Remove dynamic enable/disable logic that existed only for the deleted widgets.
for block_pattern, label in [
    (
        r'        if hasattr\(self,"adx_mode"\):\n'
        r'            enabled=self\.enable_adx\.isChecked\(\) and self\.adx_mode\.currentText\(\) != "Disabled"\n'
        r'            self\.adx_period\.setEnabled\(self\.enable_adx\.isChecked\(\)\)\n'
        r'            self\.adx_mode\.setEnabled\(self\.enable_adx\.isChecked\(\)\)\n'
        r'            self\.adx_max\.setEnabled\(enabled and self\.adx_mode\.currentText\(\) in \("ADX <= Maximum","Range"\)\)\n'
        r'            self\.adx_min\.setEnabled\(enabled and self\.adx_mode\.currentText\(\) in \("ADX >= Minimum","Range"\)\)\n',
        "ADX dynamic block",
    ),
    (
        r'        if hasattr\(self,"bb_width_mode"\):\n'
        r'            bben=self\.enable_bb_width\.isChecked\(\) and self\.bb_width_mode\.currentText\(\) != "Disabled"\n'
        r'            self\.bb_width_mode\.setEnabled\(self\.enable_bb_width\.isChecked\(\)\); self\.bb_width_max\.setEnabled\(bben and self\.bb_width_mode\.currentText\(\) in \("Maximum Width","Range"\)\); self\.bb_width_min\.setEnabled\(bben and self\.bb_width_mode\.currentText\(\) in \("Minimum Width","Range"\)\)\n'
        r'            self\.skip_monday_timezone\.setEnabled\(self\.skip_monday_entries\.isChecked\(\)\)\n'
        r'            dien=self\.enable_di_spread\.isChecked\(\) and self\.di_spread_mode\.currentText\(\) != "Disabled"\n'
        r'            self\.di_spread_mode\.setEnabled\(self\.enable_di_spread\.isChecked\(\)\); self\.di_spread_max\.setEnabled\(dien and self\.di_spread_mode\.currentText\(\) in \("Maximum Spread","Range"\)\); self\.di_spread_min\.setEnabled\(dien and self\.di_spread_mode\.currentText\(\) in \("Minimum Spread","Range"\)\)\n',
        "BB/DI dynamic block",
    ),
]:
    text, n = re.subn(block_pattern, "", text, count=1)
    if n != 1:
        raise RuntimeError(f"Stage 13 could not find {label}")

for forbidden in (
    'group("Trend Filter")',
    'group("Market Compression Filters")',
    'self.enable_adx=', 'self.adx_mode=', 'self.adx_max=', 'self.adx_min=', 'self.adx_period=',
    'self.enable_bb_width=', 'self.bb_width_mode=', 'self.bb_width_min=', 'self.bb_width_max=',
    'self.skip_monday_entries=', 'self.skip_monday_timezone=',
    'self.enable_di_spread=', 'self.di_spread_mode=', 'self.di_spread_min=', 'self.di_spread_max=',
):
    if forbidden in text:
        raise RuntimeError(f"Stage 13 legacy GUI construction remains: {forbidden}")

main_path.write_text(text, encoding="utf-8")

regression = ROOT / "tests" / "test_stage13_hidden_entry_filter_gui_removed.py"
regression.write_text('''from pathlib import Path\n\nfrom PySide6.QtWidgets import QApplication, QGroupBox\n\nfrom crypto_strategy_lab.gui.main_window import MainWindow\n\n\ndef app():\n    return QApplication.instance() or QApplication([])\n\n\ndef test_hidden_global_entry_filter_widgets_are_not_constructed():\n    app()\n    window = MainWindow()\n    try:\n        removed = (\n            "enable_adx", "adx_period", "adx_mode", "adx_max", "adx_min",\n            "enable_bb_width", "bb_width_mode", "bb_width_min", "bb_width_max",\n            "skip_monday_entries", "skip_monday_timezone",\n            "enable_di_spread", "di_spread_mode", "di_spread_min", "di_spread_max",\n        )\n        for name in removed:\n            assert not hasattr(window, name)\n        titles = {box.title() for box in window.findChildren(QGroupBox)}\n        assert "Trend Filter" not in titles\n        assert "Market Compression Filters" not in titles\n    finally:\n        window.close()\n\n\ndef test_runtime_keeps_legacy_global_filters_inert_but_preserves_shared_adx_period():\n    app()\n    window = MainWindow()\n    try:\n        window.apply_values({\n            "adx_period": 21,\n            "enable_adx_filter": True,\n            "adx_filter_mode": "ADX >= Minimum",\n            "adx_minimum": 33.0,\n            "enable_bb_width_filter": True,\n            "enable_skip_monday_entries": True,\n            "enable_di_spread_filter": True,\n        })\n        values = window.values()\n        assert values["adx_period"] == 21\n        assert values["enable_adx_filter"] is False\n        assert values["adx_filter_mode"] == "Disabled"\n        assert values["enable_bb_width_filter"] is False\n        assert values["enable_skip_monday_entries"] is False\n        assert values["enable_di_spread_filter"] is False\n    finally:\n        window.close()\n\n\ndef test_main_window_source_has_no_hidden_entry_filter_group_plumbing():\n    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    for fragment in (\n        'group("Trend Filter")',\n        'group("Market Compression Filters")',\n        "self.enable_adx=",\n        "self.enable_bb_width=",\n        "self.skip_monday_entries=",\n        "self.enable_di_spread=",\n    ):\n        assert fragment not in source\n''', encoding="utf-8")

print("Stage 13 hidden entry-filter GUI widgets removed")
