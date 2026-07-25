"""Reports and repeatable batch orchestration for random entry timing."""
from __future__ import annotations
from dataclasses import replace
import numpy as np
import pandas as pd
from config import EntryTimingMode
from engine import BacktestEngine
from statistics import summarize

DECISION_COLUMNS = ["decision_id","candle_timestamp","candle_open_time","candle_close_time","pair_id_previously_closed","previous_pair_close_time","candles_waited_since_close","random_seed","random_draw","entry_probability","decision","forced_entry","entry_created","new_pair_id","entry_timestamp","entry_price","equity_before_entry","entry_timing_mode"]

def decisions_frame(rows): return pd.DataFrame(rows, columns=DECISION_COLUMNS)

def _wait_bucket(n):
    return "1 candle" if n == 1 else "2 candles" if n == 2 else "3–4 candles" if n <= 4 else "5–8 candles" if n <= 8 else "9 or more candles"

def random_analysis(trades, decisions, config):
    d=decisions_frame(decisions); opened=d[d.decision.isin(["OPEN","FORCED_OPEN"])] if not d.empty else d
    waits=pd.to_numeric(opened.get("candles_waited_since_close",pd.Series(dtype=float)),errors="coerce")
    pnl=pd.to_numeric(trades.get("pair_net_pnl",pd.Series(dtype=float)),errors="coerce")
    wins=pnl[pnl>0].sum(); losses=-pnl[pnl<0].sum(); equity=pd.to_numeric(trades.get("equity_after_trade",pd.Series(dtype=float)),errors="coerce")
    dd=(equity-equity.cummax().clip(lower=config.initial_equity)).min() if len(equity) else 0
    by_bucket={b:float(g.pair_net_pnl.mean()) for b,g in trades.assign(_bucket=pd.to_numeric(trades.get("candles_waited_before_entry",pd.Series(index=trades.index,dtype=float)),errors="coerce").map(_wait_bucket)).groupby("_bucket")} if not trades.empty else {}
    dist=waits.value_counts().sort_index().to_dict()
    row={"Random seed":config.random_seed,"Entry probability":config.random_entry_probability,"Total eligible candles":len(d),"Total OPEN decisions":int((d.decision=="OPEN").sum()) if len(d) else 0,"Total SKIP decisions":int((d.decision=="SKIP").sum()) if len(d) else 0,"Total forced entries":int((d.decision=="FORCED_OPEN").sum()) if len(d) else 0,"Observed OPEN percentage":float((d.decision=="OPEN").mean()) if len(d) else 0,"Observed SKIP percentage":float((d.decision=="SKIP").mean()) if len(d) else 0,"Total pairs opened":int(trades["pair_id"].nunique()) if "pair_id" in trades else len(trades),"Average candles waited":float(waits.mean()) if len(waits) else 0,"Median candles waited":float(waits.median()) if len(waits) else 0,"Minimum candles waited":float(waits.min()) if len(waits) else 0,"Maximum candles waited":float(waits.max()) if len(waits) else 0,"Average minutes waited":float(waits.mean()*config.strategy_timeframe_minutes) if len(waits) else 0,"Distribution of waiting candles":str(dist),"Gross P&L":float(trades.get("pair_gross_pnl",pd.Series(dtype=float)).sum()),"Fees":float(trades.get("pair_total_fees",pd.Series(dtype=float)).sum()),"Net P&L":float(pnl.sum()),"Pair win rate":float((pnl>0).mean()) if len(pnl) else 0,"Profit factor":float(wins/losses) if losses else float("inf"),"Maximum drawdown":float(dd),"Average P&L per pair":float(pnl.mean()) if len(pnl) else 0,"Average P&L by waiting-time bucket":str(by_bucket)}
    return pd.DataFrame([row])

def _batch_row(seed,trades,decisions,config):
    s=summarize(trades,config.initial_equity); d=decisions_frame(decisions); waits=pd.to_numeric(trades.get("candles_waited_before_entry",pd.Series(dtype=float)),errors="coerce")
    return {"Seed":seed,"Number of pairs":int(trades["pair_id"].nunique()) if "pair_id" in trades else len(trades),"Eligible decisions":len(d),"Open decisions":int((d.decision=="OPEN").sum()),"Skip decisions":int((d.decision=="SKIP").sum()),"Average wait":float(waits.mean()) if len(waits) else 0,"Median wait":float(waits.median()) if len(waits) else 0,"Maximum wait":float(waits.max()) if len(waits) else 0,"Gross P&L":float(trades.get("pair_gross_pnl",pd.Series(dtype=float)).sum()),"Fees":float(trades.get("pair_total_fees",pd.Series(dtype=float)).sum()),"Net P&L":float(trades.get("pair_net_pnl",pd.Series(dtype=float)).sum()),"Return percentage":s.get("total_return_percentage",0),"Win rate":s.get("win_rate",0),"Profit factor":s.get("profit_factor",0),"Maximum drawdown":s.get("maximum_drawdown",0),"Ending equity":s.get("ending_equity",config.initial_equity)}

def run_batch(data,intrabar,config):
    rows=[]
    for seed in range(config.random_seed_start,config.random_seed_start+config.random_seed_count):
        cfg=replace(config,random_seed=seed,enable_random_entry_batch=False)
        engine=BacktestEngine(data,cfg,intrabar); trades=engine.run(); rows.append(_batch_row(seed,trades,engine.random_entry_decisions,cfg))
    frame=pd.DataFrame(rows); net=frame["Net P&L"]; dd=frame["Maximum drawdown"]
    stats=pd.DataFrame([{"Number of seed-runs":len(frame),"Mean net P&L":net.mean(),"Median net P&L":net.median(),"Standard deviation of net P&L":net.std(ddof=0),"Minimum net P&L":net.min(),"Maximum net P&L":net.max(),"5th percentile":net.quantile(.05),"25th percentile":net.quantile(.25),"75th percentile":net.quantile(.75),"95th percentile":net.quantile(.95),"Percentage of profitable seed-runs":(net>0).mean(),"Mean maximum drawdown":dd.mean(),"Worst maximum drawdown":dd.min(),"Mean number of trades":frame["Number of pairs"].mean(),"Correlation between number of trades and net P&L":frame["Number of pairs"].corr(net)}])
    return frame,stats

def comparison_row(label,seed,trades,initial):
    s=summarize(trades,initial); entries=pd.to_datetime(trades.get("entry_time",pd.Series(dtype=object)),utc=True); exits=pd.to_datetime(trades.get("exit_time",pd.Series(dtype=object)),utc=True)
    return {"Strategy version":label,"Seed":seed,"Number of pairs":int(trades["pair_id"].nunique()) if "pair_id" in trades else len(trades),"Gross P&L":float(trades.get("pair_gross_pnl",pd.Series(dtype=float)).sum()),"Fees":float(trades.get("pair_total_fees",pd.Series(dtype=float)).sum()),"Net P&L":float(trades.get("pair_net_pnl",pd.Series(dtype=float)).sum()),"Return":s.get("total_return_percentage",0),"Win rate":s.get("win_rate",0),"Profit factor":s.get("profit_factor",0),"Maximum drawdown":s.get("maximum_drawdown",0),"Average holding time":s.get("average_holding_time",0),"Average time between pairs":float((entries.iloc[1:].reset_index(drop=True)-exits.iloc[:-1].reset_index(drop=True)).dt.total_seconds().mean()/60) if len(trades)>1 else 0}
