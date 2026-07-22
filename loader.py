"""CSV loading utilities for Binance OHLCV files."""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def load_ohlcv_csv(path: str, timestamp_unit: str | None = None) -> pd.DataFrame:
    """Load a Binance OHLCV CSV and validate the required schema."""
    df = pd.read_csv(path, usecols=REQUIRED_COLUMNS)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit=timestamp_unit, utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        df["timestamp"] = pd.to_datetime(pd.read_csv(path, usecols=["timestamp"])["timestamp"], utc=True)
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)
