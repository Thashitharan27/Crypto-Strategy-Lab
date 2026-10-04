from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.walk_forward_direction_tracker import (
    LONG,
    NEUTRAL,
    SHORT,
    build_walk_forward_direction_tracker,
)


def _samples(outcomes: list[str], *, regime: str = "BULL") -> pd.DataFrame:
    rows: list[dict] = []
    for index, winner in enumerate(outcomes, start=1):
        long_r = 1.0 if winner == LONG else -1.0 if winner == SHORT else 0.0
        short_r = 1.0 if winner == SHORT else -1.0 if winner == LONG else 0.0
        candidate_id = f"wf-{index}"
        common = {
            "walk_forward_candidate_id": candidate_id,
            "research_signal_index": index,
            "market_regime": regime,
        }
        rows.append({**common, "side": LONG, "pair_net_r": long_r})
        rows.append({**common, "side": SHORT, "pair_net_r": short_r})
    return pd.DataFrame(rows)


def test_current_candidate_outcome_is_not_in_its_own_history() -> None:
    details, scores, summary = build_walk_forward_direction_tracker(
        _samples([LONG, SHORT, LONG])
    )

    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)
    assert market.loc[0, "last100_vote"] == NEUTRAL
    assert market.loc[1, "last100_vote"] == LONG
    assert market.loc[1, "last100_long_count"] == 1
    assert market.loc[1, "last100_short_count"] == 0
    assert market.loc[2, "last100_vote"] == NEUTRAL
    assert market.loc[2, "last100_long_count"] == 1
    assert market.loc[2, "last100_short_count"] == 1

    assert scores.loc[1, "winner"] == SHORT
    assert scores.loc[1, "last100_decision"] == LONG
    assert summary["current_candidate_excluded_from_own_history"] is True


def test_exact_sixty_percent_is_neutral() -> None:
    details, _, _ = build_walk_forward_direction_tracker(
        _samples([LONG, LONG, LONG, SHORT, SHORT, LONG])
    )
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    # Candidate six sees 3 LONG and 2 SHORT = exactly 60%, which is neutral.
    assert market.loc[5, "last100_long_count"] == 3
    assert market.loc[5, "last100_short_count"] == 2
    assert market.loc[5, "last100_long_share"] == 0.60
    assert market.loc[5, "last100_vote"] == NEUTRAL
    assert market.loc[5, "last20_vote"] == NEUTRAL


def test_final_policy_requires_last100_and_last20_to_agree() -> None:
    _, scores, summary = build_walk_forward_direction_tracker(
        _samples([LONG, LONG, LONG, LONG, SHORT])
    )

    # The fifth candidate is still scored from four prior LONG observations.
    last = scores.iloc[-1]
    assert last["last100_decision"] == LONG
    assert last["last20_decision"] == LONG
    assert last["agreed_decision"] == LONG
    assert bool(last["agreement_correct"]) is False

    assert summary["final_policy"] == "REQUIRE_LAST100_AND_LAST20_SAME_DIRECTION"
    assert summary["agreement_candidates"] > 0


def test_pair_validation_requires_one_long_and_one_short() -> None:
    broken = _samples([LONG]).iloc[:1].copy()
    try:
        build_walk_forward_direction_tracker(broken)
    except ValueError as exc:
        assert "exactly one LONG and one SHORT" in str(exc)
    else:
        raise AssertionError("expected malformed pair to be rejected")
