from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]

# 1) Engine: retire legacy long-momentum telemetry assignment now that the
# one-off long momentum filter and its precomputed series are gone.
p = ROOT / "crypto_strategy_lab/engine.py"
s = p.read_text(encoding="utf-8")
s = s.replace(
    '        pair.long_momentum_return=float(self.long_momentum_return_values[ind_i]) if np.isfinite(self.long_momentum_return_values[ind_i]) else np.nan\n',
    '        pair.long_momentum_return=pair.directional_momentum_return\n',
)
ast.parse(s)
p.write_text(s, encoding="utf-8")

# 2) GUI config validation: remove stale validation for retired directional ADX.
p = ROOT / "crypto_strategy_lab/gui/config_logic.py"
s = p.read_text(encoding="utf-8")
s = re.sub(
    r'\n    for key, label in \(\("directional_long_adx_maximum", "Long ADX maximum"\), \("directional_short_adx_minimum", "Short ADX minimum"\)\):\n        try:\n            if float\(values\.get\(key, -1\)\) < 0: errors\.append\(f"\{label\} must be non-negative\."\)\n        except \(TypeError, ValueError\): errors\.append\(f"\{label\} must be numeric\."\)',
    '',
    s,
)
ast.parse(s)
p.write_text(s, encoding="utf-8")

# 3) Run-info writer: replace the legacy DI/R:R + one-off entry-filter prose
# with the current Strategy Profiles source-of-truth summary.
p = ROOT / "crypto_strategy_lab/output_manager.py"
s = p.read_text(encoding="utf-8")
start = s.index('def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n')
end_marker = '    (run_dir / "run_info.txt").write_text("\\n".join(lines) + "\\n")\n'
end = s.index(end_marker, start) + len(end_marker)
replacement = '''def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:\n    if config.enable_partial_stop_loss:\n        stop_description = (\n            f"Partial stop: {config.sl1_close_pct}% at {config.sl1_r}R; "\n            f"remainder at {config.sl2_r}R (Core SL ignored)"\n        )\n    elif config.enable_partial_take_profit:\n        stop_description = f"Partial TP stop: {config.stop_loss_r}R (Core SL ignored)"\n    else:\n        stop_description = f"Stop loss multiple: {config.sl_mult}R"\n\n    if config.enable_strategy_profiles:\n        enabled_profiles = [key for key, profile in config.strategy_profiles.items() if profile.enabled]\n        target_description = (\n            "Strategy Profiles: " + (", ".join(enabled_profiles) if enabled_profiles else "none enabled")\n            + f"; run mode {config.strategy_profile_run_mode}"\n        )\n    elif config.enable_partial_take_profit:\n        target_description = (\n            f"Partial take profit: {config.tp1_close_pct}% at {config.tp1_r}R; "\n            f"remainder at {config.tp2_r}R (Core TP ignored)"\n        )\n    else:\n        target_description = f"Take profit multiple: {config.tp_mult}R"\n\n    lines = [\n        "Backtest Run Information",\n        "========================",\n        f"Output folder: {run_dir.resolve()}",\n        f"Run name: {config.run_name or '(none)'}",\n        f"Strategy CSV: {config.strategy_csv}",\n        f"Intrabar CSV: {config.intrabar_csv if config.use_intrabar_data else '(disabled)'}",\n        f"Symbol: {infer_symbol(config)}",\n        f"Strategy timeframe: {config.strategy_timeframe_minutes}m",\n        f"Risk mode: {config.risk_mode.value}",\n        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",\n        stop_description,\n        target_description,\n        (\n            f"Trailing stop: enabled; trigger {config.trail_activation_trigger.value}; "\n            f"activation {config.trail_activation_r}R; distance {config.trail_distance_r}R; "\n            f"apply to {config.trail_apply_to.value}; fixed final targets remain active"\n            if config.enable_trailing_profit\n            else "Trailing stop: disabled"\n        ),\n        (\n            f"Bull-long R-step staircase: enabled; activate at {config.bull_long_r_step_activation_r}R; "\n            f"distance {config.bull_long_r_step_distance_r}R; step {config.bull_long_r_step_size_r}R; "\n            f"close {config.bull_long_r_step_activation_close_pct}% at activation; "\n            + (\n                f"maximum target {config.bull_long_r_step_maximum_r}R"\n                if config.bull_long_r_step_maximum_r > 0\n                else "no fixed target"\n            )\n            if config.enable_bull_long_r_step_trailing\n            else "Bull-long R-step staircase: disabled"\n        ),\n        f"Partial intrabar ordering: {'STOP_FIRST' if config.tie_policy.value == 'PESSIMISTIC' else 'TP1_THEN_TP2_THEN_STOP'}",\n        f"Initial equity: {config.initial_equity}",\n        f"Total pairs: {summary.get('total_pairs')}",\n        f"Ending equity: {summary.get('ending_equity')}",\n        f"Total return %: {summary.get('total_return_percentage')}",\n    ]\n    (run_dir / "run_info.txt").write_text("\\n".join(lines) + "\\n")\n'''
s = s[:start] + replacement + s[end:]
ast.parse(s)
p.write_text(s, encoding="utf-8")
