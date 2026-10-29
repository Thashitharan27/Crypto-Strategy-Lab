"""Optional, causal mechanical interpretations of the supply/demand lesson.

Quality labels describe observable price patterns, not proof of institutional
orders. Legacy defaults never change zone construction or entry eligibility.
"""
from bisect import bisect_right
from copy import deepcopy
from math import isfinite

MODELS = ('LEGACY', 'PIVOT', 'PIVOT_TWO', 'RANGE')
REQUIREMENTS = {
    'photon_fresh_zone_only': 'fresh',
    'photon_require_zone_bos': 'bos',
    'photon_require_flip': 'flip',
    'photon_require_sweep': 'sweep',
    'photon_require_inducement': 'inducement',
    'photon_require_stacking': 'stacked',
    'photon_require_zone_value': 'in_value',
    'photon_require_4h_alignment': '4h_aligned',
    'photon_require_daily_alignment': '1d_aligned',
    'photon_require_weekly_alignment': '1w_aligned',
    'photon_require_15m_internal_alignment': '15m_internal_aligned',
}


def options(config, *, collect_evidence=False):
    return dict(photon_zone_model=getattr(config, 'photon_zone_model', 'LEGACY'),
                collect_evidence=collect_evidence,
                photon_range_base_bars=getattr(config, 'photon_range_base_bars', 3),
                **{key: getattr(config, key, False) for key in REQUIREMENTS})


def enabled(opts):
    return opts and (opts.get('collect_evidence',False) or opts.get('photon_zone_model', 'LEGACY') != 'LEGACY'
                     or any(opts.get(k, False) for k in REQUIREMENTS))


def validate(config):
    from .photon_demand_pullback import validate_entry_model
    validate_entry_model(getattr(config, "photon_demand_entry_model", "ORIGINAL"))
    if getattr(config, 'photon_zone_model', 'LEGACY') not in MODELS:
        raise ValueError('Photon zone model must be LEGACY, PIVOT, PIVOT_TWO or RANGE')
    n = getattr(config, 'photon_range_base_bars', 3)
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= 12:
        raise ValueError('Photon range base must contain 2 to 12 candles')
    r = getattr(config, 'photon_fixed_target_r', 3.)
    if not isfinite(r) or r <= 0:
        raise ValueError('Photon fixed target R must be finite and positive')
    if not getattr(config, 'photon_demand_pullback', False) and not getattr(config, 'photon_midpoint_reversal', False) and not getattr(config, 'photon_quarter_range', False) and getattr(config, 'photon_zone_reversal', False) and getattr(config, 'photon_fixed_target_enabled', False):
        if getattr(config, 'photon_hold_tp_until_15m_reversal', False):
            raise ValueError('Photon fixed-R TP cannot be combined with hold beyond TP')
        if getattr(config, 'photon_exit_on_15m_change', False):
            raise ValueError('Photon fixed-R TP cannot be combined with early 15m trend exits')
        if r < getattr(config, 'sd_minimum_r', 1.):
            raise ValueError('Photon fixed target R must meet the minimum reward/risk')


def state_at(guide, at):
    states = guide.get('snapshots', ())
    times = guide.get('_lesson_times')
    if times is None:
        times = [s['availableAt'] for s in states]
    j = bisect_right(times, at)-1
    return states[j] if j >= 0 and at < states[j]['availableAt']+guide['interval'] else None


def construct_zones(native, guide, tf, opts):
    """Immediate thrust-close confirmation; candle colour is unrestricted."""
    from .photon_structure import valid_bar
    from .photon_zones import zone_location
    model = opts['photon_zone_model']
    n = 1 if model == 'PIVOT' else 2 if model == 'PIVOT_TWO' else opts['photon_range_base_bars']
    zones = []
    for i in range(n, len(native)):
        base, thrust = native[i-n:i], native[i]
        block = base+[thrust]
        if not all(valid_bar(b) for b in block) or any(b['time']-a['time'] != guide['interval'] for a,b in zip(block,block[1:])):
            continue
        # A range base needs a common price overlap across all its candles.
        if model == 'RANGE' and max(b['low'] for b in base) >= min(b['high'] for b in base):
            continue
        lower, upper = min(b['low'] for b in base), max(b['high'] for b in base)
        sign = 1 if thrust['close'] > upper else -1 if thrust['close'] < lower else 0
        if not sign or upper <= lower:
            continue
        at = thrust['time']+guide['interval']
        state = state_at(guide, at)
        bounds = state.get('range') if state else None
        kind = 'DEMAND' if sign == 1 else 'SUPPLY'
        zones.append(dict(id=f'{tf}:{kind}:{model}:{base[0]["time"]}',timeframe=tf,
            kind=kind,lower=lower,upper=upper,originTime=base[0]['time'],
            availableAt=at,breakTime=thrust['time'],brokenLevel=upper if sign==1 else lower,
            confirmedBy='THRUST',creationRange=dict(bounds) if bounds else None,
            creationLocation=zone_location(lower,upper,bounds),lessonModel=model,
            baseCandles=n))
    return zones


