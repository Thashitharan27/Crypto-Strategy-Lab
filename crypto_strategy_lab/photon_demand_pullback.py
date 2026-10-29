"""Long-only, closed-candle 4H/15m demand pullback research option."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite
import pandas as pd
from .photon_structure import valid_bar


def demand_pullback_setups(bars, atr_values, guides, *, confirmation_minutes=1440,
                          stop_buffer_atr=.05, minimum_r=1.):
    from .photon_trend import MODE, validate_settings
    validate_settings(confirmation_minutes, 1)
    if len(bars) != len(atr_values):
        raise ValueError('Photon ATR must align with 1m candles')
    if not isfinite(stop_buffer_atr) or stop_buffer_atr < 0 or not isfinite(minimum_r) or minimum_r <= 0:
        raise ValueError('Invalid Photon stop buffer / minimum R')
    if any(bars[i]['time'] <= bars[i-1]['time'] for i in range(1, len(bars))):
        raise ValueError('Photon requires unique increasing 1m timestamps')
    streams = {tf: iter(g.get('snapshots', ())) for tf, g in guides.items()}
    upcoming = {tf: next(it, None) for tf, it in streams.items()}
    state, zones = {}, {}
    updates, changes = defaultdict(list), defaultdict(list)
    for z in guides['15m'].get('supplyDemand', {}).get('zones', ()):
        updates[z['availableAt']].append(('CREATE', z))
    for e in guides['15m'].get('supplyDemand', {}).get('events', ()):
        updates[e['availableAt']].append(('UPDATE', e))
    for e in guides['15m'].get('events', ()):
        if e['kind'] == 'TREND_CHANGE':
            changes[e['availableAt']].append(e)
    signals, live = [None]*len(bars), [None]*len(bars)
    campaign = None
    previous_internal = 0
    iso = lambda t: pd.Timestamp(t, unit='s', tz='UTC').isoformat()
    for i, b in enumerate(bars):
        at = b['time']+60
        if not valid_bar(b) or i and b['time'] != bars[i-1]['time']+60:
            campaign = None
            zones.clear()
            state.clear()
            previous_internal = 0
        if not valid_bar(b):
            continue
        # Touches must use zones known before this minute opened.
        touches = [z for z in zones.values() if z['kind'] == 'DEMAND'
                   and b['low'] <= z['upper'] and b['high'] >= z['lower']]
        for tf, stream in streams.items():
            while upcoming[tf] is not None and upcoming[tf]['availableAt'] <= at:
                state[tf] = upcoming[tf]
                upcoming[tf] = next(stream, None)
        for action, item in updates[at]:
            if action == 'CREATE':
                zones[item['id']] = item
            elif item['kind'] in ('INVALIDATED', 'RETIRED'):
                zones.pop(item['zoneId'], None)
        current = {tf: s for tf, s in state.items()
                   if at < s['availableAt']+guides[tf]['interval']}
        h, m, minute = (current.get(tf) for tf in ('4h', '15m', '1m'))
        internal = minute.get('internal', 0) if minute else 0
        prior = previous_internal
        previous_internal = internal
        if not h or h['trend'] != 1 or not m or m['trend'] != 1 or not m.get('range') or not minute:
            campaign = None
            continue
        if any(e['direction'] == 1 for e in changes[at]):
            campaign = dict(alignmentAt=at, parent=None, bearish=False)
            continue
        if campaign is None:
            continue
        if at-campaign['alignmentAt'] > confirmation_minutes*60:
            campaign = None
            continue
        campaign['bearish'] |= internal == -1
        if campaign['parent'] is None:
            eligible = [z for z in touches if z['id'] in zones
                        and b['low'] > z['lower']-stop_buffer_atr*float(atr_values[i])]
            if eligible and at > campaign['alignmentAt']:
                parent = max(eligible, key=lambda z: (z['availableAt'], z['id']))
                campaign.update(parent=deepcopy(parent), touchAt=at,
                                touchTime=b['time'], touchHigh=b['high'])
            continue
        parent = campaign['parent']
        if parent['id'] not in zones or b['low'] < parent['lower']:
            campaign = None
            continue
        if at <= campaign['touchAt']:
            continue
        # Bearish pullbacks need a new bullish internal shift. A continuously
        # bullish 1m trend instead needs an observable upward departure.
        returned = (internal == 1 and prior == -1 if campaign['bearish'] else
                    internal == 1 and b['close'] > campaign['touchHigh'])
        if not returned or b['close'] <= parent['upper']:
            continue
        av = float(atr_values[i])
        if not isfinite(av) or av <= 0:
            continue
        entry = b['close']
        stop = parent['lower']-stop_buffer_atr*av
        target = m['range']['equilibrium']
        risk, reward = entry-stop, target-entry
        if stop <= 0 or risk <= 0 or reward <= 0 or reward/risk < minimum_r:
            continue
        zone = dict(bottom=parent['lower'], top=parent['upper'],
                    pivotTime=iso(parent.get('originTime', parent['availableAt'])),
                    confirmedTime=iso(parent['availableAt']), touchTime=iso(campaign['touchTime']),
                    bounceTime=iso(b['time']))
        signals[i] = dict(version=1, strategy=MODE, side='LONG',
            entryModel='15M_DEMAND_PULLBACK', entryExecution='MARKET_NEXT_OPEN',
            entry=entry, stop=stop, target=target, stopSource='15M_ZONE',
            stopBoundary=parent['lower'], signalIndex=i, signalTime=iso(b['time']),
            signalAvailableAt=at, expiresAt=at+60,
            alignmentAt=campaign['alignmentAt'], parentTouchAt=campaign['touchAt'],
            parentZone=deepcopy(parent), contextZone=deepcopy(parent),
            zone=zone, entryZone=deepcopy(zone),
            opposingZone=dict(bottom=target, top=target, pivotTime=iso(m['availableAt']),
                              confirmedTime=iso(m['availableAt'])),
            range4h=deepcopy(h.get('range')), range15m=deepcopy(m['range']),
            targetMode='15M_MIDPOINT', target4h=(h.get('range') or {}).get('equilibrium'),
            returnModel='BEARISH_TO_BULLISH' if campaign['bearish'] else 'BULLISH_BOUNCE',
            review=dict(status='PREFERRED_ALIGNMENT', checks=[], mismatches=[]),
            narrative={tf: dict(trend=s['trend'], internal=s.get('internal', 0),
                                availableAt=s['availableAt']) for tf, s in current.items()})
        live[i] = i
        campaign = None
    return signals, live
