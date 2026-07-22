"""Summary statistics for completed dual-position trade pairs."""

from __future__ import annotations

import pandas as pd


def summarize(trades: pd.DataFrame) -> dict[str, object]:
    if trades.empty:
        return {"total_trades": 0}
    wins = trades["net_pnl"] > 0
    losses = trades["net_pnl"] < 0
    gross_profit = trades.loc[wins, "net_pnl"].sum()
    gross_loss = -trades.loc[losses, "net_pnl"].sum()
    equity = trades["net_pnl"].cumsum()
    drawdown = equity - equity.cummax()
    signs = trades["net_pnl"].gt(0).astype(int).replace(0, -1)
    groups = signs.ne(signs.shift()).cumsum()
    streaks = signs.groupby(groups).agg(["first", "size"])
    return {
        "total_trades": int(len(trades)),
        "winning_pairs": int(wins.sum()),
        "losing_pairs": int(losses.sum()),
        "win_rate": float(wins.mean()),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else float("inf"),
        "average_r": float(trades["net_r"].mean()),
        "total_r": float(trades["net_r"].sum()),
        "maximum_drawdown": float(drawdown.min()),
        "maximum_consecutive_losses": int(streaks.loc[streaks["first"] == -1, "size"].max() or 0),
        "maximum_consecutive_wins": int(streaks.loc[streaks["first"] == 1, "size"].max() or 0),
        "average_holding_time": str(trades["holding_time"].mean()),
        "total_fees_paid": float(trades["fees"].sum()),
    }


def equity_curve(trades: pd.DataFrame, initial_equity: float = 0.0) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time", "equity", "drawdown"])
    equity = initial_equity + trades["net_pnl"].cumsum()
    return pd.DataFrame({
        "time": pd.to_datetime(trades[["long_exit_time", "short_exit_time"]].max(axis=1)),
        "equity": equity,
        "drawdown": equity - equity.cummax(),
    })
