"""Direct 4H premium/discount limits using only completed structure snapshots."""
from copy import deepcopy
from math import isfinite

import pandas as pd

from .photon_structure import aggregate_closed, map_structure, valid_bar
from .photon_zones import attach_ranges


def prepare_quarter_context(bars):
    native = aggregate_closed(bars, 60, 14400, 0)
    guide = map_structure(native, 14400, qualification="CHOCH_PULLBACK")
    attach_ranges(guide)
    return {"4h": guide}


def quarter_range_setups(bars, atr_values, guides, *, stop_buffer_atr=.05, minimum_r=1.):
    from .photon_trend import MODE, resolve_retest

    if len(bars) != len(atr_values):
        raise ValueError("Photon ATR must align with 1m candles")
    if not isfinite(stop_buffer_atr) or stop_buffer_atr < 0 or not isfinite(minimum_r) or minimum_r <= 0:
        raise ValueError("Invalid quarter-range stop buffer or minimum R")
    if any(bars[i]['time'] <= bars[i-1]['time'] for i in range(1, len(bars))):
        raise ValueError("Photon requires unique increasing 1m timestamps")
    guide = guides['4h']
    snapshots = iter(guide.get('snapshots', ()))
    upcoming = next(snapshots, None)
    state = pending = None
    used = set()
    signals, live = [None]*len(bars), [None]*len(bars)
    iso = lambda t: pd.Timestamp(t, unit='s', tz='UTC').isoformat()
    for i, bar in enumerate(bars):
        at = bar['time']+60
        if not valid_bar(bar) or i > 0 and bar['time']-bars[i-1]['time'] != 60:
            pending = None
        if not valid_bar(bar):
            continue
        # The order was already public at the preceding close. Its outcome
        # is used only to prevent another order, never to create a past fill.
        if pending and resolve_retest(pending, bar)[0] != 'WAITING':
            pending = None
        while upcoming is not None and upcoming['availableAt'] <= at:
            state = upcoming
            upcoming = next(snapshots, None)
        bounds = state.get('range') if state and at < state['availableAt']+14400 else None
        sign = state.get('trend', 0) if bounds else 0
        key = (sign, bounds['lowTime'], bounds['low'], bounds['highTime'], bounds['high']) if sign in (-1, 1) else None
        if pending and pending['rangeKey'] != key:
            pending = None
        if pending:
            live[i] = pending['signalIndex']
            continue
        if key is None or key in used:
            continue
        low, high = bounds['low'], bounds['high']
        if not isfinite(low) or not isfinite(high) or low <= 0 or high <= low:
            continue
        entry = low+(high-low)*(.25 if sign == 1 else .75)
        # Arm only while price is on the approach side of the limit.
        if sign*(bar['close']-entry) <= 0:
            continue
        atr = float(atr_values[i])
        if not isfinite(atr) or atr <= 0:
            continue
        boundary = low if sign == 1 else high
        stop = boundary-sign*stop_buffer_atr*atr
        target = high if sign == 1 else low
        risk, reward = sign*(entry-stop), sign*(target-entry)
        if stop <= 0 or risk <= 0 or reward/risk < minimum_r:
            continue
        zone = dict(bottom=low, top=high, pivotTime=iso(bounds['lowTime']),
                    confirmedTime=iso(at), touchTime=None, bounceTime=None)
        pending = dict(version=1, strategy=MODE, side='LONG' if sign == 1 else 'SHORT',
                       entry=entry, stop=stop, target=target, entryModel='QUARTER_RANGE',
                       entryExecution='LIMIT_RETEST', stopSource='4H_STRONG_BOUNDARY',
                       signalTime=iso(bar['time']), signalAvailableAt=at, signalIndex=i,
                       rangeKey=key, range4h=deepcopy(bounds), range15m=None,
                       target4h=target, targetMode='4H_SWING', entryPercent=25 if sign == 1 else 75,
                       zone=zone, entryZone=None, opposingZone=None,
                       review=dict(status='PASSED', checks=[], mismatches=[]),
                       narrative={'4h': dict(trend=sign, availableAt=state['availableAt'])})
        signals[i] = deepcopy(pending)
        live[i] = i
        used.add(key)
    return signals, live
