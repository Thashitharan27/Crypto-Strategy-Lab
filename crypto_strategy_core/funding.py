"""Causal funding-rule evidence shared by research and live runtimes."""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import timedelta
import math

import pandas as pd

from .timeseries import rolling_time_zscore


def _utc(value: object) -> pd.Timestamp:
    """Normalize to UTC without discarding nanosecond precision."""
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def funding_bias(rate: float) -> str:
    value = float(rate)
    if not math.isfinite(value):
        return "UNKNOWN"
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "NEUTRAL"


def funding_rule_evidence_series(
    decision_times: Sequence[object],
    event_times: Sequence[object],
    rates: Sequence[float],
    *,
    zscore_window_days: float = 7.0,
    zscore_min_samples: int = 6,
    extreme_zscore: float = 2.0,
) -> dict[str, list[object]]:
    """Return CSL funding rule evidence available at each decision time.

    Event timestamps are deduplicated last-write-wins, then sorted. Each decision
    uses only events published at or before that timestamp. The 24-hour window is
    (T-24h, T], matching CSL's existing feature provider.
    """
    if len(event_times) != len(rates):
        raise ValueError("funding event timestamps and rates must have equal lengths")
    if (
        isinstance(zscore_min_samples, bool)
        or not isinstance(zscore_min_samples, int)
        or zscore_min_samples <= 0
    ):
        raise ValueError("funding z-score minimum samples must be a positive integer")
    window_days = float(zscore_window_days)
    threshold = float(extreme_zscore)
    if not math.isfinite(window_days) or window_days <= 0:
        raise ValueError("funding z-score window days must be positive and finite")
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("funding extreme z-score must be finite and non-negative")

    unique: dict[pd.Timestamp, float] = {}
    for timestamp, rate in zip(event_times, rates):
        unique[_utc(timestamp)] = float(rate)
    ordered = sorted(unique.items(), key=lambda item: item[0])
    times = [timestamp for timestamp, _ in ordered]
    values = [rate for _, rate in ordered]

    series = pd.Series(values, dtype="float64")
    previous = series.shift(1).to_numpy(float).tolist()
    change = (series - series.shift(1)).to_numpy(float).tolist()
    mean3 = series.rolling(3, min_periods=3).mean().to_numpy(float).tolist()
    zscore = rolling_time_zscore(
        values,
        times,
        days=window_days,
        minimum=zscore_min_samples,
    )

    finite = [math.isfinite(value) for value in values]
    safe = [value if ok else 0.0 for value, ok in zip(values, finite)]
    prefix_sum = [0.0]
    prefix_count = [0]
    for value, ok in zip(safe, finite):
        prefix_sum.append(prefix_sum[-1] + value)
        prefix_count.append(prefix_count[-1] + int(ok))

    output: dict[str, list[object]] = {
        "funding_source_available_at": [],
        "funding_rate": [],
        "funding_rate_bps": [],
        "funding_bias": [],
        "funding_previous": [],
        "funding_change": [],
        "funding_change_bps": [],
        "funding_3_event_mean": [],
        "funding_3_event_mean_bps": [],
        "funding_7d_zscore": [],
        "funding_extreme_positive": [],
        "funding_extreme_negative": [],
        "funding_24h_sum": [],
        "funding_24h_sum_bps": [],
        "funding_24h_count": [],
    }

    for decision in decision_times:
        decision_time = _utc(decision)
        index = bisect_right(times, decision_time) - 1
        right = index + 1
        left = bisect_right(times, decision_time - timedelta(hours=24))
        trailing_sum = prefix_sum[right] - prefix_sum[left]
        trailing_count = prefix_count[right] - prefix_count[left]

        if index < 0:
            source_time = None
            rate = prev = delta = avg3 = z = float("nan")
        else:
            source_time = times[index]
            rate = values[index]
            prev = previous[index]
            delta = change[index]
            avg3 = mean3[index]
            z = zscore[index]

        output["funding_source_available_at"].append(source_time)
        output["funding_rate"].append(rate)
        output["funding_rate_bps"].append(
            rate * 10000.0 if math.isfinite(rate) else float("nan")
        )
        output["funding_bias"].append(funding_bias(rate))
        output["funding_previous"].append(prev)
        output["funding_change"].append(delta)
        output["funding_change_bps"].append(
            delta * 10000.0 if math.isfinite(delta) else float("nan")
        )
        output["funding_3_event_mean"].append(avg3)
        output["funding_3_event_mean_bps"].append(
            avg3 * 10000.0 if math.isfinite(avg3) else float("nan")
        )
        output["funding_7d_zscore"].append(z)
        output["funding_extreme_positive"].append(
            None if not math.isfinite(z) else z >= threshold
        )
        output["funding_extreme_negative"].append(
            None if not math.isfinite(z) else z <= -threshold
        )
        output["funding_24h_sum"].append(float(trailing_sum))
        output["funding_24h_sum_bps"].append(float(trailing_sum) * 10000.0)
        output["funding_24h_count"].append(int(trailing_count))

    return output


def funding_rule_evidence_at(
    decision_time: object,
    event_times: Sequence[object],
    rates: Sequence[float],
    *,
    zscore_window_days: float = 7.0,
    zscore_min_samples: int = 6,
    extreme_zscore: float = 2.0,
) -> dict[str, object]:
    """Return one decision-time row from the shared funding evidence series."""
    series = funding_rule_evidence_series(
        [decision_time],
        event_times,
        rates,
        zscore_window_days=zscore_window_days,
        zscore_min_samples=zscore_min_samples,
        extreme_zscore=extreme_zscore,
    )
    return {name: values[0] for name, values in series.items()}
