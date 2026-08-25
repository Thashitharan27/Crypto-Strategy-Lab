from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.bayesian_research import (
    BayesianTradeModel,
    enrich_bayesian_trade_probabilities,
    threshold_simulation,
)


def _trade(
    entry: str,
    exit_: str,
    *,
    side: str = "LONG",
    pnl: float = 1.0,
    net_r: float | None = None,
    regime: str = "BULL",
    plus_di: float = 30.0,
    minus_di: float = 15.0,
    plus_change: float = 2.0,
    minus_change: float = -1.0,
    adx: float = 25.0,
) -> dict[str, object]:
    return {
        "entry_time": pd.Timestamp(entry, tz="UTC"),
        "exit_time": pd.Timestamp(exit_, tz="UTC"),
        "side": side,
        "pair_net_pnl": pnl,
        "pair_net_r": pnl if net_r is None else net_r,
        "market_regime": regime,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "plus_di_change": plus_change,
        "minus_di_change": minus_change,
        "adx": adx,
    }


def test_future_outcome_cannot_change_an_earlier_probability():
    rows = [
        _trade("2024-01-01 00:00", "2024-01-01 02:00", pnl=1.0),
        # This entry happens before trade 1 has closed, so it must still see a
        # completely neutral model regardless of trade 1's eventual result.
        _trade("2024-01-01 01:00", "2024-01-01 03:00", pnl=-1.0),
        _trade("2024-01-01 04:00", "2024-01-01 05:00", pnl=1.0),
    ]
    first = enrich_bayesian_trade_probabilities(pd.DataFrame(rows))

    changed = pd.DataFrame(rows)
    changed.loc[0, "pair_net_pnl"] = -100.0
    changed.loc[0, "pair_net_r"] = -100.0
    second = enrich_bayesian_trade_probabilities(changed)

    assert first.loc[1, "bayes_long_probability"] == pytest.approx(0.5)
    assert second.loc[1, "bayes_long_probability"] == pytest.approx(0.5)
    assert first.loc[1, "bayes_long_probability"] == second.loc[1, "bayes_long_probability"]
    # By the third entry, trade 1 and trade 2 have completed, so their outcomes
    # are allowed to affect the posterior.
    assert first.loc[2, "bayes_long_probability"] != second.loc[2, "bayes_long_probability"]


def test_small_context_sample_is_shrunk_instead_of_trusting_raw_win_rate():
    model = BayesianTradeModel(prior_strength=20.0)
    observations = [
        _trade("2024-01-01 00:00", "2024-01-01 01:00", pnl=1.0),
        _trade("2024-01-02 00:00", "2024-01-02 01:00", pnl=1.0),
        _trade("2024-01-03 00:00", "2024-01-03 01:00", pnl=1.0),
        _trade("2024-01-04 00:00", "2024-01-04 01:00", pnl=-1.0),
    ]
    for raw in observations:
        model.observe(pd.Series(raw))

    estimate = model.estimate(pd.Series(observations[-1]), "LONG")

    assert estimate.context_samples == 4
    assert estimate.probability < 0.75
    assert estimate.probability > 0.5
    assert estimate.confidence == "LOW"


def test_completed_trade_becomes_available_at_a_later_entry():
    frame = pd.DataFrame(
        [
            _trade("2024-01-01 00:00", "2024-01-01 01:00", pnl=1.0),
            _trade("2024-01-01 02:00", "2024-01-01 03:00", pnl=-1.0),
        ]
    )

    scored = enrich_bayesian_trade_probabilities(frame)

    assert scored.loc[0, "bayes_long_side_samples"] == 0
    assert scored.loc[0, "bayes_long_context_samples"] == 0
    assert scored.loc[1, "bayes_long_side_samples"] == 1
    assert scored.loc[1, "bayes_long_context_samples"] == 1
    assert scored.loc[1, "bayes_long_probability"] > 0.5


def test_long_and_short_are_scored_independently():
    frame = pd.DataFrame(
        [
            _trade("2024-01-01 00:00", "2024-01-01 01:00", side="LONG", pnl=1.0),
            _trade(
                "2024-01-01 02:00",
                "2024-01-01 03:00",
                side="SHORT",
                pnl=-1.0,
                plus_di=15.0,
                minus_di=30.0,
                plus_change=-1.0,
                minus_change=2.0,
                regime="BEAR",
            ),
            _trade("2024-01-01 04:00", "2024-01-01 05:00", side="LONG", pnl=1.0),
        ]
    )

    scored = enrich_bayesian_trade_probabilities(frame)
    last = scored.iloc[-1]

    assert last["bayes_long_side_samples"] == 1
    assert last["bayes_short_side_samples"] == 1
    assert 0.0 < last["bayes_long_probability"] < 1.0
    assert 0.0 < last["bayes_short_probability"] < 1.0
    assert last["bayes_actual_side_probability"] == pytest.approx(last["bayes_long_probability"])


def test_threshold_flags_require_probability_and_minimum_context_sample():
    # Repeated identical contexts make the sample gate deterministic.  Strongly
    # winning history should eventually qualify at 55%, while early rows cannot
    # qualify even if their posterior rises above the threshold.
    rows = []
    for day in range(1, 27):
        rows.append(
            _trade(
                f"2024-01-{day:02d} 00:00",
                f"2024-01-{day:02d} 01:00",
                pnl=1.0 if day <= 24 else -1.0,
            )
        )
    scored = enrich_bayesian_trade_probabilities(
        pd.DataFrame(rows), min_context_samples=20
    )

    assert not scored.loc[10, "bayes_take_55_min20"]
    assert scored.loc[21, "bayes_actual_context_samples"] >= 20
    assert scored.loc[21, "bayes_take_55_min20"]

    summary = threshold_simulation(scored, min_context_samples=20)
    row_55 = summary.loc[np.isclose(summary["minimum_probability"], 0.55)].iloc[0]
    expected = scored["bayes_take_55_min20"].sum()
    assert row_55["trades"] == expected
    assert row_55["trades"] > 0


def test_input_order_does_not_change_scores_for_distinct_entry_times():
    frame = pd.DataFrame(
        [
            _trade("2024-01-01 00:00", "2024-01-01 01:00", pnl=1.0),
            _trade("2024-01-01 02:00", "2024-01-01 03:00", pnl=-1.0),
            _trade("2024-01-01 04:00", "2024-01-01 05:00", pnl=1.0),
        ]
    )
    normal = enrich_bayesian_trade_probabilities(frame.copy()).set_index("entry_time")
    shuffled = enrich_bayesian_trade_probabilities(
        frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
    ).set_index("entry_time")

    assert normal["bayes_long_probability"].sort_index().tolist() == pytest.approx(
        shuffled["bayes_long_probability"].sort_index().tolist()
    )


def test_empty_frame_gets_stable_bayesian_schema():
    frame = pd.DataFrame()
    scored = enrich_bayesian_trade_probabilities(frame)

    assert scored.empty
    assert "bayes_long_probability" in scored
    assert "bayes_short_probability" in scored
    assert "bayes_take_60_min20" in scored
