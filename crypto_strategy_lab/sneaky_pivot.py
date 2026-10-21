"""All-day, previous-day-level Sneaky Pivot research strategy."""
import numpy as np
import pandas as pd

MODE = "SNEAKY_PIVOT"


def snapshot_levels(prior, pivots, previous):
    """Four distinct roles; absent outside swings stay explicitly unavailable."""
    levels=[{"role":"rangeHigh","label":"Previous day high","price":prior["high"]},
            {"role":"rangeLow","label":"Previous day low","price":prior["low"]}]
    for side,role,label in (("SHORT","swingHigh","Older swing high"),("LONG","swingLow","Older swing low")):
        older=[p for p in pivots[side] if p["time"]<previous and
               (p["price"]>prior["high"] if side=="SHORT" else p["price"]<prior["low"])]
        levels.append({"role":role,"label":label,"price":older[-1]["price"] if older else None})
    return levels


def historical_levels(frame, setup_start, strength=2):
    """Display-only reconstruction for older runs that did not save all levels."""
    cutoff=pd.Timestamp(setup_start);previous=cutoff.normalize()-pd.Timedelta(days=1)
    frame=frame[pd.to_datetime(frame.period_start,utc=True)<cutoff].copy()
    times=pd.DatetimeIndex(pd.to_datetime(frame.period_start,utc=True))
    # Match the engine's missing-candle reset before rebuilding context.
    gaps=np.flatnonzero((times[1:]-times[:-1])!=pd.Timedelta(minutes=15))
    if len(gaps):frame=frame.iloc[gaps[-1]+1:];times=times[gaps[-1]+1:]
    prior=frame[(times>=previous)&(times<cutoff.normalize())]
    if len(prior)!=96:return None
    pivots={"LONG":[],"SHORT":[]}
    for side,key,compare in (("LONG","low",np.less),("SHORT","high",np.greater)):
        prices=frame[key].to_numpy(float)
        for j in range(strength,len(frame)-strength):
            if compare(prices[j],np.r_[prices[j-strength:j],prices[j+1:j+strength+1]]).all():
                pivots[side].append({"time":times[j],"price":float(prices[j])})
    return snapshot_levels({"high":float(prior.high.max()),"low":float(prior.low.min())},pivots,previous)


def validate_settings(tolerance, body, wait, hold):
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Sneaky Pivot level tolerance must be finite and non-negative")
    if not np.isfinite(body) or body <= 0:
        raise ValueError("Sneaky Pivot minimum body ATR must be finite and positive")
    if hold < 15*(wait+2):
        raise ValueError("Sneaky Pivot holding limit must cover the confirmation and breakout window")
    for value, label, maximum in ((wait, "confirmation wait", 20), (hold, "holding minutes", 100000)):
        if not np.isfinite(value) or int(value) != value or not 1 <= value <= maximum:
            raise ValueError(f"Sneaky Pivot {label} must be an integer from 1 to {maximum}")


