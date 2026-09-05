"""Causal futures basis evidence shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np
import pandas as pd

from .timeseries import rolling_time_zscore


def _canonical_series(
    timestamps: Sequence[object],
    values: Sequence[float],
    *,
    name: str,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    if len(timestamps) != len(values):
        raise ValueError(f"{name} timestamps and values must have equal lengths")
    frame = pd.DataFrame(
        {
            "available_at": pd.to_datetime(list(timestamps), utc=True),
            "value": pd.to_numeric(pd.Series(list(values)), errors="coerce"),
        }
    )
    frame = (
        frame.sort_values("available_at", kind="stable")
        .drop_duplicates("available_at", keep="last")
        .reset_index(drop=True)
    )
    return (
        pd.DatetimeIndex(frame["available_at"]),
        frame["value"].to_numpy(float),
    )


def _asof_indices(
    decision_times: pd.DatetimeIndex,
    source_times: pd.DatetimeIndex,
) -> np.ndarray:
    if not len(source_times):
        return np.full(len(decision_times), -1, dtype=int)
    source_ns = source_times.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    decision_ns = decision_times.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    return np.searchsorted(source_ns, decision_ns, side="right") - 1


def _asof_numeric(
    decision_times: pd.DatetimeIndex,
    source_times: pd.DatetimeIndex,
    values: np.ndarray,
) -> np.ndarray:
    out = np.full(len(decision_times), np.nan, dtype=float)
    index = _asof_indices(decision_times, source_times)
    valid = index >= 0
    out[valid] = values[index[valid]]
    return out


def _asof_times(
    decision_times: pd.DatetimeIndex,
    source_times: pd.DatetimeIndex,
) -> list[object]:
    index = _asof_indices(decision_times, source_times)
    out: list[object] = [pd.NaT] * len(decision_times)
    for position, source_index in enumerate(index):
        if source_index >= 0:
            out[position] = source_times[int(source_index)]
    return out


def _relative(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.divide(
        left - right,
        right,
        out=np.full(len(left), np.nan, dtype=float),
        where=np.isfinite(left) & np.isfinite(right) & (right != 0),
    )


def _basis_state(values: np.ndarray, neutral_bps: float = 1.0) -> list[str]:
    bps = values * 10000.0
    state = np.full(len(values), "UNKNOWN", dtype=object)
    finite = np.isfinite(bps)
    state[finite] = "NEUTRAL"
    state[finite & (bps > neutral_bps)] = "POSITIVE"
    state[finite & (bps < -neutral_bps)] = "NEGATIVE"
    return [str(value) for value in state.tolist()]


def basis_evidence_series(
    decision_times: Sequence[object],
    trade_prices: Sequence[float],
    mark_times: Sequence[object],
    mark_prices: Sequence[float],
    index_times: Sequence[object],
    index_prices: Sequence[float],
    *,
    premium_times: Sequence[object] | None = None,
    premium_prices: Sequence[float] | None = None,
    zscore_window_days: float = 7.0,
    zscore_min_samples: int = 5,
) -> dict[str, list[object]]:
    """Return CSL-compatible mark/index/premium basis evidence at each decision.

    Mark/index basis changes and z-scores are calculated on the native mark
    timeline before as-of sampling to strategy decisions. Premium z-scores are
    likewise source-native. This prevents strategy-timeframe aliasing.
    """
    decisions = pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True))
    trade = pd.to_numeric(pd.Series(list(trade_prices)), errors="coerce").to_numpy(float)
    if len(decisions) != len(trade):
        raise ValueError("basis decision timestamps and trade prices must align")
    if len(decisions) and not decisions.is_monotonic_increasing:
        raise ValueError("basis decision timestamps must be chronological")

    window = float(zscore_window_days)
    if not math.isfinite(window) or window <= 0:
        raise ValueError("basis z-score window days must be positive and finite")
    if (
        isinstance(zscore_min_samples, bool)
        or not isinstance(zscore_min_samples, int)
        or zscore_min_samples <= 0
    ):
        raise ValueError("basis z-score minimum samples must be a positive integer")

    mark_index, mark = _canonical_series(mark_times, mark_prices, name="mark")
    index_index, index = _canonical_series(index_times, index_prices, name="index")
    if not len(mark_index) or not len(index_index):
        raise ValueError("basis evidence requires non-empty mark and index price sources")

    index_on_mark = _asof_numeric(mark_index, index_index, index)
    index_on_mark_i = _asof_indices(mark_index, index_index)
    index_time_on_mark: list[object] = [pd.NaT] * len(mark_index)
    for position, source_index in enumerate(index_on_mark_i):
        if source_index >= 0:
            index_time_on_mark[position] = index_index[int(source_index)]

    native_basis = _relative(mark, index_on_mark)
    native_basis_bps = native_basis * 10000.0
    native_basis_change = np.full(len(native_basis), np.nan, dtype=float)
    if len(native_basis) > 1:
        native_basis_change[1:] = native_basis[1:] - native_basis[:-1]
    native_basis_zscore = np.asarray(
        rolling_time_zscore(
            native_basis,
            mark_index,
            days=window,
            minimum=zscore_min_samples,
        ),
        dtype=float,
    )

    mark_on_decision_i = _asof_indices(decisions, mark_index)
    aligned_mark = np.full(len(decisions), np.nan, dtype=float)
    aligned_index = np.full(len(decisions), np.nan, dtype=float)
    aligned_basis = np.full(len(decisions), np.nan, dtype=float)
    aligned_basis_bps = np.full(len(decisions), np.nan, dtype=float)
    aligned_basis_change = np.full(len(decisions), np.nan, dtype=float)
    aligned_basis_zscore = np.full(len(decisions), np.nan, dtype=float)
    mark_source_times: list[object] = [pd.NaT] * len(decisions)
    index_source_times: list[object] = [pd.NaT] * len(decisions)
    for position, source_index in enumerate(mark_on_decision_i):
        if source_index < 0:
            continue
        source_index = int(source_index)
        aligned_mark[position] = mark[source_index]
        aligned_index[position] = index_on_mark[source_index]
        aligned_basis[position] = native_basis[source_index]
        aligned_basis_bps[position] = native_basis_bps[source_index]
        aligned_basis_change[position] = native_basis_change[source_index]
        aligned_basis_zscore[position] = native_basis_zscore[source_index]
        mark_source_times[position] = mark_index[source_index]
        index_source_times[position] = index_time_on_mark[source_index]

    premium_close = np.full(len(decisions), np.nan, dtype=float)
    premium_change = np.full(len(decisions), np.nan, dtype=float)
    premium_zscore = np.full(len(decisions), np.nan, dtype=float)
    premium_source_times: list[object] = [pd.NaT] * len(decisions)
    if premium_times is not None or premium_prices is not None:
        if premium_times is None or premium_prices is None:
            raise ValueError("premium timestamps and prices must be supplied together")
        premium_index, premium = _canonical_series(
            premium_times,
            premium_prices,
            name="premium",
        )
        if len(premium_index):
            native_premium_change = np.full(len(premium), np.nan, dtype=float)
            if len(premium) > 1:
                native_premium_change[1:] = premium[1:] - premium[:-1]
            native_premium_zscore = np.asarray(
                rolling_time_zscore(
                    premium,
                    premium_index,
                    days=window,
                    minimum=zscore_min_samples,
                ),
                dtype=float,
            )
            premium_close = _asof_numeric(decisions, premium_index, premium)
            premium_change = _asof_numeric(
                decisions, premium_index, native_premium_change
            )
            premium_zscore = _asof_numeric(
                decisions, premium_index, native_premium_zscore
            )
            premium_source_times = _asof_times(decisions, premium_index)

    trade_mark_basis = _relative(trade, aligned_mark)
    trade_index_basis = _relative(trade, aligned_index)

    return {
        "mark_source_available_at": mark_source_times,
        "mark_price": aligned_mark.tolist(),
        "index_source_available_at": index_source_times,
        "index_price": aligned_index.tolist(),
        "premium_source_available_at": premium_source_times,
        "premium_index_close": premium_close.tolist(),
        "mark_index_basis": aligned_basis.tolist(),
        "mark_index_basis_bps": aligned_basis_bps.tolist(),
        "mark_index_basis_state": _basis_state(aligned_basis),
        "trade_mark_basis": trade_mark_basis.tolist(),
        "trade_mark_basis_bps": (trade_mark_basis * 10000.0).tolist(),
        "trade_index_basis": trade_index_basis.tolist(),
        "trade_index_basis_bps": (trade_index_basis * 10000.0).tolist(),
        "mark_index_basis_change": aligned_basis_change.tolist(),
        "mark_index_basis_zscore_7d": aligned_basis_zscore.tolist(),
        "premium_index_change": premium_change.tolist(),
        "premium_index_zscore_7d": premium_zscore.tolist(),
    }
