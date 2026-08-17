from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

LEGACY_KEYS = (
    "enable_bull_long_r_step_trailing",
    "bull_long_r_step_activation_r",
    "bull_long_r_step_distance_r",
    "bull_long_r_step_size_r",
    "bull_long_r_step_maximum_r",
    "bull_long_r_step_activation_close_pct",
    "enable_atr_checkpoint_tp_extension",
    "atr_checkpoint_di_spread_minimum",
    "atr_checkpoint_bb_width_minimum",
    "atr_checkpoint_profit_lock_start",
    "atr_checkpoint_profit_lock_distance",
)


def write(path, text):
    path.write_text(text, encoding="utf-8")


# 1. BacktestConfig: Strategy Profiles are now the sole owners of these exit managers.
p = ROOT / "crypto_strategy_lab/config.py"
s = p.read_text(encoding="utf-8")
for key in LEGACY_KEYS:
    s = re.sub(rf"^\s{{4}}{re.escape(key)}:.*\n", "", s, flags=re.M)
write(p, s)

# 2. Engine: remove non-profile fallbacks. A special exit can only be enabled by
# the Strategy Profile selected when the position opens.
p = ROOT / "crypto_strategy_lab/engine.py"
s = p.read_text(encoding="utf-8")
s = re.sub(
    r"pos\.atr_checkpoint_extension_enabled = bool\(\s*profile_for_special_exit\.atr_checkpoint_tp_extension_enabled\s*if profile_for_special_exit else \(self\.config\.enable_atr_checkpoint_tp_extension and sizing_direction == pos\.side\.value\)\s*\)",
    "pos.atr_checkpoint_extension_enabled = bool(profile_for_special_exit and profile_for_special_exit.atr_checkpoint_tp_extension_enabled)",
    s,
)
s = re.sub(
    r"pos\.atr_checkpoint_di_spread_minimum = profile_for_special_exit\.atr_checkpoint_di_spread_minimum if profile_for_special_exit else self\.config\.atr_checkpoint_di_spread_minimum",
    "pos.atr_checkpoint_di_spread_minimum = profile_for_special_exit.atr_checkpoint_di_spread_minimum",
    s,
)
s = re.sub(
    r"pos\.atr_checkpoint_bb_width_minimum = profile_for_special_exit\.atr_checkpoint_bb_width_minimum if profile_for_special_exit else self\.config\.atr_checkpoint_bb_width_minimum",
    "pos.atr_checkpoint_bb_width_minimum = profile_for_special_exit.atr_checkpoint_bb_width_minimum",
    s,
)
s = re.sub(
    r"pos\.atr_checkpoint_profit_lock_start = profile_for_special_exit\.atr_checkpoint_profit_lock_start if profile_for_special_exit else self\.config\.atr_checkpoint_profit_lock_start",
    "pos.atr_checkpoint_profit_lock_start = profile_for_special_exit.atr_checkpoint_profit_lock_start",
    s,
)
s = re.sub(
    r"pos\.atr_checkpoint_profit_lock_distance = profile_for_special_exit\.atr_checkpoint_profit_lock_distance if profile_for_special_exit else self\.config\.atr_checkpoint_profit_lock_distance",
    "pos.atr_checkpoint_profit_lock_distance = profile_for_special_exit.atr_checkpoint_profit_lock_distance",
    s,
)
s = re.sub(
    r"pos\.r_step_trailing_enabled = bool\(\s*profile_for_special_exit\.r_step_trailing_enabled\s*if profile_for_special_exit else \(self\.config\.enable_bull_long_r_step_trailing and pos\.side == Side\.LONG and applied_regime == \"BULL\"\)\s*\)",
    "pos.r_step_trailing_enabled = bool(profile_for_special_exit and profile_for_special_exit.r_step_trailing_enabled)",
    s,
)
for field, old in (
    ("r_step_activation_r", "bull_long_r_step_activation_r"),
    ("r_step_distance_r", "bull_long_r_step_distance_r"),
    ("r_step_size_r", "bull_long_r_step_size_r"),
    ("r_step_maximum_r", "bull_long_r_step_maximum_r"),
    ("r_step_activation_close_pct", "bull_long_r_step_activation_close_pct"),
):
    s = re.sub(
        rf"pos\.{field} = profile_for_special_exit\.{field} if profile_for_special_exit else self\.config\.{old}",
        f"pos.{field} = profile_for_special_exit.{field}", s,
    )
write(p, s)

