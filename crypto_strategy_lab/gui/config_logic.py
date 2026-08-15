"""Pure helpers for GUI configuration conversion and validation."""
from __future__ import annotations

import json
import copy
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy, AdxFilterMode, BBWidthFilterMode, DISpreadFilterMode, TradeDirectionMode, DIExecutionMode, DailyEntryMissedPolicy, TrailApplyTo, TrailIntrabarMode, TrailActivationTrigger, AfterTP1StopMode, TP2ExitMode, EntryTimingMode, RandomEntryStartMode, VWAPConfirmationMode
from crypto_strategy_lab.strategy_profiles import default_profiles, profiles_to_dict

DEFAULT_GUI_CONFIG: dict[str, Any] = {
    "market_symbol": "XRPUSDT",
    "enable_strategy_profiles": False, "strategy_profile_run_mode": "COMBINED_SHARED_CAPITAL", "strategy_profiles": profiles_to_dict(default_profiles()),
    "input_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_15m.csv", "strategy_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_15m.csv", "intrabar_csv": "C:/CryptoBots/Binance Market Data/futures/usdm/BTCUSDT_1m.csv", "output_dir": "output", "run_name": "",
    "sl_mult": 2.0, "tp_mult": 3.0, "entry_mode": "WAIT_UNTIL_CLOSED",
    "vwap_breakout_lookback_hours": 4.0, "vwap_volume_lookback": 20, "vwap_volume_multiplier": 1.5, "vwap_slope_lookback": 1, "vwap_atr_pct_minimum": 0.0, "vwap_atr_pct_maximum": 1.0, "vwap_confirmation_mode": "IMMEDIATE", "vwap_retest_window_candles": 4, "vwap_retest_tolerance_atr": 0.25,
    "enable_random_entry": False, "entry_timing_mode": "CURRENT", "random_entry_probability": 0.50, "random_seed": 42, "random_entry_start_mode": "NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE", "randomize_first_entry": True, "max_random_wait_candles": 0, "enable_random_entry_batch": False, "random_seed_start": 1, "random_seed_count": 100,
    "enable_coin_flip_sizing": False, "coin_flip_seed": 42, "coin_flip_large_multiplier": 3.0, "coin_flip_small_multiplier": 1.0,
    "enable_di_direction_sizing": False, "flip_filtered_di_direction": False, "di_direction_minimum_spread": 30.0, "di_direction_long_minimum_spread": 30.0, "di_direction_short_minimum_spread": 30.0, "di_execution_mode": "BOTH_SIDES", "di_reward_risk_ratio": 1.0, "di_long_reward_risk_ratio": 1.0, "di_short_reward_risk_ratio": 1.0,
    "enable_direction_voting": False, "direction_vote_use_di": True, "direction_vote_use_structure": True, "direction_vote_structure_lookback": 20, "direction_vote_use_momentum": True, "direction_vote_momentum_lookback_hours": 24, "direction_vote_momentum_threshold": 0.0, "direction_vote_use_volume_pressure": True, "direction_vote_volume_lookback": 20, "direction_vote_volume_threshold": 0.10, "direction_vote_use_higher_timeframe": True, "direction_vote_higher_timeframe_hours": 4, "direction_vote_higher_timeframe_sma_period": 20, "direction_vote_minimum_votes": 2,
    "enable_di_regime_reward_risk": False, "di_regime_bear_return_threshold": -0.20,
    "di_long_bull_reward_risk_ratio": 2.0, "di_long_bear_reward_risk_ratio": 1.0, "di_long_sideways_reward_risk_ratio": 2.0,
    "di_short_bull_reward_risk_ratio": 1.0, "di_short_bear_reward_risk_ratio": 1.0, "di_short_sideways_reward_risk_ratio": 2.0,
    "enable_bull_long_conditional_reward_risk": False, "bull_long_conditional_bb_width_minimum": 0.05, "bull_long_conditional_adx_maximum": 40.0, "bull_long_conditional_reward_risk_ratio": 1.0,
    "enable_bull_long_r_step_trailing": False, "bull_long_r_step_activation_r": 2.0, "bull_long_r_step_distance_r": 2.0, "bull_long_r_step_size_r": 1.0, "bull_long_r_step_maximum_r": 0.0, "bull_long_r_step_activation_close_pct": 0.0,
    "enable_bull_long_momentum_confirmation": False, "bull_long_confirmation_lookback_days": 60, "bull_long_confirmation_return_threshold": 0.20, "bull_long_unconfirmed_reward_risk_ratio": 1.0,
    "enable_bull_long_momentum_target_extension": False, "bull_long_momentum_extension_lookback_days": 30, "bull_long_momentum_extension_return_threshold": 0.10, "enable_bull_long_momentum_extension_return_maximum": False, "bull_long_momentum_extension_return_maximum": 0.40, "bull_long_momentum_extended_reward_risk_ratio": 4.0,
    "enable_bull_long_structural_confirmation": False, "bull_long_structural_sma_days": 200, "bull_long_structural_slope_lookback_days": 30, "bull_long_structural_unconfirmed_reward_risk_ratio": 1.0,
    "enable_sideways_long_conditional_reward_risk": False, "sideways_long_conditional_adx_maximum": 35.0, "sideways_long_conditional_reward_risk_ratio": 1.0,
    "enable_sideways_short_conditional_reward_risk": False, "sideways_short_conditional_di_spread_minimum": 35.0, "sideways_short_conditional_di_spread_maximum": 40.0, "sideways_short_conditional_reward_risk_ratio": 1.0,
    "enable_bear_short_conditional_reward_risk": False, "bear_short_conditional_di_spread_maximum": 35.0, "bear_short_conditional_reward_risk_ratio": 1.0,
    "enable_directional_adx_filter": False, "directional_long_adx_maximum": 60.0, "directional_short_adx_minimum": 25.0,
    "enable_long_momentum_filter": False, "long_momentum_lookback_hours": 24, "long_momentum_minimum_return": 0.06,
    "enable_regime_direction_filter": False, "allow_bull_long": True, "allow_bull_short": True, "allow_bear_long": True, "allow_bear_short": True, "allow_sideways_long": True, "allow_sideways_short": True,
    "enable_directional_di_spread_range": False, "directional_long_di_spread_minimum": 0.0, "directional_long_di_spread_maximum": 1000.0, "directional_short_di_spread_minimum": 0.0, "directional_short_di_spread_maximum": 1000.0,
    "enable_directional_adx_range": False, "directional_long_adx_minimum": 0.0, "directional_long_adx_range_maximum": 1000.0, "directional_short_adx_range_minimum": 0.0, "directional_short_adx_maximum": 1000.0,
    "enable_directional_atr_pct_range": False, "directional_long_atr_pct_minimum": 0.0, "directional_long_atr_pct_maximum": 1.0, "directional_short_atr_pct_minimum": 0.0, "directional_short_atr_pct_maximum": 1.0,
    "enable_directional_rsi_range": False, "directional_rsi_period": 14, "directional_long_rsi_minimum": 0.0, "directional_long_rsi_maximum": 100.0, "directional_short_rsi_minimum": 0.0, "directional_short_rsi_maximum": 100.0,
    "enable_directional_close_location_range": False, "directional_long_close_location_minimum": 0.0, "directional_long_close_location_maximum": 1.0, "directional_short_close_location_minimum": 0.0, "directional_short_close_location_maximum": 1.0,
    "enable_directional_momentum_range": False, "directional_momentum_lookback_hours": 24, "directional_long_momentum_minimum": -10.0, "directional_long_momentum_maximum": 10.0, "directional_short_momentum_minimum": -10.0, "directional_short_momentum_maximum": 10.0,
    "enable_atr_checkpoint_tp_extension": False, "atr_checkpoint_di_spread_minimum": 30.0, "atr_checkpoint_bb_width_minimum": 0.03, "atr_checkpoint_profit_lock_start": 3.0, "atr_checkpoint_profit_lock_distance": 1.0,
    "enable_biased_short_adx_cap": False, "biased_short_adx_maximum": 50.0,
    "enable_short_vwap_distance_filter": False, "short_vwap_minimum_distance_atr": 2.0,
    "enable_bull_regime_short_filter": False, "market_regime_method": "BTC_STRUCTURAL", "structural_regime_sma_days": 200, "structural_regime_slope_lookback_days": 30, "structural_regime_benchmark_csv": None, "bull_regime_lookback_days": 90, "bull_regime_return_threshold": 0.20, "enable_bear_regime_adx_filter": False, "bear_regime_adx_minimum": 25.0,
    "entry_interval": 1, "enable_daily_entry_schedule": False, "daily_entry_time": "00:00", "daily_entry_timezone": "UTC", "daily_entry_missed_policy": "SKIP_DAY", "enable_skip_monday_entries": False, "skip_monday_timezone": "UTC", "max_active_pairs": 1, "tie_policy": "PESSIMISTIC",
    "risk_mode": "ATR", "atr_period": 14, "atr_multiplier": 1.0, "enable_adx_filter": False, "adx_period": 14, "adx_filter_mode": "Disabled", "adx_maximum": 25.0, "adx_minimum": 20.0, "enable_bb_width_filter": False, "bb_width_filter_mode": "Disabled", "bb_width_maximum": 0.03, "bb_width_minimum": 0.012, "enable_di_spread_filter": False, "di_spread_filter_mode": "Disabled", "di_spread_maximum": 10.0, "di_spread_minimum": 0.0,
    "percent_r": 0.002, "fixed_r": 100.0, "initial_equity": 1000.0,
    "risk_per_leg": 0.01, "maker_fee": 0.0002, "taker_fee": 0.0005,
    "use_maker_entry": False, "use_maker_exit": False, "slippage": 0.0005,
    "strategy_timeframe_minutes": 15, "intrabar_timeframe_minutes": 1, "use_intrabar_data": True,
    "trading_start_date": None, "trading_end_date": None, "max_effective_leverage_per_leg": "3.0",
    "max_combined_effective_leverage": "5.0", "intrabar_missing_policy": "WARN_AND_USE_15M", "zero_cost_comparison": False, "trade_direction": "BOTH", "enable_trailing_profit": False, "trail_activation_trigger": "PRICE_REACHES_R", "trail_activation_r": 3.0, "trail_distance_r": 1.0, "trail_apply_to": "BOTH", "trail_intrabar_mode": "PESSIMISTIC",
    "enable_partial_take_profit": False, "enable_partial_stop_loss": False, "sl1_r": 0.5, "sl1_close_pct": 50.0, "sl2_r": 8.0, "tp1_r": 3.0, "tp1_close_pct": 50.0, "tp2_r": 12.0, "tp2_close_pct": 50.0, "stop_loss_r": 10.0, "after_tp1_stop_mode": "KEEP_ORIGINAL_SL", "after_tp1_stop_offset_r": 0.0, "tp2_exit_mode": "FIXED_TP2",
    "enable_both_open_timeout": False, "max_both_open_minutes": 480, "enable_remaining_leg_timeout_after_first_sl": False, "remaining_leg_timeout_after_first_sl_minutes": 240, "remaining_leg_timeout_after_first_sl_unit": "Hours", "enable_remaining_leg_timeout_profit_extension": False, "remaining_leg_timeout_profit_threshold_r": 10.0, "analysis_level": "STANDARD", "enable_trade_telemetry": False, "save_full_telemetry_csv": False, "save_trade_journey_summary": False, "save_trade_journey_charts": False, "telemetry_interval_minutes": 15, "enable_indicator_lifecycle_analysis": False, "lifecycle_phases": 4, "lifecycle_early_checkpoints": [15, 30, 60], "lifecycle_minimum_bucket_sample": 20, "create_lifecycle_charts": False, "lifecycle_flat_pattern_threshold_pct": 5.0, "save_feature_analysis_reports": False, "save_indicator_analysis_reports": True, "create_standard_charts": True, "both_open_timeout_unit": "Hours", "enable_be_after_opposite_sl": False, "be_mode": "ENTRY_PRICE", "be_offset_r": 0.0, "be_same_candle_policy": "NEXT_CANDLE",
    "enable_reentry_gate_after_remaining_leg_timeout": False,
    "enable_remaining_leg_checkpoint_score_extension": False, "checkpoint_score_use_profit": True, "checkpoint_score_min_profit_r": 0.85, "checkpoint_score_use_atr_pct": True, "checkpoint_score_max_atr_pct": 0.08, "checkpoint_score_use_directional_di": True, "checkpoint_score_min_directional_di": 2.3, "checkpoint_score_use_bb_width_pct": True, "checkpoint_score_max_bb_width_pct": 0.349, "checkpoint_score_min_conditions": 3,
    "enable_first_sl_survivor_partial_close": False, "first_sl_survivor_partial_close_pct": 25.0, "enable_checkpoint_zero_score_confirmation": False, "checkpoint_zero_score_confirmations_required": 2, "checkpoint_zero_score_recheck_minutes": 120, "checkpoint_zero_score_recheck_unit": "Hours",
}


