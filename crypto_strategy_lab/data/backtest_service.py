"""Prepare simulator inputs from the Binance Data Lake."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from .legacy_bridge import load_backtest_frames_from_store
from .query import DataRequest
from .store import MarketDataStore


@dataclass(frozen=True, slots=True)
class BacktestDataBundle:
    """All market-data inputs required by one simulator run."""

    request: DataRequest
    strategy: pd.DataFrame
    intrabar: pd.DataFrame | None
    structural_benchmark: pd.DataFrame | None
    structural_benchmark_symbol: str | None
    structural_benchmark_interval: str | None


def load_backtest_bundle(
    store: MarketDataStore,
    request: DataRequest,
    *,
    market_regime_method: str,
    structural_regime_sma_days: int = 200,
    structural_regime_slope_lookback_days: int = 30,
    benchmark_interval: str = "1h",
    refresh_catalog: bool = True,
) -> BacktestDataBundle:
    """Load strategy, intrabar and optional structural benchmark data.

    Structural regime warm-up is fetched before the requested strategy start so
    the first strategy candle can use only benchmark history that was already
    available at that time. The raw archive tree remains read-only.
    """

    if refresh_catalog:
        store.refresh_catalog()

    strategy, intrabar = load_backtest_frames_from_store(store, request)
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
        structural_benchmark=benchmark,
        structural_benchmark_symbol=benchmark_symbol,
        structural_benchmark_interval=benchmark_interval_used,
    )
