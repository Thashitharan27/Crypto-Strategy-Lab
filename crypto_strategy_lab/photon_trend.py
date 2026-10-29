"""Backtest-only 4H-trend / 15m-value / 1m-CHoCH confirmation strategy.

Numerical defaults and the last-opposing-candle zone rule are explicit research
choices. No counter-4H orders, same-confirmation-candle fills or FX pip stops.
"""
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
import json
from math import isfinite
from bisect import bisect_right

import numpy as np
import pandas as pd

from .photon_structure import aggregate_closed, map_structure, valid_bar
from .photon_zones import attach_ranges, build_zones

MODE = "PHOTON_4H_TREND"
LABEL = "Photon — Automated Trades / 1m Confirmation"


def selected(profiles):
    if not isinstance(profiles,Mapping):return False
    return any(r.get("_strategy_direction_mode")==MODE for p in profiles.values()
               for r in getattr(p,"entry_rules",()))


def validate_settings(confirmation, retest, timeframe=None, active=False):
    for value,label in ((confirmation,"confirmation timeout"),(retest,"retest timeout")):
        if isinstance(value,bool) or not isfinite(value) or int(value)!=value or not 1<=value<=10080:
            raise ValueError(f"Photon {label} must be an integer from 1 to 10080 minutes")
    if active and timeframe!=1:
        raise ValueError("Photon 4H Trend requires actual 1m strategy candles")


def prepare_context(bars, *, zone_reversal=False, lesson_options=None):
    result={};natives={}
    for tf,seconds,offset in (("1m",60,0),("15m",900,0),("4h",14400,0),("1d",86400,0),("1w",604800,345600)):
        native=bars if tf=="1m" else aggregate_closed(bars,60,seconds,offset)
        natives[tf]=native
        guide=map_structure(native,seconds,qualification="CHOCH_PULLBACK",
                            intrabars=bars if zone_reversal and seconds>60 else None, intrabar_interval=60)
        if tf=="1m" and not zone_reversal:
            # Only internal-break evidence is required on the execution chart.
            guide["snapshots"]=[];guide["trace"]=[]
        else:
            attach_ranges(guide)
            if tf in (("15m","4h","1d") if zone_reversal else ("15m","4h")):
                guide["supplyDemand"]=build_zones(bars,native,guide,tf,source_interval=60)
        result[tf]=guide
    from .photon_lesson import apply_to_guides
    return apply_to_guides(result,natives,bars,60,lesson_options)


def resolve_retest(order, candle):
    """Proximal limit, with gap improvement; never fill beyond the stop."""
    long=order["side"]=="LONG";entry=order["entry"];stop=order["stop"]
    if candle["open"]<=stop if long else candle["open"]>=stop:
        return "INVALIDATED",None
    target=order.get("target")
    if target is not None and (candle["open"]>=target if long else candle["open"]<=target):
        return "INVALIDATED",None
    touched=candle["low"]<=entry if long else candle["high"]>=entry
    if not touched:
        return "WAITING",None
    return "FILLED",min(candle["open"],entry) if long else max(candle["open"],entry)


def review_checks(campaign, current, entry, sign):
    """Decision-time preferences, never future outcomes or entry permission."""
    checks=[]
    def add(code,label,passed,detail):
        checks.append(dict(code=code,label=label,passed=bool(passed),detail=detail))
    preferred="discount / EQ" if sign==1 else "premium / EQ"
    for tf,label,bounds in (("4H","4H",current['4h']['range']),
                            ("15M","15m",campaign['leg'])):
        eq=bounds['equilibrium']
        location='discount' if entry<eq else 'premium' if entry>eq else 'EQ'
        add(tf+'_ENTRY_VALUE',label+' entry in '+preferred,
            entry<=eq if sign==1 else entry>=eq,
            f'{"Buy" if sign==1 else "Sell"} planned in {label} {location}. Entry {entry:g}; midpoint {eq:g}.')
    add('CONTEXT_4H_VALUE','Initial reaction in 4H '+preferred,
        campaign.get('contextInValue',True),
        'Initial zone touch '+('reached' if campaign.get('contextInValue',True) else 'did not reach')+
        f' 4H {preferred}; midpoint {campaign["contextRange"]["equilibrium"]:g}.')
    add('FRESH_15M_CONFIRMATION','Fresh 15m confirmation after the context touch',
        campaign.get('alignmentType','FRESH_EVENT')=='FRESH_EVENT',
        'Accepted existing 15m alignment; no new break was required after this touch.'
        if campaign.get('alignmentType')=='EXISTING_ALIGNMENT' else '15m confirmation followed the context touch.')
    m=current['15m']
    add('15M_SWING_ALIGNMENT','15m swing aligned with 4H',m['trend']==sign,
        'Internal structure supports entry while the 15m swing opposes 4H. Value and target still use the saved 15m swing range.'
        if m['trend']!=sign else '15m swing and 4H swing agree.')
    for tf,label in (('1d','Daily'),('1w','Weekly')):
        state=current.get(tf);trend=state['trend'] if state else 0
        add(tf.upper()+'_CONTEXT',label+' context aligned with 4H',trend==sign,
            label+(' context is unknown.' if not trend else ' context opposes 4H.' if trend!=sign else ' context agrees with 4H.'))
    mismatches=[deepcopy(c) for c in checks if not c['passed']]
    return dict(checks=checks,mismatches=mismatches,
                status='REVIEW_REQUIRED' if mismatches else 'PREFERRED_ALIGNMENT')


