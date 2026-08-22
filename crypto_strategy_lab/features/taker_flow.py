"""Compact taker flow derived from completed Binance kline aggregates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
import numpy as np
import pandas as pd
from crypto_strategy_lab.data.alignment import causal_asof_join
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from .base import FeatureDataResource, FeatureDefinition, ParameterDefinition

TAKER_FLOW_CONTEXT_FEATURE_NAME = "taker_flow_context"
TAKER_FLOW_CONTEXT_FEATURE_VERSION = "1"


def taker_flow_resource(interval: str = "5m") -> FeatureDataResource:
    return FeatureDataResource(DatasetKind.KLINES, interval, "taker_flow")


@dataclass(frozen=True, slots=True)
class TakerFlowContextFeatureProvider:
    definition: FeatureDefinition = FeatureDefinition(
        name=TAKER_FLOW_CONTEXT_FEATURE_NAME, version=TAKER_FLOW_CONTEXT_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES,),
        parameters={"taker_flow_interval": ParameterDefinition(str, "5m"),
                    "volume_tolerance": ParameterDefinition(float, 1e-9)},
        output_columns=("taker_source_available_at", "taker_age_seconds", "taker_buy_volume",
            "taker_sell_volume", "taker_buy_sell_ratio", "taker_delta", "taker_delta_pct",
            "taker_delta_15m", "taker_delta_pct_15m", "taker_delta_1h", "taker_delta_pct_1h",
            "flow_acceleration", "flow_persistence"),
        availability_rule="completed_auxiliary_kline_available_at_or_before_strategy_decision")

    def compute(self, request: DataRequest, datasets: Mapping[object, pd.DataFrame],
                parameters: Mapping[str, object], feature_frames=None) -> pd.DataFrame:
        del feature_frames
        p=self.definition.normalize_parameters(parameters); interval=str(p["taker_flow_interval"])
        strategy=datasets[DatasetKind.KLINES].copy()
        resource=taker_flow_resource(interval)
        source=datasets.get(resource)
        if source is None:
            raise ValueError(f"taker_flow_context requires auxiliary {resource!r}")
        source=source.copy()
        required={"available_at", "volume", "taker_buy_base_volume"}
        if not required <= set(source): raise ValueError(f"Taker-flow klines missing {sorted(required-set(source))}")
        source["available_at"]=pd.to_datetime(source.available_at, utc=True)
        source=source.sort_values("available_at").drop_duplicates("available_at", keep="last").reset_index(drop=True)
        total=pd.to_numeric(source.volume, errors="coerce").to_numpy(float)
        buy=pd.to_numeric(source.taker_buy_base_volume, errors="coerce").to_numpy(float)
        tolerance=float(p["volume_tolerance"])*np.maximum(1.0, np.abs(total))
        if np.any(buy-total > tolerance): raise ValueError("taker_buy_base_volume exceeds volume beyond tolerance")
        sell=total-buy; delta=buy-sell
        source["taker_buy_volume"]=buy; source["taker_sell_volume"]=sell
        source["taker_buy_sell_ratio"]=np.divide(buy,sell,out=np.full(len(source),np.nan),where=sell!=0)
        source["taker_delta"]=delta
        source["taker_delta_pct"]=np.divide(delta,total,out=np.full(len(source),np.nan),where=total!=0)
        indexed=pd.DataFrame({"delta":delta,"volume":total}, index=pd.DatetimeIndex(source.available_at))
        for label, window in (("15m","15min"),("1h","1h")):
            roll=indexed.rolling(window, closed="both", min_periods=1).sum()
            source[f"taker_delta_{label}"]=roll.delta.to_numpy()
            source[f"taker_delta_pct_{label}"]=np.divide(roll.delta,roll.volume,
                out=np.full(len(source),np.nan),where=roll.volume.to_numpy()!=0)
        source["flow_acceleration"]=source.taker_delta_15m-source.taker_delta_15m.shift(1)
        signs=np.sign(delta)
        # Persistence is the fraction of completed trailing-hour intervals matching aggregate sign.
        values=[]
        times=pd.DatetimeIndex(source.available_at)
        for i,t in enumerate(times):
            mask=(times >= t-pd.Timedelta(hours=1)) & (times <= t)
            current=np.sign(source.loc[i,"taker_delta_1h"])
            sample=signs[mask]
            values.append(np.nan if len(sample)<2 or current==0 else float(np.mean(sample==current)))
        source["flow_persistence"]=values
        decisions=pd.DataFrame({"timestamp":pd.to_datetime(strategy.period_start,utc=True),
            "decision_time":pd.to_datetime(strategy.available_at,utc=True)})
        facts=[name for name in self.definition.output_columns
               if name not in {"timestamp","available_at","taker_source_available_at","taker_age_seconds"}]
        joined=causal_asof_join(decisions, source[["available_at",*facts]])
        out=pd.DataFrame({"timestamp":joined.timestamp,"available_at":joined.decision_time,
                          "taker_source_available_at":joined.available_at})
        out["taker_age_seconds"]=(out.available_at-out.taker_source_available_at).dt.total_seconds()
        for col in facts: out[col]=pd.to_numeric(joined[col],errors="coerce")
        out.attrs.update(feature_name=self.definition.name,feature_version=self.definition.version,
                         effective_warmup_bars=0,request_cache_key=request.cache_key(),source_interval=interval)
        return out
