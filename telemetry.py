"""Trade telemetry and indicator-journey analysis exports."""
from __future__ import annotations

from pathlib import Path
import traceback
import numpy as np
import pandas as pd

INDICATORS = ("adx", "di_spread", "bb_width", "atr")


def _series(frame: pd.DataFrame, column: str, dtype=float) -> pd.Series:
    """Return one column as a Series even if duplicate names produce a DataFrame."""
    if column not in frame:
        return pd.Series(dtype=dtype)
    values = frame[column]
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    return values

MILESTONES = {15:"15m",30:"30m",45:"45m",60:"60m",120:"2h",240:"4h",480:"8h"}
BASE_TELEMETRY_COLUMNS = ["pair_id","long_leg_id","short_leg_id","timestamp","elapsed_minutes","elapsed_strategy_bars","close","high","low","atr","adx","plus_di","minus_di","di_spread","di_ratio","bb_middle","bb_upper","bb_lower","bb_width","bb_width_pct","long_is_open","short_is_open","long_unrealized_pnl","short_unrealized_pnl","pair_unrealized_pnl","long_distance_to_sl","long_distance_to_tp","short_distance_to_sl","short_distance_to_tp","long_distance_to_sl_r","long_distance_to_tp_r","short_distance_to_sl_r","short_distance_to_tp_r","long_current_sl","short_current_sl","long_tp","short_tp","long_trailing_enabled","long_trailing_active","long_trailing_activation_price","long_current_trailing_stop","long_current_active_stop","long_highest_price_since_entry","long_distance_to_activation_r","long_distance_to_trailing_stop_r","long_unrealized_profit_r","short_trailing_enabled","short_trailing_active","short_trailing_activation_price","short_current_trailing_stop","short_current_active_stop","short_lowest_price_since_entry","short_distance_to_activation_r","short_distance_to_trailing_stop_r","short_unrealized_profit_r"]

for _side in ("long", "short"):
    BASE_TELEMETRY_COLUMNS.extend([f"{_side}_original_quantity", f"{_side}_remaining_quantity", f"{_side}_tp1_hit", f"{_side}_tp2_hit", f"{_side}_tp1_price", f"{_side}_tp2_price", f"{_side}_realized_pnl", f"{_side}_total_current_pnl"])

TELEMETRY_COLUMNS = BASE_TELEMETRY_COLUMNS

def telemetry_columns_for_direction(direction) -> list[str]:
    value = getattr(direction, "value", direction)
    if value == "LONG_ONLY":
        return [c for c in BASE_TELEMETRY_COLUMNS if not c.startswith("short_")]
    if value == "SHORT_ONLY":
        return [c for c in BASE_TELEMETRY_COLUMNS if not c.startswith("long_")]
    return BASE_TELEMETRY_COLUMNS

