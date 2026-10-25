"""Mapping-only interpretation of Photon market structure Parts 1 and 2.

No order, entry, stop or target is produced. Swing qualification is explicitly
our two-sided pivot interpretation, not a rule specified by the videos.
"""
from __future__ import annotations

from math import isfinite

MODE = "PHOTON_STRUCTURE_MAP"
LABEL = "Photon Market Structure — Parts 1 & 2 (mapping only)"
SWING_STRENGTH = 2


def selected(profiles):
    return any(
        rule.get("_strategy_direction_mode") == MODE
        for profile in profiles.values()
        for rule in getattr(profile, "entry_rules", ())
    )


class PhotonStructureMixin:
    """Hard entry gate, including direct opening and scheduled-entry paths."""

    def _infer_signal_strategy_mode(self):
        if selected(self.config.strategy_profiles):
            return MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self, i):
        if self.signal_strategy_mode == MODE:
            return None
        return super()._selected_direction(i)

    def _should_enter(self, i):
        if self.signal_strategy_mode == MODE:
            return False
        return super()._should_enter(i)

    def _open_pair(self, *args, **kwargs):
        if self.signal_strategy_mode == MODE:
            return None
        return super()._open_pair(*args, **kwargs)


def aggregate_closed(bars, source_seconds=900, target_seconds=14400):
    """UTC buckets; omit incomplete, duplicate, invalid or gapped buckets."""
    if target_seconds < source_seconds or target_seconds % source_seconds:
        raise ValueError("target timeframe must be a multiple of source timeframe")
    count = target_seconds // source_seconds
    buckets = {}
    for b in bars:
        buckets.setdefault(int(b["time"]) // target_seconds * target_seconds, []).append(b)
    result = []
    for start, group in sorted(buckets.items()):
        if len(group) != count or [b["time"] for b in group] != [start + i * source_seconds for i in range(count)]:
            continue
        if not all(valid_bar(b) for b in group):
            continue
        result.append(dict(time=start, open=group[0]["open"], high=max(b["high"] for b in group),
                           low=min(b["low"] for b in group), close=group[-1]["close"]))
    return result


def valid_bar(b):
    return (all(isfinite(b[k]) for k in ("time", "open", "high", "low", "close"))
            and b["low"] <= min(b["open"], b["close"])
            and b["high"] >= max(b["open"], b["close"]))


def map_structure(bars, interval=900, strength=SWING_STRENGTH):
    """Forward-only snapshots. Historical pivots carry their confirmation time.

    Strict comparisons: equal prices are touches. An outside candle crossing
    both internal levels has unknown intrabar order and emits no CHoCH.
    Internal pivots follow candle runs: a failure to extend the previous high
    (up run) or low (down run) starts the opposing run, including inside bars.
    Swing pivots need `strength` bars on both sides; protected points are only
    promoted by a close beyond the opposing qualified swing level.
    """
    if not isinstance(strength, int) or isinstance(strength, bool) or strength < 1:
        raise ValueError("swing strength must be a positive integer")
    events, snapshots = [], []
    segment = 0
    high = low = ih = il = None
    high_ready = low_ready = False
    trend = internal = run = 0
    extreme = None
    last_break = -1
    previous_high = previous_low = None

    def point(index, kind):
        return {"index": index, "time": bars[index]["time"], "price": bars[index][kind]}

    def emit(kind, direction, p, at, label=None):
        events.append(dict(kind=kind, direction=direction, price=p["price"],
                           time=at - interval, fromTime=p["time"], availableAt=at, label=label or kind))

    for i, b in enumerate(bars):
        at = b["time"] + interval
        if not valid_bar(b) or (i and b["time"] - bars[i-1]["time"] != interval):
            high = low = ih = il = None
            high_ready = low_ready = False
            trend = internal = run = 0
            extreme = None
            segment = i if valid_bar(b) else i + 1
            last_break = -1
            previous_high = previous_low = None
            events.append(dict(kind="GAP", time=b["time"], availableAt=at, label="Structure reset: data gap"))
        if not valid_bar(b):
            snapshots.append(dict(availableAt=at, trend=0, internal=0, high=None, low=None, phase="UNKNOWN"))
            continue

        # Test existing levels before learning any pivots from this candle.
        up = ih is not None and b["high"] > ih["price"]
        down = il is not None and b["low"] < il["price"]
        if up and down:
            emit("AMBIGUOUS", 0, ih, at, "Both internal levels crossed; intrabar order unknown")
        elif up and internal != 1:
            internal = 1
            emit("CHOCH", 1, ih, at)
        elif down and internal != -1:
            internal = -1
            emit("CHOCH", -1, il, at)

        range_known = high is not None and low is not None and high["price"] > low["price"]
        up = range_known and high_ready and b["close"] > high["price"]
        down = range_known and low_ready and b["close"] < low["price"]
        if up or down:
            direction = 1 if up else -1
            broken = high if up else low
            prior = low if up else high
            kind = "TREND_CHANGE" if trend and direction != trend else "BOS"
            emit(kind, direction, broken, at)
            start = max(segment, broken["index"])
            key = "low" if up else "high"
            origin = min(range(start, i+1), key=lambda k: bars[k]["low"]) if up else max(range(start, i+1), key=lambda k: bars[k]["high"])
            protected = point(origin, key)
            if prior is None:
                label = "L" if up else "H"
            elif up:
                label = "HL" if protected["price"] > prior["price"] else "LL" if protected["price"] < prior["price"] else "EL"
            else:
                label = "HH" if protected["price"] > prior["price"] else "LH" if protected["price"] < prior["price"] else "EH"
            emit("SWING", direction, protected, at, label)
            if up:
                previous_high = broken["price"]
                low, low_ready = protected, True
                high, high_ready = point(i, "high"), False
            else:
                previous_low = broken["price"]
                high, high_ready = protected, True
                low, low_ready = point(i, "low"), False
            trend, last_break = direction, i

        # Track the developing weak extreme without calling it confirmed.
        if trend == 1 and not high_ready and b["high"] > high["price"]:
            high = point(i, "high")
        if trend == -1 and not low_ready and b["low"] < low["price"]:
            low = point(i, "low")
        j = i - strength
        if j - strength >= segment:
            for key in ("high", "low"):
                price = bars[j][key]
                qualifies = all(price > bars[k][key] if key == "high" else price < bars[k][key]
                                for k in range(j-strength, i+1) if k != j)
                if not qualifies:
                    continue
                p = point(j, key)
                if key == "high" and (trend == 0 or (trend == 1 and not high_ready and j >= last_break and price == high["price"])):
                    previous = previous_high if trend else high["price"] if high else None
                    high, high_ready = p, True
                    label = "H" if previous is None else "HH" if price > previous else "LH" if price < previous else "EH"
                    emit("PIVOT", 1, p, at, label)
                if key == "low" and (trend == 0 or (trend == -1 and not low_ready and j >= last_break and price == low["price"])):
                    previous = previous_low if trend else low["price"] if low else None
                    low, low_ready = p, True
                    label = "L" if previous is None else "HL" if price > previous else "LL" if price < previous else "EL"
                    emit("PIVOT", -1, p, at, label)

        if i > segment:
            previous = bars[i-1]
            outside = b["high"] > previous["high"] and b["low"] < previous["low"]
            if not outside:
                if run == 0:
                    run = 1 if b["high"] > previous["high"] else -1 if b["low"] < previous["low"] else 0
                    extreme = point(i, "high" if run == 1 else "low") if run else None
                elif run == 1:
                    if b["high"] > previous["high"]:
                        if b["high"] > extreme["price"]:
                            extreme = point(i, "high")
                    else:
                        ih, run, extreme = extreme, -1, point(i, "low")
                else:
                    if b["low"] < previous["low"]:
                        if b["low"] < extreme["price"]:
                            extreme = point(i, "low")
                    else:
                        il, run, extreme = extreme, 1, point(i, "high")
        phase = "UNKNOWN" if not trend or not internal else "POSSIBLE_CONTINUATION" if trend == internal else "POSSIBLE_PULLBACK"
        snapshots.append(dict(availableAt=at, trend=trend, internal=internal,
                              high=dict(high, strong=trend == -1, confirmed=high_ready) if high else None,
                              low=dict(low, strong=trend == 1, confirmed=low_ready) if low else None, phase=phase))
    return dict(events=events, snapshots=snapshots, interval=interval)


def build_mapping(bars):
    return dict(strategy=MODE, mappingOnly=True, swingStrength=SWING_STRENGTH,
                qualification="Two bars on each side qualify swing pivots; implementation interpretation, not specified in the videos.",
                timeframes={"15m": map_structure(bars), "4h": map_structure(aggregate_closed(bars), 14400)})
