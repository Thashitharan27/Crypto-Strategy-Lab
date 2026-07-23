"""Pure helpers for GUI configuration conversion and validation."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode, TiePolicy

DEFAULT_GUI_CONFIG: dict[str, Any] = {
    "input_csv": "data/binance_ohlcv.csv", "strategy_csv": "data/BTCUSDT_15m.csv", "intrabar_csv": "data/BTCUSDT_1m.csv", "output_dir": "output", "run_name": "",
    "sl_mult": 2.0, "tp_mult": 3.0, "entry_mode": "WAIT_UNTIL_CLOSED",
    "entry_interval": 1, "max_active_pairs": 1, "tie_policy": "PESSIMISTIC",
    "risk_mode": "ATR", "atr_period": 14, "atr_multiplier": 1.0,
    "percent_r": 0.002, "fixed_r": 100.0, "initial_equity": 1000.0,
    "risk_per_leg": 0.005, "maker_fee": 0.0002, "taker_fee": 0.0005,
    "use_maker_entry": False, "use_maker_exit": False, "slippage": 0.0001,
    "strategy_timeframe_minutes": 15, "intrabar_timeframe_minutes": 1, "use_intrabar_data": True,
    "trading_start_date": None, "trading_end_date": None, "max_effective_leverage_per_leg": None,
    "max_combined_effective_leverage": None, "intrabar_missing_policy": "WARN_AND_USE_15M", "zero_cost_comparison": False,
    "enable_both_open_timeout": False, "max_both_open_minutes": 480, "both_open_timeout_unit": "Hours",
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
        ("fixed_r", 0, "Fixed R must be > 0."),
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
    if values.get("entry_mode") not in [e.value for e in EntryMode]: errors.append("Invalid entry mode.")
    if values.get("tie_policy") not in [TiePolicy.PESSIMISTIC.value, TiePolicy.OPTIMISTIC.value]: errors.append("Invalid tie policy.")
    if values.get("risk_mode") not in [e.value for e in RiskMode]: errors.append("Invalid risk mode.")
    if int(values.get("intrabar_timeframe_minutes", 1)) >= int(values.get("strategy_timeframe_minutes", 15)): errors.append("Intrabar timeframe must be less than strategy timeframe.")
    if values.get("intrabar_missing_policy") not in [e.value for e in IntrabarMissingPolicy]: errors.append("Invalid missing intrabar policy.")
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
        entry_mode=EntryMode(merged["entry_mode"]), entry_interval=int(merged["entry_interval"]),
        max_active_pairs=int(merged["max_active_pairs"]), tie_policy=TiePolicy(merged["tie_policy"]),
        risk_mode=RiskMode(merged["risk_mode"]), atr_period=int(merged["atr_period"]),
        atr_multiplier=float(merged["atr_multiplier"]), percent_r=float(merged["percent_r"]),
        fixed_r=float(merged["fixed_r"]), initial_equity=float(merged["initial_equity"]),
        risk_per_leg=float(merged["risk_per_leg"]), maker_fee=float(merged["maker_fee"]),
        taker_fee=float(merged["taker_fee"]), use_maker_entry=bool(merged["use_maker_entry"]),
        use_maker_exit=bool(merged["use_maker_exit"]), slippage=float(merged["slippage"]),
        strategy_timeframe_minutes=int(merged["strategy_timeframe_minutes"]), intrabar_timeframe_minutes=int(merged["intrabar_timeframe_minutes"]),
        use_intrabar_data=bool(merged["use_intrabar_data"]), trading_start_date=merged.get("trading_start_date"), trading_end_date=merged.get("trading_end_date"),
        max_effective_leverage_per_leg=float(merged["max_effective_leverage_per_leg"]) if merged.get("max_effective_leverage_per_leg") not in (None, "") else None,
        max_combined_effective_leverage=float(merged["max_combined_effective_leverage"]) if merged.get("max_combined_effective_leverage") not in (None, "") else None,
        intrabar_missing_policy=IntrabarMissingPolicy(merged["intrabar_missing_policy"]), zero_cost_comparison=bool(merged["zero_cost_comparison"]),
        enable_both_open_timeout=bool(merged["enable_both_open_timeout"]), max_both_open_minutes=int(merged["max_both_open_minutes"]),
        run_name=str(merged.get("run_name", "")),
    )


def save_config_json(path: str | Path, values: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps({**default_gui_config(), **values}, indent=2, default=str))


def load_config_json(path: str | Path) -> dict[str, Any]:
    return {**default_gui_config(), **json.loads(Path(path).read_text())}