def default_gui_config() -> dict[str, Any]:
    """Return a fresh copy of the GUI defaults."""
    return copy.deepcopy(DEFAULT_GUI_CONFIG)


def parse_percentage(value: str | float | int) -> float:
    """Convert human-readable percentages such as ``0.5%`` to decimals."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("percentage is required")
    if text.endswith("%"):
        return float(text[:-1].strip()) / 100.0
    return float(text)


def format_percentage(value: float, decimals: int = 4) -> str:
    text = f"{value * 100:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def theoretical_break_even(sl_mult: float, tp_mult: float) -> float:
    winning = tp_mult - sl_mult
    losing_abs = abs(-2 * sl_mult)
    denom = winning + losing_abs
    return losing_abs / denom if denom > 0 else 1.0


def validate_config_values(values: dict[str, Any], require_paths: bool = True) -> list[str]:
    values = {**default_gui_config(), **values}
    errors: list[str] = []
    if require_paths:
        strategy_path = values.get("strategy_csv") if values.get("strategy_csv") != DEFAULT_GUI_CONFIG.get("strategy_csv") else values.get("input_csv")
        if not Path(strategy_path or "").is_file():
            errors.append("Strategy CSV must exist.")
        if values.get("use_intrabar_data") and values.get("intrabar_csv") and values.get("intrabar_csv") != DEFAULT_GUI_CONFIG.get("intrabar_csv") and not Path(values.get("intrabar_csv")).is_file():
            errors.append("Intrabar CSV must exist when enabled.")
        out = Path(values.get("output_dir", ""))
        if not str(out):
            errors.append("Output folder is required.")
    checks = [
        ("sl_mult", 0, "SL multiple must be > 0."), ("tp_mult", 0, "TP multiple must be > 0."),
        ("initial_equity", 0, "Starting equity must be > 0."), ("risk_per_leg", 0, "Risk per leg must be > 0."),
        ("atr_multiplier", 0, "ATR multiplier must be > 0."), ("strategy_timeframe_minutes", 0, "Strategy timeframe must be > 0."), ("intrabar_timeframe_minutes", 0, "Intrabar timeframe must be > 0."), ("percent_r", 0, "Percentage R must be > 0."),
        ("fixed_r", 0, "Fixed R must be > 0."), ("sl1_r", 0, "SL1_R must be greater than zero."), ("sl2_r", 0, "SL2_R must be greater than zero."), ("sl1_close_pct", 0, "SL1 close percentage must be greater than zero."), ("tp1_r", 0, "TP1_R must be greater than zero."), ("tp2_r", 0, "TP2_R must be greater than zero."), ("stop_loss_r", 0, "STOP_LOSS_R must be greater than zero."), ("tp1_close_pct", 0, "TP1_CLOSE_PCT must be greater than zero."), ("tp2_close_pct", 0, "TP2_CLOSE_PCT must be greater than zero."), ("trail_activation_r", 0, "Trailing Activation (R) must be > 0."), ("trail_distance_r", 0, "Trailing Distance (R) must be > 0."),
    ]
    for key, limit, msg in checks:
        try:
            if float(values.get(key, 0)) <= limit: errors.append(msg)
        except (TypeError, ValueError): errors.append(msg)
    if float(values.get("risk_per_leg", 0)) >= 1: errors.append("Risk per leg must be < 100%.")
    for key, msg in [("atr_period", "ATR period must be >= 1."), ("entry_interval", "Entry interval must be >= 1."), ("max_active_pairs", "Maximum active pairs must be >= 1.")]:
        try:
            if int(values.get(key, 0)) < 1: errors.append(msg)
        except (TypeError, ValueError): errors.append(msg)
    for key, label in [("maker_fee", "Maker fee"), ("taker_fee", "Taker fee"), ("slippage", "Slippage")]:
        try:
            if float(values.get(key, 0)) < 0: errors.append(f"{label} must be >= 0.")
        except (TypeError, ValueError): errors.append(f"{label} must be >= 0.")
    try:
        if float(values.get("tp2_r")) <= float(values.get("tp1_r")): errors.append("TP2_R must be greater than TP1_R.")
        if abs(float(values.get("tp1_close_pct")) + float(values.get("tp2_close_pct")) - 100.0) > 1e-9: errors.append("TP1_CLOSE_PCT + TP2_CLOSE_PCT must equal 100%.")
    except (TypeError, ValueError): errors.append("Partial take-profit values cannot be blank and must be numeric.")
    if values.get("after_tp1_stop_mode") not in [e.value for e in AfterTP1StopMode]: errors.append("Invalid AFTER_TP1_STOP_MODE.")
    if values.get("tp2_exit_mode") not in [e.value for e in TP2ExitMode]: errors.append("Invalid TP2_EXIT_MODE.")
    if values.get("entry_mode") not in [e.value for e in EntryMode]: errors.append("Invalid entry mode.")
    if float(values.get("vwap_breakout_lookback_hours",0)) <= 0: errors.append("VWAP breakout lookback hours must be positive.")
    if int(values.get("vwap_volume_lookback",0)) <= 0: errors.append("VWAP volume lookback must be positive.")
    if float(values.get("vwap_volume_multiplier",0)) <= 0: errors.append("VWAP volume multiplier must be positive.")
    if int(values.get("vwap_slope_lookback",0)) <= 0: errors.append("VWAP slope lookback must be positive.")
    if not 0 <= float(values.get("vwap_atr_pct_minimum",0)) <= float(values.get("vwap_atr_pct_maximum",1)): errors.append("VWAP ATR percentage range is invalid.")
    if values.get("vwap_confirmation_mode") not in [e.value for e in VWAPConfirmationMode]: errors.append("Invalid VWAP confirmation mode.")
    if int(values.get("vwap_retest_window_candles",0)) <= 0: errors.append("VWAP retest window must be positive.")
    if float(values.get("vwap_retest_tolerance_atr",-1)) < 0: errors.append("VWAP retest tolerance cannot be negative.")
    if values.get("enable_adx_filter") and values.get("adx_filter_mode") == "Range" and float(values.get("adx_minimum",0)) > float(values.get("adx_maximum",0)): errors.append("ADX minimum cannot exceed ADX maximum.")
    if values.get("entry_timing_mode") not in [e.value for e in EntryTimingMode]: errors.append("Invalid entry timing mode.")
    if values.get("random_entry_start_mode") not in [e.value for e in RandomEntryStartMode]: errors.append("Invalid Random Entry Start Mode.")
    try:
        if not 0 < float(values.get("random_entry_probability")) <= 1: errors.append("Entry Probability must be greater than 0 and less than or equal to 1.")
    except (TypeError, ValueError): errors.append("Entry Probability must be greater than 0 and less than or equal to 1.")
    try: int(values.get("random_seed"))
    except (TypeError, ValueError): errors.append("Random Seed must be an integer.")
    try: int(values.get("coin_flip_seed"))
    except (TypeError, ValueError): errors.append("Coin Flip Seed must be an integer.")
    try:
        if float(values.get("coin_flip_small_multiplier", 0)) <= 0 or float(values.get("coin_flip_large_multiplier", 0)) <= float(values.get("coin_flip_small_multiplier", 0)): errors.append("Coin-flip multipliers must be positive and large must exceed small.")
    except (TypeError, ValueError): errors.append("Coin-flip multipliers must be numeric.")
    if values.get("enable_coin_flip_sizing") and values.get("trade_direction") not in ("BOTH", "BOTH_INDEPENDENT"): errors.append("Coin-flip sizing requires both long and short positions.")
    if values.get("enable_coin_flip_sizing") and (values.get("enable_partial_take_profit") or values.get("enable_partial_stop_loss")): errors.append("Coin-flip sizing cannot be combined with partial TP or partial SL.")
    if values.get("enable_coin_flip_sizing") and values.get("enable_di_direction_sizing"): errors.append("Coin-flip sizing and DI-direction sizing cannot both be enabled.")
    direction_voter_keys=("direction_vote_use_di","direction_vote_use_structure","direction_vote_use_momentum","direction_vote_use_volume_pressure","direction_vote_use_higher_timeframe")
    enabled_direction_voters=sum(bool(values.get(k)) for k in direction_voter_keys)
    if values.get("enable_direction_voting") and not enabled_direction_voters: errors.append("Direction voting requires at least one voter.")
    if values.get("enable_direction_voting") and int(values.get("direction_vote_minimum_votes",1))>enabled_direction_voters: errors.append("Minimum Winning Votes cannot exceed the number of enabled direction voters.")
    if values.get("flip_filtered_di_direction") and not (values.get("enable_di_direction_sizing") or values.get("enable_strategy_profiles")): errors.append("Direction flip requires DI-direction selection.")
    try:
        if float(values.get("di_direction_minimum_spread", -1)) < 0: errors.append("DI direction minimum spread must be non-negative.")
    except (TypeError, ValueError): errors.append("DI direction minimum spread must be numeric.")
    for key, label in (("di_direction_long_minimum_spread", "Long DI direction minimum spread"), ("di_direction_short_minimum_spread", "Short DI direction minimum spread")):
        try:
            if float(values.get(key, -1)) < 0: errors.append(f"{label} must be non-negative.")
        except (TypeError, ValueError): errors.append(f"{label} must be numeric.")
    try:
        if float(values.get("di_reward_risk_ratio", 0)) <= 0: errors.append("DI reward/risk ratio must be positive.")
    except (TypeError, ValueError): errors.append("DI reward/risk ratio must be numeric.")
    for key, label in (("di_long_reward_risk_ratio", "Long DI reward/risk ratio"), ("di_short_reward_risk_ratio", "Short DI reward/risk ratio")):
        try:
            if float(values.get(key, 0)) <= 0: errors.append(f"{label} must be positive.")
        except (TypeError, ValueError): errors.append(f"{label} must be numeric.")
    regime_ratio_keys = (
        "di_long_bull_reward_risk_ratio", "di_long_bear_reward_risk_ratio", "di_long_sideways_reward_risk_ratio",
        "di_short_bull_reward_risk_ratio", "di_short_bear_reward_risk_ratio", "di_short_sideways_reward_risk_ratio",
    )
    for key in regime_ratio_keys:
        try:
            if float(values.get(key, 0)) <= 0: errors.append("DI regime reward/risk ratios must be positive.")
        except (TypeError, ValueError): errors.append("DI regime reward/risk ratios must be numeric.")
    try:
        bear_threshold = float(values.get("di_regime_bear_return_threshold", -1))
        bull_threshold = float(values.get("bull_regime_return_threshold", 0.20))
        if bear_threshold <= -1: errors.append("DI bear threshold must be greater than -100%.")
        if values.get("enable_di_regime_reward_risk") and bear_threshold >= bull_threshold: errors.append("DI bear threshold must be below bull threshold.")
    except (TypeError, ValueError): errors.append("DI regime return thresholds must be numeric.")
    if values.get("enable_di_regime_reward_risk") and not values.get("enable_di_direction_sizing"): errors.append("Regime-specific DI reward/risk requires DI-direction sizing.")
    if values.get("enable_bull_long_conditional_reward_risk") and not values.get("enable_di_regime_reward_risk"): errors.append("Conditional bull-long reward/risk requires regime-specific DI reward/risk.")
    if float(values.get("bull_long_conditional_bb_width_minimum", 0)) < 0: errors.append("Bull-long conditional BB width minimum must be non-negative.")
    if float(values.get("bull_long_conditional_adx_maximum", 0)) < 0: errors.append("Bull-long conditional ADX maximum must be non-negative.")
    if float(values.get("bull_long_conditional_reward_risk_ratio", 0)) <= 0: errors.append("Bull-long conditional reward/risk must be positive.")
    if values.get("enable_bull_long_r_step_trailing") and not values.get("enable_di_regime_reward_risk"): errors.append("Bull-long staircase requires regime-specific DI reward/risk.")
    if values.get("enable_bull_long_r_step_trailing") and values.get("enable_partial_take_profit"): errors.append("Bull-long staircase cannot be combined with Partial Take Profit.")
    if values.get("enable_bull_long_r_step_trailing") and values.get("enable_atr_checkpoint_tp_extension"): errors.append("Bull-long staircase cannot be combined with ATR checkpoint TP extension.")
    if values.get("enable_bull_long_r_step_trailing") and values.get("enable_trailing_profit"): errors.append("Bull-long staircase cannot be combined with the independent trailing stop.")
    if float(values.get("bull_long_r_step_activation_r", 0)) <= 0: errors.append("Bull-long staircase activation must be positive.")
    if float(values.get("bull_long_r_step_distance_r", 0)) <= 0: errors.append("Bull-long staircase distance must be positive.")
    if float(values.get("bull_long_r_step_size_r", 0)) <= 0: errors.append("Bull-long staircase step size must be positive.")
    staircase_max=float(values.get("bull_long_r_step_maximum_r",0))
    if staircase_max < 0: errors.append("Bull-long staircase maximum cannot be negative.")
    if 0 < staircase_max <= float(values.get("bull_long_r_step_activation_r",0)): errors.append("Bull-long staircase maximum must be zero or above activation.")
    staircase_close=float(values.get("bull_long_r_step_activation_close_pct",0))
    if not 0 <= staircase_close < 100: errors.append("Bull-long staircase activation close must be from 0% up to, but not including, 100%.")
    if values.get("enable_bull_long_momentum_confirmation") and not values.get("enable_di_regime_reward_risk"): errors.append("Bull-long momentum confirmation requires regime-specific DI reward/risk.")
    if int(values.get("bull_long_confirmation_lookback_days", 0)) <= 0: errors.append("Bull-long confirmation lookback must be positive.")
    if float(values.get("bull_long_confirmation_return_threshold", -1)) <= -1: errors.append("Bull-long confirmation return threshold must be greater than -100%.")
    if float(values.get("bull_long_unconfirmed_reward_risk_ratio", 0)) <= 0: errors.append("Bull-long unconfirmed reward/risk must be positive.")
    if values.get("enable_bull_long_momentum_target_extension") and not values.get("enable_di_regime_reward_risk"): errors.append("Bull-long momentum target extension requires regime-specific DI reward/risk.")
    if int(values.get("bull_long_momentum_extension_lookback_days", 0)) <= 0: errors.append("Bull-long momentum extension lookback must be positive.")
    if float(values.get("bull_long_momentum_extension_return_threshold", -1)) <= -1: errors.append("Bull-long momentum extension return threshold must be greater than -100%.")
    if float(values.get("bull_long_momentum_extension_return_maximum", -1)) <= -1: errors.append("Bull-long momentum extension return maximum must be greater than -100%.")
    if values.get("enable_bull_long_momentum_extension_return_maximum") and float(values.get("bull_long_momentum_extension_return_maximum", 0)) <= float(values.get("bull_long_momentum_extension_return_threshold", 0)): errors.append("Bull-long momentum extension return maximum must exceed its minimum threshold.")
    if float(values.get("bull_long_momentum_extended_reward_risk_ratio", 0)) <= 0: errors.append("Bull-long momentum extended reward/risk must be positive.")
    if values.get("enable_bull_long_structural_confirmation") and not values.get("enable_di_regime_reward_risk"): errors.append("Bull-long structural confirmation requires regime-specific DI reward/risk.")
    if int(values.get("bull_long_structural_sma_days", 0)) <= 0: errors.append("Bull-long structural SMA days must be positive.")
    if int(values.get("bull_long_structural_slope_lookback_days", 0)) <= 0: errors.append("Bull-long structural SMA slope lookback must be positive.")
    if float(values.get("bull_long_structural_unconfirmed_reward_risk_ratio", 0)) <= 0: errors.append("Bull-long structural unconfirmed reward/risk must be positive.")
    for key, label in (
        ("enable_sideways_long_conditional_reward_risk", "sideways-long"),
        ("enable_sideways_short_conditional_reward_risk", "sideways-short"),
        ("enable_bear_short_conditional_reward_risk", "bear-short"),
    ):
        if values.get(key) and not values.get("enable_di_regime_reward_risk"): errors.append(f"Conditional {label} reward/risk requires regime-specific DI reward/risk.")
    if float(values.get("sideways_long_conditional_adx_maximum", 0)) < 0: errors.append("Sideways-long conditional ADX maximum must be non-negative.")
    if float(values.get("sideways_long_conditional_reward_risk_ratio", 0)) <= 0: errors.append("Sideways-long conditional reward/risk must be positive.")
    side_short_min = float(values.get("sideways_short_conditional_di_spread_minimum", 0))
    side_short_max = float(values.get("sideways_short_conditional_di_spread_maximum", 0))
    if side_short_min < 0 or side_short_max < 0: errors.append("Sideways-short conditional DI spread thresholds must be non-negative.")
    if side_short_min >= side_short_max: errors.append("Sideways-short conditional DI spread minimum must be below maximum.")
    if float(values.get("sideways_short_conditional_reward_risk_ratio", 0)) <= 0: errors.append("Sideways-short conditional reward/risk must be positive.")
    if float(values.get("bear_short_conditional_di_spread_maximum", 0)) < 0: errors.append("Bear-short conditional DI spread maximum must be non-negative.")
    if float(values.get("bear_short_conditional_reward_risk_ratio", 0)) <= 0: errors.append("Bear-short conditional reward/risk must be positive.")
    for key, label in (("directional_long_adx_maximum", "Long ADX maximum"), ("directional_short_adx_minimum", "Short ADX minimum")):
        try:
            if float(values.get(key, -1)) < 0: errors.append(f"{label} must be non-negative.")
        except (TypeError, ValueError): errors.append(f"{label} must be numeric.")
    if values.get("enable_directional_adx_filter") and not values.get("enable_di_direction_sizing"): errors.append("Direction-specific ADX filter requires DI-direction sizing.")
    if values.get("enable_long_momentum_filter") and not values.get("enable_di_direction_sizing"): errors.append("Long momentum filter requires DI-direction sizing.")
    try:
        if int(values.get("long_momentum_lookback_hours", 0)) <= 0: errors.append("Long momentum lookback hours must be positive.")
        if float(values.get("long_momentum_minimum_return", -1)) <= -1: errors.append("Long momentum minimum return must be greater than -100%.")
    except (TypeError, ValueError): errors.append("Long momentum settings must be numeric.")
    if values.get("enable_di_direction_sizing") and (values.get("enable_partial_take_profit") or values.get("enable_partial_stop_loss")): errors.append("DI-direction sizing cannot be combined with partial TP or partial SL.")
    if values.get("di_execution_mode") not in [e.value for e in DIExecutionMode]: errors.append("Invalid DI execution mode.")
    if values.get("di_execution_mode") == DIExecutionMode.PREFERRED_SIDE_ONLY.value and not values.get("enable_di_direction_sizing"): errors.append("Preferred-side-only execution requires DI-direction sizing.")
    if values.get("enable_bull_regime_short_filter") and not values.get("enable_di_direction_sizing"): errors.append("Bull-regime short filter requires DI-direction sizing.")
    if values.get("enable_bear_regime_adx_filter") and not values.get("enable_di_direction_sizing"): errors.append("Bear-regime ADX filter requires DI-direction sizing.")
    if values.get("enable_biased_short_adx_cap") and not values.get("enable_di_direction_sizing"): errors.append("Biased-short ADX cap requires DI-direction sizing.")
    if values.get("enable_short_vwap_distance_filter") and not values.get("enable_di_direction_sizing"): errors.append("Short VWAP-distance filter requires DI-direction sizing.")
    try:
        if float(values.get("biased_short_adx_maximum", -1)) < 0: errors.append("Biased-short ADX maximum must be non-negative.")
    except (TypeError, ValueError): errors.append("Biased-short ADX maximum must be numeric.")
    try:
        if float(values.get("short_vwap_minimum_distance_atr", -1)) < 0: errors.append("Short VWAP minimum distance must be non-negative.")
    except (TypeError, ValueError): errors.append("Short VWAP minimum distance must be numeric.")
    try:
        if int(values.get("bull_regime_lookback_days", 0)) <= 0: errors.append("Bull-regime lookback days must be positive.")
        if float(values.get("bull_regime_return_threshold", 0)) <= -1: errors.append("Bull-regime return threshold must be greater than -100%.")
    except (TypeError, ValueError): errors.append("Bull-regime settings must be numeric and positive.")
    try:
        if float(values.get("bear_regime_adx_minimum", -1)) < 0: errors.append("Bear-regime ADX minimum must be non-negative.")
    except (TypeError, ValueError): errors.append("Bear-regime ADX minimum must be numeric.")
    for key, label in (("max_random_wait_candles","Maximum Random Wait Candles"),("random_seed_count","Random Seed Count")):
        try:
            if int(values.get(key)) < (1 if key == "random_seed_count" else 0): errors.append(f"{label} is invalid.")
        except (TypeError, ValueError): errors.append(f"{label} is invalid.")
    if values.get("tie_policy") not in [TiePolicy.PESSIMISTIC.value, TiePolicy.OPTIMISTIC.value]: errors.append("Invalid tie policy.")
    if values.get("risk_mode") not in [e.value for e in RiskMode]: errors.append("Invalid risk mode.")
    if values.get("trade_direction") not in [e.value for e in TradeDirectionMode]: errors.append("Invalid trade direction mode.")
    if values.get("trail_apply_to") not in [e.value for e in TrailApplyTo]: errors.append("Apply Trailing To must be BOTH, LONG_ONLY, or SHORT_ONLY.")
    if values.get("trail_intrabar_mode") not in [e.value for e in TrailIntrabarMode]: errors.append("Intrabar Trailing Mode must be PESSIMISTIC or OPTIMISTIC.")
    if values.get("trail_activation_trigger") not in [e.value for e in TrailActivationTrigger]: errors.append("Invalid trailing activation trigger.")
    if values.get("enable_trailing_profit") and values.get("trail_activation_trigger")=="AFTER_TP1" and not values.get("enable_partial_take_profit"): errors.append("AFTER_TP1 trailing requires Partial Take Profit.")
    if values.get("enable_trailing_profit") and values.get("trail_activation_trigger")=="AFTER_SL1" and not values.get("enable_partial_stop_loss"): errors.append("AFTER_SL1 trailing requires Partial Stop Loss.")
    if values.get("enable_trailing_profit") and values.get("trail_activation_trigger")=="AFTER_TP1_OR_SL1" and not (values.get("enable_partial_take_profit") or values.get("enable_partial_stop_loss")): errors.append("AFTER_TP1_OR_SL1 trailing requires a partial TP or SL ladder.")
    if values.get("daily_entry_missed_policy") not in [e.value for e in DailyEntryMissedPolicy]: errors.append("Invalid daily entry missed policy.")
    try:
        hh, mm = [int(part) for part in str(values.get("daily_entry_time", "00:00")).split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
        if (hh * 60 + mm) % int(values.get("strategy_timeframe_minutes", 15)) != 0: errors.append("Daily entry time must align to the strategy timeframe.")
    except (TypeError, ValueError): errors.append("Daily entry time must be HH:MM.")
    if values.get("use_intrabar_data") and int(values.get("intrabar_timeframe_minutes", 1)) >= int(values.get("strategy_timeframe_minutes", 15)): errors.append("Intrabar timeframe must be less than strategy timeframe.")
    if int(values.get("telemetry_interval_minutes", 15)) % int(values.get("strategy_timeframe_minutes", 15)) != 0: errors.append("Telemetry interval must be a multiple of the strategy timeframe.")
    if values.get("intrabar_missing_policy") not in [e.value for e in IntrabarMissingPolicy]: errors.append("Invalid missing intrabar policy.")
    if values.get("be_mode") not in [e.value for e in BreakEvenMode]: errors.append("Invalid BE mode.")
    if values.get("be_same_candle_policy") not in [e.value for e in BreakEvenSameCandlePolicy]: errors.append("Invalid same-candle BE policy.")
    if values.get("adx_filter_mode") not in [e.value for e in AdxFilterMode]: errors.append("Invalid ADX filter mode.")
    if values.get("bb_width_filter_mode") not in [e.value for e in BBWidthFilterMode]: errors.append("Invalid BB width filter mode.")
    if values.get("di_spread_filter_mode") not in [e.value for e in DISpreadFilterMode]: errors.append("Invalid DI spread filter mode.")
    try:
        if int(values.get("adx_period", 0)) < 1: errors.append("ADX period must be >= 1.")
        if float(values.get("adx_maximum", 0)) < 0 or float(values.get("adx_minimum", 0)) < 0: errors.append("ADX thresholds must be >= 0.")
    except (TypeError, ValueError): errors.append("ADX settings are invalid.")
    try:
        if float(values.get("bb_width_maximum", 0)) < 0 or float(values.get("bb_width_minimum", 0)) < 0: errors.append("BB width thresholds must be >= 0.")
        if float(values.get("di_spread_maximum", 0)) < 0 or float(values.get("di_spread_minimum", 0)) < 0: errors.append("DI spread thresholds must be >= 0.")
    except (TypeError, ValueError): errors.append("Market compression filter settings are invalid.")
    try:
        if float(values.get("be_offset_r", 0)) < 0: errors.append("BE Offset in R must be >= 0.")
    except (TypeError, ValueError): errors.append("BE Offset in R must be >= 0.")
    if values.get("enable_remaining_leg_timeout_after_first_sl"):
        try:
            if int(values.get("remaining_leg_timeout_after_first_sl_minutes", 0)) <= 0: errors.append("Remaining-Leg Timeout After First SL must be > 0 when enabled.")
        except (TypeError, ValueError): errors.append("Remaining-Leg Timeout After First SL must be > 0 when enabled.")
    if values.get("enable_remaining_leg_timeout_profit_extension") and not values.get("enable_remaining_leg_timeout_after_first_sl"):
        errors.append("Profit-based timeout extension requires Remaining-Leg Timeout After First SL to be enabled.")
    if values.get("enable_remaining_leg_checkpoint_score_extension") and not values.get("enable_remaining_leg_timeout_after_first_sl"):
        errors.append("Checkpoint score extension requires Remaining-Leg Timeout After First SL to be enabled.")
    if values.get("enable_remaining_leg_checkpoint_score_extension") and values.get("enable_remaining_leg_timeout_profit_extension"):
        errors.append("Choose either profit-only extension or checkpoint score extension, not both.")
    if values.get("enable_first_sl_survivor_partial_close") and values.get("enable_partial_take_profit"):
        errors.append("First-SL survivor partial close cannot be combined with Partial Take Profit.")
    if float(values.get("sl2_r", 8)) <= float(values.get("sl1_r", 0.5)):
        errors.append("SL2_R must be greater than SL1_R.")
    if not 0 < float(values.get("sl1_close_pct", 50)) < 100:
        errors.append("SL1 close percentage must be between 0% and 100%.")
    if values.get("enable_first_sl_survivor_partial_close"):
        try:
            pct=float(values.get("first_sl_survivor_partial_close_pct", 0))
            if pct <= 0 or pct >= 100: errors.append("First-SL survivor partial close must be between 0% and 100%.")
        except (TypeError, ValueError): errors.append("First-SL survivor partial close must be between 0% and 100%.")
    if values.get("enable_checkpoint_zero_score_confirmation") and not values.get("enable_remaining_leg_checkpoint_score_extension"):
        errors.append("Consecutive zero-score confirmation requires the checkpoint score extension.")
    if values.get("enable_checkpoint_zero_score_confirmation"):
        try:
            if int(values.get("checkpoint_zero_score_confirmations_required", 0)) < 2: errors.append("Zero-score confirmations required must be at least 2.")
        except (TypeError, ValueError): errors.append("Zero-score confirmations required must be a whole number.")
        try:
            if int(values.get("checkpoint_zero_score_recheck_minutes", 0)) <= 0: errors.append("Zero-score recheck interval must be positive.")
        except (TypeError, ValueError): errors.append("Zero-score recheck interval must be positive.")
    if values.get("enable_reentry_gate_after_remaining_leg_timeout") and not values.get("enable_remaining_leg_timeout_after_first_sl"):
        errors.append("Checkpoint re-entry gate requires Remaining-Leg Timeout After First SL to be enabled.")
    try:
        if float(values.get("remaining_leg_timeout_profit_threshold_r", 0)) < 0: errors.append("Timeout Extension Threshold (R) must be >= 0.")
    except (TypeError, ValueError): errors.append("Timeout Extension Threshold (R) must be >= 0.")
    if values.get("enable_remaining_leg_checkpoint_score_extension"):
        condition_count = sum(bool(values.get(key)) for key in ("checkpoint_score_use_profit", "checkpoint_score_use_atr_pct", "checkpoint_score_use_directional_di", "checkpoint_score_use_bb_width_pct"))
        try:
            required = int(values.get("checkpoint_score_min_conditions", 0))
            if condition_count == 0 or required < 1 or required > condition_count: errors.append("Checkpoint score required conditions must be between 1 and the number of enabled conditions.")
        except (TypeError, ValueError): errors.append("Checkpoint score required conditions must be a whole number.")
    if values.get("enable_both_open_timeout"):
        try:
            if int(values.get("max_both_open_minutes", 0)) <= 0: errors.append("Maximum Both-Open Time must be > 0 when enabled.")
        except (TypeError, ValueError): errors.append("Maximum Both-Open Time must be > 0 when enabled.")
    return errors


def build_backtest_config(values: dict[str, Any], require_paths: bool = True) -> BacktestConfig:
    merged = {**default_gui_config(), **values}
    legacy_di_minimum = float(values.get("di_direction_minimum_spread", DEFAULT_GUI_CONFIG["di_direction_minimum_spread"]))
    if "di_direction_long_minimum_spread" not in values:
        merged["di_direction_long_minimum_spread"] = legacy_di_minimum
    if "di_direction_short_minimum_spread" not in values:
        merged["di_direction_short_minimum_spread"] = legacy_di_minimum
    legacy_di_ratio = float(values.get("di_reward_risk_ratio", DEFAULT_GUI_CONFIG["di_reward_risk_ratio"]))
    if "di_long_reward_risk_ratio" not in values:
        merged["di_long_reward_risk_ratio"] = legacy_di_ratio
    if "di_short_reward_risk_ratio" not in values:
        merged["di_short_reward_risk_ratio"] = legacy_di_ratio
    errors = validate_config_values(merged, require_paths=require_paths)
    if errors:
        raise ValueError("\n".join(errors))
    return BacktestConfig(
        input_csv=Path(merged["input_csv"]), strategy_csv=Path(merged["input_csv"] if merged.get("strategy_csv") == DEFAULT_GUI_CONFIG.get("strategy_csv") else (merged.get("strategy_csv") or merged["input_csv"])), intrabar_csv=Path(merged["intrabar_csv"]) if merged.get("intrabar_csv") else None, output_dir=Path(merged["output_dir"]),
        enable_strategy_profiles=bool(merged["enable_strategy_profiles"]), strategy_profile_run_mode=str(merged["strategy_profile_run_mode"]), strategy_profiles=merged["strategy_profiles"],
        vwap_confirmation_mode=VWAPConfirmationMode(merged["vwap_confirmation_mode"]), vwap_retest_window_candles=int(merged["vwap_retest_window_candles"]), vwap_retest_tolerance_atr=float(merged["vwap_retest_tolerance_atr"]),
        sl_mult=float(merged["sl_mult"]), tp_mult=float(merged["tp_mult"]),
        flip_filtered_di_direction=bool(merged["flip_filtered_di_direction"]),
        entry_mode=EntryMode(merged["entry_mode"]), entry_interval=int(merged["entry_interval"]), vwap_breakout_lookback_hours=float(merged["vwap_breakout_lookback_hours"]), vwap_volume_lookback=int(merged["vwap_volume_lookback"]), vwap_volume_multiplier=float(merged["vwap_volume_multiplier"]), vwap_slope_lookback=int(merged["vwap_slope_lookback"]), vwap_atr_pct_minimum=float(merged["vwap_atr_pct_minimum"]), vwap_atr_pct_maximum=float(merged["vwap_atr_pct_maximum"]), enable_random_entry=bool(merged["enable_random_entry"]), entry_timing_mode=EntryTimingMode(merged["entry_timing_mode"]), random_entry_probability=float(merged["random_entry_probability"]), random_seed=int(merged["random_seed"]), enable_coin_flip_sizing=bool(merged["enable_coin_flip_sizing"]), coin_flip_seed=int(merged["coin_flip_seed"]), coin_flip_large_multiplier=float(merged["coin_flip_large_multiplier"]), coin_flip_small_multiplier=float(merged["coin_flip_small_multiplier"]), enable_di_direction_sizing=bool(merged["enable_di_direction_sizing"]), enable_direction_voting=bool(merged["enable_direction_voting"]), direction_vote_use_di=bool(merged["direction_vote_use_di"]), direction_vote_use_structure=bool(merged["direction_vote_use_structure"]), direction_vote_structure_lookback=int(merged["direction_vote_structure_lookback"]), direction_vote_use_momentum=bool(merged["direction_vote_use_momentum"]), direction_vote_momentum_lookback_hours=int(merged["direction_vote_momentum_lookback_hours"]), direction_vote_momentum_threshold=float(merged["direction_vote_momentum_threshold"]), direction_vote_use_volume_pressure=bool(merged["direction_vote_use_volume_pressure"]), direction_vote_volume_lookback=int(merged["direction_vote_volume_lookback"]), direction_vote_volume_threshold=float(merged["direction_vote_volume_threshold"]), direction_vote_use_higher_timeframe=bool(merged["direction_vote_use_higher_timeframe"]), direction_vote_higher_timeframe_hours=int(merged["direction_vote_higher_timeframe_hours"]), direction_vote_higher_timeframe_sma_period=int(merged["direction_vote_higher_timeframe_sma_period"]), direction_vote_minimum_votes=int(merged["direction_vote_minimum_votes"]), di_direction_minimum_spread=float(merged["di_direction_minimum_spread"]), di_direction_long_minimum_spread=float(merged["di_direction_long_minimum_spread"]), di_direction_short_minimum_spread=float(merged["di_direction_short_minimum_spread"]), di_execution_mode=DIExecutionMode(merged["di_execution_mode"]), di_reward_risk_ratio=float(merged["di_reward_risk_ratio"]), di_long_reward_risk_ratio=float(merged["di_long_reward_risk_ratio"]), di_short_reward_risk_ratio=float(merged["di_short_reward_risk_ratio"]), enable_di_regime_reward_risk=bool(merged["enable_di_regime_reward_risk"]), di_regime_bear_return_threshold=float(merged["di_regime_bear_return_threshold"]), di_long_bull_reward_risk_ratio=float(merged["di_long_bull_reward_risk_ratio"]), di_long_bear_reward_risk_ratio=float(merged["di_long_bear_reward_risk_ratio"]), di_long_sideways_reward_risk_ratio=float(merged["di_long_sideways_reward_risk_ratio"]), di_short_bull_reward_risk_ratio=float(merged["di_short_bull_reward_risk_ratio"]), di_short_bear_reward_risk_ratio=float(merged["di_short_bear_reward_risk_ratio"]), di_short_sideways_reward_risk_ratio=float(merged["di_short_sideways_reward_risk_ratio"]), enable_bull_long_conditional_reward_risk=bool(merged["enable_bull_long_conditional_reward_risk"]), bull_long_conditional_bb_width_minimum=float(merged["bull_long_conditional_bb_width_minimum"]), bull_long_conditional_adx_maximum=float(merged["bull_long_conditional_adx_maximum"]), bull_long_conditional_reward_risk_ratio=float(merged["bull_long_conditional_reward_risk_ratio"]), enable_sideways_long_conditional_reward_risk=bool(merged["enable_sideways_long_conditional_reward_risk"]), sideways_long_conditional_adx_maximum=float(merged["sideways_long_conditional_adx_maximum"]), sideways_long_conditional_reward_risk_ratio=float(merged["sideways_long_conditional_reward_risk_ratio"]), enable_sideways_short_conditional_reward_risk=bool(merged["enable_sideways_short_conditional_reward_risk"]), sideways_short_conditional_di_spread_minimum=float(merged["sideways_short_conditional_di_spread_minimum"]), sideways_short_conditional_di_spread_maximum=float(merged["sideways_short_conditional_di_spread_maximum"]), sideways_short_conditional_reward_risk_ratio=float(merged["sideways_short_conditional_reward_risk_ratio"]), enable_bear_short_conditional_reward_risk=bool(merged["enable_bear_short_conditional_reward_risk"]), bear_short_conditional_di_spread_maximum=float(merged["bear_short_conditional_di_spread_maximum"]), bear_short_conditional_reward_risk_ratio=float(merged["bear_short_conditional_reward_risk_ratio"]), enable_directional_adx_filter=bool(merged["enable_directional_adx_filter"]), directional_long_adx_maximum=float(merged["directional_long_adx_maximum"]), directional_short_adx_minimum=float(merged["directional_short_adx_minimum"]), enable_atr_checkpoint_tp_extension=bool(merged["enable_atr_checkpoint_tp_extension"]), atr_checkpoint_di_spread_minimum=float(merged["atr_checkpoint_di_spread_minimum"]), atr_checkpoint_bb_width_minimum=float(merged["atr_checkpoint_bb_width_minimum"]), atr_checkpoint_profit_lock_start=float(merged["atr_checkpoint_profit_lock_start"]), atr_checkpoint_profit_lock_distance=float(merged["atr_checkpoint_profit_lock_distance"]), enable_biased_short_adx_cap=bool(merged["enable_biased_short_adx_cap"]), biased_short_adx_maximum=float(merged["biased_short_adx_maximum"]), enable_short_vwap_distance_filter=bool(merged["enable_short_vwap_distance_filter"]), short_vwap_minimum_distance_atr=float(merged["short_vwap_minimum_distance_atr"]), enable_bull_regime_short_filter=bool(merged["enable_bull_regime_short_filter"]), market_regime_method=str(merged["market_regime_method"]), structural_regime_sma_days=int(merged["structural_regime_sma_days"]), structural_regime_slope_lookback_days=int(merged["structural_regime_slope_lookback_days"]), structural_regime_benchmark_csv=Path(merged["structural_regime_benchmark_csv"]) if merged.get("structural_regime_benchmark_csv") else None, bull_regime_lookback_days=int(merged["bull_regime_lookback_days"]), bull_regime_return_threshold=float(merged["bull_regime_return_threshold"]), random_entry_start_mode=RandomEntryStartMode(merged["random_entry_start_mode"]), randomize_first_entry=bool(merged["randomize_first_entry"]), max_random_wait_candles=int(merged["max_random_wait_candles"]), enable_random_entry_batch=bool(merged["enable_random_entry_batch"]), random_seed_start=int(merged["random_seed_start"]), random_seed_count=int(merged["random_seed_count"]), enable_daily_entry_schedule=bool(merged["enable_daily_entry_schedule"]), daily_entry_time=str(merged["daily_entry_time"]), daily_entry_timezone=str(merged["daily_entry_timezone"]), daily_entry_missed_policy=DailyEntryMissedPolicy(merged["daily_entry_missed_policy"]), enable_skip_monday_entries=bool(merged["enable_skip_monday_entries"]), skip_monday_timezone=str(merged["skip_monday_timezone"]),
        enable_long_momentum_filter=bool(merged["enable_long_momentum_filter"]), long_momentum_lookback_hours=int(merged["long_momentum_lookback_hours"]), long_momentum_minimum_return=float(merged["long_momentum_minimum_return"]),
        enable_regime_direction_filter=bool(merged["enable_regime_direction_filter"]), allow_bull_long=bool(merged["allow_bull_long"]), allow_bull_short=bool(merged["allow_bull_short"]), allow_bear_long=bool(merged["allow_bear_long"]), allow_bear_short=bool(merged["allow_bear_short"]), allow_sideways_long=bool(merged["allow_sideways_long"]), allow_sideways_short=bool(merged["allow_sideways_short"]),
        enable_directional_di_spread_range=bool(merged["enable_directional_di_spread_range"]), directional_long_di_spread_minimum=float(merged["directional_long_di_spread_minimum"]), directional_long_di_spread_maximum=float(merged["directional_long_di_spread_maximum"]), directional_short_di_spread_minimum=float(merged["directional_short_di_spread_minimum"]), directional_short_di_spread_maximum=float(merged["directional_short_di_spread_maximum"]),
        enable_directional_adx_range=bool(merged["enable_directional_adx_range"]), directional_long_adx_minimum=float(merged["directional_long_adx_minimum"]), directional_long_adx_range_maximum=float(merged["directional_long_adx_range_maximum"]), directional_short_adx_range_minimum=float(merged["directional_short_adx_range_minimum"]), directional_short_adx_maximum=float(merged["directional_short_adx_maximum"]),
        enable_directional_atr_pct_range=bool(merged["enable_directional_atr_pct_range"]), directional_long_atr_pct_minimum=float(merged["directional_long_atr_pct_minimum"]), directional_long_atr_pct_maximum=float(merged["directional_long_atr_pct_maximum"]), directional_short_atr_pct_minimum=float(merged["directional_short_atr_pct_minimum"]), directional_short_atr_pct_maximum=float(merged["directional_short_atr_pct_maximum"]),
        enable_directional_rsi_range=bool(merged["enable_directional_rsi_range"]), directional_rsi_period=int(merged["directional_rsi_period"]), directional_long_rsi_minimum=float(merged["directional_long_rsi_minimum"]), directional_long_rsi_maximum=float(merged["directional_long_rsi_maximum"]), directional_short_rsi_minimum=float(merged["directional_short_rsi_minimum"]), directional_short_rsi_maximum=float(merged["directional_short_rsi_maximum"]),
        enable_directional_close_location_range=bool(merged["enable_directional_close_location_range"]), directional_long_close_location_minimum=float(merged["directional_long_close_location_minimum"]), directional_long_close_location_maximum=float(merged["directional_long_close_location_maximum"]), directional_short_close_location_minimum=float(merged["directional_short_close_location_minimum"]), directional_short_close_location_maximum=float(merged["directional_short_close_location_maximum"]),
        enable_directional_momentum_range=bool(merged["enable_directional_momentum_range"]), directional_momentum_lookback_hours=int(merged["directional_momentum_lookback_hours"]), directional_long_momentum_minimum=float(merged["directional_long_momentum_minimum"]), directional_long_momentum_maximum=float(merged["directional_long_momentum_maximum"]), directional_short_momentum_minimum=float(merged["directional_short_momentum_minimum"]), directional_short_momentum_maximum=float(merged["directional_short_momentum_maximum"]),
        enable_bull_long_momentum_confirmation=bool(merged["enable_bull_long_momentum_confirmation"]), bull_long_confirmation_lookback_days=int(merged["bull_long_confirmation_lookback_days"]), bull_long_confirmation_return_threshold=float(merged["bull_long_confirmation_return_threshold"]), bull_long_unconfirmed_reward_risk_ratio=float(merged["bull_long_unconfirmed_reward_risk_ratio"]),
        enable_bull_long_momentum_target_extension=bool(merged["enable_bull_long_momentum_target_extension"]), bull_long_momentum_extension_lookback_days=int(merged["bull_long_momentum_extension_lookback_days"]), bull_long_momentum_extension_return_threshold=float(merged["bull_long_momentum_extension_return_threshold"]), enable_bull_long_momentum_extension_return_maximum=bool(merged["enable_bull_long_momentum_extension_return_maximum"]), bull_long_momentum_extension_return_maximum=float(merged["bull_long_momentum_extension_return_maximum"]), bull_long_momentum_extended_reward_risk_ratio=float(merged["bull_long_momentum_extended_reward_risk_ratio"]),
        enable_bull_long_structural_confirmation=bool(merged["enable_bull_long_structural_confirmation"]), bull_long_structural_sma_days=int(merged["bull_long_structural_sma_days"]), bull_long_structural_slope_lookback_days=int(merged["bull_long_structural_slope_lookback_days"]), bull_long_structural_unconfirmed_reward_risk_ratio=float(merged["bull_long_structural_unconfirmed_reward_risk_ratio"]),
        enable_bull_long_r_step_trailing=bool(merged["enable_bull_long_r_step_trailing"]), bull_long_r_step_activation_r=float(merged["bull_long_r_step_activation_r"]), bull_long_r_step_distance_r=float(merged["bull_long_r_step_distance_r"]), bull_long_r_step_size_r=float(merged["bull_long_r_step_size_r"]), bull_long_r_step_maximum_r=float(merged["bull_long_r_step_maximum_r"]), bull_long_r_step_activation_close_pct=float(merged["bull_long_r_step_activation_close_pct"]),
        enable_bear_regime_adx_filter=bool(merged["enable_bear_regime_adx_filter"]), bear_regime_adx_minimum=float(merged["bear_regime_adx_minimum"]),
        max_active_pairs=int(merged["max_active_pairs"]), tie_policy=TiePolicy(merged["tie_policy"]),
        risk_mode=RiskMode(merged["risk_mode"]), atr_period=int(merged["atr_period"]),
        atr_multiplier=float(merged["atr_multiplier"]), enable_adx_filter=bool(merged["enable_adx_filter"]), adx_period=int(merged["adx_period"]), adx_filter_mode=AdxFilterMode(merged["adx_filter_mode"]), adx_maximum=float(merged["adx_maximum"]), adx_minimum=float(merged["adx_minimum"]), enable_bb_width_filter=bool(merged["enable_bb_width_filter"]), bb_width_filter_mode=BBWidthFilterMode(merged["bb_width_filter_mode"]), bb_width_maximum=float(merged["bb_width_maximum"]), bb_width_minimum=float(merged["bb_width_minimum"]), enable_di_spread_filter=bool(merged["enable_di_spread_filter"]), di_spread_filter_mode=DISpreadFilterMode(merged["di_spread_filter_mode"]), di_spread_maximum=float(merged["di_spread_maximum"]), di_spread_minimum=float(merged["di_spread_minimum"]), percent_r=float(merged["percent_r"]),
        fixed_r=float(merged["fixed_r"]), initial_equity=float(merged["initial_equity"]),
        risk_per_leg=float(merged["risk_per_leg"]), maker_fee=float(merged["maker_fee"]),
        taker_fee=float(merged["taker_fee"]), use_maker_entry=bool(merged["use_maker_entry"]),
        use_maker_exit=bool(merged["use_maker_exit"]), slippage=float(merged["slippage"]),
        strategy_timeframe_minutes=int(merged["strategy_timeframe_minutes"]), intrabar_timeframe_minutes=int(merged["intrabar_timeframe_minutes"]),
        use_intrabar_data=bool(merged["use_intrabar_data"]), trading_start_date=merged.get("trading_start_date"), trading_end_date=merged.get("trading_end_date"),
        max_effective_leverage_per_leg=float(merged["max_effective_leverage_per_leg"]) if merged.get("max_effective_leverage_per_leg") not in (None, "") else None,
        max_combined_effective_leverage=float(merged["max_combined_effective_leverage"]) if merged.get("max_combined_effective_leverage") not in (None, "") else None,
        intrabar_missing_policy=IntrabarMissingPolicy(merged["intrabar_missing_policy"]), zero_cost_comparison=bool(merged["zero_cost_comparison"]), trade_direction=TradeDirectionMode(merged["trade_direction"]), enable_partial_take_profit=bool(merged["enable_partial_take_profit"]), enable_partial_stop_loss=bool(merged["enable_partial_stop_loss"]), sl1_r=float(merged["sl1_r"]), sl1_close_pct=float(merged["sl1_close_pct"]), sl2_r=float(merged["sl2_r"]), tp1_r=float(merged["tp1_r"]), tp1_close_pct=float(merged["tp1_close_pct"]), tp2_r=float(merged["tp2_r"]), tp2_close_pct=float(merged["tp2_close_pct"]), stop_loss_r=float(merged["stop_loss_r"]), after_tp1_stop_mode=AfterTP1StopMode(merged["after_tp1_stop_mode"]), after_tp1_stop_offset_r=float(merged["after_tp1_stop_offset_r"]), tp2_exit_mode=TP2ExitMode(merged["tp2_exit_mode"]), enable_trailing_profit=bool(merged["enable_trailing_profit"]), trail_activation_trigger=TrailActivationTrigger(merged["trail_activation_trigger"]), trail_activation_r=float(merged["trail_activation_r"]), trail_distance_r=float(merged["trail_distance_r"]), trail_apply_to=TrailApplyTo(merged["trail_apply_to"]), trail_intrabar_mode=TrailIntrabarMode(merged["trail_intrabar_mode"]),
        enable_both_open_timeout=bool(merged["enable_both_open_timeout"]), max_both_open_minutes=int(merged["max_both_open_minutes"]), enable_remaining_leg_timeout_after_first_sl=bool(merged["enable_remaining_leg_timeout_after_first_sl"]), remaining_leg_timeout_after_first_sl_minutes=int(merged["remaining_leg_timeout_after_first_sl_minutes"]), enable_remaining_leg_timeout_profit_extension=bool(merged["enable_remaining_leg_timeout_profit_extension"]), remaining_leg_timeout_profit_threshold_r=float(merged["remaining_leg_timeout_profit_threshold_r"]), enable_remaining_leg_checkpoint_score_extension=bool(merged["enable_remaining_leg_checkpoint_score_extension"]), checkpoint_score_use_profit=bool(merged["checkpoint_score_use_profit"]), checkpoint_score_min_profit_r=float(merged["checkpoint_score_min_profit_r"]), checkpoint_score_use_atr_pct=bool(merged["checkpoint_score_use_atr_pct"]), checkpoint_score_max_atr_pct=float(merged["checkpoint_score_max_atr_pct"]), checkpoint_score_use_directional_di=bool(merged["checkpoint_score_use_directional_di"]), checkpoint_score_min_directional_di=float(merged["checkpoint_score_min_directional_di"]), checkpoint_score_use_bb_width_pct=bool(merged["checkpoint_score_use_bb_width_pct"]), checkpoint_score_max_bb_width_pct=float(merged["checkpoint_score_max_bb_width_pct"]), checkpoint_score_min_conditions=int(merged["checkpoint_score_min_conditions"]), enable_first_sl_survivor_partial_close=bool(merged["enable_first_sl_survivor_partial_close"]), first_sl_survivor_partial_close_pct=float(merged["first_sl_survivor_partial_close_pct"]), enable_checkpoint_zero_score_confirmation=bool(merged["enable_checkpoint_zero_score_confirmation"]), checkpoint_zero_score_confirmations_required=int(merged["checkpoint_zero_score_confirmations_required"]), checkpoint_zero_score_recheck_minutes=int(merged["checkpoint_zero_score_recheck_minutes"]), enable_reentry_gate_after_remaining_leg_timeout=bool(merged["enable_reentry_gate_after_remaining_leg_timeout"]),
        enable_be_after_opposite_sl=bool(merged["enable_be_after_opposite_sl"]), be_mode=BreakEvenMode(merged["be_mode"]), be_offset_r=float(merged["be_offset_r"]), be_same_candle_policy=BreakEvenSameCandlePolicy(merged["be_same_candle_policy"]),
        run_name=str(merged.get("run_name", "")), enable_trade_telemetry=bool(merged["enable_trade_telemetry"]), save_full_telemetry_csv=bool(merged["save_full_telemetry_csv"]), save_trade_journey_summary=bool(merged["save_trade_journey_summary"]), save_trade_journey_charts=bool(merged["save_trade_journey_charts"]), telemetry_interval_minutes=int(merged["telemetry_interval_minutes"]), enable_indicator_lifecycle_analysis=bool(merged["enable_indicator_lifecycle_analysis"]), lifecycle_phases=int(merged["lifecycle_phases"]), lifecycle_early_checkpoints=tuple(int(v) for v in merged["lifecycle_early_checkpoints"]), lifecycle_minimum_bucket_sample=int(merged["lifecycle_minimum_bucket_sample"]), create_lifecycle_charts=bool(merged["create_lifecycle_charts"]), lifecycle_flat_pattern_threshold_pct=float(merged["lifecycle_flat_pattern_threshold_pct"]), save_feature_analysis_reports=bool(merged["save_feature_analysis_reports"]), save_indicator_analysis_reports=bool(merged["save_indicator_analysis_reports"]), create_standard_charts=bool(merged["create_standard_charts"]),
    )


def save_config_json(path: str | Path, values: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(canonical_config_values({**default_gui_config(), **values}), indent=2, default=str))


_OBSOLETE_EXACT = {
    "trade_direction","sl_mult","tp_mult","enable_partial_stop_loss","sl1_r","sl1_close_pct","sl2_r","enable_partial_take_profit","tp1_r","tp1_close_pct","tp2_r","tp2_close_pct","stop_loss_r","after_tp1_stop_mode","after_tp1_stop_offset_r","tp2_exit_mode","enable_trailing_profit","trail_activation_trigger","trail_activation_r","trail_distance_r","trail_apply_to","trail_intrabar_mode",
    "enable_both_open_timeout","max_both_open_minutes","both_open_timeout_unit","enable_be_after_opposite_sl","be_mode","be_offset_r","be_same_candle_policy",
    "enable_adx_filter","adx_filter_mode","adx_minimum","adx_maximum","enable_bb_width_filter","bb_width_filter_mode","bb_width_minimum","bb_width_maximum",
    "enable_di_spread_filter","di_spread_filter_mode","di_spread_minimum","di_spread_maximum","enable_skip_monday_entries","skip_monday_timezone",
    "enable_random_entry","entry_timing_mode","random_entry_probability","random_seed","random_entry_start_mode","randomize_first_entry","max_random_wait_candles","enable_random_entry_batch","random_seed_start","random_seed_count",
    "enable_coin_flip_sizing","coin_flip_seed","coin_flip_large_multiplier","coin_flip_small_multiplier","enable_di_direction_sizing","di_execution_mode",
    "enable_remaining_leg_timeout_after_first_sl","remaining_leg_timeout_after_first_sl_minutes","remaining_leg_timeout_after_first_sl_unit","enable_remaining_leg_timeout_profit_extension","remaining_leg_timeout_profit_threshold_r",
    "enable_remaining_leg_checkpoint_score_extension","enable_first_sl_survivor_partial_close","first_sl_survivor_partial_close_pct","enable_checkpoint_zero_score_confirmation","checkpoint_zero_score_confirmations_required","checkpoint_zero_score_recheck_minutes","checkpoint_zero_score_recheck_unit","enable_reentry_gate_after_remaining_leg_timeout",
    "enable_atr_checkpoint_tp_extension","atr_checkpoint_di_spread_minimum","atr_checkpoint_bb_width_minimum","atr_checkpoint_profit_lock_start","atr_checkpoint_profit_lock_distance",
    "vwap_breakout_lookback_hours","vwap_volume_lookback","vwap_volume_multiplier","vwap_slope_lookback","vwap_atr_pct_minimum","vwap_atr_pct_maximum","vwap_confirmation_mode","vwap_retest_window_candles","vwap_retest_tolerance_atr",
}
_OBSOLETE_PREFIXES = ("di_direction_","di_reward_","di_long_","di_short_","enable_di_regime_","enable_bull_long_","bull_long_","enable_sideways_","sideways_","enable_bear_short_","bear_short_","enable_directional_","directional_","enable_long_momentum_","long_momentum_","enable_regime_direction_","allow_bull_","allow_bear_","allow_sideways_","enable_biased_","biased_","enable_short_vwap_","short_vwap_","enable_bull_regime_short_","enable_bear_regime_adx_","bear_regime_adx_","checkpoint_score_")


def canonical_config_values(values: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, profile-only public configuration format."""
    keep_regime={"di_regime_bear_return_threshold","bull_regime_lookback_days","bull_regime_return_threshold"}
    result={}
    for key,value in values.items():
        if key in keep_regime or key not in _OBSOLETE_EXACT and not key.startswith(_OBSOLETE_PREFIXES): result[key]=value
    result["enable_strategy_profiles"]=True
    return result


def load_config_json(path: str | Path) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text())
    # Saved configs created before structural regimes existed retain their
    # original trailing-return semantics.
    loaded.setdefault("market_regime_method", "ASSET_RETURN")
    if not loaded.get("market_symbol"):
        match=re.search(r"([A-Z0-9]+USDT)(?:[_-]|$)",Path(str(loaded.get("strategy_csv") or loaded.get("input_csv") or "")).stem.upper())
        if match: loaded["market_symbol"]=match.group(1)
    legacy_di_minimum = loaded.get("di_direction_minimum_spread", DEFAULT_GUI_CONFIG["di_direction_minimum_spread"])
    loaded.setdefault("di_direction_long_minimum_spread", legacy_di_minimum)
    loaded.setdefault("di_direction_short_minimum_spread", legacy_di_minimum)
    legacy_di_ratio = loaded.get("di_reward_risk_ratio", DEFAULT_GUI_CONFIG["di_reward_risk_ratio"])
    loaded.setdefault("di_long_reward_risk_ratio", legacy_di_ratio)
    loaded.setdefault("di_short_reward_risk_ratio", legacy_di_ratio)
    return {**default_gui_config(), **loaded}
