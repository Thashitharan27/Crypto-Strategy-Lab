"""Causal taker-flow evidence shared by research and live runtimes."""
from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np
import pandas as pd


TAKER_FLOW_FIELDS = (
    "taker_buy_volume",
    "taker_sell_volume",
    "taker_buy_sell_ratio",
    "taker_delta",
    "taker_delta_pct",
    "taker_delta_15m",
    "taker_delta_pct_15m",
    "taker_delta_1h",
    "taker_delta_pct_1h",
    "flow_acceleration",
    "flow_persistence",
)


def taker_flow_evidence_series(
    decision_times: Sequence[object],
    source_times: Sequence[object],
    volumes: Sequence[float],
    taker_buy_base_volumes: Sequence[float],
    *,
    volume_tolerance: float = 1e-9,
) -> dict[str, list[object]]:
    """Return CSL-compatible completed-kline taker-flow evidence.

    Rolling 15-minute and 1-hour evidence is calculated on the native auxiliary
    kline timeline using elapsed right-inclusive windows. Strategy decisions
    receive the latest completed source row at or before decision time.
    """
    if len(source_times) != len(volumes) or len(source_times) != len(
        taker_buy_base_volumes
    ):
        raise ValueError("taker-flow source timestamps and volume fields must align")
    tolerance_value = float(volume_tolerance)
    if not math.isfinite(tolerance_value) or tolerance_value < 0:
        raise ValueError("taker-flow volume tolerance must be finite and non-negative")

    decisions = pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True))
    if len(decisions) and not decisions.is_monotonic_increasing:
        raise ValueError("taker-flow decision timestamps must be chronological")

    source = pd.DataFrame(
        {
            "available_at": pd.to_datetime(list(source_times), utc=True),
            "volume": pd.to_numeric(pd.Series(list(volumes)), errors="coerce"),
            "taker_buy_base_volume": pd.to_numeric(
                pd.Series(list(taker_buy_base_volumes)), errors="coerce"
            ),
        }
    )
    source = (
        source.sort_values("available_at", kind="stable")
        .drop_duplicates("available_at", keep="last")
        .reset_index(drop=True)
    )

    total = source["volume"].to_numpy(float)
    buy = source["taker_buy_base_volume"].to_numpy(float)
    finite = np.isfinite(total) & np.isfinite(buy)
    if np.any(finite & ((total < 0) | (buy < 0))):
        raise ValueError("Taker-flow volume fields cannot be negative")
    tolerance = tolerance_value * np.maximum(1.0, np.abs(total))
    excess = buy - total
    if np.any(finite & (excess > tolerance)):
        raise ValueError("taker_buy_base_volume exceeds volume beyond tolerance")

    sell = total - buy
    tiny_negative = finite & (sell < 0) & (np.abs(sell) <= tolerance)
    sell[tiny_negative] = 0.0
    delta = buy - sell

    source["taker_buy_volume"] = buy
    source["taker_sell_volume"] = sell
    source["taker_buy_sell_ratio"] = np.divide(
        buy,
        sell,
        out=np.full(len(source), np.nan),
        where=np.isfinite(buy) & np.isfinite(sell) & (sell > 0),
    )
    source["taker_delta"] = delta
    source["taker_delta_pct"] = np.divide(
        delta,
        total,
        out=np.full(len(source), np.nan),
        where=np.isfinite(delta) & np.isfinite(total) & (total != 0),
    )

    indexed = pd.DataFrame(
        {"delta": delta, "volume": total},
        index=pd.DatetimeIndex(source["available_at"]),
    )
    for label, window in (("15m", "15min"), ("1h", "1h")):
        rolling = indexed.rolling(window, closed="right", min_periods=1).sum()
        rolling_delta = rolling["delta"].to_numpy(float)
        rolling_volume = rolling["volume"].to_numpy(float)
        source[f"taker_delta_{label}"] = rolling_delta
        source[f"taker_delta_pct_{label}"] = np.divide(
            rolling_delta,
            rolling_volume,
            out=np.full(len(source), np.nan),
            where=rolling_volume != 0,
        )

    source["flow_acceleration"] = (
        source["taker_delta_15m"] - source["taker_delta_15m"].shift(1)
    )

    signs = np.sign(delta)
    sign_frame = pd.DataFrame(
        {
            "positive": (signs > 0).astype(float),
            "negative": (signs < 0).astype(float),
            "count": np.ones(len(source), dtype=float),
        },
        index=pd.DatetimeIndex(source["available_at"]),
    )
    sign_counts = sign_frame.rolling("1h", closed="right", min_periods=1).sum()
    aggregate_sign = np.sign(source["taker_delta_1h"].to_numpy(float))
    count = sign_counts["count"].to_numpy(float)
    persistence = np.full(len(source), np.nan)
    valid = (count >= 2) & (aggregate_sign != 0)
    positive = valid & (aggregate_sign > 0)
    negative = valid & (aggregate_sign < 0)
    persistence[positive] = (
        sign_counts["positive"].to_numpy(float)[positive] / count[positive]
    )
    persistence[negative] = (
        sign_counts["negative"].to_numpy(float)[negative] / count[negative]
    )
    source["flow_persistence"] = persistence

    if source.empty:
        output: dict[str, list[object]] = {
            "taker_source_available_at": [pd.NaT] * len(decisions)
        }
        for field in TAKER_FLOW_FIELDS:
            output[field] = [float("nan")] * len(decisions)
        return output

    source_index = pd.DatetimeIndex(source["available_at"])
    source_ns = source_index.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    decision_ns = decisions.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    indices = np.searchsorted(source_ns, decision_ns, side="right") - 1

    output = {"taker_source_available_at": []}
    for field in TAKER_FLOW_FIELDS:
        output[field] = []
    for source_position in indices:
        if source_position < 0:
            output["taker_source_available_at"].append(pd.NaT)
            for field in TAKER_FLOW_FIELDS:
                output[field].append(float("nan"))
            continue
        position = int(source_position)
        output["taker_source_available_at"].append(source_index[position])
        for field in TAKER_FLOW_FIELDS:
            output[field].append(source.iloc[position][field])
    return output
