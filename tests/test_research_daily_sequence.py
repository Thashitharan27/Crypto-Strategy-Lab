from crypto_strategy_lab.research_daily_sequence import stop_reason


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