def trend_setups(bars, atr_values, *, confirmation_minutes=1440,retest_minutes=60,
                 stop_buffer_atr=.05,minimum_r=1.,target_4h=False,flexible=False,guides=None):
    """Forward-only staged orders, plus their validity at each completed minute.

    Strict mode requires a value reaction, fresh 15m alignment and a later
    pullback in both value halves. Flexible mode accepts existing swing or
    internal alignment and records value preferences as review warnings. Both
    require known 15m demand/supply, later 1m CHoCH and a subsequent origin retest.
    """
    validate_settings(confirmation_minutes,retest_minutes)
    if len(bars)!=len(atr_values):raise ValueError("Photon ATR must align with 1m candles")
    if not isfinite(stop_buffer_atr) or stop_buffer_atr<0 or not isfinite(minimum_r) or minimum_r<=0:
        raise ValueError("Photon stop buffer and minimum R must be finite and non-negative / positive")
    if any(bars[i]["time"]<=bars[i-1]["time"] for i in range(1,len(bars))):
        raise ValueError("Photon requires unique increasing 1m timestamps")
    guides=prepare_context(bars) if guides is None else guides
    snapshots={tf:iter(g["snapshots"]) for tf,g in guides.items() if tf!="1m"}
    upcoming={tf:next(it,None) for tf,it in snapshots.items()};state={}
    updates=defaultdict(list);events=defaultdict(list)
    for tf,g in guides.items():
        for e in g["events"]:
            if e["kind"] in ("CHOCH","BOS","TREND_CHANGE"):events[e["availableAt"]].append((tf,e))
        for z in g.get("supplyDemand",{}).get("zones",[]):updates[z["availableAt"]].append(("CREATE",z))
        for e in g.get("supplyDemand",{}).get("events",[]):updates[e["availableAt"]].append(("UPDATE",e))
    zones={};signals=[None]*len(bars);live=[None]*len(bars);campaign=None;pending=None;used=set()
    indices={b["time"]:i for i,b in enumerate(bars)}
    for i,b in enumerate(bars):
        at=b["time"]+60
        gap=not valid_bar(b) or i>0 and b["time"]-bars[i-1]["time"]!=60
        if gap:campaign=pending=None;zones.clear()
        if not valid_bar(b):continue
        # Pending fills use only context that existed BEFORE this minute opened.
        if pending:
            status,_=resolve_retest(pending,b)
            if status!="WAITING":pending=None
        for tf,it in snapshots.items():
            while upcoming[tf] is not None and upcoming[tf]["availableAt"]<=at:
                state[tf]=upcoming[tf];upcoming[tf]=next(it,None)
        for action,item in updates[at]:
            if action=="CREATE":zones[item["id"]]=item
            elif item["kind"] in ("INVALIDATED","RETIRED"):zones.pop(item["zoneId"],None)
        current={tf:s if at<s["availableAt"]+guides[tf]["interval"] else None for tf,s in state.items()}
        h=current.get("4h");m=current.get("15m")
        sign=h["trend"] if h and h.get("range") else 0
        if not sign:campaign=pending=None;continue
        long=sign==1;side="LONG" if long else "SHORT";kind="DEMAND" if long else "SUPPLY"
        protected=h["low"] if long else h["high"]
        protected_key=(protected["time"],protected["price"])
        broken_protection=b["low"]<=protected["price"] if long else b["high"]>=protected["price"]
        m_aligned=bool(m and m.get('range') and (m['trend']==sign or flexible and m['internal']==sign))
        if pending:
            if (at>=pending["expiresAt"] or pending["side"]!=side or broken_protection
                or not m_aligned or pending["parentZoneId"] not in zones or pending["contextZone"]["id"] not in zones
                or (b["high"]>=pending["target"] if long else b["low"]<=pending["target"])):
                pending=None
            else:live[i]=pending["signalIndex"]
        if pending:continue
        if campaign and (campaign["side"]!=side or campaign["protectedKey"]!=protected_key
                         or broken_protection or at-campaign["contextAt"]>confirmation_minutes*60
                         or campaign["contextZone"]["id"] not in zones
                         or campaign.get("parentZoneId") and campaign["parentZoneId"] not in zones):
            campaign=None
        if broken_protection:continue

        def touches(z,eq):
            return min(b["high"],z["upper"],eq if long else float("inf"))>=max(b["low"],z["lower"],eq if not long else -float("inf"))

        def overlaps(z):
            return b['high']>=z['lower'] and b['low']<=z['upper']

        def arm_parent(z):
            campaign.update(stage='WAIT_1M',touchAt=at,parentZoneId=z['id'],parentZone=deepcopy(z),
                            reactionExtreme=b['low'] if long else b['high'])

        if campaign is None:
            matches=[z for z in zones.values() if z["kind"]==kind and z["availableAt"]<at
                     and z["id"] not in used and (overlaps(z) if flexible else touches(z,h["range"]["equilibrium"]))]
            if matches:
                z=max(matches,key=lambda z:(flexible and z['timeframe']=='15m',z["availableAt"]))
                campaign=dict(stage="WAIT_15M",side=side,protectedKey=protected_key,contextAt=at,
                              contextZone=deepcopy(z),contextRange=deepcopy(h["range"]),
                              contextInValue=touches(z,h['range']['equilibrium']))
                if flexible and m_aligned:
                    campaign.update(stage='WAIT_15M_PULLBACK',alignmentAt=m['availableAt'],
                                    alignmentType='EXISTING_ALIGNMENT',leg=deepcopy(m['range']))
                    # An already aligned continuation can use this very 15m
                    # zone pullback. The 1m CHoCH must still occur later.
                    if z['timeframe']=='15m':arm_parent(z)
            continue
        if campaign["stage"]=="WAIT_15M":
            aligned=m_aligned and any(tf=="15m" and e["direction"]==sign for tf,e in events[at])
            if aligned and at>campaign["contextAt"]:
                campaign.update(stage="WAIT_15M_PULLBACK",alignmentAt=at,alignmentType='FRESH_EVENT',leg=deepcopy(m["range"]))
            continue
        if not m_aligned:
            campaign=None;continue
        if campaign["stage"]=="WAIT_15M_PULLBACK":
            campaign["leg"]=deepcopy(m["range"])
            eq=min(h["range"]["equilibrium"],m["range"]["equilibrium"]) if long else max(h["range"]["equilibrium"],m["range"]["equilibrium"])
            matches=[z for z in zones.values() if z["timeframe"]=="15m" and z["kind"]==kind
                     and z["availableAt"]<at and z["id"] not in used and (overlaps(z) if flexible else touches(z,eq))]
            if matches and at>campaign["alignmentAt"]:
                z=max(matches,key=lambda z:z["availableAt"])
                arm_parent(z)
            continue
        campaign["reactionExtreme"]=(min if long else max)(campaign["reactionExtreme"],b["low"] if long else b["high"])
        shift=next((e for tf,e in events[at] if tf=="1m" and e["kind"]=="CHOCH" and e["direction"]==sign),None)
        if not shift or at<=campaign["touchAt"]:continue
        start=max(indices[shift["fromTime"]]+1,indices[campaign["touchAt"]-60])
        extreme=(min if long else max)(range(start,i+1),key=lambda j:bars[j]["low"] if long else bars[j]["high"])
        origins=[j for j in range(extreme,i) if (bars[j]["close"]<bars[j]["open"] if long else bars[j]["close"]>bars[j]["open"])]
        if not origins:continue
        origin=bars[origins[-1]];entry=origin["high"] if long else origin["low"]
        if not (b["close"]>origin["high"] if long else b["close"]<origin["low"]):continue
        av=float(atr_values[i])
        if not isfinite(av) or av<=0:continue
        boundary=(min if long else max)(campaign["reactionExtreme"],origin["low"] if long else origin["high"])
        stop=boundary-sign*stop_buffer_atr*av
        target_state=h if target_4h else m
        target=target_state["range"]["high" if long else "low"]
        risk=sign*(entry-stop);reward=sign*(target-entry)
        eq=min(h["range"]["equilibrium"],campaign["leg"]["equilibrium"]) if long else max(h["range"]["equilibrium"],campaign["leg"]["equilibrium"])
        if (stop<=0 or risk<=0 or reward<=0 or reward/risk<minimum_r
            or not flexible and not (entry<=eq if long else entry>=eq)):continue
        review=review_checks(campaign,current,entry,sign)
        iso=lambda t:pd.Timestamp(t,unit="s",tz="UTC").isoformat()
        zone=dict(bottom=origin["low"],top=origin["high"],pivotTime=iso(origin["time"]),confirmedTime=iso(at),touchTime=iso(campaign["touchAt"]-60),bounceTime=iso(b["time"]))
        pending=dict(version=1,strategy=MODE,side=side,entry=entry,stop=stop,target=target,
                     entryModel='FLEXIBLE_REVIEW' if flexible else 'STRICT_CONFIRMATION',review=review,
                     signalTime=iso(b["time"]),signalAvailableAt=at,signalIndex=i,
                     expiresAt=at+retest_minutes*60,parentZoneId=campaign["parentZoneId"],
                     zone=zone,entryZone=deepcopy(zone),opposingZone=dict(bottom=target*.999999,top=target*1.000001,pivotTime=iso(target_state["high" if long else "low"]["time"]),confirmedTime=iso(target_state["availableAt"])),
                     contextZone=campaign["contextZone"],parentZone=campaign["parentZone"],
                     contextTouchAt=campaign["contextAt"],alignmentAt=campaign["alignmentAt"],parentTouchAt=campaign["touchAt"],
                     range4h=deepcopy(h["range"]),range15m=deepcopy(campaign["leg"]),
                     target4h=h["range"]["high" if long else "low"],targetMode="4H_SWING" if target_4h else "15M_SWING",
                     narrative={tf:dict(trend=s["trend"],internal=s["internal"],availableAt=s["availableAt"]) for tf,s in current.items() if s})
        signals[i]=deepcopy(pending);live[i]=i;used.add(campaign["parentZoneId"]);campaign=None
    return signals,live


