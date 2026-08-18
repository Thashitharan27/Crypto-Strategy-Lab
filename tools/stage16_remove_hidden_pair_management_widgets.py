from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main_path.read_text(encoding="utf-8")

# Remove the hidden both-open timeout widget/group near Core Strategy.
both_widget = re.compile(
    r'        self\.both_timeout=QCheckBox\("Enable Both-Open Timeout"\);.*?self\.both_timeout_help\.setWordWrap\(True\)\n'
)
text, count = both_widget.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not find both-open timeout widgets")

both_group = '''        both_open=group("Both-Open Timeout")\n        for lab,w in [("",self.both_timeout),("Maximum Time Open",timeout_row),("",self.both_timeout_help)]: both_open.addRow(lab,w)\n'''
if both_group not in text:
    raise RuntimeError("Stage 16 could not find both-open timeout group")
text = text.replace(both_group, "", 1)

both_signal = '        self.both_timeout.toggled.connect(self.both_timeout_duration.setEnabled); self.both_timeout.toggled.connect(self.both_timeout_unit.setEnabled)\n'
if both_signal not in text:
    raise RuntimeError("Stage 16 could not find both-open timeout signal wiring")
text = text.replace(both_signal, "", 1)

# Remove all remaining hidden pair-level management groups: opposite-leg BE,
# remaining-leg timeout/checkpoint experiments, and the hidden BE calculator.
pair_groups = re.compile(
    r'        be_rule=group\("Break-Even After Opposite SL"\)\n.*?'
    r'        self\.be_label=QLabel\(\); self\.be_label\.setWordWrap\(True\); be\.addRow\(self\.be_label\)\n',
    re.S,
)
text, count = pair_groups.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not find hidden pair-management groups")

obsolete_line = '        for obsolete in (both_open,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n'
if obsolete_line not in text:
    raise RuntimeError("Stage 16 could not find final hidden-group visibility loop")
text = text.replace(obsolete_line, "", 1)

# Keep BacktestConfig compatibility internally but make the profile-only GUI
# emit the same inert defaults rather than hidden widget state.
old_both_values = '"enable_both_open_timeout":self.both_timeout.isChecked(),"max_both_open_minutes":self.both_timeout_duration.value()*(60 if self.both_timeout_unit.currentText()=="Hours" else 1),"both_open_timeout_unit":self.both_timeout_unit.currentText(),'
new_both_values = '"enable_both_open_timeout":False,"max_both_open_minutes":480,"both_open_timeout_unit":"Hours",'
if old_both_values not in text:
    raise RuntimeError("Stage 16 could not find both-open runtime values")
text = text.replace(old_both_values, new_both_values, 1)

old_remaining_values = '"enable_remaining_leg_timeout_after_first_sl":self.remaining_leg_timeout.isChecked(),"remaining_leg_timeout_after_first_sl_minutes":self.remaining_leg_timeout_duration.value()*(60 if self.remaining_leg_timeout_unit.currentText()=="Hours" else 1),"remaining_leg_timeout_after_first_sl_unit":self.remaining_leg_timeout_unit.currentText(),"enable_remaining_leg_timeout_profit_extension":self.remaining_leg_timeout_profit_extension.isChecked(),"remaining_leg_timeout_profit_threshold_r":self.remaining_leg_timeout_profit_threshold_r.value(),'
new_remaining_values = '"enable_remaining_leg_timeout_after_first_sl":False,"remaining_leg_timeout_after_first_sl_minutes":240,"remaining_leg_timeout_after_first_sl_unit":"Hours","enable_remaining_leg_timeout_profit_extension":False,"remaining_leg_timeout_profit_threshold_r":10.0,'
if old_remaining_values not in text:
    raise RuntimeError("Stage 16 could not find remaining-leg runtime values")
text = text.replace(old_remaining_values, new_remaining_values, 1)

old_be_values = '"enable_be_after_opposite_sl":self.be_after_sl.isChecked(),"be_mode":self.be_mode.currentText(),"be_offset_r":self.be_offset.value(),"be_same_candle_policy":self.be_same_candle.currentText(),'
new_be_values = '"enable_be_after_opposite_sl":False,"be_mode":"ENTRY_PRICE","be_offset_r":0.0,"be_same_candle_policy":"NEXT_CANDLE",'
if old_be_values not in text:
    raise RuntimeError("Stage 16 could not find opposite-leg BE runtime values")
text = text.replace(old_be_values, new_be_values, 1)

