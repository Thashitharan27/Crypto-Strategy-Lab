"""Causal Daily/4H zone reversal entries; all decisions use completed candles."""
# Frozen from 1739f4b7 for historical run reproduction (68c5fa4f).
# Keep this model separate so later changes cannot silently alter saved reruns.
from collections import defaultdict
from copy import deepcopy
from math import isfinite

import pandas as pd

from .photon_structure import valid_bar


def zone_reversal_setups(bars, atr_values, guides, *, confirmation_minutes=1440,
                        stop_buffer_atr=.05, minimum_r=1.):
    from .photon_trend import MODE, validate_settings
    validate_settings(confirmation_minutes, 1)
    if len(bars) != len(atr_values):
        raise ValueError("Photon ATR must align with 1m candles")
    if not isfinite(minimum_r) or minimum_r <= 0 or not isfinite(stop_buffer_atr) or stop_buffer_atr < 0:
        raise ValueError("Photon stop buffer and minimum R must be finite and non-negative / positive")
    if any(bars[i]['time'] <= bars[i-1]['time'] for i in range(1, len(bars))):
        raise ValueError("Photon requires unique increasing 1m timestamps")
    snapshots = {tf: iter(g.get('snapshots', ())) for tf, g in guides.items()}
    upcoming = {tf: next(it, None) for tf, it in snapshots.items()}
    state, zones = {}, {}
    updates, changes = defaultdict(list), defaultdict(list)
    for tf, guide in guides.items():
        for z in guide.get('supplyDemand', {}).get('zones', ()):
            updates[z['availableAt']].append(('CREATE', z))
        for e in guide.get('supplyDemand', {}).get('events', ()):
            updates[e['availableAt']].append(('UPDATE', e))
        if tf == '15m':
            for e in guide.get('events', ()):
                if e['kind'] == 'TREND_CHANGE':
                    changes[e['availableAt']].append(e)
    signals, live = [None]*len(bars), [None]*len(bars)
    campaign = None
    # One campaign per continuous visit, not repeated entries while inside a zone.
    inside = set()
    iso = lambda t: pd.Timestamp(t, unit='s', tz='UTC').isoformat()
    for i, b in enumerate(bars):
        at = b['time']+60
        gap = not valid_bar(b) or i > 0 and b['time']-bars[i-1]['time'] != 60
        if gap:
            campaign = None
            zones.clear()
            inside.clear()
        if not valid_bar(b):
            continue
        # A candle can only touch zones already known when it opened.
        touches = {k for k, z in zones.items() if b['high'] >= z['lower'] and b['low'] <= z['upper']}
        new_visits = touches-inside
        for tf, it in snapshots.items():
            while upcoming[tf] is not None and upcoming[tf]['availableAt'] <= at:
                state[tf] = upcoming[tf]
                upcoming[tf] = next(it, None)
        for action, item in updates[at]:
            if action == 'CREATE':
                zones[item['id']] = item
            elif item['kind'] in ('INVALIDATED', 'RETIRED'):
                zones.pop(item['zoneId'], None)
        inside = touches.intersection(zones)
        current = {tf: s for tf, s in state.items() if at < s['availableAt']+guides[tf]['interval']}
        h, m, minute = current.get('4h'), current.get('15m'), current.get('1m')
        bounds = h.get('range') if h else None
        if not bounds:
            campaign = None
            continue
        if campaign and (campaign['contextZone']['id'] not in zones
                         or at-campaign['contextAt'] > confirmation_minutes*60):
            campaign = None
        if campaign is None:
            matches = [zones[k] for k in new_visits if k in zones
                       and zones[k]['timeframe'] in ('1d', '4h')
                       and (b['low'] < bounds['equilibrium'] if zones[k]['kind'] == 'DEMAND'
                            else b['high'] > bounds['equilibrium'])]
            if matches:
                z = max(matches, key=lambda z: (z['availableAt'], z['timeframe'] == '1d'))
                sign = 1 if z['kind'] == 'DEMAND' else -1
                campaign = dict(contextZone=deepcopy(z), contextAt=at, direction=sign,
                                extreme=b['low'] if sign == 1 else b['high'], touchClose=b['close'],
                                alignmentAt=None, touchTime=b['time'], stopZoneIds=set(touches))
            continue
        campaign['stopZoneIds'].update(touches)
        sign = campaign['direction']
        long = sign == 1
        campaign['extreme'] = (min if long else max)(campaign['extreme'], b['low'] if long else b['high'])
        for event in changes[at]:
            if at > campaign['contextAt']:
                if event['direction'] == sign:
                    campaign['alignmentAt'] = at
                elif campaign['alignmentAt'] is not None:
                    campaign = None
                    break
        if campaign is None:
            continue
        if not campaign['alignmentAt'] or not m or m['trend'] != sign or not minute or minute['trend'] != sign:
            continue
        # The structural reversal must also have moved away from the touch close.
        if sign*(b['close']-campaign['touchClose']) <= 0:
            continue
        entry, target = b['close'], bounds['equilibrium']
        if not bounds['low'] <= entry <= bounds['high'] or sign*(target-entry) <= 0:
            continue
        context = campaign['contextZone']
        nested = [z for z in zones.values() if z['timeframe'] == '15m'
                  and z['kind'] == context['kind'] and z['availableAt'] <= at
                  and z['lower'] >= context['lower'] and z['upper'] <= context['upper']
                  and (z['id'] in campaign['stopZoneIds'] or z['lower'] <= campaign['extreme'] <= z['upper'])
                  and sign*(entry-(z['lower'] if long else z['upper'])) > 0]
        parent = max(nested, key=lambda z: z['availableAt']) if nested else None
        boundary = (parent['lower'] if long else parent['upper']) if parent else campaign['extreme']
        av = float(atr_values[i])
        if not isfinite(av) or av <= 0:
            continue
        stop = boundary-sign*stop_buffer_atr*av
        risk, reward = sign*(entry-stop), sign*(target-entry)
        if stop <= 0 or risk <= 0 or reward/risk < minimum_r:
            continue
        zone_source = parent or context
        zone = dict(bottom=zone_source['lower'], top=zone_source['upper'],
                    pivotTime=iso(zone_source.get('originTime', campaign['touchTime'])),
                    confirmedTime=iso(zone_source['availableAt']), touchTime=iso(campaign['touchTime']),
                    bounceTime=iso(b['time']))
        checks = [dict(code=code, label=label, passed=True, detail=detail) for code, label, detail in (
            ('HTF_ZONE', 'Daily / 4H zone touched', context['timeframe']+' '+context['kind']+'; touch '+iso(campaign['contextAt'])),
            ('15M_CHANGE', 'Fresh 15m trend change', 'Confirmed '+iso(campaign['alignmentAt'])),
            ('1M_ALIGNMENT', '1m swing aligned', 'Confirmed '+iso(at)+'; existing alignment accepted'),
            ('4H_VALUE', 'Entry in 4H '+('discount' if long else 'premium'), f'Planned entry {entry:g}; midpoint {target:g}'),
            ('STOP_SOURCE', 'Stop beyond '+('15m zone' if parent else 'touch extreme'), f'Boundary {boundary:g}; buffered stop {stop:g}'),
            ('MINIMUM_R', 'Minimum reward / risk to 4H midpoint', f'{reward/risk:g}R at confirmation; minimum {minimum_r:g}R; rechecked at fill'),
        )]
        signals[i] = dict(version=1, strategy=MODE, entryModel='HTF_ZONE_REVERSAL',
                          side='LONG' if long else 'SHORT', entry=entry, stop=stop, target=target,
                          signalTime=iso(b['time']), signalAvailableAt=at, signalIndex=i,
                          contextZone=deepcopy(context), parentZone=deepcopy(parent), zone=zone,
                          entryZone=deepcopy(zone),
                          opposingZone=dict(bottom=target*.999999, top=target*1.000001,
                                            pivotTime=iso(bounds.get('knownAt', h['availableAt'])),
                                            confirmedTime=iso(h['availableAt'])), contextTouchAt=campaign['contextAt'],
                          alignmentAt=campaign['alignmentAt'], stopSource='15M_ZONE' if parent else 'TOUCH_EXTREME',
                          stopBoundary=boundary, touchExtreme=campaign['extreme'],
                          range4h=deepcopy(bounds), range15m=deepcopy(m.get('range')),
                          targetMode='4H_MIDPOINT', target4h=target,
                          review=dict(status='PREFERRED_ALIGNMENT', checks=checks, mismatches=[]),
                          narrative={tf: dict(trend=s['trend'], internal=s.get('internal', 0), availableAt=s['availableAt'])
                                     for tf, s in current.items()})
        live[i] = i
        campaign = None
    return signals, live
