"""GUI worker adapter for Data Lake v2 market data and prepared features.

The reporting/output pipeline in :mod:`crypto_strategy_lab.gui.worker` remains
valuable during migration. This adapter prepares market data and causal features
through the Data Lake, then binds the forward ``DataLakeBacktestEngine`` for one
worker run. No CSV market-data filename is resolved by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import traceback

import pandas as pd
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
        # Installed before MainWindow attaches its completion handler, so the
        # manifest/research files normally exist when the GUI refreshes.
        self.finished.connect(self._write_data_lake_metadata_and_research)

    def _prepare_bundle(self) -> BacktestDataBundle:
        strategy_interval = f"{int(self.config.strategy_timeframe_minutes)}m"
        intrabar_interval = (
            f"{int(self.config.intrabar_timeframe_minutes)}m"
            if self.config.use_intrabar_data
            else None
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
        )

    @Slot()
    def run(self) -> None:
        """Prepare Data Lake inputs, then reuse the mature GUI output pipeline."""

        try:
            self._emit_stage("Loading Binance Data Lake", 0)
            self.data_bundle = self._prepare_bundle()
            bundle = self.data_bundle
            self._log(
                f"Data Lake source: {self.run_spec.symbol} | "
                f"strategy={bundle.request.strategy_interval} ({len(bundle.strategy):,} rows) | "
                f"intrabar={bundle.request.intrabar_interval or 'disabled'} "
                f"({len(bundle.intrabar) if bundle.intrabar is not None else 0:,} rows)"
            )
            self._log(
                "Prepared technical features: "
                f"{bundle.technical_features.attrs.get('feature_name', 'core_directional')}@"
                f"{bundle.technical_features.attrs.get('feature_version', 'unknown')} | "
                f"ATR({self.config.atr_period}) ADX/DI({self.config.adx_period}) "
                f"DI pressure lookback={self.config.di_pressure_lookback}"
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

        # BacktestWorker still calls module-level loader/engine hooks. Binding
        # these only for this worker execution lets us reuse its reporting logic
        # while the large legacy worker is progressively decomposed.
        original_loader = worker_module.load_backtest_data
        original_engine = worker_module.BacktestEngine
        benchmark = bundle.structural_benchmark
        technical_features = bundle.technical_features

        def prepared_loader(_config, _strategy_data=None):
            return bundle.strategy, bundle.intrabar

        class BoundDataLakeEngine(DataLakeBacktestEngine):
            def __init__(self, *args, **kwargs):
                kwargs["structural_benchmark"] = benchmark
                kwargs["technical_features"] = technical_features
                super().__init__(*args, **kwargs)

        worker_module.load_backtest_data = prepared_loader
        worker_module.BacktestEngine = BoundDataLakeEngine
        try:
            super().run()
        finally:
            worker_module.load_backtest_data = original_loader
            worker_module.BacktestEngine = original_engine

    @Slot(dict, object, object, object)
    def _write_data_lake_metadata_and_research(self, summary, trades, _equity, run_dir) -> None:
        if self.data_bundle is None:
            return
        run_dir = Path(run_dir)
        bundle = self.data_bundle
        request = bundle.request
        features = bundle.technical_features
        try:
            summary.update(
                {
                    "data_source": "binance_data_lake_v2",
                    "market_symbol": request.symbol,
                    "strategy_interval": request.strategy_interval,
                    "intrabar_interval": request.intrabar_interval,
                    "data_request_start": request.start.isoformat(),
                    "data_request_end": request.end.isoformat(),
                    "technical_feature_name": features.attrs.get("feature_name"),
                    "technical_feature_version": features.attrs.get("feature_version"),
                }
            )
            (run_dir / "summary.json").write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
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
                        if self.run_spec.intrabar_start is not None
                        else None
                    ),
                },
                "strategy_rows": len(bundle.strategy),
                "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
                "technical_features": {
                    "name": features.attrs.get("feature_name"),
                    "version": features.attrs.get("feature_version"),
                    "rows": len(features),
                    "atr_period": features.attrs.get("atr_period"),
                    "adx_period": features.attrs.get("adx_period"),
                    "di_pressure_lookback": features.attrs.get("di_pressure_lookback"),
                    "effective_warmup_bars": features.attrs.get("effective_warmup_bars"),
                },
                "structural_benchmark_symbol": bundle.structural_benchmark_symbol,
                "structural_benchmark_interval": bundle.structural_benchmark_interval,
                "benchmark_rows": (
                    len(bundle.structural_benchmark)
                    if bundle.structural_benchmark is not None
                    else 0
                ),
                "trade_rows": len(trades),
            }
            (run_dir / "run_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            generate_state_transition_reports(bundle.strategy, trades, run_dir)
            self._log("Data Lake manifest and state-transition research reports saved")
        except Exception as exc:
            # The core backtest has already completed. Ancillary metadata must
            # never turn a valid run into a failed run.
            self._log(f"WARNING: Data Lake post-run metadata/research failed: {exc}")
