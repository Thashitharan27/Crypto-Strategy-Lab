from crypto_strategy_lab.research_coin_flip import coin_flip_direction


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
