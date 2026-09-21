"""Causal Ichimoku market-structure research context.

The provider stores values on the decision-time row, never on their traditional
visual plotting offsets. A forward Kumo value is therefore information computed
from already-completed candles and known now; Chikou confirmation compares the
latest completed close with historical price instead of writing today's close
back into a historical row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.atr import atr
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.data.timing import interval_to_timedelta

from .base import FeatureDefinition, OutputField, ParameterDefinition


ICHIMOKU_CONTEXT_FEATURE_NAME = "ichimoku_context"
ICHIMOKU_CONTEXT_FEATURE_VERSION = "1"

ICHIMOKU_DEFAULT_CONVERSION_PERIOD = 9
ICHIMOKU_DEFAULT_BASE_PERIOD = 26
ICHIMOKU_DEFAULT_SPAN_B_PERIOD = 52
ICHIMOKU_DEFAULT_DISPLACEMENT = 26


def _rolling_midpoint(high: np.ndarray, low: np.ndarray, period: int) -> np.ndarray:
    high_series = pd.Series(high, dtype=float)
    low_series = pd.Series(low, dtype=float)
    return (
        (
            high_series.rolling(period, min_periods=period).max()
            + low_series.rolling(period, min_periods=period).min()
        )
        / 2.0
    ).to_numpy(float)


def _line_state(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    result = np.full(len(first), "UNKNOWN", dtype=object)
    finite = np.isfinite(first) & np.isfinite(second)
    result[finite & (first > second)] = "BULLISH"
    result[finite & (first < second)] = "BEARISH"
    result[finite & np.isclose(first, second, rtol=0.0, atol=1e-12)] = "FLAT"
    return result


def _cross_state(spread: np.ndarray) -> np.ndarray:
    result = np.full(len(spread), "NONE", dtype=object)
    if len(spread) < 2:
        return result
    current = spread[1:]
    previous = spread[:-1]
    finite = np.isfinite(current) & np.isfinite(previous)
    bullish = finite & (current > 0.0) & (previous <= 0.0)
    bearish = finite & (current < 0.0) & (previous >= 0.0)
    result[1:][bullish] = "BULLISH_CROSS"
    result[1:][bearish] = "BEARISH_CROSS"
    return result


def _twist_state(span_a: np.ndarray, span_b: np.ndarray) -> np.ndarray:
    spread = span_a - span_b
    result = np.full(len(spread), "NONE", dtype=object)
    if len(spread) < 2:
        return result
    current = spread[1:]
    previous = spread[:-1]
    finite = np.isfinite(current) & np.isfinite(previous)
    result[1:][finite & (current > 0.0) & (previous <= 0.0)] = "BULLISH_TWIST"
    result[1:][finite & (current < 0.0) & (previous >= 0.0)] = "BEARISH_TWIST"
    return result


def _price_vs_cloud(price: np.ndarray, span_a: np.ndarray, span_b: np.ndarray) -> np.ndarray:
    result = np.full(len(price), "UNKNOWN", dtype=object)
    finite = np.isfinite(price) & np.isfinite(span_a) & np.isfinite(span_b)
    lower = np.minimum(span_a, span_b)
    upper = np.maximum(span_a, span_b)
    result[finite & (price > upper)] = "ABOVE_CLOUD"
    result[finite & (price < lower)] = "BELOW_CLOUD"
    result[finite & (price >= lower) & (price <= upper)] = "INSIDE_CLOUD"
    return result


def _chikou_vs_price(close: np.ndarray, displacement: int) -> np.ndarray:
    result = np.full(len(close), "UNKNOWN", dtype=object)
    if displacement <= 0 or len(close) <= displacement:
        return result
    historical = np.full(len(close), np.nan, dtype=float)
    historical[displacement:] = close[:-displacement]
    finite = np.isfinite(close) & np.isfinite(historical)
    result[finite & (close > historical)] = "ABOVE_PRICE"
    result[finite & (close < historical)] = "BELOW_PRICE"
    result[finite & np.isclose(close, historical, rtol=0.0, atol=1e-12)] = "AT_PRICE"
    return result


def _flat_bars(values: np.ndarray) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    count = 0
    previous = np.nan
    for index, raw in enumerate(values):
        value = float(raw)
        if not np.isfinite(value):
            count = 0
            previous = np.nan
            continue
        if np.isfinite(previous) and np.isclose(value, previous, rtol=0.0, atol=1e-12):
            count += 1
        else:
            count = 1
        result[index] = float(count)
        previous = value
    return result


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return np.divide(
        numerator,
        denominator,
        out=np.full(len(numerator), np.nan, dtype=float),
        where=np.isfinite(numerator) & np.isfinite(denominator) & (denominator > 0.0),
    )


def _resample_completed(
    source: pd.DataFrame,
    *,
    strategy_minutes: int,
    target_minutes: int,
) -> pd.DataFrame:
    if target_minutes <= strategy_minutes:
        raise ValueError("target Ichimoku timeframe must be higher than strategy timeframe")
    if target_minutes % strategy_minutes:
        raise ValueError("target Ichimoku timeframe must be an integer multiple of strategy timeframe")

    factor = target_minutes // strategy_minutes
    frame = source[
        ["period_start", "available_at", "open", "high", "low", "close"]
    ].copy()
    frame["period_start"] = pd.to_datetime(frame["period_start"], utc=True)
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    grouped = frame.set_index("period_start").resample(
        f"{target_minutes}min", label="left", closed="left", origin="epoch"
    )
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        source_bars=("close", "count"),
        source_available_at=("available_at", "max"),
    )
    result = result[result["source_bars"].eq(factor)].dropna(
        subset=["open", "high", "low", "close"]
    ).reset_index()
    end_time = result["period_start"] + pd.Timedelta(minutes=target_minutes)
    result["available_at"] = pd.concat(
        [
            pd.to_datetime(result["source_available_at"], utc=True),
            pd.Series(end_time, index=result.index),
        ],
        axis=1,
    ).max(axis=1)
    return result.drop(columns=["source_available_at"])


@dataclass(frozen=True, slots=True)
class IchimokuContextFeatureProvider:
    """Prepare causal Ichimoku structure without changing strategy direction."""

    definition: FeatureDefinition = FeatureDefinition(
        name=ICHIMOKU_CONTEXT_FEATURE_NAME,
        version=ICHIMOKU_CONTEXT_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES,),
        parameters={
            "timeframe_minutes": ParameterDefinition(int, 0),
            "conversion_period": ParameterDefinition(int, ICHIMOKU_DEFAULT_CONVERSION_PERIOD),
            "base_period": ParameterDefinition(int, ICHIMOKU_DEFAULT_BASE_PERIOD),
            "span_b_period": ParameterDefinition(int, ICHIMOKU_DEFAULT_SPAN_B_PERIOD),
            "displacement": ParameterDefinition(int, ICHIMOKU_DEFAULT_DISPLACEMENT),
            "atr_period": ParameterDefinition(int, 14),
        },
        output_columns=(
            "ichimoku_timeframe_minutes",
            "ichimoku_completed_candle_time",
            "ichimoku_tenkan",
            "ichimoku_kijun",
            "ichimoku_current_span_a",
            "ichimoku_current_span_b",
            "ichimoku_future_span_a",
            "ichimoku_future_span_b",
            "ichimoku_atr",
            "price_vs_cloud",
            "tk_state",
            "tk_cross",
            "tk_spread_atr",
            "tenkan_distance_atr",
            "kijun_distance_atr",
            "kijun_slope_atr",
            "kijun_flat_bars",
            "current_cloud_state",
            "future_cloud_state",
            "cloud_thickness_atr",
            "future_cloud_thickness_atr",
            "kumo_twist",
            "chikou_vs_price",
            "cloud_distance_atr",
        ),
        output_schema={
            "price_vs_cloud": OutputField("string"),
            "tk_state": OutputField("string"),
            "tk_cross": OutputField("string"),
            "current_cloud_state": OutputField("string"),
            "future_cloud_state": OutputField("string"),
            "kumo_twist": OutputField("string"),
            "chikou_vs_price": OutputField("string"),
        },
        # Classic current-cloud values need Span B's 52-bar window shifted by 26.
        warmup_bars=78,
        availability_rule="latest_completed_ichimoku_candle_at_strategy_decision",
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
            raise ValueError("ichimoku_context requires canonical kline data") from exc

        required = {"period_start", "available_at", "open", "high", "low", "close"}
        missing = sorted(required - set(source.columns))
        if missing:
            raise ValueError(f"Canonical kline frame is missing columns: {missing}")
        if source.empty:
            raise ValueError("Cannot calculate Ichimoku context from an empty kline frame")

        source = source.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        source["period_start"] = pd.to_datetime(source["period_start"], utc=True)
        source["available_at"] = pd.to_datetime(source["available_at"], utc=True)

        strategy_minutes = int(
            interval_to_timedelta(request.strategy_interval).total_seconds() // 60
        )
        requested_minutes = int(parameters.get("timeframe_minutes", 0))
        timeframe_minutes = requested_minutes or strategy_minutes
        conversion = int(parameters.get("conversion_period", ICHIMOKU_DEFAULT_CONVERSION_PERIOD))
        base_period = int(parameters.get("base_period", ICHIMOKU_DEFAULT_BASE_PERIOD))
        span_b_period = int(parameters.get("span_b_period", ICHIMOKU_DEFAULT_SPAN_B_PERIOD))
        displacement = int(parameters.get("displacement", ICHIMOKU_DEFAULT_DISPLACEMENT))
        atr_period = int(parameters.get("atr_period", 14))
        if min(conversion, base_period, span_b_period, displacement, atr_period) <= 0:
            raise ValueError("Ichimoku periods, displacement and ATR period must be positive")
        if timeframe_minutes < strategy_minutes or timeframe_minutes % strategy_minutes:
            raise ValueError(
                "Ichimoku timeframe must equal the strategy timeframe or be an integer multiple"
            )

        if timeframe_minutes == strategy_minutes:
            bars = source[
                ["period_start", "available_at", "open", "high", "low", "close"]
            ].copy()
        else:
            bars = _resample_completed(
                source,
                strategy_minutes=strategy_minutes,
                target_minutes=timeframe_minutes,
            )

        high = pd.to_numeric(bars["high"], errors="raise").to_numpy(float)
        low = pd.to_numeric(bars["low"], errors="raise").to_numpy(float)
        close = pd.to_numeric(bars["close"], errors="raise").to_numpy(float)
        tenkan = _rolling_midpoint(high, low, conversion)
        kijun = _rolling_midpoint(high, low, base_period)
        span_a_source = (tenkan + kijun) / 2.0
        span_b_source = _rolling_midpoint(high, low, span_b_period)
        current_span_a = np.full(len(bars), np.nan, dtype=float)
        current_span_b = np.full(len(bars), np.nan, dtype=float)
        if len(bars) > displacement:
            current_span_a[displacement:] = span_a_source[:-displacement]
            current_span_b[displacement:] = span_b_source[:-displacement]

        atr_values = atr(high, low, close, atr_period)
        tk_spread = tenkan - kijun
        kijun_previous = np.full(len(kijun), np.nan, dtype=float)
        if len(kijun) > 1:
            kijun_previous[1:] = kijun[:-1]

        bar_context = pd.DataFrame(
            {
                "ichimoku_completed_candle_time": pd.to_datetime(
                    bars["period_start"], utc=True
                ),
                "_context_available_at": pd.to_datetime(bars["available_at"], utc=True),
                "ichimoku_timeframe_minutes": float(timeframe_minutes),
                "ichimoku_tenkan": tenkan,
                "ichimoku_kijun": kijun,
                "ichimoku_current_span_a": current_span_a,
                "ichimoku_current_span_b": current_span_b,
                "ichimoku_future_span_a": span_a_source,
                "ichimoku_future_span_b": span_b_source,
                "ichimoku_atr": atr_values,
                "tk_state": _line_state(tenkan, kijun),
                "tk_cross": _cross_state(tk_spread),
                "tk_spread_atr": _safe_divide(tk_spread, atr_values),
                "kijun_slope_atr": _safe_divide(kijun - kijun_previous, atr_values),
                "kijun_flat_bars": _flat_bars(kijun),
                "current_cloud_state": _line_state(current_span_a, current_span_b),
                "future_cloud_state": _line_state(span_a_source, span_b_source),
                "cloud_thickness_atr": _safe_divide(
                    np.abs(current_span_a - current_span_b), atr_values
                ),
                "future_cloud_thickness_atr": _safe_divide(
                    np.abs(span_a_source - span_b_source), atr_values
                ),
                "kumo_twist": _twist_state(span_a_source, span_b_source),
                "chikou_vs_price": _chikou_vs_price(close, displacement),
            }
        ).sort_values("_context_available_at", kind="stable")

        decision = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(source["period_start"], utc=True),
                "available_at": pd.to_datetime(source["available_at"], utc=True),
                "_decision_price": pd.to_numeric(source["close"], errors="raise").to_numpy(float),
            }
        )
        aligned = pd.merge_asof(
            decision.sort_values("available_at", kind="stable"),
            bar_context,
            left_on="available_at",
            right_on="_context_available_at",
            direction="backward",
            allow_exact_matches=True,
        ).sort_values("timestamp", kind="stable").reset_index(drop=True)

        price = aligned["_decision_price"].to_numpy(float)
        context_atr = pd.to_numeric(aligned["ichimoku_atr"], errors="coerce").to_numpy(float)
        tenkan_aligned = pd.to_numeric(
            aligned["ichimoku_tenkan"], errors="coerce"
        ).to_numpy(float)
        kijun_aligned = pd.to_numeric(
            aligned["ichimoku_kijun"], errors="coerce"
        ).to_numpy(float)
        span_a_aligned = pd.to_numeric(
            aligned["ichimoku_current_span_a"], errors="coerce"
        ).to_numpy(float)
        span_b_aligned = pd.to_numeric(
            aligned["ichimoku_current_span_b"], errors="coerce"
        ).to_numpy(float)

        aligned["price_vs_cloud"] = _price_vs_cloud(
            price, span_a_aligned, span_b_aligned
        )
        aligned["tenkan_distance_atr"] = _safe_divide(
            price - tenkan_aligned, context_atr
        )
        aligned["kijun_distance_atr"] = _safe_divide(
            price - kijun_aligned, context_atr
        )
        lower = np.minimum(span_a_aligned, span_b_aligned)
        upper = np.maximum(span_a_aligned, span_b_aligned)
        cloud_distance = np.full(len(price), np.nan, dtype=float)
        finite = (
            np.isfinite(price)
            & np.isfinite(lower)
            & np.isfinite(upper)
            & np.isfinite(context_atr)
            & (context_atr > 0.0)
        )
        cloud_distance[finite & (price > upper)] = (
            price[finite & (price > upper)] - upper[finite & (price > upper)]
        ) / context_atr[finite & (price > upper)]
        cloud_distance[finite & (price < lower)] = (
            price[finite & (price < lower)] - lower[finite & (price < lower)]
        ) / context_atr[finite & (price < lower)]
        cloud_distance[finite & (price >= lower) & (price <= upper)] = 0.0
        aligned["cloud_distance_atr"] = cloud_distance

        output_columns = [
            "timestamp",
            "available_at",
            *[
                column
                for column in self.definition.output_columns
                if column not in {"timestamp", "available_at"}
            ],
        ]
        output = aligned.drop(
            columns=["_decision_price", "_context_available_at"]
        )[output_columns]
        if bool(
            (
                pd.to_datetime(output["available_at"], utc=True)
                < pd.to_datetime(output["timestamp"], utc=True)
            ).any()
        ):
            raise ValueError("Ichimoku feature availability precedes its strategy candle")

        output.attrs.update(
            feature_name=self.definition.name,
            feature_version=self.definition.version,
            timeframe_minutes=timeframe_minutes,
            conversion_period=conversion,
            base_period=base_period,
            span_b_period=span_b_period,
            displacement=displacement,
            atr_period=atr_period,
            effective_warmup_bars=max(
                span_b_period + displacement,
                base_period + displacement,
                atr_period,
            ),
            request_cache_key=request.cache_key(),
        )
        return output
