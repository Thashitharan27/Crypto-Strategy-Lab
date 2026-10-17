"""B2 frozen-input parity through the existing ResearchRunner orchestration.

The Data Lake bundle and reporter are isolated fixtures; the native BacktestEngine
executes the trades. Original source archives and production manifest parity are
reserved for consolidated Windows certification.
"""
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
from pandas.testing import assert_frame_equal
from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService, GuiResearchRequest
from crypto_strategy_lab.research_runner import ResearchRunner
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile
import crypto_strategy_lab.research_runner as runner_module


def test_research_runner_artifact_parity_direct_native_vs_guarded_http(tmp_path, monkeypatch):
    output = tmp_path / "approved"
    output.mkdir()
    (tmp_path / "raw").mkdir()
    candles = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
        "open": [100.0, 100.0], "high": [101.0, 111.0],
        "low": [99.0, 99.0], "close": [100.0, 100.0], "volume": [1, 1],
    })
    frozen = candles.copy(deep=True)
    config = replace(ResearchRunConfig(), data=replace(
        ResearchRunConfig().data, use_intrabar_data=True,
    ))
    engine_config = BacktestConfig(
        risk_mode=RiskMode.FIXED, fixed_r=10,
        initial_equity=1000, risk_per_leg=0.01,
        taker_fee=0.001, maker_fee=0, slippage=0,
        tie_policy=TiePolicy.OPTIMISTIC,
        entry_mode=EntryMode.WAIT_UNTIL_CLOSED,
        use_intrabar_data=False, enable_trade_telemetry=False,
        strategy_profiles={
            key: StrategyProfile(enabled=True, stop_loss_multiple=1, reward_risk_ratio=1)
            for key in PROFILE_KEYS
        },
    )

    class Cache:
        def get_or_build(self, key, builder, *, provenance):
            return builder(), False

    class Strategy:
        def bind(self, prepared, strategy_config):
            return "native policy"

    class Simulator:
        def run(self, prepared, intrabar, policy, execution_config, **kwargs):
            assert policy == "native policy"
            engine = BacktestEngine(prepared.copy(deep=True), engine_config)
            engine.market_regime_values[:] = "SIDEWAYS"
            engine.plus_di_values[:] = 50
            engine.minus_di_values[:] = 10
            engine.di_spread[:] = 40
            return engine.run()

    class Reporter:
        def __init__(self, target):
            self.path = target
        def report(self, result, context):
            assert context.config.reporting.output_dir == str(output)
            # Isolated deterministic serialization; not the production manifest reporter.
            result.trades.to_csv(self.path, index=False)

    records = []
    def load_bundle(store, request, **kwargs):
        records.append((request, kwargs["research_start"], kwargs["feature_config"]))
        def feature(name):
            frame = pd.DataFrame({"value": [1, 2]})
            frame.attrs.update(feature_cache_key=name, feature_cache_hit=False)
            return frame
        return type("Bundle", (), {
            "strategy": candles.copy(deep=True),
            "intrabar": None,
            "technical_features": feature("directional"),
            "context_features": feature("context"),
            "support_resistance_features": None,
            "state_transition_daily_features": None,
            "research_features": {},
        })()

    monkeypatch.setattr(runner_module, "load_backtest_bundle", load_bundle)
    monkeypatch.setattr(runner_module, "bundle_prepared_identity",
                        lambda *args, **kwargs: ("frozen-key", {"fixture": "frozen"}))
    monkeypatch.setattr(runner_module, "from_data_lake_bundle",
                        lambda bundle, policy: (bundle.strategy.copy(deep=True), None))
    monkeypatch.setattr(runner_module, "intrabar_from_data_lake_bundle",
                        lambda bundle: None)

    def native_service(target):
        service = GuiApplicationService(tmp_path / "raw", tmp_path / "cache")
        service._runner_factory = lambda root: ResearchRunner(
            service.store, object(), Cache(), Strategy(), Simulator(), (Reporter(target),),
        )
        return service

    request = GuiResearchRequest(
        exchange="binance", market="futures_um", symbol="BTCUSDT",
        period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        strategy_timeframe="15m", intrabar_timeframe="1m",
    )
    direct = native_service(tmp_path / "desktop.csv").run(
        request, bind_guarded_output_root(config, output),
    )

    integration = BrowserGuardedIntegration(
        native_service(tmp_path / "browser.csv"), tmp_path,
        enabled=True, execution_root=output,
    )
    token = "h" * 48
    app = create_browser_app(
        token=token, guarded_integration=integration, guarded_enabled=True,
    )
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/guarded/jobs",
                headers={"Authorization": "Bearer " + token},
                json={
                    "request_id": "research-runner-parity",
                    "request": {
                        "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
                        "period_start": "2024-01-01T00:00:00Z",
                        "period_end": "2024-01-02T00:00:00Z",
                        "strategy_timeframe": "15m", "intrabar_timeframe": "1m",
                    },
                    "config": config.to_dict(),
                },
            )
            assert response.status_code == 202, response.text
            browser = integration._jobs.result("research-runner-parity").result(timeout=10)
            assert client.get(
                "/api/v1/guarded/jobs/research-runner-parity",
                headers={"Authorization": "Bearer " + token},
            ).json()["status"] == "COMPLETED"
    finally:
        integration.close()

    assert_frame_equal(direct.trades, browser.trades, check_exact=True)
    assert len(direct.trades) == 2
    assert direct.trades.iloc[0].long_exit_reason == "TP"
    assert direct.trades.iloc[1].long_exit_reason == "END_OF_DATA"
    assert (tmp_path / "desktop.csv").read_bytes() == (tmp_path / "browser.csv").read_bytes()
    assert direct.prepared_cache_key == browser.prepared_cache_key == "frozen-key"
    assert direct.strategy_rows == browser.strategy_rows == 2
    assert direct.prepared_rows == browser.prepared_rows == 2
    assert len(records) == 2
    assert records[0][1:] == records[1][1:]
    assert_frame_equal(candles, frozen, check_exact=True)
