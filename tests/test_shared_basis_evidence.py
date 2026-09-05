from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_core.basis import basis_evidence_series


def test_basis_zscore_is_native_timeline_not_strategy_alias() -> None:
    mark_times = pd.date_range("2026-01-01T01:00:00Z", periods=4, freq="1h")
    index_times = mark_times
    result = basis_evidence_series(
        [pd.Timestamp("2026-01-01T04:00:00Z")],
        [104.0],
        mark_times,
        [101.0, 102.0, 103.0, 104.0],
        index_times,
        [100.0, 100.0, 100.0, 100.0],
        zscore_min_samples=2,
    )
    # Native mark/index basis is 1%,2%,3%,4%; the final population z-score
    # therefore uses all four source-native observations, not one strategy row.
    expected = (0.04 - 0.025) / math.sqrt(
        sum((value - 0.025) ** 2 for value in (0.01, 0.02, 0.03, 0.04)) / 4
    )
    assert result["mark_index_basis_zscore_7d"][0] == pytest.approx(expected)
    assert result["mark_index_basis_bps"][0] == pytest.approx(400.0)
    assert result["mark_index_basis_state"][0] == "POSITIVE"


def test_basis_asof_alignment_never_uses_future_reference_price() -> None:
    decisions = [
        pd.Timestamp("2026-01-01T02:30:00Z"),
        pd.Timestamp("2026-01-01T03:30:00Z"),
    ]
    result = basis_evidence_series(
        decisions,
        [102.5, 103.5],
        [
            pd.Timestamp("2026-01-01T02:00:00Z"),
            pd.Timestamp("2026-01-01T03:00:00Z"),
            pd.Timestamp("2026-01-01T04:00:00Z"),
        ],
        [102.0, 103.0, 999.0],
        [
            pd.Timestamp("2026-01-01T01:45:00Z"),
            pd.Timestamp("2026-01-01T02:45:00Z"),
            pd.Timestamp("2026-01-01T04:00:00Z"),
        ],
        [100.0, 101.0, 1.0],
        premium_times=[
            pd.Timestamp("2026-01-01T02:00:00Z"),
            pd.Timestamp("2026-01-01T03:00:00Z"),
            pd.Timestamp("2026-01-01T04:00:00Z"),
        ],
        premium_prices=[0.001, 0.002, 50.0],
        zscore_min_samples=2,
    )
    assert result["mark_price"] == [102.0, 103.0]
    assert result["index_price"] == [100.0, 101.0]
    assert result["premium_index_close"] == [0.001, 0.002]
    assert pd.Timestamp(result["mark_source_available_at"][0]) <= decisions[0]
    assert pd.Timestamp(result["index_source_available_at"][1]) <= decisions[1]
    assert pd.Timestamp(result["premium_source_available_at"][1]) <= decisions[1]


def test_basis_optional_premium_remains_unavailable() -> None:
    result = basis_evidence_series(
        [pd.Timestamp("2026-01-01T01:00:00Z")],
        [100.5],
        [pd.Timestamp("2026-01-01T01:00:00Z")],
        [100.4],
        [pd.Timestamp("2026-01-01T01:00:00Z")],
        [100.0],
    )
    assert np.isnan(result["premium_index_close"][0])
    assert np.isnan(result["premium_index_zscore_7d"][0])
    assert pd.isna(result["premium_source_available_at"][0])


@pytest.mark.parametrize(
    ("window", "minimum"),
    [(float("inf"), 5), (0.0, 5), (7.0, 0)],
)
def test_basis_rejects_invalid_zscore_parameters(window: float, minimum: int) -> None:
    with pytest.raises(ValueError):
        basis_evidence_series(
            [],
            [],
            [],
            [],
            [],
            [],
            zscore_window_days=window,
            zscore_min_samples=minimum,
        )