class PhotonTrendMixin:
    def _configure_signal_features(self):
        super()._configure_signal_features()
        if not selected(self.config.strategy_profiles):return
        validate_settings(self.config.photon_confirmation_minutes,self.config.photon_retest_minutes,self.config.strategy_timeframe_minutes,True)
        bars=[dict(time=int(pd.Timestamp(t).timestamp()),open=float(o),high=float(h),low=float(l),close=float(c)) for t,o,h,l,c in zip(self.times,self.open,self.high,self.low,self.close)]
        self.photon_trend_exits = {}
        if self.config.photon_demand_pullback:
            from .photon_demand_pullback import demand_pullback_setups
            self.photon_setups, self.photon_order_live = demand_pullback_setups(
                bars, self.atr_values, prepare_context(bars, zone_reversal=True),
                entry_model=self.config.photon_demand_entry_model,
                confirmation_minutes=self.config.photon_confirmation_minutes,
                stop_buffer_atr=self.config.sd_stop_buffer_atr, minimum_r=self.config.sd_minimum_r)
            return
        if self.config.photon_midpoint_reversal:
            from .photon_midpoint_reversal import midpoint_reversal_setups, prepare_midpoint_context
            self.photon_setups, self.photon_order_live = midpoint_reversal_setups(
                bars, prepare_midpoint_context(bars),
                minimum_r=1. if self.config.photon_midpoint_fixed_1r else max(1., self.config.sd_minimum_r),
                fixed_1r=self.config.photon_midpoint_fixed_1r)
            return
        if self.config.photon_quarter_range:
            from .photon_quarter_range import quarter_range_setups, prepare_quarter_context
            self.photon_setups, self.photon_order_live = quarter_range_setups(
                bars, self.atr_values, prepare_quarter_context(bars),
                stop_buffer_atr=self.config.sd_stop_buffer_atr, minimum_r=self.config.sd_minimum_r)
            return
        if self.config.photon_zone_reversal:
            from .photon_zone_reversal import zone_reversal_setups
            from .photon_lesson import options, qualify_setup, context_pass
            guides = prepare_context(bars, zone_reversal=True, lesson_options=options(self.config))
            self.photon_15m_snapshots = guides['15m'].get('snapshots', ())
            self.photon_15m_snapshot_times = [s['availableAt'] for s in self.photon_15m_snapshots]
            self.photon_setups, self.photon_order_live = zone_reversal_setups(
                bars, self.atr_values, guides,
                confirmation_minutes=self.config.photon_confirmation_minutes,
                stop_buffer_atr=self.config.sd_stop_buffer_atr, minimum_r=self.config.sd_minimum_r,
                retest_minutes=self.config.photon_retest_minutes,
                legacy_entry_and_stop=self.config.photon_legacy_entry_and_stop,
                daily_zone_only=self.config.photon_daily_zone_only,
                fixed_target_r=self.config.photon_fixed_target_r if self.config.photon_fixed_target_enabled else None,
                context_filter=lambda z,at:context_pass(z,guides,at,self.config))
            for j,setup in enumerate(self.photon_setups):
                if setup is None:continue
                passed,proof=qualify_setup(setup,guides,self.config)
                if not passed:self.photon_setups[j]=None
                elif proof is not None:
                    setup['lessonEvidence']=proof
                    for name,value in proof['checks'].items():
                        required=name in proof['required']
                        setup['review']['checks'].append(dict(code='LESSON_'+name.upper(),
                            label=name.replace('_',' ')+' ('+('required' if required else 'optional evidence')+')',
                            passed=value,detail='Observed price-pattern evidence at the saved touch / decision; unknown fails a required check.'))
                if passed and self.config.photon_fixed_target_enabled:
                    sign=1 if setup['side']=='LONG' else -1
                    setup['target']=setup['entry']+sign*self.config.photon_fixed_target_r*abs(setup['entry']-setup['stop'])
                    setup['targetMode']='FIXED_R'
                    setup['fixedTargetR']=self.config.photon_fixed_target_r
                    setup['target4h']=setup['range4h']['equilibrium']
                    for check in setup['review']['checks']:
                        if check['code']=='MINIMUM_R':
                            check.update(label='Minimum reward / risk to fixed-R TP',detail=f'{self.config.photon_fixed_target_r:g}R before costs; recalculated from the actual fill and original SL.')
                        if check['code']=='4H_VALUE':check['detail']=f"Planned entry {setup['entry']:g}; 4H midpoint {setup['range4h']['equilibrium']:g}"
            self.photon_order_live=[j if j is not None and self.photon_setups[j] is not None else None for j in self.photon_order_live]
            self.photon_trend_exits = {e['availableAt']: e['direction'] for e in guides['15m']['events']
                                       if e['kind'] == 'TREND_CHANGE'}
            return
        self.photon_setups,self.photon_order_live=trend_setups(bars,self.atr_values,
            confirmation_minutes=self.config.photon_confirmation_minutes,retest_minutes=self.config.photon_retest_minutes,
            stop_buffer_atr=self.config.sd_stop_buffer_atr,minimum_r=self.config.sd_minimum_r,target_4h=self.config.photon_target_4h,
            flexible=self.config.photon_flexible_entries)

    def _infer_signal_strategy_mode(self):
        return MODE if selected(self.config.strategy_profiles) else super()._infer_signal_strategy_mode()

    def _selected_direction(self,i):
        if getattr(self,"signal_strategy_mode",None)==MODE:return self.photon_setups[i]["side"] if self.photon_setups[i] else None
        return super()._selected_direction(i)

    def _should_enter(self,i):
        if getattr(self,"signal_strategy_mode",None)==MODE:return bool(self.photon_setups[i]) and super()._should_enter(i)
        return super()._should_enter(i)

    def _entry_decision(self,i,active_at_candle_start=False):
        if getattr(self,"signal_strategy_mode",None)!=MODE:return super()._entry_decision(i,active_at_candle_start)
        if active_at_candle_start or self.active_pairs or self.pending_next_open_entry or i+1>=len(self.times) or not self._should_enter(i):return None
        market = self.config.photon_demand_pullback or self.config.photon_midpoint_reversal or (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and self.photon_setups[i].get("entryExecution") != "LIMIT_RETEST"
        source = "PHOTON_DEMAND_PULLBACK_OPEN" if self.config.photon_demand_pullback else "PHOTON_15M_MIDPOINT_OPEN" if self.config.photon_midpoint_reversal else "PHOTON_4H_QUARTER_LIMIT" if self.config.photon_quarter_range else "PHOTON_ZONE_REVERSAL_OPEN" if market else "PHOTON_ORIGIN_RETEST"
        return dict(execution_index=i+1,indicator_index=i,defer_to_next_open=True,photon_limit=True,photon_market=market,fill_price_source=source,scheduled_timestamp=pd.Timestamp(self.times[i])+pd.Timedelta(minutes=1),actual_entry_timestamp=None)

    def _execute_pending_next_open_entry(self,i,active_at_candle_start=False):
        order=getattr(self,"pending_next_open_entry",None)
        if not order or not order.get("photon_limit"):return super()._execute_pending_next_open_entry(i,active_at_candle_start)
        if order["execution_index"]!=i:return
        self.pending_next_open_entry=None;j=order["indicator_index"]
        # Prepared frames and their window bounds share naive UTC instants;
        # raw-frame engines use aware UTC. Keep the engine's representation.
        stamp=pd.Timestamp(self.times[i])
        if (i==0 or self.photon_order_live[i-1]!=j or pd.Timestamp(self.times[i])-pd.Timestamp(self.times[i-1])!=pd.Timedelta(minutes=1)
            or active_at_candle_start or self.active_pairs
            or self.trading_start is not None and stamp<self.trading_start
            or self.trading_end is not None and stamp>self.trading_end):return
        setup=self.photon_setups[j]
        if order.get("photon_market"):
            status, raw = "FILLED", float(self.open[i])
        else:
            status,raw=resolve_retest(setup,dict(open=self.open[i],high=self.high[i],low=self.low[i]))
        if status=="WAITING":
            if i+1<len(self.times):order["execution_index"]=i+1;self.pending_next_open_entry=order
            return
        if status!="FILLED":return
        order.update(fill_price=raw,actual_entry_timestamp=pd.Timestamp(self.times[i]),entry_schedule_status="PHOTON_MARKET_FILLED" if order.get("photon_market") else "PHOTON_LIMIT_FILLED")
        self._photon_fill=raw
        try:
            passed,reason=self._entry_filter_result(j,i)
            if passed:
                before=len(self.active_pairs);self._open_pair(i,passed,reason,order)
                if len(self.active_pairs)>before:
                    pair=self.active_pairs[-1]
                    for pos in pair.positions():
                        if not order.get("photon_market"):
                            pos.fib_limit_fill_time=pd.Timestamp(self.times[i]);pos.fib_limit_fill_price=raw
                        # Market entries fill at the open, so both SL and TP are
                        # eligible in this first minute. Limit fills stay conservative.
                        self._scan_position_exit(pair,pos,i)
            else:self._record_skipped_signal(j,reason)
        finally:self._photon_fill=None

    def _scan_pair_exit(self, pair, i):
        for pos in pair.positions():
            self._photon_close_on_trend(pos, i)
        if pair.is_open:
            return super()._scan_pair_exit(pair, i)

    def _scan_position_exit(self, pair, pos, i):
        if not self._photon_close_on_trend(pos, i):
            return super()._scan_position_exit(pair, pos, i)

    def _scan_exit(self, pos, i):
        if not self._photon_close_on_trend(pos, i):
            return super()._scan_exit(pos, i)

    def _photon_close_on_trend(self, pos, i):
        held = getattr(pos, 'photon_tp_hold_activated', False)
        if (getattr(self, "signal_strategy_mode", None) == MODE and pos.is_open
                and (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and (self.config.photon_exit_on_15m_change or held)):
            from .trade import Side, ExitReason, ExitSource
            at = int(pd.Timestamp(self.times[i]).timestamp())
            direction = self._photon_15m_trend(at) if held else self.photon_trend_exits.get(at)
            if direction and pos.is_open and (direction == -1 if pos.side == Side.LONG else direction == 1):
                opening = float(self.open[i])
                long = pos.side == Side.LONG
                stopped = opening <= pos.sl if long else opening >= pos.sl
                reached = opening >= pos.tp if long else opening <= pos.tp
                reason = ExitReason.SL if stopped else ExitReason.TP if reached and not held else ExitReason.PHOTON_15M_TREND_CHANGE
                slip = 1-self.config.slippage if long else 1+self.config.slippage
                self._close_position(pos, i, opening*slip, reason, ExitSource.STRATEGY_OPEN, self.times[i])
                return True
        return False

    def _photon_15m_trend(self, at):
        """Only the latest completed, non-stale 15m snapshot is eligible."""
        j = bisect_right(self.photon_15m_snapshot_times, at)-1
        if j < 0 or at >= self.photon_15m_snapshot_times[j]+900:
            return 0
        return self.photon_15m_snapshots[j].get('trend', 0)

    def _maybe_exit_bar(self, pos, i, high, low, timestamp, source):
        if not (getattr(self, 'signal_strategy_mode', None) == MODE and pos.is_open
                and (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and self.config.photon_hold_tp_until_15m_reversal):
            return super()._maybe_exit_bar(pos, i, high, low, timestamp, source)
        from .trade import Side
        long = pos.side == Side.LONG
        held = getattr(pos, 'photon_tp_hold_activated', False)
        reached = high >= pos.tp if long else low <= pos.tp
        stopped = low <= pos.sl if long else high >= pos.sl
        fill_time = getattr(pos, 'fib_limit_fill_time', None)
        limit_fill_bar = fill_time is not None and (
            pd.Timestamp(timestamp) == pd.Timestamp(fill_time)
            or (str(getattr(source, 'value', source)) == '15M_FALLBACK' and pos.entry_index == i))
        at = int(pd.Timestamp(timestamp).timestamp())
        if not held and reached and not stopped and not limit_fill_bar and self._photon_15m_trend(at) == (1 if long else -1):
            pos.photon_tp_hold_activated = held = True
            pos.photon_tp_first_hit_time = pd.Timestamp(timestamp)
        if not held:
            return super()._maybe_exit_bar(pos, i, high, low, timestamp, source)
        # Disable only the TP trigger. Keep the original target in trade reports
        # and preserve the normal stop-loss scanner on every subsequent candle.
        target = pos.tp
        try:
            pos.tp = float('inf') if long else -float('inf')
            return super()._maybe_exit_bar(pos, i, high, low, timestamp, source)
        finally:
            pos.tp = target

    def _profile_context(self,i):
        context=super()._profile_context(i)
        if getattr(self,"signal_strategy_mode",None)!=MODE or context is None:return context
        return (*context[:3],replace(context[3],reward_risk_ratio=self.config.photon_fixed_target_r if (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and self.config.photon_fixed_target_enabled else 1.,stop_loss_multiple=1.,position_sizing_stop_override_enabled=False,
            partial_profit_enabled=False,partial_stop_enabled=False,trailing_enabled=False,break_even_enabled=False,
            r_step_trailing_enabled=False,atr_checkpoint_tp_extension_enabled=False,timeout_enabled=False))

    def _expected_entry_price(self,indicator_i,execution_i,direction):
        raw=getattr(self,"_photon_fill",None)
        if getattr(self,"signal_strategy_mode",None)==MODE and raw is not None:return raw*(1+self.config.slippage if direction=="LONG" else 1-self.config.slippage)
        return super()._expected_entry_price(indicator_i,execution_i,direction)

    def _photon_target(self, setup, entry):
        sign = 1 if setup['side'] == 'LONG' else -1
        if not self.config.photon_demand_pullback and self.config.photon_midpoint_reversal and self.config.photon_midpoint_fixed_1r:
            return entry+sign*abs(entry-setup['stop'])
        if (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)
                and self.config.photon_fixed_target_enabled):
            return entry+sign*self.config.photon_fixed_target_r*abs(entry-setup['stop'])
        return float(setup['target'])

    def _sr_stop_plan(self,i,execution_i=None):
        if getattr(self,"signal_strategy_mode",None)!=MODE:return super()._sr_stop_plan(i,execution_i)
        s=self.photon_setups[i];side=self._effective_trade_direction(i)
        reject=dict(passed=False,applied=False,reason="PHOTON_ENTRY_GEOMETRY_REJECTED",distance=None)
        if not s or side!=s["side"]:return reject
        entry=self._expected_entry_price(i,execution_i,side);sign=1 if side=="LONG" else -1
        risk=sign*(entry-s["stop"])
        fixed=(self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and self.config.photon_fixed_target_enabled
        fixed_1r=not self.config.photon_demand_pullback and self.config.photon_midpoint_reversal and self.config.photon_midpoint_fixed_1r
        minimum_r=1. if fixed_1r else self.config.sd_minimum_r
        target=self._photon_target(s, entry)
        reward=sign*(target-entry)
        if not self.config.photon_demand_pullback and self.config.photon_midpoint_reversal:
            bounds = s['range4h']
            if (not bounds['low'] < entry < bounds['high'] or risk <= 0
                    or sign*(bounds['equilibrium']-entry)/risk < max(1., minimum_r)):
                return reject
        if (self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and not s["range4h"]["low"] <= entry <= s["range4h"]["high"]:
            return reject
        if not np.isfinite([entry,risk,reward]).all() or risk<=0 or reward<=0 or reward/risk+(1e-10 if fixed or fixed_1r else 0)<minimum_r:return reject
        return dict(passed=True,applied=True,reason=("PHOTON_"+s["stopSource"]+"_STOP") if self.config.photon_demand_pullback or self.config.photon_zone_reversal or self.config.photon_quarter_range or self.config.photon_midpoint_reversal else "PHOTON_CONFIRMED_ORIGIN_STOP",distance=risk,stop_price=s["stop"],boundary_price=s["stop"],level_price=target,distance_atr=risk/float(self.atr_values[i]),timeframe_minutes=1)

    def _sr_tp_filter_result(self,i,execution_i=None):
        if getattr(self,"signal_strategy_mode",None)==MODE:return True,None
        return super()._sr_tp_filter_result(i,execution_i)

    def _apply_sr_take_profit(self,i,pair):
        if getattr(self,"signal_strategy_mode",None)!=MODE:return super()._apply_sr_take_profit(i,pair)
        for pos in pair.positions():
            pos.tp=self._photon_target(self.photon_setups[i], pos.entry_price)

    def _open_pair(self,i,entry_filter_passed=True,entry_filter_reason="Strategy profile passed",schedule=None):
        before=len(self.active_pairs);result=super()._open_pair(i,entry_filter_passed,entry_filter_reason,schedule)
        if getattr(self,"signal_strategy_mode",None)==MODE and len(self.active_pairs)>before:
            self.active_pairs[-1].photon_setup=deepcopy(self.photon_setups[schedule["indicator_index"] if schedule else i])
            if ((self.config.photon_zone_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)) and self.config.photon_fixed_target_enabled
                    or not self.config.photon_demand_pullback and self.config.photon_midpoint_reversal and self.config.photon_midpoint_fixed_1r):
                self.active_pairs[-1].photon_setup['target']=self.active_pairs[-1].positions()[0].tp
                self.active_pairs[-1].photon_setup['targetMode']='FIXED_1R_BEFORE_MIDPOINT' if self.config.photon_midpoint_reversal else 'FIXED_R'
        return result

    def _build_result_row(self,pair,row_kind,positions):
        row=super()._build_result_row(pair,row_kind,positions)
        if getattr(self,"signal_strategy_mode",None)==MODE:
            setup=getattr(pair,'photon_setup',None)
            row["supply_demand_setup"]=json.dumps(setup,allow_nan=False)
            row['photon_hold_tp_until_15m_reversal'] = self.config.photon_hold_tp_until_15m_reversal and not (self.config.photon_demand_pullback or self.config.photon_quarter_range or self.config.photon_midpoint_reversal)
            row['photon_tp_hold_activated'] = any(getattr(p, 'photon_tp_hold_activated', False) for p in positions)
            row['photon_tp_first_hit_time'] = next((getattr(p, 'photon_tp_first_hit_time', None) for p in positions if getattr(p, 'photon_tp_hold_activated', False)), None)
            review=setup.get('review',{}) if setup else {}
            row['photon_entry_model']=setup.get('entryModel') if setup else None
            row['photon_review_status']=review.get('status','LEGACY_NOT_RECORDED')
            row['photon_mismatches']='; '.join(c['label']+': '+c['detail'] for c in review.get('mismatches',[]))
        return row
