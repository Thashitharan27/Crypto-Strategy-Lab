"""Causal Binance funding context aligned to strategy candle decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.alignment import causal_asof_join
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition


FUNDING_CONTEXT_FEATURE_NAME = "funding_context"
FUNDING_CONTEXT_FEATURE_VERSION = "1"


def _funding_bias(rate: np.ndarray) -> np.ndarray:
    state = np.full(len(rate), "UNKNOWN", dtype=object)
    finite = np.isfinite(rate)
    state[finite] = "NEUTRAL"
    state[finite & (rate > 0)] = "POSITIVE"
    state[finite & (rate < 0)] = "NEGATIVE"
    return state


def _trailing_window_sums(
    decision_times: pd.Series,
    event_times: pd.Series,
    rates: np.ndarray,
    window: pd.Timedelta,
) -> tuple[np.ndarray, np.ndarray]:
    decisions_ns = pd.DatetimeIndex(pd.to_datetime(decision_times, utc=True)).asi8
    events_ns = pd.DatetimeIndex(pd.to_datetime(event_times, utc=True)).asi8
    finite = np.isfinite(rates)
    safe_rates = np.where(finite, rates, 0.0)
    prefix_sum = np.concatenate(([0.0], np.cumsum(safe_rates)))
    prefix_count = np.concatenate(([0], np.cumsum(finite.astype(int))))
    window_ns = int(window.value)

    right = np.searchsorted(events_ns, decisions_ns, side="right")
    left = np.searchsorted(events_ns, decisions_ns - window_ns, side="left")
    sums = prefix_sum[right] - prefix_sum[left]
    counts = prefix_count[right] - prefix_count[left]
    return sums.astype(float), counts.astype(int)


@dataclass(frozen=True, slots=True)
class FundingContextFeatureProvider:
    """Attach only funding settlements already published by each candle close."""

    definition: FeatureDefinition = FeatureDefinition(
        name=FUNDING_CONTEXT_FEATURE_NAME,
        version=FUNDING_CONTEXT_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES, DatasetKind.FUNDING_RATE),
        output_columns=(
            "funding_source_available_at",
            "funding_age_hours",
            "funding_rate",
            "funding_rate_bps",
            "funding_interval_hours",
            "funding_bias",
            "funding_event_changed",
            "funding_24h_sum",
            "funding_24h_sum_bps",
            "funding_24h_count",
        ),
        warmup_bars=0,
        availability_rule="funding_events_available_at_or_before_strategy_candle_close",
    )

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[DatasetKind, pd.DataFrame],
        parameters: Mapping[str, object],
        feature_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        del parameters, feature_frames
        try:
            klines = datasets[DatasetKind.KLINES].copy()
            funding = datasets[DatasetKind.FUNDING_RATE].copy()
        except KeyError as exc:
            raise ValueError("funding_context requires klines and funding_rate") from exc

        required_kline = {"period_start", "available_at"}
        missing_kline = sorted(required_kline - set(klines.columns))
        if missing_kline:
            raise ValueError(f"Canonical kline frame is missing columns: {missing_kline}")
        if "available_at" not in funding.columns or "funding_rate" not in funding.columns:
            raise ValueError("Canonical funding frame requires available_at and funding_rate")
        if klines.empty:
            raise ValueError("Cannot align funding context to an empty kline frame")

        klines = klines.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        decisions = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(klines["period_start"], utc=True),
                "decision_time": pd.to_datetime(klines["available_at"], utc=True),
            }
        )

        funding_columns = ["available_at", "funding_rate"]
        if "funding_interval_hours" in funding.columns:
            funding_columns.append("funding_interval_hours")
        right = funding[funding_columns].copy()
        right["available_at"] = pd.to_datetime(right["available_at"], utc=True)
        right["funding_rate"] = pd.to_numeric(right["funding_rate"], errors="coerce")
        if "funding_interval_hours" in right.columns:
            right["funding_interval_hours"] = pd.to_numeric(
                right["funding_interval_hours"], errors="coerce"
            )
        right = right.sort_values("available_at", kind="stable").drop_duplicates(
            "available_at", keep="last"
        ).reset_index(drop=True)

        joined = causal_asof_join(decisions, right)
        output = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(joined["timestamp"], utc=True),
                "available_at": pd.to_datetime(joined["decision_time"], utc=True),
                "funding_source_available_at": pd.to_datetime(joined["available_at"], utc=True),
                "funding_rate": pd.to_numeric(joined["funding_rate"], errors="coerce"),
            }
        )
        output["funding_age_hours"] = (
            output["available_at"] - output["funding_source_available_at"]
        ).dt.total_seconds() / 3600.0
        output["funding_rate_bps"] = output["funding_rate"] * 10000.0
        output["funding_interval_hours"] = (
            pd.to_numeric(joined["funding_interval_hours"], errors="coerce")
            if "funding_interval_hours" in joined.columns
            else np.nan
        )
        output["funding_bias"] = _funding_bias(output["funding_rate"].to_numpy(float))

        current_source = output["funding_source_available_at"]
        previous_source = current_source.shift(1)
        output["funding_event_changed"] = current_source.notna() & current_source.ne(previous_source)

        event_rates = right["funding_rate"].to_numpy(float)
        trailing_sum, trailing_count = _trailing_window_sums(
            output["available_at"],
            right["available_at"],
            event_rates,
            pd.Timedelta(hours=24),
        )
        output["funding_24h_sum"] = trailing_sum
        output["funding_24h_sum_bps"] = trailing_sum * 10000.0
        output["funding_24h_count"] = trailing_count

        source_available = output["funding_source_available_at"]
        leak = source_available.notna() & (source_available > output["available_at"])
        if bool(leak.any()):
            raise AssertionError("Funding context attached a future funding event")

        output.attrs.update(
            {
                "feature_name": self.definition.name,
                "feature_version": self.definition.version,
                "effective_warmup_bars": self.definition.warmup_bars,
                "trailing_window_hours": 24,
                "request_cache_key": request.cache_key(),
            }
        )
        return output
