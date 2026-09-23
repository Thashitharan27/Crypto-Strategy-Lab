from __future__ import annotations

from crypto_strategy_lab.walk_forward_adaptive_weekly import _adaptive_status


def _summary(*, matches: int, wins: int, losses: int, net_r: float, average_r: float | None):
    return {
        "matches": matches,
        "wins": wins,
        "losses": losses,
        "net_r": net_r,
        "average_r": average_r,
        "support_count": wins,
        "contradiction_count": losses,
    }


def test_no_recent_exposure_is_dormant_not_bad():
    status = _adaptive_status(
        lifecycle_status="ACTIVE",
        learning=_summary(
            matches=6, wins=5, losses=1, net_r=3.2, average_r=0.5333333333
        ),
        recent=_summary(
            matches=0, wins=0, losses=0, net_r=0.0, average_r=None
        ),
    )
    assert status == "DORMANT_NO_EXPOSURE"


def test_positive_learning_then_negative_recent_evidence_is_decaying():
    status = _adaptive_status(
        lifecycle_status="ACTIVE",
        learning=_summary(
            matches=16, wins=16, losses=0, net_r=14.64, average_r=0.915
        ),
        recent=_summary(
            matches=7, wins=2, losses=5, net_r=-3.734, average_r=-0.5334285714
        ),
    )
    assert status == "DECAYING"


def test_retired_event_state_remains_retired_regardless_of_recent_sample():
    status = _adaptive_status(
        lifecycle_status="RETIRED",
        learning=_summary(
            matches=10, wins=8, losses=2, net_r=5.0, average_r=0.5
        ),
        recent=_summary(
            matches=4, wins=4, losses=0, net_r=3.0, average_r=0.75
        ),
    )
    assert status == "RETIRED"
