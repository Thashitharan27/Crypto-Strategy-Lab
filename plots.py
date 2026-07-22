"""Plot exports for backtest results."""

from __future__ import annotations

from pathlib import Path
import pandas as pd


def save_plots(trades: pd.DataFrame, equity: pd.DataFrame, output_dir: Path) -> None:
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    if not equity.empty:
        ax = equity.plot(x="time", y="equity", title="Equity Curve", legend=False)
        ax.set_ylabel("Equity")
        ax.figure.tight_layout()
        ax.figure.savefig(output_dir / "equity_curve.png")
        plt.close(ax.figure)
    if trades.empty:
        return
    charts = [
        (trades["net_r"], "R Distribution", "r_distribution.png"),
        (trades["holding_time"].dt.total_seconds() / 3600, "Holding Time (hours)", "holding_time_distribution.png"),
    ]
    for series, title, filename in charts:
        fig, ax = plt.subplots()
        series.hist(ax=ax, bins=50)
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(output_dir / filename)
        plt.close(fig)
    returns = trades.assign(exit_time=pd.to_datetime(trades[["long_exit_time", "short_exit_time"]].max(axis=1)))
    for freq, filename, title in [("ME", "monthly_returns.png", "Monthly Returns"), ("YE", "yearly_returns.png", "Yearly Returns")]:
        agg = returns.set_index("exit_time")["net_pnl"].resample(freq).sum()
        fig, ax = plt.subplots()
        agg.plot(kind="bar", ax=ax, title=title)
        fig.tight_layout()
        fig.savefig(output_dir / filename)
        plt.close(fig)
