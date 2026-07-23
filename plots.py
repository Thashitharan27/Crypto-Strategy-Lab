"""Plot exports for backtest results."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from output_manager import compatible_resample_freq

logger = logging.getLogger(__name__)


def _supported_resample_freq(series: pd.Series, preferred: str) -> str:
    """Return the first equivalent alias supported by the installed pandas version."""
    candidates = [compatible_resample_freq(preferred)]
    fallback = {"ME": "M", "YE": "Y", "M": "ME", "Y": "YE"}.get(candidates[0])
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            series.resample(candidate)
            return candidate
        except ValueError as exc:
            last_error = exc
    raise last_error if last_error is not None else ValueError(f"Unsupported resample frequency: {preferred}")


def _month_year_frequencies(returns: pd.DataFrame) -> tuple[str, str]:
    """Return month/year-end aliases supported across pandas versions."""
    pnl_by_exit = returns.set_index("exit_time")["pair_net_pnl"]
    return _supported_resample_freq(pnl_by_exit, "ME"), _supported_resample_freq(pnl_by_exit, "YE")


def _save_chart(chart_name: str, draw: Callable[[], None], warnings: list[str]) -> None:
    try:
        draw()
    except Exception as exc:  # noqa: BLE001 - chart export must not fail the backtest.
        message = f"Chart generation failed for {chart_name}: {exc}"
        logger.warning(message, exc_info=True)
        warnings.append(message)


def save_plots(trades: pd.DataFrame, equity: pd.DataFrame, output_dir: Path) -> list[str]:
    warnings: list[str] = []
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001 - chart export must not fail the backtest.
        message = f"Chart generation failed for all charts: {exc}"
        logger.warning(message, exc_info=True)
        return [message]

    output_dir.mkdir(parents=True, exist_ok=True)

    if not equity.empty:
        def equity_curve_chart() -> None:
            ax = equity.plot(x="time", y="equity", title="Equity Curve", legend=False)
            try:
                ax.set_ylabel("Equity")
                ax.figure.tight_layout()
                ax.figure.savefig(output_dir / "equity_curve.png")
            finally:
                plt.close(ax.figure)

        def drawdown_chart() -> None:
            ax = equity.plot(x="time", y="drawdown", title="Drawdown", legend=False)
            try:
                ax.set_ylabel("Drawdown")
                ax.figure.tight_layout()
                ax.figure.savefig(output_dir / "drawdown.png")
            finally:
                plt.close(ax.figure)

        _save_chart("equity_curve.png", equity_curve_chart, warnings)
        _save_chart("drawdown.png", drawdown_chart, warnings)

    if trades.empty:
        return warnings

    charts = [
        (trades["pair_net_r"], "R Distribution", "r_distribution.png"),
        (trades["holding_hours"], "Holding Time (hours)", "holding_time_distribution.png"),
    ]
    for series, title, filename in charts:
        def histogram_chart(series: pd.Series = series, title: str = title, filename: str = filename) -> None:
            fig, ax = plt.subplots()
            try:
                series.hist(ax=ax, bins=50)
                ax.set_title(title)
                fig.tight_layout()
                fig.savefig(output_dir / filename)
            finally:
                plt.close(fig)

        _save_chart(filename, histogram_chart, warnings)

    if "adx" in trades:
        def adx_distribution_chart() -> None:
            fig, ax = plt.subplots()
            try:
                trades.loc[trades["pair_net_pnl"] > 0, "adx"].dropna().plot(kind="hist", bins=20, alpha=0.6, ax=ax, label="Winning trades")
                trades.loc[trades["pair_net_pnl"] < 0, "adx"].dropna().plot(kind="hist", bins=20, alpha=0.6, ax=ax, label="Losing trades")
                ax.set_title("ADX Distribution"); ax.set_xlabel("ADX"); ax.legend(); fig.tight_layout(); fig.savefig(output_dir / "adx_distribution.png")
            finally:
                plt.close(fig)
        def adx_vs_pnl_chart() -> None:
            fig, ax = plt.subplots()
            try:
                trades.plot(kind="scatter", x="adx", y="pair_net_pnl", ax=ax, title="ADX vs PnL")
                ax.set_xlabel("ADX"); ax.set_ylabel("Pair Net PnL"); fig.tight_layout(); fig.savefig(output_dir / "adx_vs_pnl.png")
            finally:
                plt.close(fig)
        _save_chart("adx_distribution.png", adx_distribution_chart, warnings)
        _save_chart("adx_vs_pnl.png", adx_vs_pnl_chart, warnings)

    returns = trades.assign(exit_time=pd.to_datetime(trades[["long_exit_time", "short_exit_time"]].max(axis=1)))
    try:
        monthly_freq, yearly_freq = _month_year_frequencies(returns)
    except Exception as exc:  # noqa: BLE001 - chart export must not fail the backtest.
        message = f"Chart generation failed for return charts: {exc}"
        logger.warning(message, exc_info=True)
        warnings.append(message)
        return warnings

    for freq, filename, title in [
        (monthly_freq, "monthly_returns.png", "Monthly Returns"),
        (yearly_freq, "yearly_returns.png", "Yearly Returns"),
    ]:
        def returns_chart(freq: str = freq, filename: str = filename, title: str = title) -> None:
            agg = returns.set_index("exit_time")["pair_net_pnl"].resample(freq).sum()
            fig, ax = plt.subplots()
            try:
                agg.plot(kind="bar", ax=ax, title=title)
                fig.tight_layout()
                fig.savefig(output_dir / filename)
            finally:
                plt.close(fig)

        _save_chart(filename, returns_chart, warnings)

    return warnings
