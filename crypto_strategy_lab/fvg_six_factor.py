"""Causal, explicit first version of the six-factor FVG research preset."""
from __future__ import annotations

import numpy as np

from crypto_strategy_lab.fair_value_gap import FVG_RULE_INDICATORS, _fvg_market_structure_features


def revisit_close_confirms(side, bottom, top, open_price, close_price):
    """Accept an inside close or a directional rejection on the safe side."""
    if not all(np.isfinite(v) for v in (bottom, top, open_price, close_price)):
        return False
    if bottom <= close_price <= top:
        return True
    if side == "LONG":
        return bool(close_price > top and close_price > open_price)
    return bool(close_price < bottom and close_price < open_price)


def six_factor_context(high, low, close, atr, *, open_, swing_strength=2, times=None,
                       min_clear_bars=3, min_move_away_atr=0.5):
    if not np.isfinite(min_clear_bars) or int(min_clear_bars) != min_clear_bars or min_clear_bars < 0:
        raise ValueError("FVG minimum clear candles must be a nonnegative integer")
    if not np.isfinite(min_move_away_atr) or min_move_away_atr < 0:
        raise ValueError("FVG minimum move-away ATR must be finite and nonnegative")
    high, low, close, atr, open_ = [np.asarray(a, dtype=float) for a in (high, low, close, atr, open_)]
    if any(a.ndim != 1 or len(a) != len(close) for a in (high, low, close, atr, open_)):
        raise ValueError("six-factor candle arrays must be one-dimensional and equally sized")
    n = len(close)
    if times is not None and len(times) != n:
        raise ValueError("six-factor timestamps must align with candles")
    strength = max(1, int(swing_strength))
    structure = _fvg_market_structure_features(high, low, open_, close, atr, strength)
    signals = np.full(n, None, dtype=object)
    features = {side: {key: np.full(n, np.nan) for key in FVG_RULE_INDICATORS} for side in ("LONG", "SHORT")}
    stops = {side: np.full(n, np.nan) for side in features}
    targets = {side: np.full(n, np.nan) for side in features}
    reviews = [None] * n
    pivots = {"high": None, "low": None}
    breaks = {"LONG": None, "SHORT": None}
    active = []

    def stamp(index):
        return str(times[index]) if times is not None else None

    for i in range(n):
        if not all(np.isfinite(a[i]) for a in (high, low, close, open_)):
            active.clear()
            pivots = {"high": None, "low": None}
            breaks = {"LONG": None, "SHORT": None}
            continue
        j = i - strength
        if j >= strength:
            for name, values, compare in (("high", high, np.greater), ("low", low, np.less)):
                peers = np.concatenate((values[j-strength:j], values[j+1:j+strength+1]))
                if np.isfinite(values[j]) and np.all(np.isfinite(peers)) and np.all(compare(values[j], peers)):
                    pivots[name] = (j, float(values[j]))
        for side, pivot_name, origin_name in (("LONG", "high", "low"), ("SHORT", "low", "high")):
            pivot = pivots[pivot_name]
            if pivot is None or pivots[origin_name] is None or i == 0:
                continue
            crossed = close[i] > pivot[1] >= close[i-1] if side == "LONG" else close[i] < pivot[1] <= close[i-1]
            if crossed:
                breaks[side] = {"index": i, "pivot_index": pivot[0], "level": pivot[1], "origin": pivots[origin_name][1], "origin_index": pivots[origin_name][0]}
                breaks["SHORT" if side == "LONG" else "LONG"] = None

        accepted = []
        survivors = []
        # Priority is measured BEFORE any zones are consumed on this candle.
        for zone in active:
            side = zone["side"]
            touched = low[i] <= zone["top"] and high[i] >= zone["bottom"]
            if not touched:
                # Entire-candle gaps through a zone invalidate it too.
                failed = close[i] < zone["bottom"] if side == "LONG" else close[i] > zone["top"]
                if not failed:
                    survivors.append(zone)
                continue
            peers = [z for z in active if z["side"] == side and z["break_index"] == zone["break_index"]]
            ranked = min(peers, key=lambda z: (z["bottom"], z["formed"])) if side == "LONG" else max(peers, key=lambda z: (z["top"], -z["formed"]))
            midpoint = (zone["origin"] + zone["extreme"]) / 2
            gap_mid = (zone["bottom"] + zone["top"]) / 2
            checks = {
                "First untouched revisit": True,
                "Inside close or directional wick rejection": revisit_close_confirms(side, zone["bottom"], zone["top"], open_[i], close[i]),
                "Prior pivot / broken-level overlap": zone["sr_aligned"],
                "Highest priority in impulse": zone is ranked,
                "Discount / premium half": bool(gap_mid <= midpoint if side == "LONG" else gap_mid >= midpoint),
                "Structure break before formation": zone["break_index"] <= zone["formed"],
            }
            separation = {"clearBars": i-zone["formed"]-1, "requiredClearBars": int(min_clear_bars),
                          "moveAwayAtr": zone["move_away"] / atr[zone["formed"]],
                          "requiredMoveAwayAtr": float(min_move_away_atr),
                          "moveAwayPrice": zone["move_away"], "formationAtr": float(atr[zone["formed"]])}
            separation["passed"] = bool(separation["clearBars"] >= min_clear_bars and separation["moveAwayAtr"] >= min_move_away_atr)
            if all(checks.values()) and separation["passed"]:
                accepted.append((zone, midpoint, checks, separation))
            # Every first touch consumes a zone, even if another check fails.
        active = survivors
        sides = {candidate[0]["side"] for candidate in accepted}
        if len(sides) == 1:
            zone, midpoint, checks, separation = min(accepted, key=lambda candidate: candidate[0]["formed"])
            side = zone["side"]
            signals[i] = side
            stops[side][i] = zone["stop"]
            targets[side][i] = zone["extreme"]
            f = features[side]
            formed = zone["formed"]
            f["FVG_AGE_BARS"][i] = i - formed
            f["FVG_GAP_SIZE_ATR"][i] = (zone["top"] - zone["bottom"]) / atr[formed]
            depth = zone["top"] - low[i] if side == "LONG" else high[i] - zone["bottom"]
            f["FVG_REVISIT_DEPTH_PCT"][i] = np.clip(depth / (zone["top"] - zone["bottom"]), 0, 1)
            for name, suffix in (("CHOCH", "choch"), ("BOS", "bos"), ("LIQUIDITY_SWEEP", "sweep")):
                direction = side.lower()
                f[f"FVG_{name}_ALIGNED"][i] = structure[f"{suffix}_{direction}"][formed]
                key = "SWEEP" if suffix == "sweep" else name
                f[f"FVG_BARS_SINCE_{key}"][i] = structure[f"bars_since_{suffix}_{direction}"][formed]
            f["FVG_DISPLACEMENT_BODY_ATR"][i] = structure["displacement_body_atr"][formed]
            f["FVG_DISPLACEMENT_BODY_RATIO"][i] = structure["displacement_body_ratio"][formed]
            strength_value = structure["displacement_close_location"][formed]
            f["FVG_DISPLACEMENT_CLOSE_LOCATION"][i] = strength_value if side == "LONG" else 1 - strength_value
            f["FVG_LOCATION_ALIGNED"][i] = 1.0
            reviews[i] = {
                "version": 1, "side": side, "bottom": zone["bottom"], "top": zone["top"],
                "confirmationRule": "INSIDE_OR_DIRECTIONAL_REJECTION_V2",
                "separationRule": "MIN_CLEAR_BARS_AND_MOVE_AWAY_V1", "separation": separation,
                "formedTime": stamp(formed), "signalTime": stamp(i),
                "formationCandles": [dict(time=stamp(j), high=float(high[j]), low=float(low[j])) for j in range(formed-2, formed+1)],
                "structurePivotTime": stamp(zone["structure_pivot_index"]),
                "structureBreakTime": stamp(zone["break_index"]),
                "impulseStartTime": stamp(zone["origin_index"]),
                "impulseOrigin": zone["origin"], "impulseExtreme": zone["extreme"],
                "midpoint": midpoint, "structureLevel": zone["structure_level"],
                "confluenceLevel": zone["sr_level"], "stopBoundary": zone["stop"],
                "checks": checks,
            }
        # Only earlier bars define the move extreme for a revisit decision.
        for zone in active:
            zone["extreme"] = max(zone["extreme"], high[i]) if zone["side"] == "LONG" else min(zone["extreme"], low[i])
            distance = high[i]-zone["top"] if zone["side"] == "LONG" else zone["bottom"]-low[i]
            zone["move_away"] = max(zone["move_away"], float(distance))
        if i < 2 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        for side in ("LONG", "SHORT"):
            bottom, top = (high[i-2], low[i]) if side == "LONG" else (high[i], low[i-2])
            event = breaks[side]
            if not np.isfinite(bottom) or not np.isfinite(top) or top <= bottom or event is None:
                continue
            # Confirmed S/R pivots plus the broken level (role reversal), with
            # an explicit 0.1 formation-ATR tolerance around the gap.
            levels = [p[1] for p in pivots.values() if p is not None] + [event["level"]]
            levels = [v for v in levels if bottom - .1*atr[i] <= v <= top + .1*atr[i]]
            origin_i = event["origin_index"]
            extreme = float(np.max(high[origin_i:i+1]) if side == "LONG" else np.min(low[origin_i:i+1]))
            active.append({"side": side, "bottom": float(bottom), "top": float(top), "formed": i,
                           "break_index": event["index"], "structure_level": event["level"], "structure_pivot_index": event["pivot_index"],
                           "origin": event["origin"], "origin_index": origin_i, "extreme": extreme, "move_away": 0.0,
                           "stop": float(low[i-1] if side == "LONG" else high[i-1]),
                           "sr_aligned": bool(levels), "sr_level": float(levels[0]) if levels else None})
    return signals, features, stops, targets, reviews
