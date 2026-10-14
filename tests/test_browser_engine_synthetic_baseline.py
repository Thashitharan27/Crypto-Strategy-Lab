"""Deterministic offline engine result baseline (synthetic candles, not history).

Lock a small known trade result before introducing browser service plumbing.
"""
import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def test_existing_di_long_single_trade_baseline():
    candles = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
        "open": [100.0, 100.0],
        "high": [101.0, 111.0],
        "low": [99.0, 99.0],
        "close": [100.0, 100.0],
        "volume": [1, 1],
    })
    config = BacktestConfig(
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
    engine = BacktestEngine(candles, config)
    engine.market_regime_values[:] = "SIDEWAYS"
    engine.plus_di_values[:] = 50
    engine.minus_di_values[:] = 10
    engine.di_spread[:] = 40
    rows = engine.run()
    # WAIT_UNTIL_CLOSED may open a second position on the final candle.
    assert len(rows) == 2
    assert rows.iloc[1].long_exit_reason == "END_OF_DATA"
    row = rows.iloc[0]
    assert row.side == "LONG"
    assert row.entry_price == pytest.approx(100)
    assert row.long_quantity == pytest.approx(1)
    assert row.long_exit_reason == "TP"
    assert row.long_fees == pytest.approx(0.21)
    assert row.pair_net_pnl == pytest.approx(9.79)
    assert row.pair_net_r == pytest.approx(0.979)
    assert row.equity_after_trade == pytest.approx(1009.79)
    assert row.strategy_entry_time == pd.Timestamp("2024-01-01T00:15:00Z")
