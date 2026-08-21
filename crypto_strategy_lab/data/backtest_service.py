"""Prepare simulator inputs from the Binance Data Lake."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd

from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features.cache import FeatureFrameCache
from crypto_strategy_lab.features.context import MarketContextFeatureProvider
from crypto_strategy_lab.features.support_resistance import SupportResistanceFeatureProvider
from crypto_strategy_lab.features.technical import CORE_DIRECTIONAL_FEATURE_NAME, CoreDirectionalFeatureProvider
from .legacy_bridge import canonical_to_legacy_ohlcv
from .query import DataRequest
from .store import MarketDataStore
from .timing import interval_to_timedelta


@dataclass(frozen=True, slots=True)
class BacktestDataBundle:
    request: DataRequest
    strategy: pd.DataFrame
    intrabar: pd.DataFrame | None
    technical_features: pd.DataFrame
    context_features: pd.DataFrame
    support_resistance_features: pd.DataFrame | None
    structural_benchmark: pd.DataFrame | None
    structural_benchmark_symbol: str | None
    structural_benchmark_interval: str | None


def _legacy_from_canonical(canonical: pd.DataFrame, interval: str, label: str) -> pd.DataFrame:
    minutes = int(interval_to_timedelta(interval).total_seconds() // 60)
    return canonical_to_legacy_ohlcv(canonical, label=label, expected_timeframe_minutes=minutes)


def _legacy_klines(store, request, interval, label):
    return _legacy_from_canonical(store.load_klines(request, interval), interval, label)


def _cached_feature(store, request, canonical, provider, parameters, feature_frames=None):
    dependency_keys = tuple(
        str(frame.attrs.get("feature_cache_key") or f"uncached-{name}")
        for name, frame in sorted((feature_frames or {}).items())
    )
    cache = FeatureFrameCache(store.cache.root)
    key = cache.key(
        provider.definition, request, parameters, canonical,
        dependency_keys=dependency_keys,
    )
    cached = cache.load(provider.definition, request, key)
    if cached is not None:
        return cached
    if feature_frames:
        frame = provider.compute(
            request, {DatasetKind.KLINES: canonical}, parameters, feature_frames
        )
    else:
        frame = provider.compute(request, {DatasetKind.KLINES: canonical}, parameters)
    frame.attrs["feature_cache_hit"] = False
    frame.attrs["feature_cache_key"] = key
    cache.store(provider.definition, request, key, frame)
    return frame


def load_backtest_bundle(
    store: MarketDataStore,
    request: DataRequest,
    *,
    market_regime_method: str,
    structural_regime_sma_days: int = 200,
    structural_regime_slope_lookback_days: int = 30,
    benchmark_interval: str = "1h",
    refresh_catalog: bool = True,
    intrabar_start: datetime | None = None,
    atr_period: int = 14,
    adx_period: int = 14,
    di_pressure_lookback: int = 3,
    bb_period: int = 20,
    bb_stddevs: float = 2.0,
    mean_reversion_period: int = 20,
    enable_support_resistance_analysis: bool = False,
    sr_timeframe_minutes: int = 0,
    sr_pivot_left: int = 5,
    sr_pivot_right: int = 5,
    sr_lookback_bars: int = 200,
    sr_zone_width_atr: float = 0.5,
    sr_near_distance_atr: float = 0.75,
    enable_sr_hold_confirmation: bool = False,
    sr_hold_confirmation_bars: int = 3,
    sr_hold_confirmation_atr: float = 0.25,
    sr_break_tolerance_atr: float = 0.25,
    sr_break_basis: str = "CLOSE",
) -> BacktestDataBundle:
    """Load market data and reusable causal feature blocks.

    Same-timeframe support/resistance is prepared and cached here. Higher-timeframe
    S/R remains on the mature complete-bar resampling path until the HTF feature
    provider is migrated, preserving its current timing semantics.
    """
    if refresh_catalog:
        store.refresh_catalog()

    canonical = store.load_klines(request, request.strategy_interval)
    strategy = _legacy_from_canonical(canonical, request.strategy_interval, "Strategy data (Data Lake v2)")

    directional = _cached_feature(
        store, request, canonical, CoreDirectionalFeatureProvider(),
        {
            "atr_period": int(atr_period), "adx_period": int(adx_period),
            "di_pressure_lookback": int(di_pressure_lookback),
        },
    )
    directional_dependency = {CORE_DIRECTIONAL_FEATURE_NAME: directional}
    context = _cached_feature(
        store, request, canonical, MarketContextFeatureProvider(),
        {
            "bb_period": int(bb_period), "bb_stddevs": float(bb_stddevs),
            "mean_reversion_period": int(mean_reversion_period),
        }, directional_dependency,
    )

    sr_features = None
    strategy_minutes = int(interval_to_timedelta(request.strategy_interval).total_seconds() // 60)
    effective_sr_minutes = int(sr_timeframe_minutes or strategy_minutes)
    if enable_support_resistance_analysis and effective_sr_minutes == strategy_minutes:
        sr_features = _cached_feature(
            store, request, canonical, SupportResistanceFeatureProvider(),
            {
                "sr_pivot_left": int(sr_pivot_left),
                "sr_pivot_right": int(sr_pivot_right),
                "sr_lookback_bars": int(sr_lookback_bars),
                "sr_zone_width_atr": float(sr_zone_width_atr),
                "sr_near_distance_atr": float(sr_near_distance_atr),
                "enable_sr_hold_confirmation": bool(enable_sr_hold_confirmation),
                "sr_hold_confirmation_bars": int(sr_hold_confirmation_bars),
                "sr_hold_confirmation_atr": float(sr_hold_confirmation_atr),
                "sr_break_tolerance_atr": float(sr_break_tolerance_atr),
                "sr_break_basis": str(sr_break_basis).upper(),
            }, directional_dependency,
        )

    intrabar = None
    if request.intrabar_interval:
        effective_start = max(request.start, intrabar_start) if intrabar_start else request.start
        intrabar_request = DataRequest(
            symbol=request.symbol, start=effective_start, end=request.end,
            strategy_interval=request.intrabar_interval,
            market=request.market, exchange=request.exchange,
        )
        intrabar = _legacy_klines(
            store, intrabar_request, request.intrabar_interval, "Intrabar data (Data Lake v2)"
        )

    benchmark = None
    benchmark_symbol = None
    benchmark_interval_used = None
    if market_regime_method in {"BTC_STRUCTURAL", "ASSET_STRUCTURAL"}:
        benchmark_symbol = "BTCUSDT" if market_regime_method == "BTC_STRUCTURAL" else request.symbol
        benchmark_interval_used = benchmark_interval
        warmup_days = int(structural_regime_sma_days) + int(structural_regime_slope_lookback_days) + 7
        benchmark_request = DataRequest(
            symbol=benchmark_symbol, start=request.start - timedelta(days=warmup_days),
            end=request.end, strategy_interval=benchmark_interval,
            market=request.market, exchange=request.exchange,
        )
        benchmark = store.load_klines(benchmark_request, benchmark_request.strategy_interval)

    return BacktestDataBundle(
        request=request, strategy=strategy, intrabar=intrabar,
        technical_features=directional, context_features=context,
        support_resistance_features=sr_features,
        structural_benchmark=benchmark,
        structural_benchmark_symbol=benchmark_symbol,
        structural_benchmark_interval=benchmark_interval_used,
    )
