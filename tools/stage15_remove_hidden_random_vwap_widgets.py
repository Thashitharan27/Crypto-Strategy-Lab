from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "crypto_strategy_lab" / "gui" / "main_window.py"
text = main_path.read_text(encoding="utf-8")

# The current entry-mode selector no longer exposes VWAP breakout or random
# entry experiments. Remove the hidden widget groups instead of constructing
# controls that cannot participate in the profile-only GUI.
hidden_groups = re.compile(
    r'        vwap_group=group\("VWAP Volume Breakout"\)\n.*?'
    r'        random_group\.addRow\("",self\.enable_coin_flip_sizing\); random_group\.addRow\("Coin Flip Seed",self\.coin_flip_seed\)\n',
    re.S,
)
text, count = hidden_groups.subn("", text, count=1)
if count != 1:
    raise RuntimeError("Stage 15 could not find hidden VWAP/random GUI groups")

old_obsolete = "        for obsolete in (both_open,vwap_group,random_group,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
new_obsolete = "        for obsolete in (both_open,be_rule,remaining_timeout,be): obsolete.parentWidget().setVisible(False)\n"
if old_obsolete not in text:
    raise RuntimeError("Stage 15 could not find hidden-group visibility list")
text = text.replace(old_obsolete, new_obsolete, 1)

old_random = '"enable_random_entry":self.enable_random_entry.isChecked(),"entry_timing_mode":self.entry_timing_mode.currentText(),"random_entry_probability":self.random_probability.value(),"random_seed":self.random_seed.text().strip(),"random_entry_start_mode":self.random_start_mode.currentText(),"randomize_first_entry":self.randomize_first.isChecked(),"max_random_wait_candles":self.max_random_wait.value(),"enable_random_entry_batch":self.enable_random_batch.isChecked(),"random_seed_start":self.random_seed_start.value(),"random_seed_count":self.random_seed_count.value(),'
new_random = '"enable_random_entry":False,"entry_timing_mode":"CURRENT","random_entry_probability":0.5,"random_seed":42,"random_entry_start_mode":"NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE","randomize_first_entry":True,"max_random_wait_candles":0,"enable_random_entry_batch":False,"random_seed_start":1,"random_seed_count":100,'
if old_random not in text:
    raise RuntimeError("Stage 15 could not find hidden random-entry runtime values")
text = text.replace(old_random, new_random, 1)

old_vwap_values = '        values.update({"vwap_breakout_lookback_hours":self.vwap_breakout_hours.value(),"vwap_volume_lookback":self.vwap_volume_lookback.value(),"vwap_volume_multiplier":self.vwap_volume_multiplier.value(),"vwap_slope_lookback":self.vwap_slope_lookback.value(),"vwap_atr_pct_minimum":self.vwap_atr_min.value(),"vwap_atr_pct_maximum":self.vwap_atr_max.value(),"vwap_confirmation_mode":self.vwap_confirmation_mode.currentText(),"vwap_retest_window_candles":self.vwap_retest_window.value(),"vwap_retest_tolerance_atr":self.vwap_retest_tolerance.value()})\n'
new_vwap_values = '        values.update({"vwap_breakout_lookback_hours":4.0,"vwap_volume_lookback":20,"vwap_volume_multiplier":1.5,"vwap_slope_lookback":1,"vwap_atr_pct_minimum":0.0,"vwap_atr_pct_maximum":1.0,"vwap_confirmation_mode":"IMMEDIATE","vwap_retest_window_candles":4,"vwap_retest_tolerance_atr":0.25})\n'
if old_vwap_values not in text:
    raise RuntimeError("Stage 15 could not find hidden VWAP values update")
text = text.replace(old_vwap_values, new_vwap_values, 1)

