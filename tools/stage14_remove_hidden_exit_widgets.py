from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main_path.read_text(encoding="utf-8")

# Remove the hidden global exit-management widgets now duplicated by each
# Strategy Profile (partial stop, partial profit, post-TP1 protection, trailing).
widget_pattern = re.compile(
    r'        self\.enable_partial_tp=QCheckBox\("Enable Partial Take Profit"\).*?'
    r'        self\.trail_intrabar_mode=QComboBox\(\); self\.trail_intrabar_mode\.addItems\(\["PESSIMISTIC","OPTIMISTIC"\]\); self\.trail_intrabar_mode\.setToolTip\("Controls same-candle ordering for both whole-position and after-TP1 trailing\."\)\n',
    re.S,
)
text, count = widget_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 14 could not find hidden global exit widget construction")

group_pattern = re.compile(
    r'        partial_sl=group\("Partial Stop Loss"\)\n.*?'
    r'        \]: trailing\.addRow\(lab,w\)\n',
    re.S,
)
text, count = group_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 14 could not find hidden global exit groups")

old_obsolete = "        for obsolete in (partial_sl,partial_tp,protective_stop,trailing,both_open,vwap_group,random_group,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
new_obsolete = "        for obsolete in (both_open,vwap_group,random_group,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
if old_obsolete not in text:
    raise RuntimeError("Stage 14 could not find hidden-group visibility list")
text = text.replace(old_obsolete, new_obsolete, 1)

old_runtime = '"trade_direction":self.trade_direction.currentText(),"enable_partial_take_profit":self.enable_partial_tp.isChecked(),"enable_partial_stop_loss":self.enable_partial_sl.isChecked(),"sl1_r":self.sl1_r.value(),"sl1_close_pct":self.sl1_close_pct.value(),"sl2_r":self.sl2_r.value(),"tp1_r":self.tp1_r.value(),"tp1_close_pct":self.tp1_close_pct.value(),"tp2_r":self.tp2_r.value(),"tp2_close_pct":self.tp2_close_pct.value(),"stop_loss_r":self.stop_loss_r.value(),"after_tp1_stop_mode":self.after_tp1_stop_mode.currentText(),"after_tp1_stop_offset_r":self.after_tp1_stop_offset_r.value(),"tp2_exit_mode":"FIXED_TP2","enable_trailing_profit":self.enable_trailing_profit.isChecked(),"trail_activation_trigger":self.trail_activation_trigger.currentText(),"trail_activation_r":self.trail_activation_r.value(),"trail_distance_r":self.trail_distance_r.value(),"trail_apply_to":self.trail_apply_to.currentText(),"trail_intrabar_mode":self.trail_intrabar_mode.currentText(),'
new_runtime = '"trade_direction":self.trade_direction.currentText(),"enable_partial_take_profit":False,"enable_partial_stop_loss":False,"sl1_r":0.5,"sl1_close_pct":50.0,"sl2_r":8.0,"tp1_r":3.0,"tp1_close_pct":50.0,"tp2_r":12.0,"tp2_close_pct":50.0,"stop_loss_r":10.0,"after_tp1_stop_mode":"KEEP_ORIGINAL_SL","after_tp1_stop_offset_r":0.0,"tp2_exit_mode":"FIXED_TP2","enable_trailing_profit":False,"trail_activation_trigger":"PRICE_REACHES_R","trail_activation_r":3.0,"trail_distance_r":1.0,"trail_apply_to":"BOTH","trail_intrabar_mode":"PESSIMISTIC",'
if old_runtime not in text:
    raise RuntimeError("Stage 14 could not find hidden exit runtime values")
text = text.replace(old_runtime, new_runtime, 1)

extra_values = '        values.update({"enable_partial_stop_loss":self.enable_partial_sl.isChecked(),"sl1_r":self.sl1_r.value(),"sl1_close_pct":self.sl1_close_pct.value(),"sl2_r":self.sl2_r.value()})\n'
if extra_values not in text:
    raise RuntimeError("Stage 14 could not find duplicate partial-stop values update")
