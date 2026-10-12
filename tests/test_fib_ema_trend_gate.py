"""Regression tests for optional Fibonacci EMA 320/1600 execution veto."""
import numpy as np
from types import SimpleNamespace
from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin


class _FakeFib(FibonacciRetracementMixin):
    def __init__(self, close, direction, entry, stop, enabled=True):
        self.close = np.asarray(close, dtype=float)
        self.config = SimpleNamespace(fib_ema_trend_gate=enabled)
        self.direction = direction
        self.entry = entry
        self.stop = stop

    def _effective_trade_direction(self, i):
        return self.direction

    def _expected_entry_price(self, i, execution_i, direction):
        return self.entry

    def _sr_stop_plan(self, i, execution_i=None):
        return {"passed": True, "stop_price": self.stop}


def test_fib_ema_long_accepts_stop_below_fast_ema():
    prices = np.concatenate((np.full(1700, 10.0), np.linspace(10.0, 20.0, 500)))
    fib = _FakeFib(prices, "LONG", 21.0, 11.0)
    assert fib._fib_ema_trend_check(len(prices) - 1)[0] is True


def test_fib_ema_long_rejects_stop_above_fast_ema():
    prices = np.concatenate((np.full(1700, 10.0), np.linspace(10.0, 20.0, 500)))
    fib = _FakeFib(prices, "LONG", 21.0, 22.0)
    assert fib._fib_ema_trend_check(len(prices) - 1)[1] == "FIB_EMA_LONG_STOP_NOT_BELOW_320"


def test_fib_ema_short_accepts_stop_above_fast_ema():
    prices = np.concatenate((np.full(1700, 20.0), np.linspace(20.0, 10.0, 500)))
    fib = _FakeFib(prices, "SHORT", 9.0, 19.0)
    assert fib._fib_ema_trend_check(len(prices) - 1)[0] is True


def test_fib_ema_short_rejects_price_above_slow_ema():
    prices = np.concatenate((np.full(1700, 20.0), np.linspace(20.0, 10.0, 500)))
    fib = _FakeFib(prices, "SHORT", 25.0, 19.0)
    assert fib._fib_ema_trend_check(len(prices) - 1)[1] == "FIB_EMA_SHORT_TREND_VETO"


def test_fib_ema_missing_warmup_rejected():
    fib = _FakeFib(np.full(1500, 10.0), "LONG", 11.0, 9.0)
    assert fib._fib_ema_trend_check(1499)[1] == "FIB_EMA_HISTORY_UNAVAILABLE"


def test_fib_ema_gate_disabled_preserves_existing_behavior():
    fib = _FakeFib(np.full(5, 10.0), "LONG", 11.0, 9.0, enabled=False)
    assert fib._fib_ema_trend_check(4)[0] is True


def test_fib_ema_gate_rejects_non_15m_timeframes():
    prices = np.full(1800, 10.0)
    fib = _FakeFib(prices, "LONG", 11.0, 9.0)
    fib.config.strategy_timeframe_minutes = 240
    assert fib._fib_ema_trend_check(1799)[1] == "FIB_EMA_GATE_REQUIRES_15M"
