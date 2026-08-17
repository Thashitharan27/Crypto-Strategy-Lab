from pathlib import Path

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

# The Stage 7 primary transform removes the dataclass fields. Remove the stale
# BacktestConfig validations that still referenced those deleted attributes.
p = ROOT / "crypto_strategy_lab/config.py"
lines = p.read_text(encoding="utf-8").splitlines(True)
lines = [line for line in lines if not any(key in line for key in LEGACY_KEYS)]
p.write_text("".join(lines), encoding="utf-8")

# Remove GUI validation rules for the retired global copies. Profile validation
# now owns these parameters inside StrategyProfile.
p = ROOT / "crypto_strategy_lab/gui/config_logic.py"
lines = p.read_text(encoding="utf-8").splitlines(True)
cleaned = []
for line in lines:
    stripped = line.strip()
    if "Bull-long staircase" in line:
        continue
    if "ATR checkpoint" in line and ("errors.append" in line or "values.get" in line):
        continue
    if any(key in line for key in LEGACY_KEYS) and ("errors.append" in line or stripped.startswith("if ")):
        continue
    cleaned.append(line)
p.write_text("".join(cleaned), encoding="utf-8")

print("Stage 7 stale config validation leftovers removed")
