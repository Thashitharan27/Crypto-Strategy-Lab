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
        return {"total_pairs": 0, "ending_equity": initial_equity}
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
        "average_net_r": float(trades["pair_net_r"].mean()),
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
        "ambiguous_event_count": int(trades["ambiguous_candle"].sum()),
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
