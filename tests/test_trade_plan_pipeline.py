"""Shared strategy plan composition is causal and rejects failed evidence."""
from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.candle_confirmation import CandleConfirmationPlan
from crypto_strategy_lab.entry_plan import EntryPlan, EntryTiming
from crypto_strategy_lab.trade_plan_pipeline import confirm_and_schedule


def _candles():
    return SimpleNamespace(
        open=np.array([10.0, 11.0]),
        high=np.array([11.2, 11.4]),
        low=np.array([9.8, 9.0]),
        close=np.array([11.0, 9.1]),
    )


def test_confirmed_signal_schedules_next_candle():
    decision = confirm_and_schedule(
        _candles(), signal_index=0, direction="LONG",
        candle_plan=CandleConfirmationPlan(enabled=True),
        entry_plan=EntryPlan(EntryTiming.NEXT_OPEN),
    )
    assert decision.confirmed
    assert decision.scheduled_entry.earliest_index == 1
    assert decision.scheduled_entry.direction == "LONG"


def test_failed_confirmation_never_schedules():
    decision = confirm_and_schedule(
        _candles(), signal_index=1, direction="LONG",
        candle_plan=CandleConfirmationPlan(enabled=True, strong_close=True,
                                          engulfing=False, wick_rejection=False, star=False),
        entry_plan=EntryPlan(),
    )
    assert not decision.confirmed
    assert decision.scheduled_entry is None


def test_future_bar_cannot_change_prior_confirmation():
    bars = _candles()
    plan = CandleConfirmationPlan(enabled=True)
    args = dict(signal_index=0, direction="LONG",
                candle_plan=plan, entry_plan=EntryPlan())
    earlier = confirm_and_schedule(bars, **args)
    bars.close[1] = 11.1
    assert confirm_and_schedule(bars, **args) == earlier
