"""Shared candle plan can be used by any signal strategy."""
from types import SimpleNamespace

import numpy as np

from crypto_strategy_lab.candle_confirmation import (
    CandleConfirmationPlan,
    candle_confirmation_check,
    evaluate_candle_confirmation,
)


def test_signal_independent_confirmation_matches_strategy_adapter():
    candles = SimpleNamespace(
        open=np.array([11.0, 9.9]),
        high=np.array([11.2, 11.5]),
        low=np.array([9.7, 9.8]),
        close=np.array([10.0, 11.3]),
    )
    patterns = dict(strong_close=False, engulfing=True, wick_rejection=False, star=False)
    plan = CandleConfirmationPlan(enabled=True, **patterns)
    for prefix in ("fib", "ema_320", "future_signal"):
        config = SimpleNamespace(**{
            f"{prefix}_candle_confirmation_enabled": True,
            **{f"{prefix}_candle_{key}": value for key, value in patterns.items()},
        })
        adapter = SimpleNamespace(config=config, **vars(candles))
        assert candle_confirmation_check(adapter, 1, "LONG", prefix) == (
            evaluate_candle_confirmation(candles, 1, "LONG", plan, reason_prefix=prefix)
        )


def test_shared_plan_respects_disabled_gate_and_no_future_candles():
    candles = SimpleNamespace(
        open=np.array([10.0, 20.0]),
        high=np.array([11.2, 30.0]),
        low=np.array([9.9, 1.0]),
        close=np.array([11.0, 2.0]),
    )
    plan = CandleConfirmationPlan(enabled=True, strong_close=True)
    before = evaluate_candle_confirmation(candles, 0, "LONG", plan)
    candles.close[1] = 29.0
    assert evaluate_candle_confirmation(candles, 0, "LONG", plan) == before
    assert before == (True, "SHARED_CANDLE_STRONG_CLOSE_CONFIRMED")
    assert evaluate_candle_confirmation(candles, 0, "LONG", CandleConfirmationPlan()) == (
        True, "SHARED_CANDLE_CONFIRMATION_DISABLED"
    )
