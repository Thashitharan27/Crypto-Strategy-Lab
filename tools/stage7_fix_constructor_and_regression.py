from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

# 1. Remove stale global special-exit constructor arguments from GUI config conversion.
p = ROOT / "crypto_strategy_lab/gui/config_logic.py"
s = p.read_text(encoding="utf-8")

# Remove ATR checkpoint args wherever they still appear in BacktestConfig(...).
s = re.sub(
    r'\s*enable_atr_checkpoint_tp_extension=bool\(merged\["enable_atr_checkpoint_tp_extension"\]\),\s*'
    r'atr_checkpoint_di_spread_minimum=float\(merged\["atr_checkpoint_di_spread_minimum"\]\),\s*'
    r'atr_checkpoint_bb_width_minimum=float\(merged\["atr_checkpoint_bb_width_minimum"\]\),\s*'
    r'atr_checkpoint_profit_lock_start=float\(merged\["atr_checkpoint_profit_lock_start"\]\),\s*'
    r'atr_checkpoint_profit_lock_distance=float\(merged\["atr_checkpoint_profit_lock_distance"\]\),',
    ' ', s,
)

# Remove Bull-long R-step args wherever they still appear in BacktestConfig(...).
s = re.sub(
    r'\s*enable_bull_long_r_step_trailing=bool\(merged\["enable_bull_long_r_step_trailing"\]\),\s*'
    r'bull_long_r_step_activation_r=float\(merged\["bull_long_r_step_activation_r"\]\),\s*'
    r'bull_long_r_step_distance_r=float\(merged\["bull_long_r_step_distance_r"\]\),\s*'
    r'bull_long_r_step_size_r=float\(merged\["bull_long_r_step_size_r"\]\),\s*'
    r'bull_long_r_step_maximum_r=float\(merged\["bull_long_r_step_maximum_r"\]\),\s*'
    r'bull_long_r_step_activation_close_pct=float\(merged\["bull_long_r_step_activation_close_pct"\]\),',
    ' ', s,
)

p.write_text(s, encoding="utf-8")

# 2. Tighten the regression test: position state fields are intentionally retained.
# The removed legacy is specifically global config / GUI / global-engine fallback plumbing.
p = ROOT / "tests/test_stage7_global_special_exit_legacy_removed.py"
p.write_text('''from dataclasses import fields\nfrom pathlib import Path\n\nfrom crypto_strategy_lab.config import BacktestConfig\nfrom crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG\n\nLEGACY = {\n    "enable_bull_long_r_step_trailing", "bull_long_r_step_activation_r",\n    "bull_long_r_step_distance_r", "bull_long_r_step_size_r",\n    "bull_long_r_step_maximum_r", "bull_long_r_step_activation_close_pct",\n    "enable_atr_checkpoint_tp_extension", "atr_checkpoint_di_spread_minimum",\n    "atr_checkpoint_bb_width_minimum", "atr_checkpoint_profit_lock_start",\n    "atr_checkpoint_profit_lock_distance",\n}\n\ndef test_global_special_exit_config_fields_are_gone():\n    names = {f.name for f in fields(BacktestConfig)}\n    assert not (LEGACY & names)\n    assert not (LEGACY & set(DEFAULT_GUI_CONFIG))\n\ndef test_global_special_exit_symbols_are_gone_from_global_plumbing():\n    root = Path(__file__).resolve().parents[1] / "crypto_strategy_lab"\n    checked = [\n        root / "config.py",\n        root / "engine.py",\n        root / "output_manager.py",\n        root / "gui" / "config_logic.py",\n        root / "gui" / "main_window.py",\n    ]\n    for path in checked:\n        text = path.read_text(encoding="utf-8")\n        for key in LEGACY:\n            assert key not in text, f"{key} remains in global plumbing: {path}"\n\ndef test_position_level_special_exit_state_is_retained():\n    text = (Path(__file__).resolve().parents[1] / "crypto_strategy_lab" / "trade.py").read_text(encoding="utf-8")\n    assert "r_step_trailing_enabled" in text\n    assert "atr_checkpoint_extension_enabled" in text\n''', encoding="utf-8")

print("Stage 7 constructor leftovers and regression scope repaired")