checkpoint_pattern = re.compile(
    r'        values\["enable_reentry_gate_after_remaining_leg_timeout"\] = self\.reentry_gate_after_timeout\.isChecked\(\)\n'
    r'        values\.update\(\{\n'
    r'.*?'
    r'        \}\)\n'
    r'        values\.update\(self\.profile_editor\.values\(\)\)\n',
    re.S,
)
checkpoint_replacement = '''        values.update({\n            "enable_reentry_gate_after_remaining_leg_timeout":False,\n            "enable_remaining_leg_checkpoint_score_extension":False,\n            "checkpoint_score_use_profit":True,\n            "checkpoint_score_min_profit_r":0.85,\n            "checkpoint_score_use_atr_pct":True,\n            "checkpoint_score_max_atr_pct":0.08,\n            "checkpoint_score_use_directional_di":True,\n            "checkpoint_score_min_directional_di":2.3,\n            "checkpoint_score_use_bb_width_pct":True,\n            "checkpoint_score_max_bb_width_pct":0.349,\n            "checkpoint_score_min_conditions":3,\n            "enable_first_sl_survivor_partial_close":False,\n            "first_sl_survivor_partial_close_pct":25.0,\n            "enable_checkpoint_zero_score_confirmation":False,\n            "checkpoint_zero_score_confirmations_required":2,\n            "checkpoint_zero_score_recheck_minutes":120,\n            "checkpoint_zero_score_recheck_unit":"Hours",\n        })\n        values.update(self.profile_editor.values())\n'''
text, count = checkpoint_pattern.subn(checkpoint_replacement, text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not replace checkpoint/remaining-leg values block")

# The helper only drove widgets that no longer exist.
helper_pattern = re.compile(
    r'    def _update_checkpoint_score_controls\(self,\*_\):\n.*?'
    r'(?=    def _apply_analysis_preset)',
    re.S,
)
text, count = helper_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not remove checkpoint widget-state helper")

# The hidden break-even calculator was the final non-profile consumer of the
# hidden global SL/TP controls. Remove only that presentation block.
be_calc_pattern = re.compile(
    r'        try: be=theoretical_break_even\(self\.sl\.value\(\),self\.tp\.value\(\)\);.*?\n'
    r'        except Exception: pass\n',
    re.S,
)
text, count = be_calc_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not remove hidden break-even calculator update")

# Drop apply_values plumbing for all deleted pair-management widgets.
both_apply_pattern = re.compile(
    r'        self\.both_timeout\.setChecked\(bool\(values\.get\("enable_both_open_timeout", False\)\)\)\n'
    r'        mins=int\(values\.get\("max_both_open_minutes", 480\)\);.*?\n'
    r'        self\.both_timeout_duration\.setEnabled\(self\.both_timeout\.isChecked\(\)\); self\.both_timeout_unit\.setEnabled\(self\.both_timeout\.isChecked\(\)\)\n',
    re.S,
)
text, count = both_apply_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not remove both-open apply_values plumbing")

remaining_apply_pattern = re.compile(
    r'        self\.remaining_leg_timeout\.setChecked\(bool\(values\.get\("enable_remaining_leg_timeout_after_first_sl", False\)\)\)\n'
    r'.*?'
    r'        self\._update_checkpoint_score_controls\(\)\n',
    re.S,
)
text, count = remaining_apply_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 16 could not remove remaining-leg apply_values plumbing")

be_apply = '''        self.be_after_sl.setChecked(bool(values.get("enable_be_after_opposite_sl", False)))\n        self.be_mode.setCurrentText(values.get("be_mode", "ENTRY_PRICE")); self.be_offset.setValue(float(values.get("be_offset_r", 0.0))); self.be_same_candle.setCurrentText(values.get("be_same_candle_policy", "NEXT_CANDLE")); self.be_offset.setEnabled(self.be_mode.currentText()=="R_OFFSET")\n'''
if be_apply not in text:
    raise RuntimeError("Stage 16 could not find opposite-leg BE apply_values plumbing")
text = text.replace(be_apply, "", 1)

removed_attrs = (
    "both_timeout", "both_timeout_duration", "both_timeout_unit", "both_timeout_help",
    "be_after_sl", "be_mode", "be_offset", "be_same_candle", "be_help", "be_label",
    "remaining_leg_timeout", "remaining_leg_timeout_duration", "remaining_leg_timeout_unit",
    "remaining_leg_timeout_profit_extension", "remaining_leg_timeout_profit_threshold_r",
    "reentry_gate_after_timeout", "checkpoint_score_extension", "checkpoint_score_use_profit",
    "checkpoint_score_min_profit_r", "checkpoint_score_use_atr", "checkpoint_score_max_atr_pct",
    "checkpoint_score_use_di", "checkpoint_score_min_di", "checkpoint_score_use_bb",
    "checkpoint_score_max_bb_pct", "checkpoint_score_required", "first_sl_survivor_partial",
    "first_sl_survivor_partial_pct", "zero_score_confirmation", "zero_score_confirmations",
    "zero_score_recheck_duration", "zero_score_recheck_unit",
)
remaining = []
for attr in removed_attrs:
    for lineno, line in enumerate(text.splitlines(), 1):
        if f"self.{attr}" in line:
            remaining.append(f"line {lineno}: self.{attr}: {line.strip()}")
if remaining:
    raise RuntimeError("Stage 16 hidden pair-management references remain:\n" + "\n".join(remaining))
if "_update_checkpoint_score_controls" in text:
    raise RuntimeError("Stage 16 checkpoint widget-state helper remains")
for title in ("Both-Open Timeout", "Break-Even After Opposite SL", "Remaining Leg Timeout After First SL", "Break-Even Calculator"):
    if f'group("{title}")' in text:
        raise RuntimeError(f"Stage 16 hidden group remains: {title}")

main_path.write_text(text, encoding="utf-8")

regression = ROOT / "tests" / "test_stage16_hidden_pair_management_gui_removed.py"
regression.write_text('''from pathlib import Path\n\nfrom PySide6.QtWidgets import QApplication, QGroupBox\n\nfrom crypto_strategy_lab.gui.config_logic import default_gui_config\nfrom crypto_strategy_lab.gui.main_window import MainWindow\n\n\ndef app():\n    return QApplication.instance() or QApplication([])\n\n\ndef test_hidden_pair_management_widgets_are_not_constructed():\n    app()\n    window = MainWindow()\n    try:\n        removed = (\n            "both_timeout", "both_timeout_duration", "both_timeout_unit",\n            "be_after_sl", "be_mode", "be_offset", "be_same_candle",\n            "remaining_leg_timeout", "remaining_leg_timeout_duration", "remaining_leg_timeout_unit",\n            "remaining_leg_timeout_profit_extension", "reentry_gate_after_timeout",\n            "checkpoint_score_extension", "first_sl_survivor_partial", "zero_score_confirmation",\n            "be_label",\n        )\n        for name in removed:\n            assert not hasattr(window, name)\n        titles = {box.title() for box in window.findChildren(QGroupBox)}\n        assert "Both-Open Timeout" not in titles\n        assert "Break-Even After Opposite SL" not in titles\n        assert "Remaining Leg Timeout After First SL" not in titles\n        assert "Break-Even Calculator" not in titles\n    finally:\n        window.close()\n\n\ndef test_retired_pair_globals_stay_inert_while_profile_timeout_and_be_survive():\n    app()\n    window = MainWindow()\n    try:\n        values = default_gui_config()\n        values.update({\n            "enable_both_open_timeout": True,\n            "max_both_open_minutes": 60,\n            "enable_be_after_opposite_sl": True,\n            "be_mode": "R_OFFSET",\n            "be_offset_r": 0.5,\n            "enable_remaining_leg_timeout_after_first_sl": True,\n            "enable_remaining_leg_timeout_profit_extension": True,\n            "enable_remaining_leg_checkpoint_score_extension": True,\n            "enable_first_sl_survivor_partial_close": True,\n            "enable_checkpoint_zero_score_confirmation": True,\n            "enable_reentry_gate_after_remaining_leg_timeout": True,\n        })\n        profile = values["strategy_profiles"]["bull_long"]\n        profile.update({\n            "timeout_enabled": True,\n            "timeout_minutes": 180,\n            "break_even_enabled": True,\n            "break_even_activation_r": 1.5,\n            "break_even_offset_r": 0.2,\n        })\n        window.apply_values(values)\n        current = window.values()\n\n        assert current["enable_both_open_timeout"] is False\n        assert current["max_both_open_minutes"] == 480\n        assert current["enable_be_after_opposite_sl"] is False\n        assert current["be_mode"] == "ENTRY_PRICE"\n        assert current["enable_remaining_leg_timeout_after_first_sl"] is False\n        assert current["enable_remaining_leg_timeout_profit_extension"] is False\n        assert current["enable_remaining_leg_checkpoint_score_extension"] is False\n        assert current["enable_first_sl_survivor_partial_close"] is False\n        assert current["enable_checkpoint_zero_score_confirmation"] is False\n        assert current["enable_reentry_gate_after_remaining_leg_timeout"] is False\n        bull_long = current["strategy_profiles"]["bull_long"]\n        assert bull_long["timeout_enabled"] is True\n        assert bull_long["timeout_minutes"] == 180\n        assert bull_long["break_even_enabled"] is True\n        assert bull_long["break_even_activation_r"] == 1.5\n        assert bull_long["break_even_offset_r"] == 0.2\n    finally:\n        window.close()\n\n\ndef test_main_window_source_has_no_hidden_pair_management_plumbing():\n    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    for fragment in (\n        'group("Both-Open Timeout")',\n        'group("Break-Even After Opposite SL")',\n        'group("Remaining Leg Timeout After First SL")',\n        'group("Break-Even Calculator")',\n        "self.both_timeout",\n        "self.be_after_sl",\n        "self.remaining_leg_timeout",\n        "_update_checkpoint_score_controls",\n    ):\n        assert fragment not in source\n''', encoding="utf-8")

print("Stage 16 hidden pair-management GUI widgets removed")
