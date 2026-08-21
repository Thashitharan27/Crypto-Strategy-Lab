"""Temporary bridge from canonical Data Lake v2 frames to the current engine shape.

This module exists only for migration parity. New feature/simulation code should
consume canonical columns directly instead of depending on `timestamp` OHLCV.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pandas.api.types import is_numeric_dtype

from crypto_strategy_lab.loader import DataSummary

from .query import DataRequest
from .store import MarketDataStore
from .timing import interval_to_timedelta


@dataclass(frozen=True, slots=True)
class FrameParity:
    rows_left: int
    rows_right: int
    overlapping_rows: int
    timestamp_mismatches: int
    value_mismatches: int
    max_abs_diff: dict[str, float]

    @property
    def exact(self) -> bool:
        return (
            self.rows_left == self.rows_right
            and self.timestamp_mismatches == 0
            and self.value_mismatches == 0
        )


@dataclass(frozen=True, slots=True)
class TradeParity:
    """Deterministic row/column comparison of two engine trade lists."""

    rows_left: int
    rows_right: int
    columns_compared: tuple[str, ...]
    columns_only_left: tuple[str, ...]
    columns_only_right: tuple[str, ...]
    mismatched_rows: int
    column_mismatches: dict[str, int]
    max_abs_diff: dict[str, float]

    @property
    def exact(self) -> bool:
        return (
            self.rows_left == self.rows_right
            and not self.columns_only_left
            and not self.columns_only_right
            and self.mismatched_rows == 0
        )


def canonical_to_legacy_ohlcv(
    frame: pd.DataFrame,
    *,
    label: str = "Data Lake data",
    expected_timeframe_minutes: int | None = None,
) -> pd.DataFrame:
    """Produce exactly the six-column shape expected by the current engine."""

    required = ("period_start", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing canonical OHLCV columns: {missing}")
    result = frame.loc[:, list(required)].rename(columns={"period_start": "timestamp"}).copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True, errors="raise")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    result = result.sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if result.empty:
        raise ValueError("No canonical OHLCV rows remain")

    diffs = result["timestamp"].diff().dropna()
    detected: int | None = None
    if not diffs.empty:
        mode = diffs.dt.total_seconds().div(60).mode()
        if not mode.empty:
            detected = int(mode.iloc[0])
    basis = expected_timeframe_minutes or detected or 1
    expected = pd.Timedelta(minutes=basis)
    gaps: list[tuple[object, object, int]] = []
    missing_candles = 0
    for idx, delta in diffs[diffs > expected].items():
        miss = int(delta / expected) - 1
        missing_candles += miss
        gaps.append((result.loc[idx - 1, "timestamp"], result.loc[idx, "timestamp"], miss))
    result.attrs["summary"] = DataSummary(
        label,
        len(result),
        result["timestamp"].min(),
        result["timestamp"].max(),
        detected,
        missing_candles,
        gaps,
    )
    return result


def load_backtest_frames_from_store(
    store: MarketDataStore,
    request: DataRequest,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Load strategy/intrabar frames for current-engine parity tests."""

    strategy = canonical_to_legacy_ohlcv(
        store.load_klines(request, request.strategy_interval),
        label="Strategy data (Data Lake v2)",
        expected_timeframe_minutes=int(interval_to_timedelta(request.strategy_interval).total_seconds() // 60),
    )
    intrabar = None
    if request.intrabar_interval:
        intrabar = canonical_to_legacy_ohlcv(
            store.load_klines(request, request.intrabar_interval),
            label="Intrabar data (Data Lake v2)",
            expected_timeframe_minutes=int(interval_to_timedelta(request.intrabar_interval).total_seconds() // 60),
        )
    return strategy, intrabar


def compare_ohlcv_frames(left: pd.DataFrame, right: pd.DataFrame, *, tolerance: float = 0.0) -> FrameParity:
    """Compare two current-engine OHLCV frames over their exact timestamps."""

    columns = ("open", "high", "low", "close", "volume")
    left_frame = left.loc[:, ["timestamp", *columns]].copy()
    right_frame = right.loc[:, ["timestamp", *columns]].copy()
    left_frame["timestamp"] = pd.to_datetime(left_frame["timestamp"], utc=True, errors="raise")
    right_frame["timestamp"] = pd.to_datetime(right_frame["timestamp"], utc=True, errors="raise")
    left_frame = left_frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    right_frame = right_frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")

    left_times = set(left_frame["timestamp"])
    right_times = set(right_frame["timestamp"])
    timestamp_mismatches = len(left_times.symmetric_difference(right_times))
    merged = left_frame.merge(right_frame, on="timestamp", how="inner", suffixes=("_left", "_right"))
    max_abs_diff: dict[str, float] = {}
    mismatch_mask = pd.Series(False, index=merged.index)
    for column in columns:
        diff = (pd.to_numeric(merged[f"{column}_left"]) - pd.to_numeric(merged[f"{column}_right"])).abs()
        max_abs_diff[column] = float(diff.max()) if not diff.empty else 0.0
        mismatch_mask |= diff > tolerance
    return FrameParity(
        rows_left=len(left_frame),
        rows_right=len(right_frame),
        overlapping_rows=len(merged),
        timestamp_mismatches=timestamp_mismatches,
        value_mismatches=int(mismatch_mask.sum()),
        max_abs_diff=max_abs_diff,
    )


def _datetime_like(column: str) -> bool:
    name = column.lower()
    return any(token in name for token in ("time", "timestamp", "date"))


def compare_trade_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    tolerance: float = 1e-10,
    ignored_columns: tuple[str, ...] = (),
) -> TradeParity:
    """Compare complete engine trade rows without depending on one fixed schema.

    The engine is deterministic, so migration parity should preserve row order as
    well as every output value. Numeric columns use an absolute tolerance;
    datetime-like columns are normalized to UTC; other columns compare exactly.
    """

    ignored = set(ignored_columns)
    left_columns = [column for column in left.columns if column not in ignored]
    right_columns = [column for column in right.columns if column not in ignored]
    common = tuple(column for column in left_columns if column in right_columns)
    only_left = tuple(column for column in left_columns if column not in right_columns)
    only_right = tuple(column for column in right_columns if column not in left_columns)

    overlap = min(len(left), len(right))
    left_frame = left.iloc[:overlap].reset_index(drop=True)
    right_frame = right.iloc[:overlap].reset_index(drop=True)
    row_mismatch = pd.Series(False, index=range(overlap), dtype=bool)
    column_mismatches: dict[str, int] = {}
    max_abs_diff: dict[str, float] = {}

    for column in common:
        left_values = left_frame[column]
        right_values = right_frame[column]
        if is_numeric_dtype(left_values.dtype) and is_numeric_dtype(right_values.dtype):
            a = pd.to_numeric(left_values, errors="coerce")
            b = pd.to_numeric(right_values, errors="coerce")
            both_na = a.isna() & b.isna()
            both_values = a.notna() & b.notna()
            diff = (a - b).abs()
            same = both_na | (both_values & (diff <= tolerance))
            valid_diff = diff[both_values]
            max_abs_diff[column] = float(valid_diff.max()) if not valid_diff.empty else 0.0
        elif _datetime_like(column):
            a = pd.to_datetime(left_values, utc=True, errors="coerce")
            b = pd.to_datetime(right_values, utc=True, errors="coerce")
            same = (a.eq(b)) | (a.isna() & b.isna())
        else:
            a = left_values.astype("string")
            b = right_values.astype("string")
            same = a.eq(b).fillna(False) | (a.isna() & b.isna())
        mismatches = ~same.fillna(False)
        count = int(mismatches.sum())
        if count:
            column_mismatches[column] = count
            row_mismatch |= mismatches

    mismatched_rows = int(row_mismatch.sum()) + abs(len(left) - len(right))
    return TradeParity(
        rows_left=len(left),
        rows_right=len(right),
        columns_compared=common,
        columns_only_left=only_left,
        columns_only_right=only_right,
        mismatched_rows=mismatched_rows,
        column_mismatches=column_mismatches,
        max_abs_diff=max_abs_diff,
    )
