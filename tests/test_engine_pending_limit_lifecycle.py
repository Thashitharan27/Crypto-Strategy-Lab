"""Pending limit order state contract remains isolated from fills."""
from types import SimpleNamespace

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.entry_plan import EntryIntent, EntryPlan, EntryTiming, LimitOrderCandidate, schedule_entry


def test_pending_limit_state_before_touch_and_after_expiration():
    entry = schedule_entry(EntryIntent("LONG", 2, limit_price=100), EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=2))
    engine = SimpleNamespace(_limit_entry_candidate=lambda entry, index: LimitOrderCandidate(100, index) if index == 4 else None)
    assert BacktestEngine._resolve_pending_limit_candidate(engine, entry, 2) == ("WAITING", None)
    assert BacktestEngine._resolve_pending_limit_candidate(engine, entry, 3) == ("WAITING", None)
    status, candidate = BacktestEngine._resolve_pending_limit_candidate(engine, entry, 4)
    assert status == "CANDIDATE"
    assert candidate.price == 100
    assert BacktestEngine._resolve_pending_limit_candidate(engine, entry, 5) == ("EXPIRED", None)


def test_pending_limit_resolver_rejects_non_limit_entry():
    entry = schedule_entry(EntryIntent("LONG", 2), EntryPlan(EntryTiming.NEXT_OPEN))
    engine = SimpleNamespace(_limit_entry_candidate=lambda entry, index: None)
    import pytest
    with pytest.raises(ValueError):
        BacktestEngine._resolve_pending_limit_candidate(engine, entry, 3)
