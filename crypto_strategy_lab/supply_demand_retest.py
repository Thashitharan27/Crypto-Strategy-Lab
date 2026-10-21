"""Causal one-hour swing-zone bounce/retest research preset."""
from dataclasses import replace
import copy
import json

import numpy as np
import pandas as pd

MODE = "SUPPLY_DEMAND_RETEST"


def validate_settings(strength, buffer, minimum_r):
    if not np.isfinite(strength) or int(strength) != strength or not 1 <= strength <= 20:
        raise ValueError("Supply/demand swing strength must be an integer from 1 to 20")
    if not np.isfinite(buffer) or buffer < 0:
        raise ValueError("Supply/demand stop buffer must be finite and non-negative")
    if not np.isfinite(minimum_r) or minimum_r <= 0:
        raise ValueError("Supply/demand minimum reward/risk must be finite and positive")


def retest_setups(times, opens, highs, lows, closes, strength=2):
    """Pivot zones become available only after all right-hand bars have closed.

    Latest confirmed zone per side; first qualified retest consumes that zone.
    No retroactive touches during pivot confirmation. Invalid/gapped data clears
    state. All returned dictionaries are detached snapshots of known evidence.
    """
    validate_settings(strength, 0., 1.)
    ts=pd.DatetimeIndex(pd.to_datetime(times,utc=True))
    arrays=[np.asarray(a,dtype=float) for a in (opens,highs,lows,closes)]
    if any(a.ndim!=1 or len(a)!=len(ts) for a in arrays) or not ts.is_monotonic_increasing or ts.has_duplicates:
        raise ValueError("Supply/demand candles must align with unique increasing timestamps")
    o,h,l,c=arrays
    zones={}
    result=[None]*len(ts)
    segment_start=0
    hour=pd.Timedelta(hours=1)
    for i in range(len(ts)):
        if (i and ts[i]-ts[i-1]!=hour) or not all(np.isfinite(a[i]) for a in arrays):
            zones.clear()
            segment_start=i
        if not all(np.isfinite(a[i]) for a in arrays):
            segment_start=i+1
            continue
        candidates=[]
        for side,z in list(zones.items()):
            invalid=c[i]<z["bottom"] if side=="LONG" else c[i]>z["top"]
            if invalid:
                del zones[side]
                continue
            if z["used"]:
                continue
            touch=l[i]<=z["top"] and h[i]>=z["bottom"]
            away=c[i]>z["top"] if side=="LONG" else c[i]<z["bottom"]
            if z["bounceTime"] is not None:
                directional=c[i]>o[i] if side=="LONG" else c[i]<o[i]
                if touch and directional:
                    other=zones.get("SHORT" if side=="LONG" else "LONG")
                    z["used"]=True
                    if other:
                        candidates.append({"version":1,"side":side,"zone":copy.deepcopy(z),
                                           "opposingZone":copy.deepcopy(other),"signalTime":ts[i].isoformat(),
                                           "target":other["top"] if side=="LONG" else other["bottom"]})
            else:
                if touch and z["touchTime"] is None:
                    z["touchTime"]=ts[i].isoformat()
                if z["touchTime"] is not None and away:
                    z["bounceTime"]=ts[i].isoformat()
        if len(candidates)==1:
            result[i]=candidates[0]
        # A confirmed pivot may only be used by subsequent candles.
        j=i-strength
        if j-strength < segment_start:
            continue
        for side,values,compare in (("LONG",l,np.less),("SHORT",h,np.greater)):
            neighbours=np.r_[values[j-strength:j],values[j+1:i+1]]
            if np.isfinite(neighbours).all() and compare(values[j],neighbours).all() and h[j]>l[j]:
                zones[side]={"bottom":float(l[j]),"top":float(h[j]),"pivotTime":ts[j].isoformat(),
                             "confirmedTime":(ts[i]+hour).isoformat(),"touchTime":None,"bounceTime":None,"used":False}
    return result


