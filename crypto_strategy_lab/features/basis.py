"""Causal futures basis context from Binance mark/index/premium klines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from crypto_strategy_core.basis import basis_evidence_series
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition, ParameterDefinition


BASIS_CONTEXT_FEATURE_NAME = "basis_context"
BASIS_CONTEXT_FEATURE_VERSION = "3"


def _reference_source(frame: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            {
                "available_at": pd.Series(dtype="datetime64[ns, UTC]"),
                f"{prefix}_price": pd.Series(dtype=float),
            }
        )
    required = {"available_at", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Canonical {prefix} kline frame is missing columns: {missing}")
    result = frame[["available_at", "close"]].copy()
    result["available_at"] = pd.to_datetime(result["available_at"], utc=True)
    result[f"{prefix}_price"] = pd.to_numeric(result.pop("close"), errors="raise")
    return (
        result.sort_values("available_at", kind="stable")
        .drop_duplicates("available_at", keep="last")
        .reset_index(drop=True)
    )


@dataclass(frozen=True, slots=True)
class BasisContextFeatureProvider:
    """Attach only reference-price facts available by strategy candle close."""

    definition: FeatureDefinition = FeatureDefinition(
        name=BASIS_CONTEXT_FEATURE_NAME,
        version=BASIS_CONTEXT_FEATURE_VERSION,
        required_datasets=(
            DatasetKind.KLINES,
            DatasetKind.MARK_PRICE_KLINES,
            DatasetKind.INDEX_PRICE_KLINES,
        ),
        optional_datasets=(DatasetKind.PREMIUM_INDEX_KLINES,),
        parameters={
            "basis_zscore_window_days": ParameterDefinition(float, 7.0),
            "basis_zscore_min_samples": ParameterDefinition(int, 5),
        },
        output_columns=(
            "mark_source_available_at",
            "mark_age_seconds",
            "mark_price",
            "index_source_available_at",
            "index_age_seconds",
            "index_price",
            "premium_source_available_at",
            "premium_age_seconds",
            "premium_index_close",
            "mark_index_basis",
            "mark_index_basis_bps",
            "mark_index_basis_state",
            "trade_mark_basis",
            "trade_mark_basis_bps",
            "trade_index_basis",
            "trade_index_basis_bps",
            "mark_index_basis_change",
            "mark_index_basis_zscore_7d",
            "premium_index_change",
            "premium_index_zscore_7d",
        ),
        warmup_bars=0,
        availability_rule="source_native_reference_facts_available_at_or_before_strategy_candle_close",
    )

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[DatasetKind, pd.DataFrame],
        parameters: Mapping[str, object],
        feature_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        del feature_frames
        params = self.definition.normalize_parameters(parameters)
        try:
            klines = datasets[DatasetKind.KLINES].copy()
            mark = datasets[DatasetKind.MARK_PRICE_KLINES].copy()
            index = datasets[DatasetKind.INDEX_PRICE_KLINES].copy()
        except KeyError as exc:
            raise ValueError(
                "basis_context requires klines, mark_price_klines and index_price_klines"
            ) from exc
        premium = datasets.get(DatasetKind.PREMIUM_INDEX_KLINES, pd.DataFrame()).copy()

        required = {"period_start", "available_at", "close"}
        missing = sorted(required - set(klines.columns))
        if missing:
            raise ValueError(f"Canonical kline frame is missing columns: {missing}")
        if klines.empty:
            raise ValueError("Cannot align basis context to an empty kline frame")

        klines = (
            klines.sort_values("period_start", kind="stable")
            .drop_duplicates("period_start", keep="last")
            .reset_index(drop=True)
        )
        strategy_times = pd.to_datetime(klines["period_start"], utc=True)
        decisions = pd.to_datetime(klines["available_at"], utc=True)
        trade_prices = pd.to_numeric(klines["close"], errors="raise").tolist()

        mark_source = _reference_source(mark, prefix="mark")
        index_source = _reference_source(index, prefix="index")
        if mark_source.empty or index_source.empty:
            raise ValueError("basis_context requires non-empty mark and index price sources")
        premium_source = _reference_source(premium, prefix="premium")

        shared = basis_evidence_series(
            decisions.tolist(),
            trade_prices,
            mark_source["available_at"].tolist(),
            mark_source["mark_price"].tolist(),
            index_source["available_at"].tolist(),
            index_source["index_price"].tolist(),
            premium_times=(
                premium_source["available_at"].tolist()
                if not premium_source.empty
                else None
            ),
            premium_prices=(
                premium_source["premium_price"].tolist()
                if not premium_source.empty
                else None
            ),
            zscore_window_days=float(params["basis_zscore_window_days"]),
            zscore_min_samples=int(params["basis_zscore_min_samples"]),
        )

        output = pd.DataFrame(shared)
        output.insert(0, "available_at", decisions)
        output.insert(0, "timestamp", strategy_times)
        for prefix in ("mark", "index", "premium"):
            source_name = f"{prefix}_source_available_at"
            output[source_name] = pd.to_datetime(
                output[source_name], utc=True, errors="coerce"
            )
            output[f"{prefix}_age_seconds"] = (
                output["available_at"] - output[source_name]
            ).dt.total_seconds()
            leak = output[source_name].notna() & (
                output[source_name] > output["available_at"]
            )
            if bool(leak.any()):
                raise AssertionError(f"Basis context attached a future {prefix} candle")

        output.attrs.update(
            {
                "feature_name": self.definition.name,
                "feature_version": self.definition.version,
                "effective_warmup_bars": self.definition.warmup_bars,
                "request_cache_key": request.cache_key(),
            }
        )
        return output