def sneaky_setups(times, opens, highs, lows, closes, atr_values, *, tolerance=.3,
                  body_atr=.5, wait=3, strength=2, buffer=.05):
    """Signal at confirmation close; breakout order expires after the next bar.

    Previous complete UTC day and older confirmed pivots are frozen per setup.
    ATR of the preceding completed candle is frozen at setup initiation.
    Missing candles reset context; incomplete UTC days supply no range.
    """
    validate_settings(tolerance, body_atr, wait, 1440)
    from .supply_demand_retest import validate_settings as validate_zone
    validate_zone(strength, buffer, 1.)
    ts = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    arrays = [np.asarray(x, dtype=float) for x in (opens, highs, lows, closes, atr_values)]
    if any(x.ndim != 1 or len(x) != len(ts) for x in arrays) or ts.has_duplicates or not ts.is_monotonic_increasing:
        raise ValueError("Sneaky Pivot candles must align with unique increasing timestamps")
    o,h,l,c,atr = arrays
    step = pd.Timedelta(minutes=15)
    result = [None]*len(ts)
    pivots = {"LONG": [], "SHORT": []}
    days = {}; pending = []; segment = 0
    for i,t in enumerate(ts):
        valid = all(np.isfinite(x[i]) for x in arrays[:4])
        if (i and t-ts[i-1] != step) or not valid:
            pending=[];days={};pivots={"LONG":[],"SHORT":[]};segment=i if valid else i+1
        if not valid:
            continue
        day=t.normalize(); previous=day-pd.Timedelta(days=1)
        # Process pending setups before initiating a new one on this candle.
        surviving=[]; candidates=[]
        for p in pending:
            side=p["side"];long=side=="LONG"
            if (l[i]<=p["stop"] if long else h[i]>=p["stop"]):
                continue
            if (c[i]>o[i] if long else c[i]<o[i]):
                zone={"bottom":min(p["low"],l[i],p["level"]),"top":max(p["high"],h[i],p["level"]),
                      "pivotTime":p["start"],"confirmedTime":(t+step).isoformat(),
                      "touchTime":p["start"],"bounceTime":t.isoformat()}
                candidates.append({"version":1,"strategy":MODE,"side":side,"zone":zone,
                    "opposingZone":{"bottom":p["rangeLow"],"top":p["rangeHigh"],"pivotTime":p["rangeStart"],"confirmedTime":p["rangeEnd"]},
                    "signalTime":t.isoformat(),"target":p["rangeHigh"] if long else p["rangeLow"],
                    "trigger":float(h[i] if long else l[i]),"stop":p["stop"],
                    "stopSource":"Older swing low" if long else "Older swing high",
                    "stopSwingTime":p["stopSwingTime"],
                    "setupStart":p["start"],"level":p["level"],"levelName":p["levelName"],"setupAtr":p["atr"],
                    "levels":p["levels"],"levelsSource":"Saved at setup"})
            elif i-p["index"] < wait:
                surviving.append(p)
        pending=surviving
        if candidates:
            # Earliest initial candle wins if several confirm simultaneously.
            result[i]=candidates[0]
        prior=days.get(previous)
        if prior and prior["count"]==96 and i and np.isfinite(atr[i-1]) and atr[i-1]>0:
            av=float(atr[i-1]);body=abs(c[i]-o[i])
            if body>=body_atr*av and body>=.5*(h[i]-l[i]):
                side="LONG" if c[i]<o[i] else "SHORT";long=side=="LONG"
                level=prior["low"] if long else prior["high"]
                older=[p for p in pivots[side] if p["time"]<previous and (p["price"]<prior["low"] if long else p["price"]>prior["high"])]
                # The day boundary is the entry test; the outside swing is
                # exclusively the stop anchor. Never substitute one for the other.
                touches=l[i]<=level<=h[i]
                near=abs((l[i] if long else h[i])-level)<=tolerance*av
                swing=older[-1] if older else None
                intact=swing is not None and (l[i]>swing["price"] if long else h[i]<swing["price"])
                if touches and near and intact:
                    name="Previous range low" if long else "Previous range high"
                    pending.append({"levels":snapshot_levels(prior,pivots,previous),"rangeStart":previous.isoformat(),"rangeEnd":day.isoformat(),"index":i,"side":side,"start":t.isoformat(),"level":float(level),"levelName":name,"atr":av,
                        "low":float(l[i]),"high":float(h[i]),"rangeLow":prior["low"],"rangeHigh":prior["high"],
                        "stop":float(swing["price"]),"stopSwingTime":swing["time"].isoformat()})
        # Confirmed pivots can only affect future candles/days.
        j=i-strength
        if j-strength>=segment:
            for side,prices,compare in (("LONG",l,np.less),("SHORT",h,np.greater)):
                if compare(prices[j],np.r_[prices[j-strength:j],prices[j+1:i+1]]).all():
                    pivots[side].append({"time":ts[j],"price":float(prices[j])})
        d=days.setdefault(day,{"count":0,"high":-np.inf,"low":np.inf})
        d["count"]+=1;d["high"]=max(d["high"],float(h[i]));d["low"]=min(d["low"],float(l[i]))
        days={key:value for key,value in days.items() if key>=previous}
    return result