class SupplyDemandRetestMixin:
    def _configure_signal_features(self):
        super()._configure_signal_features()
        if not any(r.get("_strategy_direction_mode")==MODE for p in self.config.strategy_profiles.values() for r in getattr(p,"entry_rules",())):
            return
        if self.config.strategy_timeframe_minutes != 60:
            raise ValueError("Supply/demand retest uses the 1h strategy timeframe")
        self.sd_setups=retest_setups(self.times,self.open,self.high,self.low,self.close,self.config.sd_swing_strength)

    def _infer_signal_strategy_mode(self):
        if any(r.get("_strategy_direction_mode")==MODE for p in self.config.strategy_profiles.values() for r in getattr(p,"entry_rules",())):
            return MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self,i):
        if getattr(self,"signal_strategy_mode",None)==MODE:
            return self.sd_setups[i]["side"] if self.sd_setups[i] else None
        return super()._selected_direction(i)

    def _should_enter(self,i):
        if getattr(self,"signal_strategy_mode",None)==MODE:
            return self._selected_direction(i) in {"LONG","SHORT"}
        return super()._should_enter(i)

    def _entry_decision(self,i,active_at_candle_start=False):
        if getattr(self,"signal_strategy_mode",None)!=MODE:
            return super()._entry_decision(i,active_at_candle_start)
        if i+1>=len(self.times) or not self._should_enter(i) or pd.Timestamp(self.times[i+1])-pd.Timestamp(self.times[i])!=pd.Timedelta(hours=1):
            return None
        return {"execution_index":i+1,"indicator_index":i,"scheduled_timestamp":pd.Timestamp(self.times[i+1]),
                "actual_entry_timestamp":None,"entry_schedule_status":"NEXT_CANDLE_OPEN", "fill_price_source":"NEXT_CANDLE_OPEN","defer_to_next_open":True}

    def _profile_context(self,i):
        context=super()._profile_context(i)
        if getattr(self,"signal_strategy_mode",None)!=MODE or context is None:
            return context
        profile=replace(context[3],reward_risk_ratio=1.,stop_loss_multiple=1.,position_sizing_stop_override_enabled=False,
                        partial_profit_enabled=False,partial_stop_enabled=False,trailing_enabled=False,break_even_enabled=False,
                        r_step_trailing_enabled=False,atr_checkpoint_tp_extension_enabled=False,timeout_enabled=False)
        return (*context[:3],profile)

    def _sr_stop_plan(self,i,execution_i=None):
        if getattr(self,"signal_strategy_mode",None)!=MODE:
            return super()._sr_stop_plan(i,execution_i)
        setup=self.sd_setups[i]
        side=self._effective_trade_direction(i)
        reject={"passed":False,"applied":False,"reason":"SD_ENTRY_GEOMETRY_REJECTED","distance":None}
        if not setup or side!=setup["side"]:
            return reject
        entry=float(self._expected_entry_price(i,execution_i,side))
        atr=float(self.atr_values[i])
        if not np.isfinite(atr) or atr<=0:
            return reject
        zone=setup["zone"]
        buffer=self.config.sd_stop_buffer_atr*atr
        stop=zone["bottom"]-buffer if side=="LONG" else zone["top"]+buffer
        risk=entry-stop if side=="LONG" else stop-entry
        reward=setup["target"]-entry if side=="LONG" else entry-setup["target"]
        if not np.isfinite([entry,risk,reward]).all() or risk<=0 or reward<=0 or reward/risk<self.config.sd_minimum_r:
            return reject
        return {"passed":True,"applied":True,"reason":"SD_ZONE_STOP","distance":risk,"stop_price":stop,
                "boundary_price":stop,"level_price":setup["target"],"distance_atr":risk/atr,"timeframe_minutes":60}

    def _apply_sr_take_profit(self,i,pair):
        if getattr(self,"signal_strategy_mode",None)!=MODE:
            return super()._apply_sr_take_profit(i,pair)
        for pos in pair.positions():
            pos.tp=float(self.sd_setups[i]["target"])

    def _sr_tp_filter_result(self,i,execution_i=None):
        if getattr(self,"signal_strategy_mode",None)==MODE:
            return True,None
        return super()._sr_tp_filter_result(i,execution_i)

    def _open_pair(self,i,entry_filter_passed=True,entry_filter_reason="Strategy profile passed",schedule=None):
        before=len(self.active_pairs)
        result=super()._open_pair(i,entry_filter_passed,entry_filter_reason,schedule)
        if getattr(self,"signal_strategy_mode",None)==MODE and len(self.active_pairs)>before:
            j=schedule["indicator_index"] if schedule else i
            self.active_pairs[-1].sd_setup=copy.deepcopy(self.sd_setups[j])
        return result

    def _build_result_row(self,pair,row_kind,positions):
        row=super()._build_result_row(pair,row_kind,positions)
        if getattr(self,"signal_strategy_mode",None)==MODE:
            row["supply_demand_setup"]=json.dumps(getattr(pair,"sd_setup",None),allow_nan=False)
        return row
