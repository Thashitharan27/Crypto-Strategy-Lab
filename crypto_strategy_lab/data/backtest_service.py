"""Prepare simulator inputs from the Binance Data Lake."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd

from crypto_strategy_lab.data.schemas import DatasetKind, MarketKind
from crypto_strategy_lab.features.agg_trade_flow import AggTradeFlowFeatureProvider
from crypto_strategy_lab.features.basis import BasisContextFeatureProvider
from crypto_strategy_lab.features.cache import FeatureFrameCache
from crypto_strategy_lab.features import production_feature_registry
from crypto_strategy_lab.features.funding import FundingContextFeatureProvider
from crypto_strategy_lab.features.futures_positioning import FuturesPositioningFeatureProvider
from crypto_strategy_lab.features.technical import CORE_DIRECTIONAL_FEATURE_NAME
from .intrabar_index import as_searchsorted_intrabar
from .legacy_bridge import canonical_to_legacy_ohlcv
from .query import DataRequest
from .store import DataNotAvailableError, MarketDataStore
from .timing import interval_to_timedelta


@dataclass(frozen=True, slots=True)
class BacktestDataBundle:
    request: DataRequest
    strategy: pd.DataFrame
    intrabar: pd.DataFrame | None
    technical_features: pd.DataFrame
    context_features: pd.DataFrame
    support_resistance_features: pd.DataFrame | None
    research_features: dict[str, pd.DataFrame]
    structural_benchmark: pd.DataFrame | None
    structural_benchmark_symbol: str | None
    structural_benchmark_interval: str | None
    state_transition_daily_features: pd.DataFrame | None = None


def _legacy_from_canonical(canonical: pd.DataFrame, interval: str, label: str) -> pd.DataFrame:
    minutes = int(interval_to_timedelta(interval).total_seconds() // 60)
    return canonical_to_legacy_ohlcv(canonical, label=label, expected_timeframe_minutes=minutes)


def _legacy_klines(store, request, interval, label):
    return _legacy_from_canonical(store.load_klines(request, interval), interval, label)


def _cached_multisource_feature(store, request, datasets, provider, parameters=None):
    """Cache a feature that depends on klines plus one or more event datasets."""
    registry = production_feature_registry()
    return registry.execute(
        [provider.definition.name], request, datasets,
        parameters={provider.definition.name: dict(parameters or {})},
        cache=FeatureFrameCache(store.cache.root),
    )[provider.definition.name]


def _cached_catalog_feature(
    store,
    request,
    canonical,
    dataset,
    provider,
    parameters=None,
):
    """Resolve a multisource feature cache before materializing its event data."""
    parameters = dict(parameters or {})
    kline_request = _dataset_request(request, DatasetKind.KLINES)
    signatures = (
        store.source_signature(
            kline_request, DatasetKind.KLINES, interval=request.strategy_interval
        ),
        store.source_signature(_dataset_request(request, dataset), dataset),
    )
    registry = production_feature_registry()
    resolved = registry.resolve(
        [provider.definition.name], {provider.definition.name: parameters}
    )[0]
    source_ids = {
        kind: signature.cache_identity()
        for kind, signature in zip(provider.definition.required_datasets, signatures)
    }
    key = registry.identity(resolved, request, source_ids, {})
    cache = FeatureFrameCache(store.cache.root)
    cached = cache.load(provider.definition, request, key)
    if cached is not None:
        try:
            provider.definition.validate_output(cached)
            return cached
        except ValueError:
            pass

    source = store.load_dataset(_dataset_request(request, dataset), dataset)
    if source.empty:
        return None
    frame = provider.compute(request, {DatasetKind.KLINES: canonical, dataset: source}, resolved.parameters)
    provider.definition.validate_output(frame)
    frame.attrs["feature_cache_hit"] = False
    frame.attrs["feature_cache_key"] = key
    cache.store(provider.definition, request, key, frame)
    return frame


def _dataset_request(request: DataRequest, dataset: DatasetKind, *, start=None) -> DataRequest:
    return DataRequest(
        symbol=request.symbol,
        start=start or request.start,
        end=request.end,
        strategy_interval=request.strategy_interval,
        market=request.market,
        exchange=request.exchange,
        datasets=(dataset,),
    )


def _optional_futures_research_features(
    store: MarketDataStore,
    request: DataRequest,
    canonical: pd.DataFrame,
    *,
    include_agg_trade_flow: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load futures research blocks when local coverage exists.

    Compact metrics/funding/reference-price datasets are inexpensive enough to
    attach automatically. Aggregate trades can be very large, so trade-flow
    aggregation is explicit opt-in.
    """
    if request.market != MarketKind.FUTURES_UM:
        return {}

    result: dict[str, pd.DataFrame] = {}
    try:
        provider = FuturesPositioningFeatureProvider()
        positioning = _cached_catalog_feature(
            store, request, canonical, DatasetKind.FUTURES_METRICS, provider
        )
        if positioning is not None:
            result[provider.definition.name] = positioning
    except DataNotAvailableError:
        pass

    try:
        funding_request = _dataset_request(
            request,
            DatasetKind.FUNDING_RATE,
            start=request.start - timedelta(hours=24),
        )
        funding = store.load_dataset(funding_request, DatasetKind.FUNDING_RATE)
        if not funding.empty:
            provider = FundingContextFeatureProvider()
            result[provider.definition.name] = _cached_multisource_feature(
                store,
                request,
                {DatasetKind.KLINES: canonical, DatasetKind.FUNDING_RATE: funding},
                provider,
            )
    except DataNotAvailableError:
        pass

    reference_start = request.start - interval_to_timedelta(request.strategy_interval)
    reference_frames: dict[DatasetKind, pd.DataFrame] = {}
    for dataset in (DatasetKind.MARK_PRICE_KLINES, DatasetKind.INDEX_PRICE_KLINES):
        try:
            frame = store.load_dataset(
                _dataset_request(request, dataset, start=reference_start),
                dataset,
                interval=request.strategy_interval,
            )
            if not frame.empty:
                reference_frames[dataset] = frame
        except DataNotAvailableError:
            pass
    if (
        DatasetKind.MARK_PRICE_KLINES in reference_frames
        and DatasetKind.INDEX_PRICE_KLINES in reference_frames
    ):
        try:
            premium = store.load_dataset(
                _dataset_request(
                    request,
                    DatasetKind.PREMIUM_INDEX_KLINES,
                    start=reference_start,
                ),
                DatasetKind.PREMIUM_INDEX_KLINES,
                interval=request.strategy_interval,
            )
            if not premium.empty:
                reference_frames[DatasetKind.PREMIUM_INDEX_KLINES] = premium
        except DataNotAvailableError:
            pass
        provider = BasisContextFeatureProvider()
        result[provider.definition.name] = _cached_multisource_feature(
            store,
            request,
            {DatasetKind.KLINES: canonical, **reference_frames},
            provider,
        )

    if include_agg_trade_flow:
        try:
            agg_trades = store.load_dataset(
                _dataset_request(request, DatasetKind.AGG_TRADES),
                DatasetKind.AGG_TRADES,
            )
            if not agg_trades.empty:
                provider = AggTradeFlowFeatureProvider()
                result[provider.definition.name] = _cached_multisource_feature(
                    store,
                    request,
                    {DatasetKind.KLINES: canonical, DatasetKind.AGG_TRADES: agg_trades},
                    provider,
                )
        except DataNotAvailableError:
            pass
    return result


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
    mean_reversion_mean_type: str = "SMA",
    mean_reversion_bb_stddevs: float = 2.0,
    mean_reversion_rsi_period: int = 14,
    mean_reversion_rsi_oversold: float = 30.0,
    mean_reversion_rsi_overbought: float = 70.0,
    mean_reversion_require_reentry: bool = True,
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
    include_agg_trade_flow: bool = False,
) -> BacktestDataBundle:
    """Load market data and reusable causal feature blocks."""
    if refresh_catalog:
        store.refresh_catalog()

    canonical = store.load_klines(request, request.strategy_interval)
    strategy = _legacy_from_canonical(canonical, request.strategy_interval, "Strategy data (Data Lake v2)")

    registry = production_feature_registry()
    requested = ["production_market_context", "state_transition_daily"]
    if enable_support_resistance_analysis:
        requested.append("support_resistance")
    strategy_minutes = int(interval_to_timedelta(request.strategy_interval).total_seconds() // 60)
    effective_sr_minutes = int(sr_timeframe_minutes or strategy_minutes)
    feature_parameters = {
        CORE_DIRECTIONAL_FEATURE_NAME: {
            "atr_period": int(atr_period), "adx_period": int(adx_period),
            "di_pressure_lookback": int(di_pressure_lookback),
        },
        "production_market_context": {
            "bb_period": int(bb_period),
            "bb_stddevs": float(bb_stddevs),
            "mean_reversion_period": int(mean_reversion_period),
            "mean_reversion_mean_type": str(mean_reversion_mean_type).upper(),
            "mean_reversion_bb_stddevs": float(mean_reversion_bb_stddevs),
            "mean_reversion_rsi_period": int(mean_reversion_rsi_period),
            "mean_reversion_rsi_oversold": float(mean_reversion_rsi_oversold),
            "mean_reversion_rsi_overbought": float(mean_reversion_rsi_overbought),
            "mean_reversion_require_reentry": bool(mean_reversion_require_reentry),
        },
    }
    if enable_support_resistance_analysis:
        feature_parameters["support_resistance"] = {
                "atr_period": int(atr_period),
                "sr_timeframe_minutes": effective_sr_minutes,
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
        }
    frames = registry.execute(
        requested, request, {DatasetKind.KLINES: canonical},
        parameters=feature_parameters, cache=FeatureFrameCache(store.cache.root),
    )
    directional = frames[CORE_DIRECTIONAL_FEATURE_NAME]
    context = frames["production_market_context"]
    sr_features = frames.get("support_resistance")
    state_transition_daily = frames["state_transition_daily"]

    research_features = _optional_futures_research_features(
        store,
        request,
        canonical,
        include_agg_trade_flow=include_agg_trade_flow,
    )

    intrabar = None
    if request.intrabar_interval:
        effective_start = max(request.start, intrabar_start) if intrabar_start else request.start
        intrabar_request = DataRequest(
            symbol=request.symbol, start=effective_start, end=request.end,
            strategy_interval=request.intrabar_interval,
            market=request.market, exchange=request.exchange,
        )
        intrabar = as_searchsorted_intrabar(
            _legacy_from_canonical(
                store.load_execution_klines(intrabar_request, request.intrabar_interval),
                request.intrabar_interval,
                "Intrabar data (Data Lake v2)",
            )
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
        research_features=research_features,
        structural_benchmark=benchmark,
        structural_benchmark_symbol=benchmark_symbol,
        structural_benchmark_interval=benchmark_interval_used,
        state_transition_daily_features=state_transition_daily,
    )
