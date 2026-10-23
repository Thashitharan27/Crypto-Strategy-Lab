"""Causal research preset combining sweep, structure, inverse FVG and FVG retracement.

This is an explicit mechanical interpretation, not a claim to reproduce all of
any educator's discretionary entries. All pivots require right-hand confirmation.
"""
import copy
import numpy as np
import pandas as pd

MODE = "TJR_CONFLUENCE"


def validate_settings(displacement, wait, lookback, body_percent, target_r, min_sweep_atr=.1):
    if not np.isfinite(min_sweep_atr) or min_sweep_atr<0:
        raise ValueError("Confluence minimum sweep depth must be finite and non-negative")
    if not np.isfinite(displacement) or displacement <= 0:
        raise ValueError("Confluence displacement must be finite and positive")
    for value,label,limit in ((wait,"maximum wait",500),(lookback,"FVG lookback",500)):
        if not np.isfinite(value) or int(value)!=value or not 1<=value<=limit:
            raise ValueError(f"Confluence {label} must be an integer from 1 to {limit}")
    if not np.isfinite(body_percent) or not 0<=body_percent<=100:
        raise ValueError("Confluence reversal body percentage must be from 0 to 100")
    if not np.isfinite(target_r) or target_r<=0:
        raise ValueError("Confluence target R must be finite and positive")


