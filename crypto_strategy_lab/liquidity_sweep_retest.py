"""Mechanical market-structure → equal-level sweep → displacement → zone retest."""
import copy
import numpy as np
import pandas as pd

MODE="LIQUIDITY_SWEEP_RETEST"


def validate_settings(tolerance, displacement, base_bars, max_wait):
    if not np.isfinite(tolerance) or tolerance<0:
        raise ValueError("Liquidity equal-level tolerance must be finite and non-negative")
    if not np.isfinite(displacement) or displacement<=0:
        raise ValueError("Liquidity displacement must be finite and positive")
    for value,label,limit in ((base_bars,"base candles",20),(max_wait,"maximum wait",500)):
        if not np.isfinite(value) or int(value)!=value or not 1<=value<=limit:
            raise ValueError(f"Liquidity {label} must be an integer from 1 to {limit}")


def liquidity_sweep_setups(times,opens,highs,lows,closes,atr_values,*,strength=2,
                           timeframe_minutes=60,tolerance_atr=.15,displacement_atr=1.,base_bars=3,max_wait=20):
    from crypto_strategy_lab.supply_demand_retest import validate_settings as validate_swing
    validate_swing(strength,0.,1.)
    validate_settings(tolerance_atr,displacement_atr,base_bars,max_wait)
    ts=pd.DatetimeIndex(pd.to_datetime(times,utc=True))
    arrays=[np.asarray(a,dtype=float) for a in (opens,highs,lows,closes,atr_values)]
    if any(a.ndim!=1 or len(a)!=len(ts) for a in arrays) or ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("Liquidity candles must align with unique increasing timestamps")
    o,h,l,c,atr=arrays
    step=pd.Timedelta(minutes=timeframe_minutes)
    pivots={"LONG":[],"SHORT":[]};pools={};bias=None;protected=None;target_zone=None
    pending=None;active=None;segment=0;result=[None]*len(ts)
    for i in range(len(ts)):
        valid=all(np.isfinite(a[i]) for a in arrays[:4])
        if (i and ts[i]-ts[i-1]!=step) or not valid:
            pivots={"LONG":[],"SHORT":[]};pools={};bias=None;protected=None;target_zone=None;pending=None;active=None
            segment=i if valid else i+1
        if not valid or not np.isfinite(atr[i]) or atr[i]<=0:
            continue
        j=i-strength
        changed=False
        if j-strength>=segment:
            for side,prices,compare in (("LONG",l,np.less),("SHORT",h,np.greater)):
                neighbours=np.r_[prices[j-strength:j],prices[j+1:i+1]]
                if compare(prices[j],neighbours).all():
                    pivot={"index":j,"bottom":float(l[j]),"top":float(h[j]),"pivotTime":ts[j].isoformat(),"confirmedTime":(ts[i]+step).isoformat()}
                    pivots[side]=[p for p in pivots[side] if j-p["index"]<=64]+[pivot]
                    changed=True
                    if len(pivots[side])>=2:
                        a,b=pivots[side][-2:];key="bottom" if side=="LONG" else "top"
                        if abs(a[key]-b[key])<=tolerance_atr*atr[i]:
                            pools[side]={"bottom":min(a[key],b[key]),"top":max(a[key],b[key]),"firstTime":a["pivotTime"],"secondTime":b["pivotTime"],"knownIndex":i,"used":False}
        if changed and len(pivots["LONG"])>=2 and len(pivots["SHORT"])>=2:
            lows2=pivots["LONG"][-2:];highs2=pivots["SHORT"][-2:]
            bullish=lows2[1]["bottom"]>lows2[0]["bottom"] and highs2[1]["top"]>highs2[0]["top"]
            bearish=lows2[1]["bottom"]<lows2[0]["bottom"] and highs2[1]["top"]<highs2[0]["top"]
            proposed="LONG" if bullish else "SHORT" if bearish else None
            if proposed and (bias is None or proposed==bias):
                if bias!=proposed: pending=None;active=None
                bias=proposed
                protected=lows2[-1]["bottom"] if bias=="LONG" else highs2[-1]["top"]
                extreme=highs2[-1] if bias=="LONG" else lows2[-1]
                if target_zone is None or (extreme["top"]>target_zone["top"] if bias=="LONG" else extreme["bottom"]<target_zone["bottom"]):
                    target_zone=copy.deepcopy(extreme)
        if bias and (c[i]<protected if bias=="LONG" else c[i]>protected):
            bias=None;protected=None;target_zone=None;pending=None;active=None
        if active:
            z=active["zone"]
            invalid=(c[i]<z["bottom"] if active["side"]=="LONG" else c[i]>z["top"])
            if bias!=active["side"] or invalid or i-active["formedIndex"]>max_wait:
                active=None
            elif i>active["formedIndex"] and l[i]<=z["top"] and h[i]>=z["bottom"] and (c[i]>o[i] if bias=="LONG" else c[i]<o[i]):
                setup=copy.deepcopy(active);setup.pop("formedIndex")
                setup["zone"]["touchTime"]=ts[i].isoformat();setup["signalTime"]=ts[i].isoformat()
                result[i]=setup;active=None
        if pending:
            if pending["side"]!=bias or i-pending["sweepIndex"]>max_wait:
                pending=None
            elif i>pending["sweepIndex"]:
                start=max(pending["sweepIndex"],i-base_bars)
                top=float(h[start:i].max());bottom=float(l[start:i].min())
                displacement=(c[i]-o[i] if bias=="LONG" else o[i]-c[i])>=displacement_atr*atr[i]
                breaks_base=c[i]>top if bias=="LONG" else c[i]<bottom
                if displacement and breaks_base and top>bottom:
                    active={"version":1,"strategy":MODE,"side":bias,"formedIndex":i,
                            "sweepTime":pending["sweepTime"],"liquidity":copy.deepcopy(pending["liquidity"]),
                            "zone":{"bottom":bottom,"top":top,"pivotTime":ts[start].isoformat(),"confirmedTime":(ts[i]+step).isoformat(),"touchTime":None,"bounceTime":ts[i].isoformat()},
                            "opposingZone":copy.deepcopy(pending["targetZone"]),
                            "target":pending["targetZone"]["top"] if bias=="LONG" else pending["targetZone"]["bottom"]}
                    active["liquidity"].pop("knownIndex",None);active["opposingZone"].pop("index",None)
                    pending=None
        pool=pools.get(bias)
        if bias and target_zone and pool and not pool["used"] and i>pool["knownIndex"] and i-pool["knownIndex"]<=64 and not pending and not active and result[i] is None:
            swept=(l[i]<pool["bottom"] and c[i]>pool["top"] if bias=="LONG" else h[i]>pool["top"] and c[i]<pool["bottom"])
            if swept:
                pool["used"]=True
                pending={"side":bias,"sweepIndex":i,"sweepTime":ts[i].isoformat(),"liquidity":copy.deepcopy(pool),"targetZone":copy.deepcopy(target_zone)}
    return result
