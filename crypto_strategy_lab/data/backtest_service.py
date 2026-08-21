"""Prepare simulator inputs from the Binance Data Lake."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from crypto_strategy_lab.features.technical import prepare_core_directional_features

from .legacy_bridge import canonical_to_legacy_ohlcv
from .query import DataRequest
from .store import MarketDataStore
from .timing import interval_to_timedelta


@dataclass(frozen=True, slots=True)
class BacktestDataBundle:
    """All market-data and prepared feature inputs required by one simulator run."""

    request: DataRequest
    strategy: pd.DataFrame
    intrabar: pd.DataFrame | None
    technical_features: pd.DataFrame
    structural_benchmark: pd.DataFrame | None
    structural_benchmark_symbol: str | None
    structural_benchmark_interval: str | None


def _legacy_from_canonical(canonical: pd.DataFrame, interval: str, label: str) -> pd.DataFrame:
    minutes = int(interval_to_timedelta(interval).total_seconds() // 60)
    return canonical_to_legacy_ohlcv(
        canonical,
        label=label,
        expected_timeframe_minutes=minutes,
    )


def _legacy_klines(store: MarketDataStore, request: DataRequest, interval: str, label: str) -> pd.DataFrame:
    return _legacy_from_canonical(store.load_klines(request, interval), interval, label)


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
) -> BacktestDataBundle:
    """Load market data and calculate reusable causal technical features.

    Structural regime warm-up is fetched before the requested strategy start so
    the first strategy candle can use only benchmark history that was already
    available at that time. ``intrabar_start`` may be later than the strategy
    request start, allowing indicator warm-up on strategy candles without
    needlessly loading minute data before trading begins. The raw archive tree
    remains read-only.
    """

    if refresh_catalog:
        store.refresh_catalog()

    canonical_strategy = store.load_klines(request, request.strategy_interval)
    strategy = _legacy_from_canonical(
        canonical_strategy,
        request.strategy_interval,
        "Strategy data (Data Lake v2)",
    )
    technical_features = prepare_core_directional_features(
        request,
        canonical_strategy,
        atr_period=atr_period,
        adx_period=adx_period,
        di_pressure_lookback=di_pressure_lookback,
    )

    intrabar = None
    if request.intrabar_interval:
        effective_intrabar_start = request.start
        if intrabar_start is not None:
            effective_intrabar_start = max(request.start, intrabar_start)
        intrabar_request = DataRequest(
            symbol=request.symbol,
            start=effective_intrabar_start,
            end=request.end,
            strategy_interval=request.intrabar_interval,
            market=request.market,
            exchange=request.exchange,
        )
        intrabar = _legacy_klines(
            store,
            intrabar_request,
            request.intrabar_interval,
            "Intrabar data (Data Lake v2)",
        )

    benchmark = None
    benchmark_symbol = None
    benchmark_interval_used = None

    if market_regime_method in {"BTC_STRUCTURAL", "ASSET_STRUCTURAL"}:
        benchmark_symbol = "BTCUSDT" if market_regime_method == "BTC_STRUCTURAL" else request.symbol
        benchmark_interval_used = benchmark_interval
        warmup_days = int(structural_regime_sma_days) + int(structural_regime_slope_lookback_days) + 7
        benchmark_request = DataRequest(
            symbol=benchmark_symbol,
            start=request.start - timedelta(days=warmup_days),
            end=request.end,
            strategy_interval=benchmark_interval,
            market=request.market,
            exchange=request.exchange,
        )
        benchmark = store.load_klines(benchmark_request, benchmark_request.strategy_interval)

    return BacktestDataBundle(
        request=request,
        strategy=strategy,
        intrabar=intrabar,
        technical_features=technical_features,
        structural_benchmark=benchmark,
        structural_benchmark_symbol=benchmark_symbol,
        structural_benchmark_interval=benchmark_interval_used,
    )
