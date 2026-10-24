"""Mechanical JeaFx-inspired full imbalance fill into origin; causal research preset."""
import copy

import numpy as np
import pandas as pd

MODE = "IMBALANCE_ORIGIN_RETEST"


def origin_retest_setups(times, opens, highs, lows, closes, atr_values, *,
                         timeframe_minutes=60, strength=2,
                         displacement_atr=.5, max_wait=20):
    from .supply_demand_retest import validate_settings
    validate_settings(strength, 0., 1.)
    if not np.isfinite(displacement_atr) or displacement_atr <= 0:
        raise ValueError("Displacement must be finite and positive")
    if not np.isfinite(max_wait) or int(max_wait) != max_wait or max_wait < 1:
        raise ValueError("Maximum wait must be a positive integer")
    if not np.isfinite(timeframe_minutes) or timeframe_minutes <= 0:
        raise ValueError("Timeframe must be positive")
    ts = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    arrays = [np.asarray(a, dtype=float) for a in (opens, highs, lows, closes, atr_values)]
    if any(a.ndim != 1 or len(a) != len(ts) for a in arrays) or ts.has_duplicates or ts.hasnans or not ts.is_monotonic_increasing:
        raise ValueError("Candles must align with unique increasing timestamps")
    o, h, l, c, atr = arrays
    step = pd.Timedelta(minutes=timeframe_minutes)
    result = [None] * len(ts)
    pending = {}
    segment = 0
    lookback = 2 * int(strength) + 1
    for i, t in enumerate(ts):
        valid = all(np.isfinite(a[i]) for a in arrays[:4]) and 0 < l[i] <= min(o[i], c[i]) <= max(o[i], c[i]) <= h[i]
        if (i and t - ts[i-1] != step) or not valid:
            pending.clear()
            segment = i if valid else i+1
        if not valid:
            continue
        candidates = []
        for side, setup in list(pending.items()):
            long = side == "LONG"
            z = setup["zone"]
            if i-setup["formedIndex"] > max_wait or (l[i] < z["bottom"] if long else h[i] > z["top"]):
                del pending[side]
                continue
            touch = l[i] <= z["top"] and h[i] >= z["bottom"]
            # Touching the origin necessarily fills the gap's far edge first.
            rejection = c[i] > o[i] and c[i] > z["top"] if long else c[i] < o[i] and c[i] < z["bottom"]
            if touch and rejection:
                saved = copy.deepcopy(setup)
                saved.pop("formedIndex")
                saved["signalTime"] = t.isoformat()
                saved["zone"].update(touchTime=t.isoformat(), bounceTime=t.isoformat())
                candidates.append(saved)
                del pending[side]
        if len(candidates) == 1:
            result[i] = candidates[0]
        j = i-2  # Origin; middle candle is displacement, current candle confirms gap.
        if j-lookback < segment or not np.isfinite(atr[i-1]) or atr[i-1] <= 0:
            continue
        bull = l[i] > h[j] and c[i-1]-o[i-1] >= displacement_atr*atr[i-1] and c[i-1] > max(h[j-lookback:j+1]) and c[j] <= o[j]
        bear = h[i] < l[j] and o[i-1]-c[i-1] >= displacement_atr*atr[i-1] and c[i-1] < min(l[j-lookback:j+1]) and c[j] >= o[j]
        if not (bull or bear) or h[j] <= l[j]:
            continue
        side = "LONG" if bull else "SHORT"
        target = float(max(h[i-1:i+1]) if bull else min(l[i-1:i+1]))
        pending[side] = dict(version=1, strategy=MODE, side=side, formedIndex=i,
            signalTime=None, target=target,
            imbalance=dict(bottom=float(h[j] if bull else h[i]), top=float(l[i] if bull else l[j])),
            zone=dict(bottom=float(l[j]), top=float(h[j]), pivotTime=ts[j].isoformat(),
                      confirmedTime=(t+step).isoformat(), touchTime=None, bounceTime=None),
            opposingZone=dict(bottom=float(l[i-1] if bull else target), top=float(target if bull else h[i-1]),
                              pivotTime=ts[i-1].isoformat(), confirmedTime=(t+step).isoformat()))
    return result
