from datetime import date

import pandas as pd

from crypto_strategy_lab.research_daily_sequence import _day_for, _new_day_state, stop_reason


def apply_outcomes(outcomes, win_lead=1, loss_lead=5):
    wins = 0
    losses = 0
    states = []
    for outcome in outcomes:
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        states.append((wins, losses, stop_reason(wins, losses, win_lead, loss_lead)))
    return states


def test_first_win_stops_day():
    assert apply_outcomes(["win"])[-1] == (1, 0, "WIN_LEAD_REACHED")


def test_loss_win_win_stops_when_wins_are_one_ahead():
    states = apply_outcomes(["loss", "win", "win"])
    assert states[0][2] is None
    assert states[1][2] is None
    assert states[2] == (2, 1, "WIN_LEAD_REACHED")


def test_equal_wins_and_losses_continue():
    states = apply_outcomes(["loss", "win", "loss", "win"])
    assert states[-1] == (2, 2, None)
    states = apply_outcomes(["loss", "win", "loss", "win", "win"])
    assert states[-1] == (3, 2, "WIN_LEAD_REACHED")


def test_three_losses_two_wins_needs_two_more_wins():
    states = apply_outcomes(["loss", "loss", "win", "loss", "win"])
    assert states[-1] == (2, 3, None)
    states = apply_outcomes(["loss", "loss", "win", "loss", "win", "win"])
    assert states[-1] == (3, 3, None)
    states = apply_outcomes(["loss", "loss", "win", "loss", "win", "win", "win"])
    assert states[-1] == (4, 3, "WIN_LEAD_REACHED")


def test_loss_lead_of_five_stops_day():
    outcomes = ["loss"] * 5
    assert apply_outcomes(outcomes)[-1] == (0, 5, "LOSS_LEAD_REACHED")
    outcomes = ["loss", "win"] + ["loss"] * 5
    assert apply_outcomes(outcomes)[-1] == (1, 6, "LOSS_LEAD_REACHED")


def test_research_day_is_based_on_configured_timezone():
    # 00:30 in Sri Lanka is still the previous UTC research day.
    ts = pd.Timestamp("2020-05-10T00:30:00+05:30")
    assert _day_for(ts, "UTC") == date(2020, 5, 9)
    assert _day_for(ts, "Asia/Colombo") == date(2020, 5, 10)


def test_each_new_day_ledger_starts_clean():
    first = _new_day_state()
    first["wins"] = 3
    first["losses"] = 2
    first["entries"] = 5
    second = _new_day_state()
    assert second == {
        "wins": 0,
        "losses": 0,
        "entries": 0,
        "completed": 0,
        "stop_reason": None,
    }
    assert first is not second
