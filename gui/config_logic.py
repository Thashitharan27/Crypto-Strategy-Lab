"""Pure helpers for GUI configuration conversion and validation."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy, AdxFilterMode, BBWidthFilterMode, DISpreadFilterMode, TradeDirectionMode, DailyEntryMissedPolicy, TrailApplyTo, TrailIntrabarMode, AfterTP1StopMode, TP2ExitMode, EntryTimingMode, RandomEntryStartMode

DEFAULT_GUI_CONFIG: dict[str, Any] = {
    "input_csv": "data/binance_ohlcv.csv", "strategy_csv": "data/BTCUSDT_15m.csv", "intrabar_csv": "data/BTCUSDT_1m.csv", "output_dir": "output", "run_name": "",
    "sl_mult": 2.0, "tp_mult": 3.0, "entry_mode": "WAIT_UNTIL_CLOSED",
    "enable_random_entry": False, "entry_timing_mode": "CURRENT", "random_entry_probability": 0.50, "random_seed": 42, "random_entry_start_mode": "NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE", "randomize_first_entry": True, "max_random_wait_candles": 0, "enable_random_entry_batch": False, "random_seed_start": 1, "random_seed_count": 100,
    "entry_interval": 1, "enable_daily_entry_schedule": False, "daily_entry_time": "00:00", "daily_entry_timezone": "UTC", "daily_entry_missed_policy": "SKIP_DAY", "max_active_pairs": 1, "tie_policy": "PESSIMISTIC",
    "risk_mode": "ATR", "atr_period": 14, "atr_multiplier": 1.0, "enable_adx_filter": False, "adx_period": 14, "adx_filter_mode": "Disabled", "adx_maximum": 25.0, "adx_minimum": 20.0, "enable_bb_width_filter": False, "bb_width_filter_mode": "Disabled", "bb_width_maximum": 0.03, "bb_width_minimum": 0.0, "enable_di_spread_filter": False, "di_spread_filter_mode": "Disabled", "di_spread_maximum": 10.0, "di_spread_minimum": 0.0,
    "percent_r": 0.002, "fixed_r": 100.0, "initial_equity": 1000.0,
    "risk_per_leg": 0.005, "maker_fee": 0.0002, "taker_fee": 0.0005,
    "use_maker_entry": False, "use_maker_exit": False, "slippage": 0.0001,
    "strategy_timeframe_minutes": 15, "intrabar_timeframe_minutes": 1, "use_intrabar_data": True,
    "trading_start_date": None, "trading_end_date": None, "max_effective_leverage_per_leg": None,
    "max_combined_effective_leverage": None, "intrabar_missing_policy": "WARN_AND_USE_15M", "zero_cost_comparison": False, "trade_direction": "BOTH", "enable_trailing_profit": False, "trail_activation_r": 3.0, "trail_distance_r": 1.0, "trail_apply_to": "BOTH", "trail_intrabar_mode": "PESSIMISTIC",
    "enable_partial_take_profit": False, "tp1_r": 3.0, "tp1_close_pct": 50.0, "tp2_r": 12.0, "tp2_close_pct": 50.0, "stop_loss_r": 10.0, "after_tp1_stop_mode": "KEEP_ORIGINAL_SL", "after_tp1_stop_offset_r": 0.0, "tp2_exit_mode": "FIXED_TP2",
    "enable_both_open_timeout": False, "max_both_open_minutes": 480, "enable_trade_telemetry": True, "save_full_telemetry_csv": True, "save_trade_journey_summary": True, "save_trade_journey_charts": True, "telemetry_interval_minutes": 15, "enable_indicator_lifecycle_analysis": True, "lifecycle_phases": 4, "lifecycle_early_checkpoints": [15, 30, 60], "lifecycle_minimum_bucket_sample": 20, "create_lifecycle_charts": True, "lifecycle_flat_pattern_threshold_pct": 5.0, "both_open_timeout_unit": "Hours", "enable_be_after_opposite_sl": False, "be_mode": "ENTRY_PRICE", "be_offset_r": 0.0, "be_same_candle_policy": "NEXT_CANDLE",
}


def default_gui_config() -> dict[str, Any]:
    """Return a fresh copy of the GUI defaults."""
    return DEFAULT_GUI_CONFIG.copy()


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
    errors: list[str] = []
    if require_paths:
        strategy_path = values.get("strategy_csv") if values.get("strategy_csv") != DEFAULT_GUI_CONFIG.get("strategy_csv") else values.get("input_csv")
        if not Path(strategy_path or "").is_file():
            errors.append("15-Minute Strategy CSV must exist.")
        if values.get("use_intrabar_data") and values.get("intrabar_csv") and values.get("intrabar_csv") != DEFAULT_GUI_CONFIG.get("intrabar_csv") and not Path(values.get("intrabar_csv")).is_file():
            errors.append("1-Minute Intrabar CSV must exist when enabled.")
        out = Path(values.get("output_dir", ""))
        if not str(out):
            errors.append("Output folder is required.")
    checks = [
        ("sl_mult", 0, "SL multiple must be > 0."), ("tp_mult", 0, "TP multiple must be > 0."),
        ("initial_equity", 0, "Starting equity must be > 0."), ("risk_per_leg", 0, "Risk per leg must be > 0."),
        ("atr_multiplier", 0, "ATR multiplier must be > 0."), ("strategy_timeframe_minutes", 0, "Strategy timeframe must be > 0."), ("intrabar_timeframe_minutes", 0, "Intrabar timeframe must be > 0."), ("percent_r", 0, "Percentage R must be > 0."),
        ("fixed_r", 0, "Fixed R must be > 0."), ("tp1_r", 0, "TP1_R must be greater than zero."), ("tp2_r", 0, "TP2_R must be greater than zero."), ("stop_loss_r", 0, "STOP_LOSS_R must be greater than zero."), ("tp1_close_pct", 0, "TP1_CLOSE_PCT must be greater than zero."), ("tp2_close_pct", 0, "TP2_CLOSE_PCT must be greater than zero."), ("trail_activation_r", 0, "Trailing Activation (R) must be > 0."), ("trail_distance_r", 0, "Trailing Distance (R) must be > 0."),
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
    if values.get("entry_timing_mode") not in [e.value for e in EntryTimingMode]: errors.append("Invalid entry timing mode.")
    if values.get("random_entry_start_mode") not in [e.value for e in RandomEntryStartMode]: errors.append("Invalid Random Entry Start Mode.")
    try:
        if not 0 < float(values.get("random_entry_probability")) <= 1: errors.append("Entry Probability must be greater than 0 and less than or equal to 1.")
    except (TypeError, ValueError): errors.append("Entry Probability must be greater than 0 and less than or equal to 1.")
    try: int(values.get("random_seed"))
    except (TypeError, ValueError): errors.append("Random Seed must be an integer.")
    for key, label in (("max_random_wait_candles","Maximum Random Wait Candles"),("random_seed_count","Random Seed Count")):
        try:
            if int(values.get(key)) < (1 if key == "random_seed_count" else 0): errors.append(f"{label} is invalid.")
        except (TypeError, ValueError): errors.append(f"{label} is invalid.")
    if values.get("tie_policy") not in [TiePolicy.PESSIMISTIC.value, TiePolicy.OPTIMISTIC.value]: errors.append("Invalid tie policy.")
    if values.get("risk_mode") not in [e.value for e in RiskMode]: errors.append("Invalid risk mode.")
    if values.get("trade_direction") not in [e.value for e in TradeDirectionMode]: errors.append("Invalid trade direction mode.")
    if values.get("trail_apply_to") not in [e.value for e in TrailApplyTo]: errors.append("Apply Trailing To must be BOTH, LONG_ONLY, or SHORT_ONLY.")
    if values.get("trail_intrabar_mode") not in [e.value for e in TrailIntrabarMode]: errors.append("Intrabar Trailing Mode must be PESSIMISTIC or OPTIMISTIC.")
    if values.get("daily_entry_missed_policy") not in [e.value for e in DailyEntryMissedPolicy]: errors.append("Invalid daily entry missed policy.")
    try:
        hh, mm = [int(part) for part in str(values.get("daily_entry_time", "00:00")).split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
        if (hh * 60 + mm) % int(values.get("strategy_timeframe_minutes", 15)) != 0: errors.append("Daily entry time must align to the strategy timeframe.")
    except (TypeError, ValueError): errors.append("Daily entry time must be HH:MM.")
    if int(values.get("intrabar_timeframe_minutes", 1)) >= int(values.get("strategy_timeframe_minutes", 15)): errors.append("Intrabar timeframe must be less than strategy timeframe.")
    if int(values.get("telemetry_interval_minutes", 15)) % int(values.get("strategy_timeframe_minutes", 15)) != 0: errors.append("Telemetry interval must be a multiple of the strategy timeframe.")
    if values.get("enable_trade_telemetry") and (int(values.get("strategy_timeframe_minutes", 15)) != 15 or int(values.get("telemetry_interval_minutes", 15)) != 15): errors.append("Only 15-minute telemetry is currently supported with a 15-minute strategy timeframe.")
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
    if values.get("enable_both_open_timeout"):
        try:
            if int(values.get("max_both_open_minutes", 0)) <= 0: errors.append("Maximum Both-Open Time must be > 0 when enabled.")
        except (TypeError, ValueError): errors.append("Maximum Both-Open Time must be > 0 when enabled.")
    return errors


def build_backtest_config(values: dict[str, Any], require_paths: bool = True) -> BacktestConfig:
    merged = {**default_gui_config(), **values}
    errors = validate_config_values(merged, require_paths=require_paths)
    if errors:
        raise ValueError("\n".join(errors))
    return BacktestConfig(
        input_csv=Path(merged["input_csv"]), strategy_csv=Path(merged["input_csv"] if merged.get("strategy_csv") == DEFAULT_GUI_CONFIG.get("strategy_csv") else (merged.get("strategy_csv") or merged["input_csv"])), intrabar_csv=Path(merged["intrabar_csv"]) if merged.get("intrabar_csv") else None, output_dir=Path(merged["output_dir"]),
        sl_mult=float(merged["sl_mult"]), tp_mult=float(merged["tp_mult"]),
        entry_mode=EntryMode(merged["entry_mode"]), entry_interval=int(merged["entry_interval"]), enable_random_entry=bool(merged["enable_random_entry"]), entry_timing_mode=EntryTimingMode(merged["entry_timing_mode"]), random_entry_probability=float(merged["random_entry_probability"]), random_seed=int(merged["random_seed"]), random_entry_start_mode=RandomEntryStartMode(merged["random_entry_start_mode"]), randomize_first_entry=bool(merged["randomize_first_entry"]), max_random_wait_candles=int(merged["max_random_wait_candles"]), enable_random_entry_batch=bool(merged["enable_random_entry_batch"]), random_seed_start=int(merged["random_seed_start"]), random_seed_count=int(merged["random_seed_count"]), enable_daily_entry_schedule=bool(merged["enable_daily_entry_schedule"]), daily_entry_time=str(merged["daily_entry_time"]), daily_entry_timezone=str(merged["daily_entry_timezone"]), daily_entry_missed_policy=DailyEntryMissedPolicy(merged["daily_entry_missed_policy"]),
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
        intrabar_missing_policy=IntrabarMissingPolicy(merged["intrabar_missing_policy"]), zero_cost_comparison=bool(merged["zero_cost_comparison"]), trade_direction=TradeDirectionMode(merged["trade_direction"]), enable_partial_take_profit=bool(merged["enable_partial_take_profit"]), tp1_r=float(merged["tp1_r"]), tp1_close_pct=float(merged["tp1_close_pct"]), tp2_r=float(merged["tp2_r"]), tp2_close_pct=float(merged["tp2_close_pct"]), stop_loss_r=float(merged["stop_loss_r"]), after_tp1_stop_mode=AfterTP1StopMode(merged["after_tp1_stop_mode"]), after_tp1_stop_offset_r=float(merged["after_tp1_stop_offset_r"]), tp2_exit_mode=TP2ExitMode(merged["tp2_exit_mode"]), enable_trailing_profit=bool(merged["enable_trailing_profit"]), trail_activation_r=float(merged["trail_activation_r"]), trail_distance_r=float(merged["trail_distance_r"]), trail_apply_to=TrailApplyTo(merged["trail_apply_to"]), trail_intrabar_mode=TrailIntrabarMode(merged["trail_intrabar_mode"]),
        enable_both_open_timeout=bool(merged["enable_both_open_timeout"]), max_both_open_minutes=int(merged["max_both_open_minutes"]),
        enable_be_after_opposite_sl=bool(merged["enable_be_after_opposite_sl"]), be_mode=BreakEvenMode(merged["be_mode"]), be_offset_r=float(merged["be_offset_r"]), be_same_candle_policy=BreakEvenSameCandlePolicy(merged["be_same_candle_policy"]),
        run_name=str(merged.get("run_name", "")), enable_trade_telemetry=bool(merged["enable_trade_telemetry"]), save_full_telemetry_csv=bool(merged["save_full_telemetry_csv"]), save_trade_journey_summary=bool(merged["save_trade_journey_summary"]), save_trade_journey_charts=bool(merged["save_trade_journey_charts"]), telemetry_interval_minutes=int(merged["telemetry_interval_minutes"]), enable_indicator_lifecycle_analysis=bool(merged["enable_indicator_lifecycle_analysis"]), lifecycle_phases=int(merged["lifecycle_phases"]), lifecycle_early_checkpoints=tuple(int(v) for v in merged["lifecycle_early_checkpoints"]), lifecycle_minimum_bucket_sample=int(merged["lifecycle_minimum_bucket_sample"]), create_lifecycle_charts=bool(merged["create_lifecycle_charts"]), lifecycle_flat_pattern_threshold_pct=float(merged["lifecycle_flat_pattern_threshold_pct"]),
    )


def save_config_json(path: str | Path, values: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps({**default_gui_config(), **values}, indent=2, default=str))


def load_config_json(path: str | Path) -> dict[str, Any]:
    return {**default_gui_config(), **json.loads(Path(path).read_text())}
