"""Minimal ATR feature dependency for cache-stable structural research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from crypto_strategy_lab.atr import atr
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition, ParameterDefinition


ATR_CONTEXT_FEATURE_NAME = "atr_context"
ATR_CONTEXT_FEATURE_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ATRContextFeatureProvider:
    """Prepare only ATR from completed strategy klines.

    Structural features such as support/resistance depend on this narrow feature
    instead of the full ADX/DMI block, so unrelated directional-setting changes
    cannot invalidate an otherwise identical structural cache.
    """

    definition: FeatureDefinition = FeatureDefinition(
        name=ATR_CONTEXT_FEATURE_NAME,
        version=ATR_CONTEXT_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES,),
        parameters={
            "atr_period": ParameterDefinition(int, 14),
        },
        output_columns=("atr",),
        warmup_bars=30,
        availability_rule="current_completed_kline_available_at",
    )

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[DatasetKind, pd.DataFrame],
        parameters: Mapping[str, object],
    ) -> pd.DataFrame:
        try:
            source = datasets[DatasetKind.KLINES].copy()
        except KeyError as exc:
            raise ValueError("atr_context requires canonical kline data") from exc

        required = {"period_start", "available_at", "high", "low", "close"}
        missing = sorted(required - set(source.columns))
        if missing:
            raise ValueError(f"Canonical kline frame is missing columns: {missing}")
        if source.empty:
            raise ValueError("Cannot calculate ATR from an empty kline frame")

        atr_period = int(parameters.get("atr_period", 14))
        if atr_period <= 0:
            raise ValueError("ATR period must be positive")

        source = source.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        high = pd.to_numeric(source["high"], errors="raise").to_numpy(float)
        low = pd.to_numeric(source["low"], errors="raise").to_numpy(float)
        close = pd.to_numeric(source["close"], errors="raise").to_numpy(float)

        output = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(source["period_start"], utc=True),
                "available_at": pd.to_datetime(source["available_at"], utc=True),
                "atr": atr(high, low, close, atr_period),
            }
        )
        period_start = pd.to_datetime(source["period_start"], utc=True)
        if bool((output["available_at"] < period_start).any()):
            raise ValueError("ATR feature availability precedes its source candle")

        output.attrs.update(
            {
                "feature_name": self.definition.name,
                "feature_version": self.definition.version,
                "atr_period": atr_period,
                "effective_warmup_bars": atr_period,
                "request_cache_key": request.cache_key(),
            }
        )
        return output
