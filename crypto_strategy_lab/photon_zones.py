"""Causal premium/discount ranges and mapping-only supply/demand references.

Zone boundaries are an explicit mechanical choice: the full wick range of the
last opposing-body candle in the originating swing leg, before a close-confirmed
structural break. These references are not orders or claims about profitability.
"""
from collections import defaultdict


def range_position(price, bounds):
    if bounds is None or price is None:
        return "UNKNOWN"
    if price < bounds["low"]:
        return "BELOW_RANGE"
    if price > bounds["high"]:
        return "ABOVE_RANGE"
    return "DISCOUNT" if price < bounds["equilibrium"] else "PREMIUM" if price > bounds["equilibrium"] else "EQ"


def zone_location(lower, upper, bounds):
    if bounds is None:
        return "UNKNOWN"
    eq = bounds["equilibrium"]
    return "DISCOUNT" if upper < eq else "PREMIUM" if lower > eq else "EQ" if lower == upper == eq else "STRADDLES_EQ"


def attach_ranges(guide):
    """Snapshot each evolving range as known then; never use a future endpoint."""
    key = known_at = None
    for state in guide["snapshots"]:
        high, low = state.get("high"), state.get("low")
        if not state["trend"] or not high or not low or high["price"] <= low["price"]:
            state["range"] = None
            key = known_at = None
            continue
        next_key = (low["time"], low["price"], high["time"], high["price"])
        if next_key != key:
            key, known_at = next_key, state["availableAt"]
        weak = high if state["trend"] == 1 else low
        bounds = dict(low=low["price"], high=high["price"],
                      equilibrium=(low["price"]+high["price"])/2,
                      lowTime=low["time"], highTime=high["time"], knownAt=known_at,
                      status="CLOSE_BREAK_PENDING" if guide.get("swingBreakRule") == "CLOSE_ONLY"
                      else "PULLBACK_CANDIDATE" if weak.get("eligible") else "DEVELOPING")
        bounds["position"] = range_position(state.get("close"), bounds)
        state["range"] = bounds


def build_zones(source, native, guide, timeframe, source_interval=900):
    """Immutable origins plus replay-filtered lifecycle events.

Touches are detected on completed canonical 15m bars after creation; invalidation
requires the zone's OWN timeframe close beyond the far edge. Gap retirement is
separate from price invalidation. Consecutive bars inside a zone are one visit.
"""
    from crypto_strategy_lab.photon_structure import valid_bar

    interval = guide["interval"]
    indices = {bar["time"]: i for i, bar in enumerate(native)}
    native_closes = {bar["time"]+interval: bar for bar in native}
    snapshots = {s["availableAt"]: s for s in guide["snapshots"]}
    origins = {e["availableAt"]: e for e in guide["events"] if e["kind"] == "SWING"}
    zones, changes, births, seen = [], [], defaultdict(list), set()
    for event in guide["events"]:
        if event["kind"] not in ("BOS", "TREND_CHANGE"):
            continue
        origin = origins.get(event["availableAt"])
        if origin is None:
            continue
        start, end = indices.get(origin.get("fromParentTime", origin["fromTime"])), indices.get(event["time"])
        if start is None or end is None:
            continue
        direction = event["direction"]
        candidates = [i for i in range(start, end) if
                      (native[i]["close"] < native[i]["open"] if direction == 1
                       else native[i]["close"] > native[i]["open"])]
        if not candidates:
            continue
        candle = native[candidates[-1]]
        lower, upper = candle["low"], candle["high"]
        # A break must have departed the selected origin, not still be inside it.
        if upper <= lower or not (native[end]["close"] > upper if direction == 1 else native[end]["close"] < lower):
            continue
        kind = "DEMAND" if direction == 1 else "SUPPLY"
        identity = f"{timeframe}:{kind}:{candle['time']}"
        if identity in seen:
            continue
        seen.add(identity)
        bounds = snapshots[event["availableAt"]].get("range")
        zone = dict(id=identity, timeframe=timeframe, kind=kind, lower=lower, upper=upper,
                    originTime=candle["time"], availableAt=event["availableAt"],
                    breakTime=event["time"], brokenLevel=event["price"], confirmedBy=event["kind"],
                    creationRange=dict(bounds) if bounds else None,
                    creationLocation=zone_location(lower, upper, bounds))
        zones.append(zone)
        births[zone["availableAt"]].append(zone)

    return zone_lifecycle(source, native, guide, zones, source_interval)


def zone_lifecycle(source, native, guide, zones, source_interval=900):
    """Shared causal lifecycle for legacy and lesson-derived zone origins."""
    if any('lessonModel' in z for z in zones):
        from .photon_lesson import indexed_lifecycle
        return indexed_lifecycle(source,native,guide,zones,source_interval)
    from .photon_structure import valid_bar
    native_closes = {bar['time']+guide['interval']: bar for bar in native}
    births = defaultdict(list)
    for zone in zones:
        births[zone['availableAt']].append(zone)
    changes = []
    active, inside = {}, set()
    previous_time = None
    for candle in source:
        at = candle["time"]+source_interval
        valid = valid_bar(candle)
        gap = not valid or previous_time is not None and candle["time"]-previous_time != source_interval
        if gap:
            for zone_id in active:
                changes.append(dict(zoneId=zone_id, kind="RETIRED", reason="DATA_GAP", availableAt=at))
            active.clear()
            inside.clear()
        previous_time = candle["time"]
        if not valid:
            continue
        own_close = native_closes.get(at)
        for zone_id, zone in list(active.items()):
            invalid = own_close is not None and (own_close["close"] < zone["lower"] if zone["kind"] == "DEMAND" else own_close["close"] > zone["upper"])
            overlap = candle["high"] >= zone["lower"] and candle["low"] <= zone["upper"]
            if overlap and zone_id not in inside:
                changes.append(dict(zoneId=zone_id, kind="TOUCHED", availableAt=at,
                                    candleTime=candle["time"]))
            if overlap:
                inside.add(zone_id)
            else:
                inside.discard(zone_id)
            if invalid:
                changes.append(dict(zoneId=zone_id, kind="INVALIDATED", availableAt=at,
                                    close=own_close["close"], candleTime=own_close["time"]))
                active.pop(zone_id)
                inside.discard(zone_id)
        # Creation candle cannot retrospectively touch/invalidate its own zone.
        for zone in births.get(at, ()):
            active[zone["id"]] = zone
    return dict(zones=zones, events=changes,
                rule="Full wick range of the last opposing-body candle within the originating swing leg before BOS / swing change; close must leave the origin range.")
