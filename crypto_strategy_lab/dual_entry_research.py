"""Research-only simultaneous LONG + SHORT simulator.

This module is deliberately isolated from normal position management.  It takes
entry opportunities already accepted by the standard engine, opens a synthetic
LONG and SHORT at the same observation time, and measures whether each leg hits
its configured TP or SL first.  No normal trade selection, sizing, equity, or
execution state is changed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_PENDING: dict[int, tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}


def _utc(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _di_bucket(value: float) -> str:
    if not np.isfinite(value):
        return "UNKNOWN"
    for low in range(0, 30, 5):
        if low <= value < low + 5:
            return f"{low}-{low + 5}"
    return "30+"


def _first_exit(side: str, entry: float, unit: float, tp_r: float, sl_r: float,
                frame: pd.DataFrame, tie_policy: str) -> dict[str, Any]:
    sign = 1.0 if side == "LONG" else -1.0
    tp = entry + sign * tp_r * unit
    sl = entry - sign * sl_r * unit
    pessimistic = str(tie_policy).upper().endswith("PESSIMISTIC")

    for bar_number, row in enumerate(frame.itertuples(index=False), 1):
        high = float(row.high)
        low = float(row.low)
        tp_hit = high >= tp if side == "LONG" else low <= tp
        sl_hit = low <= sl if side == "LONG" else high >= sl
        if not tp_hit and not sl_hit:
            continue
        if tp_hit and sl_hit:
            reason = "SL" if pessimistic else "TP"
            ambiguous = True
        else:
            reason = "TP" if tp_hit else "SL"
            ambiguous = False
        price = tp if reason == "TP" else sl
        return {
            "reason": reason,
            "price": price,
            "time": _utc(row.timestamp),
            "bars": bar_number,
            "ambiguous": ambiguous,
            "tp_price": tp,
            "sl_price": sl,
        }

    return {
        "reason": "UNRESOLVED",
        "price": np.nan,
        "time": pd.NaT,
        "bars": np.nan,
        "ambiguous": False,
        "tp_price": tp,
        "sl_price": sl,
    }


def _leg_r(reason: str, tp_r: float, sl_r: float) -> float:
    if reason == "TP":
        return float(tp_r)
    if reason == "SL":
        return -float(sl_r)
    return np.nan


def _net_leg_r(side: str, entry: float, exit_price: float, gross_r: float, unit: float,
               config) -> float:
    if not np.isfinite(gross_r):
        return np.nan
    result = float(gross_r)
    if bool(getattr(config, "dual_entry_include_slippage", False)):
        # Apply entry and exit slippage against the position in normalized R units.
        slip = float(config.slippage)
        result -= (entry * slip + float(exit_price) * slip) / unit
    if bool(getattr(config, "dual_entry_include_fees", False)):
        entry_fee = float(config.maker_fee if config.use_maker_entry else config.taker_fee)
        exit_fee = float(config.maker_fee if config.use_maker_exit else config.taker_fee)
        result -= (entry * entry_fee + float(exit_price) * exit_fee) / unit
    return result


def _pair_result(long_reason: str, short_reason: str) -> str:
    if long_reason == "TP" and short_reason == "TP":
        return "DOUBLE_TP"
    if long_reason == "TP" and short_reason == "SL":
        return "LONG_TP_SHORT_SL"
    if long_reason == "SL" and short_reason == "TP":
        return "SHORT_TP_LONG_SL"
    if long_reason == "SL" and short_reason == "SL":
        return "DOUBLE_SL"
    return "OPEN_OR_EXPIRED"


def _sr_fields(engine, i: int, side: str) -> dict[str, Any]:
    if not bool(getattr(engine.config, "enable_support_resistance_analysis", False)):
        return {}
    context = engine._analyze_support_resistance(i, side)
    if context is None:
        return {}
    prefix = "long_sr" if side == "LONG" else "short_sr"
    return {
        f"{prefix}_location": getattr(getattr(context, "price_location", None), "value", "UNKNOWN"),
        f"{prefix}_rating": getattr(getattr(context, "trade_location_rating", None), "value", "UNKNOWN"),
        f"{prefix}_room_atr": getattr(context, "room_in_direction_atr", np.nan),
        f"{prefix}_support_distance_atr": getattr(context, "nearest_support_distance_atr", np.nan),
        f"{prefix}_resistance_distance_atr": getattr(context, "nearest_resistance_distance_atr", np.nan),
    }


def run_dual_entry_research(engine) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Simulate paired LONG/SHORT observations from the normal engine's accepted entries."""
    config = engine.config
    if not bool(getattr(config, "enable_dual_entry_research", False)):
        return pd.DataFrame(), pd.DataFrame(), {}

    tp_r = float(getattr(config, "dual_entry_tp_r", 2.0))
    sl_r = float(getattr(config, "dual_entry_sl_r", 5.0))
    max_minutes = int(getattr(config, "dual_entry_max_duration_minutes", 0) or 0)
    source = engine.intrabar_data if bool(config.use_intrabar_data) and engine.intrabar_data is not None else engine.data
    source = source.copy()
    source["timestamp"] = pd.to_datetime(source["timestamp"], utc=True)
    source = source.sort_values("timestamp").reset_index(drop=True)
    strategy_times = pd.to_datetime(engine.data["timestamp"], utc=True)

    rows: list[dict[str, Any]] = []
    for observation_id, pair in enumerate(engine.completed_pairs, 1):
        candle_time = _utc(pair.strategy_candle_open_time)
        matches = np.flatnonzero(strategy_times.to_numpy() == candle_time.to_datetime64())
        if len(matches):
            i = int(matches[-1])
        else:
            i = int(strategy_times.searchsorted(candle_time, side="right") - 1)
        if i < 0 or i >= len(engine.data):
            continue
        unit = float(engine.risk[i])
        if not np.isfinite(unit) or unit <= 0:
            continue

        entry_time = _utc(pair.strategy_entry_time)
        entry = float(pair.strategy_entry_price)
        future = source[source["timestamp"] >= entry_time]
        if max_minutes > 0:
            future = future[future["timestamp"] <= entry_time + pd.Timedelta(minutes=max_minutes)]
        if future.empty:
            continue

        long_exit = _first_exit("LONG", entry, unit, tp_r, sl_r, future, str(config.tie_policy))
        short_exit = _first_exit("SHORT", entry, unit, tp_r, sl_r, future, str(config.tie_policy))
        long_gross_r = _leg_r(long_exit["reason"], tp_r, sl_r)
        short_gross_r = _leg_r(short_exit["reason"], tp_r, sl_r)
        long_net_r = _net_leg_r("LONG", entry, long_exit["price"], long_gross_r, unit, config)
        short_net_r = _net_leg_r("SHORT", entry, short_exit["price"], short_gross_r, unit, config)
        pair_gross_r = long_gross_r + short_gross_r if np.isfinite(long_gross_r) and np.isfinite(short_gross_r) else np.nan
        pair_net_r = long_net_r + short_net_r if np.isfinite(long_net_r) and np.isfinite(short_net_r) else np.nan

        selected = engine._selected_direction(i)
        di = engine._di_pressure_snapshot(i, selected)
        spread = float(di.get("di_spread", np.nan))
        spread_change = float(di.get("di_spread_change", np.nan))
        lookback = max(1, int(di.get("di_pressure_lookback", getattr(config, "di_pressure_lookback", 1))))
        first_tp_side = "NONE"
        tp_events = []
        if long_exit["reason"] == "TP":
            tp_events.append((long_exit["time"], "LONG"))
        if short_exit["reason"] == "TP":
            tp_events.append((short_exit["time"], "SHORT"))
        if tp_events:
            first_tp_side = min(tp_events, key=lambda item: item[0])[1]
        completed_times = [x["time"] for x in (long_exit, short_exit) if x["reason"] != "UNRESOLVED"]
        completion_time = max(completed_times) if len(completed_times) == 2 else pd.NaT

        regime = engine._regime_at(i) if hasattr(engine, "_regime_at") else None
        row = {
            "observation_id": observation_id,
            "source_pair_id": getattr(pair, "pair_id", observation_id),
            "strategy_candle_open_time": candle_time,
            "entry_time": entry_time,
            "entry_price": entry,
            "distance_unit": unit,
            "tp_r": tp_r,
            "sl_r": sl_r,
            "long_tp_price": long_exit["tp_price"],
            "long_sl_price": long_exit["sl_price"],
            "long_exit_reason": long_exit["reason"],
            "long_exit_time": long_exit["time"],
            "long_exit_price": long_exit["price"],
            "long_bars_to_exit": long_exit["bars"],
            "long_same_bar_ambiguous": long_exit["ambiguous"],
            "long_gross_r": long_gross_r,
            "long_net_r": long_net_r,
            "short_tp_price": short_exit["tp_price"],
            "short_sl_price": short_exit["sl_price"],
            "short_exit_reason": short_exit["reason"],
            "short_exit_time": short_exit["time"],
            "short_exit_price": short_exit["price"],
            "short_bars_to_exit": short_exit["bars"],
            "short_same_bar_ambiguous": short_exit["ambiguous"],
            "short_gross_r": short_gross_r,
            "short_net_r": short_net_r,
            "pair_result": _pair_result(long_exit["reason"], short_exit["reason"]),
            "pair_gross_r": pair_gross_r,
            "pair_net_r": pair_net_r,
            "first_tp_side": first_tp_side,
            "pair_completion_time": completion_time,
            "bars_to_pair_completion": max(long_exit["bars"], short_exit["bars"]) if np.isfinite(long_exit["bars"]) and np.isfinite(short_exit["bars"]) else np.nan,
            "market_regime": regime,
            "di_selected_direction": selected or "NONE",
            "di_bucket": _di_bucket(spread),
            "di_pressure_speed": spread_change / lookback if np.isfinite(spread_change) else np.nan,
            **di,
        }
        long_mr = engine._mean_reversion_snapshot(i, selected, "LONG")
        short_mr = engine._mean_reversion_snapshot(i, selected, "SHORT")
        for key, value in long_mr.items():
            row[f"long_{key}"] = value
        for key, value in short_mr.items():
            row[f"short_{key}"] = value
        row.update(_sr_fields(engine, i, "LONG"))
        row.update(_sr_fields(engine, i, "SHORT"))
        rows.append(row)

    observations = pd.DataFrame(rows)
    if observations.empty:
        return observations, pd.DataFrame(), {
            "enabled": True, "observations": 0, "tp_r": tp_r, "sl_r": sl_r,
            "break_even_double_tp_rate_pct_before_costs": 100.0 * sl_r / (tp_r * 2.0 + sl_r - tp_r),
        }

    resolved = observations[observations["pair_result"] != "OPEN_OR_EXPIRED"].copy()
    group_source = resolved if not resolved.empty else observations
    di_summary = (
        group_source.groupby(["di_bucket", "di_pressure_state"], dropna=False)
        .agg(
            pairs=("observation_id", "count"),
            double_tp=("pair_result", lambda s: int((s == "DOUBLE_TP").sum())),
            long_tp_short_sl=("pair_result", lambda s: int((s == "LONG_TP_SHORT_SL").sum())),
            short_tp_long_sl=("pair_result", lambda s: int((s == "SHORT_TP_LONG_SL").sum())),
            double_sl=("pair_result", lambda s: int((s == "DOUBLE_SL").sum())),
            average_pair_gross_r=("pair_gross_r", "mean"),
            average_pair_net_r=("pair_net_r", "mean"),
            average_di_pressure_speed=("di_pressure_speed", "mean"),
        )
        .reset_index()
    )
    di_summary["double_tp_rate_pct"] = np.where(
        di_summary["pairs"] > 0, di_summary["double_tp"] / di_summary["pairs"] * 100.0, np.nan
    )

    # For outcomes +2/+2 versus +2/-5, break-even is 3 / 7 = 42.857%.
    double_tp_rate = float((resolved["pair_result"] == "DOUBLE_TP").mean() * 100.0) if len(resolved) else np.nan
    summary = {
        "enabled": True,
        "observations": int(len(observations)),
        "resolved_pairs": int(len(resolved)),
        "unresolved_pairs": int((observations["pair_result"] == "OPEN_OR_EXPIRED").sum()),
        "tp_r": tp_r,
        "sl_r": sl_r,
        "double_tp": int((resolved["pair_result"] == "DOUBLE_TP").sum()),
        "double_tp_rate_pct": double_tp_rate,
        "average_pair_gross_r": float(resolved["pair_gross_r"].mean()) if len(resolved) else np.nan,
        "average_pair_net_r": float(resolved["pair_net_r"].mean()) if len(resolved) else np.nan,
        "include_fees": bool(getattr(config, "dual_entry_include_fees", False)),
        "include_slippage": bool(getattr(config, "dual_entry_include_slippage", False)),
        "max_duration_minutes": max_minutes,
        "break_even_double_tp_rate_pct_before_costs": 100.0 * (sl_r - tp_r) / ((2.0 * tp_r) + (sl_r - tp_r)),
    }
    return observations, di_summary, summary


def store_pending(config, observations: pd.DataFrame, di_summary: pd.DataFrame, summary: dict[str, Any]) -> None:
    if bool(getattr(config, "enable_dual_entry_research", False)):
        _PENDING[id(config)] = (observations, di_summary, summary)


def flush_pending(config, run_dir: str | Path) -> None:
    """Write research artifacts into the normal run directory, if a result is pending."""
    payload = _PENDING.pop(id(config), None)
    if payload is None:
        return
    observations, di_summary, summary = payload
    run_dir = Path(run_dir)
    observations.to_csv(run_dir / "dual_entry_research.csv", index=False)
    di_summary.to_csv(run_dir / "dual_entry_di_summary.csv", index=False)
    (run_dir / "dual_entry_research_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
