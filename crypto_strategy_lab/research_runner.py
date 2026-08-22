"""Composition-based application service for validated Data Lake research."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from .data.backtest_service import BacktestDataBundle, load_backtest_bundle
from .data.timing import normalize_binance_interval
from .data.quality import DataQualityReport
from .prepared_backtest import from_data_lake_bundle, intrabar_from_data_lake_bundle
from .prepared_cache import bundle_prepared_identity
from .research_adapters import prepared_policy_config


class Simulator(Protocol):
    def run(
        self,
        prepared,
        intrabar,
        strategy,
        execution_config,
        *,
        data_config,
        feature_config,
    ): ...


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
    data_quality: DataQualityReport | None = None


class ResearchRunner:
    """Coordinate injected services without owning feature or fill formulas."""

    def __init__(
        self,
        data_store,
        feature_registry,
        prepared_cache,
        strategy,
        simulator,
        reporters: Sequence[Reporter] = (),
    ):
        self.data_store = data_store
        self.feature_registry = feature_registry
        self.prepared_cache = prepared_cache
        self.strategy = strategy
        self.simulator = simulator
        self.reporters = tuple(reporters)

    @staticmethod
    def _validate_request_contract(request, run_config) -> None:
        run_config.validate()
        data = run_config.data
        expected_strategy = normalize_binance_interval(
            f"{int(data.strategy_timeframe_minutes)}m"
        )
        expected_intrabar = (
            normalize_binance_interval(f"{int(data.intrabar_timeframe_minutes)}m")
            if data.use_intrabar_data
            else None
        )
        if request.strategy_interval != expected_strategy:
            raise ValueError("DataRequest strategy interval disagrees with DataConfig")
        if request.intrabar_interval != expected_intrabar:
            raise ValueError("DataRequest intrabar interval disagrees with DataConfig")

    def run(self, request, run_config, *, refresh_catalog=True, intrabar_start=None):
        self._validate_request_contract(request, run_config)
        timings: dict[str, float] = {}
        before = dict(getattr(self.data_store, "canonical_cache_events", {}))

        started = time.perf_counter()
        bundle = load_backtest_bundle(
            self.data_store,
            request,
            refresh_catalog=refresh_catalog,
            intrabar_start=intrabar_start,
            feature_registry=self.feature_registry,
            feature_config=run_config.features,
        )
        timings["data_features"] = time.perf_counter() - started

        # L3 sees only the config projection that is physically materialized in
        # PreparedBacktestFrame. Execution and reporting never participate.
        prepared_policy = prepared_policy_config(run_config)
        started = time.perf_counter()
        key, provenance = bundle_prepared_identity(
            self.prepared_cache,
            bundle,
            prepared_policy,
            feature_registry=self.feature_registry,
        )
        prepared, hit = self.prepared_cache.get_or_build(
            key,
            lambda: from_data_lake_bundle(bundle, prepared_policy)[0],
            provenance=provenance,
        )
        intrabar = intrabar_from_data_lake_bundle(bundle)
        if intrabar is not None:
            intrabar.validate_compatible(prepared)
        timings["prepared_cache"] = time.perf_counter() - started

        policy = self.strategy.bind(prepared, run_config.strategy)
        simulation_started = time.perf_counter()
        trades = self.simulator.run(
            prepared,
            intrabar,
            policy,
            run_config.execution,
            data_config=run_config.data,
            feature_config=run_config.features,
        )
        simulation_total = time.perf_counter() - simulation_started
        engine_init = float(getattr(self.simulator, "last_engine_init_seconds", 0.0) or 0.0)
        simulator_run = getattr(self.simulator, "last_simulation_seconds", None)
        timings["engine_init"] = engine_init
        timings["simulation"] = (
            float(simulator_run) if simulator_run is not None else simulation_total
        )
        timings["strategy_simulation_total"] = simulation_total

        frames = {
            "core_directional": bundle.technical_features,
            "production_market_context": bundle.context_features,
        }
        if bundle.support_resistance_features is not None:
            frames["support_resistance"] = bundle.support_resistance_features
        if bundle.state_transition_daily_features is not None:
            frames["state_transition_daily"] = bundle.state_transition_daily_features
        frames.update(bundle.research_features)
        features = {
            name: {
                "cache_hit": bool(frame.attrs.get("feature_cache_hit", False)),
                "cache_key": frame.attrs.get("feature_cache_key"),
                "rows": len(frame),
            }
            for name, frame in frames.items()
        }
        after = dict(getattr(self.data_store, "canonical_cache_events", {}))
        canonical = {
            name: int(after.get(name, 0) - before.get(name, 0))
            for name in sorted(set(before) | set(after))
        }
        result = ResearchRunResult(
            request=request,
            trades=trades,
            prepared_cache_hit=hit,
            prepared_cache_key=key,
            feature_cache_metadata=features,
            canonical_cache_metadata=canonical,
            strategy_rows=len(bundle.strategy),
            intrabar_rows=len(bundle.intrabar) if bundle.intrabar is not None else 0,
            prepared_rows=len(prepared),
            stage_timings=timings,
            data_quality=getattr(bundle, "data_quality", None),
        )

        report_started = time.perf_counter()
        context = ResearchRunContext(run_config, bundle)
        for reporter in self.reporters:
            reporter.report(result, context)
        timings["reporting"] = time.perf_counter() - report_started
        return result
