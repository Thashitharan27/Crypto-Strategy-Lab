"""Mapping-only Photon structure, premium/discount and supply/demand analysis.

The chart uses close-confirmed swing breaks without a preceding CHoCH gate.
Only close-confirmed swing breaks admit solid points.
The old two-sided pivot method remains available for legacy callers. Neither
method claims to resolve the presenter's discretionary meaningful-swing size.
No order, entry, stop or target is produced.
"""
from __future__ import annotations

from math import isfinite
from collections.abc import Mapping

MODE = "PHOTON_STRUCTURE_MAP"
LABEL = "Photon Market Structure — Parts 1 & 2 (mapping only)"
SWING_STRENGTH = 2
CONTEXT_DAYS = 730


def selected(profiles):
    if not isinstance(profiles, Mapping):
        return False
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


def aggregate_closed(bars, source_seconds=900, target_seconds=14400, offset=0):
    """UTC buckets; omit incomplete, duplicate, invalid or gapped buckets."""
    if target_seconds < source_seconds or target_seconds % source_seconds:
        raise ValueError("target timeframe must be a multiple of source timeframe")
    count = target_seconds // source_seconds
    buckets = {}
    for b in bars:
        start = (int(b["time"]) - offset) // target_seconds * target_seconds + offset
        buckets.setdefault(start, []).append(b)
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


def map_structure(bars, interval=900, strength=SWING_STRENGTH, qualification="PIVOT",
                  intrabars=None, intrabar_interval=900):
    """Forward-only snapshots. Historical pivots carry their confirmation time.

    Strict comparisons: equal prices are touches. An outside candle crossing
    both internal levels emits no CHoCH unless complete matching lower-timeframe
    candles establish distinct first-crossing times. These ordered events remain
    unavailable until the parent candle closes. Same-child crossings stay unknown.
    Internal pivots follow candle runs: a failure to extend the previous high
    (up run) or low (down run) starts the opposing run, including inside bars.
    Legacy PIVOT qualification needs `strength` bars on both sides. The chart's
    CHOCH_PULLBACK identifier is retained for saved callers, but no longer gates
    swing breaks on internal CHoCH. Protected points are promoted by a close
    beyond the existing swing level, tested before learning this candle's wick.
    """
    if qualification not in ("PIVOT", "CHOCH_PULLBACK"):
        raise ValueError("unknown swing qualification")
    if not isinstance(strength, int) or isinstance(strength, bool) or strength < 1:
        raise ValueError("swing strength must be a positive integer")
    events, snapshots, trace = [], [], []
    segment = 0
    high = low = ih = il = None
    high_ready = low_ready = False
    trend = internal = run = 0
    extreme = None
    last_break = -1
    previous_high = previous_low = None
    # Only complete source buckets whose OHLC matches the parent are evidence.
    # Index once; missing, duplicate or inconsistent source stays ambiguous.
    source_groups = {}
    source_parents = {}
    if intrabars is not None and intrabar_interval < interval:
        for child in intrabars:
            start = int(child["time"]) // interval * interval
            source_groups.setdefault(start, []).append(child)
        source_parents = {p["time"]: p for p in aggregate_closed(
            intrabars, intrabar_interval, interval)}

    def crossing_order(parent, upper, lower):
        aggregate = source_parents.get(parent["time"])
        if aggregate is None or any(aggregate[k] != parent[k] for k in ("open", "high", "low", "close")):
            return None
        first_up = first_down = None
        for child in source_groups[parent["time"]]:
            if first_up is None and child["high"] > upper["price"]:
                first_up = child["time"]
            if first_down is None and child["low"] < lower["price"]:
                first_down = child["time"]
        if first_up is None or first_down is None or first_up == first_down:
            return None
        return [1, -1] if first_up < first_down else [-1, 1]

    def point(index, kind):
        parent = bars[index]
        time = parent["time"]
        # Geometry may use an observed child wick time, but index and all
        # confirmation clocks remain tied to the completed parent candle.
        aggregate = source_parents.get(time)
        if qualification == "CHOCH_PULLBACK" and aggregate is not None and all(
                aggregate[k] == parent[k] for k in ("open", "high", "low", "close")):
            time = next(c["time"] for c in source_groups[time]
                        if c[kind] == parent[kind])
        return {"index": index, "time": time, "price": parent[kind]}

    def emit(kind, direction, p, at, label=None):
        events.append(dict(kind=kind, direction=direction, price=p["price"],
                           time=at - interval, fromTime=p["time"], availableAt=at, label=label or kind))
        if p["time"] != bars[p["index"]]["time"]:
            events[-1]["fromParentTime"] = bars[p["index"]]["time"]

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
            trace.append(dict(kind="GAP", time=b["time"], availableAt=at))
        if not valid_bar(b):
            snapshots.append(dict(availableAt=at, trend=0, internal=0, high=None, low=None, phase="UNKNOWN"))
            continue

        # Test existing levels before learning any pivots from this candle.
        up = ih is not None and b["high"] > ih["price"]
        down = il is not None and b["low"] < il["price"]
        order = crossing_order(b, ih, il) if up and down and qualification == "CHOCH_PULLBACK" else None
        if up and down:
            if order is None:
                emit("AMBIGUOUS", 0, ih, at, "Both internal levels crossed; intrabar order unknown")
            else:
                for direction in order:
                    if internal != direction:
                        internal = direction
                        emit("CHOCH", direction, ih if direction == 1 else il, at)
                        events[-1]["orderBasis"] = "LOWER_TIMEFRAME"
                        events[-1]["sourceInterval"] = intrabar_interval
        elif up and internal != 1:
            internal = 1
            emit("CHOCH", 1, ih, at)
        elif down and internal != -1:
            internal = -1
            emit("CHOCH", -1, il, at)

        if qualification == "CHOCH_PULLBACK":
            # Retire penetrated references even when the break continued the
            # existing internal direction. Otherwise an already-broken low can
            # falsely make a later bullish break look like a two-sided sweep.
            if up:
                ih = None
            if down:
                il = None
            if up and down and order is None:
                internal = 0

        range_known = high is not None and low is not None and high["price"] > low["price"]
        up = range_known and (qualification == "CHOCH_PULLBACK" or high_ready) and b["close"] > high["price"]
        down = range_known and (qualification == "CHOCH_PULLBACK" or low_ready) and b["close"] < low["price"]
        if up or down:
            direction = 1 if up else -1
            broken = high if up else low
            prior = low if up else high
            kind = "TREND_CHANGE" if trend and direction != trend else "BOS"
            emit(kind, direction, broken, at)
            # The pullback begins AFTER the candle that set the broken level.
            # Its opposite wick may predate that extreme and is not evidence
            # of the following pullback. Including it creates false protected
            # levels and duplicate high/low anchors at the same timestamp.
            start = max(segment, broken["index"] + 1)
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
            # Only a close-confirmed swing break admits points to the solid
            # structural zigzag: the level broken, then the origin that broke it.
            trace.extend([
                dict(kind="BOS_SWING", direction=direction, fromTime=broken["time"],
                     price=broken["price"], availableAt=at, confirmedBy=kind),
                dict(kind="BOS_SWING", direction=-direction, fromTime=protected["time"],
                     price=protected["price"], availableAt=at, confirmedBy=kind),
            ])
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
        if trend == 1 and (qualification == "CHOCH_PULLBACK" or not high_ready) and b["high"] > high["price"]:
            high = point(i, "high")
        if trend == -1 and (qualification == "CHOCH_PULLBACK" or not low_ready) and b["low"] < low["price"]:
            low = point(i, "low")
        j = i - strength
        if qualification == "PIVOT" and j - strength >= segment:
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
                    if qualification == "CHOCH_PULLBACK" and not internal:
                        internal = run
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
        if qualification == "CHOCH_PULLBACK" and trend == 0:
            # Seed from observed internal runs, rather than an arbitrary number
            # of bars either side. A close through this range establishes trend.
            if ih is not None:
                high, high_ready = dict(ih), True
            if il is not None:
                low, low_ready = dict(il), True
        phase = "UNKNOWN" if not trend or not internal else "POSSIBLE_CONTINUATION" if trend == internal else "POSSIBLE_PULLBACK"
        snapshots.append(dict(availableAt=at, close=b["close"], trend=trend, internal=internal,
                              high=dict(high, strong=trend == -1, confirmed=high_ready) if high else None,
                              low=dict(low, strong=trend == 1, confirmed=low_ready) if low else None, phase=phase))
        s = snapshots[-1]
        s["internalHigh"] = dict(ih) if ih else None
        s["internalLow"] = dict(il) if il else None
        if qualification == "CHOCH_PULLBACK":
            for key in ("high", "low"):
                if s[key]:
                    s[key]["eligible"] = True
                    s[key]["confirmed"] = s[key]["strong"]
            weak = high if trend == 1 else low if trend == -1 else None
            s["developing"] = [dict(weak)] if weak else []
            if weak and weak["index"] < i:
                # The weak extreme and latest close describe run + reaction;
                # neither becomes a solid anchor until a swing break proves it.
                s["developing"].append(dict(time=b["time"], price=b["close"], index=i))
    return dict(events=events, trace=trace, traceBasis="BOS_CONFIRMED", snapshots=snapshots,
                interval=interval, qualification=qualification,
                swingBreakRule="CLOSE_ONLY" if qualification == "CHOCH_PULLBACK" else "PIVOT_CLOSE")