text = text.replace(extra_values, "", 1)

apply_lines = [
    '        self.enable_partial_tp.setChecked(bool(values.get("enable_partial_take_profit",False))); self.tp1_r.setValue(float(values.get("tp1_r",3))); self.tp1_close_pct.setValue(float(values.get("tp1_close_pct",50))); self.tp2_r.setValue(float(values.get("tp2_r",12))); self.tp2_close_pct.setValue(float(values.get("tp2_close_pct",50))); self.stop_loss_r.setValue(float(values.get("stop_loss_r",10))); self.after_tp1_stop_mode.setCurrentText(str(values.get("after_tp1_stop_mode","KEEP_ORIGINAL_SL"))); self.after_tp1_stop_offset_r.setValue(float(values.get("after_tp1_stop_offset_r",0))); self.tp2_exit_mode.setCurrentText(str(values.get("tp2_exit_mode","FIXED_TP2")));\n',
    '        self.enable_partial_sl.setChecked(bool(values.get("enable_partial_stop_loss",False))); self.sl1_r.setValue(float(values.get("sl1_r",0.5))); self.sl1_close_pct.setValue(float(values.get("sl1_close_pct",50))); self.sl2_r.setValue(float(values.get("sl2_r",8)))\n',
]
for line in apply_lines:
    if line not in text:
        raise RuntimeError(f"Stage 14 could not find apply_values exit line: {line.strip()[:60]}")
    text = text.replace(line, "", 1)

old_mixed = '        self.zero_cost.setChecked(bool(values["zero_cost_comparison"])); self.trade_direction.setCurrentText(str(values.get("trade_direction", "BOTH"))); self.enable_trailing_profit.setChecked(bool(values.get("enable_trailing_profit",False) or values.get("tp2_exit_mode")=="TRAILING_AFTER_TP1")); self.trail_activation_trigger.setCurrentText(str(values.get("trail_activation_trigger","AFTER_TP1" if values.get("tp2_exit_mode")=="TRAILING_AFTER_TP1" else "PRICE_REACHES_R"))); self.trail_activation_r.setValue(float(values.get("trail_activation_r",3))); self.trail_distance_r.setValue(float(values.get("trail_distance_r",1))); self.trail_apply_to.setCurrentText(str(values.get("trail_apply_to","BOTH"))); self.trail_intrabar_mode.setCurrentText(str(values.get("trail_intrabar_mode","PESSIMISTIC")))\n'
new_mixed = '        self.zero_cost.setChecked(bool(values["zero_cost_comparison"])); self.trade_direction.setCurrentText(str(values.get("trade_direction", "BOTH")))\n'
if old_mixed not in text:
    raise RuntimeError("Stage 14 could not find mixed trade-direction/trailing apply line")
text = text.replace(old_mixed, new_mixed, 1)

# Remove dynamic logic that only operated the deleted hidden widgets.
dynamic_pattern = re.compile(
    r'        if hasattr\(self,"enable_partial_sl"\):\n.*?'
    r'                self\.trailing_help\.setText\("Enable trailing to tighten the active protective stop independently\. Fixed TP2 and SL2 remain final exits\."\)\n',
    re.S,
)
text, count = dynamic_pattern.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 14 could not find hidden exit dynamic block")

removed_attrs = (
    "enable_partial_tp", "tp1_r", "tp1_close_pct", "tp2_r", "tp2_close_pct",
    "stop_loss_r", "after_tp1_stop_mode", "after_tp1_stop_offset_r", "tp2_exit_mode",
    "enable_partial_sl", "sl1_r", "sl1_close_pct", "sl2_r",
    "enable_trailing_profit", "trail_activation_trigger", "trail_activation_r",
    "trail_distance_r", "trail_apply_to", "trail_intrabar_mode",
    "protective_stop_help", "trailing_help",
)
for attr in removed_attrs:
    if f"self.{attr}" in text:
        raise RuntimeError(f"Stage 14 deleted-widget reference remains: self.{attr}")
