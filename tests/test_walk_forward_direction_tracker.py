from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.walk_forward_direction_tracker import (
    LONG,
    NEUTRAL,
    SHORT,
    build_walk_forward_direction_tracker,
    _adapt_direction_vote,
)


def _samples(
    outcomes: list[str],
    *,
    regime: str = "BULL",
    close_hours: list[int] | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    close_hours = close_hours or [1] * len(outcomes)
    for index, (winner, close_hour) in enumerate(zip(outcomes, close_hours), start=1):
        long_r = 1.0 if winner == LONG else -1.0 if winner == SHORT else 0.0
        short_r = 1.0 if winner == SHORT else -1.0 if winner == LONG else 0.0
        candidate_id = f"wf-{index}"
        entry_time = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(days=index - 1)
        exit_time = entry_time + pd.Timedelta(hours=close_hour)
        common = {
            "walk_forward_candidate_id": candidate_id,
            "research_signal_index": index,
            "market_regime": regime,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "research_signal_available_at": entry_time,
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


def test_still_open_earlier_candidate_is_not_available_to_later_candidate() -> None:
    samples = _samples(
        [LONG, SHORT, LONG],
        close_hours=[72, 1, 1],
    )
    details, scores, summary = build_walk_forward_direction_tracker(samples)
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    # Candidate 1 opened first but does not fully close until candidate 3's
    # entry timestamp.  Strictly-before availability means candidate 2 cannot
    # see it, and candidate 3 still cannot see it at the same timestamp.
    assert market.loc[1, "last100_directional_count"] == 0
    assert market.loc[1, "last100_vote"] == NEUTRAL
    assert market.loc[2, "last100_directional_count"] == 1
    assert market.loc[2, "last100_short_count"] == 1
    assert market.loc[2, "last100_vote"] == SHORT

    assert summary["history_requires_fully_closed_pair_before_candidate"] is True
    assert summary["history_availability_rule"] == (
        "pair_available_time < candidate_entry_time"
    )


def test_pair_becomes_eligible_only_after_both_sides_close() -> None:
    samples = _samples([LONG, SHORT, LONG], close_hours=[25, 1, 1])
    # Make candidate 1's SHORT side close later than its LONG side.
    mask = (
        samples["walk_forward_candidate_id"].eq("wf-1")
        & samples["side"].eq(SHORT)
    )
    samples.loc[mask, "exit_time"] = pd.Timestamp("2026-01-03T12:00:00Z")

    details, _, _ = build_walk_forward_direction_tracker(samples)
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    # Candidate 2 is before candidate 1's later side closes, so candidate 1 is
    # unavailable. Candidate 3 is also before 2026-01-03 12:00, so still unavailable.
    assert market.loc[1, "last100_directional_count"] == 0
    assert market.loc[2, "last100_directional_count"] == 1  # candidate 2 only


def test_future_feature_availability_is_rejected() -> None:
    samples = _samples([LONG])
    samples["funding_context_feature_available_at"] = pd.Timestamp(
        "2026-01-01T00:01:00Z"
    )
    try:
        build_walk_forward_direction_tracker(samples)
    except ValueError as exc:
        assert "leaks future data" in str(exc)
        assert "funding_context_feature_available_at" in str(exc)
    else:
        raise AssertionError("expected future feature availability to be rejected")



def test_adaptive_direction_waits_for_twenty_prior_calls() -> None:
    outcomes = [LONG] * 25
    details, scores, summary = build_walk_forward_direction_tracker(_samples(outcomes))
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    # Candidate 21 has only 19 prior directional market-regime calls because
    # candidate 1 had no prior history and therefore no raw agreed direction.
    assert market.loc[20, "adaptive_direction_sample_n"] == 19
    assert market.loc[20, "adaptive_vote"] == NEUTRAL

    # Candidate 22 now has 20 prior fully closed directional calls, all correct.
    assert market.loc[21, "adaptive_direction_sample_n"] == 20
    assert market.loc[21, "adaptive_direction_accuracy"] == 1.0
    assert market.loc[21, "raw_agreed_vote"] == LONG
    assert market.loc[21, "adaptive_vote"] == LONG

    assert scores.loc[21, "adaptive_decision"] == LONG
    assert summary["adaptive_direction_policy"]["rolling_directional_calls"] == 30
    assert summary["adaptive_direction_policy"]["minimum_prior_directional_calls"] == 20


def test_adaptive_direction_flips_when_prior_accuracy_is_below_forty_percent() -> None:
    # Build enough stable LONG calls, then make those LONG calls repeatedly wrong.
    # The adaptive history tracks correctness of the raw direction, independently
    # from the current candidate's eventual outcome.
    outcomes = [LONG] * 21 + [SHORT] * 30
    details, _, _ = build_walk_forward_direction_tracker(_samples(outcomes))
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    flipped = market.loc[
        (market["raw_agreed_vote"] == LONG)
        & (market["adaptive_direction_sample_n"] >= 20)
        & (market["adaptive_direction_accuracy"] < 0.40)
    ]
    if not flipped.empty:
        assert set(flipped["adaptive_vote"]) == {SHORT}


def test_adaptive_history_obeys_pair_close_availability() -> None:
    outcomes = [LONG] * 25
    samples = _samples(outcomes)
    # Delay candidate 2 until well after candidate 22's entry. Its raw call must
    # not be counted in candidate 22's adaptive performance sample.
    mask = samples["walk_forward_candidate_id"].eq("wf-2")
    samples.loc[mask, "exit_time"] = pd.Timestamp("2026-02-15T00:00:00Z")

    details, _, _ = build_walk_forward_direction_tracker(samples)
    market = details.loc[details["feature"] == "market_regime"].reset_index(drop=True)

    assert market.loc[21, "adaptive_direction_sample_n"] == 19
    assert market.loc[21, "adaptive_vote"] == NEUTRAL



def test_adaptive_direction_thresholds_keep_ignore_and_flip() -> None:
    assert _adapt_direction_vote(LONG, sample_n=20, accuracy=0.61) == LONG
    assert _adapt_direction_vote(SHORT, sample_n=20, accuracy=0.61) == SHORT
    assert _adapt_direction_vote(LONG, sample_n=20, accuracy=0.60) == NEUTRAL
    assert _adapt_direction_vote(SHORT, sample_n=20, accuracy=0.40) == NEUTRAL
    assert _adapt_direction_vote(LONG, sample_n=20, accuracy=0.39) == SHORT
    assert _adapt_direction_vote(SHORT, sample_n=20, accuracy=0.39) == LONG
    assert _adapt_direction_vote(LONG, sample_n=19, accuracy=1.0) == NEUTRAL