def indexed_lifecycle(source,native,guide,zones,source_interval):
    """Price-indexed returns; scan invalidation only at native candle closes.

    The index may contain later origins, but only active, already-born zones
    can produce events. It cannot reveal a future zone or change a past visit.
    """
    from collections import defaultdict
    from .photon_structure import valid_bar
    ordered=sorted(zones,key=lambda z:(z['lower'],z['id']))
    def tree(lo,hi):
        if lo>=hi:return None
        mid=(lo+hi)//2;z=ordered[mid];left=tree(lo,mid);right=tree(mid+1,hi)
        return (z,left,right,max(z['upper'],left[3] if left else -float('inf'),right[3] if right else -float('inf')))
    root=tree(0,len(ordered))
    def overlaps(node,low,high,active,found):
        if node is None or node[3]<low:return
        z,left,right,_=node
        overlaps(left,low,high,active,found)
        if z['lower']<=high:
            if z['upper']>=low and z['id'] in active:found.add(z['id'])
            overlaps(right,low,high,active,found)
    births=defaultdict(list)
    for z in zones:births[z['availableAt']].append(z)
    native_closes={b['time']+guide['interval']:b for b in native}
    active={};inside=set();previous=None;events=[]
    for b in source:
        at=b['time']+source_interval;valid=valid_bar(b)
        if not valid or previous is not None and b['time']-previous!=source_interval:
            events.extend(dict(zoneId=k,kind='RETIRED',reason='DATA_GAP',availableAt=at) for k in active)
            active.clear();inside.clear()
        previous=b['time']
        if not valid:continue
        touched=set();overlaps(root,b['low'],b['high'],active,touched)
        for key in sorted(touched-inside,key=lambda k:(active[k]['availableAt'],k)):
            events.append(dict(zoneId=key,kind='TOUCHED',availableAt=at,candleTime=b['time']))
        inside=touched
        closing=native_closes.get(at)
        if closing:
            for key,z in list(active.items()):
                if closing['close']<z['lower'] if z['kind']=='DEMAND' else closing['close']>z['upper']:
                    events.append(dict(zoneId=key,kind='INVALIDATED',availableAt=at,close=closing['close'],candleTime=closing['time']))
                    active.pop(key);inside.discard(key)
        for z in births.get(at,()):active[z['id']]=z
    return dict(zones=zones,events=events,rule='Lesson base departure with own-timeframe close invalidation.')


def active_at(zone, data, at):
    index_data(data)
    return zone['availableAt'] <= at < data['_lesson_ends'].get(zone['id'],float('inf'))


def index_data(data):
    if '_lesson_ends' in data:return
    data['_lesson_ends']={};data['_lesson_touches']={}
    data['_lesson_births']={z['id']:z for z in data['zones']}
    for e in data.get('events',()):
        if e['kind'] in ('INVALIDATED','RETIRED'):
            data['_lesson_ends'].setdefault(e['zoneId'],e['availableAt'])
        if e['kind']=='TOUCHED':data['_lesson_touches'].setdefault(e['zoneId'],[]).append(e)
    data['_lesson_flip_events']=sorted((e['availableAt'],data['_lesson_births'][e['zoneId']]['kind'],e['zoneId'])
        for e in data.get('events',()) if e['kind']=='INVALIDATED' and e['zoneId'] in data['_lesson_births']
        and any(t['availableAt']<e['availableAt'] for t in data['_lesson_touches'].get(e['zoneId'],())))
    data['_lesson_flip_times']=[x[0] for x in data['_lesson_flip_events']]


