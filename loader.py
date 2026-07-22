"""CSV loading utilities for Binance OHLCV files."""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
TIMESTAMP_ALIASES = ("timestamp", "open_time", "time", "datetime", "date")
EXPECTED_INTERVAL = pd.Timedelta(minutes=15)


def load_ohlcv_csv(path: str, timestamp_unit: str | None = "ms") -> pd.DataFrame:
    """Load, normalize, and validate a Binance-style OHLCV CSV."""
    df = pd.read_csv(path)
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]

    time_col = next((col for col in TIMESTAMP_ALIASES if col in df.columns), None)
    if time_col is None:
        raise ValueError(f"Missing timestamp column. Accepted aliases: {list(TIMESTAMP_ALIASES)}")
    if time_col != "timestamp":
        df = df.rename(columns={time_col: "timestamp"})

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    before = len(df)
    raw_timestamp = df["timestamp"].copy()

    unit = timestamp_unit or None
    df["timestamp"] = pd.to_datetime(raw_timestamp, unit=unit, utc=True, errors="coerce")
    if df["timestamp"].isna().any() and unit is not None:
        fallback = pd.to_datetime(raw_timestamp, utc=True, errors="coerce")
        df["timestamp"] = df["timestamp"].fillna(fallback)

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=REQUIRED_COLUMNS)
    invalid_ohlc = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
        | (df["volume"] < 0)
    )
    invalid_count = int(invalid_ohlc.sum())
    df = df.loc[~invalid_ohlc]
    df = df.sort_values("timestamp", kind="stable")
    duplicate_count = int(df["timestamp"].duplicated().sum())
    df = df.drop_duplicates("timestamp", keep="first").reset_index(drop=True)

    diffs = df["timestamp"].diff().dropna()
    missing_gaps = diffs[diffs > EXPECTED_INTERVAL]
    missing_candles = int(((missing_gaps / EXPECTED_INTERVAL) - 1).sum()) if not missing_gaps.empty else 0
    if missing_candles:
        print(f"WARNING: Detected {missing_candles} missing 15-minute candles across {len(missing_gaps)} gaps.")

    print(
        "Loading summary: "
        f"rows_read={before}, rows_loaded={len(df)}, rows_removed={before - len(df)}, "
        f"duplicates_removed={duplicate_count}, invalid_ohlc_removed={invalid_count}, "
        f"missing_15m_candles={missing_candles}, "
        f"start={df['timestamp'].min() if not df.empty else 'n/a'}, "
        f"end={df['timestamp'].max() if not df.empty else 'n/a'}"
    )
    if df.empty:
        raise ValueError("No valid OHLCV rows loaded")
    return df
