from crypto_strategy_core.ema_strategy import (
    ema_20_100_cross,
    ema_20_100_entry_direction,
)


def _series(previous_fast, current_fast, previous_slow=10.0, current_slow=10.0):
    fast = [9.0] * 99 + [previous_fast, current_fast]
    slow = [10.0] * 99 + [previous_slow, current_slow]
    return fast, slow


def test_long_only_cross_requires_completed_upward_cross():
    fast, slow = _series(10.0, 11.0)
    assert ema_20_100_entry_direction(100, fast, slow, "EMA_20_100_CROSS") == "LONG"
    assert ema_20_100_entry_direction(99, fast, slow, "EMA_20_100_CROSS") is None
    assert ema_20_100_entry_direction(100, fast, slow, "EMA_20_100_CROSS_SHORT") is None


def test_short_and_both_modes():
    fast, slow = _series(10.0, 9.0)
    assert ema_20_100_entry_direction(100, fast, slow, "EMA_20_100_CROSS") is None
    assert ema_20_100_entry_direction(100, fast, slow, "EMA_20_100_CROSS_SHORT") == "SHORT"
    assert ema_20_100_entry_direction(100, fast, slow, "EMA_20_100_CROSS_BOTH") == "SHORT"


def test_missing_or_nonfinite_evidence_fails_closed():
    fast, slow = _series(float("nan"), 11.0)
    assert ema_20_100_cross(100, fast, slow, upwards=True) is False
    assert ema_20_100_entry_direction(101, fast, slow, "EMA_20_100_CROSS") is None
