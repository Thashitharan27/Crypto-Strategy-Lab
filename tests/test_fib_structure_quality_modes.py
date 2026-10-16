"""Regression coverage for optional Fibonacci impulse structure modes."""
import numpy as np
import pytest

from crypto_strategy_lab.fib_retracement import fibonacci_retracement_arrays


def _run(mode):
    # Deterministic, causal synthetic candles containing swing impulses.
    close = np.array([100, 98, 94, 90, 94, 99, 104, 110, 106, 102,
                      98, 94, 90, 87, 91, 94, 96, 92, 88, 84,
                      88, 92, 95, 90, 86, 82, 86, 90, 93, 88,
                      84, 81, 85, 89, 92, 88, 85, 82, 87, 91], dtype=float)
    # Wide sample enough to expose multiple confirmed pivots.
    close = np.tile(close, 4)
    # Distinct extrema avoid equal-high/low plateaus, which strict pivots
    # intentionally do not confirm.
    opening = close.copy()
    high = np.maximum(opening, close) + 0.4
    low = np.minimum(opening, close) - 0.4
    return fibonacci_retracement_arrays(
        opening, high, low, close, np.full(len(close), 2.0),
        pivot_strength=2, structure_quality_mode=mode,
    )


def test_modes_generate_same_shapes_and_causal_candidate_inventory():
    import json
    baseline = _run("BASELINE")
    clean = _run("CLEAN_ONLY")
    weighted = _run("WEIGHTED")
    assert set(baseline) == set(clean) == set(weighted)
    inventory_key = "_FIB_CANDIDATE_INVENTORY_JSON"
    for output in (baseline, clean, weighted):
        inventory = output[inventory_key]
        assert len(inventory) == 160
        candidates = [c for row in inventory for c in json.loads(row)]
        assert candidates
        assert all(c["structure_class"] in ("CLEAN", "EXTENDED", "FRAGMENTED") for c in candidates)
        assert all(0 <= c["max_internal_retracement_ratio"] for c in candidates)
    clean_candidates = [
        c for row in clean[inventory_key] for c in json.loads(row)
    ]
    assert all(c["structure_class"] == "CLEAN" for c in clean_candidates if c["structure_quality_eligible"])


def test_invalid_mode_fails_before_execution():
    with pytest.raises(ValueError, match="Invalid Fibonacci structure quality mode"):
        _run("UNKNOWN")


def test_default_matches_explicit_baseline():
    close = np.array([100., 98., 95., 90., 96., 102., 105., 101., 96., 92.])
    op = np.r_[close[0], close[:-1]]
    kw = {"pivot_strength": 2}
    args = (op, np.maximum(op, close) + .3, np.minimum(op, close) - .3, close, np.ones(len(close)))
    implicit = fibonacci_retracement_arrays(*args, **kw)
    explicit = fibonacci_retracement_arrays(*args, structure_quality_mode="BASELINE", **kw)
    for key in implicit:
        assert np.array_equal(implicit[key], explicit[key], equal_nan=True) if implicit[key].dtype.kind in "fi" else list(implicit[key]) == list(explicit[key])
