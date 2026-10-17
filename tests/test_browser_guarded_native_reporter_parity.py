"""B2 bounded production-reporter parity across native and guarded HTTP paths.

The input bundle/preparation is frozen and injected; native BacktestEngine
performs execution and the genuine BayesianSamplingCsvManifestReporter owns all
publication and native validation. This is not historical Data Lake certification.
"""
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from pandas.testing import assert_frame_equal

from crypto_strategy_lab.bayesian_sampling_reporting import BayesianSamplingCsvManifestReporter
from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root
from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService, GuiResearchRequest, CompletedRunReader
from crypto_strategy_lab.prepared_backtest import PreparedBacktestFrame, _FLOAT_FIELDS, _TEXT_FIELDS
from crypto_strategy_lab.research_adapters import _signal_frame
from crypto_strategy_lab.research_runner import ResearchRunner
from crypto_strategy_lab.run_manifest import artifact_path
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile
import crypto_strategy_lab.research_runner as runner_module


def _prepared(candles):
    times = pd.to_datetime(candles["timestamp"], utc=True).to_numpy(dtype="datetime64[ns]")
    count = len(times)
    values = {name: np.zeros(count, dtype=np.float64) for name in _FLOAT_FIELDS}
    values.update({name: np.array(["NEUTRAL"] * count, dtype=object) for name in _TEXT_FIELDS})
    values.update({
        "timestamp": times,
        "decision_available_at": times + np.timedelta64(15, "m"),
        "strategy_interval": pd.Timedelta("15min"),
        "market_regime": np.array(["SIDEWAYS"] * count, dtype=object),
        "bull_regime_return": np.zeros(count),
        "mean_reversion_strength": np.zeros(count, dtype=np.int64),
        "mean_reversion_long_reentry": np.zeros(count, dtype=np.bool_),
        "mean_reversion_short_reentry": np.zeros(count, dtype=np.bool_),
        "momentum_returns_by_hours": {},
    })
    for name in ("open", "high", "low", "close", "volume"):
        values[name] = candles[name].to_numpy(dtype=np.float64)
    values["atr"] = np.ones(count)
    values["adx"] = np.full(count, 25.0)
    values["plus_di"] = np.full(count, 50.0)
    values["minus_di"] = np.full(count, 10.0)
    assert set(values) == {field.name for field in fields(PreparedBacktestFrame) if field.name != "research"}
    return PreparedBacktestFrame(**values)