# 3. GUI defaults and config conversion: remove duplicate global fields.
p = ROOT / "crypto_strategy_lab/gui/config_logic.py"
s = p.read_text(encoding="utf-8")
for key in LEGACY_KEYS:
    s = re.sub(rf'\s*"{re.escape(key)}"\s*:\s*[^,\n]+,?', '', s)
# clean excessive blank lines caused by deleted groups
s = re.sub(r"\n\s*\n\s*\n", "\n\n", s)
write(p, s)

# 4. Main GUI: remove the duplicate DI-tab special-exit controls and serialization.
p = ROOT / "crypto_strategy_lab/gui/main_window.py"
s = p.read_text(encoding="utf-8")
for name in (
    "enable_bull_long_r_step_trailing", "bull_long_r_step_activation_r",
    "bull_long_r_step_distance_r", "bull_long_r_step_size_r",
    "bull_long_r_step_maximum_r", "bull_long_r_step_activation_close_pct",
    "enable_atr_checkpoint_tp_extension", "atr_checkpoint_di_spread_min",
    "atr_checkpoint_bb_width_min", "atr_checkpoint_profit_lock_start",
    "atr_checkpoint_profit_lock_distance",
):
    s = re.sub(rf"^\s*{re.escape('self.' + name)}=.*\n", "", s, flags=re.M)
# dead help labels left behind by previously removed one-off filters
for name in ("biased_short_adx_help", "long_momentum_help", "short_vwap_distance_help"):
    s = re.sub(rf"^\s*self\.{name}=QLabel\([^\n]*\)\n", "", s, flags=re.M)
    s = re.sub(rf"^\s*self\.{name}\.setWordWrap\(True\)\n", "", s, flags=re.M)
s = re.sub(r"^\s*self\.enable_bull_long_r_step_trailing\.toggled\.connect\(self\.update_dynamic\)\n", "", s, flags=re.M)
# remove old ATR checkpoint group from DI tab
s = re.sub(r'\n\s*checkpoint_box=QGroupBox\("ATR Checkpoint TP Extension"\).*?form\.addWidget\(checkpoint_box\);', '', s, flags=re.S)
# remove legacy keys from the giant _base_values dict
for key in LEGACY_KEYS:
    s = re.sub(rf'"{re.escape(key)}":self\.[^,}}]+,?', '', s)
# remove dedicated R-step values.update block
s = re.sub(r'\n\s*values\.update\(\{"enable_bull_long_r_step_trailing".*?\}\)', '', s)
# remove legacy load-state statements
s = re.sub(r'^\s*self\.enable_bull_long_r_step_trailing\.setChecked\([^\n]*\)\n', '', s, flags=re.M)
s = re.sub(r'^\s*self\.enable_atr_checkpoint_tp_extension\.setChecked\([^\n]*\)\n', '', s, flags=re.M)
write(p, s)

# 5. Output text must not advertise removed global controls.
p = ROOT / "crypto_strategy_lab/output_manager.py"
s = p.read_text(encoding="utf-8")
for key in LEGACY_KEYS:
    # Remove simple report lines containing any retired symbol.
    s = re.sub(rf"^.*{re.escape(key)}.*\n", "", s, flags=re.M)
write(p, s)

# 6. Focused regression test.
p = ROOT / "tests/test_stage7_global_special_exit_legacy_removed.py"
p.write_text('''from dataclasses import fields\nfrom pathlib import Path\n\nfrom crypto_strategy_lab.config import BacktestConfig\nfrom crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG\n\nLEGACY = {\n    "enable_bull_long_r_step_trailing", "bull_long_r_step_activation_r",\n    "bull_long_r_step_distance_r", "bull_long_r_step_size_r",\n    "bull_long_r_step_maximum_r", "bull_long_r_step_activation_close_pct",\n    "enable_atr_checkpoint_tp_extension", "atr_checkpoint_di_spread_minimum",\n    "atr_checkpoint_bb_width_minimum", "atr_checkpoint_profit_lock_start",\n    "atr_checkpoint_profit_lock_distance",\n}\n\ndef test_global_special_exit_config_fields_are_gone():\n    names = {f.name for f in fields(BacktestConfig)}\n    assert not (LEGACY & names)\n    assert not (LEGACY & set(DEFAULT_GUI_CONFIG))\n\ndef test_production_code_has_no_global_special_exit_symbols():\n    root = Path(__file__).resolve().parents[1] / "crypto_strategy_lab"\n    for path in root.rglob("*.py"):\n        text = path.read_text(encoding="utf-8")\n        for key in LEGACY:\n            assert key not in text, f"{key} remains in {path}"\n''', encoding="utf-8")
print("Stage 7 global special-exit legacy cleanup applied")