def confluence_setups(times, opens, highs, lows, closes, atr_values, *, strength=2,
                      timeframe_minutes=15, displacement_atr=.5, max_wait=30,
                      fvg_lookback=64, min_body_percent=50., require_structure=True,
                      require_ifvg=True, require_equilibrium=True,
                      require_live_confirmations=True, min_sweep_atr=.1):
    from crypto_strategy_lab.supply_demand_retest import validate_settings as validate_swing
    validate_swing(strength,0.,1.)
    validate_settings(displacement_atr,max_wait,fvg_lookback,min_body_percent,3.,min_sweep_atr)
    ts=pd.DatetimeIndex(pd.to_datetime(times,utc=True))
    arrays=[np.asarray(a,dtype=float) for a in (opens,highs,lows,closes,atr_values)]
    if any(a.ndim!=1 or len(a)!=len(ts) for a in arrays) or ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("Confluence candles must align with unique increasing timestamps")
    o,h,l,c,atr=arrays;step=pd.Timedelta(minutes=timeframe_minutes)
    pivots={"LONG":[],"SHORT":[]};gaps=[];pending={};segment=0
    result=[None]*len(ts)
    for i,t in enumerate(ts):
        valid=all(np.isfinite(a[i]) for a in arrays[:4]) and l[i]<=min(o[i],c[i])<=max(o[i],c[i])<=h[i]
        if (i and t-ts[i-1]!=step) or not valid:
            pivots={"LONG":[],"SHORT":[]};gaps=[];pending={};segment=i if valid else i+1
        if not valid:
            continue
        # Only still-valid, recent FVGs can be inverted by a new sweep setup.
        gaps=[g for g in gaps if i-g["index"]<=fvg_lookback and not (c[i]<g["bottom"] if g["side"]=="LONG" else c[i]>g["top"])]
        new_gap=None
        if i-2>=segment and np.isfinite(atr[i-1]) and atr[i-1]>0:
            bull=l[i]>h[i-2] and c[i-1]-o[i-1]>=displacement_atr*atr[i-1]
            bear=h[i]<l[i-2] and o[i-1]-c[i-1]>=displacement_atr*atr[i-1]
            if bull or bear:
                new_gap={"side":"LONG" if bull else "SHORT","index":i,
                         "bottom":float(h[i-2] if bull else h[i]),"top":float(l[i] if bull else l[i-2]),
                         "pivotTime":ts[i-2].isoformat(),"confirmedTime":(t+step).isoformat()}
        candidates=[]
        for side,p in list(pending.items()):
            long=side=="LONG"
            broken=l[i]<=p["sweepExtreme"] if long else h[i]>=p["sweepExtreme"]
            if broken or i-p["sweepIndex"]>max_wait:
                del pending[side];continue
            p["impulseExtreme"]=max(p["impulseExtreme"],h[i]) if long else min(p["impulseExtreme"],l[i])
            if p["structureTime"] is None and p["structureLevel"] is not None and (c[i-1]<=p["structureLevel"]<c[i] if long else c[i-1]>=p["structureLevel"]>c[i]):
                p["structureTime"]=(t+step).isoformat()
            inv=p["inverseFvg"]
            if inv and p["inverseTime"] is None and (c[i]>inv["top"] if long else c[i]<inv["bottom"]):
                p["inverseTime"]=(t+step).isoformat()
            if require_live_confirmations and not confirmations_hold(p,c[i],side,require_structure,require_ifvg):
                del pending[side];continue
            if p.get("zone"):
                z=p["zone"]
                invalid=c[i]<z["bottom"] if long else c[i]>z["top"]
                if invalid:
                    del pending[side];continue
                touch=l[i]<=z["entryTop"] and h[i]>=z["entryBottom"]
                directional=c[i]>o[i] if long else c[i]<o[i]
                body=abs(c[i]-o[i]);span=h[i]-l[i]
                discount=(c[i]<=p["equilibrium"] if long else c[i]>=p["equilibrium"])
                if i>p["armedIndex"] and touch and directional and span>0 and body>=min_body_percent/100*span and (not require_equilibrium or discount):
                    setup=copy.deepcopy(p)
                    for key in ("sweepIndex","armedIndex","impulseExtreme"):
                        setup.pop(key,None)
                    setup.update(version=1,strategy=MODE,side=side,signalTime=t.isoformat(),
                                 requiredStructure=bool(require_structure),requiredIfvg=bool(require_ifvg),requiredEquilibrium=bool(require_equilibrium),
                                 requiredLiveConfirmations=bool(require_live_confirmations),minimumSweepDepthAtr=float(min_sweep_atr),
                                 minReversalBodyPercent=float(min_body_percent),reversalBodyPercent=float(100*body/span),
                                 target=None,opposingZone=None)
                    setup["zone"]["touchTime"]=t.isoformat();setup["zone"]["bounceTime"]=t.isoformat()
                    candidates.append(setup);del pending[side]
                continue
            previous_gap=p.get("candidateGap")
            if previous_gap and (c[i]<previous_gap["bottom"] if long else c[i]>previous_gap["top"]):
                p.pop("candidateGap",None)
            if new_gap and new_gap["side"]==side and new_gap["index"]-2>=p["sweepIndex"]:
                p["candidateGap"]=copy.deepcopy(new_gap)
            ready=(not require_structure or p["structureTime"] is not None) and (not require_ifvg or p["inverseTime"] is not None)
            g=p.get("candidateGap")
            if ready and g:
                midpoint=float((p["sweepExtreme"]+p["impulseExtreme"])/2)
                bottom=g["bottom"];top=g["top"]
                entry_bottom=bottom if long or not require_equilibrium else max(bottom,midpoint)
                entry_top=min(top,midpoint) if long and require_equilibrium else top
                if entry_bottom<entry_top and (c[i]>=bottom if long else c[i]<=top):
                    p["zone"]={**copy.deepcopy(g),"entryBottom":entry_bottom,"entryTop":entry_top,"touchTime":None,"bounceTime":None}
                    p["equilibrium"]=midpoint;p["rangeLow"]=float(p["sweepExtreme"] if long else p["impulseExtreme"])
                    p["rangeHigh"]=float(p["impulseExtreme"] if long else p["sweepExtreme"])
                    p["armedIndex"]=i;p["armedTime"]=(t+step).isoformat()
        # Unknown intrabar order: never choose a direction if both sides confirm.
        if len(candidates)==1:
            result[i]=candidates[0]
        if np.isfinite(atr[i]) and atr[i]>0:
            sweeps=[]
            for side in ("LONG","SHORT"):
                long=side=="LONG";other="SHORT" if long else "LONG"
                eligible=[p for p in pivots[side] if not p["used"] and i-p["index"]<=fvg_lookback]
                pivot=eligible[-1] if eligible else None
                for crossed in eligible:
                    if l[i]<crossed["price"] if long else h[i]>crossed["price"]:
                        crossed["used"]=True
                if pivot and (l[i]<pivot["price"] if long else h[i]>pivot["price"]):
                    pivot["used"]=True
                    reclaimed=c[i]>pivot["price"] if long else c[i]<pivot["price"]
                    structures=[p for p in pivots[other] if not p["used"] and i-p["index"]<=fvg_lookback]
                    structure=structures[-1] if structures else None
                    opposite=[g for g in gaps if g["side"]==other]
                    inv=copy.deepcopy(opposite[-1]) if opposite else None
                    depth=abs(pivot["price"]-(l[i] if long else h[i]))/atr[i]
                    if depth>=min_sweep_atr and reclaimed and side not in pending and (not require_structure or structure) and (not require_ifvg or inv):
                        sweeps.append((side,pivot,structure,inv))
            if len(sweeps)==1:
                side,pivot,structure,inv=sweeps[0];long=side=="LONG"
                pending[side]={"side":side,"sweepIndex":i,"sweepTime":t.isoformat(),
                    "liquidityLevel":pivot["price"],"liquidityTime":pivot["time"],
                    "sweepExtreme":float(l[i] if long else h[i]),"setupAtr":float(atr[i]),
                    "sweepDepthAtr":float(abs(pivot["price"]-(l[i] if long else h[i]))/atr[i]),
                    "impulseExtreme":float(h[i] if long else l[i]),
                    "structureLevel":structure["price"] if structure else None,
                    "structureTime":None,"inverseFvg":inv,"inverseTime":None}
        if new_gap:
            gaps.append(new_gap)
        # New pivots become usable on the next candle, never retroactively.
        j=i-strength
        if j-strength>=segment:
            for side,prices,compare in (("LONG",l,np.less),("SHORT",h,np.greater)):
                if compare(prices[j],np.r_[prices[j-strength:j],prices[j+1:i+1]]).all():
                    pivots[side].append({"index":j,"price":float(prices[j]),"time":ts[j].isoformat(),"used":False})
                    pivots[side]=[p for p in pivots[side] if i-p["index"]<=fvg_lookback]
    return result


def confirmations_hold(setup, price, side, require_structure=True, require_ifvg=True):
    """Only activated, required confirmations can invalidate a pending setup.

    Equality holds; a close (or actual entry fill) strictly through the defended
    edge fails. An IFVG defends its far edge, not the inversion breakout edge.
    """
    long=side=="LONG"
    if require_structure and setup.get("structureTime") is not None:
        level=setup["structureLevel"]
        if price<level if long else price>level:
            return False
    if require_ifvg and setup.get("inverseTime") is not None and setup.get("inverseFvg"):
        gap=setup["inverseFvg"]
        if price<gap["bottom"] if long else price>gap["top"]:
            return False
    return True
