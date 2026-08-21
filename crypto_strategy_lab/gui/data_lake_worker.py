"""GUI worker adapter for Data Lake v2 market data and prepared features.

The mature reporting/output pipeline remains in place while market data and
stateless context are prepared once through the Data Lake before simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import traceback

from PySide6.QtCore import Slot

from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data.backtest_service import BacktestDataBundle, load_backtest_bundle
from crypto_strategy_lab.data_lake_engine import DataLakeBacktestEngine
from crypto_strategy_lab.state_transition_research import generate_state_transition_reports
from crypto_strategy_lab.gui import worker as worker_module
from crypto_strategy_lab.gui.worker import BacktestWorker


@dataclass(frozen=True, slots=True)
class DataLakeGuiRunSpec:
    """Runtime-only market-data selection passed from the GUI to the worker."""

    raw_root: Path
    cache_root: Path
    symbol: str
    start: datetime
    end: datetime
    intrabar_start: datetime | None = None
    refresh_catalog: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_root", Path(self.raw_root))
        object.__setattr__(self, "cache_root", Path(self.cache_root))
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        if not self.symbol:
            raise ValueError("Data Lake GUI symbol must not be empty")
        if self.start >= self.end:
            raise ValueError("Data Lake GUI start must be before end")


class DataLakeGuiBacktestWorker(BacktestWorker):
    """Existing GUI/report worker with Data Lake market data and feature inputs."""

    def __init__(self, config, run_spec: DataLakeGuiRunSpec):
        super().__init__(config, strategy_data=None)
        self.run_spec = run_spec
        self.data_bundle: BacktestDataBundle | None = None
        self.finished.connect(self._write_data_lake_metadata_and_research)

    def _prepare_bundle(self) -> BacktestDataBundle:
        strategy_interval = f"{int(self.config.strategy_timeframe_minutes)}m"
        intrabar_interval = (
            f"{int(self.config.intrabar_timeframe_minutes)}m"
            if self.config.use_intrabar_data else None
        )
        request = DataRequest(
            symbol=self.run_spec.symbol,
            start=self.run_spec.start,
            end=self.run_spec.end,
            strategy_interval=strategy_interval,
            intrabar_interval=intrabar_interval,
        )
        store = MarketDataStore(self.run_spec.raw_root, self.run_spec.cache_root)
        return load_backtest_bundle(
            store,
            request,
            market_regime_method=self.config.market_regime_method,
            structural_regime_sma_days=self.config.structural_regime_sma_days,
            structural_regime_slope_lookback_days=self.config.structural_regime_slope_lookback_days,
            refresh_catalog=self.run_spec.refresh_catalog,
            intrabar_start=self.run_spec.intrabar_start,
            atr_period=self.config.atr_period,
            adx_period=self.config.adx_period,
            di_pressure_lookback=self.config.di_pressure_lookback,
            bb_period=self.config.bb_period,
            bb_stddevs=self.config.bb_stddevs,
            mean_reversion_period=self.config.mean_reversion_period,
        )

    @Slot()
    def run(self) -> None:
        try:
            self._emit_stage("Loading Binance Data Lake", 0)
            self.data_bundle = self._prepare_bundle()
            bundle = self.data_bundle
            directional = bundle.technical_features
            context = bundle.context_features
            self._log(
                f"Data Lake source: {self.run_spec.symbol} | "
                f"strategy={bundle.request.strategy_interval} ({len(bundle.strategy):,} rows) | "
                f"intrabar={bundle.request.intrabar_interval or 'disabled'} "
                f"({len(bundle.intrabar) if bundle.intrabar is not None else 0:,} rows)"
            )
            self._log(
                f"Prepared features: {directional.attrs.get('feature_name')}@"
                f"{directional.attrs.get('feature_version')} "
                f"(cache={'hit' if directional.attrs.get('feature_cache_hit') else 'miss'}), "
                f"{context.attrs.get('feature_name')}@{context.attrs.get('feature_version')} "
                f"(cache={'hit' if context.attrs.get('feature_cache_hit') else 'miss'})"
            )
            if bundle.structural_benchmark is not None:
                self._log(
                    f"Structural benchmark: {bundle.structural_benchmark_symbol} "
                    f"{bundle.structural_benchmark_interval} "
                    f"({len(bundle.structural_benchmark):,} rows)"
                )
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
            return

        original_loader = worker_module.load_backtest_data
        original_engine = worker_module.BacktestEngine
        benchmark = bundle.structural_benchmark
        technical_features = bundle.technical_features
        context_features = bundle.context_features

        def prepared_loader(_config, _strategy_data=None):
            return bundle.strategy, bundle.intrabar

        class BoundDataLakeEngine(DataLakeBacktestEngine):
            def __init__(self, *args, **kwargs):
                kwargs["structural_benchmark"] = benchmark
                kwargs["technical_features"] = technical_features
                kwargs["context_features"] = context_features
                super().__init__(*args, **kwargs)

        worker_module.load_backtest_data = prepared_loader
        worker_module.BacktestEngine = BoundDataLakeEngine
        try:
            super().run()
        finally:
            worker_module.load_backtest_data = original_loader
            worker_module.BacktestEngine = original_engine

    @staticmethod
    def _feature_manifest(frame):
        return {
            "name": frame.attrs.get("feature_name"),
            "version": frame.attrs.get("feature_version"),
            "rows": len(frame),
            "cache_hit": bool(frame.attrs.get("feature_cache_hit", False)),
            "cache_key": frame.attrs.get("feature_cache_key"),
            "effective_warmup_bars": frame.attrs.get("effective_warmup_bars"),
        }

    @Slot(dict, object, object, object)
    def _write_data_lake_metadata_and_research(self, summary, trades, _equity, run_dir) -> None:
        if self.data_bundle is None:
            return
        run_dir = Path(run_dir)
        bundle = self.data_bundle
        request = bundle.request
        directional = bundle.technical_features
        context = bundle.context_features
        try:
            summary.update(
                {
                    "data_source": "binance_data_lake_v2",
                    "market_symbol": request.symbol,
                    "strategy_interval": request.strategy_interval,
                    "intrabar_interval": request.intrabar_interval,
                    "data_request_start": request.start.isoformat(),
                    "data_request_end": request.end.isoformat(),
                    "technical_feature_name": directional.attrs.get("feature_name"),
                    "technical_feature_version": directional.attrs.get("feature_version"),
                    "context_feature_name": context.attrs.get("feature_name"),
                    "context_feature_version": context.attrs.get("feature_version"),
                }
            )
            (run_dir / "summary.json").write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )
            directional_manifest = self._feature_manifest(directional)
            directional_manifest.update(
                atr_period=directional.attrs.get("atr_period"),
                adx_period=directional.attrs.get("adx_period"),
                di_pressure_lookback=directional.attrs.get("di_pressure_lookback"),
            )
            context_manifest = self._feature_manifest(context)
            context_manifest.update(
                bb_period=context.attrs.get("bb_period"),
                bb_stddevs=context.attrs.get("bb_stddevs"),
                mean_reversion_period=context.attrs.get("mean_reversion_period"),
            )
            manifest = {
                "data_source": "binance_data_lake_v2",
                "raw_root": str(self.run_spec.raw_root.resolve()),
                "cache_root": str(self.run_spec.cache_root.resolve()),
                "request": {
                    "symbol": request.symbol,
                    "start": request.start.isoformat(),
                    "end": request.end.isoformat(),
                    "strategy_interval": request.strategy_interval,
                    "intrabar_interval": request.intrabar_interval,
                    "intrabar_start": (
                        self.run_spec.intrabar_start.isoformat()
                        if self.run_spec.intrabar_start is not None else None
                    ),
                },
                "strategy_rows": len(bundle.strategy),
                "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
                "features": {
                    "core_directional": directional_manifest,
                    "market_context": context_manifest,
                },
                "structural_benchmark_symbol": bundle.structural_benchmark_symbol,
                "structural_benchmark_interval": bundle.structural_benchmark_interval,
                "benchmark_rows": (
                    len(bundle.structural_benchmark)
                    if bundle.structural_benchmark is not None else 0
                ),
                "trade_rows": len(trades),
            }
            (run_dir / "run_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            generate_state_transition_reports(bundle.strategy, trades, run_dir)
            self._log("Data Lake manifest and state-transition research reports saved")
        except Exception as exc:
            self._log(f"WARNING: Data Lake post-run metadata/research failed: {exc}")
