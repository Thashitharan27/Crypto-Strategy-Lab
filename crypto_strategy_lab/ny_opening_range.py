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
