"""Causal futures-positioning evidence shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np
import pandas as pd

from .timeseries import rolling_time_zscore


def _canonical_series(
    timestamps: Sequence[object],
    values: Sequence[float],
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    if len(timestamps) != len(values):
        raise ValueError("positioning timestamps and values must have equal lengths")
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


def _elapsed_change(
    times: pd.DatetimeIndex,
    values: np.ndarray,
    horizon: pd.Timedelta,
) -> tuple[np.ndarray, np.ndarray]:
    times_ns = times.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    prior_i = np.searchsorted(
        times_ns,
        times_ns - int(horizon.value),
        side="right",
    ) - 1
    prior = np.full(len(values), np.nan, dtype=float)
    valid = prior_i >= 0
    prior[valid] = values[prior_i[valid]]
    finite = np.isfinite(values) & np.isfinite(prior)
    change = np.full(len(values), np.nan, dtype=float)
    change[finite] = values[finite] - prior[finite]
    pct = np.divide(
        change,
        prior,
        out=np.full(len(values), np.nan, dtype=float),
        where=finite & (prior != 0),
    )
    return change, pct


def _asof(
    decision_times: pd.DatetimeIndex,
    source_times: pd.DatetimeIndex,
    values: np.ndarray,
) -> np.ndarray:
    out = np.full(len(decision_times), np.nan, dtype=float)
    if not len(source_times):
        return out
    source_ns = source_times.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    decision_ns = decision_times.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    index = np.searchsorted(source_ns, decision_ns, side="right") - 1
    valid = index >= 0
    out[valid] = values[index[valid]]
    return out


def _state(price: np.ndarray, oi: np.ndarray) -> list[str]:
    out = np.full(len(price), "UNKNOWN", dtype=object)
    finite = np.isfinite(price) & np.isfinite(oi)
    out[finite] = "FLAT_OR_MIXED"
    out[finite & (price > 0) & (oi > 0)] = "PRICE_UP_OI_UP"
    out[finite & (price > 0) & (oi < 0)] = "PRICE_UP_OI_DOWN"
    out[finite & (price < 0) & (oi > 0)] = "PRICE_DOWN_OI_UP"
    out[finite & (price < 0) & (oi < 0)] = "PRICE_DOWN_OI_DOWN"
    return [str(value) for value in out.tolist()]


def _pct_change(values: np.ndarray, periods: int = 1) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype=float)
    if periods <= 0:
        raise ValueError("pct-change periods must be positive")
    if periods >= len(values):
        return out
    previous = values[:-periods]
    current = values[periods:]
    finite = np.isfinite(previous) & np.isfinite(current)
    result = np.divide(
        current - previous,
        previous,
        out=np.full(len(current), np.nan, dtype=float),
        where=finite & (previous != 0),
    )
    out[periods:] = result
    return out


def positioning_evidence_series(
    decision_times: Sequence[object],
    strategy_closes: Sequence[float],
    metric_times: Sequence[object],
    open_interest: Sequence[float],
    *,
    price_times_1h: Sequence[object] | None = None,
    price_closes_1h: Sequence[float] | None = None,
    oi_zscore_window_days: float = 7.0,
    oi_zscore_min_samples: int = 20,
) -> dict[str, list[object]]:
    """Return CSL-compatible OI/price positioning evidence for strategy decisions.

    Metric and optional 1h price timelines are sorted and duplicate timestamps use
    the final source-native observation. Strategy decisions must remain
    chronological because PRICE_OI_STATE is explicitly a strategy-bar change.
    """
    decisions = pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True))
    closes = pd.to_numeric(pd.Series(list(strategy_closes)), errors="coerce").to_numpy(float)
    if len(decisions) != len(closes):
        raise ValueError("decision timestamps and strategy closes must align")
    if len(decisions) and not decisions.is_monotonic_increasing:
        raise ValueError("strategy decision timestamps must be chronological")

    window_days = float(oi_zscore_window_days)
    if not math.isfinite(window_days) or window_days <= 0:
        raise ValueError("OI z-score window days must be positive and finite")
    if (
        isinstance(oi_zscore_min_samples, bool)
        or not isinstance(oi_zscore_min_samples, int)
        or oi_zscore_min_samples <= 0
    ):
        raise ValueError("OI z-score minimum samples must be a positive integer")

    metric_index, oi = _canonical_series(metric_times, open_interest)
    oi_change_5m, oi_pct_5m = _elapsed_change(
        metric_index, oi, pd.Timedelta(minutes=5)
    )
    oi_change_1h, oi_pct_1h = _elapsed_change(
        metric_index, oi, pd.Timedelta(hours=1)
    )
    oi_change_24h, oi_pct_24h = _elapsed_change(
        metric_index, oi, pd.Timedelta(hours=24)
    )
    oi_zscore = np.asarray(
        rolling_time_zscore(
            oi,
            metric_index,
            days=window_days,
            minimum=oi_zscore_min_samples,
        ),
        dtype=float,
    )

    aligned_oi = _asof(decisions, metric_index, oi)
    aligned_oi_change_5m = _asof(decisions, metric_index, oi_change_5m)
    aligned_oi_5m = _asof(decisions, metric_index, oi_pct_5m)
    aligned_oi_change_1h = _asof(decisions, metric_index, oi_change_1h)
    aligned_oi_1h = _asof(decisions, metric_index, oi_pct_1h)
    aligned_oi_change_24h = _asof(decisions, metric_index, oi_change_24h)
    aligned_oi_24h = _asof(decisions, metric_index, oi_pct_24h)
    aligned_oi_z = _asof(decisions, metric_index, oi_zscore)

    price_change_1h = np.full(len(decisions), np.nan, dtype=float)
    if price_times_1h is not None or price_closes_1h is not None:
        if price_times_1h is None or price_closes_1h is None:
            raise ValueError("1h price timestamps and closes must be supplied together")
        price_index, price_close = _canonical_series(price_times_1h, price_closes_1h)
        _, price_pct_1h = _elapsed_change(
            price_index,
            price_close,
            pd.Timedelta(hours=1),
        )
        price_change_1h = _asof(decisions, price_index, price_pct_1h)

    strategy_oi_change = _pct_change(aligned_oi, 1)
    strategy_price_return = _pct_change(closes, 1)

    return {
        "open_interest": aligned_oi.tolist(),
        "oi_change_5m": aligned_oi_change_5m.tolist(),
        "oi_change_pct_5m": aligned_oi_5m.tolist(),
        "oi_change_1h": aligned_oi_change_1h.tolist(),
        "oi_change_pct_1h": aligned_oi_1h.tolist(),
        "oi_change_24h": aligned_oi_change_24h.tolist(),
        "oi_change_pct_24h": aligned_oi_24h.tolist(),
        "oi_zscore_7d": aligned_oi_z.tolist(),
        "price_change_pct_1h": price_change_1h.tolist(),
        "oi_vs_price_state_1h": _state(price_change_1h, aligned_oi_1h),
        "open_interest_change_1bar_pct": strategy_oi_change.tolist(),
        "price_return_1bar": strategy_price_return.tolist(),
        "price_oi_state": _state(strategy_price_return, strategy_oi_change),
    }



def ratio_bias_evidence_series(
    decision_times: Sequence[object],
    source_times: Sequence[object],
    ratios: Sequence[float],
) -> dict[str, list[float]]:
    """As-of align a source-native long/short ratio and expose CSL bias=ratio-1."""
    decisions = pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True))
    if len(decisions) and not decisions.is_monotonic_increasing:
        raise ValueError("ratio decision timestamps must be chronological")
    source_index, values = _canonical_series(source_times, ratios)
    aligned = _asof(decisions, source_index, values)
    bias = np.where(np.isfinite(aligned), aligned - 1.0, np.nan)
    return {
        "ratio": aligned.tolist(),
        "bias": bias.tolist(),
    }
