from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.config import IntrabarMissingPolicy, TiePolicy
from crypto_strategy_lab.data_lake_production_engine import DataLakeProductionBacktestEngine
from crypto_strategy_lab.prepared_backtest import IntrabarExecutionData
from crypto_strategy_lab.research_sampling import StrategyResearchSamplingEngine
from crypto_strategy_lab.trade import ExitReason, Position, Side, TradePair


def _intrabar(*, event_minute: int | None = None, remove_minute: int | None = None):
    timestamps = pd.date_range(
        "2026-01-01T00:00:00Z", periods=60, freq="1min"
    ).to_numpy(dtype="datetime64[ns]")
    opens = np.full(len(timestamps), 100.0)
    highs = np.full(len(timestamps), 100.2)
    lows = np.full(len(timestamps), 99.8)
    if event_minute is not None:
        highs[event_minute] = 101.2
    if remove_minute is not None:
        keep = np.arange(len(timestamps)) != int(remove_minute)
        timestamps, opens, highs, lows = (
            timestamps[keep], opens[keep], highs[keep], lows[keep]
        )
    return IntrabarExecutionData(
        timestamps,
        pd.Timedelta(minutes=1),
        opens,
        highs,
        lows,
    )


def _pair(pair_id: int = 1, *, timeout_minutes: int | None = None):
    position = Position(
        side=Side.LONG,
        entry_time=pd.Timestamp("2026-01-01T00:15:00Z"),
        entry_index=0,
        entry_price=100.0,
        risk=1.0,
        sl=99.0,
        tp=101.0,
        quantity=1.0,
        risk_amount=1.0,
        entry_notional=100.0,
        atr_at_entry=1.0,
        original_sl=99.0,
    )
    pair = TradePair(
        pair_id=pair_id,
        long=position,
        short=None,
        equity_before_trade=1000.0,
        strategy_candle_open_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        strategy_entry_time=pd.Timestamp("2026-01-01T00:15:00Z"),
        strategy_entry_price=100.0,
    )
    pair.profile_timeout_enabled = timeout_minutes is not None
    pair.profile_timeout_minutes = timeout_minutes
    return pair


def _engine(pairs, intrabar, *, telemetry: bool = False):
    engine = object.__new__(StrategyResearchSamplingEngine)
    engine.config = SimpleNamespace(
        use_intrabar_data=True,
        intrabar_timeframe_minutes=1,
        intrabar_missing_policy=IntrabarMissingPolicy.ERROR,
        slippage=0.0,
        tie_policy=TiePolicy.PESSIMISTIC,
        maker_fee=0.0,
        taker_fee=0.0,
        use_maker_exit=False,
        enable_trade_telemetry=telemetry,
    )
    engine.times = pd.date_range(
        "2026-01-01T00:00:00Z", periods=4, freq="15min"
    ).to_numpy(dtype="datetime64[ns]")
    engine.entry_delta = pd.Timedelta(minutes=15)
    engine.intrabar_data = intrabar
    engine.active_pairs = list(pairs)
    engine.completed_pairs = []
    engine.close = np.full(len(engine.times), 100.0)
    engine.missing_intrabar_intervals = []
    engine.fallback_reasons = []
    engine.last_timeout_exit_time = None
    engine.skipped_signals = []
    return engine


def _assert_exit_parity(actual_pair, expected_pair):
    actual = actual_pair.position
    expected = expected_pair.position
    assert actual.exit_reason == expected.exit_reason
    assert actual.exit_source == expected.exit_source
    assert actual.exit_time == expected.exit_time
    assert actual.exit_price == pytest.approx(expected.exit_price)
    assert actual.gross_pnl == pytest.approx(expected.gross_pnl)
    assert actual.net_pnl == pytest.approx(expected.net_pnl)
    assert actual.gross_r == pytest.approx(expected.gross_r)
    assert actual.net_r == pytest.approx(expected.net_r)
    assert actual.price_r == pytest.approx(expected.price_r)
    assert actual.ambiguous == expected.ambiguous


