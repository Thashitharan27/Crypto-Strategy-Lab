"""Searchsorted intrabar slicing without changing simulator exit logic.

The mature engine asks for intrabar rows with the idiom::

    frame[(frame.timestamp >= start) & (frame.timestamp < end)]

On a multi-year 1m DataFrame that boolean expression scans every row for every
strategy candle. ``SearchsortedIntrabarFrame`` preserves that public expression,
but turns the paired timestamp predicates into positional ``searchsorted`` bounds.
The resulting slice is a DataFrame-compatible intrabar window whose ``iterrows``
uses pandas' much lighter tuple iterator. The stateful simulator therefore keeps
its existing row-by-row exit order without allocating a Series for every 1m bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class _TimestampRange:
    owner_id: int
    lower: pd.Timestamp | None = None
    lower_inclusive: bool = True
    upper: pd.Timestamp | None = None
    upper_inclusive: bool = False

    def __and__(self, other):
        if not isinstance(other, _TimestampRange) or other.owner_id != self.owner_id:
            return NotImplemented
        lower = self.lower if self.lower is not None else other.lower
        lower_inclusive = self.lower_inclusive if self.lower is not None else other.lower_inclusive
        if self.lower is not None and other.lower is not None:
            if other.lower > self.lower:
                lower, lower_inclusive = other.lower, other.lower_inclusive
            elif other.lower == self.lower:
                lower_inclusive = self.lower_inclusive and other.lower_inclusive

        upper = self.upper if self.upper is not None else other.upper
        upper_inclusive = self.upper_inclusive if self.upper is not None else other.upper_inclusive
        if self.upper is not None and other.upper is not None:
            if other.upper < self.upper:
                upper, upper_inclusive = other.upper, other.upper_inclusive
            elif other.upper == self.upper:
                upper_inclusive = self.upper_inclusive and other.upper_inclusive
        return _TimestampRange(
            owner_id=self.owner_id,
            lower=lower,
            lower_inclusive=lower_inclusive,
            upper=upper,
            upper_inclusive=upper_inclusive,
        )


class _TimestampAccessor:
    """Series-compatible timestamp view with lazy range predicates."""

    def __init__(self, frame: "SearchsortedIntrabarFrame") -> None:
        self._frame = frame

    @staticmethod
    def _utc(value) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    @property
    def _series(self) -> pd.Series:
        return self._frame._timestamp_series()

    def __ge__(self, value):
        return _TimestampRange(id(self._frame), lower=self._utc(value), lower_inclusive=True)

    def __gt__(self, value):
        return _TimestampRange(id(self._frame), lower=self._utc(value), lower_inclusive=False)

    def __lt__(self, value):
        return _TimestampRange(id(self._frame), upper=self._utc(value), upper_inclusive=False)

    def __le__(self, value):
        return _TimestampRange(id(self._frame), upper=self._utc(value), upper_inclusive=True)

    def __getitem__(self, key):
        return self._series.__getitem__(key)

    def __len__(self) -> int:
        return len(self._series)

    def __array__(self, dtype=None):
        return np.asarray(self._series, dtype=dtype)

    def __getattr__(self, name):
        return getattr(self._series, name)


class _IntrabarWindowFrame(pd.DataFrame):
    """Internal engine window with Series-free row iteration.

    ``BacktestEngine`` only reads row attributes (timestamp/open/high/low) from
    these range slices. ``itertuples`` preserves those values and exact index
    ordering while avoiding the much heavier Series construction performed by
    pandas ``DataFrame.iterrows``.
    """

    @property
    def _constructor(self):
        # Keep ordinary pandas behavior for any secondary DataFrame operation.
        return pd.DataFrame

    def iterrows(self):
        rows = pd.DataFrame.itertuples(self, index=False, name="IntrabarRow")
        return zip(self.index, rows)


class SearchsortedIntrabarFrame(pd.DataFrame):
    """DataFrame whose timestamp range masks use a pre-built DatetimeIndex."""

    _metadata = ["_intrabar_timestamp_index", "intrabar_index_mode", "intrabar_iteration_mode"]

    @property
    def _constructor(self):
        return SearchsortedIntrabarFrame

    def _timestamp_series(self) -> pd.Series:
        return pd.DataFrame.__getitem__(self, "timestamp")

    @property
    def timestamp(self):
        return _TimestampAccessor(self)

    def _boolean_mask_for_range(self, bounds: _TimestampRange) -> np.ndarray:
        series = pd.to_datetime(self._timestamp_series(), utc=True)
        mask = np.ones(len(self), dtype=bool)
        if bounds.lower is not None:
            mask &= (series >= bounds.lower).to_numpy() if bounds.lower_inclusive else (series > bounds.lower).to_numpy()
        if bounds.upper is not None:
            mask &= (series <= bounds.upper).to_numpy() if bounds.upper_inclusive else (series < bounds.upper).to_numpy()
        return mask

    @staticmethod
    def _engine_window(frame) -> _IntrabarWindowFrame:
        return _IntrabarWindowFrame(frame, copy=False)

    def __getitem__(self, key):
        if isinstance(key, _TimestampRange) and key.owner_id == id(self):
            index = getattr(self, "_intrabar_timestamp_index", None)
            if index is not None and getattr(self, "intrabar_index_mode", None) == "searchsorted":
                left = 0
                right = len(self)
                if key.lower is not None:
                    left = int(index.searchsorted(key.lower, side="left" if key.lower_inclusive else "right"))
                if key.upper is not None:
                    right = int(index.searchsorted(key.upper, side="right" if key.upper_inclusive else "left"))
                return self._engine_window(self.iloc[left:right])
            return self._engine_window(
                pd.DataFrame.__getitem__(self, self._boolean_mask_for_range(key))
            )
        return pd.DataFrame.__getitem__(self, key)


def as_searchsorted_intrabar(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """Wrap a sorted intrabar frame; fall back transparently if it is unsorted."""

    if frame is None:
        return None
    if "timestamp" not in frame.columns:
        raise ValueError("Intrabar data requires a timestamp column")

    wrapped = SearchsortedIntrabarFrame(frame.copy(deep=False))
    timestamps = pd.DatetimeIndex(pd.to_datetime(wrapped._timestamp_series(), utc=True))
    wrapped._intrabar_timestamp_index = timestamps
    wrapped.intrabar_index_mode = (
        "searchsorted"
        if not timestamps.hasnans and timestamps.is_monotonic_increasing
        else "boolean_fallback"
    )
    wrapped.intrabar_iteration_mode = "itertuples"
    return wrapped
