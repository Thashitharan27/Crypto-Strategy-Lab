from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pandas as pd
import pytest

from crypto_strategy_core.funding import funding_rule_evidence_series

UTC = timezone.utc


def test_shared_funding_rule_evidence_matches_csl_event_timeline_semantics() -> None:
    events = pd.to_datetime(
        [
            "2025-12-31T16:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-01-01T04:05:00Z",
            "2026-01-01T08:00:00Z",
            "2026-01-01T16:00:00Z",
            "2026-01-02T00:00:00Z",
        ],
        utc=True,
    )
    rates = [0.0001, 0.0002, 0.0099, -0.0001, 0.0003, 0.0004]
    decisions = pd.to_datetime(
        ["2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"], utc=True
    )
    out = funding_rule_evidence_series(decisions, events, rates)

    assert out["funding_source_available_at"][0] == datetime(
        2026, 1, 1, tzinfo=UTC
    )
    assert out["funding_rate"][0] == pytest.approx(0.0002)
    assert out["funding_rate_bps"][0] == pytest.approx(2.0)
    assert out["funding_bias"][0] == "POSITIVE"
    assert out["funding_24h_count"][0] == 2
    assert out["funding_24h_sum"][0] == pytest.approx(0.0003)

    assert out["funding_rate"][1] == pytest.approx(-0.0001)
    assert out["funding_previous"][1] == pytest.approx(0.0099)
    assert out["funding_change"][1] == pytest.approx(-0.0100)
    assert out["funding_change_bps"][1] == pytest.approx(-100.0)
    assert out["funding_3_event_mean"][1] == pytest.approx(
        (0.0002 + 0.0099 - 0.0001) / 3
    )
    assert out["funding_24h_count"][1] == 4
    assert out["funding_24h_sum"][1] == pytest.approx(0.0101)


def test_shared_funding_duplicate_event_timestamp_is_last_write_wins() -> None:
    at = datetime(2026, 1, 1, 8, tzinfo=UTC)
    out = funding_rule_evidence_series(
        [at],
        [at - timedelta(hours=8), at, at],
        [0.0001, 0.9, -0.0002],
        zscore_min_samples=2,
    )
    assert out["funding_rate"][0] == pytest.approx(-0.0002)
    assert out["funding_bias"][0] == "NEGATIVE"
    assert out["funding_24h_count"][0] == 2


def test_shared_funding_future_mutation_cannot_change_past_decisions() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [start + timedelta(hours=8 * index) for index in range(30)]
    rates = [0.0001 + index * 0.00001 for index in range(30)]
    decisions = [start + timedelta(hours=8 * index) for index in range(20)]
    baseline = funding_rule_evidence_series(
        decisions,
        events,
        rates,
        zscore_min_samples=6,
    )
    changed = list(rates)
    for index in range(20, len(changed)):
        changed[index] = 0.5
    mutated = funding_rule_evidence_series(
        decisions,
        events,
        changed,
        zscore_min_samples=6,
    )
    for key in (
        "funding_rate",
        "funding_rate_bps",
        "funding_bias",
        "funding_previous",
        "funding_change",
        "funding_3_event_mean",
        "funding_7d_zscore",
        "funding_extreme_positive",
        "funding_extreme_negative",
        "funding_24h_sum",
        "funding_24h_count",
    ):
        left, right = baseline[key], mutated[key]
        for a, b in zip(left, right):
            if isinstance(a, float) and math.isnan(a):
                assert isinstance(b, float) and math.isnan(b)
            else:
                assert a == b


def test_shared_funding_preserves_nanosecond_event_ordering() -> None:
    events = pd.to_datetime(
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
    out = funding_rule_evidence_series(
        decision,
        events,
        [0.0001, 0.0009],
        zscore_min_samples=1,
    )
    assert out["funding_source_available_at"][0] == events[0]
    assert out["funding_rate"][0] == pytest.approx(0.0001)