def test_production_reporter_manifest_invariants_direct_vs_guarded_http(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    approved.mkdir()
    (tmp_path / "raw").mkdir()
    candles = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
        "open": [100.0, 100.0], "high": [101.0, 111.0],
        "low": [99.0, 99.0], "close": [100.0, 100.0], "volume": [1, 1],
    })
    frozen = candles.copy(deep=True)
    prepared = _prepared(candles)
    config = ResearchRunConfig()
    execution = BacktestConfig(
        risk_mode=RiskMode.FIXED, fixed_r=10, initial_equity=1000,
        risk_per_leg=0.01, taker_fee=0.001, maker_fee=0, slippage=0,
        tie_policy=TiePolicy.OPTIMISTIC, entry_mode=EntryMode.WAIT_UNTIL_CLOSED,
        use_intrabar_data=False, enable_trade_telemetry=False,
        strategy_profiles={
            key: StrategyProfile(enabled=True, stop_loss_multiple=1, reward_risk_ratio=1)
            for key in PROFILE_KEYS
        },
    )

    def frozen_bundle(store, request, **kwargs):
        def feature():
            frame = pd.DataFrame({"value": [1.0, 2.0]})
            frame.attrs["feature_cache_key"] = "frozen"
            return frame
        return type("Bundle", (), {
            "strategy": candles.copy(deep=True), "intrabar": None,
            "technical_features": feature(), "context_features": feature(),
            "support_resistance_features": None,
            "state_transition_daily_features": None, "research_features": {},
        })()

    monkeypatch.setattr(runner_module, "load_backtest_bundle", frozen_bundle)
    monkeypatch.setattr(runner_module, "bundle_prepared_identity",
                        lambda *args, **kwargs: ("prepared-frozen", {"fixture": True}))
    monkeypatch.setattr(runner_module, "from_data_lake_bundle",
                        lambda bundle, policy: (prepared, None))
    monkeypatch.setattr(runner_module, "intrabar_from_data_lake_bundle", lambda _: None)

    class Cache:
        def get_or_build(self, key, builder, *, provenance):
            return builder(), False

    class Strategy:
        def bind(self, frame, settings):
            return "native"

    class Simulator:
        def __init__(self):
            self.last_signals = None
        def run(self, frame, intrabar, policy, settings, **kwargs):
            engine = BacktestEngine(candles.copy(deep=True), execution)
            engine.market_regime_values[:] = "SIDEWAYS"
            engine.plus_di_values[:] = 50
            engine.minus_di_values[:] = 10
            engine.di_spread[:] = 40
            rows = engine.run()
            rows["research_signal_index"] = 1
            rows["research_signal_candle_open_time"] = pd.Timestamp(frame.timestamp[1])
            rows["research_signal_available_at"] = pd.Timestamp(frame.decision_available_at[1])
            self.last_signals = _signal_frame(frame, rows, ())
            return rows

    def service():
        app = GuiApplicationService(tmp_path / "raw", tmp_path / "cache")
        app._runner_factory = lambda output_root: ResearchRunner(
            app.store, object(), Cache(), Strategy(), Simulator(),
            (BayesianSamplingCsvManifestReporter(output_root),),
        )
        return app

    request = GuiResearchRequest(
        exchange="binance", market="futures_um", symbol="BTCUSDT",
        period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        strategy_timeframe="15m", intrabar_timeframe="1m",
    )
    direct = service().run(request, bind_guarded_output_root(config, approved))

    integration = BrowserGuardedIntegration(
        service(), tmp_path, enabled=True, execution_root=approved,
    )
    token = "t" * 48
    browser_app = create_browser_app(
        token=token, guarded_integration=integration, guarded_enabled=True,
    )
    try:
        with TestClient(browser_app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/guarded/jobs",
                headers={"Authorization": "Bearer " + token},
                json={
                    "request_id": "production-report-parity",
                    "request": {
                        "exchange": "binance", "market": "futures_um",
                        "symbol": "BTCUSDT",
                        "period_start": "2024-01-01T00:00:00Z",
                        "period_end": "2024-01-02T00:00:00Z",
                        "strategy_timeframe": "15m", "intrabar_timeframe": "1m",
                    },
                    "config": config.to_dict(),
                },
            )
            assert response.status_code == 202, response.text
            browser = integration._jobs.result("production-report-parity").result(timeout=30)
            assert client.get(
                "/api/v1/guarded/jobs/production-report-parity",
                headers={"Authorization": "Bearer " + token},
            ).json()["status"] == "COMPLETED"
    finally:
        integration.close()

    assert_frame_equal(direct.trades, browser.trades, check_exact=True)
    assert direct.output_dir != browser.output_dir
    native_reader = CompletedRunReader()
    first, first_summary = native_reader.read(direct.output_dir)
    second, second_summary = native_reader.read(browser.output_dir)
    assert first_summary == second_summary
    for section in ("request", "hashes", "prepared", "config", "catalog"):
        assert first[section] == second[section]
    assert first["execution_result"]["trade_fingerprint"] == second["execution_result"]["trade_fingerprint"]
    assert first["research"]["trade_fingerprint"] == second["research"]["trade_fingerprint"]
    assert set(first["artifacts"]) == set(second["artifacts"])
    for name in first["artifacts"]:
        left = artifact_path(direct.output_dir, first, name, verify=True)
        right = artifact_path(browser.output_dir, second, name, verify=True)
        if name in ("trades", "feature_context", "trade_csv", "signals", "summary"):
            assert left.read_bytes() == right.read_bytes(), name
    for result in (direct, browser):
        assert verify_recovered_run(approved, Path(result.output_dir).name)["status"] == "ARTIFACTS_VERIFIED"
    assert_frame_equal(candles, frozen, check_exact=True)
