"""Causal market-regime features computed outside the execution simulator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition


STRUCTURAL_REGIME_DEFINITION = FeatureDefinition(
    name="structural_market_regime",
    version="1",
    required_datasets=(DatasetKind.KLINES,),
    output_columns=("market_regime",),
    availability_rule="completed_utc_day_available_next_midnight",
)


def _benchmark_timestamp_column(frame: pd.DataFrame) -> str:
    for column in ("period_start", "timestamp", "open_time", "time", "datetime", "date"):
        if column in frame.columns:
            return column
    raise ValueError("Structural regime benchmark requires a timestamp column")


def structural_regime_values(
    strategy_times,
    benchmark: pd.DataFrame,
    *,
    sma_days: int,
    slope_lookback_days: int,
) -> np.ndarray:
    """Map a completed-daily structural regime to strategy timestamps causally.

    The benchmark may be a canonical Data Lake kline frame (``period_start``)
    or a legacy-like OHLCV frame (``timestamp``). The close of UTC day D is not
    usable until 00:00 UTC on day D+1. Mapping is therefore always backward from
    each strategy timestamp to the latest already-available daily state.
    """

    if sma_days < 2:
        raise ValueError("sma_days must be at least 2")
    if slope_lookback_days < 1:
        raise ValueError("slope_lookback_days must be positive")
    if benchmark is None or benchmark.empty:
        raise ValueError("Structural regime benchmark is empty")
    if "close" not in benchmark.columns:
        raise ValueError("Structural regime benchmark requires close")

    time_col = _benchmark_timestamp_column(benchmark)
    source = benchmark[[time_col, "close"]].copy()
    source["timestamp"] = pd.to_datetime(source[time_col], utc=True, errors="coerce")
    source["close"] = pd.to_numeric(source["close"], errors="coerce")
    source = (
        source.dropna(subset=["timestamp", "close"])
        .sort_values("timestamp", kind="stable")
        .drop_duplicates("timestamp", keep="last")
    )
    if source.empty:
        raise ValueError("Structural regime benchmark has no valid rows")

    daily = source.set_index("timestamp")["close"].resample("1D").last().dropna().to_frame()
    daily["sma"] = daily["close"].rolling(sma_days, min_periods=sma_days).mean()
    daily["prior_sma"] = daily["sma"].shift(slope_lookback_days)
    daily["market_regime"] = np.where(
        (daily["close"] > daily["sma"]) & (daily["sma"] > daily["prior_sma"]),
        "BULL",
        np.where(
            (daily["close"] < daily["sma"]) & (daily["sma"] < daily["prior_sma"]),
            "BEAR",
            "SIDEWAYS",
        ),
    )
    daily.loc[daily[["sma", "prior_sma"]].isna().any(axis=1), "market_regime"] = None

    available = daily.reset_index()[["timestamp", "market_regime"]]
    available["available_at"] = available["timestamp"] + pd.Timedelta(days=1)
    available = available[["available_at", "market_regime"]].sort_values("available_at")

    target = pd.DataFrame({"strategy_time": pd.to_datetime(strategy_times, utc=True, errors="raise")})
    target["_order"] = np.arange(len(target))
    mapped = pd.merge_asof(
        target.sort_values("strategy_time"),
        available,
        left_on="strategy_time",
        right_on="available_at",
        direction="backward",
    ).sort_values("_order")
    return mapped["market_regime"].to_numpy(dtype=object)
