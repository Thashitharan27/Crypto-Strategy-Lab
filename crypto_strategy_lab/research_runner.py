"""Composition-based application service for validated Data Lake research."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from .data.backtest_service import BacktestDataBundle, load_backtest_bundle
from .prepared_backtest import from_data_lake_bundle, intrabar_from_data_lake_bundle
from .prepared_cache import bundle_prepared_identity
from .research_adapters import native_simulator_config


class Simulator(Protocol):
    def run(self, prepared, intrabar, strategy, execution_config, *, native_config): ...


class Reporter(Protocol):
    def report(self, result: "ResearchRunResult", context: "ResearchRunContext") -> None: ...


@dataclass(frozen=True)
class ResearchRunContext:
    config: Any
    bundle: BacktestDataBundle


@dataclass(frozen=True)
class ResearchRunResult:
    request: Any
    trades: pd.DataFrame
    prepared_cache_hit: bool
    prepared_cache_key: str
    feature_cache_metadata: Mapping[str, Any]
    canonical_cache_metadata: Mapping[str, Any]
    strategy_rows: int
    intrabar_rows: int
    prepared_rows: int
    stage_timings: Mapping[str, float]
    output_dir: Path | None = None


class ResearchRunner:
    """Coordinates dependencies; it contains no market-feature or fill formulas."""
    def __init__(self, data_store, feature_registry, prepared_cache, strategy, simulator,
                 reporters: Sequence[Reporter] = ()):
        self.data_store = data_store
        self.feature_registry = feature_registry
        self.prepared_cache = prepared_cache
        self.strategy = strategy
        self.simulator = simulator
        self.reporters = tuple(reporters)

    def run(self, request, run_config, *, refresh_catalog=True, intrabar_start=None):
        run_config.validate(request)
        native = native_simulator_config(run_config)
        timings = {}
        before = dict(getattr(self.data_store, "canonical_cache_events", {}))
        started = time.perf_counter()
        f = run_config.features
        bundle = load_backtest_bundle(
            self.data_store, request, refresh_catalog=refresh_catalog,
            intrabar_start=intrabar_start, feature_registry=self.feature_registry,
            market_regime_method=f.market_regime_method,
            structural_regime_sma_days=f.structural_regime_sma_days,
            structural_regime_slope_lookback_days=f.structural_regime_slope_lookback_days,
            atr_period=f.atr_period, adx_period=f.adx_period,
            di_pressure_lookback=f.di_pressure_lookback, bb_period=f.bb_period,
            bb_stddevs=f.bb_stddevs, mean_reversion_period=f.mean_reversion_period,
            mean_reversion_mean_type=f.mean_reversion_mean_type,
            mean_reversion_bb_stddevs=f.mean_reversion_bb_stddevs,
            mean_reversion_rsi_period=f.mean_reversion_rsi_period,
            mean_reversion_rsi_oversold=f.mean_reversion_rsi_oversold,
            mean_reversion_rsi_overbought=f.mean_reversion_rsi_overbought,
            mean_reversion_require_reentry=f.mean_reversion_require_reentry,
            enable_support_resistance_analysis=f.enable_support_resistance_analysis,
            sr_timeframe_minutes=f.sr_timeframe_minutes, sr_pivot_left=f.sr_pivot_left,
            sr_pivot_right=f.sr_pivot_right, sr_lookback_bars=f.sr_lookback_bars,
            sr_zone_width_atr=f.sr_zone_width_atr, sr_near_distance_atr=f.sr_near_distance_atr,
            enable_sr_hold_confirmation=f.enable_sr_hold_confirmation,
            sr_hold_confirmation_bars=f.sr_hold_confirmation_bars,
            sr_hold_confirmation_atr=f.sr_hold_confirmation_atr,
            sr_break_tolerance_atr=f.sr_break_tolerance_atr, sr_break_basis=f.sr_break_basis,
            include_agg_trade_flow=f.include_agg_trade_flow)
        timings["data_features"] = time.perf_counter() - started
        started = time.perf_counter()
        key, provenance = bundle_prepared_identity(self.prepared_cache, bundle, native,
                                                    feature_registry=self.feature_registry)
        prepared, hit = self.prepared_cache.get_or_build(
            key, lambda: from_data_lake_bundle(bundle, native)[0], provenance=provenance)
        intrabar = intrabar_from_data_lake_bundle(bundle)
        if intrabar is not None: intrabar.validate_compatible(prepared)
        timings["prepared_cache"] = time.perf_counter() - started
        started = time.perf_counter()
        policy = self.strategy.bind(prepared, run_config.strategy)
        trades = self.simulator.run(prepared, intrabar, policy, run_config.execution,
                                    native_config=native)
        timings["simulation"] = time.perf_counter() - started
        frames = {"core_directional": bundle.technical_features,
                  "production_market_context": bundle.context_features}
        if bundle.support_resistance_features is not None:
            frames["support_resistance"] = bundle.support_resistance_features
        frames.update(bundle.research_features)
        features = {name: {"cache_hit": bool(frame.attrs.get("feature_cache_hit", False)),
                           "cache_key": frame.attrs.get("feature_cache_key"), "rows": len(frame)}
                    for name, frame in frames.items()}
        after = dict(getattr(self.data_store, "canonical_cache_events", {}))
        canonical = {k: int(after.get(k, 0) - before.get(k, 0)) for k in set(before) | set(after)}
        result = ResearchRunResult(request, trades, hit, key, features, canonical,
                                   len(bundle.strategy), len(bundle.intrabar) if bundle.intrabar is not None else 0,
                                   len(prepared), timings)
        report_started = time.perf_counter()
        context = ResearchRunContext(run_config, bundle)
        for reporter in self.reporters: reporter.report(result, context)
        timings["reporting"] = time.perf_counter() - report_started
        return result

