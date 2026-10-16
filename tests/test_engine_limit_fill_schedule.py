"""Non-executing limit candidate fill-metadata adapter tests."""
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.entry_plan import (
    EntryIntent, EntryPlan, EntryTiming, LimitOrderCandidate, schedule_entry,
)


def test_limit_candidate_metadata_preserves_signal_and_fill_index():
    order = schedule_entry(
        EntryIntent("LONG", 5, limit_price=100),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=2),
    )
    candidate = LimitOrderCandidate(price=100, execution_index=7)
    payload = BacktestEngine._limit_candidate_fill_schedule(
        SimpleNamespace(), order, candidate, 5
    )
    assert payload["indicator_index"] == 5
    assert payload["execution_index"] == 7
    assert payload["fill_price"] == 100
    assert payload["actual_entry_timestamp"] is None
    assert payload["fill_price_source"] == "LIMIT_LEVEL_CANDIDATE"


def test_limit_candidate_adapter_rejects_expired_or_incorrect_signal():
    order = schedule_entry(
        EntryIntent("SHORT", 3, limit_price=105),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=1),
    )
    with pytest.raises(ValueError):
        BacktestEngine._limit_candidate_fill_schedule(
            SimpleNamespace(), order, LimitOrderCandidate(105, 5), 3
        )
    with pytest.raises(ValueError):
        BacktestEngine._limit_candidate_fill_schedule(
            SimpleNamespace(), order, LimitOrderCandidate(105, 4), 2
        )


def test_full_intrabar_window_requires_both_edges_and_all_minutes():
    import pandas as pd
    from crypto_strategy_lab.entry_plan import has_complete_intrabar_window

    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = start + pd.Timedelta(minutes=5)
    minutes = list(pd.date_range(start, periods=5, freq="1min"))
    is_complete = lambda rows: has_complete_intrabar_window(rows, start, end, pd.Timedelta(minutes=1))

    assert is_complete(minutes)
    assert not is_complete(minutes[1:])  # Missing leading minute
    assert not is_complete(minutes[:-1])  # Missing trailing minute
    assert not is_complete(minutes[:2] + minutes[3:])  # Interior gap
    assert not is_complete(minutes + [minutes[-1]])  # Duplicate
    assert not is_complete(minutes[:-1] + [minutes[-1] + pd.Timedelta(seconds=1)])
    assert not is_complete(list(reversed(minutes)))
    assert not is_complete(minutes + [end])  # End is exclusive
    assert not is_complete([])
    assert not has_complete_intrabar_window(minutes, start, end, pd.Timedelta(minutes=2))
    assert not has_complete_intrabar_window(minutes, start, end, pd.Timedelta(0))


def test_full_intrabar_window_normalizes_timezones_without_changing_rows():
    import pandas as pd
    from crypto_strategy_lab.entry_plan import has_complete_intrabar_window

    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = start + pd.Timedelta(minutes=3)
    observed = list(pd.date_range(start, periods=3, freq="1min").tz_convert("Asia/Colombo"))
    before = observed.copy()
    assert has_complete_intrabar_window(observed, start, end, pd.Timedelta(minutes=1))
    assert observed == before