def partial_take_profit_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    """Build a one-row audit summary for two-stage exits."""
    pairs=len(trades); legs=sum(f"{s}_original_quantity" in trades for s in ("long","short"))*pairs
    def count(side, field):
        col=f"{side}_{field}"; return int(trades[col].fillna(False).astype(bool).sum()) if col in trades else 0
    l1,l2,s1,s2=(count("long","tp1_hit"),count("long","tp2_hit"),count("short","tp1_hit"),count("short","tp2_hit"))
    reasons=pd.concat([trades.get("long_final_exit_reason",pd.Series(dtype=object)),trades.get("short_final_exit_reason",pd.Series(dtype=object))],ignore_index=True)
    gross=float(trades.get("pair_gross_pnl",pd.Series(dtype=float)).sum()); fees=float(trades.get("pair_total_fees",pd.Series(dtype=float)).sum()); net=float(trades.get("pair_net_pnl",pd.Series(dtype=float)).sum())
    wins=trades.get("pair_net_pnl",pd.Series(dtype=float)); gains=float(wins[wins>0].sum()); losses=float(-wins[wins<0].sum())
    eq=trades.get("equity_after_trade",pd.Series(dtype=float)); dd=float((eq-eq.cummax()).min()) if len(eq) else 0.0
    def avg(cols):
        values=pd.concat([trades[c].dropna() for c in cols if c in trades],ignore_index=True); return float(values.mean()) if len(values) else np.nan
    return pd.DataFrame([{"total_pairs":pairs,"total_legs":legs,"long_tp1_hit_count":l1,"long_tp1_hit_rate":l1/pairs if pairs else 0,"long_tp2_hit_count":l2,"long_tp2_hit_rate":l2/pairs if pairs else 0,"short_tp1_hit_count":s1,"short_tp1_hit_rate":s1/pairs if pairs else 0,"short_tp2_hit_count":s2,"short_tp2_hit_rate":s2/pairs if pairs else 0,"legs_stopped_before_tp1":int(reasons.eq("SL").sum()),"legs_stopped_after_tp1":int(reasons.eq("TP1_THEN_SL").sum()),"legs_reached_tp1_and_tp2":l2+s2,"average_tp1_realized_pnl":avg(["long_tp1_net_pnl","short_tp1_net_pnl"]),"average_tp2_realized_pnl":avg(["long_tp2_net_pnl","short_tp2_net_pnl"]),"average_loss_before_tp1":avg(["long_stop_net_pnl","short_stop_net_pnl"]),"average_loss_after_tp1":avg(["long_stop_net_pnl","short_stop_net_pnl"]),"gross_pnl":gross,"total_fees":fees,"net_pnl":net,"profit_factor":gains/losses if losses else np.inf,"pair_win_rate":float((wins>0).mean()) if len(wins) else 0,"maximum_drawdown":dd}])

def _as_membership_values(values):
    if values is None:
        return []
    if isinstance(values, (pd.Series, np.ndarray, list, tuple)):
        return values
    return [values]


