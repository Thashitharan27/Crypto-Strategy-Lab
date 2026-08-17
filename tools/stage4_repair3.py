import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")

# 1) The compact DI tab no longer creates the legacy DI-sizing widget, so the
# old ATR-checkpoint dynamic block must not dereference it.
p = "crypto_strategy_lab/gui/main_window.py"
s = read(p)
old = '''        if hasattr(self,"enable_atr_checkpoint_tp_extension"):\n            checkpoint_enabled=self.enable_atr_checkpoint_tp_extension.isChecked() and self.enable_di_direction_sizing.isChecked()\n            self.enable_atr_checkpoint_tp_extension.setEnabled(self.enable_di_direction_sizing.isChecked())\n            for control in (self.atr_checkpoint_di_spread_min,self.atr_checkpoint_bb_width_min,self.atr_checkpoint_profit_lock_start,self.atr_checkpoint_profit_lock_distance):\n                control.setEnabled(checkpoint_enabled)\n'''
if old in s:
    s = s.replace(old, "", 1)
write(p, s)

# 2) Remove telemetry assignments for deleted one-off legacy R:R paths. Keep
# only generic applied-regime / applied-R:R telemetry used by profile runs.
p = "crypto_strategy_lab/engine.py"
s = read(p)
lines = s.splitlines()
new_lines = []
for line in lines:
    if "pair.di_reward_risk_regime=applied_regime;" in line and "bull_long_conditional_reward_risk_applied" in line:
        indent = line[: len(line) - len(line.lstrip())]
        new_lines.append(indent + "pair.di_reward_risk_regime=applied_regime; pair.di_applied_long_reward_risk_ratio=long_reward_risk; pair.di_applied_short_reward_risk_ratio=short_reward_risk")
    else:
        new_lines.append(line)
write(p, "\n".join(new_lines) + "\n")

# 3) Remove GUI-config tests whose purpose is the retired legacy DI-sizing and
# one-off filter architecture. Strategy Profile tests cover the replacement.
p = "tests/test_gui_config_logic.py"
s = read(p)
tree = ast.parse(s)
source_lines = s.splitlines(True)
cuts = []
legacy_markers = {
    "enable_di_direction_sizing",
    "enable_bull_regime_short_filter",
    "enable_bear_regime_adx_filter",
    "enable_biased_short_adx_cap",
    "enable_short_vwap_distance_filter",
    "enable_long_momentum_filter",
    "enable_directional_adx_filter",
}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
        body = "".join(source_lines[node.lineno - 1: node.end_lineno])
        if any(marker in body for marker in legacy_markers):
            cuts.append((node.lineno - 1, node.end_lineno))
for start, end in sorted(cuts, reverse=True):
    del source_lines[start:end]
write(p, "".join(source_lines))
