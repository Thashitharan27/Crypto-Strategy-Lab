"""Regression coverage for chronological S/R preparation fast paths."""
from __future__ import annotations

from dataclasses import fields

import numpy as np

from crypto_strategy_core.higher_timeframe_sr import HigherTimeframeSRDetector
from crypto_strategy_core.research_support_resistance import (
    ResearchHigherTimeframeSRDetector,
    ResearchSupportResistanceDetector,
)
from crypto_strategy_core.support_resistance import SupportResistanceDetector


def _series(count: int = 180):
    rng = np.random.default_rng(20260912)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.9, count))
    open_ = close + rng.normal(0.0, 0.35, count)
    high = np.maximum(open_, close) + rng.uniform(0.2, 1.4, count)
    low = np.minimum(open_, close) - rng.uniform(0.2, 1.4, count)
    # Vary ATR enough to force merged-zone membership to change over time.
    atr = 1.1 + 0.55 * (1.0 + np.sin(np.arange(count) / 5.0))
    return open_, high, low, close, atr


def _assert_value_equal(left, right) -> None:
    if isinstance(left, (float, np.floating)) or isinstance(right, (float, np.floating)):
        left_float = float(left)
        right_float = float(right)
        if np.isnan(left_float) and np.isnan(right_float):
            return
        assert left_float == right_float
        return
    assert left == right


def _assert_context_equal(left, right) -> None:
    assert type(left) is type(right)
    for field in fields(type(left)):
        _assert_value_equal(getattr(left, field.name), getattr(right, field.name))


def _config():
    return dict(
        pivot_left=2,
        pivot_right=2,
        lookback_bars=45,
        zone_width_atr=0.85,
        near_distance_atr=0.9,
        enable_hold_confirmation=True,
        hold_confirmation_bars=3,
        hold_confirmation_atr=0.25,
        break_tolerance_atr=0.25,
        break_basis="CLOSE",
    )


def test_strategy_research_detector_matches_authoritative_detector_exactly():
    open_, high, low, close, atr = _series()
    baseline = SupportResistanceDetector(**_config())
    optimized = ResearchSupportResistanceDetector(**_config())

    for index in range(len(close)):
        for direction in ("LONG", "SHORT"):
            expected = baseline.analyze_price_location(
                index, open_, high, low, close, atr, direction
            )
            actual = optimized.analyze_price_location(
                index, open_, high, low, close, atr, direction
            )
            _assert_context_equal(actual, expected)

    # Research preparation only needs the current presentation context.  The
    # structural detector state remains incremental, while these large object
    # caches stay bounded across multi-year runs.
    assert len(optimized._base_context_cache) <= 1
    assert len(optimized._context_cache) <= 2
    assert len(optimized._context_input_cache) <= 1


def test_higher_timeframe_research_detector_matches_authoritative_detector_exactly():
    open_, high, low, close, atr = _series(110)
    baseline = HigherTimeframeSRDetector(**_config())
    optimized = ResearchHigherTimeframeSRDetector(**_config())

    # Mimic many strategy candles observing the same completed higher-timeframe
    # candle while the external strategy price continues to move.
    for index in range(len(close)):
        for offset in (-0.7, 0.0, 0.8):
            evaluation_price = float(close[index] + offset)
            for direction in ("LONG", "SHORT"):
                expected = baseline.analyze_external_price(
                    index,
                    open_,
                    high,
                    low,
                    close,
                    atr,
                    direction,
                    evaluation_price,
                )
                actual = optimized.analyze_external_price(
                    index,
                    open_,
                    high,
                    low,
                    close,
                    atr,
                    direction,
                    evaluation_price,
                )
                _assert_context_equal(actual, expected)


def test_higher_timeframe_reuses_merged_zones_for_same_completed_candle():
    open_, high, low, close, atr = _series(90)
    detector = ResearchHigherTimeframeSRDetector(**_config())

    calls = 0
    original_merge = detector.zone_merger.merge_levels

    def counted_merge(levels, current_atr):
        nonlocal calls
        calls += 1
        return original_merge(levels, current_atr)

    detector.zone_merger.merge_levels = counted_merge
    index = 70
    detector.analyze_external_price(
        index, open_, high, low, close, atr, "LONG", float(close[index])
    )
    calls_after_first = calls

    for offset in np.linspace(-1.0, 1.0, 20):
        price = float(close[index] + offset)
        detector.analyze_external_price(
            index, open_, high, low, close, atr, "LONG", price
        )
        detector.analyze_external_price(
            index, open_, high, low, close, atr, "SHORT", price
        )

    assert calls == calls_after_first
