"""Fast implementation of the optional dual LONG + SHORT research simulation.

Keeps the research model isolated from normal trading while avoiding repeated
full-DataFrame filtering for every observation.  Exit discovery uses binary
search to jump to the entry bar and vectorized chunks to locate TP/SL events.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from crypto_strategy_lab.dual_entry_research import (
    _di_bucket,
    _leg_r,
    _net_leg_r,
    _pair_result,
    _sr_fields,
    _utc,
)


def _resolved_exit(reason: str, price: float, time_ns, bars: int, ambiguous: bool,
                   tp: float, sl: float) -> dict[str, Any]:
    return {
        "reason": reason,
        "price": price,
        "time": pd.Timestamp(time_ns, tz="UTC"),
        "bars": bars,
        "ambiguous": ambiguous,
        "tp_price": tp,
        "sl_price": sl,
    }


def _unresolved(tp: float, sl: float) -> dict[str, Any]:
    return {
        "reason": "UNRESOLVED", "price": np.nan, "time": pd.NaT,
        "bars": np.nan, "ambiguous": False, "tp_price": tp, "sl_price": sl,
    }


def _scan_pair(entry: float, unit: float, tp_r: float, sl_r: float,
               timestamps: np.ndarray, highs: np.ndarray, lows: np.ndarray,
               start: int, stop: int, tie_policy: str,
               chunk_size: int = 4096) -> tuple[dict[str, Any], dict[str, Any]]:
    long_tp = entry + tp_r * unit
    long_sl = entry - sl_r * unit
    short_tp = entry - tp_r * unit
    short_sl = entry + sl_r * unit
    pessimistic = str(tie_policy).upper().endswith("PESSIMISTIC")
    long_exit = None
    short_exit = None

    cursor = start
    while cursor < stop and (long_exit is None or short_exit is None):
        end = min(stop, cursor + chunk_size)
        h = highs[cursor:end]
        l = lows[cursor:end]

        if long_exit is None:
            tp_hits = h >= long_tp
            sl_hits = l <= long_sl
            hits = tp_hits | sl_hits
            found = np.flatnonzero(hits)
            if found.size:
                rel = int(found[0]); absolute = cursor + rel
                both = bool(tp_hits[rel] and sl_hits[rel])
                reason = "SL" if both and pessimistic else ("TP" if tp_hits[rel] else "SL")
                price = long_tp if reason == "TP" else long_sl
                long_exit = _resolved_exit(reason, price, timestamps[absolute], absolute - start + 1,
                                           both, long_tp, long_sl)

        if short_exit is None:
            tp_hits = l <= short_tp
            sl_hits = h >= short_sl
            hits = tp_hits | sl_hits
            found = np.flatnonzero(hits)
            if found.size:
                rel = int(found[0]); absolute = cursor + rel
                both = bool(tp_hits[rel] and sl_hits[rel])
                reason = "SL" if both and pessimistic else ("TP" if tp_hits[rel] else "SL")
                price = short_tp if reason == "TP" else short_sl
                short_exit = _resolved_exit(reason, price, timestamps[absolute], absolute - start + 1,
                                            both, short_tp, short_sl)
        cursor = end

    return long_exit or _unresolved(long_tp, long_sl), short_exit or _unresolved(short_tp, short_sl)


def run_dual_entry_research(engine) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = engine.config
    if not bool(getattr(config, "enable_dual_entry_research", False)):
        return pd.DataFrame(), pd.DataFrame(), {}

    tp_r = float(getattr(config, "dual_entry_tp_r", 2.0))
    sl_r = float(getattr(config, "dual_entry_sl_r", 5.0))
    max_minutes = int(getattr(config, "dual_entry_max_duration_minutes", 0) or 0)

    source = engine.intrabar_data if bool(config.use_intrabar_data) and engine.intrabar_data is not None else engine.data
    source = source[["timestamp", "high", "low"]].copy()
    source["timestamp"] = pd.to_datetime(source["timestamp"], utc=True)
    source = source.sort_values("timestamp").reset_index(drop=True)
    source_ns = source["timestamp"].astype("int64").to_numpy()
    highs = source["high"].to_numpy(float)
    lows = source["low"].to_numpy(float)

    strategy_times = pd.to_datetime(engine.data["timestamp"], utc=True)
    strategy_ns = strategy_times.astype("int64").to_numpy()
    rows: list[dict[str, Any]] = []
    total = len(engine.completed_pairs)
    engine.log(f"Dual-entry research: scanning {total:,} accepted entries with indexed intrabar lookup")

    for observation_id, pair in enumerate(engine.completed_pairs, 1):
        candle_time = _utc(pair.strategy_candle_open_time)
        candle_ns = candle_time.value
        i = int(np.searchsorted(strategy_ns, candle_ns, side="right") - 1)
        if i < 0 or i >= len(engine.data):
            continue
        unit = float(engine.risk[i])
        if not np.isfinite(unit) or unit <= 0:
            continue

        entry_time = _utc(pair.strategy_entry_time)
        entry_ns = entry_time.value
        start = int(np.searchsorted(source_ns, entry_ns, side="left"))
        if start >= len(source_ns):
            continue
        if max_minutes > 0:
            end_ns = (entry_time + pd.Timedelta(minutes=max_minutes)).value
            stop = int(np.searchsorted(source_ns, end_ns, side="right"))
        else:
            stop = len(source_ns)
        if stop <= start:
            continue

        entry = float(pair.strategy_entry_price)
        long_exit, short_exit = _scan_pair(
            entry, unit, tp_r, sl_r, source_ns, highs, lows, start, stop, str(config.tie_policy)
        )
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
        tp_events = []
        if long_exit["reason"] == "TP": tp_events.append((long_exit["time"], "LONG"))
        if short_exit["reason"] == "TP": tp_events.append((short_exit["time"], "SHORT"))
        first_tp_side = min(tp_events, key=lambda item: item[0])[1] if tp_events else "NONE"
        completed_times = [x["time"] for x in (long_exit, short_exit) if x["reason"] != "UNRESOLVED"]
        completion_time = max(completed_times) if len(completed_times) == 2 else pd.NaT
        regime = engine._regime_at(i) if hasattr(engine, "_regime_at") else None

        row = {
            "observation_id": observation_id, "source_pair_id": getattr(pair, "pair_id", observation_id),
            "strategy_candle_open_time": candle_time, "entry_time": entry_time, "entry_price": entry,
            "distance_unit": unit, "tp_r": tp_r, "sl_r": sl_r,
            "long_tp_price": long_exit["tp_price"], "long_sl_price": long_exit["sl_price"],
            "long_exit_reason": long_exit["reason"], "long_exit_time": long_exit["time"],
            "long_exit_price": long_exit["price"], "long_bars_to_exit": long_exit["bars"],
            "long_same_bar_ambiguous": long_exit["ambiguous"], "long_gross_r": long_gross_r, "long_net_r": long_net_r,
            "short_tp_price": short_exit["tp_price"], "short_sl_price": short_exit["sl_price"],
            "short_exit_reason": short_exit["reason"], "short_exit_time": short_exit["time"],
            "short_exit_price": short_exit["price"], "short_bars_to_exit": short_exit["bars"],
            "short_same_bar_ambiguous": short_exit["ambiguous"], "short_gross_r": short_gross_r, "short_net_r": short_net_r,
            "pair_result": _pair_result(long_exit["reason"], short_exit["reason"]),
            "pair_gross_r": pair_gross_r, "pair_net_r": pair_net_r, "first_tp_side": first_tp_side,
            "pair_completion_time": completion_time,
            "bars_to_pair_completion": max(long_exit["bars"], short_exit["bars"]) if np.isfinite(long_exit["bars"]) and np.isfinite(short_exit["bars"]) else np.nan,
            "market_regime": regime, "di_selected_direction": selected or "NONE", "di_bucket": _di_bucket(spread),
            "di_pressure_speed": spread_change / lookback if np.isfinite(spread_change) else np.nan, **di,
        }
        for key, value in engine._mean_reversion_snapshot(i, selected, "LONG").items(): row[f"long_{key}"] = value
        for key, value in engine._mean_reversion_snapshot(i, selected, "SHORT").items(): row[f"short_{key}"] = value
        row.update(_sr_fields(engine, i, "LONG")); row.update(_sr_fields(engine, i, "SHORT")); rows.append(row)
        if observation_id % 500 == 0 or observation_id == total:
            engine.log(f"Dual-entry research: {observation_id:,}/{total:,} observations scanned")

    observations = pd.DataFrame(rows)
    if observations.empty:
        return observations, pd.DataFrame(), {"enabled": True, "observations": 0, "tp_r": tp_r, "sl_r": sl_r}

    resolved = observations[observations["pair_result"] != "OPEN_OR_EXPIRED"].copy()
    group_source = resolved if not resolved.empty else observations
    di_summary = group_source.groupby(["di_bucket", "di_pressure_state"], dropna=False).agg(
        pairs=("observation_id", "count"),
        double_tp=("pair_result", lambda s: int((s == "DOUBLE_TP").sum())),
        long_tp_short_sl=("pair_result", lambda s: int((s == "LONG_TP_SHORT_SL").sum())),
        short_tp_long_sl=("pair_result", lambda s: int((s == "SHORT_TP_LONG_SL").sum())),
        double_sl=("pair_result", lambda s: int((s == "DOUBLE_SL").sum())),
        average_pair_gross_r=("pair_gross_r", "mean"), average_pair_net_r=("pair_net_r", "mean"),
        average_di_pressure_speed=("di_pressure_speed", "mean"),
    ).reset_index()
    di_summary["double_tp_rate_pct"] = np.where(di_summary["pairs"] > 0, di_summary["double_tp"] / di_summary["pairs"] * 100.0, np.nan)
    double_tp_rate = float((resolved["pair_result"] == "DOUBLE_TP").mean() * 100.0) if len(resolved) else np.nan
    summary = {
        "enabled": True, "observations": int(len(observations)), "resolved_pairs": int(len(resolved)),
        "unresolved_pairs": int((observations["pair_result"] == "OPEN_OR_EXPIRED").sum()),
        "tp_r": tp_r, "sl_r": sl_r, "double_tp": int((resolved["pair_result"] == "DOUBLE_TP").sum()),
        "double_tp_rate_pct": double_tp_rate,
        "average_pair_gross_r": float(resolved["pair_gross_r"].mean()) if len(resolved) else np.nan,
        "average_pair_net_r": float(resolved["pair_net_r"].mean()) if len(resolved) else np.nan,
        "include_fees": bool(getattr(config, "dual_entry_include_fees", False)),
        "include_slippage": bool(getattr(config, "dual_entry_include_slippage", False)),
        "max_duration_minutes": max_minutes,
        "break_even_double_tp_rate_pct_before_costs": 100.0 * (sl_r - tp_r) / ((2.0 * tp_r) + (sl_r - tp_r)),
    }
    return observations, di_summary, summary
