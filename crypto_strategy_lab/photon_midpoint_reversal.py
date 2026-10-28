"""Fresh 15m trend changes in 4H value, with at least 1R to equilibrium."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite

import pandas as pd

from .photon_structure import aggregate_closed, map_structure, valid_bar
from .photon_zones import attach_ranges


def prepare_midpoint_context(bars):
    guides = {}
    for tf, seconds in (('4h', 14400), ('15m', 900)):
        guide = map_structure(aggregate_closed(bars, 60, seconds, 0), seconds,
                              qualification='CHOCH_PULLBACK')
        attach_ranges(guide)
        guides[tf] = guide
    return guides


def midpoint_reversal_setups(bars, guides, *, minimum_r=1., fixed_1r=False):
    from .photon_trend import MODE
    if not isfinite(minimum_r) or minimum_r < 1:
        raise ValueError('Midpoint reversal requires at least 1R')
    if any(bars[i]['time'] <= bars[i-1]['time'] for i in range(1, len(bars))):
        raise ValueError('Photon requires unique increasing 1m timestamps')
    events = defaultdict(list)
    for event in guides['15m'].get('events', ()):
        if event['kind'] == 'TREND_CHANGE':
            events[event['availableAt']].append(event)
    snapshots = iter(guides['4h'].get('snapshots', ()))
    upcoming = next(snapshots, None)
    state = None
    signals, live = [None]*len(bars), [None]*len(bars)
    iso = lambda t: pd.Timestamp(t, unit='s', tz='UTC').isoformat()
    for i, bar in enumerate(bars):
        at = bar['time']+60
        while upcoming is not None and upcoming['availableAt'] <= at:
            state = upcoming
            upcoming = next(snapshots, None)
        if not valid_bar(bar) or i > 0 and bar['time']-bars[i-1]['time'] != 60:
            continue
        if not state or at >= state['availableAt']+14400:
            continue
        bounds, sign = state.get('range'), state.get('trend', 0)
        if not bounds or sign not in (-1, 1):
            continue
        change = next((e for e in events.get(at, ()) if e['direction'] == sign), None)
        if change is None:
            continue
        low, high, target, entry = bounds['low'], bounds['high'], bounds['equilibrium'], bar['close']
        if not all(isfinite(v) for v in (low, high, target, entry)) or not 0 < low < high:
            continue
        stop = low if sign == 1 else high
        risk, reward = sign*(entry-stop), sign*(target-entry)
        if not low < entry < high or risk <= 0 or reward <= 0 or reward/risk < minimum_r:
            continue
        # One immediate market attempt for EACH fresh 15m change. There is no
        # range-level deduplication and no persistent/retested order.
        zone = dict(bottom=low, top=high, pivotTime=iso(bounds['lowTime']),
                    confirmedTime=iso(at), touchTime=iso(bar['time']), bounceTime=None)
        signals[i] = dict(version=1, strategy=MODE, side='LONG' if sign == 1 else 'SHORT',
                          entry=entry, stop=stop, target=entry+sign*risk if fixed_1r else target,
                          entryModel='MIDPOINT_15M_REVERSAL', entryExecution='MARKET_OPEN',
                          stopSource='4H_STRONG_BOUNDARY', signalIndex=i,
                          signalTime=iso(bar['time']), signalAvailableAt=at,
                          alignmentAt=at, trendChange15m=deepcopy(change),
                          range4h=deepcopy(bounds), range15m=None,
                          target4h=target, targetMode='FIXED_1R_BEFORE_MIDPOINT' if fixed_1r else '4H_MIDPOINT',
                          zone=zone, entryZone=None, opposingZone=None,
                          minimumR=minimum_r, plannedR=1. if fixed_1r else reward/risk, midpointRoomR=reward/risk,
                          review=dict(status='PASSED', checks=[], mismatches=[]),
                          narrative={'4h': dict(trend=sign, availableAt=state['availableAt'])})
        live[i] = i
    return signals, live
