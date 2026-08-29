from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import crypto_strategy_lab.research_adapters as adapters
from crypto_strategy_lab.data import (
    DataQualityStatus,
    DatasetQualityReport,
    DatasetKind,
    MarketKind,
)
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.gui.v2_controller import (
    GuiApplicationService,
    GuiResearchRequest,
)
from crypto_strategy_lab.research_adapters import (
    BoundNativeStrategyPolicy,
    NativeSimulator,
)
from crypto_strategy_lab.research_runner import _simulator_stage_timings


def _ok_quality_report(request, dataset, interval, required):
    return DatasetQualityReport(
        dataset=dataset.value,
        symbol=request.symbol,
        interval=interval,
        required=required,
        requested_start=request.start.isoformat(),
        requested_end=request.end.isoformat(),
        observed_start=request.start.isoformat(),
        observed_end=request.end.isoformat(),
        complete_start=request.start.isoformat(),
        complete_end=request.end.isoformat(),
        row_count=1,
        source_identity="test-source",
        status=DataQualityStatus.OK,
        issues=(),
    )


def test_native_simulator_detaches_rejection_attrs_before_signal_capture(monkeypatch):
    rejected = [{"reason": "TEST"} for _ in range(5000)]

    class FakeEngine:
        telemetry_rows = ()

        def __init__(self):
            self.skipped_signals = rejected

        def run(self):
            trades = pd.DataFrame()
            trades.attrs["skipped_signals"] = self.skipped_signals
            return trades

    engine = FakeEngine()

    class FakeEngineFactory:
        @classmethod
        def from_prepared(cls, prepared, intrabar, native_config):
            return engine

    monkeypatch.setattr(
        adapters,
        "RuleAwareDataLakeProductionBacktestEngine",
        FakeEngineFactory,
    )
    monkeypatch.setattr(
        adapters,
        "native_simulator_config",
        lambda *args, **kwargs: object(),
    )

    observed = {}

    def fake_signal_frame(prepared, trades, skipped_signals):
        observed["attrs_detached"] = "skipped_signals" not in trades.attrs
        observed["same_rejection_list"] = skipped_signals is rejected
        observed["rejection_count"] = len(skipped_signals)
        return pd.DataFrame()

    monkeypatch.setattr(adapters, "_signal_frame", fake_signal_frame)
    monkeypatch.setattr(
        adapters,
        "enrich_bayesian_trade_probabilities",
        lambda trades: trades,
    )

    simulator = NativeSimulator()
    result = simulator.run(
        prepared=None,
        intrabar=None,
        strategy=BoundNativeStrategyPolicy(config=object()),
        execution_config=object(),
        data_config=object(),
        feature_config=object(),
    )

    assert result.empty
    assert observed == {
        "attrs_detached": True,
        "same_rejection_list": True,
        "rejection_count": 5000,
    }
    assert rejected == []
    assert simulator.last_adapter_setup_seconds >= 0.0
    assert simulator.last_engine_init_seconds >= 0.0
    assert simulator.last_simulation_seconds >= 0.0
    assert simulator.last_signal_capture_seconds >= 0.0
    assert simulator.last_bayesian_seconds >= 0.0
    assert simulator.last_adapter_cleanup_seconds >= 0.0


def test_simulator_stage_timings_expose_post_engine_costs():
    simulator = SimpleNamespace(
        last_adapter_setup_seconds=0.1,
        last_engine_init_seconds=0.2,
        last_simulation_seconds=0.3,
        last_signal_capture_seconds=0.4,
        last_bayesian_seconds=0.5,
        last_adapter_cleanup_seconds=0.1,
    )

    timings = _simulator_stage_timings(simulator, 2.0)

    assert timings["simulator_setup"] == pytest.approx(0.1)
    assert timings["engine_init"] == pytest.approx(0.2)
    assert timings["simulation"] == pytest.approx(0.3)
    assert timings["signal_capture"] == pytest.approx(0.4)
    assert timings["bayesian_enrichment"] == pytest.approx(0.5)
    assert timings["simulator_cleanup"] == pytest.approx(0.1)
    assert timings["simulator_unattributed"] == pytest.approx(0.4)
    assert timings["strategy_simulation_total"] == pytest.approx(2.0)


def test_gui_run_reuses_recent_validated_catalog_snapshot_once(tmp_path):
    class FakeStore:
        def __init__(self):
            self.progress_callback = None
            self.refresh_count = 0

        def refresh_catalog(self):
            self.refresh_count += 1
            return 123

        def data_quality_report(
            self,
            request,
            dataset,
            *,
            interval=None,
            required=True,
            **kwargs,
        ):
            assert dataset is DatasetKind.KLINES
            return _ok_quality_report(request, dataset, interval, required)

    class FakeRunner:
        def __init__(self):
            self.refresh_flags = []

        def run(self, request, config, *, refresh_catalog=True, **kwargs):
            self.refresh_flags.append(bool(refresh_catalog))
            return "completed"

    runner = FakeRunner()
    service = object.__new__(GuiApplicationService)
    service.raw_root = tmp_path / "raw"
    service.cache_root = tmp_path / "cache"
    service.store = FakeStore()
    service.catalog = SimpleNamespace()
    service.completed_runs = SimpleNamespace()
    service._runner_factory = lambda output_root: runner
    service.progress_callback = None
    service._catalog_generation = 0
    service._validated_catalog_snapshot = None

    request = GuiResearchRequest(
        exchange="binance",
        market=MarketKind.FUTURES_UM,
        symbol="BTCUSDT",
        period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2024, 2, 1, tzinfo=timezone.utc),
        strategy_timeframe="4h",
        intrabar_timeframe=None,
    )
    config = ResearchRunConfig()

    assert service.refresh_catalog() == 123
    report = service.required_data_quality(request)
    assert report.overall_status is DataQualityStatus.OK

    assert service.run(request, config) == "completed"
    assert runner.refresh_flags == [False]

    # The validation snapshot is deliberately one-shot. A second run must use
    # normal discovery unless Setup validates the request again.
    assert service.run(request, config) == "completed"
    assert runner.refresh_flags == [False, True]
