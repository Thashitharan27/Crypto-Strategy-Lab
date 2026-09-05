from __future__ import annotations

import math

import pandas as pd
import pytest

from crypto_strategy_core.taker_flow import taker_flow_evidence_series


def test_taker_flow_elapsed_windows_and_persistence_match_csl() -> None:
    source_times = pd.to_datetime(
        [
            "2026-01-01T00:05:00Z",
            "2026-01-01T00:10:00Z",
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:20:00Z",
        ],
        utc=True,
    )
    result = taker_flow_evidence_series(
        [pd.Timestamp("2026-01-01T00:20:00Z")],
        source_times,
        [10.0, 10.0, 10.0, 10.0],
        [8.0, 8.0, 2.0, 8.0],
    )
    # At T=20m, elapsed 15m means (05m,20m]: exactly the last 3 candles.
    assert result["taker_delta_pct_15m"][0] == pytest.approx(0.2)
    assert result["taker_delta_pct_1h"][0] == pytest.approx(0.3)
    assert result["flow_persistence"][0] == pytest.approx(0.75)
    assert result["taker_buy_sell_ratio"][0] == pytest.approx(4.0)


def test_taker_flow_decision_asof_never_uses_future_auxiliary_kline() -> None:
    result = taker_flow_evidence_series(
        [
            pd.Timestamp("2026-01-01T00:12:00Z"),
            pd.Timestamp("2026-01-01T00:20:00Z"),
        ],
        pd.to_datetime(
            [
                "2026-01-01T00:05:00Z",
                "2026-01-01T00:10:00Z",
                "2026-01-01T00:15:00Z",
            ],
            utc=True,
        ),
        [10.0, 10.0, 10.0],
        [8.0, 2.0, 10.0],
    )
    assert pd.Timestamp(result["taker_source_available_at"][0]) == pd.Timestamp(
        "2026-01-01T00:10:00Z"
    )
    assert result["taker_delta_pct"][0] == pytest.approx(-0.6)
    assert pd.Timestamp(result["taker_source_available_at"][1]) == pd.Timestamp(
        "2026-01-01T00:15:00Z"
    )


def test_taker_flow_tiny_buy_excess_is_clamped_but_material_excess_fails() -> None:
    time = [pd.Timestamp("2026-01-01T00:05:00Z")]
    result = taker_flow_evidence_series(
        time,
        time,
        [10.0],
        [10.0 + 1e-10],
        volume_tolerance=1e-9,
    )
    assert result["taker_sell_volume"][0] == 0.0
    assert math.isnan(float(result["taker_buy_sell_ratio"][0]))

    with pytest.raises(ValueError, match="exceeds volume"):
        taker_flow_evidence_series(
            time,
            time,
            [10.0],
            [10.1],
            volume_tolerance=1e-9,
        )


@pytest.mark.parametrize(
    ("volume", "buy"),
    [(-1.0, 0.0), (1.0, -0.1)],
)
def test_taker_flow_rejects_negative_volume_fields(volume: float, buy: float) -> None:
    time = [pd.Timestamp("2026-01-01T00:05:00Z")]
    with pytest.raises(ValueError, match="cannot be negative"):
        taker_flow_evidence_series(time, time, [volume], [buy])


def test_taker_flow_rejects_invalid_tolerance_and_descending_decisions() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        taker_flow_evidence_series([], [], [], [], volume_tolerance=float("inf"))
    with pytest.raises(ValueError, match="chronological"):
        taker_flow_evidence_series(
            pd.to_datetime(
                ["2026-01-01T00:10:00Z", "2026-01-01T00:05:00Z"], utc=True
            ),
            [],
            [],
            [],
        )
