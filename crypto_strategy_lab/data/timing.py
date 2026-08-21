"""Canonical timing and availability rules used to prevent look-ahead."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from .schemas import DatasetKind


_INTERVAL_RE = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>[smhdw])$")

_CANDLE_DATASETS = {
    DatasetKind.KLINES,
    DatasetKind.MARK_PRICE_KLINES,
    DatasetKind.INDEX_PRICE_KLINES,
    DatasetKind.PREMIUM_INDEX_KLINES,
}

_INTERVAL_AGGREGATE_DATASETS = {
    DatasetKind.FUTURES_METRICS,
}


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, treating a naive value as UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def interval_to_timedelta(interval: str) -> timedelta:
    """Convert fixed Binance intervals such as 1m, 15m, 4h or 1d."""

    match = _INTERVAL_RE.fullmatch(str(interval).strip())
    if not match:
        raise ValueError(f"Unsupported fixed interval: {interval!r}")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    if unit == "d":
        return timedelta(days=count)
    return timedelta(weeks=count)


def canonical_available_at(
    dataset: DatasetKind,
    event_time: datetime,
    *,
    interval: str | None = None,
    period_end: datetime | None = None,
) -> datetime:
    """Return the earliest timestamp at which a source value may be consumed.

    Candle and interval-aggregate datasets are withheld until their interval is
    complete. Event datasets (funding, trades and order-book events) are usable
    at their event timestamp.
    """

    event_time = ensure_utc(event_time)
    if dataset in _CANDLE_DATASETS or dataset in _INTERVAL_AGGREGATE_DATASETS:
        if period_end is not None:
            return ensure_utc(period_end)
        if interval is None:
            raise ValueError(f"{dataset.value} requires interval or period_end")
        return event_time + interval_to_timedelta(interval)
    return event_time
