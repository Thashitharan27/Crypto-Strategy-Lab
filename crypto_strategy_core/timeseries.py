"""Elapsed-time rolling primitives shared by historical and live evidence."""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from datetime import datetime

import pandas as pd


def _positive_finite_days(days: float) -> float:
    value = float(days)
    if not pd.notna(value) or value in (float("inf"), float("-inf")) or value <= 0:
        raise ValueError("window days must be positive and finite")
    return value


def rolling_time_zscore(
    values: Sequence[float],
    available_at: Sequence[datetime],
    *,
    days: float = 7.0,
    minimum: int = 20,
) -> list[float]:
    """Return right-inclusive elapsed-time z-scores using population stddev."""
    window_days = _positive_finite_days(days)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0:
        raise ValueError("minimum samples must be a positive integer")
    if len(values) != len(available_at):
        raise ValueError("values and available_at must have equal length")

    timestamps = pd.DatetimeIndex(pd.to_datetime(list(available_at), utc=True))
    numeric = pd.to_numeric(pd.Series(list(values)), errors="coerce").to_numpy(float)
    ordered = sorted(
        range(len(numeric)),
        key=lambda position: (timestamps[position], position),
    )
    ordered_index = pd.DatetimeIndex([timestamps[position] for position in ordered])
    series = pd.Series(
        [numeric[position] for position in ordered],
        index=ordered_index,
        dtype="float64",
    )
    rolling = series.rolling(f"{window_days}D", min_periods=minimum)
    std = rolling.std(ddof=0)
    ordered_scores = ((series - rolling.mean()) / std.where(std > 0)).to_numpy(float)
    scores = [float("nan")] * len(ordered_scores)
    for position, score in zip(ordered, ordered_scores):
        scores[position] = float(score)
    return scores


def oi_zscore_observations(
    points: Iterable[tuple[datetime, float]],
    *,
    days: float = 7.0,
    minimum: int = 20,
) -> list[tuple[datetime, float]]:
    """Deduplicate source observations by timestamp then calculate rolling z-score."""
    unique: dict[pd.Timestamp, float] = {}
    for timestamp, value in points:
        unique[pd.Timestamp(timestamp).tz_convert("UTC") if pd.Timestamp(timestamp).tzinfo else pd.Timestamp(timestamp, tz="UTC")] = float(value)
    ordered = sorted(unique.items(), key=lambda item: item[0])
    scores = rolling_time_zscore(
        [value for _, value in ordered],
        [timestamp.to_pydatetime() for timestamp, _ in ordered],
        days=days,
        minimum=minimum,
    )
    return [
        (timestamp.to_pydatetime(), score)
        for (timestamp, _), score in zip(ordered, scores)
    ]


def asof_oi_zscore(
    observations: Sequence[tuple[datetime, float]],
    available_at: datetime,
) -> float:
    """Return the latest source-native z-score available at or before a decision."""
    if not observations:
        return float("nan")
    target = pd.Timestamp(available_at)
    target = target.tz_convert("UTC") if target.tzinfo else target.tz_localize("UTC")
    unique: dict[datetime, float] = {}
    for timestamp, value in observations:
        parsed = pd.Timestamp(timestamp)
        normalized_timestamp = (
            parsed.tz_convert("UTC") if parsed.tzinfo else parsed.tz_localize("UTC")
        ).to_pydatetime()
        unique[normalized_timestamp] = float(value)
    normalized = sorted(unique.items(), key=lambda item: item[0])
    times = [timestamp for timestamp, _ in normalized]
    index = bisect_right(times, target.to_pydatetime()) - 1
    return normalized[index][1] if index >= 0 else float("nan")
