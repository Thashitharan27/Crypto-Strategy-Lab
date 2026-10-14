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
