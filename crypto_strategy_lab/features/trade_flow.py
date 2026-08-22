"""Causal research features derived exclusively from compact trade aggregates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import numpy as np
import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from .base import FeatureDataResource, FeatureDefinition, OutputField, ParameterDefinition

TRADE_FLOW_FEATURE_NAME = "trade_flow_context"
TRADE_FLOW_FEATURE_VERSION = "1"

def trade_flow_resource(source: DatasetKind, interval: str = "1m") -> FeatureDataResource:
    if source not in {DatasetKind.AGG_TRADES, DatasetKind.TRADES}:
        raise ValueError("trade flow source must be agg_trades or trades")
    return FeatureDataResource(source, interval, "trade_flow_aggregate")

def _windows(value: object) -> tuple[int, ...]:
    raw = value if isinstance(value, (list, tuple)) else str(value).split(",")
    mapping = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
    try: return tuple(mapping[str(item).strip()] for item in raw)
    except KeyError as exc: raise ValueError("trade_flow_windows support only 1m,5m,15m,1h") from exc

_BASE_FIELDS = ("underlying_trade_count", "source_event_count", "base_volume", "quote_volume",
                "aggressive_buy_base_volume", "aggressive_sell_base_volume", "trade_delta_base")

def _schema(params):
    schema = {"trade_flow_source": OutputField("string", False), "trade_source_covered": OutputField("bool", False),
              "cvd_utc_day": OutputField("numeric"), "cvd_1h": OutputField("numeric"),
              "trade_intensity_change": OutputField("numeric"), "last_trade_event_at": OutputField("datetime"),
              "trade_event_age_seconds": OutputField("numeric")}
    for minutes in _windows(params["trade_flow_windows"]):
        suffix = "1h" if minutes == 60 else f"{minutes}m"
        for name in ("trade_count", "source_event_count", "volume", "quote_volume", "aggressive_buy_volume",
                     "aggressive_sell_volume", "trade_delta", "trade_delta_pct", "trade_intensity", "source_event_intensity"):
            schema[f"{name}_{suffix}"] = OutputField("numeric")
        schema[f"trade_vwap_{suffix}"] = OutputField("numeric")
        schema[f"average_trade_size_{suffix}"] = OutputField("numeric")
    return schema

@dataclass(frozen=True, slots=True)
class TradeFlowContextFeatureProvider:
    definition: FeatureDefinition = FeatureDefinition(
        name=TRADE_FLOW_FEATURE_NAME, version=TRADE_FLOW_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES,),
        parameters={"trade_flow_source": ParameterDefinition(str, "AGG_TRADES"),
                    "trade_flow_windows": ParameterDefinition(lambda x: tuple(x) if isinstance(x, (list, tuple)) else tuple(str(x).split(",")), ("1m","5m","15m","1h"))},
        output_schema_factory=_schema,
        availability_rule="completed_1m_trade_aggregates_available_at_bucket_close")

    def compute(self, request: DataRequest, datasets: Mapping[object, pd.DataFrame], parameters: Mapping[str, object], feature_frames=None) -> pd.DataFrame:
        del feature_frames
        source = DatasetKind[str(parameters["trade_flow_source"]).upper()]
        resource = trade_flow_resource(source)
        if resource not in datasets:
            raise ValueError("trade_flow_context requires a compact trade_flow_aggregate resource")
        agg = datasets[resource].copy()
        forbidden = {"agg_trade_id", "trade_id", "is_buyer_maker", "first_trade_id", "last_trade_id"}
        if forbidden & set(agg):
            raise ValueError("raw trade-event columns are forbidden in the trade-flow provider")
        agg = agg.sort_values("available_at", kind="stable")
        required = {"period_start", "period_end", "available_at", "trade_flow_source_covered", "weighted_price_sum", "last_event_at", *_BASE_FIELDS}
        if required - set(agg): raise ValueError(f"compact trade aggregate missing {sorted(required-set(agg))}")
        for col in ("period_start", "period_end", "available_at", "last_event_at"):
            agg[col] = pd.to_datetime(agg[col], utc=True)
        covered = agg.trade_flow_source_covered.astype(bool)
        facts = pd.DataFrame({"available_at": agg.available_at, "trade_source_covered": covered})
        windows = _windows(parameters["trade_flow_windows"])
        for minutes in windows:
            suffix = "1h" if minutes == 60 else f"{minutes}m"
            valid = covered.rolling(minutes, min_periods=minutes).sum().eq(minutes)
            sums = {name: pd.to_numeric(agg[name]).rolling(minutes, min_periods=minutes).sum().where(valid) for name in _BASE_FIELDS}
            weighted = pd.to_numeric(agg.weighted_price_sum).rolling(minutes, min_periods=minutes).sum().where(valid)
            facts[f"trade_count_{suffix}"] = sums["underlying_trade_count"]
            facts[f"source_event_count_{suffix}"] = sums["source_event_count"]
            facts[f"volume_{suffix}"] = sums["base_volume"]; facts[f"quote_volume_{suffix}"] = sums["quote_volume"]
            facts[f"aggressive_buy_volume_{suffix}"] = sums["aggressive_buy_base_volume"]
            facts[f"aggressive_sell_volume_{suffix}"] = sums["aggressive_sell_base_volume"]
            facts[f"trade_delta_{suffix}"] = sums["trade_delta_base"]
            facts[f"trade_delta_pct_{suffix}"] = (sums["trade_delta_base"] / sums["base_volume"].replace(0, np.nan))
            facts[f"trade_vwap_{suffix}"] = weighted / sums["base_volume"].replace(0, np.nan)
            facts[f"average_trade_size_{suffix}"] = sums["base_volume"] / sums["underlying_trade_count"].replace(0, np.nan)
            facts[f"trade_intensity_{suffix}"] = sums["underlying_trade_count"] / minutes
            facts[f"source_event_intensity_{suffix}"] = sums["source_event_count"] / minutes
        day = agg.available_at.dt.floor("D")
        facts["cvd_utc_day"] = pd.to_numeric(agg.trade_delta_base).where(covered).groupby(day).cumsum()
        valid60 = covered.rolling(60, min_periods=60).sum().eq(60)
        facts["cvd_1h"] = pd.to_numeric(agg.trade_delta_base).rolling(60, min_periods=60).sum().where(valid60)
        current5 = pd.to_numeric(agg.underlying_trade_count).rolling(5, min_periods=5).sum() / 5
        prior60 = pd.to_numeric(agg.underlying_trade_count).shift(5).rolling(60, min_periods=60).sum() / 60
        reference_valid = covered.shift(5).rolling(60, min_periods=60).sum().eq(60)
        facts["trade_intensity_change"] = (current5 / prior60.replace(0, np.nan) - 1).where(reference_valid)
        facts["last_trade_event_at"] = agg.last_event_at.ffill().where(covered)
        facts["trade_event_age_seconds"] = (facts.available_at - facts.last_trade_event_at).dt.total_seconds()
        facts["trade_flow_source"] = source.value
        klines = datasets[DatasetKind.KLINES].copy().sort_values("available_at")
        decision = pd.to_datetime(klines.available_at, utc=True)
        aligned = pd.merge_asof(pd.DataFrame({"timestamp": pd.to_datetime(klines.period_start, utc=True), "available_at": decision}), facts, on="available_at", direction="backward")
        aligned["trade_flow_source"] = aligned.trade_flow_source.fillna(source.value)
        aligned["trade_source_covered"] = aligned.trade_source_covered.fillna(False).astype(bool)
        return aligned