def test_direct_v2_resolves_future_interval_with_native_exit_parity():
    intrabar = _intrabar(event_minute=35)
    expected_pair = _pair()
    actual_pair = _pair()
    expected = _engine([expected_pair], intrabar)
    actual = _engine([actual_pair], intrabar)

    # The mature path must revisit the next strategy interval before it can see
    # the 00:35 event.
    DataLakeProductionBacktestEngine._update_positions_to_strategy_index(expected, 1)
    assert expected_pair.position.is_open
    DataLakeProductionBacktestEngine._update_positions_to_strategy_index(expected, 2)

    # V2 may resolve that independent future event on the first update, but must
    # produce the exact mature exit fields.
    actual._update_positions_to_strategy_index(1)

    _assert_exit_parity(actual_pair, expected_pair)
    assert actual_pair.position.exit_reason == ExitReason.TP
    stats = actual.research_exit_optimization_stats()
    assert stats["research_exit_kernel"] == "DIRECT_SIMPLE_INTRABAR_V2_WITH_V1_FALLBACK"
    assert stats["research_direct_simple_positions"] == 1
    assert stats["research_direct_simple_tp_sl"] == 1
    assert stats["research_batched_simple_position_intervals"] == 0


def test_direct_v2_preserves_end_of_data_close_exactly():
    intrabar = _intrabar()
    expected_pair = _pair()
    actual_pair = _pair()
    expected = _engine([expected_pair], intrabar)
    actual = _engine([actual_pair], intrabar)

    for strategy_index in (1, 2, 3):
        DataLakeProductionBacktestEngine._update_positions_to_strategy_index(
            expected, strategy_index
        )
    expected._force_close_end()

    actual._update_positions_to_strategy_index(1)

    _assert_exit_parity(actual_pair, expected_pair)
    assert actual_pair.position.exit_reason == ExitReason.END_OF_DATA
    stats = actual.research_exit_optimization_stats()
    assert stats["research_direct_simple_end_of_data"] == 1


def test_direct_v2_never_jumps_over_a_future_intrabar_gap():
    # The current 00:15-00:30 window is complete, but a 00:32 gap exists before
    # a would-be 00:35 target. V2 must refuse the horizon shortcut and let V1
    # remain authoritative for the current complete interval.
    intrabar = _intrabar(event_minute=35, remove_minute=32)
    pair = _pair()
    engine = _engine([pair], intrabar)

    engine._update_positions_to_strategy_index(1)

    assert pair.position.is_open
    assert getattr(pair.position, "_research_direct_simple_disabled", False)
    stats = engine.research_exit_optimization_stats()
    assert stats["research_direct_simple_positions"] == 0
    assert stats["research_direct_simple_fallback_positions"] == 1
    assert stats["research_batched_simple_position_intervals"] == 1


def test_direct_v2_is_disabled_when_trade_telemetry_is_enabled():
    intrabar = _intrabar(event_minute=35)
    pair = _pair()
    engine = _engine([pair], intrabar, telemetry=True)

    engine._update_positions_to_strategy_index(1)

    # Closing at the future event now would suppress intermediate telemetry, so
    # the existing per-interval batch path must remain authoritative.
    assert pair.position.is_open
    stats = engine.research_exit_optimization_stats()
    assert stats["research_direct_simple_positions"] == 0
    assert stats["research_batched_simple_position_intervals"] == 1


def test_research_rejections_keep_counts_and_reason_without_rich_snapshot_cost():
    engine = object.__new__(StrategyResearchSamplingEngine)
    engine.skipped_signals = []

    engine._record_skipped_signal(123, "ADX rule rejected")

    assert engine.skipped_signals == [
        {
            "entry_filter_reason": "ADX rule rejected",
            "adx_filter_reason": "ADX rule rejected",
        }
    ]
