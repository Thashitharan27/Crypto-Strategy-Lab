"""Compact taker flow derived from completed Binance kline aggregates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from crypto_strategy_core.taker_flow import taker_flow_evidence_series
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from .base import FeatureDataResource, FeatureDefinition, ParameterDefinition

TAKER_FLOW_CONTEXT_FEATURE_NAME = "taker_flow_context"
TAKER_FLOW_CONTEXT_FEATURE_VERSION = "3"


def taker_flow_resource(interval: str = "5m") -> FeatureDataResource:
    return FeatureDataResource(DatasetKind.KLINES, interval, "taker_flow")


@dataclass(frozen=True, slots=True)
class TakerFlowContextFeatureProvider:
    definition: FeatureDefinition = FeatureDefinition(
        name=TAKER_FLOW_CONTEXT_FEATURE_NAME,
        version=TAKER_FLOW_CONTEXT_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES,),
        parameters={
            "taker_flow_interval": ParameterDefinition(str, "5m"),
            "volume_tolerance": ParameterDefinition(float, 1e-9),
        },
        output_columns=(
            "taker_source_available_at",
            "taker_age_seconds",
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
        ),
        availability_rule="completed_auxiliary_kline_available_at_or_before_strategy_decision",
    )

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[object, pd.DataFrame],
        parameters: Mapping[str, object],
        feature_frames=None,
    ) -> pd.DataFrame:
        del feature_frames
        params = self.definition.normalize_parameters(parameters)
        interval = str(params["taker_flow_interval"])
        strategy = datasets[DatasetKind.KLINES].copy()
        resource = taker_flow_resource(interval)
        source = datasets.get(resource)
        if source is None:
            raise ValueError(f"taker_flow_context requires auxiliary {resource!r}")
        source = source.copy()

        required_strategy = {"period_start", "available_at"}
        missing_strategy = sorted(required_strategy - set(strategy.columns))
        if missing_strategy:
            raise ValueError(f"Strategy klines missing {missing_strategy}")
        required_source = {"available_at", "volume", "taker_buy_base_volume"}
        missing_source = sorted(required_source - set(source.columns))
        if missing_source:
            raise ValueError(f"Taker-flow klines missing {missing_source}")

        strategy = (
            strategy.sort_values("period_start", kind="stable")
            .drop_duplicates("period_start", keep="last")
            .reset_index(drop=True)
        )
        decisions = pd.to_datetime(strategy["available_at"], utc=True)
        shared = taker_flow_evidence_series(
            decisions.tolist(),
            pd.to_datetime(source["available_at"], utc=True).tolist(),
            pd.to_numeric(source["volume"], errors="coerce").tolist(),
            pd.to_numeric(
                source["taker_buy_base_volume"], errors="coerce"
            ).tolist(),
            volume_tolerance=float(params["volume_tolerance"]),
        )

        out = pd.DataFrame(shared)
        out.insert(0, "available_at", decisions)
        out.insert(
            0,
            "timestamp",
            pd.to_datetime(strategy["period_start"], utc=True),
        )
        out["taker_source_available_at"] = pd.to_datetime(
            out["taker_source_available_at"], utc=True, errors="coerce"
        )
        out["taker_age_seconds"] = (
            out["available_at"] - out["taker_source_available_at"]
        ).dt.total_seconds()
        for column in self.definition.output_columns:
            if column in {"taker_source_available_at", "taker_age_seconds"}:
                continue
            out[column] = pd.to_numeric(out[column], errors="coerce")

        source_available = out["taker_source_available_at"]
        if bool(
            (
                source_available.notna()
                & (source_available > out["available_at"])
            ).any()
        ):
            raise AssertionError("Taker flow attached a future auxiliary kline")

        out.attrs.update(
            feature_name=self.definition.name,
            feature_version=self.definition.version,
            effective_warmup_bars=0,
            request_cache_key=request.cache_key(),
            source_interval=interval,
        )
        return out
