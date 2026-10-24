"""Closed-HTF zone selection and causal lower-timeframe shift/retest entries.

An explicit research interpretation of inducement, not order-book inference.
"""
import copy

import numpy as np
import pandas as pd

MODE = "IMBALANCE_ORIGIN_RETEST"
CONFIRMED = "INDUCEMENT_CONFIRMATION"


def validate_model(model, context_minutes, timeframe_minutes, active=True):
    if model not in {"ORIGIN_REJECTION", CONFIRMED}:
        raise ValueError("Unknown imbalance entry model")
    if not np.isfinite(context_minutes) or int(context_minutes) != context_minutes or context_minutes <= 0:
        raise ValueError("Imbalance context minutes must be a positive integer")
    if not np.isfinite(timeframe_minutes) or int(timeframe_minutes) != timeframe_minutes or timeframe_minutes <= 0:
        raise ValueError("Entry timeframe must be a positive integer")
    if active and model == CONFIRMED and (timeframe_minutes <= 0 or context_minutes <= timeframe_minutes or context_minutes % timeframe_minutes):
        raise ValueError("Inducement context must be larger than and an exact multiple of the entry timeframe")


def _confirm_pivots(bars, i, strength, pivots):
    j = i-strength
    if j-strength < 0:
        return
    for side, key, compare in (("LONG", "high", np.greater), ("SHORT", "low", np.less)):
        neighbours = [b[key] for k,b in enumerate(bars[j-strength:i+1], j-strength) if k != j]
        if compare(bars[j][key], neighbours).all():
            pivots[side].append(dict(price=bars[j][key], time=bars[j]["time"], confirmedTime=bars[i]["end"]))
            pivots[side] = pivots[side][-2:]


def context_zones(bars, strength=2, displacement_atr=1.):
    """One release slot per complete HTF candle; no unconfirmed pivots used.

    Zones must break an existing unbroken swing with a close in an established
    HH/HL or LH/LL trend. The target is that prior swing, frozen before breakout.
    """
    result = [None]*len(bars)
    pivots = {"LONG": [], "SHORT": []}
    history = []
    broken = set()
    candidate = None
    trs = []
    for i, bar in enumerate(bars):
        if history and bar["time"] != history[-1]["end"]:
            history=[];pivots={"LONG":[],"SHORT":[]};broken=set();candidate=None;trs=[]
        if candidate:
            origin, impulse, swing = candidate["origin"], candidate["impulse"], candidate["swing"]
            long = candidate["side"] == "LONG"
            gap = bar["low"] > origin["high"] if long else bar["high"] < origin["low"]
            if gap:
                zone = dict(bottom=origin["low"], top=origin["high"], pivotTime=origin["time"].isoformat(),
                    confirmedTime=bar["end"].isoformat(), touchTime=None, bounceTime=None)
                result[i] = dict(version=1, strategy=MODE, entryModel=CONFIRMED, side=candidate["side"],
                    target=swing["price"], structureLevel=swing["price"], structureTime=swing["time"].isoformat(),
                    structureBreakTime=impulse["end"].isoformat(), signalTime=None, zone=zone,
                    imbalance=dict(bottom=origin["high"] if long else bar["high"], top=bar["low"] if long else origin["low"]),
                    opposingZone=dict(bottom=swing["price"]*.999999, top=swing["price"]*1.000001,
                                      pivotTime=swing["time"].isoformat(), confirmedTime=swing["confirmedTime"].isoformat()))
        candidate = None
        prev_close = history[-1]["close"] if history else bar["close"]
        trs.append(max(bar["high"]-bar["low"],abs(bar["high"]-prev_close),abs(bar["low"]-prev_close)))
        # Displacement is measured against the preceding completed HTF ATR.
        atr = float(np.mean(trs[-15:-1])) if len(trs)>=15 else np.nan
        if history:
            origin=history[-1]
            for side in ("LONG","SHORT"):
                long=side=="LONG";highs=pivots["LONG"];lows=pivots["SHORT"]
                trend=len(highs)==2 and len(lows)==2 and (highs[-1]["price"]>highs[-2]["price"] and lows[-1]["price"]>lows[-2]["price"] if long else highs[-1]["price"]<highs[-2]["price"] and lows[-1]["price"]<lows[-2]["price"])
                if trend:
                    defended=lows[-1] if long else highs[-1]
                    trend=("SHORT" if long else "LONG",defended["time"]) not in broken
                swing=(highs if long else lows)[-1] if (highs if long else lows) else None
                body=bar["close"]-bar["open"] if long else bar["open"]-bar["close"]
                opposing=origin["close"]<=origin["open"] if long else origin["close"]>=origin["open"]
                crossed=swing is not None and (prev_close<=swing["price"]<bar["close"] if long else prev_close>=swing["price"]>bar["close"])
                key=(side,swing["time"]) if swing else None
                if trend and opposing and origin['high']>origin['low'] and crossed and key not in broken and np.isfinite(atr) and atr>0 and body>=displacement_atr*atr:
                    candidate=dict(side=side,origin=origin,impulse=bar,swing=copy.deepcopy(swing))
                if crossed:
                    broken.add(key)
        history.append(bar)
        _confirm_pivots(history,len(history)-1,strength,pivots)
    return result