for title in ("Partial Stop Loss", "Partial Take Profit", "Post-TP1 Protective Stop", "Independent Trailing Stop"):
    if f'group("{title}")' in text:
        raise RuntimeError(f"Stage 14 hidden group remains: {title}")

main_path.write_text(text, encoding="utf-8")

regression = ROOT / "tests" / "test_stage14_hidden_exit_gui_removed.py"
regression.write_text('''from pathlib import Path\n\nfrom PySide6.QtWidgets import QApplication, QGroupBox\n\nfrom crypto_strategy_lab.gui.config_logic import default_gui_config\nfrom crypto_strategy_lab.gui.main_window import MainWindow\n\n\ndef app():\n    return QApplication.instance() or QApplication([])\n\n\ndef test_hidden_global_exit_widgets_are_not_constructed():\n    app()\n    window = MainWindow()\n    try:\n        removed = (\n            "enable_partial_tp", "tp1_r", "tp1_close_pct", "tp2_r", "tp2_close_pct",\n            "stop_loss_r", "after_tp1_stop_mode", "after_tp1_stop_offset_r", "tp2_exit_mode",\n            "enable_partial_sl", "sl1_r", "sl1_close_pct", "sl2_r",\n            "enable_trailing_profit", "trail_activation_trigger", "trail_activation_r",\n            "trail_distance_r", "trail_apply_to", "trail_intrabar_mode",\n        )\n        for name in removed:\n            assert not hasattr(window, name)\n        titles = {box.title() for box in window.findChildren(QGroupBox)}\n        assert "Partial Stop Loss" not in titles\n        assert "Partial Take Profit" not in titles\n        assert "Post-TP1 Protective Stop" not in titles\n        assert "Independent Trailing Stop" not in titles\n    finally:\n        window.close()\n\n\ndef test_global_exit_values_stay_inert_while_profiles_own_exit_management():\n    app()\n    window = MainWindow()\n    try:\n        values = default_gui_config()\n        values.update({\n            "enable_partial_stop_loss": True,\n            "enable_partial_take_profit": True,\n            "enable_trailing_profit": True,\n        })\n        profile = values["strategy_profiles"]["bull_long"]\n        profile.update({\n            "partial_stop_enabled": True,\n            "sl1_r": 0.75,\n            "sl2_r": 2.5,\n            "partial_profit_enabled": True,\n            "tp1_r": 1.25,\n            "tp2_r": 3.0,\n            "trailing_enabled": True,\n            "trailing_activation_r": 2.5,\n            "trailing_distance_r": 0.75,\n        })\n        window.apply_values(values)\n        current = window.values()\n\n        assert current["enable_partial_stop_loss"] is False\n        assert current["enable_partial_take_profit"] is False\n        assert current["enable_trailing_profit"] is False\n        bull_long = current["strategy_profiles"]["bull_long"]\n        assert bull_long["partial_stop_enabled"] is True\n        assert bull_long["sl1_r"] == 0.75\n        assert bull_long["partial_profit_enabled"] is True\n        assert bull_long["tp2_r"] == 3.0\n        assert bull_long["trailing_enabled"] is True\n        assert bull_long["trailing_distance_r"] == 0.75\n    finally:\n        window.close()\n\n\ndef test_main_window_source_has_no_hidden_global_exit_plumbing():\n    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    for fragment in (\n        'group("Partial Stop Loss")',\n        'group("Partial Take Profit")',\n        'group("Post-TP1 Protective Stop")',\n        'group("Independent Trailing Stop")',\n        "self.enable_partial_sl",\n        "self.enable_partial_tp",\n        "self.enable_trailing_profit",\n    ):\n        assert fragment not in source\n''', encoding="utf-8")

print("Stage 14 hidden global exit-management widgets removed")
