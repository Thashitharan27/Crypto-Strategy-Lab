from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_core.candles import atr
from crypto_strategy_core.higher_timeframe_sr import HigherTimeframeSRDetector
from crypto_strategy_core.research_support_resistance import (
    ResearchHigherTimeframeSRDetector,
    ResearchSupportResistanceDetector,
)
from crypto_strategy_core.support_resistance import SupportResistanceDetector
from crypto_strategy_core.support_resistance_evidence import (
    _zone_inventory,
    support_resistance_evidence_series,
)


def _series(count: int = 80):
    times = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="1h")
    decisions = times + pd.Timedelta(hours=1)
    base = 100.0 + np.sin(np.arange(count) / 3.0) * 8.0 + np.arange(count) * 0.05
    open_ = base + np.sin(np.arange(count) / 2.0) * 0.3
    close = base + np.cos(np.arange(count) / 2.0) * 0.3
    high = np.maximum(open_, close) + 1.2
    low = np.minimum(open_, close) - 1.2
    atr_values = np.asarray(atr(high, low, close, 14), dtype=float)
    return times, decisions, open_, high, low, close, atr_values


def test_shared_sr_same_timeframe_is_future_mutation_invariant() -> None:
    times, decisions, open_, high, low, close, atr_values = _series()
    baseline = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        pivot_left=3,
        pivot_right=3,
        lookback_bars=40,
    )
    cutoff = 50
    changed_open = open_.copy()
    changed_high = high.copy()
    changed_low = low.copy()
    changed_close = close.copy()
    changed_open[cutoff + 1 :] *= 4.0
    changed_high[cutoff + 1 :] *= 4.0
    changed_low[cutoff + 1 :] *= 4.0
    changed_close[cutoff + 1 :] *= 4.0
    changed_atr = np.asarray(atr(changed_high, changed_low, changed_close, 14), dtype=float)
    mutated = support_resistance_evidence_series(
        times,
        decisions,
        changed_open, changed_high, changed_low, changed_close, changed_atr,
        strategy_minutes=60,
        pivot_left=3,
        pivot_right=3,
        lookback_bars=40,
    )
    fields = (
        "long_near_support",
        "long_near_resistance",
        "long_support_state",
        "long_resistance_state",
        "long_trade_location_rating",
        "long_room_in_direction_atr",
        "short_trade_location_rating",
    )
    for index in range(cutoff + 1):
        for field in fields:
            left = baseline[index][field]
            right = mutated[index][field]
            if isinstance(left, float) and np.isnan(left):
                assert isinstance(right, float) and np.isnan(right)
            else:
                assert left == right


def test_shared_sr_higher_timeframe_never_uses_incomplete_bar() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(96)
    rows = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        sr_timeframe_minutes=240,
        atr_period=14,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=30,
    )
    assert len(rows) == len(times)
    for decision_time, row in zip(decisions, rows):
        completed = row["sr_completed_candle_time"]
        if pd.isna(completed):
            continue
        assert pd.Timestamp(completed) <= decision_time


def test_shared_sr_resampling_uses_candle_open_not_decision_close() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(16)
    rows = support_resistance_evidence_series(
        times,
        decisions,
        open_, high, low, close, atr_values,
        strategy_minutes=60,
        sr_timeframe_minutes=240,
        pivot_left=1,
        pivot_right=1,
        lookback_bars=10,
    )
    # The first complete 4h candle opened at 00:00 and closes at 04:00.
    assert pd.Timestamp(rows[3]["sr_completed_candle_time"]) == pd.Timestamp(
        "2026-01-01T04:00:00Z"
    )


def test_shared_sr_requires_chronological_strategy_rows() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(20)
    reverse_times = times[::-1]
    reverse_decisions = decisions[::-1]
    try:
        support_resistance_evidence_series(
            reverse_times,
            reverse_decisions,
            open_[::-1], high[::-1], low[::-1], close[::-1], atr_values[::-1],
            strategy_minutes=60,
        )
    except ValueError as exc:
        assert "chronological" in str(exc)
    else:
        raise AssertionError("descending S/R timestamps must fail closed")

def test_shared_sr_zone_inventory_is_causal_and_contains_all_active_zones() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(120)
    rows = support_resistance_evidence_series(
        times,
        decisions,
        open_,
        high,
        low,
        close,
        atr_values,
        strategy_minutes=60,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=80,
        min_rejection_atr=0.0,
        include_zone_inventory=True,
    )

    parsed = [json.loads(row["zone_inventory_json"]) for row in rows]
    assert any(len(zones) >= 2 for zones in parsed)
    for zones in parsed:
        ids = [zone["zone_id"] for zone in zones]
        assert len(ids) == len(set(ids))
        for structure in ("SUPPORT", "RESISTANCE"):
            nearest = [
                zone
                for zone in zones
                if zone["structure"] == structure and zone["nearest"]
            ]
            assert len(nearest) <= 1

    cutoff = 70
    changed_open = open_.copy()
    changed_high = high.copy()
    changed_low = low.copy()
    changed_close = close.copy()
    changed_open[cutoff + 1 :] *= 1.7
    changed_high[cutoff + 1 :] *= 1.7
    changed_low[cutoff + 1 :] *= 1.7
    changed_close[cutoff + 1 :] *= 1.7
    changed_atr = np.asarray(
        atr(changed_high, changed_low, changed_close, 14), dtype=float
    )
    mutated = support_resistance_evidence_series(
        times,
        decisions,
        changed_open,
        changed_high,
        changed_low,
        changed_close,
        changed_atr,
        strategy_minutes=60,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=80,
        min_rejection_atr=0.0,
        include_zone_inventory=True,
    )
    assert [
        row["zone_inventory_json"] for row in rows[: cutoff + 1]
    ] == [
        row["zone_inventory_json"] for row in mutated[: cutoff + 1]
    ]



