"""Causal, source-native Binance futures positioning research facts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.alignment import causal_asof_join
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from .base import FeatureDefinition, ParameterDefinition

FUTURES_POSITIONING_FEATURE_NAME = "futures_positioning"
FUTURES_POSITIONING_FEATURE_VERSION = "3"
RATIOS = (
    "top_trader_account_long_short_ratio", "top_trader_position_long_short_ratio",
    "global_long_short_account_ratio", "taker_long_short_volume_ratio",
)


def _elapsed_change(frame: pd.DataFrame, column: str, horizon: pd.Timedelta) -> tuple[np.ndarray, np.ndarray]:
    """Compare each observation with the last observation at or before T-H."""
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(float)
    times = pd.DatetimeIndex(frame.available_at).asi8
    prior_i = np.searchsorted(times, times - horizon.value, side="right") - 1
    prior = np.full(len(frame), np.nan)
    valid = prior_i >= 0
    prior[valid] = values[prior_i[valid]]
    change = values - prior
    pct = np.divide(change, prior, out=np.full(len(frame), np.nan),
                    where=np.isfinite(values) & np.isfinite(prior) & (prior != 0))
    change[~(np.isfinite(values) & np.isfinite(prior))] = np.nan
    return change, pct


def _time_zscore(frame: pd.DataFrame, column: str, days: float, minimum: int) -> np.ndarray:
    series = pd.Series(pd.to_numeric(frame[column], errors="coerce").to_numpy(float),
                       index=pd.DatetimeIndex(frame.available_at))
    window = series.rolling(f"{days}D", min_periods=minimum)
    std = window.std(ddof=0)
    return ((series - window.mean()) / std.where(std > 0)).to_numpy(float)


def _state(price: np.ndarray, oi: np.ndarray) -> np.ndarray:
    out = np.full(len(price), "UNKNOWN", object)
    finite = np.isfinite(price) & np.isfinite(oi)
    out[finite] = "FLAT_OR_MIXED"
    out[finite & (price > 0) & (oi > 0)] = "PRICE_UP_OI_UP"
    out[finite & (price > 0) & (oi < 0)] = "PRICE_UP_OI_DOWN"
    out[finite & (price < 0) & (oi > 0)] = "PRICE_DOWN_OI_UP"
    out[finite & (price < 0) & (oi < 0)] = "PRICE_DOWN_OI_DOWN"
    return out


@dataclass(frozen=True, slots=True)
class FuturesPositioningFeatureProvider:
    definition: FeatureDefinition = FeatureDefinition(
        name=FUTURES_POSITIONING_FEATURE_NAME, version=FUTURES_POSITIONING_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES, DatasetKind.FUTURES_METRICS),
        parameters={"oi_zscore_window_days": ParameterDefinition(float, 7.0),
                    "oi_zscore_min_samples": ParameterDefinition(int, 20)},
        output_columns=(
            "metrics_source_available_at", "metrics_age_seconds", "open_interest", "open_interest_value",
            "oi_change_5m", "oi_change_pct_5m", "oi_change_1h", "oi_change_pct_1h",
            "oi_change_24h", "oi_change_pct_24h", "oi_zscore_7d", "price_change_pct_1h",
            "oi_vs_price_state_1h", "open_interest_change_1bar_pct", "open_interest_change_3bar_pct",
            "open_interest_value_change_1bar_pct", "price_return_1bar", "price_oi_state",
            *RATIOS, "top_trader_account_bias", "top_trader_position_bias",
            "global_long_short_account_bias", "taker_long_short_volume_bias"),
        availability_rule="source_native_metrics_then_available_at_asof_strategy_decision")

    def compute(self, request: DataRequest, datasets: Mapping[DatasetKind, pd.DataFrame],
                parameters: Mapping[str, object], feature_frames=None) -> pd.DataFrame:
        del feature_frames
        k = datasets[DatasetKind.KLINES].copy()
        m = datasets[DatasetKind.FUTURES_METRICS].copy()
        if not {"period_start", "available_at", "close"} <= set(k):
            raise ValueError("Canonical kline frame requires period_start, available_at and close")
        if "available_at" not in m or "open_interest" not in m:
            raise ValueError("Canonical futures metrics frame requires available_at and open_interest")
        p = self.definition.normalize_parameters(parameters)
        k = k.sort_values("period_start").drop_duplicates("period_start", keep="last")
        decisions = pd.DataFrame({"timestamp": pd.to_datetime(k.period_start, utc=True),
                                  "decision_time": pd.to_datetime(k.available_at, utc=True),
                                  "close": pd.to_numeric(k.close, errors="coerce")})
        m["available_at"] = pd.to_datetime(m.available_at, utc=True)
        m = m.sort_values("available_at").drop_duplicates("available_at", keep="last").reset_index(drop=True)
        for col in ("open_interest", "open_interest_value", *RATIOS):
            if col not in m: m[col] = np.nan
            m[col] = pd.to_numeric(m[col], errors="coerce")
        for label, delta in (("5m", pd.Timedelta(minutes=5)), ("1h", pd.Timedelta(hours=1)),
                             ("24h", pd.Timedelta(hours=24))):
            m[f"oi_change_{label}"], m[f"oi_change_pct_{label}"] = _elapsed_change(m, "open_interest", delta)
        m["oi_zscore_7d"] = _time_zscore(m, "open_interest", p["oi_zscore_window_days"], p["oi_zscore_min_samples"])
        joined = causal_asof_join(decisions, m)
        out = pd.DataFrame({"timestamp": joined.timestamp, "available_at": joined.decision_time,
                            "metrics_source_available_at": joined.available_at})
        out["metrics_age_seconds"] = (out.available_at-out.metrics_source_available_at).dt.total_seconds()
        for col in ("open_interest", "open_interest_value", *RATIOS, "oi_change_5m", "oi_change_pct_5m",
                    "oi_change_1h", "oi_change_pct_1h", "oi_change_24h", "oi_change_pct_24h", "oi_zscore_7d"):
            out[col] = pd.to_numeric(joined[col], errors="coerce")
        # Price is strategy-source data. An elapsed-hour comparison is used (never a fixed strategy-row lag).
        dt = pd.DatetimeIndex(decisions.decision_time).asi8
        pi = np.searchsorted(dt, dt-pd.Timedelta(hours=1).value, side="right")-1
        close = decisions.close.to_numpy(float); prior = np.full(len(close), np.nan); valid=pi>=0; prior[valid]=close[pi[valid]]
        out["price_change_pct_1h"] = np.divide(close-prior, prior, out=np.full(len(close), np.nan), where=prior!=0)
        out["oi_vs_price_state_1h"] = _state(out.price_change_pct_1h.to_numpy(), out.oi_change_pct_1h.to_numpy())
        # Retained compatibility fields; their names explicitly describe strategy-bar semantics.
        oi=out.open_interest; val=out.open_interest_value
        out["open_interest_change_1bar_pct"]=oi.pct_change(fill_method=None)
        out["open_interest_change_3bar_pct"]=oi.pct_change(3, fill_method=None)
        out["open_interest_value_change_1bar_pct"]=val.pct_change(fill_method=None)
        out["price_return_1bar"]=pd.Series(close).pct_change(fill_method=None)
        out["price_oi_state"]=_state(out.price_return_1bar.to_numpy(), out.open_interest_change_1bar_pct.to_numpy())
        for ratio, bias in zip(RATIOS, ("top_trader_account_bias", "top_trader_position_bias", "global_long_short_account_bias", "taker_long_short_volume_bias")):
            out[bias]=out[ratio]-1.0
        out.attrs.update(feature_name=self.definition.name, feature_version=self.definition.version,
                         effective_warmup_bars=0, request_cache_key=request.cache_key())
        return out
