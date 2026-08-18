"""Temporary Stage 19 audit for retired configuration names."""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import re

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.gui.config_logic import DEFAULT_GUI_CONFIG

LEGACY = {
    "strategy_csv",
    "trade_direction", "sl_mult", "tp_mult",
    "enable_partial_stop_loss", "sl1_r", "sl1_close_pct", "sl2_r",
    "enable_partial_take_profit", "tp1_r", "tp1_close_pct", "tp2_r", "tp2_close_pct",
    "stop_loss_r", "after_tp1_stop_mode", "after_tp1_stop_offset_r", "tp2_exit_mode",
    "enable_trailing_profit", "trail_activation_trigger", "trail_activation_r", "trail_distance_r",
    "trail_apply_to", "trail_intrabar_mode", "enable_both_open_timeout", "max_both_open_minutes",
    "enable_be_after_opposite_sl", "be_mode", "be_offset_r", "be_same_candle_policy",
    "enable_adx_filter", "adx_filter_mode", "adx_minimum", "adx_maximum",
    "enable_bb_width_filter", "bb_width_filter_mode", "bb_width_minimum", "bb_width_maximum",
    "enable_di_spread_filter", "di_spread_filter_mode", "di_spread_minimum", "di_spread_maximum",
    "enable_skip_monday_entries", "skip_monday_timezone",
    "enable_random_entry", "entry_timing_mode", "random_entry_probability", "random_seed",
    "random_entry_start_mode", "randomize_first_entry", "max_random_wait_candles",
    "enable_random_entry_batch", "random_seed_start", "random_seed_count",
    "enable_coin_flip_sizing", "coin_flip_seed", "coin_flip_large_multiplier", "coin_flip_small_multiplier",
    "enable_di_direction_sizing", "di_execution_mode", "flip_filtered_di_direction",
    "di_direction_minimum_spread", "di_direction_long_minimum_spread", "di_direction_short_minimum_spread",
    "enable_remaining_leg_timeout_after_first_sl", "remaining_leg_timeout_after_first_sl_minutes",
    "enable_remaining_leg_timeout_profit_extension", "remaining_leg_timeout_profit_threshold_r",
    "enable_remaining_leg_checkpoint_score_extension", "checkpoint_score_use_profit", "checkpoint_score_min_profit_r",
    "checkpoint_score_use_atr_pct", "checkpoint_score_max_atr_pct", "checkpoint_score_use_directional_di",
    "checkpoint_score_min_directional_di", "checkpoint_score_use_bb_width_pct", "checkpoint_score_max_bb_width_pct",
    "checkpoint_score_min_conditions", "enable_first_sl_survivor_partial_close", "first_sl_survivor_partial_close_pct",
    "enable_checkpoint_zero_score_confirmation", "checkpoint_zero_score_confirmations_required",
    "checkpoint_zero_score_recheck_minutes", "enable_reentry_gate_after_remaining_leg_timeout",
    "vwap_breakout_lookback_hours", "vwap_volume_lookback", "vwap_volume_multiplier", "vwap_slope_lookback",
    "vwap_atr_pct_minimum", "vwap_atr_pct_maximum", "vwap_confirmation_mode",
    "vwap_retest_window_candles", "vwap_retest_tolerance_atr", "position_sizing_mode",
    "enable_strategy_profiles",
}

# These are the important configuration boundaries. Old names may still appear
# temporarily inside dead engine code while Stage 19 deletes those branches, but
# they must never be accepted or serialized as current configuration.
field_names = {field.name for field in fields(BacktestConfig)}
retired_fields = sorted(field_names & LEGACY)
if retired_fields:
    raise SystemExit(f"Retired BacktestConfig fields remain: {', '.join(retired_fields)}")
retired_gui = sorted(set(DEFAULT_GUI_CONFIG) & LEGACY)
if retired_gui:
    raise SystemExit(f"Retired GUI defaults remain: {', '.join(retired_gui)}")

ROOT = Path(__file__).resolve().parents[1]
for path in sorted((ROOT / "crypto_strategy_lab").rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        names = sorted(name for name in LEGACY if re.search(rf"\b{re.escape(name)}\b", line))
        if names:
            hits.append((number, names, line.strip()))
    if hits:
        print(f"\n## {path.relative_to(ROOT)}")
        for number, names, line in hits:
            print(f"{number}: {', '.join(names)} :: {line[:220]}")

print("\nCurrent config boundary is free of retired fields.")