def build_mapping(bars, detail_start=None):
    from crypto_strategy_lab.photon_zones import attach_ranges, build_zones

    frames = {"15m": (900, 0), "4h": (14400, 0), "1d": (86400, 0),
              "1w": (604800, 345600)}  # Monday 00:00 UTC (Unix epoch was Thursday).
    detail = bars if detail_start is None else [b for b in bars if b["time"] >= detail_start]
    timeframes = {}
    for tf, (seconds, offset) in frames.items():
        native = detail if tf == "15m" else aggregate_closed(
            detail if tf == "4h" else bars, target_seconds=seconds, offset=offset)
        guide = map_structure(native, seconds, qualification="CHOCH_PULLBACK",
                              intrabars=detail if tf == "4h" else None)
        attach_ranges(guide)
        if tf != "1w":
            guide["supplyDemand"] = build_zones(detail if tf in ("15m", "4h") else bars, native, guide, tf)
        timeframes[tf] = guide
    return dict(strategy=MODE, mappingOnly=True, schemaVersion=2, contextDays=CONTEXT_DAYS,
                lessons=["Market structure", "Multi-timeframe structure", "Premium/discount and supply/demand"],
                qualification="Swing breaks require a close beyond the existing swing level; no preceding internal CHoCH is required. CHoCH remains separate internal-phase evidence. Experimental mapping for visual review.",
                timeframes=timeframes)
