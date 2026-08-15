"""Use downloaded Binance higher-timeframe candles for direction voting.

The desktop downloader keeps a ``<SYMBOL>_4h.csv`` dataset beside the strategy
CSV. This module installs a small runtime override so the direction voter uses
that real Binance dataset instead of reconstructing 4-hour closes from the
strategy timeframe.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_strategy_lab.loader import load_ohlcv_csv


_TIMEFRAME_SUFFIX = re.compile(
    r"^(?P<symbol>.+)_(?:1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|3d|1w|1M)$"
)


def _higher_timeframe_path(config) -> Path:
    """Return the sibling Binance CSV for the configured higher timeframe."""
    hours = int(config.direction_vote_higher_timeframe_hours)
    strategy_path = Path(config.strategy_csv).expanduser()
    match = _TIMEFRAME_SUFFIX.match(strategy_path.stem)
    if match is None:
        raise ValueError(
            "Higher-timeframe voting now uses a downloaded Binance dataset. "
            "The strategy CSV filename must use the normal <SYMBOL>_<timeframe>.csv "
            "format (for example XRPUSDT_15m.csv)."
        )
    return strategy_path.with_name(f"{match.group('symbol')}_{hours}h.csv")


def _binance_higher_timeframe_trend_array(self):
    """Vote from the last fully completed downloaded Binance HTF candle."""
    out = np.full(len(self.data), np.nan, float)
    if not self.config.enable_direction_voting or not self.config.direction_vote_use_higher_timeframe or not len(self.data):
        return out

    hours = int(self.config.direction_vote_higher_timeframe_hours)
    if hours <= 0:
        raise ValueError("Higher-timeframe hours must be positive.")

    path = _higher_timeframe_path(self.config)
    if not path.is_file():
        raise FileNotFoundError(
            f"Higher-timeframe Binance dataset not found: {path}. "
            "Open Binance Data Hub and download/update the required shared dataset."
        )

    higher = load_ohlcv_csv(
        str(path),
        self.config.timestamp_unit,
        hours * 60,
        "Higher-timeframe Binance data",
        True,
    )[["timestamp", "close"]].copy()

    # Binance timestamps are candle OPEN times. The candle may influence a
    # strategy decision only after its full higher-timeframe duration has
    # elapsed, which prevents look-ahead bias.
    higher["available_time"] = higher["timestamp"] + pd.Timedelta(hours=hours)
    period = int(self.config.direction_vote_higher_timeframe_sma_period)
    higher["sma"] = higher["close"].rolling(period, min_periods=period).mean()
    higher["prior_sma"] = higher["sma"].shift(1)

    strategy_times = pd.to_datetime(self.data.timestamp, utc=True)
    available = pd.DataFrame(
        {
            "available_time": strategy_times
            + pd.Timedelta(minutes=self.config.strategy_timeframe_minutes),
            "row": np.arange(len(self.data)),
        }
    )
    merged = pd.merge_asof(
        available.sort_values("available_time"),
        higher[["available_time", "close", "sma", "prior_sma"]]
        .sort_values("available_time"),
        on="available_time",
        direction="backward",
    )

    long_vote = (merged["close"] > merged["sma"]) & (
        merged["sma"] > merged["prior_sma"]
    )
    short_vote = (merged["close"] < merged["sma"]) & (
        merged["sma"] < merged["prior_sma"]
    )
    out[merged.loc[long_vote, "row"].to_numpy(int)] = 1
    out[merged.loc[short_vote, "row"].to_numpy(int)] = -1
    return out


def install_binance_higher_timeframe_patch() -> None:
    """Install the Binance-dataset implementation on ``BacktestEngine`` once."""
    from crypto_strategy_lab.engine import BacktestEngine

    if getattr(BacktestEngine, "_binance_htf_dataset_patch", False):
        return
    BacktestEngine._higher_timeframe_trend_array = _binance_higher_timeframe_trend_array
    BacktestEngine._binance_htf_dataset_patch = True
