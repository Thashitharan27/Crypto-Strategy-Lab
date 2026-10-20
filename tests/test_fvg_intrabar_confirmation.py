import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

from crypto_strategy_lab.fair_value_gap import FairValueGapMixin
from crypto_strategy_lab.prepared_backtest import IntrabarExecutionData


class _Base:
    def _entry_decision(self, i, active_at_candle_start=False):
        return {"base": True}

    def _should_enter(self, i):
        return True

    def _record_skipped_signal(self, i, reason):
        self.skipped.append((i, reason))

    def _entry_filter_result(self, indicator_i, execution_i=None):
        return True, "passed"

    def _effective_trade_direction(self, i):
        return self._selected_direction(i)

    def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="passed", schedule=None):
        self.opened.append((i, dict(schedule or {})))

    def _scan_pair_exit(self, pair, i):
        self.scanned.append((pair, i))


class _Probe(FairValueGapMixin, _Base):
    # This fixture isolates the 15m confirmation scheduler. The production
    # FVG target/box validity is covered separately and requires market arrays
    # that are intentionally absent from this narrow scheduling fixture.
    def _fvg_target_plan(self, i, execution_i=None):
        return {"passed": True}


def _probe(closes):
    p = _Probe()
    p.config = SimpleNamespace(
        fvg_confirmation_enabled=True,
        fvg_confirmation_minutes=15,
        intrabar_timeframe_minutes=5,
        strategy_timeframe_minutes=60,
        enable_daily_entry_schedule=False,
        max_active_pairs=1,
        slippage=0.0,
    )
    p.signal_strategy_mode = "FAIR_VALUE_GAP"
    p.times = np.array([
        np.datetime64("2026-01-01T00:00:00"),
        np.datetime64("2026-01-01T01:00:00"),
        np.datetime64("2026-01-01T02:00:00"),
    ])
    intrabar_times = pd.date_range("2026-01-01T01:00:00Z", periods=12, freq="5min")
    opens = np.array([100.0, 101.0, 102.0] + [103.0] * 9)
    highs = np.maximum(opens, np.array(list(closes) + [103.0] * 9))
    lows = np.minimum(opens, np.array(list(closes) + [103.0] * 9))
    full_closes = np.array(list(closes) + [103.0] * 9)
    p.intrabar_data = IntrabarExecutionData(
        intrabar_times, pd.Timedelta(minutes=5), opens, highs, lows, full_closes
    )
    p.fvg_first_revisit = np.array(["LONG", None, None], dtype=object)
    p.active_pairs = []
    p.pending_next_open_entry = None
    p.skipped = []
    p.opened = []
    p.scanned = []
    return p


def test_fvg_confirmation_aggregates_first_intrabar_window_and_uses_close():
    p = _probe([101.0, 102.0, 104.0])
    candle = p._fvg_confirmation_candle(1)
    assert candle["open"] == 100.0
    assert candle["close"] == 104.0
    assert candle["minutes"] == 15
    assert candle["confirmed_at"] == pd.Timestamp("2026-01-01T01:15:00Z")


def test_fvg_confirmation_defers_signal_to_next_strategy_candle():
    p = _probe([101.0, 102.0, 104.0])
    decision = p._entry_decision(0)
    assert decision["indicator_index"] == 0
    assert decision["execution_index"] == 1
    assert decision["fvg_confirmation"] is True
    assert decision["defer_to_next_open"] is True


def test_fvg_long_confirmation_rejects_red_15m_candle():
    p = _probe([99.5, 99.0, 98.0])
    p.pending_next_open_entry = p._entry_decision(0)
    p._execute_pending_next_open_entry(1)
    assert p.opened == []
    assert p.skipped == [(0, "FVG_CONFIRMATION_DIRECTION_MISMATCH")]


def test_fvg_long_confirmation_enters_at_confirmed_15m_close():
    p = _probe([101.0, 102.0, 104.0])
    p.pending_next_open_entry = p._entry_decision(0)
    p._execute_pending_next_open_entry(1)
    assert len(p.opened) == 1
    execution_i, schedule = p.opened[0]
    assert execution_i == 1
    assert schedule["fill_price_source"] == "FVG_INTRABAR_CONFIRMATION"
    assert schedule["fill_price"] == 104.0
    assert schedule["actual_entry_timestamp"] == pd.Timestamp("2026-01-01T01:15:00")


def test_fvg_confirmation_fill_preserves_timezone_aware_strategy_clock():
    p = _probe([101.0, 102.0, 104.0])
    p.times = pd.DatetimeIndex(p.times).tz_localize("UTC").tz_convert("Asia/Colombo")
    p.pending_next_open_entry = p._entry_decision(0)
    p._execute_pending_next_open_entry(1)
    entry = p.opened[0][1]["actual_entry_timestamp"]
    assert entry == pd.Timestamp("2026-01-01T01:15:00Z")
    assert str(entry.tzinfo) == str(p.times.tz)


def test_fvg_five_minute_fill_can_start_naive_array_exit_window():
    p = _probe([101.0, 99.0, 98.0])
    p.config.fvg_confirmation_minutes = 5
    p.pending_next_open_entry = p._entry_decision(0)
    p._execute_pending_next_open_entry(1)
    entry = p.opened[0][1]["actual_entry_timestamp"]
    start = max(entry, pd.Timestamp(p.times[1]))
    assert start == pd.Timestamp("2026-01-01T01:05:00")
    window = p.intrabar_data.fast_window(start, pd.Timestamp(p.times[2]))
    assert window.first_timestamp == start
    assert p.opened[0][1]["fill_price"] == 101.0


@pytest.mark.parametrize("side,first_close,enters", [
    ("LONG", 101.0, True), ("LONG", 99.0, False), ("LONG", 100.0, False),
    ("SHORT", 99.0, True), ("SHORT", 101.0, False), ("SHORT", 100.0, False),
])
def test_first_minute_confirmation_does_not_wait_for_a_later_candle(side, first_close, enters):
    p = _probe([101.0, 102.0, 104.0])
    p.config.strategy_timeframe_minutes = 15
    p.config.intrabar_timeframe_minutes = 1
    p.config.fvg_confirmation_minutes = 1
    p._selected_direction = lambda i: side
    times = pd.date_range("2026-01-01T01:00:00Z", periods=15, freq="1min")
    closes = np.array([first_close] + ([105.0] * 14 if side == "LONG" else [95.0] * 14))
    opens = np.full(15, 100.0)
    p.intrabar_data = IntrabarExecutionData(
        times, pd.Timedelta(minutes=1), opens,
        np.maximum(opens, closes), np.minimum(opens, closes), closes,
    )
    p.pending_next_open_entry = p._entry_decision(0)
    p._execute_pending_next_open_entry(1)
    assert bool(p.opened) == enters
    assert p.pending_next_open_entry is None
    if enters:
        schedule = p.opened[0][1]
        assert schedule["actual_entry_timestamp"] == pd.Timestamp("2026-01-01T01:01:00")
        assert schedule["fill_price"] == first_close
    else:
        assert p.skipped == [(0, "FVG_CONFIRMATION_DIRECTION_MISMATCH")]
