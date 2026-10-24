"""New York opening four-hour range: outside close, then inside close reversal.

The range is four elapsed hours from New York midnight. This explicit crypto
session convention does not depend on a chart provider's 4h candle alignment.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

MODE = "NY_OPENING_RANGE_REVERSAL"
TIMEZONE = "America/New_York"


def validate_target(target_r):
    if not np.isfinite(target_r) or target_r < 2:
        raise ValueError("New York range target must be finite and at least 2R")


def validate_timeframe(profiles, minutes):
    if any(r.get('_strategy_direction_mode')==MODE for p in profiles.values() for r in getattr(p,'entry_rules',())) and minutes!=5:
        raise ValueError("New York opening range reversal requires 5m strategy candles")


def requires_sr(profiles, policy):
    return policy=='SR_STOP' and any(r.get('_strategy_direction_mode')==MODE for p in profiles.values() for r in getattr(p,'entry_rules',()))


def validate_policy(policy, extension_pct, sr_buffer_atr):
    if policy not in {'DEFAULT','SKIP','SR_STOP'}:
        raise ValueError("Unknown New York range oversized-target policy")
    if not np.isfinite(extension_pct) or extension_pct<0:
        raise ValueError("Allowed target extension must be finite and non-negative")
    if not np.isfinite(sr_buffer_atr) or sr_buffer_atr<0:
        raise ValueError("New York S/R stop buffer must be finite and non-negative")


def range_entry_plan(setup, entry, target_r, *, policy='DEFAULT', extension_pct=0.,
                     sr_context=None, atr=None, sr_buffer_atr=.05):
    """Enforce target room at executable entry without clamping an R target.

    S/R input must be the detector's completed-candle context at the signal.
    Never substitute the target limit itself as a synthetic stop level.
    """
    validate_target(target_r);validate_policy(policy,extension_pct,sr_buffer_atr)
    long=setup['side']=='LONG';sign=1 if long else -1
    stop=setup['stop'];bottom=setup['zone']['bottom'];top=setup['zone']['top']
    width=top-bottom;limit=top+width*extension_pct/100 if long else bottom-width*extension_pct/100
    risk=sign*(entry-stop);target=entry+sign*target_r*risk
    details=dict(passed=False,applied=False,distance=None,entry_price=entry,stop_price=stop,target_price=target,
                 original_stop=stop,original_target=target,target_limit=limit,overshoot_policy=policy,
                 allowed_extension_pct=extension_pct,stop_source='BREAKOUT_EXTREME')
    def reject(reason):return {**details,'reason':reason}
    def valid_geometry():return np.isfinite([entry,stop,risk,target]).all() and min(entry,stop,target)>0 and risk>0
    def fits():return sign*(target-limit)<=1e-10*max(abs(limit),1.)
    if not valid_geometry():return reject('NY_RANGE_INVALID_ENTRY_GEOMETRY')
    if not bottom<entry<top:return reject('NY_RANGE_ENTRY_OUTSIDE_RANGE')
    if policy!='DEFAULT' and not fits():
        if policy=='SKIP':return reject('NY_RANGE_TARGET_TOO_FAR')
        if sr_context is None:return reject('NY_RANGE_SR_CONTEXT_UNAVAILABLE')
        prefix='support' if long else 'resistance'
        def value(name):
            raw=sr_context.get(name) if isinstance(sr_context,dict) else getattr(sr_context,name,None)
            try:return float(raw) if np.isfinite(float(raw)) else None
            except (TypeError,ValueError):return None
        state=sr_context.get(prefix+'_state') if isinstance(sr_context,dict) else getattr(sr_context,prefix+'_state',None)
        state=str(getattr(state,'value',state)).upper()
        level=value('nearest_'+prefix+'_price')
        boundary=value(prefix+'_zone_low' if long else prefix+'_zone_high')
        if boundary is None:boundary=level
        if boundary is None or ('BROKEN' in state or state.startswith('NO_') or state in {'NONE','UNKNOWN'}):
            return reject('NY_RANGE_NO_VALID_SR_STOP')
        if sr_buffer_atr and (atr is None or not np.isfinite(atr) or atr<=0):
            return reject('NY_RANGE_SR_ATR_UNAVAILABLE')
        stop=boundary-sign*(sr_buffer_atr*atr if sr_buffer_atr else 0.)
        risk=sign*(entry-stop);target=entry+sign*target_r*risk
        details.update(stop_price=stop,target_price=target,stop_source='CONFIRMED_SR',sr_level=level,sr_boundary=boundary,sr_state=state)
        if not valid_geometry() or risk>=sign*(entry-details['original_stop']):return reject('NY_RANGE_NO_VALID_SR_STOP')
        if not fits():return reject('NY_RANGE_SR_STOP_TOO_WIDE')
    return {**details,'passed':True,'applied':True,'reason':'NY_RANGE_SR_STOP' if details['stop_source']=='CONFIRMED_SR' else 'NY_RANGE_EXCURSION_STOP',
            'distance':risk,'stop_price':stop,'boundary_price':stop,'level_price':target,'distance_atr':None,'timeframe_minutes':5}


def range_reversal_setups(times, opens, highs, lows, closes, *, target_r=2.):
    validate_target(target_r)
    ts=pd.DatetimeIndex(pd.to_datetime(times,utc=True))
    arrays=[np.asarray(a,dtype=float) for a in (opens,highs,lows,closes)]
    if any(a.ndim!=1 or len(a)!=len(ts) for a in arrays) or ts.hasnans or ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("New York range candles must align with unique increasing timestamps")
    if len(ts) and ((ts.asi8 % pd.Timedelta(minutes=5).value)!=0).any():
        raise ValueError("New York range requires aligned 5m candle opens")
    o,h,l,c=arrays
    step=pd.Timedelta(minutes=5)
    result=[None]*len(ts)
    current_day=None;pending=None;ready=False
    for i,(t,day) in enumerate(zip(ts,ts.tz_convert(TIMEZONE).date)):
        if day!=current_day:
            current_day=day
            start=pd.Timestamp(day).tz_localize(TIMEZONE).tz_convert('UTC')
            end=pd.Timestamp(day+timedelta(days=1)).tz_localize(TIMEZONE).tz_convert('UTC')
            range_end=start+pd.Timedelta(hours=4)
            count=0;expected=start;complete=True;bottom=np.inf;top=-np.inf
            pending=None;ready=False
        valid=np.isfinite([o[i],h[i],l[i],c[i]]).all() and 0<l[i]<=min(o[i],c[i])<=max(o[i],c[i])<=h[i]
        if t<range_end:
            if not valid or t!=expected:complete=False
            expected=t+step
            if valid:
                count+=1;bottom=min(bottom,float(l[i]));top=max(top,float(h[i]))
            ready=complete and count==48 and expected==range_end and top>bottom
            continue  # No breakout on the still-forming range's final candle.
        if not ready:continue
        if not valid:
            pending=None
            continue
        if i and t-ts[i-1]!=step:
            pending=None  # Do not carry an excursion across unknown candles.
        inside=bottom<c[i]<top
        if pending:
            long=pending['side']=='LONG'
            pending['extreme']=float(min(pending['extreme'],l[i]) if long else max(pending['extreme'],h[i]))
            if inside:
                # Entry would be next open: a midnight fill belongs to a new day.
                if t+step<end:
                    sign=1 if long else -1;stop=pending['extreme']
                    risk=sign*(c[i]-stop);target=float(c[i]+sign*target_r*risk)
                    if risk>0 and target>0:
                        zone=dict(bottom=bottom,top=top,pivotTime=start.isoformat(),confirmedTime=range_end.isoformat(),
                                  touchTime=pending['time'],bounceTime=t.isoformat())
                        result[i]=dict(version=1,strategy=MODE,side=pending['side'],zone=zone,
                            opposingZone=dict(bottom=target*.999999,top=target*1.000001,pivotTime=t.isoformat(),confirmedTime=(t+step).isoformat()),
                            signalTime=t.isoformat(),target=target,targetR=float(target_r),stop=float(stop),
                            breakoutTime=pending['time'],dayEnd=end.isoformat(),sessionDay=str(day),sessionTimezone=TIMEZONE,
                            rangeConvention='FOUR_ELAPSED_HOURS_FROM_NY_MIDNIGHT')
                pending=None
                continue
            opposite=c[i]>top if long else c[i]<bottom
            if not opposite:continue
            pending=None  # An opposite outside close starts a fresh excursion.
        if c[i]>top:
            pending=dict(side='SHORT',extreme=float(h[i]),time=t.isoformat())
        elif c[i]<bottom:
            pending=dict(side='LONG',extreme=float(l[i]),time=t.isoformat())
    return result
