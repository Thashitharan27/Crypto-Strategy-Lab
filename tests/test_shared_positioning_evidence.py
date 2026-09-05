from __future__ import annotations

import math

import pandas as pd
import pytest

from crypto_strategy_core.positioning import positioning_evidence_series, ratio_bias_evidence_series


def test_shared_positioning_matches_source_native_oi_horizons_and_1h_price_state() -> None:
    decisions = pd.to_datetime(["2026-01-01T04:00:00Z"], utc=True)
    metrics = pd.to_datetime(
        [
            "2026-01-01T03:00:00Z",
            "2026-01-01T03:55:00Z",
            "2026-01-01T04:00:00Z",
        ],
        utc=True,
    )
    price = pd.to_datetime(
        ["2026-01-01T03:00:00Z", "2026-01-01T04:00:00Z"],
        utc=True,
    )
    out = positioning_evidence_series(
        decisions,
        [999.0],
        metrics,
        [100.0, 110.0, 120.0],
        price_times_1h=price,
        price_closes_1h=[100.0, 110.0],
        oi_zscore_min_samples=2,
    )
    assert out["oi_change_5m"][0] == pytest.approx(10.0)
    assert out["oi_change_pct_5m"][0] == pytest.approx(10.0 / 110.0)
    assert out["oi_change_1h"][0] == pytest.approx(20.0)
    assert out["oi_change_pct_1h"][0] == pytest.approx(0.20)
    assert out["price_change_pct_1h"][0] == pytest.approx(0.10)
    assert out["oi_vs_price_state_1h"][0] == "PRICE_UP_OI_UP"


def test_shared_price_oi_state_uses_strategy_bar_changes_after_metric_asof() -> None:
    decisions = pd.to_datetime(
        [
            "2026-01-01T04:00:00Z",
            "2026-01-01T08:00:00Z",
            "2026-01-01T12:00:00Z",
        ],
        utc=True,
    )
    metric_times = pd.to_datetime(
        [
            "2026-01-01T03:55:00Z",
            "2026-01-01T07:55:00Z",
            "2026-01-01T11:55:00Z",
        ],
        utc=True,
    )
    out = positioning_evidence_series(
        decisions,
        [100.0, 102.0, 101.0],
        metric_times,
        [100.0, 110.0, 105.0],
        oi_zscore_min_samples=2,
    )
    assert out["price_oi_state"] == [
        "UNKNOWN",
        "PRICE_UP_OI_UP",
        "PRICE_DOWN_OI_DOWN",
    ]
    assert out["open_interest_change_1bar_pct"][1] == pytest.approx(0.10)
    assert out["price_return_1bar"][1] == pytest.approx(0.02)


def test_shared_positioning_future_source_mutation_cannot_change_past_rows() -> None:
    decisions = pd.date_range("2026-01-01T04:00:00Z", periods=6, freq="4h")
    metric_times = pd.date_range("2026-01-01T03:55:00Z", periods=30, freq="1h")
    oi = [100.0 + index for index in range(len(metric_times))]
    closes = [100.0 + index * 2 for index in range(len(decisions))]
    baseline = positioning_evidence_series(
        decisions,
        closes,
        metric_times,
        oi,
        oi_zscore_min_samples=3,
    )

    changed = list(oi)
    cutoff = pd.Timestamp("2026-01-01T12:00:00Z")
    for index, timestamp in enumerate(metric_times):
        if timestamp > cutoff:
            changed[index] *= 50.0
    mutated = positioning_evidence_series(
        decisions,
        closes,
        metric_times,
        changed,
        oi_zscore_min_samples=3,
    )

    for row, decision in enumerate(decisions):
        if decision > cutoff:
            continue
        for key in (
            "open_interest",
            "oi_change_pct_5m",
            "oi_change_pct_1h",
            "oi_change_pct_24h",
            "oi_zscore_7d",
            "price_oi_state",
        ):
            left, right = baseline[key][row], mutated[key][row]
            if isinstance(left, float) and math.isnan(left):
                assert isinstance(right, float) and math.isnan(right)
            else:
                assert left == right


def test_shared_positioning_preserves_nanosecond_metric_asof_order() -> None:
    metric_times = pd.to_datetime(
        [
            "2026-01-01T00:00:00.000000100Z",
            "2026-01-01T00:00:00.000000900Z",
        ],
        utc=True,
    )
    decision = pd.to_datetime(
        ["2026-01-01T00:00:00.000000500Z"],
        utc=True,
    )
    out = positioning_evidence_series(
        decision,
        [100.0],
        metric_times,
        [111.0, 999.0],
        oi_zscore_min_samples=1,
    )
    assert out["open_interest"][0] == pytest.approx(111.0)


def test_shared_positioning_requires_chronological_strategy_rows() -> None:
    decisions = pd.to_datetime(
        ["2026-01-01T08:00:00Z", "2026-01-01T04:00:00Z"],
        utc=True,
    )
    with pytest.raises(ValueError, match="chronological"):
        positioning_evidence_series(
            decisions,
            [101.0, 100.0],
            pd.to_datetime(["2026-01-01T03:55:00Z"], utc=True),
            [100.0],
        )



def test_shared_ratio_bias_is_causal_and_last_write_wins() -> None:
    source_times = pd.to_datetime(
        [
            "2026-01-01T03:55:00Z",
            "2026-01-01T07:55:00Z",
            "2026-01-01T07:55:00Z",
            "2026-01-01T11:55:00Z",
        ],
        utc=True,
    )
    decisions = pd.to_datetime(
        ["2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"],
        utc=True,
    )
    out = ratio_bias_evidence_series(
        decisions,
        source_times,
        [1.10, 9.0, 1.25, 0.80],
    )
    assert out["ratio"] == pytest.approx([1.10, 1.25])
    assert out["bias"] == pytest.approx([0.10, 0.25])


def test_shared_ratio_bias_preserves_nanosecond_asof_order() -> None:
    source_times = pd.to_datetime(
        [
            "2026-01-01T00:00:00.000000100Z",
            "2026-01-01T00:00:00.000000900Z",
        ],
        utc=True,
    )
    decision = pd.to_datetime(
        ["2026-01-01T00:00:00.000000500Z"],
        utc=True,
    )
    out = ratio_bias_evidence_series(
        decision,
        source_times,
        [1.20, 9.00],
    )
    assert out["ratio"][0] == pytest.approx(1.20)
    assert out["bias"][0] == pytest.approx(0.20)


def test_shared_ratio_future_mutation_cannot_change_past_bias() -> None:
    source_times = pd.date_range("2026-01-01T00:00:00Z", periods=8, freq="5min")
    decisions = pd.to_datetime(
        ["2026-01-01T00:10:00Z", "2026-01-01T00:20:00Z"],
        utc=True,
    )
    baseline = ratio_bias_evidence_series(
        decisions,
        source_times,
        [1.0 + index * 0.01 for index in range(8)],
    )
    changed = [1.0 + index * 0.01 for index in range(8)]
    changed[5:] = [99.0, 99.0, 99.0]
    mutated = ratio_bias_evidence_series(decisions, source_times, changed)
    assert mutated == baseline
