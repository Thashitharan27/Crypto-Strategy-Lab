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


def test_fib_ema_confluence_measures_level_to_ema_not_price_to_ema():
    n = 220
    open_ = np.linspace(90.0, 110.0, n)
    high = open_ + 1.0
    low = open_ - 1.0
    close = open_ + 0.2
    atr = np.full(n, 2.0)

    # Build one confirmed bullish impulse then a retracement near its 0.500 level.
    open_[195:202] = [100, 99, 98, 100, 104, 108, 106]
    high[195:202] = [101, 100, 99, 101, 105, 110, 107]
    low[195:202] = [99, 98, 96, 99, 103, 107, 105]
    close[195:202] = [100, 99, 97, 100, 104, 109, 106]
    open_[202:206] = [105, 104, 103, 103]
    high[202:206] = [106, 105, 104, 104]
    low[202:206] = [104, 103, 102, 102]
    close[202:206] = [105, 104, 103, 103]

    ema50 = np.full(n, np.nan)
    ema100 = np.full(n, np.nan)
    ema200 = np.full(n, np.nan)
    # We only care that the distance is measured from the active Fib level,
    # not from the current close. Use deliberately different locations.
    ema50[205] = 102.0
    ema100[205] = 103.0
    ema200[205] = 104.0

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=2,
        ema_50_values=ema50,
        ema_100_values=ema100,
        ema_200_values=ema200,
    )
    level = values["_FIB_ACTIVE_LEVEL_PRICE"][205]
    assert np.isfinite(level)
    assert np.isclose(
        values["FIB_EMA_100_DISTANCE_ATR"][205],
        abs(level - 103.0) / 2.0,
    )
    assert not np.isclose(
        values["FIB_EMA_100_DISTANCE_ATR"][205],
        abs(close[205] - 103.0) / 2.0,
    )


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

def test_fib_native_stop_uses_next_deeper_level_and_target_uses_impulse_extreme():
    class Base:
        def _sr_stop_plan(self, i, execution_i=None):
            return {"passed": True, "applied": False, "reason": "BASE", "distance": 1.0}
        def _effective_trade_direction(self, _i):
            return "LONG"
        def _expected_entry_price(self, i, execution_i, direction):
            return 11.0
        def _entry_filter_result(self, i, execution_i=None):
            return True, "OK"
        def _open_pair(self, *args, **kwargs):
            return None
        def _build_result_row(self, *args, **kwargs):
            return {}

    class Probe(FibonacciRetracementMixin, Base):
        pass

    p = Probe.__new__(Probe)
    p.signal_strategy_mode = FIB_RETRACEMENT_MODE
    p.config = SimpleNamespace(
        strategy_timeframe_minutes=240,
        fib_stop_buffer_atr=0.05,
        fib_target_buffer_atr=0.05,
        fib_minimum_target_r=0.5,
    )
    p.open = np.array([11.0, 11.0])
    p.atr_values = np.array([1.0, 1.0])
    p.fib_retracement = {
        "FIB_NEAREST_LEVEL": np.array([0.500, 0.500]),
        "_FIB_IMPULSE_START_PRICE": np.array([8.0, 8.0]),
        "_FIB_IMPULSE_END_PRICE": np.array([12.0, 12.0]),
    }

    stop = p._sr_stop_plan(0, 1)
    # 0.618 of a 4-point bullish impulse is 9.528; stop adds a 0.05 ATR buffer below.
    assert stop["passed"] is True
    assert stop["fib_entry_level"] == 0.5
    assert stop["fib_stop_level"] == 0.618
    assert np.isclose(stop["boundary_price"], 9.528)
    assert np.isclose(stop["stop_price"], 9.478)
    assert np.isclose(stop["distance"], 1.522)

    target = p._fib_target_plan(0, 1)
    assert target["passed"] is True
    assert np.isclose(target["level_price"], 12.0)
    assert np.isclose(target["limit_price"], 11.95)
    assert target["available_r"] > 0.5

