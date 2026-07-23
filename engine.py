"""Event-driven dual long/short backtesting engine with 15m strategy and optional 1m exits."""
from __future__ import annotations
from collections.abc import Callable
import numpy as np, pandas as pd
from atr import atr
from adx import adx
from config import BacktestConfig, EntryMode, IntrabarMissingPolicy, PositionSizingMode, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy
from entry_filters import ADXFilter, BBWidthFilter, DISpreadFilter
from indicators import bollinger_bands, lag
from strategy import custom_entry_signal
from trade import ExitReason, ExitSource, Position, Side, TradePair

class BacktestEngine:
    def __init__(self, data: pd.DataFrame, config: BacktestConfig, intrabar_data: pd.DataFrame | None = None, progress_callback: Callable[[int, int, int, int], None] | None = None, progress_interval: int = 50):
        self.data=data.reset_index(drop=True); self.intrabar_data=intrabar_data.reset_index(drop=True) if intrabar_data is not None else None; self.config=config; self.progress_callback=progress_callback; self.progress_interval=max(1, int(progress_interval))
        self.high=self.data.high.to_numpy(float); self.low=self.data.low.to_numpy(float); self.close=self.data.close.to_numpy(float); self.open=self.data.open.to_numpy(float); self.times=self.data.timestamp.to_numpy()
        self.atr_values=atr(self.high,self.low,self.close,self.config.atr_period); self.adx_values,self.plus_di_values,self.minus_di_values=adx(self.high,self.low,self.close,self.config.adx_period); self.bb_middle,self.bb_upper,self.bb_lower,self.bb_width,self.bb_width_pct=bollinger_bands(self.close,self.config.bb_period,self.config.bb_stddevs); self.bb_width_1=lag(self.bb_width,1); self.bb_width_3=lag(self.bb_width,3); self.bb_width_5=lag(self.bb_width,5); self.bb_width_change=self.bb_width-self.bb_width_5; self.bb_width_change_pct=np.divide(self.bb_width_change,self.bb_width_5,out=np.full(len(self.bb_width),np.nan,float),where=np.isfinite(self.bb_width_5)&(self.bb_width_5!=0)); self.di_spread=np.abs(self.plus_di_values-self.minus_di_values); self.di_spread_1=lag(self.di_spread,1); self.di_spread_3=lag(self.di_spread,3); self.di_spread_5=lag(self.di_spread,5); self.di_spread_change=self.di_spread-self.di_spread_5; mx=np.maximum(self.plus_di_values,self.minus_di_values); mn=np.minimum(self.plus_di_values,self.minus_di_values); self.di_ratio=np.divide(mx,mn,out=np.full(len(mx),np.nan,float),where=np.isfinite(mn)&(mn!=0)); self.risk=self._risk_array(); self.entry_filters=[ADXFilter(self.config,self.adx_values),BBWidthFilter(self.config,self.bb_width),DISpreadFilter(self.config,self.di_spread)]
        self.active_pairs=[]; self.completed_pairs=[]; self.skipped_signals=[]; self.signals_evaluated=0; self.next_pair_id=1; self.current_equity=config.initial_equity; self.missing_intrabar_intervals=[]; self.fallback_reasons=[]
        self.entry_delta=pd.Timedelta(minutes=config.strategy_timeframe_minutes)
        self.timeout_delta=pd.Timedelta(minutes=config.max_both_open_minutes)
        self.last_timeout_exit_time=None
        self.trading_start=pd.Timestamp(config.trading_start_date, tz="UTC") if config.trading_start_date else None
        self.trading_end=pd.Timestamp(config.trading_end_date, tz="UTC") if config.trading_end_date else None
        self.first_valid_atr_timestamp=self._first_valid_atr_timestamp()
        self.warmup_candle_count=int((self.data.timestamp < self.trading_start).sum()) if self.trading_start is not None else 0
    def _first_valid_atr_timestamp(self):
        idx=np.where(np.isfinite(self.atr_values))[0]
        return self.data.timestamp.iloc[int(idx[0])] if len(idx) else None
    def run(self)->pd.DataFrame:
        total=len(self.data)
        self._emit_progress(0,total)
        for i in range(total):
            self._update_positions_to_strategy_index(i); self._collect_closed_pairs()
            if self._should_enter(i):
                self.signals_evaluated += 1
                passed, reason = self._entry_filter_result(i)
                if passed: self._open_pair(i, passed, reason)
                else: self._record_skipped_signal(i, reason)
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
    def _in_trading_window(self,i):
        et=self._entry_time(i)
        return (self.trading_start is None or et >= self.trading_start) and (self.trading_end is None or et <= self.trading_end)
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
        if self.config.max_combined_effective_leverage is not None: cap_qty=min(cap_qty, self.config.max_combined_effective_leverage*equity/(2*entry_price))
        capped=cap_qty < qty - 1e-12
        return cap_qty,capped
    def _open_pair(self,i, adx_filter_passed=True, adx_filter_reason="ADX filter disabled"):
        raw=self.close[i]; long_entry=raw*(1+self.config.slippage); short_entry=raw*(1-self.config.slippage); r=float(self.risk[i]); stop=self.config.sl_mult*r; risk_amt=self.current_equity*self.config.risk_per_leg
        entry_fee_rate=self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee; exit_fee_rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        long_stop_exit=(long_entry-stop)*(1-self.config.slippage); short_stop_exit=(short_entry+stop)*(1+self.config.slippage)
        long_stop_loss_per_unit=(long_entry-long_stop_exit)+(long_entry*entry_fee_rate)+(long_stop_exit*exit_fee_rate)
        short_stop_loss_per_unit=(short_stop_exit-short_entry)+(short_entry*entry_fee_rate)+(short_stop_exit*exit_fee_rate)
        sizing_loss_per_unit=max(long_stop_loss_per_unit, short_stop_loss_per_unit) if self.config.position_sizing_mode==PositionSizingMode.ALL_IN_STOP_RISK else stop
        uncapped=risk_amt/sizing_loss_per_unit; lqty,lc=self._cap_qty(uncapped,long_entry,self.current_equity); sqty,sc=self._cap_qty(uncapped,short_entry,self.current_equity); fee_rate=entry_fee_rate
        long=Position(Side.LONG,self._entry_time(i),i,long_entry,r,long_entry-stop,long_entry+self.config.tp_mult*r,lqty,risk_amt,long_entry*lqty,float(self.atr_values[i]),uncapped,lqty*long_entry/self.current_equity, entry_fee=long_entry*lqty*fee_rate, fees=long_entry*lqty*fee_rate, original_sl=long_entry-stop, be_enabled=self.config.enable_be_after_opposite_sl, be_mode=self.config.be_mode.value, be_offset_r=self.config.be_offset_r)
        short=Position(Side.SHORT,self._entry_time(i),i,short_entry,r,short_entry+stop,short_entry-self.config.tp_mult*r,sqty,risk_amt,short_entry*sqty,float(self.atr_values[i]),uncapped,sqty*short_entry/self.current_equity, entry_fee=short_entry*sqty*fee_rate, fees=short_entry*sqty*fee_rate, original_sl=short_entry+stop, be_enabled=self.config.enable_be_after_opposite_sl, be_mode=self.config.be_mode.value, be_offset_r=self.config.be_offset_r)
        pair=TradePair(self.next_pair_id,long,short,self.current_equity,pd.Timestamp(self.times[i]),self._entry_time(i),raw,lc or sc); pair.adx=float(self.adx_values[i]) if np.isfinite(self.adx_values[i]) else np.nan; pair.plus_di=float(self.plus_di_values[i]) if np.isfinite(self.plus_di_values[i]) else np.nan; pair.minus_di=float(self.minus_di_values[i]) if np.isfinite(self.minus_di_values[i]) else np.nan; self._attach_market_state(pair,i); pair.adx_filter_passed=adx_filter_passed; pair.entry_filter_passed=adx_filter_passed; pair.entry_filter_reason=adx_filter_reason; pair.adx_filter_reason=adx_filter_reason; self.active_pairs.append(pair); self.next_pair_id+=1

    def _attach_market_state(self, pair, i):
        fields = {"bb_middle":self.bb_middle,"bb_upper":self.bb_upper,"bb_lower":self.bb_lower,"bb_width":self.bb_width,"bb_width_pct":self.bb_width_pct,"bb_width_1":self.bb_width_1,"bb_width_3":self.bb_width_3,"bb_width_5":self.bb_width_5,"bb_width_change":self.bb_width_change,"bb_width_change_pct":self.bb_width_change_pct,"di_spread":self.di_spread,"di_ratio":self.di_ratio,"di_spread_1":self.di_spread_1,"di_spread_3":self.di_spread_3,"di_spread_5":self.di_spread_5,"di_spread_change":self.di_spread_change}
        for name, arr in fields.items():
            setattr(pair, name, float(arr[i]) if np.isfinite(arr[i]) else np.nan)
    def _update_positions_to_strategy_index(self,i):
        for pair in self.active_pairs:
            if i > pair.long.entry_index and self._maybe_timeout_pair(pair, i):
                continue
            if i > pair.long.entry_index:
                self._scan_pair_exit(pair,i)
    def _scan_pair_exit(self,pair,i):
        if not self.config.use_intrabar_data or self.intrabar_data is None:
            for pos in (pair.long,pair.short):
                if pos.is_open: self._scan_exit(pos,i); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        start=pd.Timestamp(pair.strategy_entry_time); end=pd.Timestamp(self.times[i])+self.entry_delta
        if start.floor(f"{self.config.intrabar_timeframe_minutes}min") != start:
            for pos in (pair.long,pair.short):
                if pos.is_open: self._fallback_exit(pos,i,"timestamp_alignment_failure"); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        sub=self.intrabar_data[(self.intrabar_data.timestamp>=start)&(self.intrabar_data.timestamp<end)]
        if sub.empty or (sub.timestamp.iloc[0] > start + pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes)) or self._has_missing_intrabar(sub,start,end):
            reason="no_overlapping_intrabar_rows" if sub.empty else "intrabar_gap"
            for pos in (pair.long,pair.short):
                if pos.is_open: pos.missing_intrabar_data=True; self._fallback_exit(pos,i,reason); self._maybe_apply_be(pair,pos,None,None,None,None)
            return
        for j,row in sub.iterrows():
            before=(pair.long.is_open,pair.short.is_open)
            for pos in (pair.long,pair.short):
                if pos.is_open and not (pos.be_active_after is not None and pd.Timestamp(row.timestamp) < pd.Timestamp(pos.be_active_after)):
                    self._maybe_exit_bar(pos,j,row.high,row.low,row.timestamp,ExitSource.INTRABAR)
                    self._maybe_apply_be(pair,pos,j,row.high,row.low,row.timestamp)
            if not pair.is_open or before != (pair.long.is_open,pair.short.is_open):
                pass
        if self.intrabar_data.timestamp.max() < end - pd.Timedelta(minutes=self.config.intrabar_timeframe_minutes):
            for pos in (pair.long,pair.short):
                if pos.is_open: self._fallback_exit(pos,i,"end_of_intrabar_data"); self._maybe_apply_be(pair,pos,None,None,None,None)

    def _scan_exit(self,pos,i):
        start=pd.Timestamp(pos.entry_time); end=pd.Timestamp(self.times[i])+self.entry_delta
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
        if not other.is_open or other.be_triggered: return False
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
        if not self.config.enable_both_open_timeout or not (pair.long.is_open and pair.short.is_open): return False
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
        hit_tp=high>=pos.tp if pos.side==Side.LONG else low<=pos.tp; hit_sl=low<=pos.sl if pos.side==Side.LONG else high>=pos.sl
        if not(hit_tp or hit_sl): return False
        if hit_tp and hit_sl: pos.ambiguous=True; use_tp=self.config.tie_policy==TiePolicy.OPTIMISTIC
        else: use_tp=hit_tp
        raw=pos.tp if use_tp else pos.sl; slip=1-self.config.slippage if pos.side==Side.LONG else 1+self.config.slippage
        reason=ExitReason.TP if use_tp else (pos.be_exit_reason if pos.be_triggered else ExitReason.SL)
        self._close_position(pos,i,raw*slip,reason,source,timestamp); return True
    def _close_position(self,pos,i,exit_price,reason,source=None,timestamp=None):
        rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee; gross=(exit_price-pos.entry_price)*pos.quantity if pos.side==Side.LONG else (pos.entry_price-exit_price)*pos.quantity; exit_fee=exit_price*pos.quantity*rate
        pos.exit_time=timestamp if timestamp is not None else self.times[i]; pos.exit_index=i; pos.exit_price=exit_price; pos.exit_reason=reason; pos.exit_source=source or (ExitSource.END_OF_DATA if reason==ExitReason.END_OF_DATA else ExitSource.FALLBACK_15M); pos.gross_pnl=gross; pos.exit_fee=exit_fee; pos.fees=pos.entry_fee+exit_fee; pos.net_pnl=gross-pos.fees; pos.gross_r=gross/pos.risk_amount; pos.net_r=pos.net_pnl/pos.risk_amount; move=(exit_price-pos.entry_price) if pos.side==Side.LONG else (pos.entry_price-exit_price); pos.price_r=move/pos.risk
    def _force_close_end(self):
        last=len(self.data)-1
        for pair in self.active_pairs:
            for pos in (pair.long,pair.short):
                if pos.is_open: self._close_position(pos,last,self.close[last],ExitReason.END_OF_DATA,ExitSource.END_OF_DATA,pd.Timestamp(self.times[last]) + self.entry_delta)
    def _collect_closed_pairs(self,force=False):
        still=[]
        for p in self.active_pairs:
            if force or not p.is_open: self.current_equity+=p.long.net_pnl+p.short.net_pnl; p.equity_after_trade=self.current_equity; self.completed_pairs.append(p)
            else: still.append(p)
        self.active_pairs=still
    def results_frame(self):
        rows=[]
        for p in self.completed_pairs:
            fees=p.long.fees+p.short.fees; gross=p.long.gross_pnl+p.short.gross_pnl; net=p.long.net_pnl+p.short.net_pnl; risk_base=p.long.risk_amount+p.short.risk_amount
            exit_t=max(pd.Timestamp(p.long.exit_time),pd.Timestamp(p.short.exit_time)); hold=exit_t-pd.Timestamp(p.strategy_entry_time); comb=p.long.entry_notional+p.short.entry_notional; exp=(self.config.tp_mult-self.config.sl_mult)*p.long.risk*(p.long.quantity+p.short.quantity)/2; est=(p.long.entry_notional+p.short.entry_notional)*((self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee)+(self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee)); fee_pct=fees/exp*100 if exp else np.inf
            all_in_stop_risk = (self._estimated_stop_loss(p.long) + self._estimated_stop_loss(p.short)) / 2 / p.equity_before_trade
            rows.append({"pair_id":p.pair_id,"position_sizing_mode":self.config.position_sizing_mode.value,"configured_price_risk_percentage":self.config.risk_per_leg,"estimated_all_in_stop_risk_percentage":all_in_stop_risk,"strategy_candle_open_time":p.strategy_candle_open_time,"strategy_entry_time":p.strategy_entry_time,"strategy_entry_price":p.strategy_entry_price,"entry_time":p.strategy_entry_time,"entry_price":p.strategy_entry_price,"strategy_timeframe_minutes":self.config.strategy_timeframe_minutes,"intrabar_timeframe_minutes":self.config.intrabar_timeframe_minutes,"both_open_timeout_enabled":self.config.enable_both_open_timeout,"max_both_open_minutes":self.config.max_both_open_minutes,"both_open_timeout_triggered":p.both_open_timeout_triggered,"pair_be_triggered":p.pair_be_triggered,"timeout_minutes":p.timeout_minutes,"timeout_exit_time":p.timeout_exit_time,"atr_period":self.config.atr_period,"atr_multiplier":self.config.atr_multiplier,"atr_at_entry":p.long.atr_at_entry,"adx":getattr(p,"adx",np.nan),"plus_di":getattr(p,"plus_di",np.nan),"minus_di":getattr(p,"minus_di",np.nan),"di_spread":getattr(p,"di_spread",np.nan),"di_ratio":getattr(p,"di_ratio",np.nan),"di_spread_1":getattr(p,"di_spread_1",np.nan),"di_spread_3":getattr(p,"di_spread_3",np.nan),"di_spread_5":getattr(p,"di_spread_5",np.nan),"di_spread_change":getattr(p,"di_spread_change",np.nan),"bb_middle":getattr(p,"bb_middle",np.nan),"bb_upper":getattr(p,"bb_upper",np.nan),"bb_lower":getattr(p,"bb_lower",np.nan),"bb_width":getattr(p,"bb_width",np.nan),"bb_width_pct":getattr(p,"bb_width_pct",np.nan),"bb_width_1":getattr(p,"bb_width_1",np.nan),"bb_width_3":getattr(p,"bb_width_3",np.nan),"bb_width_5":getattr(p,"bb_width_5",np.nan),"bb_width_change":getattr(p,"bb_width_change",np.nan),"bb_width_change_pct":getattr(p,"bb_width_change_pct",np.nan),"entry_filter_passed":getattr(p,"entry_filter_passed",True),"entry_filter_reason":getattr(p,"entry_filter_reason","Entry filters disabled"),"adx_filter_passed":getattr(p,"adx_filter_passed",True),"adx_filter_reason":getattr(p,"adx_filter_reason","ADX filter disabled"),"r_distance":p.long.risk,"equity_before_trade":p.equity_before_trade,
            **self._pos_cols('long',p.long), **self._pos_cols('short',p.short),"combined_entry_notional":comb,"combined_effective_leverage":comb/p.equity_before_trade,"leverage_capped":p.leverage_capped,"pair_gross_pnl":gross,"pair_total_fees":fees,"pair_net_pnl":net,"pair_price_r":p.long.price_r+p.short.price_r,"pair_gross_account_r":gross/risk_base,"pair_fee_account_r":fees/risk_base,"pair_net_account_r":net/risk_base,"pair_gross_r":p.long.gross_r+p.short.gross_r,"pair_fee_r":fees/p.long.risk_amount,"pair_net_r":p.long.net_r+p.short.net_r,"expected_gross_winning_pair_pnl":exp,"estimated_round_trip_fees":est,"fees_as_percentage_of_expected_winning_profit":fee_pct,"equity_after_trade":p.equity_after_trade,"holding_minutes":hold.total_seconds()/60,"holding_hours":hold.total_seconds()/3600,"holding_bars":max(0, (exit_t-pd.Timestamp(p.strategy_entry_time))/self.entry_delta),"holding_time":hold,"ambiguous_intrabar":p.long.ambiguous or p.short.ambiguous,"ambiguous_candle":p.long.ambiguous or p.short.ambiguous,"missing_intrabar_data":p.long.missing_intrabar_data or p.short.missing_intrabar_data})
        frame=pd.DataFrame(rows)
        if not frame.empty:
            frame["signals_evaluated"] = self.signals_evaluated
            frame["signals_skipped_by_adx"] = sum(("ADX unavailable" in str(x.get("entry_filter_reason", x.get("adx_filter_reason", "")))) or str(x.get("entry_filter_reason", x.get("adx_filter_reason", ""))).startswith("ADX ") for x in self.skipped_signals)
            frame["signals_skipped_by_filters"] = len(self.skipped_signals)
            frame["signals_traded"] = len(frame)
        frame.attrs["skipped_signals"] = self.skipped_signals
        return frame
    def _estimated_stop_loss(self,pos):
        if pos.side==Side.LONG:
            stop_exit=pos.sl*(1-self.config.slippage); gross=(pos.entry_price-stop_exit)*pos.quantity
        else:
            stop_exit=pos.sl*(1+self.config.slippage); gross=(stop_exit-pos.entry_price)*pos.quantity
        exit_rate=self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        return gross + pos.entry_fee + stop_exit*pos.quantity*exit_rate
    def _pos_cols(self,prefix,pos):
        est_stop_loss=self._estimated_stop_loss(pos)
        return {f"{prefix}_entry_price":pos.entry_price,f"{prefix}_quantity":pos.quantity,f"{prefix}_uncapped_quantity":pos.uncapped_quantity,f"{prefix}_entry_notional":pos.entry_notional,f"{prefix}_effective_leverage":pos.effective_leverage,f"{prefix}_risk_amount":pos.risk_amount,f"{prefix}_configured_price_risk_percentage":self.config.risk_per_leg,f"{prefix}_estimated_all_in_stop_risk_percentage":est_stop_loss/pos.risk_amount*self.config.risk_per_leg if pos.risk_amount else 0,f"{prefix}_original_sl":pos.original_sl,f"{prefix}_current_sl":pos.sl,f"{prefix}_sl":pos.sl,f"{prefix}_tp":pos.tp,f"{prefix}_be_enabled":pos.be_enabled,f"{prefix}_be_triggered":pos.be_triggered,f"{prefix}_be_trigger_time":pos.be_trigger_time,f"{prefix}_be_triggered_by_side":pos.be_triggered_by_side.value if pos.be_triggered_by_side else None,f"{prefix}_be_mode":pos.be_mode,f"{prefix}_be_offset_r":pos.be_offset_r,f"{prefix}_be_stop_price":pos.be_stop_price,f"{prefix}_be_exit_reason":pos.be_exit_reason.value if pos.be_exit_reason else None,f"{prefix}_be_same_candle_ambiguous":pos.be_same_candle_ambiguous,f"{prefix}_exit_time":pos.exit_time,f"{prefix}_exit_price":pos.exit_price,f"{prefix}_exit_reason":pos.exit_reason.value if pos.exit_reason else None,f"{prefix}_exit_source":pos.exit_source.value if pos.exit_source else None,f"{prefix}_fallback_reason":pos.fallback_reason,f"{prefix}_entry_fee":pos.entry_fee,f"{prefix}_exit_fee":pos.exit_fee,f"{prefix}_total_fees":pos.fees,f"{prefix}_fees":pos.fees,f"{prefix}_gross_pnl":pos.gross_pnl,f"{prefix}_net_pnl":pos.net_pnl,f"{prefix}_price_r":pos.price_r,f"{prefix}_account_r":pos.net_r,f"{prefix}_gross_r":pos.gross_r,f"{prefix}_net_r":pos.net_r}
