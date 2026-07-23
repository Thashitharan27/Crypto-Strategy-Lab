"""Summary statistics for completed dual-position trade pairs."""

from __future__ import annotations

import pandas as pd


def _max_streak(mask: pd.Series) -> int:
    if mask.empty:
        return 0
    groups = mask.ne(mask.shift()).cumsum()
    return int(mask.groupby(groups).sum().max() or 0)


def summarize(trades: pd.DataFrame, initial_equity: float = 1000.0) -> dict[str, object]:
    if trades.empty:
        return {"total_pairs": 0, "ending_equity": initial_equity, "exit_source_counts": {"1M_INTRABAR": 0, "15M_FALLBACK": 0, "END_OF_DATA": 0}}
    wins = trades["pair_net_pnl"] > 0
    losses = trades["pair_net_pnl"] < 0
    flats = trades["pair_net_pnl"] == 0
    gross_profit = trades.loc[wins, "pair_net_pnl"].sum()
    gross_loss = -trades.loc[losses, "pair_net_pnl"].sum()
    equity = trades["equity_after_trade"]
    running_peak = equity.cummax().clip(lower=initial_equity)
    drawdown = equity - running_peak
    max_dd = float(drawdown.min())
    max_dd_pct = float((drawdown / running_peak).min()) if not running_peak.empty else 0.0
    source_values = pd.concat([trades.get("long_exit_source", pd.Series(dtype=object)), trades.get("short_exit_source", pd.Series(dtype=object))], ignore_index=True)
    source_counts = {"1M_INTRABAR": int((source_values == "1M_INTRABAR").sum()), "15M_FALLBACK": int((source_values == "15M_FALLBACK").sum()), "END_OF_DATA": int((source_values == "END_OF_DATA").sum())}
    timeout_pairs = trades[trades.get("both_open_timeout_triggered", pd.Series(False, index=trades.index)).astype(bool)]
    fallback_reasons = pd.concat([trades.get("long_fallback_reason", pd.Series(dtype=object)), trades.get("short_fallback_reason", pd.Series(dtype=object))], ignore_index=True).dropna().value_counts().to_dict()
    combos = {}
    grouped = trades.groupby(["long_exit_reason", "short_exit_reason"], dropna=False)
    for (long_reason, short_reason), group in grouped:
        key = f"Long {long_reason} / Short {short_reason}"
        combos[key] = {
            "count": int(len(group)),
            "percentage": float(len(group) / len(trades)),
            "average_net_r": float(group["pair_net_r"].mean()),
            "total_net_r": float(group["pair_net_r"].sum()),
        }
    return {
        "total_pairs": int(len(trades)),
        "wins": int(wins.sum()),
        "losses": int(losses.sum()),
        "flat_pairs": int(flats.sum()),
        "win_rate": float(wins.mean()),
        "loss_rate": float(losses.mean()),
        "average_gross_account_r": float(trades.get("pair_gross_account_r", trades["pair_gross_r"]).mean()),
        "average_net_r": float(trades["pair_net_r"].mean()),
        "average_net_account_r": float(trades.get("pair_net_account_r", trades["pair_net_r"]).mean()),
        "median_net_r": float(trades["pair_net_r"].median()),
        "total_net_r": float(trades["pair_net_r"].sum()),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else float("inf"),
        "ending_equity": float(equity.iloc[-1]),
        "total_return_percentage": float((equity.iloc[-1] / initial_equity - 1) * 100),
        "maximum_drawdown": max_dd,
        "maximum_drawdown_percentage": max_dd_pct * 100,
        "maximum_consecutive_wins": _max_streak(wins),
        "maximum_consecutive_losses": _max_streak(losses),
        "average_holding_time": float(trades["holding_hours"].mean()),
        "total_fees": float(trades["pair_total_fees"].sum()),
        "pairs_closed_by_both_open_timeout": int(len(timeout_pairs)),
        "average_timeout_pair_pnl": float(timeout_pairs["pair_net_pnl"].mean()) if not timeout_pairs.empty else 0.0,
        "total_timeout_pair_pnl": float(timeout_pairs["pair_net_pnl"].sum()) if not timeout_pairs.empty else 0.0,
        "timeout_pairs_profitable": int((timeout_pairs["pair_net_pnl"] > 0).sum()) if not timeout_pairs.empty else 0,
        "timeout_pairs_losing": int((timeout_pairs["pair_net_pnl"] < 0).sum()) if not timeout_pairs.empty else 0,
        "ambiguous_event_count": int(trades["ambiguous_candle"].sum()),
        "ambiguous_intrabar_count": int(trades.get("ambiguous_intrabar", trades["ambiguous_candle"]).sum()),
        "missing_intrabar_interval_count": int(trades.get("missing_intrabar_data", pd.Series(dtype=bool)).sum()),
        "exit_source_counts": source_counts,
        "intrabar_exit_count": source_counts["1M_INTRABAR"],
        "fallback_15m_exit_count": source_counts["15M_FALLBACK"],
        "end_of_data_exit_count": source_counts["END_OF_DATA"],
        "fallback_reason_counts": {str(k): int(v) for k, v in fallback_reasons.items()},
        "leverage_capped_trade_count": int(trades.get("leverage_capped", pd.Series(dtype=bool)).sum()),
        "average_combined_effective_leverage": float(trades.get("combined_effective_leverage", pd.Series(dtype=float)).mean()),
        "maximum_combined_effective_leverage": float(trades.get("combined_effective_leverage", pd.Series(dtype=float)).max()),
        "average_fees_as_percentage_of_expected_winning_profit": float(trades.get("fees_as_percentage_of_expected_winning_profit", pd.Series(dtype=float)).mean()),
        "exit_combinations": combos,
    }


def equity_curve(trades: pd.DataFrame, initial_equity: float = 1000.0) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time", "equity", "drawdown"])
    equity = trades["equity_after_trade"]
    return pd.DataFrame({
        "time": pd.to_datetime(trades[["long_exit_time", "short_exit_time"]].max(axis=1)),
        "equity": equity,
        "drawdown": equity - equity.cummax().clip(lower=initial_equity),
    })