def test_fib_target_room_gate_uses_actual_stop_and_entry_geometry():
    class Base:
        def _sr_stop_plan(self, i, execution_i=None):
            return {"passed": True, "applied": False, "reason": "BASE", "distance": 1.0}
        def _effective_trade_direction(self, _i):
            return "LONG"
        def _expected_entry_price(self, i, execution_i, direction):
            return 11.0
        def _entry_filter_result(self, i, execution_i=None):
            return True, "OK"

    class Probe(FibonacciRetracementMixin, Base):
        pass

    p = Probe.__new__(Probe)
    p.signal_strategy_mode = FIB_RETRACEMENT_MODE
    p.config = SimpleNamespace(
        strategy_timeframe_minutes=240,
        fib_stop_buffer_atr=0.10,
        fib_target_buffer_atr=0.20,
        fib_minimum_target_r=2.0,
    )
    p.open = np.array([11.0, 11.0])
    p.atr_values = np.array([1.0, 1.0])
    p.fib_retracement = {
        "FIB_NEAREST_LEVEL": np.array([0.500, 0.500]),
        "_FIB_IMPULSE_START_PRICE": np.array([8.0, 8.0]),
        "_FIB_IMPULSE_END_PRICE": np.array([12.0, 12.0]),
    }

    stop = p._sr_stop_plan(0, 1)
    assert np.isclose(stop["stop_price"], 9.428)

    target = p._fib_target_plan(0, 1)
    assert target["passed"] is False
    assert target["reason"] == "FIB_TARGET_INSUFFICIENT_ROOM"
    assert target["minimum_r"] == 2.0
    assert np.isclose(target["limit_price"], 11.8)
    assert target["available_r"] < 2.0

    p.config.fib_minimum_target_r = 0.5
    allowed = p._fib_target_plan(0, 1)
    assert allowed["passed"] is True
    assert allowed["available_r"] >= 0.5


def test_fib_fixed_r_target_uses_actual_stop_r_while_room_gate_stays_independent():
    class Base:
        def _sr_stop_plan(self, i, execution_i=None):
            return {"passed": True, "applied": False, "reason": "BASE", "distance": 1.0}
        def _effective_trade_direction(self, _i):
            return "LONG"
        def _expected_entry_price(self, i, execution_i, direction):
            return 11.0
        def _entry_filter_result(self, i, execution_i=None):
            return True, "OK"

    class Probe(FibonacciRetracementMixin, Base):
        pass

    p = Probe.__new__(Probe)
    p.signal_strategy_mode = FIB_RETRACEMENT_MODE
    p.config = SimpleNamespace(
        strategy_timeframe_minutes=240,
        fib_stop_buffer_atr=0.05,
        fib_target_mode="FIXED_R",
        fib_fixed_target_r=4.0,
        fib_target_buffer_atr=0.05,
        fib_minimum_target_r=0.5,
    )
    p.open = np.array([11.0, 11.0])
    p.atr_values = np.array([1.0, 1.0])
    p.fib_retracement = {
        "FIB_NEAREST_LEVEL": np.array([0.500, 0.500]),
        "_FIB_IMPULSE_START_PRICE": np.array([8.0, 8.0]),
        "_FIB_IMPULSE_END_PRICE": np.array([12.0, 12.0]),
    }

    stop = p._sr_stop_plan(0, 1)
    target = p._fib_target_plan(0, 1)

    assert target["passed"] is True
    assert target["reason"] == "FIB_FIXED_R_TARGET"
    assert target["target_mode"] == "FIXED_R"
    assert target["target_r"] == 4.0
    assert np.isclose(target["limit_price"], 11.0 + 4.0 * stop["distance"])
    assert np.isclose(target["room_limit_price"], 11.95)
    assert target["available_r"] < 1.0

    # Raising only the room gate rejects the same 4R target setup; the two
    # controls deliberately have separate meanings.
    p.config.fib_minimum_target_r = 4.0
    rejected = p._fib_target_plan(0, 1)
    assert rejected["passed"] is False
    assert rejected["reason"] == "FIB_TARGET_INSUFFICIENT_ROOM"