old_coin_values = '        values.update({"enable_coin_flip_sizing":self.enable_coin_flip_sizing.isChecked(),"coin_flip_seed":self.coin_flip_seed.text().strip(),"coin_flip_large_multiplier":3.0,"coin_flip_small_multiplier":1.0})\n'
new_coin_values = '        values.update({"enable_coin_flip_sizing":False,"coin_flip_seed":42,"coin_flip_large_multiplier":3.0,"coin_flip_small_multiplier":1.0})\n'
if old_coin_values not in text:
    raise RuntimeError("Stage 15 could not find hidden coin-flip sizing values update")
text = text.replace(old_coin_values, new_coin_values, 1)

apply_lines = [
    '        self.vwap_breakout_hours.setValue(float(values.get("vwap_breakout_lookback_hours",4.0))); self.vwap_volume_lookback.setValue(int(values.get("vwap_volume_lookback",20))); self.vwap_volume_multiplier.setValue(float(values.get("vwap_volume_multiplier",1.5))); self.vwap_slope_lookback.setValue(int(values.get("vwap_slope_lookback",1))); self.vwap_atr_min.setValue(float(values.get("vwap_atr_pct_minimum",0))); self.vwap_atr_max.setValue(float(values.get("vwap_atr_pct_maximum",1))); self.vwap_confirmation_mode.setCurrentText(str(values.get("vwap_confirmation_mode","IMMEDIATE"))); self.vwap_retest_window.setValue(int(values.get("vwap_retest_window_candles",4))); self.vwap_retest_tolerance.setValue(float(values.get("vwap_retest_tolerance_atr",0.25)))\n',
    '        self.enable_random_entry.setChecked(bool(values.get("enable_random_entry",False))); self.entry_timing_mode.setCurrentText(str(values.get("entry_timing_mode","CURRENT"))); self.random_probability.setValue(float(values.get("random_entry_probability",0.5))); self.random_seed.setText(str(values.get("random_seed",42))); self.random_start_mode.setCurrentText(str(values.get("random_entry_start_mode","NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"))); self.randomize_first.setChecked(bool(values.get("randomize_first_entry",True))); self.max_random_wait.setValue(int(values.get("max_random_wait_candles",0))); self.enable_random_batch.setChecked(bool(values.get("enable_random_entry_batch",False))); self.random_seed_start.setValue(int(values.get("random_seed_start",1))); self.random_seed_count.setValue(int(values.get("random_seed_count",100)))\n',
    '        self.enable_coin_flip_sizing.setChecked(bool(values.get("enable_coin_flip_sizing",False))); self.coin_flip_seed.setText(str(values.get("coin_flip_seed",42)))\n',
]
for line in apply_lines:
    if line not in text:
        raise RuntimeError(f"Stage 15 could not find hidden-widget apply line: {line.strip()[:70]}")
    text = text.replace(line, "", 1)

vwap_dynamic = '''        if hasattr(self,"vwap_confirmation_mode"):\n            retest=self.entry_mode.currentData()=="VWAP_VOLUME_BREAKOUT" and self.vwap_confirmation_mode.currentText()=="RETEST"\n            self.vwap_retest_window.setEnabled(retest); self.vwap_retest_tolerance.setEnabled(retest)\n'''
if vwap_dynamic not in text:
    raise RuntimeError("Stage 15 could not find VWAP dynamic-state block")
text = text.replace(vwap_dynamic, "", 1)

removed_attrs = (
    "vwap_breakout_hours", "vwap_volume_lookback", "vwap_volume_multiplier", "vwap_slope_lookback",
    "vwap_atr_min", "vwap_atr_max", "vwap_confirmation_mode", "vwap_retest_window", "vwap_retest_tolerance",
    "enable_random_entry", "entry_timing_mode", "random_probability", "random_seed", "random_start_mode",
    "randomize_first", "max_random_wait", "enable_random_batch", "random_seed_start", "random_seed_count",
    "enable_coin_flip_sizing", "coin_flip_seed",
)
remaining = []
for attr in removed_attrs:
    for lineno, line in enumerate(text.splitlines(), 1):
        if f"self.{attr}" in line:
            remaining.append(f"line {lineno}: self.{attr}: {line.strip()}")
