"""B2 isolated execution parity through independent desktop and guarded HTTP paths.

Uses the existing BacktestEngine on frozen candles, not a substitute fill model.
Original-file and production Data Lake parity remain separate certification.
"""
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pandas.testing import assert_frame_equal

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root
from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService, GuiResearchRequest
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def _frozen_candles():
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
        "open": [100.0, 100.0],
        "high": [101.0, 111.0],
        "low": [99.0, 99.0],
        "close": [100.0, 100.0],
        "volume": [1, 1],
    })


def _engine_config():
    return BacktestConfig(
        risk_mode=RiskMode.FIXED, fixed_r=10,
        initial_equity=1000, risk_per_leg=0.01,
        taker_fee=0.001, maker_fee=0, slippage=0,
        tie_policy=TiePolicy.OPTIMISTIC,
        entry_mode=EntryMode.WAIT_UNTIL_CLOSED,
        use_intrabar_data=False, enable_trade_telemetry=False,
        strategy_profiles={
            key: StrategyProfile(
                enabled=True, stop_loss_multiple=1, reward_risk_ratio=1,
            ) for key in PROFILE_KEYS
        },
    )


@pytest.mark.parametrize("side,exit_case", [
    ("LONG", "TP"), ("SHORT", "TP"),
    ("LONG", "SL"), ("SHORT", "SL"),
    ("LONG", "TP1_THEN_SL"),
])
def test_frozen_native_trade_rows_match_direct_service_and_guarded_http(tmp_path, side, exit_case):
    root = tmp_path / "guarded-output"
    root.mkdir()
    source = _frozen_candles()
    if side == "SHORT":
        source["high"], source["low"] = 200.0 - source["low"].copy(), 200.0 - source["high"].copy()
    if exit_case == "SL":
        source.loc[1, "high"] = 101.0 if side == "LONG" else 111.0
        source.loc[1, "low"] = 89.0 if side == "LONG" else 99.0
    engine_config = _engine_config()
    if exit_case == "TP1_THEN_SL":
        source = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC"),
            "open": [100.0] * 4, "close": [100.0] * 4,
            "high": [101.0, 101.0, 120.0, 105.0],
            "low": [99.0, 99.0, 99.0, 79.0], "volume": [1] * 4,
        })
        profiles = dict(engine_config.strategy_profiles)
        profiles["sideways_long"] = StrategyProfile(
            enabled=True, stop_loss_multiple=2,
            partial_profit_enabled=True, tp1_r=1,
            tp1_close_pct=50, tp2_r=2,
        )
        engine_config = replace(engine_config, atr_period=1, strategy_profiles=profiles)
    calls = []

    class NativeEngineRunner:
        def run(self, request, config, **kwargs):
            assert request.symbol == "BTCUSDT"
            assert config.reporting.output_dir == str(root)
            engine = BacktestEngine(source.copy(deep=True), engine_config)
            engine.market_regime_values[:] = "SIDEWAYS"
            engine.plus_di_values[:] = 50 if side == "LONG" else 10
            engine.minus_di_values[:] = 10 if side == "LONG" else 50
            engine.di_spread[:] = 40
            result = engine.run()
            calls.append((request, config.to_dict(), result.copy(deep=True)))
            return result

    def native_service():
        return GuiApplicationService(
            tmp_path / "raw", tmp_path / "cache",
            runner_factory=lambda output_root: NativeEngineRunner(),
        )

    base = ResearchRunConfig()
    direct_config = bind_guarded_output_root(base, root)
    request = GuiResearchRequest(
        exchange="binance", market="futures_um", symbol="BTCUSDT",
        period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        strategy_timeframe="4h", intrabar_timeframe="1m",
    )
    direct = native_service().run(request, direct_config)

    guarded = BrowserGuardedIntegration(
        native_service(), tmp_path, enabled=True, execution_root=root,
    )
    token = "b" * 48
    app = create_browser_app(
        token=token, guarded_integration=guarded, guarded_enabled=True,
    )
    payload = {
        "request_id": "frozen-native-" + side.lower() + "-" + exit_case.lower(),
        "request": {
            "exchange": "binance", "market": "futures_um",
            "symbol": "BTCUSDT",
            "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2024-01-02T00:00:00Z",
            "strategy_timeframe": "4h",
            "intrabar_timeframe": "1m",
        },
        "config": base.to_dict(),
    }
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/guarded/jobs",
                json=payload, headers={"Authorization": "Bearer " + token},
            )
            assert response.status_code == 202, response.text
            browser = guarded._jobs.result("frozen-native-" + side.lower() + "-" + exit_case.lower()).result(timeout=10)
            status = client.get(
                "/api/v1/guarded/jobs/frozen-native-" + side.lower() + "-" + exit_case.lower(),
                headers={"Authorization": "Bearer " + token},
            )
            assert status.json() == {
                "request_id": "frozen-native-" + side.lower() + "-" + exit_case.lower(), "status": "COMPLETED",
            }
    finally:
        guarded.close()

    assert len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert calls[0][1] == calls[1][1] == direct_config.to_dict()
    assert_frame_equal(direct, browser, check_exact=True)
    assert len(direct) >= 1 if exit_case == "TP1_THEN_SL" else len(direct) == 2
    assert direct.iloc[0].side == side
    assert direct.iloc[0].strategy_entry_time == pd.Timestamp("2024-01-01T00:15:00Z")
    if side == "LONG":
        assert direct.iloc[0].long_exit_reason == exit_case
        if exit_case == "TP1_THEN_SL":
            assert direct.iloc[0].long_tp1_hit
            assert direct.iloc[0].long_tp1_quantity > 0
            assert direct.iloc[0].long_stop_exit_quantity > 0
            assert direct.iloc[0].long_fees > 0
            assert direct.iloc[0].pair_net_pnl == pytest.approx(
                direct.iloc[0].pair_gross_pnl - direct.iloc[0].pair_total_fees
            )
        if exit_case == "TP":
            assert direct.iloc[0].long_fees == pytest.approx(0.21)
            assert direct.iloc[0].pair_net_pnl == pytest.approx(9.79)
            assert direct.iloc[0].equity_after_trade == pytest.approx(1009.79)
        else:
            assert direct.iloc[0].pair_net_pnl < 0
            assert direct.iloc[0].equity_after_trade < 1000
        if exit_case != "TP1_THEN_SL":
            assert direct.iloc[1].long_exit_reason == "END_OF_DATA"
    else:
        assert direct.iloc[0].short_exit_reason == exit_case
        assert (direct.iloc[0].pair_net_pnl > 0) == (exit_case == "TP")
        assert (direct.iloc[0].equity_after_trade > 1000) == (exit_case == "TP")
        assert direct.iloc[1].short_exit_reason == "END_OF_DATA"
    if side == "LONG" and exit_case == "TP":
        assert_frame_equal(source, _frozen_candles(), check_exact=True)
    elif exit_case == "TP1_THEN_SL":
        assert source.iloc[3]["low"] == 79.0
    else:
        assert source.iloc[1]["low"] == pytest.approx(89.0 if (side == "SHORT" and exit_case == "TP") or (side == "LONG" and exit_case == "SL") else 99.0)