def finite(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else np.nan


def outcome_label(row: pd.Series) -> str:
    long = row.get("long_exit_reason")
    short = row.get("short_exit_reason")
    if long == "BOTH_OPEN_TIMEOUT" and short == "BOTH_OPEN_TIMEOUT": return "BOTH_OPEN_TIMEOUT"
    if long == "END_OF_DATA" or short == "END_OF_DATA": return "END_OF_DATA"
    be = {"BE", "BE_COST_ADJUSTED", "BE_R_OFFSET"}
    if long == "TP" and short == "SL": return "Long TP / Short SL"
    if long == "SL" and short == "TP": return "Long SL / Short TP"
    if long == "SL" and short == "SL": return "Long SL / Short SL"
    if long == "SL" and short in be: return "Long SL / Short BE"
    if long in be and short == "SL": return "Long BE / Short SL"
    return "Other"


def _at_or_before(group: pd.DataFrame, minutes: float, col: str):
    eligible = group[group["elapsed_minutes"] <= minutes]
    if eligible.empty: return np.nan
    return finite(_series(eligible, col).iloc[-1])


def add_journey_columns(trades: pd.DataFrame, telemetry: pd.DataFrame) -> pd.DataFrame:
    source_attrs = dict(trades.attrs)
    trades = trades.copy()
    if trades.empty or telemetry.empty:
        result = _ensure_journey_columns(trades)
        result.attrs.update(source_attrs)
        return result
    by_pair = {pid: g.sort_values("elapsed_minutes") for pid, g in telemetry.groupby("pair_id", sort=False)}
    updates = []
    for _, row in trades.iterrows():
        g = by_pair.get(row["pair_id"], pd.DataFrame())
        out = {}
        holding = float(row.get("holding_minutes", 0) or 0)
        first_hour_target = 60 if holding >= 60 else holding
        out["first_hour_full_window_available"] = bool(holding >= 60)
        for ind in INDICATORS:
            s = pd.to_numeric(_series(g, ind), errors="coerce")
            entry = finite(s.iloc[0]) if len(s) else np.nan
            exitv = finite(s.iloc[-1]) if len(s) else np.nan
            firsth = _at_or_before(g, first_hour_target, ind) if len(g) else np.nan
            out[f"{ind}_entry"] = entry; out[f"{ind}_first_hour"] = firsth; out[f"{ind}_exit"] = exitv
            out[f"{ind}_min"] = finite(s.min()) if len(s) else np.nan; out[f"{ind}_max"] = finite(s.max()) if len(s) else np.nan; out[f"{ind}_mean"] = finite(s.mean()) if len(s) else np.nan
            out[f"{ind}_journey_change"] = exitv - entry if pd.notna(exitv) and pd.notna(entry) else np.nan
            out[f"{ind}_change_first_hour"] = firsth - entry if pd.notna(firsth) and pd.notna(entry) else np.nan
            out[f"{ind}_slope_per_hour"] = out[f"{ind}_journey_change"] / (holding / 60) if holding > 0 and pd.notna(out[f"{ind}_journey_change"]) else np.nan
            if ind in ("bb_width", "atr"):
                out[f"{ind}_journey_change_pct"] = out[f"{ind}_journey_change"] / entry * 100 if pd.notna(entry) and entry else np.nan
            for mins, label in MILESTONES.items():
                out[f"{ind}_{label}"] = _at_or_before(g, mins, ind) if holding >= mins else np.nan
        updates.append(out)
    journey = pd.DataFrame(updates, index=trades.index)
    result = pd.concat([trades, journey], axis=1)
    result.attrs.update(source_attrs)
    return result


def _ensure_journey_columns(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy(); trades["first_hour_full_window_available"] = pd.Series([], dtype=bool)
    for ind in INDICATORS:
        for suffix in ("entry","first_hour","exit","min","max","mean","journey_change","change_first_hour","slope_per_hour"):
            trades[f"{ind}_{suffix}"] = np.nan
        if ind in ("bb_width","atr"): trades[f"{ind}_journey_change_pct"] = np.nan
        for label in MILESTONES.values(): trades[f"{ind}_{label}"] = np.nan
    return trades


def trade_journey_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    cols = ["outcome","trade_count","average_holding_hours","median_holding_hours","average_adx_entry","average_adx_max","average_adx_change_first_hour","average_adx_slope_per_hour","average_di_spread_entry","average_di_spread_max","average_di_spread_change_first_hour","average_di_spread_slope_per_hour","average_bb_width_entry","average_bb_width_max","average_bb_width_change_first_hour","average_bb_width_journey_change_pct","average_bb_width_slope_per_hour","average_atr_entry","average_atr_max","average_atr_change_first_hour","average_atr_journey_change_pct","average_atr_slope_per_hour","average_net_pnl","total_net_pnl"]
    if trades.empty: return pd.DataFrame(columns=cols)
    t=trades.copy(); t["outcome"] = t.apply(outcome_label, axis=1); rows=[]
    order=["Long TP / Short SL","Long SL / Short TP","Long SL / Short SL","Long SL / Short BE","Long BE / Short SL","BOTH_OPEN_TIMEOUT","END_OF_DATA","Other"]
    for label in order:
        g=t[t.outcome==label]
        rows.append({"outcome":label,"trade_count":len(g),"average_holding_hours":g.holding_hours.mean(),"median_holding_hours":g.holding_hours.median(),"average_net_pnl":g.pair_net_pnl.mean(),"total_net_pnl":g.pair_net_pnl.sum(), **{f"average_{c}":_series(g, c).mean() for c in ["adx_entry","adx_max","adx_change_first_hour","adx_slope_per_hour","di_spread_entry","di_spread_max","di_spread_change_first_hour","di_spread_slope_per_hour","bb_width_entry","bb_width_max","bb_width_change_first_hour","bb_width_journey_change_pct","bb_width_slope_per_hour","atr_entry","atr_max","atr_change_first_hour","atr_journey_change_pct","atr_slope_per_hour"] if c in g}})
    return pd.DataFrame(rows, columns=cols)


def winner_loser_journey_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    metrics={"adx_entry":"ADX at entry","adx_max":"ADX maximum","adx_change_first_hour":"ADX first-hour change","adx_journey_change":"ADX total change","di_spread_entry":"DI Spread at entry","di_spread_max":"DI Spread maximum","di_spread_change_first_hour":"DI Spread first-hour change","di_spread_journey_change":"DI Spread total change","bb_width_entry":"BB Width at entry","bb_width_max":"BB Width maximum","bb_width_change_first_hour":"BB Width first-hour change","bb_width_journey_change_pct":"BB Width total percentage change","atr_entry":"ATR at entry","atr_max":"ATR maximum","atr_change_first_hour":"ATR first-hour change","atr_journey_change_pct":"ATR total percentage change","holding_hours":"Holding time","pair_net_pnl":"Net PnL"}
    rows=[]
    groups={"Winner":trades[trades.pair_net_pnl>0] if not trades.empty else trades,"Loser":trades[trades.pair_net_pnl<0] if not trades.empty else trades,"Flat":trades[trades.pair_net_pnl==0] if not trades.empty else trades}
    for cls,g in groups.items():
        for col,name in metrics.items():
            s=pd.to_numeric(_series(g, col),errors="coerce")
            rows.append({"class":cls,"metric":name,"count":int(s.count()),"mean":s.mean(),"median":s.median(),"standard_deviation":s.std(),"minimum":s.min(),"maximum":s.max()})
    return pd.DataFrame(rows)


def double_sl_journey_analysis(trades: pd.DataFrame, telemetry: pd.DataFrame) -> pd.DataFrame:
    rows=[]; tel={pid:g.sort_values("timestamp") for pid,g in telemetry.groupby("pair_id", sort=False)} if not telemetry.empty else {}
    long_exit = trades.get("long_exit_reason", pd.Series([], dtype=object))
    short_exit = trades.get("short_exit_reason", pd.Series([], dtype=object))
    ds=trades[(long_exit=="SL") & (short_exit=="SL")] if not trades.empty else trades
    for _,r in ds.iterrows():
        lt,st=pd.Timestamp(r.long_exit_time),pd.Timestamp(r.short_exit_time); first_side="long" if lt<=st else "short"; first_t=min(lt,st); second_t=max(lt,st); g=tel.get(r.pair_id,pd.DataFrame())
        row={"pair_id":r.pair_id,"entry_time":r.entry_time,"first_sl_side":first_side,"first_sl_time":first_t,"second_sl_time":second_t,"minutes_between_sl_hits":(second_t-first_t).total_seconds()/60,"holding_hours":r.holding_hours,"pair_net_pnl":r.pair_net_pnl}
        before=g[g.timestamp<=first_t] if not g.empty else g; after=g[g.timestamp>=first_t] if not g.empty else g
        for ind in INDICATORS:
            row[f"{ind}_entry"]=r.get(f"{ind}_entry",np.nan); row[f"{ind}_at_first_sl"]=finite(_series(before, ind).iloc[-1]) if len(before) else np.nan; row[f"{ind}_max_before_first_sl"]=_series(before, ind).max() if len(before) else np.nan; row[f"{ind}_max_after_first_sl"]=_series(after, ind).max() if len(after) else np.nan; row[f"{ind}_change_first_hour"]=r.get(f"{ind}_change_first_hour",np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def save_journey_charts(trades: pd.DataFrame, telemetry: pd.DataFrame, charts_dir: Path) -> list[str]:
    warnings=[]
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        return [f"Chart generation failed for journey charts: {exc}\n{traceback.format_exc()}"]
    charts_dir.mkdir(parents=True, exist_ok=True)
    winners=trades[trades.apply(outcome_label, axis=1).isin(["Long TP / Short SL","Long SL / Short TP"])] if not trades.empty else trades
    long_exit = trades.get("long_exit_reason", pd.Series([], dtype=object))
    short_exit = trades.get("short_exit_reason", pd.Series([], dtype=object))
    double=trades[(long_exit=="SL") & (short_exit=="SL")] if not trades.empty else trades
    for ind in INDICATORS:
        try:
            fig,ax=plt.subplots()
            for label, ids in [("TP/SL winners", winners.pair_id if not winners.empty else []),("Double-SL trades", double.pair_id if not double.empty else [])]:
                g=telemetry[telemetry.pair_id.isin(_as_membership_values(ids))] if not telemetry.empty else telemetry
                if not g.empty: g.groupby("elapsed_minutes")[[ind]].mean()[ind].plot(ax=ax,label=label)
            ax.set_xlabel("Elapsed minutes from entry"); ax.set_ylabel(ind); ax.legend(); fig.tight_layout(); fig.savefig(charts_dir / f"{ind}_journey_winners_vs_double_sl.png"); plt.close(fig)
        except Exception as exc: warnings.append(f"Chart generation failed for {ind} journey: {exc}\n{traceback.format_exc()}")
        try:
            fig,ax=plt.subplots(); _series(trades, f"{ind}_change_first_hour").dropna().plot(kind="hist", bins=30, ax=ax); ax.set_title(f"{ind} first-hour change distribution"); fig.tight_layout(); fig.savefig(charts_dir / f"{ind}_first_hour_change_distribution.png"); plt.close(fig)
        except Exception as exc: warnings.append(f"Chart generation failed for {ind} first-hour distribution: {exc}\n{traceback.format_exc()}")
    return warnings

def trailing_profit_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy, one-row trailing-profit performance report."""
    t = trades.copy()
    def col(name, default=np.nan):
        return t[name] if name in t else pd.Series([default] * len(t), index=t.index)
    la, sa = col("long_trailing_activated", False).fillna(False).astype(bool), col("short_trailing_activated", False).fillna(False).astype(bool)
    le, se = col("long_trailing_enabled", False).fillna(False).astype(bool), col("short_trailing_enabled", False).fillna(False).astype(bool)
    lr, sr = pd.to_numeric(col("long_trailing_profit_r"), errors="coerce"), pd.to_numeric(col("short_trailing_profit_r"), errors="coerce")
    reasons = pd.concat([col("long_exit_reason", None), col("short_exit_reason", None)])
    profits = pd.concat([lr, sr]).dropna(); net = pd.to_numeric(col("pair_net_pnl", 0), errors="coerce").fillna(0)
    categories={"neither":~la&~sa,"only_long":la&~sa,"only_short":~la&sa,"both":la&sa}
    gross_profit=float(net[net>0].sum()); gross_loss=float(net[net<0].sum())
    row={"total_legs":int(col("long_entry_price").notna().sum()+col("short_entry_price").notna().sum()),"total_pairs":int(t.pair_id.nunique()) if "pair_id" in t else len(t),"eligible_legs":int(le.sum()+se.sum()),"trailing_activations":int(la.sum()+sa.sum()),"trailing_activation_percentage":100*(la.sum()+sa.sum())/max(1,le.sum()+se.sum()),"trailing_stop_exits":int((reasons=="TRAILING_STOP").sum()),"activated_other_exit":int(la.sum()+sa.sum()-(reasons=="TRAILING_STOP").sum()),"average_trailing_exit_profit_r":profits.mean(),"median_trailing_exit_profit_r":profits.median(),"maximum_trailing_exit_profit_r":profits.max(),"minimum_trailing_exit_profit_r":profits.min(),"gross_profit":gross_profit,"gross_loss":gross_loss,"fees":pd.to_numeric(col("pair_total_fees",0),errors="coerce").sum(),"net_pnl":net.sum(),"profit_factor":gross_profit/abs(gross_loss) if gross_loss else np.inf,"eligible_long_legs":int(le.sum()),"long_trailing_activations":int(la.sum()),"long_trailing_exits":int((col("long_exit_reason",None)=="TRAILING_STOP").sum()),"average_long_trailing_profit_r":lr.mean(),"median_long_trailing_profit_r":lr.median(),"maximum_long_trailing_profit_r":lr.max(),"long_net_pnl":pd.to_numeric(col("long_net_pnl",0),errors="coerce").sum(),"eligible_short_legs":int(se.sum()),"short_trailing_activations":int(sa.sum()),"short_trailing_exits":int((col("short_exit_reason",None)=="TRAILING_STOP").sum()),"average_short_trailing_profit_r":sr.mean(),"median_short_trailing_profit_r":sr.median(),"maximum_short_trailing_profit_r":sr.max(),"short_net_pnl":pd.to_numeric(col("short_net_pnl",0),errors="coerce").sum(),"net_pair_pnl":net.sum(),"pair_win_rate":100*(net>0).mean() if len(net) else np.nan}
    for name,mask in categories.items(): row[f"pairs_{name}_activated"]=int(mask.sum()); row[f"average_pair_pnl_{name}"]=net[mask].mean()
    return pd.DataFrame([row])