if remaining:
    raise RuntimeError("Stage 15 hidden-widget references remain:\n" + "\n".join(remaining))
for title in ("VWAP Volume Breakout", "Random Entry Timing"):
    if f'group("{title}")' in text:
        raise RuntimeError(f"Stage 15 hidden group remains: {title}")

main_path.write_text(text, encoding="utf-8")

regression = ROOT / "tests" / "test_stage15_hidden_random_vwap_gui_removed.py"
regression.write_text('''from pathlib import Path\n\nfrom PySide6.QtWidgets import QApplication, QGroupBox\n\nfrom crypto_strategy_lab.gui.config_logic import default_gui_config\nfrom crypto_strategy_lab.gui.main_window import MainWindow\n\n\ndef app():\n    return QApplication.instance() or QApplication([])\n\n\ndef test_hidden_random_vwap_widgets_are_not_constructed():\n    app()\n    window = MainWindow()\n    try:\n        removed = (\n            "vwap_breakout_hours", "vwap_volume_lookback", "vwap_volume_multiplier", "vwap_slope_lookback",\n            "vwap_atr_min", "vwap_atr_max", "vwap_confirmation_mode", "vwap_retest_window", "vwap_retest_tolerance",\n            "enable_random_entry", "entry_timing_mode", "random_probability", "random_seed", "random_start_mode",\n            "randomize_first", "max_random_wait", "enable_random_batch", "random_seed_start", "random_seed_count",\n            "enable_coin_flip_sizing", "coin_flip_seed",\n        )\n        for name in removed:\n            assert not hasattr(window, name)\n        titles = {box.title() for box in window.findChildren(QGroupBox)}\n        assert "VWAP Volume Breakout" not in titles\n        assert "Random Entry Timing" not in titles\n    finally:\n        window.close()\n\n\ndef test_retired_random_and_breakout_globals_stay_inert_while_profile_vwap_rule_survives():\n    app()\n    window = MainWindow()\n    try:\n        values = default_gui_config()\n        values.update({\n            "enable_random_entry": True,\n            "entry_timing_mode": "RANDOM_AFTER_PAIR_CLOSE",\n            "random_entry_probability": 0.9,\n            "enable_random_entry_batch": True,\n            "enable_coin_flip_sizing": True,\n            "vwap_breakout_lookback_hours": 24.0,\n            "vwap_confirmation_mode": "RETEST",\n        })\n        profile = values["strategy_profiles"]["bull_short"]\n        profile.update({\n            "vwap_distance_enabled": True,\n            "vwap_distance_minimum": -0.5,\n            "vwap_distance_maximum": 1.5,\n        })\n        window.apply_values(values)\n        current = window.values()\n\n        assert current["enable_random_entry"] is False\n        assert current["entry_timing_mode"] == "CURRENT"\n        assert current["random_entry_probability"] == 0.5\n        assert current["enable_random_entry_batch"] is False\n        assert current["enable_coin_flip_sizing"] is False\n        assert current["vwap_breakout_lookback_hours"] == 4.0\n        assert current["vwap_confirmation_mode"] == "IMMEDIATE"\n        bull_short = current["strategy_profiles"]["bull_short"]\n        assert bull_short["vwap_distance_enabled"] is True\n        assert bull_short["vwap_distance_minimum"] == -0.5\n        assert bull_short["vwap_distance_maximum"] == 1.5\n    finally:\n        window.close()\n\n\ndef test_main_window_source_has_no_hidden_random_vwap_plumbing():\n    source = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "gui" / "main_window.py").read_text(encoding="utf-8")\n    for fragment in (\n        'group("VWAP Volume Breakout")',\n        'group("Random Entry Timing")',\n        "self.vwap_confirmation_mode",\n        "self.enable_random_entry",\n        "self.enable_coin_flip_sizing",\n    ):\n        assert fragment not in source\n''', encoding="utf-8")

print("Stage 15 hidden random/VWAP GUI widgets removed")
