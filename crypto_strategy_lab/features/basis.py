"""Causal futures basis context from Binance mark/index/premium klines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.alignment import causal_asof_join
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition


BASIS_CONTEXT_FEATURE_NAME = "basis_context"
BASIS_CONTEXT_FEATURE_VERSION = "1"


def _basis_state(values: np.ndarray, neutral_bps: float = 1.0) -> np.ndarray:
    bps = values * 10000.0
    state = np.full(len(values), "UNKNOWN", dtype=object)
    finite = np.isfinite(bps)
    state[finite] = "NEUTRAL"
    state[finite & (bps > neutral_bps)] = "POSITIVE"
    state[finite & (bps < -neutral_bps)] = "NEGATIVE"
    return state


def _align_reference(
    decisions: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    prefix: str,
) -> pd.DataFrame:
    if frame.empty:
        result = decisions[["timestamp", "decision_time"]].copy()
        result[f"{prefix}_source_available_at"] = pd.Series(
            pd.NaT,
            index=result.index,
            dtype="datetime64[ns, UTC]",
        )
        result[f"{prefix}_price"] = np.nan
        return result
    required = {"available_at", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Canonical {prefix} kline frame is missing columns: {missing}")
    right = frame[["available_at", "close"]].copy()
    right["available_at"] = pd.to_datetime(right["available_at"], utc=True)
    right["close"] = pd.to_numeric(right["close"], errors="raise")
    right = right.sort_values("available_at", kind="stable").drop_duplicates(
        "available_at", keep="last"
    )
    joined = causal_asof_join(decisions, right)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(joined["timestamp"], utc=True),
            "decision_time": pd.to_datetime(joined["decision_time"], utc=True),
            f"{prefix}_source_available_at": pd.to_datetime(joined["available_at"], utc=True),
            f"{prefix}_price": pd.to_numeric(joined["close"], errors="coerce"),
        }
    )


def _relative(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.divide(
        left - right,
        right,
        out=np.full(len(left), np.nan, dtype=float),
        where=np.isfinite(left) & np.isfinite(right) & (right != 0),
    )


@dataclass(frozen=True, slots=True)
class BasisContextFeatureProvider:
    """Attach only reference-price candles available by strategy candle close."""

    definition: FeatureDefinition = FeatureDefinition(
        name=BASIS_CONTEXT_FEATURE_NAME,
        version=BASIS_CONTEXT_FEATURE_VERSION,
        required_datasets=(
            DatasetKind.KLINES,
            DatasetKind.MARK_PRICE_KLINES,
            DatasetKind.INDEX_PRICE_KLINES,
        ),
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
        ),
        warmup_bars=0,
        availability_rule="reference_klines_available_at_or_before_strategy_candle_close",
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
            mark = datasets[DatasetKind.MARK_PRICE_KLINES].copy()
            index = datasets[DatasetKind.INDEX_PRICE_KLINES].copy()
        except KeyError as exc:
            raise ValueError("basis_context requires klines, mark_price_klines and index_price_klines") from exc
        premium = datasets.get(DatasetKind.PREMIUM_INDEX_KLINES, pd.DataFrame()).copy()

        required = {"period_start", "available_at", "close"}
        missing = sorted(required - set(klines.columns))
        if missing:
            raise ValueError(f"Canonical kline frame is missing columns: {missing}")
        if klines.empty:
            raise ValueError("Cannot align basis context to an empty kline frame")

        klines = klines.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        decisions = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(klines["period_start"], utc=True),
                "decision_time": pd.to_datetime(klines["available_at"], utc=True),
                "trade_price": pd.to_numeric(klines["close"], errors="raise"),
            }
        )

        mark_aligned = _align_reference(decisions, mark, prefix="mark")
        index_aligned = _align_reference(decisions, index, prefix="index")
        premium_aligned = _align_reference(decisions, premium, prefix="premium")

        output = pd.DataFrame(
            {
                "timestamp": decisions["timestamp"],
                "available_at": decisions["decision_time"],
                "mark_source_available_at": mark_aligned["mark_source_available_at"],
                "mark_price": mark_aligned["mark_price"],
                "index_source_available_at": index_aligned["index_source_available_at"],
                "index_price": index_aligned["index_price"],
                "premium_source_available_at": premium_aligned["premium_source_available_at"],
                "premium_index_close": premium_aligned["premium_price"],
            }
        )
        for prefix in ("mark", "index", "premium"):
            output[f"{prefix}_age_seconds"] = (
                output["available_at"] - output[f"{prefix}_source_available_at"]
            ).dt.total_seconds()

        trade = decisions["trade_price"].to_numpy(float)
        mark_price = output["mark_price"].to_numpy(float)
        index_price = output["index_price"].to_numpy(float)
        mark_index = _relative(mark_price, index_price)
        trade_mark = _relative(trade, mark_price)
        trade_index = _relative(trade, index_price)
        output["mark_index_basis"] = mark_index
        output["mark_index_basis_bps"] = mark_index * 10000.0
        output["mark_index_basis_state"] = _basis_state(mark_index)
        output["trade_mark_basis"] = trade_mark
        output["trade_mark_basis_bps"] = trade_mark * 10000.0
        output["trade_index_basis"] = trade_index
        output["trade_index_basis_bps"] = trade_index * 10000.0

        for prefix in ("mark", "index", "premium"):
            source = output[f"{prefix}_source_available_at"]
            leak = source.notna() & (source > output["available_at"])
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