def inducement_setups(times, opens, highs, lows, closes, atr_values, *,
                      timeframe_minutes=15, context_minutes=60, strength=2,
                      displacement_atr=1., max_wait=20):
    from .supply_demand_retest import validate_settings
    validate_model(CONFIRMED,context_minutes,timeframe_minutes)
    validate_settings(strength,0.,1.)
    strength=int(strength);context_minutes=int(context_minutes);timeframe_minutes=int(timeframe_minutes)
    if not np.isfinite(displacement_atr) or displacement_atr<=0:
        raise ValueError("Displacement must be finite and positive")
    if not np.isfinite(max_wait) or int(max_wait)!=max_wait or max_wait<1:
        raise ValueError("Maximum wait must be a positive integer")
    ts=pd.DatetimeIndex(pd.to_datetime(times,utc=True))
    arrays=[np.asarray(a,dtype=float) for a in (opens,highs,lows,closes,atr_values)]
    if any(a.ndim!=1 or len(a)!=len(ts) for a in arrays) or ts.has_duplicates or ts.hasnans or not ts.is_monotonic_increasing:
        raise ValueError("Candles must align with unique increasing timestamps")
    o,h,l,c=arrays[:4]
    step=pd.Timedelta(minutes=timeframe_minutes);context=pd.Timedelta(minutes=context_minutes)
    ratio=context_minutes//timeframe_minutes
    frame=pd.DataFrame(dict(time=ts,open=o,high=h,low=l,close=c,index=np.arange(len(ts))))
    bars=[];release={}
    for bucket,group in frame.groupby(frame.time.dt.floor(f'{context_minutes}min'),sort=True):
        valid=np.isfinite(group[['open','high','low','close']]).all().all() and (group.low>0).all() and (group.low<=group[['open','close']].min(axis=1)).all() and (group.high>=group[['open','close']].max(axis=1)).all()
        if len(group)!=ratio or group.time.iloc[0]!=bucket or group.time.iloc[-1]+step!=bucket+context or not group.time.diff().iloc[1:].eq(step).all() or not valid:
            continue
        bars.append(dict(time=bucket,end=bucket+context,open=float(group.open.iloc[0]),high=float(group.high.max()),low=float(group.low.min()),close=float(group.close.iloc[-1])))
        release[len(bars)-1]=int(group['index'].iloc[-1])
    released={release[i]:z for i,z in enumerate(context_zones(bars,strength,displacement_atr)) if z}
    pending=[];history=[];pivots={"LONG":[],"SHORT":[]};result=[None]*len(ts)
    for i,t in enumerate(ts):
        valid=np.isfinite([o[i],h[i],l[i],c[i]]).all() and 0<l[i]<=min(o[i],c[i])<=max(o[i],c[i])<=h[i]
        if (i and t-ts[i-1]!=step) or not valid:
            pending=[];history=[];pivots={"LONG":[],"SHORT":[]}
        if not valid:continue
        candidates=[];survivors=[]
        for p in pending:
            long=p['side']=='LONG';z=p['zone'];sign=1 if long else -1
            if t+step>pd.Timestamp(z['confirmedTime'])+max_wait*context or (c[i]<z['bottom'] if long else c[i]>z['top']):continue
            if l[i]<=p['imbalance']['bottom'] if long else h[i]>=p['imbalance']['top']:
                p['gapFilled']=True
            touched=l[i]<=z['top'] and h[i]>=z['bottom']
            if p.get('entryZone'):
                ez=p['entryZone']
                # Once the shift is confirmed, never widen a breached reversal stop.
                if l[i]<p['reversalExtreme'] if long else h[i]>p['reversalExtreme']:continue
                retest=l[i]<=ez['top'] and h[i]>=ez['bottom']
                reject=c[i]>o[i] and c[i]>ez['top'] if long else c[i]<o[i] and c[i]<ez['bottom']
                if retest and reject:
                    saved=copy.deepcopy(p);saved.pop('touchedIndex',None)
                    saved['signalTime']=t.isoformat();saved['entryZone']['touchTime']=t.isoformat();saved['entryZone']['bounceTime']=t.isoformat()
                    candidates.append(saved);continue
            else:
                if touched and p.get('touchedIndex') is None:
                    p['touchedIndex']=i;p['zone']['touchTime']=t.isoformat()
                    p['reversalExtreme']=float(l[i] if long else h[i])
                if p.get('touchedIndex') is not None:
                    p['reversalExtreme']=float(min(p['reversalExtreme'],l[i]) if long else max(p['reversalExtreme'],h[i]))
                    swing=pivots[p['side']][-1] if pivots[p['side']] else None
                    origin=history[-1] if history else None
                    # Require a pivot formed at/after the zone touch, then a close
                    # through it. A later origin retest supplies the higher low /
                    # lower high without assuming intrabar ordering.
                    shifted=swing and pd.Timestamp(swing['time'])>=ts[p['touchedIndex']] and (c[i-1]<=swing['price']<c[i] if long else c[i-1]>=swing['price']>c[i])
                    opposing=origin and origin['high']>origin['low'] and (origin['close']<=origin['open'] if long else origin['close']>=origin['open'])
                    recovered=c[i]>z['top'] if long else c[i]<z['bottom']
                    if shifted and opposing and recovered and sign*(c[i]-o[i])>0:
                        p['entryZone']=dict(bottom=origin['low'],top=origin['high'],pivotTime=origin['time'].isoformat(),confirmedTime=(t+step).isoformat(),touchTime=None,bounceTime=None)
                        p['shiftLevel']=swing['price'];p['shiftTime']=(t+step).isoformat();p['zone']['bounceTime']=t.isoformat()
            survivors.append(p)
        pending=survivors
        if i in released:
            new=copy.deepcopy(released[i]);long=new['side']=='LONG'
            # Reject shallower origins while an untouched, stronger origin and
            # its intervening gap remain open. Filled/expired origins cannot veto.
            deeper=any(p['side']==new['side'] and p.get('touchedIndex') is None and not p.get('gapFilled',False) and
                (p['zone']['top']<new['zone']['bottom'] and l[i]>p['imbalance']['bottom'] if long else p['zone']['bottom']>new['zone']['top'] and h[i]<p['imbalance']['top']) for p in pending)
            if not deeper:pending.append(new)
        # Newly confirmed deeper zones also veto an older shallow setup that
        # would otherwise enter at this same close; no intrabar priority assumed.
        def shadowed(setup):
            return any(p is not setup and p['side']==setup['side'] and p.get('touchedIndex') is None and not p.get('gapFilled',False) and
                (p['zone']['top']<setup['zone']['bottom'] if setup['side']=='LONG' else p['zone']['bottom']>setup['zone']['top']) for p in pending)
        candidates=[p for p in candidates if not shadowed(p)]
        pending=[p for p in pending if not shadowed(p)]
        if len(candidates)==1:result[i]=candidates[0]
        history.append(dict(time=t,end=t+step,open=float(o[i]),high=float(h[i]),low=float(l[i]),close=float(c[i])))
        _confirm_pivots(history,len(history)-1,strength,pivots)
    return result
