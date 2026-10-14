"""Regression tests for shared signal-to-entry scheduling."""
import pytest

from crypto_strategy_lab.entry_plan import (
    EntryIntent, EntryPlan, EntryTiming, schedule_entry,
)


def test_signal_close_is_on_confirmed_bar_not_next_open():
    entry = schedule_entry(
        EntryIntent(direction="LONG", signal_index=10),
        EntryPlan(EntryTiming.SIGNAL_CLOSE),
    )
    assert entry.earliest_index == 10
    assert entry.timing == EntryTiming.SIGNAL_CLOSE


def test_next_open_cannot_fill_signal_bar():
    entry = schedule_entry(
        EntryIntent(direction="SHORT", signal_index=10),
        EntryPlan(),
    )
    assert entry.earliest_index == 11
    assert entry.limit_price is None


def test_limit_level_requires_price_and_expires_deterministically():
    entry = schedule_entry(
        EntryIntent(direction="LONG", signal_index=10, limit_price=99),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=3),
    )
    assert entry.earliest_index == 11
    assert entry.expires_after_index == 13
    assert entry.limit_price == 99


@pytest.mark.parametrize("plan,intent", [
    (EntryPlan(EntryTiming.LIMIT_LEVEL), EntryIntent("LONG", 5)),
    (EntryPlan(), EntryIntent("LONG", 5, limit_price=100)),
])
def test_invalid_price_mode_combinations_fail(plan, intent):
    with pytest.raises(ValueError):
        schedule_entry(intent, plan)


def test_invalid_timeout_and_direction_are_rejected():
    with pytest.raises(ValueError):
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=0)
    with pytest.raises(ValueError):
        EntryPlan(EntryTiming.NEXT_OPEN, limit_timeout_bars=5)
    with pytest.raises(ValueError):
        EntryIntent("SIDEWAYS", 3)
