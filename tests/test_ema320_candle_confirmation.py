"""Regression tests for EMA320/Fibonacci shared directional candle confirmation."""
from types import SimpleNamespace

import numpy as np
import pytest

from crypto_strategy_lab.candle_confirmation import candle_confirmation_check
from crypto_strategy_lab.ema_pullback import Ema920PullbackMixin


def _probe(bars, direction="LONG", selected="strong_close", enabled=True, flip=False):
    keys = ("strong_close", "engulfing", "wick_rejection", "star")
    cfg = {f"ema_320_candle_{key}": key == selected for key in keys}
    cfg["ema_320_candle_confirmation_enabled"] = enabled
    cfg["ema_320_flip_signals"] = flip
    probe = SimpleNamespace(
        config=SimpleNamespace(**cfg),
        open=np.array([bar[0] for bar in bars], dtype=float),
        high=np.array([bar[1] for bar in bars], dtype=float),
        low=np.array([bar[2] for bar in bars], dtype=float),
        close=np.array([bar[3] for bar in bars], dtype=float),
    )
    return candle_confirmation_check(probe, len(bars) - 1, direction, "ema_320")


@pytest.mark.parametrize("selected,direction,bars,reason", [
    ("strong_close", "LONG", [(10, 11.2, 9.9, 11)], "STRONG_CLOSE"),
    ("strong_close", "SHORT", [(11, 11.2, 9.9, 10)], "STRONG_CLOSE"),
    ("engulfing", "LONG", [(11, 11.2, 9.7, 10), (9.9, 11.5, 9.8, 11.3)], "ENGULFING"),
    ("engulfing", "SHORT", [(10, 11.3, 9.7, 11), (11.1, 11.2, 9.5, 9.7)], "ENGULFING"),
    ("wick_rejection", "LONG", [(10, 10.5, 8.5, 10.4)], "WICK_REJECTION"),
    ("wick_rejection", "SHORT", [(10.4, 12.2, 10.0, 10.1)], "WICK_REJECTION"),
    ("star", "LONG", [(11, 11.2, 9.8, 10), (10, 10.2, 9.7, 9.9), (10, 10.9, 9.9, 10.8)], "STAR"),
    ("star", "SHORT", [(10, 11.2, 9.8, 11), (11, 11.2, 10.8, 11.1), (11, 11.1, 10.1, 10.2)], "STAR"),
])
def test_each_directional_pattern(selected, direction, bars, reason):
    ok, code = _probe(bars, direction, selected)
    assert ok and reason in code


def test_disabled_gate_keeps_baseline_and_no_selection_vetoes():
    weak = [(10, 12, 9, 10.1)]
    assert _probe(weak, enabled=False)[0]
    assert not _probe(weak, selected="none")[0]


def test_future_bar_does_not_affect_signal():
    bars = [(10, 11.2, 9.9, 11), (20, 30, 1, 2)]
    probe = SimpleNamespace(
        config=SimpleNamespace(ema_320_candle_confirmation_enabled=True),
        open=np.array([bar[0] for bar in bars]),
        high=np.array([bar[1] for bar in bars]),
        low=np.array([bar[2] for bar in bars]),
        close=np.array([bar[3] for bar in bars]),
    )
    before = candle_confirmation_check(probe, 0, "LONG", "ema_320")
    probe.close[1] = 29
    assert candle_confirmation_check(probe, 0, "LONG", "ema_320") == before


def test_pattern_history_boundary_and_direction():
    assert not _probe([(10, 11, 9, 10.1)], selected="star")[0]
    assert not _probe([(10, 11.2, 9.9, 11)], direction="SHORT")[0]


def test_ema320_full_body_signal_is_first_only():
    probe = SimpleNamespace(
        config=SimpleNamespace(ema_320_flip_signals=False),
        open=np.array([99., 99., 101., 102.]),
        high=np.array([100., 102., 103., 104.]),
        low=np.array([98., 98., 100., 101.]),
        close=np.array([99., 101., 102., 103.]),
        ema_320_values=np.full(4, 100.),
    )
    probe._ema_320_price_cross = lambda i: Ema920PullbackMixin._ema_320_price_cross(probe, i)
    assert Ema920PullbackMixin._ema_320_full_body_signal(probe, 2) == "LONG"
    assert Ema920PullbackMixin._ema_320_full_body_signal(probe, 3) is None
    assert Ema920PullbackMixin._ema_320_trade_direction(probe, 2) == "LONG"
    probe.config.ema_320_flip_signals = True
    assert Ema920PullbackMixin._ema_320_trade_direction(probe, 2) == "SHORT"
