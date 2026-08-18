"""Output directory management for backtest runs."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_strategy_lab.config import BacktestConfig


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._-")


def _format_number(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def _risk_label(config: BacktestConfig) -> str:
    mode = getattr(config.risk_mode, "value", config.risk_mode)
    if mode == "ATR":
        return f"ATR{config.atr_period}x{_format_number(config.atr_multiplier)}"
    if mode == "PERCENT":
        return f"PCT{_format_number(config.percent_r * 100)}"
    return f"FIXED{_format_number(config.fixed_r)}"


def _profile_exit_labels(config: BacktestConfig) -> tuple[str, str]:
    profiles = [profile for profile in config.strategy_profiles.values() if profile.enabled]
    signatures = {
        (
            profile.partial_stop_enabled,
            profile.sl1_r,
            profile.sl1_close_pct,
            profile.sl2_r,
            profile.stop_loss_multiple,
            profile.partial_profit_enabled,
            profile.tp1_r,
            profile.tp1_close_pct,
            profile.tp2_r,
            profile.reward_risk_ratio,
        )
        for profile in profiles
    }
    if not profiles or len(signatures) != 1:
        return "MIXED", "EXITS"

    profile = profiles[0]
    if profile.partial_stop_enabled:
        stop = (
            f"PSL{_format_number(profile.sl1_r)}x{_format_number(profile.sl1_close_pct)}"
            f"-SL{_format_number(profile.sl2_r)}"
        )
    else:
        stop = f"SL{_format_number(profile.stop_loss_multiple)}"
    if profile.partial_profit_enabled:
        target = (
            f"PTP{_format_number(profile.tp1_r)}x{_format_number(profile.tp1_close_pct)}"
            f"-TP{_format_number(profile.tp2_r)}"
        )
    else:
        target = f"TP{_format_number(profile.stop_loss_multiple * profile.reward_risk_ratio)}"
    return stop, target


def _profile_mode_label(config: BacktestConfig) -> str | None:
    if not config.enable_strategy_profiles:
        return None
    labels = {
        "ISOLATED_PROFILES": "PROFILES-ISOLATED",
        "COMBINED_SHARED_CAPITAL": "PROFILES-COMBINED",
        "BOTH": "PROFILES-BOTH",
    }
    return labels.get(config.strategy_profile_run_mode, f"PROFILES-{_safe_part(config.strategy_profile_run_mode)}")


def _stop_label(config: BacktestConfig) -> str:
    if config.enable_partial_stop_loss:
        closed = _format_number(config.sl1_close_pct)
        return (
            f"PSL{_format_number(config.sl1_r)}x{closed}"
            f"-SL{_format_number(config.sl2_r)}"
        )
    if config.enable_partial_take_profit:
        return f"SL{_format_number(config.stop_loss_r)}"
    return f"SL{_format_number(config.sl_mult)}"


def _target_label(config: BacktestConfig) -> str:
    if config.enable_partial_take_profit:
        closed = _format_number(config.tp1_close_pct)
        return (
            f"PTP{_format_number(config.tp1_r)}x{closed}"
            f"-TP{_format_number(config.tp2_r)}"
        )
    if config.enable_di_direction_sizing and config.enable_di_regime_reward_risk:
        return "RRREGIME"
    if config.enable_di_direction_sizing:
        long_target = config.sl_mult * config.di_long_reward_risk_ratio
        short_target = config.sl_mult * config.di_short_reward_risk_ratio
        if long_target != short_target:
            return f"LTP{_format_number(long_target)}-STP{_format_number(short_target)}"
        target_multiple = long_target
    else:
        target_multiple = config.tp_mult
    return f"TP{_format_number(target_multiple)}"


def infer_symbol(config: BacktestConfig) -> str:
    stem = Path(config.input_csv).stem.upper()
    match = re.match(r"([A-Z]+?)(?:USDT|USD|BTC|ETH)?(?:_|-|$)", stem)
    return match.group(1) if match else "BACKTEST"


def run_folder_name(config: BacktestConfig, timestamp: datetime | None = None) -> str:
    stamp = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    stop, target = (
        _profile_exit_labels(config)
        if config.enable_strategy_profiles
        else (_stop_label(config), _target_label(config))
    )
    parts = [
        infer_symbol(config),
        f"{config.strategy_timeframe_minutes}m",
        _risk_label(config),
    ]
    profile_mode = _profile_mode_label(config)
    if profile_mode:
        parts.append(profile_mode)
    parts.extend([
        stop,
        target,
        stamp,
    ])
    base = "_".join(parts)
    run_name = _safe_part(config.run_name or "")
    return f"{run_name}_{base}" if run_name else base


def planned_run_dir(config: BacktestConfig) -> Path:
    if config.output_run_dir is not None:
        return Path(config.output_run_dir)
    return Path(config.output_dir) / run_folder_name(config)


def create_run_dir(config: BacktestConfig) -> Path:
    path = planned_run_dir(config)
    counter = 1
    while path.exists():
        path = path.with_name(f"{path.name}_{counter}")
        counter += 1
    path.mkdir(parents=True, exist_ok=False)
    (path / "charts").mkdir(exist_ok=True)
    return path


def config_to_dict(config: BacktestConfig) -> dict[str, Any]:
    raw = asdict(config) if is_dataclass(config) else {f.name: getattr(config, f.name) for f in fields(BacktestConfig)}
    return {key: _jsonable(value) for key, value in raw.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def write_config(config: BacktestConfig, run_dir: Path) -> None:
    (run_dir / "config.json").write_text(json.dumps(config_to_dict(config), indent=2, default=str))


def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:
    if config.enable_partial_stop_loss:
        stop_description = (
            f"Partial stop: {config.sl1_close_pct}% at {config.sl1_r}R; "
            f"remainder at {config.sl2_r}R (Core SL ignored)"
        )
    elif config.enable_partial_take_profit:
        stop_description = f"Partial TP stop: {config.stop_loss_r}R (Core SL ignored)"
    else:
        stop_description = f"Stop loss multiple: {config.sl_mult}R"

    if config.enable_strategy_profiles:
        enabled_profiles = [key for key, profile in config.strategy_profiles.items() if profile.enabled]
        target_description = (
            "Strategy Profiles: " + (", ".join(enabled_profiles) if enabled_profiles else "none enabled")
            + f"; run mode {config.strategy_profile_run_mode}"
        )
    elif config.enable_partial_take_profit:
        target_description = (
            f"Partial take profit: {config.tp1_close_pct}% at {config.tp1_r}R; "
            f"remainder at {config.tp2_r}R (Core TP ignored)"
        )
    else:
        target_description = f"Take profit multiple: {config.tp_mult}R"

    lines = [
        "Backtest Run Information",
        "========================",
        f"Output folder: {run_dir.resolve()}",
        f"Run name: {config.run_name or '(none)'}",
        f"Strategy CSV: {config.input_csv}",
        f"Intrabar CSV: {config.intrabar_csv if config.use_intrabar_data else '(disabled)'}",
        f"Symbol: {infer_symbol(config)}",
        f"Strategy timeframe: {config.strategy_timeframe_minutes}m",
        f"Risk mode: {config.risk_mode.value}",
        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",
        stop_description,
        target_description,
        (
            f"Trailing stop: enabled; trigger {config.trail_activation_trigger.value}; "
            f"activation {config.trail_activation_r}R; distance {config.trail_distance_r}R; "
            f"apply to {config.trail_apply_to.value}; fixed final targets remain active"
            if config.enable_trailing_profit
            else "Trailing stop: disabled"
        ),
        f"Partial intrabar ordering: {'STOP_FIRST' if config.tie_policy.value == 'PESSIMISTIC' else 'TP1_THEN_TP2_THEN_STOP'}",
        f"Initial equity: {config.initial_equity}",
        f"Total pairs: {summary.get('total_pairs')}",
        f"Ending equity: {summary.get('ending_equity')}",
        f"Total return %: {summary.get('total_return_percentage')}",
    ]
    (run_dir / "run_info.txt").write_text("\n".join(lines) + "\n")


def compatible_resample_freq(freq: str) -> str:
    """Map legacy pandas aliases to modern aliases by default."""
    return {"M": "ME", "Y": "YE"}.get(freq, freq)


def periodic_results(trades: pd.DataFrame, freq: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["period", "pair_count", "net_pnl", "net_r"])
    exits = pd.to_datetime(trades.get("exit_time", pd.Series(pd.NaT, index=trades.index)), errors="coerce", utc=True)
    side_exit_columns = [column for column in ("long_exit_time", "short_exit_time") if column in trades]
    if side_exit_columns and exits.isna().any():
        side_exits = pd.concat(
            [pd.to_datetime(trades[column], errors="coerce", utc=True) for column in side_exit_columns],
            axis=1,
        ).max(axis=1)
        exits = exits.fillna(side_exits)
    if exits.isna().all():
        raise ValueError("Periodic results require at least one valid trade exit timestamp.")
    # Keep this narrow. Copying the full telemetry-rich trade frame also deep
    # copies its large attrs (notably skipped_signals) in recent pandas.
    frame = pd.DataFrame({"exit_time": exits, "pair_net_pnl": trades["pair_net_pnl"], "pair_net_r": trades["pair_net_r"]}).set_index("exit_time")
    frame = frame.loc[frame.index.notna()]
    candidates = [compatible_resample_freq(freq)]
    fallback = {"ME": "M", "YE": "Y", "M": "ME", "Y": "YE"}.get(candidates[0])
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            periodic = frame.resample(candidate).agg(pair_count=("pair_net_pnl", "size"), net_pnl=("pair_net_pnl", "sum"), net_r=("pair_net_r", "sum"))
            periodic = periodic.reset_index()
            return periodic.rename(columns={periodic.columns[0]: "period"})
        except ValueError as exc:
            last_error = exc
    raise last_error if last_error is not None else ValueError(f"Unsupported resample frequency: {freq}")


def update_latest(output_root: Path, run_dir: Path) -> None:
    latest = output_root / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        else:
            shutil.rmtree(latest)
    try:
        latest.symlink_to(run_dir.resolve(), target_is_directory=True)
    except OSError:
        shutil.copytree(run_dir, latest)

TRADE_R_COLUMN_METADATA = {
    "r_distance": "Price-distance R selected by the configured risk mode before SL/TP multiples.",
    "configured_price_risk_percentage": "Configured account-equity percentage used as the price-risk budget per leg before fees and slippage.",
    "estimated_all_in_stop_risk_percentage": "Estimated per-leg account-equity loss at stop after entry fee, stop-exit fee, and configured slippage.",
    "*_price_r": "Realized price movement divided by r_distance; excludes quantity, fees, and account equity.",
    "*_gross_r": "Gross cash PnL divided by that leg's planned risk_amount.",
    "*_net_r": "Net cash PnL after fees divided by that leg's planned risk_amount.",
    "*_account_r": "Alias for leg net_r retained for backward-compatible account-risk reporting.",
    "pair_price_r": "Sum of long_price_r and short_price_r; a price-distance measure, not cash risk.",
    "pair_gross_account_r": "Pair gross cash PnL divided by combined planned risk_amount for both legs.",
    "pair_fee_account_r": "Pair fees divided by combined planned risk_amount for both legs.",
    "pair_net_account_r": "Pair net cash PnL divided by combined planned risk_amount for both legs.",
    "pair_gross_r": "Pair gross cash PnL divided by the pair's combined planned risk_amount.",
    "pair_fee_r": "Pair fees divided by the pair's combined planned risk_amount.",
    "pair_net_r": "Pair net cash PnL divided by the pair's combined planned risk_amount; valid for equal and asymmetric leg sizing.",
    "pair_leg_gross_r_sum": "Legacy diagnostic: sum of each leg's independently normalized gross_r.",
    "pair_leg_net_r_sum": "Legacy diagnostic: sum of each leg's independently normalized net_r.",
    "adx": "Wilder ADX value from the 15-minute strategy candle evaluated before pair entry.",
    "plus_di": "Wilder +DI value from the 15-minute strategy candle evaluated before pair entry.",
    "minus_di": "Wilder -DI value from the 15-minute strategy candle evaluated before pair entry.",
    "market_structure_direction": "Confirmed swing-high/swing-low direction at entry: LONG, SHORT, or ABSTAIN.",
    "market_structure_reason": "Specific confirmed-structure classification or abstention reason.",
    "market_structure_pivot_span": "Candles required on each side to confirm a swing pivot; currently two.",
    "market_structure_minimum_displacement_atr": "Smaller directional change across the latest two swing highs/lows, normalized by entry ATR; telemetry only.",
    "market_structure_maximum_displacement_atr": "Larger directional change across the latest two swing highs/lows, normalized by entry ATR; telemetry only.",
    "market_structure_breakout_distance_atr": "Directional close distance beyond the prior swing boundary in ATR units; negative means no close breakout.",
    "market_structure_breakout_confirmed_by_close": "Whether the entry candle closed beyond the prior directional swing boundary.",
    "directional_di": "DI supporting the selected trade direction at signal time.",
    "opposing_di": "DI opposing the selected trade direction at signal time.",
    "directional_di_change": "Directional DI change over the configured analysis lookback.",
    "opposing_di_change": "Opposing DI change over the configured analysis lookback.",
    "di_spread_change": "Absolute DI spread change over the configured analysis lookback.",
    "di_pressure_state": "Analysis-only EXPANDING, CONTRACTING, MIXED, or UNKNOWN classification.",
    "di_pressure_lookback": "Number of past strategy candles used for DI pressure telemetry.",
    "di_spread": "Absolute difference between +DI and -DI on the 15-minute strategy candle.",
    "di_ratio": "max(+DI, -DI) divided by min(+DI, -DI), with division by zero protected as NaN.",
    "di_spread_entry_5bar_change": "DI spread change at entry versus five strategy candles ago.",
    "bb_middle": "Bollinger Bands middle SMA on the 15-minute strategy candle.",
    "bb_upper": "Bollinger Bands upper band on the 15-minute strategy candle.",
    "bb_lower": "Bollinger Bands lower band on the 15-minute strategy candle.",
    "bb_width": "Raw Bollinger Band Width: (upper - lower) / middle.",
    "bb_width_pct": "Bollinger Band Width expressed as a percentage.",
    "bb_width_entry_5bar_change": "Raw BB width change at entry versus five strategy candles ago.",
    "bb_width_entry_5bar_change_pct": "BB width percentage change at entry versus five strategy candles ago.",
    "indicator_warmup_complete": "True when ADX and BB width were both available at entry; false rows include indicator_warmup_note explaining incomplete warm-up.",
    "adx_available_at_entry": "True when ADX had enough warm-up history to be available at entry.",
    "bb_width_available_at_entry": "True when Bollinger Band width had enough warm-up history to be available at entry.",
    "indicator_warmup_note": "Explains whether missing entry indicators are due to incomplete indicator warm-up.",
    "adx_filter_passed": "Whether the ADX entry filter allowed this traded signal.",
    "adx_filter_reason": "Human-readable ADX filter decision for this signal.",
    "both_open_timeout_enabled": "Whether the optional rule to close pairs that keep both legs open beyond the configured duration was enabled for this run.",
    "max_both_open_minutes": "Configured maximum elapsed minutes from pair entry while both long and short remain open.",
    "both_open_timeout_triggered": "True when both legs of this pair were closed by the both-open timeout rule.",
    "timeout_exit_time": "Timestamp used for the both-open timeout exit, when applicable.",
    "remaining_leg_timeout_after_first_sl_enabled": "Whether the optional remaining-leg timeout after the first normal SL was enabled for this pair.",
    "remaining_leg_timeout_after_first_sl_minutes": "Configured remaining-leg waiting period in minutes.",
    "remaining_leg_timeout_after_first_sl_started": "True only when one leg exited for the normal SL reason while its opposite leg remained open.",
    "first_sl_side": "LONG or SHORT side whose normal SL started the remaining-leg timer.",
    "first_sl_time": "Exact timestamp of the first normal SL that started the timer.",
    "remaining_leg_timeout_deadline": "First normal SL timestamp plus the configured timeout minutes.",
    "remaining_leg_timeout_triggered": "True when the opposite leg was still open and was market-closed at the deadline's first available execution candle.",
    "remaining_leg_timeout_exit_time": "Timestamp of the intrabar or fallback strategy candle used for a triggered remaining-leg timeout.",
    "remaining_leg_timeout_exit_side": "Side closed by the remaining-leg timeout.",
    "remaining_leg_timeout_profit_extension_enabled": "Whether a remaining leg at or above the configured unrealized-profit R threshold receives another full timeout interval.",
    "remaining_leg_timeout_profit_threshold_r": "Minimum unrealized price R required at a timeout checkpoint to keep the remaining leg open.",
    "remaining_leg_timeout_checkpoint_count": "Number of timeout checkpoints evaluated for the remaining leg.",
    "remaining_leg_timeout_extension_count": "Number of checkpoints that qualified for another full timeout interval.",
    "remaining_leg_timeout_last_checkpoint_time": "Timestamp of the most recent remaining-leg timeout checkpoint.",
    "remaining_leg_timeout_last_checkpoint_profit_r": "Remaining leg unrealized price R at its most recent timeout checkpoint.",
    "checkpoint_reentry_gate_started": "True when a checkpoint timeout started a virtual TP/SL gate that blocks replacement entries.",
    "checkpoint_reentry_gate_side": "Side of the virtually monitored leg.",
    "checkpoint_reentry_gate_tp": "TP boundary monitored after the checkpoint close.",
    "checkpoint_reentry_gate_sl": "Active SL boundary monitored after the checkpoint close.",
    "checkpoint_reentry_gate_start_time": "Checkpoint close time when virtual monitoring began.",
    "checkpoint_reentry_gate_release_time": "Candle time when TP or SL released the entry gate.",
    "checkpoint_reentry_gate_release_reason": "TP, SL, or TP_AND_SL boundary that released the gate.",
    "remaining_leg_checkpoint_score_extension_enabled": "Whether the configurable checkpoint condition score controls timeout extensions.",
    "checkpoint_score_last_atr_pct": "ATR as a percentage of checkpoint price using the last completed strategy candle.",
    "checkpoint_score_last_directional_di": "Direction-adjusted DI at the checkpoint: +DI-minus--DI for long, reversed for short.",
    "checkpoint_score_last_bb_width_pct": "Bollinger Band width percentage at the checkpoint.",
    "checkpoint_score_last_pass_count": "Number of enabled checkpoint conditions that passed at the most recent checkpoint.",
    "checkpoint_score_last_condition_count": "Number of checkpoint score conditions enabled.",
    "checkpoint_score_last_passed": "Whether the most recent checkpoint score reached the required condition count.",
    "first_sl_survivor_partial_taken": "Whether part of the surviving leg was realized when the opposite leg hit its first normal SL.",
    "first_sl_survivor_partial_side": "Side of the surviving leg that was partially closed.",
    "first_sl_survivor_partial_time": "Execution time of the first-SL survivor partial close.",
    "first_sl_survivor_partial_pct": "Configured percentage of the survivor closed at the first SL.",
    "first_sl_survivor_partial_exit_price": "Executed partial-close price after normal directional slippage.",
    "first_sl_survivor_partial_net_pnl": "Net realized PnL from the first-SL partial close after its exit fee.",
    "checkpoint_zero_score_streak": "Current consecutive zero-score checkpoint count.",
    "checkpoint_zero_score_max_streak": "Largest consecutive zero-score count reached by the pair.",
    "checkpoint_zero_score_last_time": "Most recent zero-score checkpoint time.",
    "checkpoint_zero_score_confirmed_close": "Whether the remaining leg closed after reaching the configured zero-score confirmation count.",
    "*_original_sl": "The leg stop loss at entry before any break-even replacement.",
    "*_current_sl": "The final active stop loss after any break-even replacement.",
    "*_be_*": "Break-even-after-opposite-SL audit fields. COST_ADJUSTED estimates a zero-net exit using entry fee, estimated exit fee, and configured slippage; final realized net PnL may differ slightly because exit fee depends on actual exit notional.",
    "pair_be_triggered": "True when one leg hit SL and the opposite leg stop was moved by the break-even rule.",
    "intrabar_partial_tp_ordering": "PESSIMISTIC uses STOP_FIRST; OPTIMISTIC uses TP1_THEN_TP2_THEN_STOP. Each leg is resolved independently.",
    "*_remaining_quantity": "Quantity still protected by reduce-only-equivalent exit logic after partial fills.",
    "*_tp1_* / *_tp2_* / *_stop_*": "Independent partial-fill quantities, times, prices, gross PnL, fees, and net PnL; unused fills are null.",
    "*_sr_context": "Pipe-separated entry-time S/R event labels for the leg (NEAR_SUPPORT, NEAR_RESISTANCE, SUPPORT_BOUNCE, RESISTANCE_REJECTION, RESISTANCE_BREAKOUT, SUPPORT_BREAKDOWN, or NO_NEARBY_SR); derived from the stored entry-time S/R snapshot only, never recalculated after entry.",
    "*_sr_support_bounce": "True when support was tested and held at entry time (SUPPORT_BOUNCE label present).",
    "*_sr_resistance_rejection": "True when resistance was tested and held at entry time (RESISTANCE_REJECTION label present).",
    "*_sr_resistance_breakout": "True when resistance structure was already broken at entry time (RESISTANCE_BREAKOUT label present).",
    "*_sr_support_breakdown": "True when support structure was already broken at entry time (SUPPORT_BREAKDOWN label present).",
    "*_sr_support_zone_low / *_sr_support_zone_high": "Bottom/top price bounds of the nearest confirmed support zone at entry time.",
    "*_sr_resistance_zone_low / *_sr_resistance_zone_high": "Bottom/top price bounds of the nearest confirmed resistance zone at entry time.",
    "*_sr_level_price": "Nearest S/R level price relevant to the leg's direction (support for LONG, resistance for SHORT).",
    "*_sr_zone_low / *_sr_zone_high": "Zone bounds of *_sr_level_price: support zone for LONG legs, resistance zone for SHORT legs.",
}


def write_trade_column_metadata(run_dir: Path) -> None:
    """Write tooltip-style definitions for R and risk percentage columns in trade_list.csv."""
    (run_dir / "trade_list_column_metadata.json").write_text(json.dumps(TRADE_R_COLUMN_METADATA, indent=2))
