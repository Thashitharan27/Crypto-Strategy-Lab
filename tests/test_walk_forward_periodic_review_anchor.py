from __future__ import annotations

from crypto_strategy_lab.walk_forward_orchestrator_impl import (
    _initial_periodic_review_anchor,
    _periodic_review_due,
)


REFERENCE_RUN = "BTCUSDT_15m_reference"


class FakeReports:
    def __init__(self, start: str = "2025-01-01T00:00:00+00:00"):
        self.start = start

    def get_run_manifest(self, run: str) -> dict:
        assert run == REFERENCE_RUN
        return {"request": {"start": self.start}}


def _definition(anchor: str = "REFERENCE_PERIOD_START") -> dict:
    return {
        "reference_run": REFERENCE_RUN,
        "periodic_review_policy": {"initial_anchor": anchor},
    }


def _resolved(sequence: int, when: str, net_r: float) -> dict:
    return {
        "sequence": sequence,
        "event_type": "TRADE_RESOLVED",
        "effective_market_time": when,
        "payload": {"candidate_id": f"candidate-{sequence}", "net_r": net_r},
    }


def test_first_periodic_review_is_due_from_reference_start():
    events = [
        _resolved(2, "2025-02-01T00:00:00+00:00", 1.0),
        _resolved(3, "2025-04-02T00:00:00+00:00", -1.0),
    ]
    anchor = _initial_periodic_review_anchor(FakeReports(), _definition(), events)

    result = _periodic_review_due(events, 3, initial_anchor=anchor)

    assert result is not None
    assert result["status"] == "PERIODIC_REVIEW_REQUIRED"
    assert result["previous_review_sequence"] is None
    assert result["previous_review_time"] is None
    assert result["review_anchor_source"] == "REFERENCE_PERIOD_START"
    assert result["review_anchor_time"] == "2025-01-01T00:00:00+00:00"
    assert result["review_due_time"] == "2025-04-01T00:00:00+00:00"
    assert result["period_trade_stats"]["trades"] == 2
    assert result["period_trade_stats"]["wins"] == 1
    assert result["period_trade_stats"]["losses"] == 1


def test_first_periodic_review_is_not_due_before_three_months():
    events = [_resolved(2, "2025-03-31T23:59:59+00:00", 1.0)]
    anchor = _initial_periodic_review_anchor(FakeReports(), _definition(), events)

    assert _periodic_review_due(events, 3, initial_anchor=anchor) is None


def test_completed_periodic_review_becomes_next_anchor():
    events = [
        {
            "sequence": 4,
            "event_type": "REVIEW_COMPLETED",
            "effective_market_time": "2025-04-02T00:00:00+00:00",
            "payload": {"review_type": "PERIODIC", "decision": "NO_CHANGE"},
        },
        _resolved(5, "2025-07-03T00:00:00+00:00", 1.0),
    ]
    initial = _initial_periodic_review_anchor(FakeReports(), _definition(), events)

    result = _periodic_review_due(events, 3, initial_anchor=initial)

    assert result is not None
    assert result["previous_review_sequence"] == 4
    assert result["previous_review_time"] == "2025-04-02T00:00:00+00:00"
    assert result["review_anchor_source"] == "REVIEW_COMPLETED"
    assert result["review_due_time"] == "2025-07-02T00:00:00+00:00"
    assert result["period_trade_stats"]["trades"] == 1


def test_migrated_experiment_does_not_invent_initial_review_anchor():
    events = [
        {
            "sequence": 2,
            "event_type": "MIGRATION_RECORDED",
            "effective_market_time": "2025-01-15T00:00:00+00:00",
            "payload": {},
        },
        _resolved(3, "2025-07-01T00:00:00+00:00", 1.0),
    ]

    assert _initial_periodic_review_anchor(FakeReports(), _definition(), events) is None


def test_manual_initial_anchor_policy_does_not_auto_schedule_first_review():
    events = [_resolved(2, "2025-07-01T00:00:00+00:00", 1.0)]

    assert (
        _initial_periodic_review_anchor(
            FakeReports(), _definition(anchor="MANUAL"), events
        )
        is None
    )


def test_bootstrap_experiment_anchors_first_periodic_review_at_walk_forward_start():
    definition = {
        "reference_run": REFERENCE_RUN,
        "periodic_review_policy": {"initial_anchor": "WALK_FORWARD_START"},
        "research_protocol": {
            "mode": "BOOTSTRAP_THEN_WF",
            "bootstrap_start": "2023-01-01T00:00:00+00:00",
            "walk_forward_start": "2025-01-01T00:00:00+00:00",
        },
    }
    events = [_resolved(2, "2025-04-02T00:00:00+00:00", 1.0)]

    anchor = _initial_periodic_review_anchor(FakeReports("2023-01-01T00:00:00+00:00"), definition, events)
    result = _periodic_review_due(events, 3, initial_anchor=anchor)

    assert anchor.isoformat() == "2025-01-01T00:00:00+00:00"
    assert result is not None
    assert result["review_due_time"] == "2025-04-01T00:00:00+00:00"