def _assert_sr_context_equal(left, right) -> None:
    for name in left.__dataclass_fields__:
        a = getattr(left, name)
        b = getattr(right, name)
        if isinstance(a, float) and np.isnan(a):
            assert isinstance(b, float) and np.isnan(b), name
        elif isinstance(b, float) and np.isnan(b):
            assert isinstance(a, float) and np.isnan(a), name
        elif isinstance(a, float) or isinstance(b, float):
            assert float(a) == pytest.approx(float(b)), name
        else:
            assert a == b, name


def test_research_same_timeframe_fastpath_preserves_every_context_and_zone() -> None:
    _, _, open_, high, low, close, atr_values = _series(520)
    config = dict(
        pivot_left=2,
        pivot_right=2,
        lookback_bars=80,
        zone_width_atr=0.45,
        zone_padding_atr=0.15,
        max_cluster_span_atr=0.85,
        min_rejection_atr=0.0,
        near_distance_atr=0.75,
        enable_hold_confirmation=True,
        hold_confirmation_bars=3,
        hold_confirmation_atr=0.2,
        break_tolerance_atr=0.2,
        break_basis="CLOSE",
    )
    baseline = SupportResistanceDetector(**config)
    optimized = ResearchSupportResistanceDetector(**config)

    for index in range(len(close)):
        for direction in ("LONG", "SHORT"):
            expected = baseline.analyze_price_location(
                index, open_, high, low, close, atr_values, direction
            )
            actual = optimized.analyze_price_location(
                index, open_, high, low, close, atr_values, direction
            )
            _assert_sr_context_equal(actual, expected)

        expected_inventory = _zone_inventory(
            baseline,
            index=index,
            high=high,
            low=low,
            current_price=float(close[index]),
            current_atr=float(atr_values[index]),
        )
        actual_inventory = _zone_inventory(
            optimized,
            index=index,
            high=high,
            low=low,
            current_price=float(close[index]),
            current_atr=float(atr_values[index]),
        )
        assert actual_inventory == expected_inventory


def test_shared_sr_reports_coarse_progress_without_changing_rows() -> None:
    times, decisions, open_, high, low, close, atr_values = _series(73)
    progress = []
    expected = support_resistance_evidence_series(
        times,
        decisions,
        open_,
        high,
        low,
        close,
        atr_values,
        strategy_minutes=60,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=40,
        min_rejection_atr=0.0,
        include_zone_inventory=True,
    )
    actual = support_resistance_evidence_series(
        times,
        decisions,
        open_,
        high,
        low,
        close,
        atr_values,
        strategy_minutes=60,
        pivot_left=2,
        pivot_right=2,
        lookback_bars=40,
        min_rejection_atr=0.0,
        include_zone_inventory=True,
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
        progress_interval=17,
    )
    pd.testing.assert_frame_equal(
        pd.DataFrame(actual),
        pd.DataFrame(expected),
        check_dtype=False,
    )
    assert progress == [(17, 73), (34, 73), (51, 73), (68, 73), (73, 73)]


def test_research_htf_detector_reuses_structural_snapshot_without_changing_context() -> None:
    _, _, open_, high, low, close, atr_values = _series(120)
    config = dict(
        pivot_left=2,
        pivot_right=2,
        lookback_bars=80,
        min_rejection_atr=0.0,
    )
    baseline = HigherTimeframeSRDetector(**config)
    optimized = ResearchHigherTimeframeSRDetector(**config)
    index = 90

    for direction, price in (
        ("LONG", float(close[index])),
        ("SHORT", float(close[index] + 0.75)),
        ("LONG", float(close[index] - 0.50)),
    ):
        expected = baseline.analyze_external_price(
            index, open_, high, low, close, atr_values, direction, price
        )
        actual = optimized.analyze_external_price(
            index, open_, high, low, close, atr_values, direction, price
        )
        _assert_sr_context_equal(actual, expected)

    assert optimized._research_external_snapshot_builds == 1
    assert optimized._research_external_snapshot_reuses == 2

    current_price = float(close[index] + 0.25)
    current_atr = float(atr_values[index])
    fast_inventory = optimized.research_zone_inventory(
        index=index,
        high=high,
        low=low,
        current_price=current_price,
        current_atr=current_atr,
    )
    reference_inventory = _zone_inventory(
        optimized,
        index=index,
        high=high,
        low=low,
        current_price=current_price,
        current_atr=current_atr,
    )
    assert fast_inventory == reference_inventory
\n