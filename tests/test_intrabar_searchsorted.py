from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, RiskMode
from crypto_strategy_lab.data.intrabar_index import SearchsortedIntrabarFrame, as_searchsorted_intrabar
from crypto_strategy_lab.engine import BacktestEngine


def intrabar_frame(periods: int = 180) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="1min")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def strategy_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=8, freq="15min")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def test_searchsorted_frame_matches_boolean_timestamp_ranges() -> None:
    plain = intrabar_frame()
    indexed = as_searchsorted_intrabar(plain)
    assert isinstance(indexed, SearchsortedIntrabarFrame)
    assert indexed.intrabar_index_mode == "searchsorted"

    for start, end in (
        ("2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"),
        ("2026-01-01T00:15:00Z", "2026-01-01T01:00:00Z"),
        ("2026-01-01T01:07:00Z", "2026-01-01T01:53:00Z"),
        ("2026-01-01T02:59:00Z", "2026-01-01T03:30:00Z"),
    ):
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        expected = plain[(plain.timestamp >= start_ts) & (plain.timestamp < end_ts)].reset_index(drop=True)
        actual = indexed[(indexed.timestamp >= start_ts) & (indexed.timestamp < end_ts)].reset_index(drop=True)
        assert type(actual) is pd.DataFrame
        pdt.assert_frame_equal(actual, expected)

    assert indexed.timestamp.max() == plain.timestamp.max()


def test_engine_reset_index_preserves_searchsorted_acceleration() -> None:
    indexed = as_searchsorted_intrabar(intrabar_frame())
    reset = indexed.reset_index(drop=True)
    assert isinstance(reset, SearchsortedIntrabarFrame)
    assert reset.intrabar_index_mode == "searchsorted"
    start = pd.Timestamp("2026-01-01T00:30:00Z")
    end = pd.Timestamp("2026-01-01T00:45:00Z")
    assert len(reset[(reset.timestamp >= start) & (reset.timestamp < end)]) == 15


def test_unsorted_intrabar_falls_back_without_changing_rows() -> None:
    plain = intrabar_frame(10).iloc[[0, 2, 1, 3, 4, 5, 6, 7, 8, 9]].reset_index(drop=True)
    indexed = as_searchsorted_intrabar(plain)
    assert isinstance(indexed, SearchsortedIntrabarFrame)
    assert indexed.intrabar_index_mode == "boolean_fallback"
    start = pd.Timestamp("2026-01-01T00:01:00Z")
    end = pd.Timestamp("2026-01-01T00:04:00Z")
    expected = plain[(plain.timestamp >= start) & (plain.timestamp < end)]
    actual = indexed[(indexed.timestamp >= start) & (indexed.timestamp < end)]
    pdt.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True))


def _engine(intrabar: pd.DataFrame) -> BacktestEngine:
    config = BacktestConfig(
        strategy_timeframe_minutes=15,
        intrabar_timeframe_minutes=1,
        telemetry_interval_minutes=15,
        use_intrabar_data=True,
        intrabar_missing_policy=IntrabarMissingPolicy.ERROR,
        risk_mode=RiskMode.FIXED,
        fixed_r=1.0,
        atr_period=2,
        adx_period=2,
        bb_period=2,
        mean_reversion_period=2,
        entry_mode=EntryMode.EVERY_N_CANDLES,
        max_active_pairs=1,
        maker_fee=0.0,
        taker_fee=0.0,
        slippage=0.0,
        enable_trade_telemetry=False,
        market_regime_method="ASSET_RETURN",
        bull_regime_lookback_days=1,
    )
    engine = BacktestEngine(strategy_frame(), config, intrabar)
    engine.market_regime_values[:] = "SIDEWAYS"
    engine.plus_di_values[:] = 50.0
    engine.minus_di_values[:] = 10.0
    engine.di_spread[:] = 40.0
    engine.di_ratio[:] = 5.0
    return engine


def test_searchsorted_wrapper_preserves_intrabar_trade_results() -> None:
    plain = intrabar_frame()
    # Force one clear TP inside each scanned 15-minute window while retaining
    # complete minute coverage. The engine should therefore make identical
    # stateful decisions regardless of how the window was selected.
    for minute in (20, 50, 80, 110):
        plain.loc[minute, "high"] = 103.0

    legacy = _engine(plain.copy()).run().reset_index(drop=True)
    indexed = _engine(as_searchsorted_intrabar(plain.copy())).run().reset_index(drop=True)

    assert not legacy.empty
    columns = [
        "side",
        "strategy_candle_open_time",
        "strategy_entry_time",
        "entry_time",
        "exit_time",
        "long_exit_reason",
        "long_exit_source",
        "pair_net_pnl",
        "pair_net_r",
        "equity_after_trade",
    ]
    pdt.assert_frame_equal(indexed[columns], legacy[columns], check_dtype=False)
