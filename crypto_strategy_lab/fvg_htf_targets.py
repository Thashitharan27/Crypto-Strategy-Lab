"""Causal snapshots of untouched higher-timeframe FVGs for profit targets."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def validate_target_settings(mode, timeframe, minimum_r, policy, strategy_minutes):
    if mode not in {"FIXED_R", "HTF_OPPOSING_FVG"}:
        raise ValueError("Invalid FVG target mode")
    if policy not in {"REJECT_TRADE", "USE_FIXED_TP"}:
        raise ValueError("Invalid FVG missing-target policy")
    if not math.isfinite(minimum_r) or minimum_r <= 0:
        raise ValueError("FVG minimum target R must be finite and positive")
    if mode == "HTF_OPPOSING_FVG" and (
        not math.isfinite(timeframe) or int(timeframe) != timeframe
        or timeframe <= strategy_minutes or timeframe % strategy_minutes
    ):
        raise ValueError("FVG target timeframe must be larger than and an exact multiple of the strategy timeframe")


def opposing_fvg_snapshots(times, high, low, close, strategy_minutes, target_minutes):
    """Return zones known at each strategy candle CLOSE, never its future bars.

    A zone is consumed by its first strategy-bar touch, including a wick, or a
    gap through it. Formation bars do not consume the zone they just created.
    Incomplete HTF buckets cannot create gaps, including across missing buckets.
    """
    validate_target_settings("HTF_OPPOSING_FVG", target_minutes, 1.0, "REJECT_TRADE", strategy_minutes)
    ts = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    high, low, close = [np.asarray(a, dtype=float) for a in (high, low, close)]
    if any(a.ndim != 1 or len(a) != len(ts) for a in (high, low, close)):
        raise ValueError("FVG target candles must align with timestamps")
    if not ts.is_monotonic_increasing or ts.has_duplicates:
        raise ValueError("FVG target timestamps must be unique and increasing")
    expected = int(target_minutes // strategy_minutes)
    step = pd.Timedelta(minutes=strategy_minutes)
    htf_step = pd.Timedelta(minutes=target_minutes)
    frame = pd.DataFrame({"time": ts, "high": high, "low": low, "close": close})
    completed = []
    for start, group in frame.groupby(frame.time.dt.floor(f"{int(target_minutes)}min"), sort=True):
        if len(group) != expected or not np.isfinite(group[["high", "low", "close"]]).all().all():
            continue
        if not (pd.DatetimeIndex(group.time) == pd.date_range(start, periods=expected, freq=step)).all():
            continue
        completed.append((start, float(group.high.max()), float(group.low.min())))
    snapshots = []
    active = []
    history = []
    cursor = 0
    for i, opening in enumerate(ts):
        if i and opening != ts[i-1] + step:
            active.clear()
            history.clear()
        if not all(np.isfinite(a[i]) for a in (high, low, close)):
            active.clear()
            history.clear()
        else:
            active = [z for z in active if not (
                (low[i] <= z["top"] and high[i] >= z["bottom"])
                or (z["side"] == "LONG" and close[i] < z["bottom"])
                or (z["side"] == "SHORT" and close[i] > z["top"])
            )]
        while cursor < len(completed) and completed[cursor][0] + htf_step <= opening + step:
            bar = completed[cursor]
            cursor += 1
            if history and bar[0] != history[-1][0] + htf_step:
                history.clear()
                active.clear()
            history.append(bar)
            history = history[-3:]
            if len(history) != 3:
                continue
            first = history[0]
            for side, bottom, top in (("LONG", first[1], bar[2]), ("SHORT", bar[1], first[2])):
                if top > bottom:
                    active.append({"side": side, "bottom": bottom, "top": top,
                                   "confirmed_at": (bar[0] + htf_step).isoformat(),
                                   "timeframe_minutes": int(target_minutes)})
        snapshots.append(tuple(active))
    return snapshots


def nearest_opposing_zone(zones, direction, entry):
    opposite = "SHORT" if direction == "LONG" else "LONG"
    zones = [z for z in zones if z["side"] == opposite]
    if any(z["bottom"] <= entry <= z["top"] for z in zones):
        return None, "FVG_HTF_TARGET_ENTRY_INSIDE_ZONE"
    ahead = [z for z in zones if z["bottom"] > entry] if direction == "LONG" else [z for z in zones if z["top"] < entry]
    if not ahead:
        return None, "FVG_HTF_TARGET_UNAVAILABLE"
    zone = min(ahead, key=lambda z: z["bottom"]) if direction == "LONG" else max(ahead, key=lambda z: z["top"])
    return zone, "FVG_HTF_OPPOSING_TARGET"
