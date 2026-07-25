"""Event-driven dual long/short backtesting engine with 15m strategy and optional 1m exits."""
from __future__ import annotations
from collections.abc import Callable
from random import Random
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
from atr import atr
from adx import adx
from config import BacktestConfig, EntryMode, IntrabarMissingPolicy, PositionSizingMode, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy, TradeDirectionMode, DailyEntryMissedPolicy, TrailApplyTo, TrailIntrabarMode, AfterTP1StopMode, TP2ExitMode, EntryTimingMode, RandomEntryStartMode
from entry_filters import ADXFilter, BBWidthFilter, DISpreadFilter
from indicators import bollinger_bands, lag
from strategy import custom_entry_signal
from trade import ExitReason, ExitSource, Position, Side, TradePair

class BacktestEngine:
    def __init__(self, data: pd.DataFrame, config: BacktestConfig, intrabar_data: pd.DataFrame | None = None, progress_callback: Callable[[int, int, int, int], None] | None = None, progress_interval: int = 50):
        self.data=data.reset_index(drop=True); self.intrabar_data=intrabar_data.reset_index(drop=True) if intrabar_data is not None else None; self.config=config; self.progress_callback=progress_callback; self.progress_interval=max(1, int(progress_interval))
        self.high=self.data.high.to_numpy(float); self.low=self.data.low.to_numpy(float); self.close=self.data.close.to_numpy(float); self.open=self.data.open.to_numpy(float); self.times=self.data.timestamp.to_numpy()
        self.atr_values=atr(self.high,self.low,self.close,self.config.atr_period); self.adx_values,self.plus_di_values,self.minus_di_values=adx(self.high,self.low,self.close,self.config.adx_period); self.bb_middle,self.bb_upper,self.bb_lower,self.bb_width,self.bb_width_pct=bollinger_bands(self.close,self.config.bb_period,self.config.bb_stddevs); self.bb_width_1=lag(self.bb_width,1); self.bb_width_3=lag(self.bb_width,3); self.bb_width_5=lag(self.bb_width,5); self.bb_width_change=self.bb_width-self.bb_width_5; self.bb_width_change_pct=np.divide(self.bb_width_change,self.bb_width_5,out=np.full(len(self.bb_width),np.nan,float),where=np.isfinite(self.bb_width_5)&(self.bb_width_5!=0)); self.di_spread=np.abs(self.plus_di_values-self.minus_di_values); self.di_spread_1=lag(self.di_spread,1); self.di_spread_3=lag(self.di_spread,3); self.di_spread_5=lag(self.di_spread,5); self.di_spread_change=self.di_spread-self.di_spread_5; mx=np.maximum(self.plus_di_values,self.minus_di_values); mn=np.minimum(self.plus_di_values,self.minus_di_values); self.di_ratio=np.divide(mx,mn,out=np.full(len(mx),np.nan,float),where=np.isfinite(mn)&(mn!=0)); self.risk=self._risk_array(); self.entry_filters=[ADXFilter(self.config,self.adx_values),BBWidthFilter(self.config,self.bb_width),DISpreadFilter(self.config,self.di_spread)]
        self.active_pairs=[]; self.completed_pairs=[]; self.telemetry_rows=[]; self.skipped_signals=[]; self.skipped_daily_entries=[]; self.signals_evaluated=0; self.daily_entry_opportunities=0; self.daily_entries_on_schedule=0; self.daily_entries_next_available=0; self.pending_daily_entry=None; self.next_pair_id=1; self.current_equity=config.initial_equity; self.missing_intrabar_intervals=[]; self.fallback_reasons=[]
        self.entry_delta=pd.Timedelta(minutes=config.strategy_timeframe_minutes)
        self.timeout_delta=pd.Timedelta(minutes=config.max_both_open_minutes)
        self.last_timeout_exit_time=None
        self.trading_start=pd.Timestamp(config.trading_start_date, tz="UTC") if config.trading_start_date else None
        self.trading_end=pd.Timestamp(config.trading_end_date, tz="UTC") if config.trading_end_date else None
        self.first_valid_atr_timestamp=self._first_valid_atr_timestamp()
        self.warmup_candle_count=int((self.data.timestamp < self.trading_start).sum()) if self.trading_start is not None else 0
        self.daily_entry_tz=ZoneInfo(config.daily_entry_timezone)
        hh, mm = [int(part) for part in str(config.daily_entry_time).split(":", 1)]
        self.daily_entry_minutes = hh * 60 + mm
        self.random_entry_active = bool(config.enable_random_entry and config.entry_timing_mode == EntryTimingMode.RANDOM_AFTER_PAIR_CLOSE)
        self.random_rng = Random(config.random_seed) if self.random_entry_active else None
        self.random_entry_decisions=[]; self.random_skips=0; self.last_closed_pair_id=None; self.previous_pair_close_time=None; self.pair_closed_index=None
    def _first_valid_atr_timestamp(self):
        idx=np.where(np.isfinite(self.atr_values))[0]
        return self.data.timestamp.iloc[int(idx[0])] if len(idx) else None
    def run(self)->pd.DataFrame:
        total=len(self.data)
        self._emit_progress(0,total)
        for i in range(total):
            self.current_index=i
            active_at_candle_start = bool(self.active_pairs)
            self._update_positions_to_strategy_index(i); self._record_active_telemetry(i); self._collect_closed_pairs()
            decision = self._entry_decision(i, active_at_candle_start)
            if decision:
                self.signals_evaluated += 1
                passed, reason = self._entry_filter_result(decision["indicator_index"])
                if passed: self._open_pair(decision["execution_index"], passed, reason, decision)
                else:
                    self._record_skipped_signal(decision["indicator_index"], reason)
                    if self.config.enable_daily_entry_schedule: self._record_skipped_daily_entry(decision["scheduled_timestamp"], "FILTER_REJECTED", reason)
            processed=i+1
            if processed == total or processed % self.progress_interval == 0:
                self._emit_progress(processed,total)
        self._force_close_end(); self._collect_closed_pairs(force=True); self._emit_progress(total,total); return self.results_frame()
    def _emit_progress(self, processed_candles, total_candles):
        if self.progress_callback is not None:
            self.progress_callback(processed_candles, total_candles, len(self.completed_pairs), self.next_pair_id - 1)
    def _risk_array(self):
        if self.config.risk_mode==RiskMode.FIXED: return np.full(len(self.data), self.config.fixed_r, float)
        if self.config.risk_mode==RiskMode.PERCENT: return self.close*self.config.percent_r
        return self.atr_values*self.config.atr_multiplier
    def _entry_time(self,i): return pd.Timestamp(self.times[i]) + self.entry_delta
    def _execution_time(self,i): return pd.Timestamp(self.times[i]) if (self.config.enable_daily_entry_schedule or self.random_entry_active) else self._entry_time(i)
    def _price_index(self,i): return i
    def _indicator_index_for_execution(self,i): return i - 1 if self.config.enable_daily_entry_schedule else i
    def _in_trading_window(self,i):
        et=self._execution_time(i)
        return (self.trading_start is None or et >= self.trading_start) and (self.trading_end is None or et <= self.trading_end)

    def _is_scheduled_candle(self, i):
        ts = pd.Timestamp(self.times[i])
        if ts.tzinfo is None: ts = ts.tz_localize("UTC")
        local = ts.tz_convert(self.daily_entry_tz)
        return local.hour * 60 + local.minute == self.daily_entry_minutes

    def _active_pair_for_skip(self):
        if not self.active_pairs: return None
        return self.active_pairs[0]

    def _record_skipped_daily_entry(self, scheduled_ts, reason, detail=""):
        pair = self._active_pair_for_skip()
        positions = pair.positions() if pair is not None else []
        exit_times = [pd.Timestamp(pos.exit_time) for pos in positions if pos.exit_time is not None]
        self.skipped_daily_entries.append({"scheduled_timestamp": scheduled_ts, "timezone": self.config.daily_entry_timezone, "reason": reason, "active_trade_id": pair.pair_id if pair is not None else None, "active_trade_entry_time": pair.strategy_entry_time if pair is not None else None, "active_trade_expected_or_actual_exit_time": max(exit_times) if exit_times else None, "detail": detail})

    def _daily_entry_decision(self, i, active_at_candle_start):
        if self.pending_daily_entry and not self.active_pairs:
            if self._base_entry_allowed(i):
                d=self.pending_daily_entry; self.pending_daily_entry=None; d.update({"execution_index": i, "indicator_index": i-1, "actual_entry_timestamp": pd.Timestamp(self.times[i]), "entry_schedule_status": "NEXT_AVAILABLE_CANDLE"}); return d
        if not self._is_scheduled_candle(i): return None
        scheduled_ts = pd.Timestamp(self.times[i])
        self.daily_entry_opportunities += 1
        if i <= 0 or not np.isfinite(self.risk[i-1]) or self.risk[i-1] <= 0:
            self._record_skipped_daily_entry(scheduled_ts, "INDICATOR_WARMUP") ; return None
        if not self._in_trading_window(i):
            self._record_skipped_daily_entry(scheduled_ts, "OUTSIDE_TRADING_DATE_RANGE") ; return None
        if active_at_candle_start or len(self.active_pairs) >= self.config.max_active_pairs:
            self._record_skipped_daily_entry(scheduled_ts, "ACTIVE_TRADE")
            if self.config.daily_entry_missed_policy == DailyEntryMissedPolicy.NEXT_AVAILABLE_CANDLE:
                self.pending_daily_entry={"scheduled_timestamp": scheduled_ts}
            return None
        return {"execution_index": i, "indicator_index": i-1, "scheduled_timestamp": scheduled_ts, "actual_entry_timestamp": scheduled_ts, "entry_schedule_status": "ON_TIME"}

    def _base_entry_allowed(self, i):
        return i > 0 and np.isfinite(self.risk[i-1]) and self.risk[i-1] > 0 and len(self.active_pairs) < self.config.max_active_pairs and self._in_trading_window(i)

    def _entry_decision(self, i, active_at_candle_start=False):
        if self.random_entry_active:
            return self._random_entry_decision(i, active_at_candle_start)
        if self.config.enable_daily_entry_schedule:
            return self._daily_entry_decision(i, active_at_candle_start)
        return {"execution_index": i, "indicator_index": i, "scheduled_timestamp": None, "actual_entry_timestamp": self._entry_time(i), "entry_schedule_status": None} if self._should_enter(i) else None
    def _random_entry_decision(self, i, active_at_candle_start=False):
        """Flip at an eligible candle open using indicators completed at i-1."""
        if active_at_candle_start or self.active_pairs or i <= 0 or not self._base_entry_allowed(i): return None
        # Entry filters are part of eligibility, so rejected/warm-up candles do
        # not perturb the dedicated random stream.
        if not self._entry_filter_result(i-1)[0]: return None
        if self.next_pair_id == 1 and not self.config.randomize_first_entry:
            return {"execution_index":i,"indicator_index":i-1,"actual_entry_timestamp":pd.Timestamp(self.times[i]),"entry_schedule_status":None,"random_bypass":True}
        if self.pair_closed_index is not None and i <= self.pair_closed_index: return None
        forced = self.config.max_random_wait_candles > 0 and self.random_skips >= self.config.max_random_wait_candles
        draw = self.random_rng.random()
        opens = forced or draw < self.config.random_entry_probability
        row={"decision_id":len(self.random_entry_decisions)+1,"candle_timestamp":pd.Timestamp(self.times[i]),"candle_open_time":pd.Timestamp(self.times[i]),"candle_close_time":pd.Timestamp(self.times[i])+self.entry_delta,"pair_id_previously_closed":self.last_closed_pair_id,"previous_pair_close_time":self.previous_pair_close_time,"candles_waited_since_close":self.random_skips+1,"random_seed":self.config.random_seed,"random_draw":draw,"entry_probability":self.config.random_entry_probability,"decision":"FORCED_OPEN" if forced else ("OPEN" if opens else "SKIP"),"forced_entry":forced,"entry_created":opens,"new_pair_id":self.next_pair_id if opens else None,"entry_timestamp":pd.Timestamp(self.times[i]) if opens else None,"entry_price":float(self.open[i]) if opens else None,"equity_before_entry":self.current_equity,"entry_timing_mode":self.config.entry_timing_mode.value}
        self.random_entry_decisions.append(row)
        if not opens: self.random_skips += 1; return None
        self.random_skips=0
        return {"execution_index":i,"indicator_index":i-1,"scheduled_timestamp":None,"actual_entry_timestamp":pd.Timestamp(self.times[i]),"entry_schedule_status":None,"random_decision":row}
    def _should_enter(self,i):
        if not np.isfinite(self.risk[i]) or self.risk[i]<=0 or len(self.active_pairs)>=self.config.max_active_pairs or not self._in_trading_window(i): return False
        if self.last_timeout_exit_time is not None and self._entry_time(i) <= self.last_timeout_exit_time: return False
        if self.config.entry_mode==EntryMode.WAIT_UNTIL_CLOSED: return not self.active_pairs
        if self.config.entry_mode==EntryMode.EVERY_N_CANDLES: return i % self.config.entry_interval==0
        if self.config.entry_mode==EntryMode.CUSTOM: return custom_entry_signal(i,{"open":self.open,"high":self.high,"low":self.low,"close":self.close},len(self.active_pairs))
        return False
    def _entry_filter_result(self, i):
        reasons=[]
        for flt in self.entry_filters:
            result=flt.evaluate(i)
            reasons.append(result.reason)
            if not result.passed:
                return False, "; ".join(reasons)
        return True, "; ".join(reasons)

    def _adx_filter_result(self, i):
        result = self.entry_filters[0].evaluate(i)
        return result.passed, result.reason
    def _record_skipped_signal(self, i, reason):
        self.skipped_signals.append({"strategy_candle_open_time": self.times[i], "strategy_entry_time": self._entry_time(i), "strategy_entry_price": float(self.close[i]), "adx": float(self.adx_values[i]) if np.isfinite(self.adx_values[i]) else np.nan, "plus_di": float(self.plus_di_values[i]) if np.isfinite(self.plus_di_values[i]) else np.nan, "minus_di": float(self.minus_di_values[i]) if np.isfinite(self.minus_di_values[i]) else np.nan, "bb_width": float(self.bb_width[i]) if np.isfinite(self.bb_width[i]) else np.nan, "di_spread": float(self.di_spread[i]) if np.isfinite(self.di_spread[i]) else np.nan, "entry_filter_passed": False, "entry_filter_reason": reason, "adx_filter_passed": False, "adx_filter_reason": reason})
    def _cap_qty(self, qty, entry_price, equity):
        capped=False; cap_qty=qty
        if self.config.max_effective_leverage_per_leg is not None: cap_qty=min(cap_qty, self.config.max_effective_leverage_per_leg*equity/entry_price)
        if self.config.max_combined_effective_leverage is not None: cap_qty=min(cap_qty, self.config.max_combined_effective_leverage*equity/(self._entry_leg_count()*entry_price))
        capped=cap_qty < qty - 1e-12
        return cap_qty,capped
    def _entry_leg_count(self):
        return 2 if self.config.trade_direction in (TradeDirectionMode.BOTH, TradeDirectionMode.BOTH_INDEPENDENT) else 1
    def _active_positions(self, pair):
        return pair.positions()

    def _open_pair(self,i, adx_filter_passed=True, adx_filter_reason="ADX filter disabled", schedule=None):
        ind_i = schedule["indicator_index"] if schedule else i; raw=(self.open[i] if (self.config.enable_daily_entry_schedule or self.random_entry_active) else self.close[i]); long_entry=raw*(1+self.config.slippage); short_entry=raw*(1-self.config.slippage); r=float(self.risk[ind_i]); stop=(self.config.stop_loss_r if self.config.enable_partial_take_profit else self.config.sl_mult)*r; risk_amt=self.current_equity*self.config.risk_per_leg
        entry_fee_rate=self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee; exit_fee_rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        long_stop_exit=(long_entry-stop)*(1-self.config.slippage); short_stop_exit=(short_entry+stop)*(1+self.config.slippage)
        long_stop_loss_per_unit=(long_entry-long_stop_exit)+(long_entry*entry_fee_rate)+(long_stop_exit*exit_fee_rate)
        short_stop_loss_per_unit=(short_stop_exit-short_entry)+(short_entry*entry_fee_rate)+(short_stop_exit*exit_fee_rate)
        sizing_loss_per_unit=max(long_stop_loss_per_unit, short_stop_loss_per_unit) if self.config.position_sizing_mode==PositionSizingMode.ALL_IN_STOP_RISK else stop
        uncapped=risk_amt/sizing_loss_per_unit; lqty,lc=self._cap_qty(uncapped,long_entry,self.current_equity); sqty,sc=self._cap_qty(uncapped,short_entry,self.current_equity); fee_rate=entry_fee_rate
        long=Position(Side.LONG,self._execution_time(i),i,long_entry,r,long_entry-stop,long_entry+self.config.tp_mult*r,lqty,risk_amt,long_entry*lqty,float(self.atr_values[ind_i]),uncapped,lqty*long_entry/self.current_equity, entry_fee=long_entry*lqty*fee_rate, fees=long_entry*lqty*fee_rate, original_sl=long_entry-stop, be_enabled=self.config.enable_be_after_opposite_sl, be_mode=self.config.be_mode.value, be_offset_r=self.config.be_offset_r)
        short=Position(Side.SHORT,self._execution_time(i),i,short_entry,r,short_entry+stop,short_entry-self.config.tp_mult*r,sqty,risk_amt,short_entry*sqty,float(self.atr_values[ind_i]),uncapped,sqty*short_entry/self.current_equity, entry_fee=short_entry*sqty*fee_rate, fees=short_entry*sqty*fee_rate, original_sl=short_entry+stop, be_enabled=self.config.enable_be_after_opposite_sl, be_mode=self.config.be_mode.value, be_offset_r=self.config.be_offset_r)
        for pos in (long, short):
            if self.config.enable_partial_take_profit:
                direction = 1 if pos.side == Side.LONG else -1
                pos.partial_tp_enabled=True; pos.original_quantity=pos.quantity; pos.remaining_quantity=pos.quantity
                pos.tp1_quantity=pos.quantity*self.config.tp1_close_pct/100.0
                pos.tp2_quantity=pos.quantity-pos.tp1_quantity # any precision remainder belongs to TP2
                pos.tp1_price=pos.entry_price+direction*self.config.tp1_r*r; pos.tp2_price=pos.entry_price+direction*self.config.tp2_r*r
                pos.tp=pos.tp2_price; pos.final_active_stop=pos.sl
            pos.trailing_enabled = (not pos.partial_tp_enabled) and self.config.enable_trailing_profit and (self.config.trail_apply_to == TrailApplyTo.BOTH or self.config.trail_apply_to.value == f"{pos.side.value}_ONLY")
            if pos.trailing_enabled:
                direction = 1 if pos.side == Side.LONG else -1
                pos.trailing_activation_price = pos.entry_price + direction * pos.risk * self.config.trail_activation_r
                pos.favourable_price = pos.entry_price
        if self.config.trade_direction == TradeDirectionMode.LONG_ONLY:
            short = None
        elif self.config.trade_direction == TradeDirectionMode.SHORT_ONLY:
            long = None
        pair=TradePair(self.next_pair_id,long,short,self.current_equity,pd.Timestamp(self.times[i]),self._execution_time(i),raw,lc or sc); pair.trade_direction=self.config.trade_direction.value; pair.daily_schedule_enabled=self.config.enable_daily_entry_schedule; pair.scheduled_entry_time=self.config.daily_entry_time; pair.scheduled_entry_timezone=self.config.daily_entry_timezone; pair.scheduled_entry_timestamp=(schedule or {}).get("scheduled_timestamp"); pair.actual_entry_timestamp=(schedule or {}).get("actual_entry_timestamp", self._execution_time(i)); pair.entry_schedule_status=(schedule or {}).get("entry_schedule_status");
        rd=(schedule or {}).get("random_decision")
        pair.random_decision=rd; pair.previous_pair_close_time=self.previous_pair_close_time
        if self.config.enable_daily_entry_schedule:
            if pair.entry_schedule_status == "ON_TIME": self.daily_entries_on_schedule += 1
            elif pair.entry_schedule_status == "NEXT_AVAILABLE_CANDLE": self.daily_entries_next_available += 1
        pair.adx=float(self.adx_values[ind_i]) if np.isfinite(self.adx_values[ind_i]) else np.nan; pair.plus_di=float(self.plus_di_values[ind_i]) if np.isfinite(self.plus_di_values[ind_i]) else np.nan; pair.minus_di=float(self.minus_di_values[ind_i]) if np.isfinite(self.minus_di_values[ind_i]) else np.nan; self._attach_market_state(pair,ind_i); pair.adx_filter_passed=adx_filter_passed; pair.entry_filter_passed=adx_filter_passed; pair.entry_filter_reason=adx_filter_reason; pair.adx_filter_reason=adx_filter_reason; self.active_pairs.append(pair); self._record_pair_telemetry(pair, i); self.next_pair_id+=1

    def _attach_market_state(self, pair, i):
        fields = {"bb_middle":self.bb_middle,"bb_upper":self.bb_upper,"bb_lower":self.bb_lower,"bb_width":self.bb_width,"bb_width_pct":self.bb_width_pct,"bb_width_1":self.bb_width_1,"bb_width_3":self.bb_width_3,"bb_width_5":self.bb_width_5,"bb_width_entry_5bar_change":self.bb_width_change,"bb_width_entry_5bar_change_pct":self.bb_width_change_pct,"di_spread":self.di_spread,"di_ratio":self.di_ratio,"di_spread_1":self.di_spread_1,"di_spread_3":self.di_spread_3,"di_spread_5":self.di_spread_5,"di_spread_entry_5bar_change":self.di_spread_change}
        for name, arr in fields.items():
            setattr(pair, name, float(arr[i]) if np.isfinite(arr[i]) else np.nan)
    def _update_positions_to_strategy_index(self,i):
        for pair in self.active_pairs:
            first = pair.positions()[0]
            if i > first.entry_index and self._maybe_timeout_pair(pair, i):
                continue
            if i > first.entry_index:
                self._scan_pair_exit(pair,i)
    def _scan_pair_exit(self,pair,i):
        if not self.config.use_intrabar_data or self.intrabar_data is None:
            for pos in pair.positions():
                if pos.is_open: self._scan_exit(pos,i); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        # Only inspect the strategy interval currently being processed. Starting
        # every scan at pair entry replays old intrabars with today's ratcheted
        # trailing stop and can therefore manufacture an exit in the past.
        start=max(pd.Timestamp(pair.strategy_entry_time), pd.Timestamp(self.times[i])); end=pd.Timestamp(self.times[i])+self.entry_delta
        if start.floor(f"{self.config.intrabar_timeframe_minutes}min") != start:
            for pos in pair.positions():
                if pos.is_open: self._fallback_exit(pos,i,"timestamp_alignment_failure"); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        sub=self.intrabar_data[(self.intrabar_data.timestamp>=start)&(self.intrabar_data.timestamp<end)]
        if sub.empty or (sub.timestamp.iloc[0] > start + pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)) or self._has_missing_intrabar(sub,start,end):
            reason="no_overlapping_intrabar_rows" if sub.empty else "intrabar_gap"
            for pos in pair.positions():
                if pos.is_open: pos.missing_intrabar_data=True; self._fallback_exit(pos,i,reason); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        for j,row in sub.iterrows():
            before=tuple(pos.is_open for pos in pair.positions())
            for pos in pair.positions():
                if pos.is_open and not (pos.be_active_after is not None and pd.Timestamp(row.timestamp) < pd.Timestamp(pos.be_active_after)):
                    self._maybe_exit_bar(pos,j,row.high,row.low,row.timestamp,ExitSource.INTRABAR)
                    self._maybe_apply_be(pair,pos,j,row.high,row.low,row.timestamp)
            if not pair.is_open or before != tuple(pos.is_open for pos in pair.positions()):
                pass
        if self.intrabar_data.timestamp.max() < end - pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes):
            for pos in pair.positions():
                if pos.is_open: self._fallback_exit(pos,i,"end_of_intrabar_data"); self._maybe_apply_be(pair,pos,None,None,None,None)

    def _scan_exit(self,pos,i):
        # Trailing state is stateful; never apply its current stop to a candle
        # which was already processed with an older stop.
        start=max(pd.Timestamp(pos.entry_time), pd.Timestamp(self.times[i])); end=pd.Timestamp(self.times[i])+self.entry_delta
        if not self.config.use_intrabar_data:
            return self._fallback_exit(pos,i,"intrabar_disabled")
        if self.intrabar_data is None:
            return self._fallback_exit(pos,i,"intrabar_file_missing")
        if start.floor(f"{self.config.intrabar_timeframe_minutes}min") != start:
            return self._fallback_exit(pos,i,"timestamp_alignment_failure")
        sub=self.intrabar_data[(self.intrabar_data.timestamp>=start)&(self.intrabar_data.timestamp<end)]
        if sub.empty:
            reason="end_of_intrabar_data" if self.intrabar_data.timestamp.max() < start else "no_overlapping_intrabar_rows"
            return self._fallback_exit(pos,i,reason)
        expected=pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)
        if sub.timestamp.iloc[0] > start + expected:
            return self._fallback_exit(pos,i,"timestamp_alignment_failure")
        if self._has_missing_intrabar(sub,start,end):
            pos.missing_intrabar_data=True
            if self.config.intrabar_missing_policy==IntrabarMissingPolicy.ERROR: raise ValueError("Missing intrabar candles during open trade")
            if self.config.intrabar_missing_policy==IntrabarMissingPolicy.WARN_AND_USE_15M: return self._fallback_exit(pos,i,"intrabar_gap")
        for j,row in sub.iterrows():
            if self._maybe_exit_bar(pos,j,row.high,row.low,row.timestamp,ExitSource.INTRABAR): return True
        if self.intrabar_data.timestamp.max() < end - pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes):
            return self._fallback_exit(pos,i,"end_of_intrabar_data")
        return False


    def _be_exit_reason(self):
        return {BreakEvenMode.ENTRY_PRICE: ExitReason.BE, BreakEvenMode.COST_ADJUSTED: ExitReason.BE_COST_ADJUSTED, BreakEvenMode.R_OFFSET: ExitReason.BE_R_OFFSET}[self.config.be_mode]
    def _be_stop(self,pos):
        if self.config.be_mode==BreakEvenMode.ENTRY_PRICE:
            return pos.entry_price
        if self.config.be_mode==BreakEvenMode.R_OFFSET:
            return pos.entry_price + self.config.be_offset_r*pos.risk if pos.side==Side.LONG else pos.entry_price - self.config.be_offset_r*pos.risk
        rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        q=pos.quantity or 1.0
        if pos.side==Side.LONG:
            # exit_price solves (x-entry)*q - entry_fee - x*q*rate ~= 0 before configured exit slippage; raw stop is adjusted so executed exit is x.
            target=(pos.entry_price*q + pos.entry_fee)/(q*(1-rate))
            return target/(1-self.config.slippage)
        target=(pos.entry_price*q - pos.entry_fee)/(q*(1+rate))
        return target/(1+self.config.slippage)
    def _maybe_apply_be(self,pair,closed_pos,bar_index,high,low,timestamp):
        if not self.config.enable_be_after_opposite_sl or closed_pos.exit_reason != ExitReason.SL: return False
        other=pair.short if closed_pos.side==Side.LONG else pair.long
        if other is None or not other.is_open or other.be_triggered: return False
        new_sl=self._be_stop(other)
        improves = new_sl > other.sl if other.side==Side.LONG else new_sl < other.sl
        if not improves: return False
        other.sl=new_sl; other.be_triggered=True; other.be_trigger_time=timestamp if timestamp is not None else closed_pos.exit_time; other.be_triggered_by_side=closed_pos.side; other.be_mode=self.config.be_mode.value; other.be_offset_r=self.config.be_offset_r; other.be_stop_price=new_sl; other.be_exit_reason=self._be_exit_reason(); pair.pair_be_triggered=True
        if timestamp is not None and self.config.be_same_candle_policy==BreakEvenSameCandlePolicy.NEXT_CANDLE:
            other.be_active_after=pd.Timestamp(timestamp)+pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)
        elif timestamp is not None:
            touched = low<=new_sl if other.side==Side.LONG else high>=new_sl
            if touched:
                other.be_same_candle_ambiguous=True
                slip=1-self.config.slippage if other.side==Side.LONG else 1+self.config.slippage
                self._close_position(other,bar_index,new_sl*slip,other.be_exit_reason,ExitSource.INTRABAR,timestamp)
        return True
    def _timeout_source(self):
        return ExitSource.INTRABAR if self.config.use_intrabar_data and self.intrabar_data is not None else ExitSource.FALLBACK_15M
    def _maybe_timeout_pair(self,pair,i):
        if not self.config.enable_both_open_timeout or pair.long is None or pair.short is None or not (pair.long.is_open and pair.short.is_open): return False
        timeout_at=pd.Timestamp(pair.strategy_entry_time) + self.timeout_delta
        interval_end=pd.Timestamp(self.times[i]) + self.entry_delta
        if interval_end < timeout_at: return False
        source=self._timeout_source()
        raw=None; ts=None; idx=i
        if source==ExitSource.INTRABAR:
            sub=self.intrabar_data[self.intrabar_data.timestamp>=timeout_at]
            sub=sub[sub.timestamp<=interval_end]
            if not sub.empty:
                row=sub.iloc[0]; raw=float(row.open); ts=pd.Timestamp(row.timestamp); idx=int(row.name)
            else:
                source=ExitSource.FALLBACK_15M
        if raw is None:
            future=self.data[self.data.timestamp>=timeout_at]
            row=future.iloc[0] if not future.empty else self.data.iloc[i]
            raw=float(row.open); ts=pd.Timestamp(row.timestamp); idx=int(row.name)
        long_exit=raw*(1-self.config.slippage); short_exit=raw*(1+self.config.slippage)
        self._close_position(pair.long,idx,long_exit,ExitReason.BOTH_OPEN_TIMEOUT,source,ts)
        self._close_position(pair.short,idx,short_exit,ExitReason.BOTH_OPEN_TIMEOUT,source,ts)
        pair.both_open_timeout_triggered=True; pair.timeout_minutes=int(self.config.max_both_open_minutes); pair.timeout_exit_time=ts; self.last_timeout_exit_time=ts
        return True
    def _fallback_exit(self,pos,i,reason):
        pos.fallback_reason=reason; self.fallback_reasons.append(reason)
        return self._maybe_exit_ohlc(pos,i,ExitSource.FALLBACK_15M)
    def _has_missing_intrabar(self,sub,start,end):
        expected=pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)
        diffs=sub.timestamp.diff().dropna(); gaps=diffs[diffs>expected]
        for idx,d in gaps.items(): self.missing_intrabar_intervals.append((sub.loc[idx-1,'timestamp'],sub.loc[idx,'timestamp'])); print(f"WARNING: Missing intrabar data {sub.loc[idx-1,'timestamp']} to {sub.loc[idx,'timestamp']}")
        return not gaps.empty
    def _maybe_exit_ohlc(self,pos,i,source): return self._maybe_exit_bar(pos,i,self.high[i],self.low[i],self.times[i],source)
    def _maybe_exit_bar(self,pos,i,high,low,timestamp,source):
        if pos.partial_tp_enabled:
            return self._maybe_partial_exit(pos,i,float(high),float(low),timestamp,source)
        if pos.trailing_enabled:
            return self._maybe_trailing_exit(pos,i,float(high),float(low),timestamp,source)
        hit_tp=high>=pos.tp if pos.side==Side.LONG else low<=pos.tp; hit_sl=low<=pos.sl if pos.side==Side.LONG else high>=pos.sl
        if not(hit_tp or hit_sl): return False
        if hit_tp and hit_sl: pos.ambiguous=True; use_tp=self.config.tie_policy==TiePolicy.OPTIMISTIC
        else: use_tp=hit_tp
        raw=pos.tp if use_tp else pos.sl; slip=1-self.config.slippage if pos.side==Side.LONG else 1+self.config.slippage
        reason=ExitReason.TP if use_tp else (pos.be_exit_reason if pos.be_triggered else ExitReason.SL)
        self._close_position(pos,i,raw*slip,reason,source,timestamp); return True

    def _partial_fill(self, pos, quantity, price, stage, i, timestamp, source):
        quantity=min(max(0.0, quantity), pos.remaining_quantity)
        if quantity <= 0: return False
        gross=((price-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-price))*quantity
        fee=price*quantity*(self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee)
        net=gross-fee; pos.remaining_quantity=max(0.0,pos.remaining_quantity-quantity)
        setattr(pos,f"{stage}_exit_time",pd.Timestamp(timestamp)); setattr(pos,f"{stage}_exit_price",price)
        setattr(pos,f"{stage}_gross_pnl",gross); setattr(pos,f"{stage}_fees",fee); setattr(pos,f"{stage}_net_pnl",net)
        pos.realized_pnl += net; pos.exit_fee += fee; pos.fees=pos.entry_fee+pos.exit_fee
        if stage=="tp1": pos.tp1_hit=True
        elif stage=="tp2": pos.tp2_hit=True
        else: pos.stop_exit_quantity=quantity
        if pos.remaining_quantity <= 1e-12:
            pos.remaining_quantity=0.0; pos.exit_time=pd.Timestamp(timestamp); pos.exit_index=i; pos.exit_price=price; pos.exit_source=source
        return True

    def _after_tp1(self,pos):
        if self.config.after_tp1_stop_mode==AfterTP1StopMode.MOVE_TO_ENTRY: candidate=pos.entry_price
        elif self.config.after_tp1_stop_mode==AfterTP1StopMode.MOVE_TO_R_OFFSET:
            candidate=pos.entry_price+self.config.after_tp1_stop_offset_r*pos.risk if pos.side==Side.LONG else pos.entry_price-self.config.after_tp1_stop_offset_r*pos.risk
        else: candidate=pos.original_sl
        pos.sl=max(pos.sl,candidate) if pos.side==Side.LONG else min(pos.sl,candidate)
        pos.final_active_stop=pos.sl
        if self.config.tp2_exit_mode==TP2ExitMode.TRAILING_AFTER_TP1:
            pos.trailing_enabled=True; pos.trailing_activation_price=pos.entry_price+(1 if pos.side==Side.LONG else -1)*pos.risk*self.config.trail_activation_r; pos.favourable_price=pos.tp1_price

    def _maybe_partial_exit(self,pos,i,high,low,timestamp,source):
        """Resolve unknown OHLC paths consistently.

        PESSIMISTIC orders an already-active stop before favourable targets.
        OPTIMISTIC orders TP1, then fixed TP2 (or trailing update), before the
        stop. Targets are monotonic, so TP2 is never processed before TP1.
        """
        stop_hit=low<=pos.sl if pos.side==Side.LONG else high>=pos.sl
        tp1_hit=(high>=pos.tp1_price if pos.side==Side.LONG else low<=pos.tp1_price) and not pos.tp1_hit
        tp2_hit=(high>=pos.tp2_price if pos.side==Side.LONG else low<=pos.tp2_price) and self.config.tp2_exit_mode==TP2ExitMode.FIXED_TP2
        if stop_hit and self.config.tie_policy==TiePolicy.PESSIMISTIC:
            return self._finish_partial_stop(pos,i,timestamp,source)
        changed=False
        if tp1_hit:
            changed=self._partial_fill(pos,pos.tp1_quantity,pos.tp1_price,"tp1",i,timestamp,source); self._after_tp1(pos)
        if pos.is_open and pos.tp1_hit and tp2_hit:
            self._partial_fill(pos,pos.remaining_quantity,pos.tp2_price,"tp2",i,timestamp,source); self._finalize_partial(pos,ExitReason.TP); return True
        if pos.is_open and pos.tp1_hit and self.config.tp2_exit_mode==TP2ExitMode.TRAILING_AFTER_TP1:
            if self._maybe_trailing_exit(pos,i,high,low,timestamp,source): return True
        if pos.is_open and stop_hit:
            return self._finish_partial_stop(pos,i,timestamp,source)
        return changed

    def _finish_partial_stop(self,pos,i,timestamp,source):
        raw=pos.sl; price=raw*(1-self.config.slippage if pos.side==Side.LONG else 1+self.config.slippage)
        self._partial_fill(pos,pos.remaining_quantity,price,"stop",i,timestamp,source)
        reason=pos.be_exit_reason if pos.be_triggered else ExitReason.SL; self._finalize_partial(pos,reason)
        return True

    def _finalize_partial(self,pos,reason):
        pos.exit_reason=reason; pos.final_exit_reason=("TP1_THEN_SL" if reason==ExitReason.SL and pos.tp1_hit else ("TP2" if pos.tp2_hit else reason.value))
        pos.gross_pnl=sum(v or 0 for v in (pos.tp1_gross_pnl,pos.tp2_gross_pnl,pos.stop_gross_pnl))
        pos.net_pnl=pos.gross_pnl-pos.fees; pos.gross_r=pos.gross_pnl/pos.risk_amount; pos.net_r=pos.net_pnl/pos.risk_amount
        pos.quantity=pos.original_quantity
        move=(pos.exit_price-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-pos.exit_price); pos.price_r=move/pos.risk
    def _maybe_trailing_exit(self, pos, i, high, low, timestamp, source):
        """Resolve OHLC ambiguity without inventing an unknowable intrabar path.

        PESSIMISTIC tests the stop that existed at bar open before allowing a
        favourable extreme to ratchet it. On the activation bar it gives an
        simultaneously touched original stop priority and defers the new trail.
        OPTIMISTIC assumes favourable extreme first, then tests the updated trail.
        """
        is_long = pos.side == Side.LONG
        old_stop = max(pos.original_sl, pos.be_stop_price or -np.inf, pos.trailing_stop or -np.inf) if is_long else min(pos.original_sl, pos.be_stop_price or np.inf, pos.trailing_stop or np.inf)
        stop_hit = low <= old_stop if is_long else high >= old_stop
        activation_hit = high >= pos.trailing_activation_price if is_long else low <= pos.trailing_activation_price
        if stop_hit and (not pos.trailing_active or self.config.trail_intrabar_mode == TrailIntrabarMode.PESSIMISTIC):
            reason = ExitReason.TRAILING_STOP if pos.trailing_active and pos.trailing_stop is not None and abs(old_stop-pos.trailing_stop)<1e-9 else (pos.be_exit_reason if pos.be_triggered and pos.be_stop_price is not None and abs(old_stop-pos.be_stop_price)<1e-9 else ExitReason.SL)
            return self._close_at_stop(pos,i,old_stop,reason,source,timestamp)
        just_activated = False
        if not pos.trailing_active and activation_hit:
            pos.trailing_active=True; pos.trailing_activation_time=timestamp; just_activated=True
        if pos.trailing_active:
            extreme = high if is_long else low
            pos.favourable_price = max(pos.favourable_price, extreme) if is_long else min(pos.favourable_price, extreme)
            candidate = pos.favourable_price - pos.risk*self.config.trail_distance_r if is_long else pos.favourable_price + pos.risk*self.config.trail_distance_r
            pos.trailing_stop = max(pos.trailing_stop or -np.inf,candidate) if is_long else min(pos.trailing_stop or np.inf,candidate)
            active = max(pos.original_sl,pos.be_stop_price or -np.inf,pos.trailing_stop) if is_long else min(pos.original_sl,pos.be_stop_price or np.inf,pos.trailing_stop)
            pos.sl=active; pos.final_active_stop=active
            hit = low <= active if is_long else high >= active
            if hit and self.config.trail_intrabar_mode == TrailIntrabarMode.OPTIMISTIC:
                reason = ExitReason.TRAILING_STOP if abs(active-pos.trailing_stop)<1e-9 else pos.be_exit_reason
                return self._close_at_stop(pos,i,active,reason,source,timestamp)
        return False
    def _close_at_stop(self,pos,i,raw,reason,source,timestamp):
        slip=1-self.config.slippage if pos.side==Side.LONG else 1+self.config.slippage
        self._close_position(pos,i,raw*slip,reason,source,timestamp)
        if reason == ExitReason.TRAILING_STOP:
            pos.trailing_exit_price=pos.exit_price; pos.trailing_profit_r=pos.price_r
        return True
    def _close_position(self,pos,i,exit_price,reason,source=None,timestamp=None):
        if pos.partial_tp_enabled and pos.remaining_quantity > 0:
            exit_time=pd.Timestamp(timestamp if timestamp is not None else self.times[i])
            self._partial_fill(pos,pos.remaining_quantity,exit_price,"stop",i,exit_time,source or ExitSource.FALLBACK_15M)
            self._finalize_partial(pos,reason)
            return
        rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee; gross=(exit_price-pos.entry_price)*pos.quantity if pos.side==Side.LONG else (pos.entry_price-exit_price)*pos.quantity; exit_fee=exit_price*pos.quantity*rate
        exit_time=pd.Timestamp(timestamp if timestamp is not None else self.times[i])
        if exit_time < pd.Timestamp(pos.entry_time):
            raise ValueError(f"Exit timestamp {exit_time} precedes entry timestamp {pos.entry_time}")
        if reason == ExitReason.TRAILING_STOP and pos.trailing_activation_time is not None and exit_time < pd.Timestamp(pos.trailing_activation_time):
            raise ValueError(f"Trailing-stop exit timestamp {exit_time} precedes activation timestamp {pos.trailing_activation_time}")
        pos.exit_time=exit_time; pos.exit_index=i; pos.exit_price=exit_price; pos.exit_reason=reason; pos.exit_source=source or (ExitSource.END_OF_DATA if reason==ExitReason.END_OF_DATA else ExitSource.FALLBACK_15M); pos.gross_pnl=gross; pos.exit_fee=exit_fee; pos.fees=pos.entry_fee+exit_fee; pos.net_pnl=gross-pos.fees; pos.gross_r=gross/pos.risk_amount; pos.net_r=pos.net_pnl/pos.risk_amount; move=(exit_price-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-exit_price); pos.price_r=move/pos.risk
    def _force_close_end(self):
        last=len(self.data)-1
        for pair in self.active_pairs:
            for pos in pair.positions():
                if pos.is_open: self._close_position(pos,last,self.close[last],ExitReason.END_OF_DATA,ExitSource.END_OF_DATA,pd.Timestamp(self.times[last]) + self.entry_delta)
    def _collect_closed_pairs(self,force=False):
        still=[]
        for p in self.active_pairs:
            if force or not p.is_open:
                self.current_equity+=sum(pos.net_pnl for pos in p.positions()); p.equity_after_trade=self.current_equity; self.completed_pairs.append(p)
                if not force:
                    self.last_closed_pair_id=p.pair_id; self.previous_pair_close_time=max(pd.Timestamp(pos.exit_time) for pos in p.positions()); self.pair_closed_index=self.current_index; self.random_skips=0
            else: still.append(p)
        self.active_pairs=still
    def _result_rows_for_pair(self, p):
        positions = list(p.positions())
        if self.config.trade_direction == TradeDirectionMode.BOTH_INDEPENDENT:
            return [(pos.side.value.lower(), [pos]) for pos in positions]
        return [("pair" if len(positions) > 1 else positions[0].side.value.lower(), positions)]

    def results_frame(self):
        rows=[]
        for p in self.completed_pairs:
            for row_kind, positions in self._result_rows_for_pair(p):
                primary = positions[0]
                fees=sum(pos.fees for pos in positions); gross=sum(pos.gross_pnl for pos in positions); net=sum(pos.net_pnl for pos in positions); risk_base=sum(pos.risk_amount for pos in positions)
                exit_t=max(pd.Timestamp(pos.exit_time) for pos in positions); hold=exit_t-pd.Timestamp(p.strategy_entry_time); comb=sum(pos.entry_notional for pos in positions)
                exp=(self.config.tp_mult-self.config.sl_mult)*sum(pos.risk*pos.quantity for pos in positions)/len(positions)
                est=comb*((self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee)+(self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee)); fee_pct=fees/exp*100 if exp else np.inf
                all_in_stop_risk = sum(self._estimated_stop_loss(pos) for pos in positions) / len(positions) / p.equity_before_trade
                row={"partial_tp_enabled":self.config.enable_partial_take_profit,"tp1_r":self.config.tp1_r,"tp1_close_pct":self.config.tp1_close_pct,"tp2_r":self.config.tp2_r,"tp2_close_pct":self.config.tp2_close_pct,"stop_loss_r":self.config.stop_loss_r,"after_tp1_stop_mode":self.config.after_tp1_stop_mode.value,"after_tp1_stop_offset_r":self.config.after_tp1_stop_offset_r,"tp2_exit_mode":self.config.tp2_exit_mode.value,"intrabar_partial_tp_ordering":("STOP_FIRST" if self.config.tie_policy==TiePolicy.PESSIMISTIC else "TP1_THEN_TP2_THEN_STOP"),"pair_id":p.pair_id,"trade_id":f"{p.pair_id}-{row_kind}" if row_kind != "pair" else p.pair_id,"trade_direction":self.config.trade_direction.value,"trailing_profit_enabled":self.config.enable_trailing_profit,"trail_activation_r":self.config.trail_activation_r,"trail_distance_r":self.config.trail_distance_r,"trail_apply_to":self.config.trail_apply_to.value,"trail_intrabar_mode":self.config.trail_intrabar_mode.value,"result_type":row_kind,"side":primary.side.value if len(positions)==1 else "BOTH","position_sizing_mode":self.config.position_sizing_mode.value,"configured_price_risk_percentage":self.config.risk_per_leg,"estimated_all_in_stop_risk_percentage":all_in_stop_risk,"strategy_candle_open_time":p.strategy_candle_open_time,"strategy_entry_time":p.strategy_entry_time,"strategy_entry_price":p.strategy_entry_price,"entry_time":p.strategy_entry_time,"entry_price":primary.entry_price if len(positions)==1 else p.strategy_entry_price,"strategy_timeframe_minutes":self.config.strategy_timeframe_minutes,"intrabar_timeframe_minutes":self.config.intrabar_timeframe_minutes,"both_open_timeout_enabled":self.config.enable_both_open_timeout,"max_both_open_minutes":self.config.max_both_open_minutes,"both_open_timeout_triggered":p.both_open_timeout_triggered,"pair_be_triggered":p.pair_be_triggered,"timeout_minutes":p.timeout_minutes,"timeout_exit_time":p.timeout_exit_time,"atr_period":self.config.atr_period,"atr_multiplier":self.config.atr_multiplier,"atr_at_entry":primary.atr_at_entry,"adx":getattr(p,"adx",np.nan),"plus_di":getattr(p,"plus_di",np.nan),"minus_di":getattr(p,"minus_di",np.nan),"di_spread":getattr(p,"di_spread",np.nan),"di_ratio":getattr(p,"di_ratio",np.nan),"di_spread_1":getattr(p,"di_spread_1",np.nan),"di_spread_3":getattr(p,"di_spread_3",np.nan),"di_spread_5":getattr(p,"di_spread_5",np.nan),"di_spread_entry_5bar_change":getattr(p,"di_spread_entry_5bar_change",np.nan),"indicator_warmup_complete":bool(np.isfinite(getattr(p,"adx",np.nan)) and np.isfinite(getattr(p,"bb_width",np.nan))),"adx_available_at_entry":bool(np.isfinite(getattr(p,"adx",np.nan))),"bb_width_available_at_entry":bool(np.isfinite(getattr(p,"bb_width",np.nan))),"indicator_warmup_note":"Complete" if (np.isfinite(getattr(p,"adx",np.nan)) and np.isfinite(getattr(p,"bb_width",np.nan))) else "Indicator warm-up incomplete at entry; missing indicator values are expected until enough historical candles are available.","bb_middle":getattr(p,"bb_middle",np.nan),"bb_upper":getattr(p,"bb_upper",np.nan),"bb_lower":getattr(p,"bb_lower",np.nan),"bb_width":getattr(p,"bb_width",np.nan),"bb_width_pct":getattr(p,"bb_width_pct",np.nan),"bb_width_1":getattr(p,"bb_width_1",np.nan),"bb_width_3":getattr(p,"bb_width_3",np.nan),"bb_width_5":getattr(p,"bb_width_5",np.nan),"bb_width_entry_5bar_change":getattr(p,"bb_width_entry_5bar_change",np.nan),"bb_width_entry_5bar_change_pct":getattr(p,"bb_width_entry_5bar_change_pct",np.nan),"daily_schedule_enabled":getattr(p,"daily_schedule_enabled",False),"scheduled_entry_time":getattr(p,"scheduled_entry_time",None),"scheduled_entry_timezone":getattr(p,"scheduled_entry_timezone",None),"scheduled_entry_timestamp":getattr(p,"scheduled_entry_timestamp",None),"actual_entry_timestamp":getattr(p,"actual_entry_timestamp",p.strategy_entry_time),"entry_delay_minutes":((pd.Timestamp(getattr(p,"actual_entry_timestamp",p.strategy_entry_time))-pd.Timestamp(getattr(p,"scheduled_entry_timestamp",p.strategy_entry_time))).total_seconds()/60 if getattr(p,"scheduled_entry_timestamp",None) is not None else 0),"entry_schedule_status":getattr(p,"entry_schedule_status",None),"entry_filter_passed":getattr(p,"entry_filter_passed",True),"entry_filter_reason":getattr(p,"entry_filter_reason","Entry filters disabled"),"adx_filter_passed":getattr(p,"adx_filter_passed",True),"adx_filter_reason":getattr(p,"adx_filter_reason","ADX filter disabled"),"r_distance":primary.risk,"equity_before_trade":p.equity_before_trade,"combined_entry_notional":comb,"combined_effective_leverage":comb/p.equity_before_trade,"leverage_capped":p.leverage_capped,"pair_gross_pnl":gross,"pair_total_fees":fees,"pair_net_pnl":net,"pair_price_r":sum(pos.price_r for pos in positions),"pair_gross_account_r":gross/risk_base,"pair_fee_account_r":fees/risk_base,"pair_net_account_r":net/risk_base,"pair_gross_r":sum(pos.gross_r for pos in positions),"pair_fee_r":fees/primary.risk_amount,"pair_net_r":sum(pos.net_r for pos in positions),"expected_gross_winning_pair_pnl":exp,"estimated_round_trip_fees":est,"fees_as_percentage_of_expected_winning_profit":fee_pct,"equity_after_trade":p.equity_after_trade,"exit_time":exit_t,"holding_minutes":hold.total_seconds()/60,"holding_hours":hold.total_seconds()/3600,"holding_bars":max(0, (exit_t-pd.Timestamp(p.strategy_entry_time))/self.entry_delta),"holding_time":hold,"ambiguous_intrabar":any(pos.ambiguous for pos in positions),"ambiguous_candle":any(pos.ambiguous for pos in positions),"missing_intrabar_data":any(pos.missing_intrabar_data for pos in positions)}
                rd=getattr(p,"random_decision",None)
                row.update({"random_entry_enabled":self.random_entry_active,"random_seed":self.config.random_seed if self.random_entry_active else None,"random_entry_probability":self.config.random_entry_probability if self.random_entry_active else None,"randomize_first_entry":self.config.randomize_first_entry,"max_random_wait_candles":self.config.max_random_wait_candles,"random_decision_id":rd.get("decision_id") if rd else None,"random_draw_that_opened_trade":rd.get("random_draw") if rd else None,"random_decision_timestamp":rd.get("candle_timestamp") if rd else None,"candles_waited_before_entry":rd.get("candles_waited_since_close") if rd else None,"minutes_waited_before_entry":rd.get("candles_waited_since_close",0)*self.config.strategy_timeframe_minutes if rd else None,"previous_pair_close_time":getattr(p,"previous_pair_close_time",None),"random_entry_forced":rd.get("forced_entry",False) if rd else False,"entry_timing_mode":self.config.entry_timing_mode.value if self.random_entry_active else EntryTimingMode.CURRENT.value})
                if p.long is not None and (len(positions)>1 or primary.side==Side.LONG): row.update(self._pos_cols('long', p.long))
                if p.short is not None and (len(positions)>1 or primary.side==Side.SHORT): row.update(self._pos_cols('short', p.short))
                rows.append(row)
        frame=pd.DataFrame(rows)
        if not frame.empty and self.config.trade_direction == TradeDirectionMode.BOTH_INDEPENDENT:
            exit_cols=[c for c in ("long_exit_time","short_exit_time") if c in frame]
            exit_times=frame[exit_cols].max(axis=1) if exit_cols else frame["entry_time"]
            frame=frame.assign(_result_exit_time=pd.to_datetime(exit_times)).sort_values(["_result_exit_time","trade_id"]).drop(columns=["_result_exit_time"]).reset_index(drop=True)
            frame["equity_after_trade"] = self.config.initial_equity + frame["pair_net_pnl"].cumsum()
        if not frame.empty:
            entry = pd.to_datetime(frame["entry_time"], utc=True)
            frame["exit_time_before_entry"] = pd.to_datetime(frame["exit_time"], utc=True) < entry
            trailing_before_activation = pd.Series(False, index=frame.index)
            activated_after_entry = pd.Series(False, index=frame.index)
            for prefix in ("long", "short"):
                reason_col=f"{prefix}_exit_reason"; exit_col=f"{prefix}_exit_time"; activation_col=f"{prefix}_trailing_activation_time"
                if not {reason_col, exit_col, activation_col}.issubset(frame.columns):
                    continue
                leg_exit=pd.to_datetime(frame[exit_col], utc=True); activation=pd.to_datetime(frame[activation_col], utc=True)
                trailing_before_activation |= frame[reason_col].eq(ExitReason.TRAILING_STOP.value) & activation.notna() & (leg_exit < activation)
                activated_after_entry |= activation.notna() & (activation > entry)
            frame["trailing_exit_before_activation"] = trailing_before_activation
            frame["zero_holding_after_trailing_activation"] = activated_after_entry & frame["holding_minutes"].eq(0)
            frame["timestamp_validation_failed"] = frame[["exit_time_before_entry", "trailing_exit_before_activation", "zero_holding_after_trailing_activation"]].any(axis=1)
            frame["signals_evaluated"] = self.signals_evaluated
            frame["signals_skipped_by_adx"] = sum(("ADX unavailable" in str(x.get("entry_filter_reason", x.get("adx_filter_reason", "")))) or str(x.get("entry_filter_reason", x.get("adx_filter_reason", ""))).startswith("ADX ") for x in self.skipped_signals)
            frame["signals_skipped_by_filters"] = len(self.skipped_signals)
            frame["signals_traded"] = len(frame)
        frame.attrs["skipped_signals"] = self.skipped_signals
        frame.attrs["skipped_daily_entries"] = self.skipped_daily_entries
        frame.attrs["daily_schedule_stats"] = {"scheduled_entry_opportunities": self.daily_entry_opportunities, "trades_opened_on_schedule": self.daily_entries_on_schedule, "scheduled_entries_opened_next_available": self.daily_entries_next_available}
        frame.attrs["random_entry_decisions"] = list(self.random_entry_decisions)
        return frame

    def telemetry_frame(self):
        from telemetry import telemetry_columns_for_direction
        return pd.DataFrame(self.telemetry_rows, columns=telemetry_columns_for_direction(self.config.trade_direction))

    def _num(self, arr, i):
        value = arr[i]
        return float(value) if np.isfinite(value) else np.nan

    def _unrealized(self, pos, close):
        if not pos.is_open:
            return 0.0
        gross = (close - pos.entry_price) * (pos.remaining_quantity if pos.partial_tp_enabled else pos.quantity) if pos.side == Side.LONG else (pos.entry_price - close) * (pos.remaining_quantity if pos.partial_tp_enabled else pos.quantity)
        return float(gross - pos.fees)

    def _record_active_telemetry(self, i):
        if not self.config.enable_trade_telemetry:
            return
        for pair in self.active_pairs:
            self._record_pair_telemetry(pair, i)

    def _record_pair_telemetry(self, pair, i):
        if not self.config.enable_trade_telemetry:
            return
        ts = pd.Timestamp(self.times[i]) + self.entry_delta
        entry = pd.Timestamp(pair.strategy_entry_time)
        if ts < entry or not pair.is_open:
            return
        elapsed = (ts - entry).total_seconds() / 60
        if elapsed < 0 or elapsed % self.config.telemetry_interval_minutes != 0:
            return
        if self.telemetry_rows and self.telemetry_rows[-1].get("pair_id") == pair.pair_id and pd.Timestamp(self.telemetry_rows[-1].get("timestamp")) == ts:
            return
        close = float(self.close[i]); high = float(self.high[i]); low = float(self.low[i])
        long_open = pair.long.is_open if pair.long is not None else False; short_open = pair.short.is_open if pair.short is not None else False
        long_pnl = self._unrealized(pair.long, close) if pair.long is not None else 0.0; short_pnl = self._unrealized(pair.short, close) if pair.short is not None else 0.0
        def distances(pos, is_long):
            if not pos.is_open:
                return (np.nan, np.nan, np.nan, np.nan)
            sl_d = close - pos.sl if is_long else pos.sl - close
            tp_d = pos.tp - close if is_long else close - pos.tp
            return (float(sl_d), float(tp_d), float(sl_d / pos.risk) if pos.risk else np.nan, float(tp_d / pos.risk) if pos.risk else np.nan)
        lsl, ltp, lslr, ltpr = distances(pair.long, True) if pair.long is not None else (np.nan, np.nan, np.nan, np.nan); ssl, stp, sslr, stpr = distances(pair.short, False) if pair.short is not None else (np.nan, np.nan, np.nan, np.nan)
        row={"pair_id":pair.pair_id,"timestamp":ts,"elapsed_minutes":elapsed,"elapsed_strategy_bars":int(elapsed / self.config.strategy_timeframe_minutes),"close":close,"high":high,"low":low,"atr":self._num(self.atr_values,i),"adx":self._num(self.adx_values,i),"plus_di":self._num(self.plus_di_values,i),"minus_di":self._num(self.minus_di_values,i),"di_spread":self._num(self.di_spread,i),"di_ratio":self._num(self.di_ratio,i),"bb_middle":self._num(self.bb_middle,i),"bb_upper":self._num(self.bb_upper,i),"bb_lower":self._num(self.bb_lower,i),"bb_width":self._num(self.bb_width,i),"bb_width_pct":self._num(self.bb_width_pct,i),"long_is_open":long_open,"short_is_open":short_open,"long_unrealized_pnl":long_pnl,"short_unrealized_pnl":short_pnl,"pair_unrealized_pnl":long_pnl+short_pnl,"long_distance_to_sl":lsl,"long_distance_to_tp":ltp,"short_distance_to_sl":ssl,"short_distance_to_tp":stp,"long_distance_to_sl_r":lslr,"long_distance_to_tp_r":ltpr,"short_distance_to_sl_r":sslr,"short_distance_to_tp_r":stpr,"long_current_sl":pair.long.sl if pair.long is not None and pair.long.is_open else np.nan,"short_current_sl":pair.short.sl if pair.short is not None and pair.short.is_open else np.nan,"long_tp":pair.long.tp if pair.long is not None else np.nan,"short_tp":pair.short.tp if pair.short is not None else np.nan}
        for prefix, pos, is_long in (("long", pair.long, True), ("short", pair.short, False)):
            enabled = bool(pos and pos.trailing_enabled)
            active = bool(pos and pos.trailing_active)
            row.update({f"{prefix}_trailing_enabled":enabled, f"{prefix}_trailing_active":active, f"{prefix}_trailing_activation_price":pos.trailing_activation_price if enabled else np.nan, f"{prefix}_current_trailing_stop":pos.trailing_stop if active else np.nan, f"{prefix}_current_active_stop":pos.sl if pos and pos.is_open else np.nan, f"{prefix}_{'highest' if is_long else 'lowest'}_price_since_entry":pos.favourable_price if enabled else np.nan, f"{prefix}_distance_to_activation_r":((pos.trailing_activation_price-close) if is_long else (close-pos.trailing_activation_price))/pos.risk if enabled and pos.risk else np.nan, f"{prefix}_distance_to_trailing_stop_r":((close-pos.trailing_stop) if is_long else (pos.trailing_stop-close))/pos.risk if active and pos.risk else np.nan, f"{prefix}_unrealized_profit_r":((close-pos.entry_price) if is_long else (pos.entry_price-close))/pos.risk if pos and pos.is_open and pos.risk else np.nan, f"{prefix}_original_quantity":pos.original_quantity if pos and pos.partial_tp_enabled else np.nan, f"{prefix}_remaining_quantity":pos.remaining_quantity if pos and pos.partial_tp_enabled else np.nan, f"{prefix}_tp1_hit":bool(pos and pos.tp1_hit), f"{prefix}_tp2_hit":bool(pos and pos.tp2_hit), f"{prefix}_tp1_price":pos.tp1_price if pos and pos.partial_tp_enabled else np.nan, f"{prefix}_tp2_price":pos.tp2_price if pos and pos.partial_tp_enabled else np.nan, f"{prefix}_realized_pnl":pos.realized_pnl-pos.entry_fee if pos and pos.partial_tp_enabled else 0.0, f"{prefix}_total_current_pnl":(pos.realized_pnl-pos.entry_fee+self._unrealized(pos,close)+pos.fees if pos and pos.partial_tp_enabled else row.get(f"{prefix}_unrealized_pnl",0.0))})
        if self.config.trade_direction == TradeDirectionMode.LONG_ONLY:
            row={k:v for k,v in row.items() if not k.startswith("short_")}
        elif self.config.trade_direction == TradeDirectionMode.SHORT_ONLY:
            row={k:v for k,v in row.items() if not k.startswith("long_")}
        self.telemetry_rows.append(row)

    def _estimated_stop_loss(self,pos):
        if pos.side==Side.LONG:
            stop_exit=pos.sl*(1-self.config.slippage); gross=(pos.entry_price-stop_exit)*pos.quantity
        else:
            stop_exit=pos.sl*(1+self.config.slippage); gross=(stop_exit-pos.entry_price)*pos.quantity
        exit_rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        return gross + pos.entry_fee + stop_exit*pos.quantity*exit_rate
    def _pos_cols(self,prefix,pos):
        est_stop_loss=self._estimated_stop_loss(pos)
        return {f"{prefix}_original_quantity":pos.original_quantity if pos.partial_tp_enabled else pos.quantity,f"{prefix}_remaining_quantity":pos.remaining_quantity if pos.partial_tp_enabled else 0.0,f"{prefix}_tp1_quantity":pos.tp1_quantity if pos.partial_tp_enabled else None,f"{prefix}_tp2_quantity":pos.tp2_quantity if pos.partial_tp_enabled else None,f"{prefix}_tp1_price":pos.tp1_price,f"{prefix}_tp2_price":pos.tp2_price,f"{prefix}_sl_price":pos.original_sl,f"{prefix}_tp1_hit":pos.tp1_hit,f"{prefix}_tp1_exit_time":pos.tp1_exit_time,f"{prefix}_tp1_exit_price":pos.tp1_exit_price,f"{prefix}_tp1_gross_pnl":pos.tp1_gross_pnl,f"{prefix}_tp1_fees":pos.tp1_fees,f"{prefix}_tp1_net_pnl":pos.tp1_net_pnl,f"{prefix}_tp2_hit":pos.tp2_hit,f"{prefix}_tp2_exit_time":pos.tp2_exit_time,f"{prefix}_tp2_exit_price":pos.tp2_exit_price,f"{prefix}_tp2_gross_pnl":pos.tp2_gross_pnl,f"{prefix}_tp2_fees":pos.tp2_fees,f"{prefix}_tp2_net_pnl":pos.tp2_net_pnl,f"{prefix}_stop_exit_time":pos.stop_exit_time,f"{prefix}_stop_exit_price":pos.stop_exit_price,f"{prefix}_stop_exit_quantity":pos.stop_exit_quantity,f"{prefix}_stop_gross_pnl":pos.stop_gross_pnl,f"{prefix}_stop_fees":pos.stop_fees,f"{prefix}_stop_net_pnl":pos.stop_net_pnl,f"{prefix}_total_gross_pnl":pos.gross_pnl,f"{prefix}_total_net_pnl":pos.net_pnl,f"{prefix}_final_exit_reason":pos.final_exit_reason or (pos.exit_reason.value if pos.exit_reason else None),f"{prefix}_existing_r":pos.risk,f"{prefix}_trailing_enabled":pos.trailing_enabled,f"{prefix}_trailing_activated":pos.trailing_active,f"{prefix}_trailing_activation_time":pos.trailing_activation_time,f"{prefix}_trailing_activation_price":pos.trailing_activation_price,f"{prefix}_{'highest' if pos.side==Side.LONG else 'lowest'}_favourable_price":pos.favourable_price if pos.trailing_active else None,f"{prefix}_final_trailing_stop":pos.trailing_stop,f"{prefix}_final_active_stop":pos.final_active_stop,f"{prefix}_trailing_exit_price":pos.trailing_exit_price,f"{prefix}_trailing_profit_r":pos.trailing_profit_r,f"{prefix}_entry_price":pos.entry_price,f"{prefix}_quantity":pos.quantity,f"{prefix}_uncapped_quantity":pos.uncapped_quantity,f"{prefix}_entry_notional":pos.entry_notional,f"{prefix}_effective_leverage":pos.effective_leverage,f"{prefix}_risk_amount":pos.risk_amount,f"{prefix}_configured_price_risk_percentage":self.config.risk_per_leg,f"{prefix}_estimated_all_in_stop_risk_percentage":est_stop_loss/pos.risk_amount*self.config.risk_per_leg if pos.risk_amount else 0,f"{prefix}_original_sl":pos.original_sl,f"{prefix}_current_sl":pos.sl,f"{prefix}_sl":pos.sl,f"{prefix}_tp":pos.tp,f"{prefix}_be_enabled":pos.be_enabled,f"{prefix}_be_triggered":pos.be_triggered,f"{prefix}_be_trigger_time":pos.be_trigger_time,f"{prefix}_be_triggered_by_side":pos.be_triggered_by_side.value if pos.be_triggered_by_side else None,f"{prefix}_be_mode":pos.be_mode,f"{prefix}_be_offset_r":pos.be_offset_r,f"{prefix}_be_stop_price":pos.be_stop_price,f"{prefix}_be_exit_reason":pos.be_exit_reason.value if pos.be_exit_reason else None,f"{prefix}_be_same_candle_ambiguous":pos.be_same_candle_ambiguous,f"{prefix}_exit_time":pos.exit_time,f"{prefix}_exit_price":pos.exit_price,f"{prefix}_exit_reason":pos.exit_reason.value if pos.exit_reason else None,f"{prefix}_exit_source":pos.exit_source.value if pos.exit_source else None,f"{prefix}_fallback_reason":pos.fallback_reason,f"{prefix}_entry_fee":pos.entry_fee,f"{prefix}_exit_fee":pos.exit_fee,f"{prefix}_total_fees":pos.fees,f"{prefix}_fees":pos.fees,f"{prefix}_gross_pnl":pos.gross_pnl,f"{prefix}_net_pnl":pos.net_pnl,f"{prefix}_price_r":pos.price_r,f"{prefix}_account_r":pos.net_r,f"{prefix}_gross_r":pos.gross_r,f"{prefix}_net_r":pos.net_r}