class SneakyPivotMixin:
    def _configure_signal_features(self):
        super()._configure_signal_features()
        if not any(r.get("_strategy_direction_mode")==MODE for p in self.config.strategy_profiles.values() for r in getattr(p,"entry_rules",())):
            return
        if self.config.strategy_timeframe_minutes != 15 or not self.config.use_intrabar_data or self.config.intrabar_timeframe_minutes != 1:
            raise ValueError("Sneaky Pivot requires 15m strategy candles and 1m execution data")
        self.sd_setups=sneaky_setups(self.times,self.open,self.high,self.low,self.close,self.atr_values,
            tolerance=self.config.sp_level_tolerance_atr,body_atr=self.config.sp_body_atr,
            wait=self.config.sp_confirmation_bars,strength=self.config.sd_swing_strength,buffer=self.config.sd_stop_buffer_atr)

    def _entry_decision(self,i,active_at_candle_start=False):
        decision=super()._entry_decision(i,active_at_candle_start)
        if getattr(self,"signal_strategy_mode",None)==MODE and decision:
            if self.active_pairs or active_at_candle_start:return None
            last_exit=getattr(self,"_sneaky_last_exit",None)
            if last_exit is not None and pd.Timestamp(self.sd_setups[i]["setupStart"])<=last_exit:
                return None
            decision["sneaky_breakout"]=True
            decision["fill_price_source"]="SNEAKY_BREAKOUT"
        return decision

    def _build_result_row(self,pair,row_kind,positions):
        row=super()._build_result_row(pair,row_kind,positions)
        if getattr(self,"signal_strategy_mode",None)==MODE and row.get("exit_time") is not None:
            stamp=pd.Timestamp(row["exit_time"])
            if not pd.isna(stamp):
                self._sneaky_last_exit=stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return row

    def _execute_pending_next_open_entry(self,i,active_at_candle_start=False):
        decision=getattr(self,"pending_next_open_entry",None)
        if not decision or not decision.get("sneaky_breakout"):
            return super()._execute_pending_next_open_entry(i,active_at_candle_start)
        if decision["execution_index"]!=i:return
        self.pending_next_open_entry=None
        j=decision["indicator_index"];setup=self.sd_setups[j]
        if active_at_candle_start or self.active_pairs or not self._in_trading_window(i):return
        # Same coverage contract as the native pending Fibonacci orders.
        start=pd.Timestamp(self.times[i]);end=start+self.entry_delta
        frame=self.intrabar_data
        if frame is None:
            raise ValueError("Sneaky Pivot breakout requires complete 1m coverage")
        from .entry_plan import has_complete_intrabar_window
        if hasattr(frame,"fast_window"):
            window=frame.fast_window(start,end)
            rows=[] if window is None or window.empty else list(window.rows())
            candles=[(pd.Timestamp(t),float(o),float(h),float(l)) for _,t,o,h,l in rows]
        else:
            window=frame[(frame.timestamp>=start)&(frame.timestamp<end)]
            candles=[(pd.Timestamp(r.timestamp),float(r.open),float(r.high),float(r.low)) for r in window.itertuples()]
        if not has_complete_intrabar_window([r[0] for r in candles],start,end,pd.Timedelta(minutes=1)):
            raise ValueError("Sneaky Pivot breakout requires complete 1m coverage")
        long=setup["side"]=="LONG";trigger=setup["trigger"]
        for timestamp,opening,high,low in candles:
            # Cancel before filling on ambiguous minutes touching both levels.
            # A breakout already present at the minute open has known ordering.
            invalidated=low<=setup["stop"] if long else high>=setup["stop"]
            open_break=opening>trigger if long else opening<trigger
            if invalidated and not open_break:
                return
            if high>trigger if long else low<trigger:
                raw=max(opening,trigger) if long else min(opening,trigger)
                decision.update(fill_price=raw,actual_entry_timestamp=timestamp,entry_schedule_status="SNEAKY_BREAKOUT_FILLED")
                self._sneaky_fill=raw
                try:
                    passed,reason=self._entry_filter_result(j,i)
                    if passed:
                        before=len(self.active_pairs)
                        self._open_pair(i,passed,reason,decision)
                        if len(self.active_pairs)>before:
                            pair=self.active_pairs[-1]
                            deadline=pd.Timestamp(setup["setupStart"])+pd.Timedelta(minutes=self.config.sp_hold_minutes)
                            pair.profile_timeout_enabled=True
                            pair.profile_timeout_minutes=max(1,int((deadline-(timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC"))).total_seconds()/60))
                            for pos in pair.positions():
                                # Native conservative intrabar-entry exit handling.
                                pos.fib_limit_fill_time=timestamp;pos.fib_limit_fill_price=raw
                                self._scan_position_exit(pair,pos,i)
                    else:self._record_skipped_signal(j,reason)
                finally:self._sneaky_fill=None
                return

    def _expected_entry_price(self,indicator_i,execution_i,direction):
        raw=getattr(self,"_sneaky_fill",None)
        if raw is not None and getattr(self,"signal_strategy_mode",None)==MODE:
            return raw*(1+self.config.slippage if direction=="LONG" else 1-self.config.slippage)
        return super()._expected_entry_price(indicator_i,execution_i,direction)

    def _sr_stop_plan(self,i,execution_i=None):
        if getattr(self,"signal_strategy_mode",None)!=MODE:return super()._sr_stop_plan(i,execution_i)
        setup=self.sd_setups[i];side=self._effective_trade_direction(i)
        reject={"passed":False,"applied":False,"reason":"SNEAKY_ENTRY_GEOMETRY_REJECTED","distance":None}
        if not setup or side!=setup["side"]:return reject
        entry=self._expected_entry_price(i,execution_i,side);stop=setup["stop"]
        sign=1 if side=="LONG" else -1;risk=sign*(entry-stop);reward=sign*(setup["target"]-entry)
        if not np.isfinite([entry,risk,reward]).all() or risk<=0 or reward<=0:return reject
        return {"passed":True,"applied":True,"reason":"SNEAKY_OLDER_SWING_STOP","distance":risk,"stop_price":stop,
                "boundary_price":stop,"level_price":setup["target"],"distance_atr":risk/setup["setupAtr"],"timeframe_minutes":15}
