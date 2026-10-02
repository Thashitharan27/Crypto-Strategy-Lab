import numpy as np
from types import SimpleNamespace

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.fib_retracement import (
    FIB_RETRACEMENT_MODE,
    FIB_RULE_INDICATORS,
    FibonacciRetracementMixin,
    fibonacci_retracement_arrays,
)
from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS, EVIDENCE_LABELS
from crypto_strategy_lab.strategy_rule_model import MARKET_PERMISSIONS, compile_profiles, infer_direction_mode


def test_fib_strategy_is_first_class_authoring_option():
    strategy, _ = compile_profiles(
        direction_mode=FIB_RETRACEMENT_MODE,
        market_permissions=MARKET_PERMISSIONS,
    )
    assert infer_direction_mode(strategy) == FIB_RETRACEMENT_MODE
    assert DIRECTION_LABELS[FIB_RETRACEMENT_MODE] == "Fib Retracement — Reaction"
    assert FIB_RULE_INDICATORS <= set(RULE_INDICATORS)
    assert FIB_RULE_INDICATORS <= set(EVIDENCE_LABELS)


def test_fib_arrays_do_not_use_unconfirmed_future_pivot():
    open_ = np.array([10, 9, 8, 9, 11, 12, 11, 10.5, 10.0, 10.8], dtype=float)
    high = np.array([10.2, 9.2, 8.2, 9.2, 11.2, 12.2, 11.2, 10.8, 10.4, 11.0])
    low = np.array([9.8, 8.8, 7.8, 8.8, 10.8, 11.8, 10.8, 10.2, 9.8, 10.4])
    close = np.array([10, 9, 8, 9, 11, 12, 11, 10.5, 10.1, 10.8], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(open_, high, low, close, atr, pivot_strength=2)
    # The high at index 5 cannot be confirmed until index 7 closes.
    assert values["FIB_IMPULSE_DIRECTION"][6] == "UNKNOWN"
    assert values["FIB_IMPULSE_DIRECTION"][7] == "LONG"


def test_fib_mixin_emits_first_reaction_only_once_per_impulse():
    class Base:
        def _configure_signal_features(self):
            return None
        def _infer_signal_strategy_mode(self):
            return "DI"
        def _selected_direction(self, _i):
            return None

    class Probe(FibonacciRetracementMixin, Base):
        pass

    p = Probe.__new__(Probe)
    p.config = SimpleNamespace(
        strategy_profiles={
            "bull_long": SimpleNamespace(
                entry_rules=({"_strategy_direction_mode": FIB_RETRACEMENT_MODE},)
            )
        }
    )
    p.open = np.array([10,9,8,9,11,12,11.2,10.5,10.2,10.7,10.3,10.8], dtype=float)
    p.high = np.array([10.2,9.2,8.2,9.2,11.2,12.2,11.5,10.8,10.6,10.9,10.6,11.0])
    p.low = np.array([9.8,8.8,7.8,8.8,10.8,11.8,11.0,10.2,9.9,10.3,10.0,10.4])
    p.close = np.array([10,9,8,9,11,12,11.2,10.5,10.4,10.7,10.4,10.8], dtype=float)
    p.atr_values = np.ones(len(p.close))
    p._configure_signal_features()
    p.signal_strategy_mode = FIB_RETRACEMENT_MODE
    signals = [p._selected_direction(i) for i in range(len(p.close))]
    assert signals.count("LONG") <= 1
