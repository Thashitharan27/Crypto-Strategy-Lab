from crypto_strategy_lab.research_coin_flip import (
    coin_flip_applies_to_trade_number,
    coin_flip_direction,
    risk_multiplier_for_trade_number,
)


def test_coin_flip_is_reproducible_for_same_seed_and_index():
    first = [coin_flip_direction(i, 42) for i in range(100)]
    second = [coin_flip_direction(i, 42) for i in range(100)]
    assert first == second
    assert set(first) <= {"LONG", "SHORT"}


def test_different_seed_changes_sequence():
    first = [coin_flip_direction(i, 42) for i in range(100)]
    second = [coin_flip_direction(i, 43) for i in range(100)]
    assert first != second


def test_coin_flip_is_reasonably_balanced_over_large_sample():
    directions = [coin_flip_direction(i, 42) for i in range(2000)]
    long_count = directions.count("LONG")
    assert 850 <= long_count <= 1150


def test_first_trade_is_normal_and_second_onward_use_coin_flip():
    assert coin_flip_applies_to_trade_number(1) is False
    assert coin_flip_applies_to_trade_number(2) is True
    assert coin_flip_applies_to_trade_number(3) is True
    assert coin_flip_applies_to_trade_number(20) is True


def test_only_second_trade_gets_research_risk_boost():
    assert risk_multiplier_for_trade_number(1, 2.0) == 1.0
    assert risk_multiplier_for_trade_number(2, 2.0) == 2.0
    assert risk_multiplier_for_trade_number(3, 2.0) == 1.0
    assert risk_multiplier_for_trade_number(10, 2.0) == 1.0


def test_second_trade_risk_boost_is_configurable():
    assert risk_multiplier_for_trade_number(2, 1.5) == 1.5
    assert risk_multiplier_for_trade_number(2, 3.0) == 3.0
