from __future__ import annotations

from tools.data_lake_preparation_profile import _summarize_events


def test_summarize_events_groups_non_overlapping_stage_timings() -> None:
    events = [
        {"category": "dataset_load", "name": "klines:4h", "seconds": 1.25},
        {"category": "dataset_load", "name": "klines:1m", "seconds": 2.50},
        {"category": "legacy_conversion", "name": "strategy", "seconds": 0.40},
        {"category": "feature_cache", "name": "core_directional", "seconds": 0.15},
    ]

    summary = _summarize_events(events, 5.0)

    assert summary["category_seconds"] == {
        "dataset_load": 3.75,
        "legacy_conversion": 0.40,
        "feature_cache": 0.15,
    }
    assert summary["category_calls"] == {
        "dataset_load": 2,
        "feature_cache": 1,
        "legacy_conversion": 1,
    }
    assert summary["instrumented_seconds"] == 4.3
    assert abs(summary["unattributed_seconds"] - 0.7) < 1e-12


def test_summarize_events_never_reports_negative_unattributed_time() -> None:
    events = [
        {"category": "dataset_load", "name": "klines:1m", "seconds": 1.01},
    ]

    summary = _summarize_events(events, 1.0)

    assert summary["instrumented_seconds"] == 1.01
    assert summary["unattributed_seconds"] == 0.0
