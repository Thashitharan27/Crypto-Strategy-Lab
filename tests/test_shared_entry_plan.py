"""Regression tests for shared signal-to-entry scheduling."""
import pytest

from crypto_strategy_lab.entry_plan import (
    EntryIntent, EntryPlan, EntryTiming, schedule_entry, is_scheduled_entry_eligible, limit_order_touched,
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


def test_limit_order_is_never_eligible_on_signal_candle_or_after_expiry():
    order = schedule_entry(
        EntryIntent("LONG", 10, limit_price=99),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=3),
    )
    assert [i for i in range(9, 16) if is_scheduled_entry_eligible(order, i)] == [11, 12, 13]


def test_unbounded_limit_order_eligible_only_after_confirmation():
    order = schedule_entry(
        EntryIntent("SHORT", 4, limit_price=105),
        EntryPlan(EntryTiming.LIMIT_LEVEL),
    )
    assert not is_scheduled_entry_eligible(order, 4)
    assert is_scheduled_entry_eligible(order, 5)
    assert is_scheduled_entry_eligible(order, 100)


@pytest.mark.parametrize("timing,expected_index", [
    (EntryTiming.SIGNAL_CLOSE, 6),
    (EntryTiming.NEXT_OPEN, 7),
])
def test_non_limit_entry_intent_is_eligible_at_only_one_index(timing, expected_index):
    order = schedule_entry(EntryIntent("LONG", 6), EntryPlan(timing))
    assert [i for i in range(5, 10) if is_scheduled_entry_eligible(order, i)] == [expected_index]


def test_limit_price_touch_only_after_confirmation_and_before_expiry():
    order = schedule_entry(
        EntryIntent("LONG", 10, limit_price=99),
        EntryPlan(EntryTiming.LIMIT_LEVEL, limit_timeout_bars=2),
    )
    assert not limit_order_touched(order, 10, 98, 100)
    assert limit_order_touched(order, 11, 98, 100)
    assert limit_order_touched(order, 12, 99, 100)
    assert not limit_order_touched(order, 13, 98, 100)
    assert not limit_order_touched(order, 11, 100, 102)


def test_limit_touch_rejects_invalid_bars_and_other_entry_modes():
    order = schedule_entry(EntryIntent("SHORT", 1, limit_price=105), EntryPlan(EntryTiming.LIMIT_LEVEL))
    assert not limit_order_touched(order, 2, float("nan"), 106)
    assert not limit_order_touched(order, 2, 107, 106)
    assert not limit_order_touched(order, 2, 0, 106)
    immediate = schedule_entry(EntryIntent("LONG", 1), EntryPlan(EntryTiming.SIGNAL_CLOSE))
    assert not limit_order_touched(immediate, 1, 90, 110)