def evidence(zone, guides, at):
    """Snapshot only what is knowable at this birth/return candle close."""
    if at < zone['availableAt']:
        return dict(checks={k:False for k in REQUIREMENTS.values()},liquidityLevel=None,touches=0,availableAt=at)
    tf = zone['timeframe']; guide = guides[tf]; data = guide['supplyDemand']
    index_data(data)
    sign = 1 if zone['kind']=='DEMAND' else -1
    touches = [e for e in data['_lesson_touches'].get(zone['id'],()) if e['availableAt']<=at]
    # The first touch is the first mitigation, not an already-mitigated revisit.
    fresh = len(touches) <= 1
    if '_lesson_bos_candidates' not in guide:
        swings = {e['availableAt']:e for e in guide.get('events',()) if e['kind']=='SWING'}
        guide['_lesson_bos_candidates']=[(e,swings.get(e['availableAt'],{}))
            for e in guide.get('events',()) if e['kind'] in ('BOS','TREND_CHANGE')]
        guide['_lesson_bos_at']={}
        guide['_lesson_bos_info']={}
    if zone['id'] not in guide['_lesson_bos_at']:
        matches=[e for e,s in guide['_lesson_bos_candidates']
            if e['direction']==sign and zone['availableAt']<=e['availableAt']
            and s.get('fromParentTime',s.get('fromTime',float('inf')))<=zone['originTime']<=e['time']]
        first=min(matches,key=lambda e:e['availableAt']) if matches else None
        guide['_lesson_bos_at'][zone['id']]=first['availableAt'] if first else float('inf')
        guide['_lesson_bos_info'][zone['id']]=dict(price=first.get('price'),time=first['time'],
            fromTime=first.get('fromTime',zone['originTime']),availableAt=first['availableAt']) if first else None
    bos = zone.get('confirmedBy') in ('BOS','TREND_CHANGE') or guide['_lesson_bos_at'][zone['id']]<=at
    before = state_at(guide, zone['originTime'])
    pivot = before.get('internalLow' if sign==1 else 'internalHigh') if before else None
    sweep = bool(pivot and (zone['lower'] < pivot['price'] < zone['upper']))
    # A flip needs a prior return to opposing supply/demand followed by its
    # own-timeframe close failure during this zone's initiation leg.
    start=bisect_right(data['_lesson_flip_times'],zone['originTime']-1)
    end=bisect_right(data['_lesson_flip_times'],min(zone['availableAt'],at))
    failure=next(((time,key) for time,kind,key in data['_lesson_flip_events'][start:end] if kind!=zone['kind']),None)
    flip=failure is not None
    # Evaluate liquidity just before the return candle: a confirmed internal
    # pivot formed after zone birth, between the zone and approaching price.
    touch = touches[-1] if touches else None
    approach = state_at(guide, touch['candleTime'] if touch else at)
    liquidity = approach.get('internalLow' if sign==1 else 'internalHigh') if approach else None
    price = approach.get('close') if approach else None
    inducement = bool(liquidity and liquidity['time'] >= zone['availableAt'] and price is not None
        and (zone['upper'] < liquidity['price'] < price if sign==1 else price < liquidity['price'] < zone['lower']))
    if inducement:
        native=guide.get('_lesson_native')
        cutoff=touch['candleTime'] if touch else at
        if native is not None:
            times=guide.get('_lesson_native_times') or [b['time'] for b in native]
            native=native[bisect_right(times,liquidity['time']):bisect_right(times,cutoff-guide['interval'])]
        inducement=bool(native is not None and not any(
            liquidity['time'] < b['time'] and b['time']+guide['interval']<=cutoff
            and (b['low']<=liquidity['price'] if sign==1 else b['high']>=liquidity['price']) for b in native))
    stack = next((other for g in guides.values() if 'supplyDemand' in g for other in g['supplyDemand']['zones']
        if other['timeframe'] != tf and other['kind']==zone['kind']
        and min(other['upper'],zone['upper']) > max(other['lower'],zone['lower'])
        and active_at(other,g['supplyDemand'],at)),None)
    stacked=stack is not None
    checks = dict(fresh=fresh,bos=bool(bos),flip=bool(flip),sweep=sweep,
        inducement=inducement,stacked=stacked,
        in_value=zone.get('creationLocation')==('DISCOUNT' if sign==1 else 'PREMIUM'))
    for timeframe,key in (('4h','4h_aligned'),('1d','1d_aligned'),('1w','1w_aligned')):
        s=state_at(guides.get(timeframe,{'interval':1}),at)
        checks[key]=bool(s and s.get('trend')==sign)
    s=state_at(guides.get('15m',{'interval':900}),at)
    checks['15m_internal_aligned']=bool(s and s.get('internal')==sign)
    reference=lambda z:{k:z[k] for k in ('id','timeframe','kind','lower','upper','originTime','availableAt')}
    departure=state_at(guide,zone['availableAt'])
    return dict(checks=checks,liquidityLevel=liquidity['price'] if inducement else None,
        liquidityTime=liquidity['time'] if inducement else None,
        sweepLevel=pivot['price'] if sweep else None,sweepTime=pivot['time'] if sweep else None,
        breakReference=guide['_lesson_bos_info'][zone['id']] if bos and guide['_lesson_bos_at'][zone['id']]<=at else None,
        flipReference=dict(**reference(data['_lesson_births'][failure[1]]),failedAt=failure[0]) if failure else None,
        stackReference=reference(stack) if stack else None,
        departurePrice=departure.get('close') if departure else None,
        returnTime=touch['candleTime'] if touch else None,
        returnAvailableAt=touch['availableAt'] if touch else None,
        touches=len(touches),availableAt=at)


