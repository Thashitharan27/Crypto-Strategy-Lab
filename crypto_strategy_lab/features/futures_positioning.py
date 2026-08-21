"""Causal Binance futures positioning context aligned to strategy candles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.alignment import causal_asof_join
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.indicators import lag

from .base import FeatureDefinition


FUTURES_POSITIONING_FEATURE_NAME = "futures_positioning"
FUTURES_POSITIONING_FEATURE_VERSION = "1"

_METRIC_COLUMNS = (
    "open_interest",
    "open_interest_value",
    "top_trader_account_long_short_ratio",
    "top_trader_position_long_short_ratio",
    "global_long_short_account_ratio",
    "taker_long_short_volume_ratio",
)


def _numeric_or_nan(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame.columns:
        return np.full(len(frame), np.nan, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(float)


def _pct_change(values: np.ndarray, bars: int) -> np.ndarray:
    previous = lag(values, bars)
    return np.divide(
        values - previous,
        previous,
        out=np.full(len(values), np.nan, dtype=float),
        where=np.isfinite(values) & np.isfinite(previous) & (previous != 0),
    )


def _ratio_bias(values: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(values), values - 1.0, np.nan)


def _price_oi_state(price_return: np.ndarray, oi_change: np.ndarray) -> np.ndarray:
    state = np.full(len(price_return), "UNKNOWN", dtype=object)
    finite = np.isfinite(price_return) & np.isfinite(oi_change)
    state[finite] = "FLAT_OR_MIXED"
    state[finite & (price_return > 0) & (oi_change > 0)] = "PRICE_UP_OI_UP"
    state[finite & (price_return < 0) & (oi_change > 0)] = "PRICE_DOWN_OI_UP"
    state[finite & (price_return > 0) & (oi_change < 0)] = "PRICE_UP_OI_DOWN"
    state[finite & (price_return < 0) & (oi_change < 0)] = "PRICE_DOWN_OI_DOWN"
    return state


@dataclass(frozen=True, slots=True)
class FuturesPositioningFeatureProvider:
    """Align OI/positioning/taker snapshots without using future metrics rows."""

    definition: FeatureDefinition = FeatureDefinition(
        name=FUTURES_POSITIONING_FEATURE_NAME,
        version=FUTURES_POSITIONING_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES, DatasetKind.FUTURES_METRICS),
        output_columns=(
            "metrics_source_available_at",
            "metrics_age_seconds",
            "open_interest",
            "open_interest_value",
            "open_interest_change_1bar_pct",
            "open_interest_change_3bar_pct",
            "open_interest_value_change_1bar_pct",
            "price_return_1bar",
            "price_oi_state",
            "top_trader_account_long_short_ratio",
            "top_trader_account_bias",
            "top_trader_position_long_short_ratio",
            "top_trader_position_bias",
            "global_long_short_account_ratio",
            "global_long_short_account_bias",
            "taker_long_short_volume_ratio",
            "taker_long_short_volume_bias",
        ),
        warmup_bars=3,
        availability_rule="latest_metrics_available_at_or_before_strategy_candle_close",
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
            metrics = datasets[DatasetKind.FUTURES_METRICS].copy()
        except KeyError as exc:
            raise ValueError("futures_positioning requires klines and futures_metrics") from exc

        required_kline = {"period_start", "available_at", "close"}
        missing_kline = sorted(required_kline - set(klines.columns))
        if missing_kline:
            raise ValueError(f"Canonical kline frame is missing columns: {missing_kline}")
        if "available_at" not in metrics.columns:
            raise ValueError("Canonical futures metrics frame is missing available_at")
        if klines.empty:
            raise ValueError("Cannot align futures positioning to an empty kline frame")

        klines = klines.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        decisions = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(klines["period_start"], utc=True),
                "decision_time": pd.to_datetime(klines["available_at"], utc=True),
                "close": pd.to_numeric(klines["close"], errors="raise"),
            }
        )

        metric_columns = [column for column in _METRIC_COLUMNS if column in metrics.columns]
        right = metrics[["available_at", *metric_columns]].copy()
        right["available_at"] = pd.to_datetime(right["available_at"], utc=True)
        right = right.sort_values("available_at", kind="stable").drop_duplicates(
            "available_at", keep="last"
        )
        joined = causal_asof_join(decisions, right)

        output = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(joined["timestamp"], utc=True),
                # The aligned feature row is consumed at the strategy decision.
                "available_at": pd.to_datetime(joined["decision_time"], utc=True),
                "metrics_source_available_at": pd.to_datetime(joined["available_at"], utc=True),
            }
        )
        output["metrics_age_seconds"] = (
            output["available_at"] - output["metrics_source_available_at"]
        ).dt.total_seconds()

        for column in _METRIC_COLUMNS:
            output[column] = _numeric_or_nan(joined, column)

        oi = output["open_interest"].to_numpy(float)
        oi_value = output["open_interest_value"].to_numpy(float)
        close = pd.to_numeric(joined["close"], errors="raise").to_numpy(float)
        output["open_interest_change_1bar_pct"] = _pct_change(oi, 1)
        output["open_interest_change_3bar_pct"] = _pct_change(oi, 3)
        output["open_interest_value_change_1bar_pct"] = _pct_change(oi_value, 1)
        output["price_return_1bar"] = _pct_change(close, 1)
        output["price_oi_state"] = _price_oi_state(
            output["price_return_1bar"].to_numpy(float),
            output["open_interest_change_1bar_pct"].to_numpy(float),
        )

        for ratio, bias in (
            ("top_trader_account_long_short_ratio", "top_trader_account_bias"),
            ("top_trader_position_long_short_ratio", "top_trader_position_bias"),
            ("global_long_short_account_ratio", "global_long_short_account_bias"),
            ("taker_long_short_volume_ratio", "taker_long_short_volume_bias"),
        ):
            output[bias] = _ratio_bias(output[ratio].to_numpy(float))

        source_available = output["metrics_source_available_at"]
        leak = source_available.notna() & (source_available > output["available_at"])
        if bool(leak.any()):
            raise AssertionError("Futures positioning feature attached a future metrics snapshot")

        output.attrs.update(
            {
                "feature_name": self.definition.name,
                "feature_version": self.definition.version,
                "effective_warmup_bars": self.definition.warmup_bars,
                "request_cache_key": request.cache_key(),
            }
        )
        return output