def required_pass(checks, opts):
    return all(checks.get(value,False) for key,value in REQUIREMENTS.items() if opts.get(key,False))


def apply_to_guides(guides, natives, source, source_interval, opts):
    if not enabled(opts):
        return guides
    from .photon_zones import zone_lifecycle
    for tf,g in guides.items():
        if 'supplyDemand' not in g:
            continue
        g['_lesson_times']=[s['availableAt'] for s in g.get('snapshots',())]
        g['_lesson_native']=natives[tf]
        g['_lesson_native_times']=[b['time'] for b in natives[tf]]
        if opts['photon_zone_model'] != 'LEGACY':
            g['supplyDemand']=zone_lifecycle(source,natives[tf],g,construct_zones(natives[tf],g,tf,opts),source_interval)
            g['supplyDemand']['rule']='Lesson '+opts['photon_zone_model']+': full base wicks; immediate departure close; candle colour unrestricted.'
    for tf,g in guides.items():
        if 'supplyDemand' not in g:
            continue
        data=g['supplyDemand']; quality=[]
        by_zone={}
        for e in data['events']:
            if e['kind']=='TOUCHED':by_zone.setdefault(e['zoneId'],[]).append(e['availableAt'])
        for z in data['zones']:
            birth=evidence(z,guides,z['availableAt'])
            times={z['availableAt'],*by_zone.get(z['id'],[])}
            if opts.get('collect_evidence',False):
                broken_at=g.get('_lesson_bos_at',{}).get(z['id'],float('inf'))
                if isfinite(broken_at):times.add(broken_at)
            for at in sorted(times):
                proof=birth if at==z['availableAt'] else evidence(z,guides,at)
                proof.update(zoneId=z['id'],eligible=required_pass(proof['checks'],opts))
                quality.append(proof)
        data['qualityEvents']=sorted(quality,key=lambda e:e['availableAt'])
        data['lessonRequirements']=[v for k,v in REQUIREMENTS.items() if opts.get(k,False)]
    # Internal lookup acceleration is not part of the replay schema.
    for g in guides.values():
        for k in list(g):
            if k.startswith('_lesson_'):g.pop(k)
        for k in list(g.get('supplyDemand',{})):
            if k.startswith('_lesson_'):g['supplyDemand'].pop(k)
    return guides


def proof_at(zone,guides,at):
    data=guides[zone['timeframe']]['supplyDemand']
    if '_lesson_proofs' not in data:
        proofs={}
        for p in data.get('qualityEvents',()):proofs.setdefault(p['zoneId'],[]).append(p)
        data['_lesson_proofs']={k:([p['availableAt'] for p in v],v) for k,v in proofs.items()}
    times,proofs=data['_lesson_proofs'].get(zone['id'],([],[]))
    j=bisect_right(times,at)-1
    return deepcopy(proofs[j]) if j>=0 else evidence(zone,guides,at)


def context_pass(zone,guides,at,config):
    opts=options(config)
    if not enabled(opts):return True
    checks=proof_at(zone,guides,at)['checks']
    return all(checks.get(v,False) for k,v in REQUIREMENTS.items()
               if opts.get(k,False) and not v.endswith('_aligned'))


def qualify_setup(setup, guides, config):
    opts=options(config)
    if not enabled(opts):return True, None
    zone=setup['contextZone']; at=setup['contextTouchAt']
    proof=proof_at(zone,guides,at)
    proof['contextEligible']=proof.get('eligible')
    # HTF alignment is required at the decision too, not just at first touch.
    sign=1 if setup['side']=='LONG' else -1
    for tf,name in (('4h','4h_aligned'),('1d','1d_aligned'),('1w','1w_aligned'),('15m','15m_internal_aligned')):
        state=state_at(guides.get(tf,{'interval':1}),setup['signalAvailableAt'])
        proof['checks'][name]=bool(state and state.get('internal' if tf=='15m' else 'trend')==sign)
    proof['decisionAvailableAt']=setup['signalAvailableAt']
    proof['required']=[v for k,v in REQUIREMENTS.items() if opts.get(k,False)]
    proof['passed']=required_pass(proof['checks'],opts)
    proof['eligible']=proof['passed']
    return proof['passed'],proof
