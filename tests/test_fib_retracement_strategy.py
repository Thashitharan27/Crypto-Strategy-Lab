import numpy as np
from types import SimpleNamespace
import json

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.fib_retracement import (
    FIB_DOMINANT_REPLACEMENT_RATIO,
    FIB_MINIMUM_HOLD_REJECTION_ATR,
    FIB_MINIMUM_STRUCTURAL_COMPETITION_RATIO,
    FIB_RESEARCH_CONTEXT_VERSION,
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


def test_fib_prefers_dominant_confirmed_swing_over_new_local_wiggles():
    close = np.array(
        [10, 8, 10, 14, 16, 13, 12, 11, 13, 15, 14, 16, 19, 17, 16],
        dtype=float,
    )
    open_ = close.copy()
    high = close + 0.4
    low = close - 0.4
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=1,
        dominant_lookback_bars=32,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # The large low@1 -> high@4 swing remains active even after newer local
    # pivots appear.  The previous implementation would switch to the newest
    # small pivot-to-pivot leg.
    assert values["_FIB_IMPULSE_START_INDEX"][10] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][10] == 4

    # The future high at 12 is not usable until candle 13 confirms it.
    assert values["_FIB_IMPULSE_END_INDEX"][12] == 4
    # Once confirmed, it is materially stronger (>10%) and may replace the
    # prior structural leg while preserving the same dominant swing low.
    assert values["_FIB_IMPULSE_START_INDEX"][13] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][13] == 12


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


def test_active_long_fib_extends_original_anchor_beyond_discovery_lookback():
    close = np.array([
        14, 10, 12, 17, 20, 18, 18.5, 18.2, 18.7, 18.4, 18.8,
        18.3, 18.9, 18.5, 19.0, 18.6, 19.1, 18.7, 19.2, 22, 25, 23, 22.5,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # The first active leg is low@1 -> high@4.
    assert values["_FIB_IMPULSE_START_INDEX"][5] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][5] == 4

    # By the time high@20 is confirmed at candle 21, low@1 is older than the
    # 16-bar discovery window.  The active unbroken leg must still extend from
    # its original anchor instead of being rebuilt from a newer local low.
    assert 20 - 1 > 16
    assert values["_FIB_IMPULSE_START_INDEX"][21] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][21] == 20
    assert np.isclose(values["_FIB_IMPULSE_START_PRICE"][21], low[1])
    assert np.isclose(values["_FIB_IMPULSE_END_PRICE"][21], high[20])


def test_active_short_fib_extends_original_anchor_beyond_discovery_lookback():
    close = np.array([
        16, 20, 18, 13, 10, 12, 11.5, 11.8, 11.3, 11.6, 11.2,
        11.7, 11.1, 11.5, 11.0, 11.4, 10.9, 11.3, 10.8, 8, 5, 7, 7.5,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    assert values["_FIB_IMPULSE_START_INDEX"][5] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][5] == 4
    assert 20 - 1 > 16
    assert values["_FIB_IMPULSE_START_INDEX"][21] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][21] == 20
    assert np.isclose(values["_FIB_IMPULSE_START_PRICE"][21], high[1])
    assert np.isclose(values["_FIB_IMPULSE_END_PRICE"][21], low[20])


def test_deep_long_retracement_resets_old_anchor_before_future_extension():
    close = np.array([
        14, 10, 12, 17, 20, 18, 18.5, 18.2, 18.7, 18.4, 13.0,
        14.0, 15.0, 15.5, 16.0, 16.5, 17.0, 17.5, 18.0, 22.0, 25.0, 23.0, 22.5,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
        active_structure_reset_depth=0.618,
    )

    assert values["_FIB_IMPULSE_START_INDEX"][5] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][5] == 4

    # The close at 10 retraces more than 61.8% of low@1 -> high@4.
    initial_span = high[4] - low[1]
    assert (high[4] - close[10]) / initial_span >= 0.618

    # The later confirmed higher high must be treated as a new cycle rather
    # than extending the stale low@1 anchor beyond the discovery window.
    assert values["_FIB_IMPULSE_END_INDEX"][21] == 20
    assert values["_FIB_IMPULSE_START_INDEX"][21] != 1
    assert values["_FIB_IMPULSE_START_INDEX"][21] == 10


def test_deep_short_retracement_resets_old_anchor_before_future_extension():
    close = np.array([
        16, 20, 18, 13, 10, 12, 11.5, 11.8, 11.3, 11.6, 17.0,
        16.0, 15.0, 14.5, 14.0, 13.5, 13.0, 12.5, 12.0, 8.0, 5.0, 7.0, 7.5,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
        active_structure_reset_depth=0.618,
    )

    assert values["_FIB_IMPULSE_START_INDEX"][5] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][5] == 4

    initial_span = high[1] - low[4]
    assert (close[10] - low[4]) / initial_span >= 0.618

    assert values["_FIB_IMPULSE_END_INDEX"][21] == 20
    assert values["_FIB_IMPULSE_START_INDEX"][21] != 1
    assert values["_FIB_IMPULSE_START_INDEX"][21] == 10


def test_fib_progressive_zone_cancels_shallow_signal_after_midpoint_penetration():
    # Confirmed LONG impulse: low@1=8.0 -> high@3=12.0.
    # 0.382=10.472, midpoint to 0.500=10.236, 0.500=10.0.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.3, 10.0, 10.6, 10.1], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.8, 10.4, 10.9, 10.5], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.9, 10.55, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.6, 10.3, 10.7, 10.35], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # Candle 5 wicks more than halfway from 0.382 toward 0.500 and closes
    # bullish back above 0.382. The old first-touch logic could signal 0.382;
    # progressive zoning must instead arm 0.500 and wait.
    assert np.isclose(values["_FIB_ARMED_LEVEL"][5], 0.500)
    assert values["_FIB_SIGNAL_DIRECTION"][5] is None
    assert np.isnan(values["_FIB_SIGNAL_LEVEL"][5])

    # Candle 6 reaches 0.500 and closes bullish above it, but this is only the
    # first completed held reaction. It becomes eligibility evidence for the
    # next candle and cannot signal immediately.
    assert values["_FIB_SIGNAL_DIRECTION"][6] is None
    first_hold_snapshot = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    first_hold = next(item for item in first_hold_snapshot if item["selected"])
    assert first_hold["signal_held_count"] >= 1
    assert first_hold["prior_signal_held_count"] == 0
    assert first_hold["prior_hold_eligible"] is False
    assert first_hold["structural_quality_eligible"] is True
    assert first_hold["entry_valid"] is False

    # Candle 7 opens and closes above the immediately shallower 0.382 Fib
    # without touching the armed 0.500 level, which rearms a distinct reaction.
    # Candle 8 then
    # retests and holds 0.500, so the prior completed hold makes it eligible.
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None
    assert values["_FIB_SIGNAL_DIRECTION"][8] == "LONG"
    assert np.isclose(values["_FIB_SIGNAL_LEVEL"][8], 0.500)
    signal_snapshot = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    selected = next(item for item in signal_snapshot if item["selected"])
    assert selected["prior_signal_held_count"] >= 1
    assert selected["prior_hold_eligible"] is True
    assert selected["structural_quality_eligible"] is True
    assert selected["entry_valid"] is True
    assert selected["signalled"] is True




def test_held_candle_requires_open_and_close_above_armed_fib():
    # Both prices must hold the level; candle colour and 0.25 ATR rejection
    # are not required. A wick may still test the level.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.04], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.4], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.03], dtype=float)
    values = fibonacci_retracement_arrays(
        open_, high, low, close, np.ones(len(close)),
        pivot_strength=1, dominant_lookback_bars=16,
        dominant_recency_penalty=0.0, dominant_replacement_ratio=1.10,
    )
    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    selected = next(item for item in inventory if item["selected"])
    assert selected["signal_level"] == 0.5
    assert selected["signal_held_count"] == 1

def test_fib_small_rejection_counts_as_held_but_duplicate_touch_does_not():
    # Open and close above 0.500 count as the first hold, even at 0.10 ATR.
    # The following touch is in the same unrearmed episode and cannot be hold #2.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.02, 10.05], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.25, 10.4], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.10, 10.30], dtype=float)
    values = fibonacci_retracement_arrays(
        open_, high, low, close, np.ones(len(close)),
        pivot_strength=1, dominant_lookback_bars=16,
        dominant_recency_penalty=0.0, dominant_replacement_ratio=1.10,
    )
    first = next(item for item in json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6]) if item["selected"])
    assert first["signal_level"] == 0.5
    assert first["signal_held_count"] == 1
    assert np.isclose(first["last_signal_rejection_atr"], 0.10)
    duplicate = next(item for item in json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][7]) if item["selected"])
    assert duplicate["signal_held_count"] == 1
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None


def test_fib_retest_opening_below_level_resets_prior_hold():
    # Even a bullish candle that closes above 0.500 fails if it opened below.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 9.98], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.25], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.10], dtype=float)
    values = fibonacci_retracement_arrays(
        open_, high, low, close, np.ones(len(close)),
        pivot_strength=1, dominant_lookback_bars=16,
        dominant_recency_penalty=0.0, dominant_replacement_ratio=1.10,
    )
    prior = next(item for item in json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6]) if item["selected"])
    assert prior["signal_held_count"] == 1
    retest = next(item for item in json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][7]) if item["selected"])
    assert retest["prior_signal_held_count"] >= 1
    assert retest["signal_held_count"] == 0
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None


def test_fib_failed_retests_reset_clean_hold_sequence():
    # LONG 0.500 setup: candle 6 is a valid first hold, candle 7 is a weak
    # failed retest, and candle 8 is another strong hold. Candle 8 must start a
    # new sequence at hold #1 instead of becoming hold #2.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 9.98, 10.05], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.25, 10.45], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 9.95, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.10, 10.35], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    first = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    first_selected = next(item for item in first if item["selected"])
    assert first_selected["signal_held_count"] == 1

    failed = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][7])
    failed_selected = next(item for item in failed if item["selected"])
    assert failed_selected["signal_test_count"] >= 2
    assert failed_selected["signal_held_count"] == 0
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None

    later = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    later_selected = next(item for item in later if item["selected"])
    assert later_selected["signal_held_count"] == 1
    assert later_selected["prior_signal_held_count"] == 0
    assert later_selected["prior_hold_eligible"] is False
    assert values["_FIB_SIGNAL_DIRECTION"][8] is None



def test_fib_range_hover_does_not_count_as_second_reaction_episode():
    # LONG 0.500 setup. Candle 6 is a valid first hold. Candle 7 stays below
    # the immediately shallower 0.382 Fib even though it does not touch 0.500.
    # Candle 8 retests with a strong close, but it is still the same reaction
    # episode and must not become hold #2 or emit a signal.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 10.20, 10.05], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.4, 10.45], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 10.15, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.30, 10.35], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    first = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    first_selected = next(item for item in first if item["selected"])
    assert first_selected["signal_held_count"] == 1

    same_episode = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    selected = next(item for item in same_episode if item["selected"])
    assert selected["prior_signal_held_count"] >= 1
    assert selected["signal_held_count"] == 1
    assert values["_FIB_SIGNAL_DIRECTION"][8] is None



def test_fib_rearm_requires_open_and_close_beyond_shallower_level():
    # LONG 0.500 setup: after hold #1, crossing above the shallower 0.382 Fib
    # with only the close is not enough. Both open and close must be above
    # 0.382 on a non-touch candle before a later 0.500 retest can be hold #2.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 10.30, 10.05, 10.60, 10.05], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.7, 10.45, 10.8, 10.45], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 10.25, 9.95, 10.55, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.60, 10.35, 10.70, 10.35], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    first = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    first_selected = next(item for item in first if item["selected"])
    assert first_selected["signal_held_count"] == 1

    # Candle 7 closes above 0.382 (~10.472) but opens below it, so no rearm.
    not_rearmed = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    not_rearmed_selected = next(item for item in not_rearmed if item["selected"])
    assert not_rearmed_selected["signal_held_count"] == 1
    assert values["_FIB_SIGNAL_DIRECTION"][8] is None

    # Candle 9 opens and closes above 0.382 without touching 0.500; candle 10
    # can therefore become the distinct second held reaction.
    rearmed = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][10])
    rearmed_selected = next(item for item in rearmed if item["selected"])
    assert rearmed_selected["signal_held_count"] >= 2
    assert values["_FIB_SIGNAL_DIRECTION"][10] == "LONG"


def test_fib_failed_unrearmed_retest_breaks_sequence():
    # Hold #1, then a weak retest before reclaiming the shallower Fib. The weak
    # retest must reset the sequence immediately rather than preserving hold #1.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 10.02, 10.6, 10.05], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.25, 10.8, 10.45], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 9.95, 10.55, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.10, 10.65, 10.35], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    first = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][6])
    first_selected = next(item for item in first if item["selected"])
    assert first_selected["signal_held_count"] == 1

    failed = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][7])
    failed_selected = next(item for item in failed if item["selected"])
    assert failed_selected["signal_held_count"] == 0

    later = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][9])
    later_selected = next(item for item in later if item["selected"])
    assert later_selected["signal_held_count"] == 1
    assert values["_FIB_SIGNAL_DIRECTION"][9] is None



def test_fib_unrearmed_duplicate_touch_cannot_trigger_entry():
    # Build two accepted distinct holds. On candle 8, a temporarily large ATR
    # makes the 4-point impulse <2 ATR, so the second accepted hold cannot
    # signal. Candle 9 restores normal ATR and gives another strong touch in
    # the same unrearmed cluster. Under the old raw-trigger gate it would now
    # enter; the accepted-hold gate must keep it blocked.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 10.2, 10.05, 10.6, 10.05, 10.02], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 10.7, 10.5, 10.9, 10.8, 10.45], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 10.1, 9.95, 10.55, 9.95, 9.95], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 10.5, 10.30, 10.70, 10.70, 10.35], dtype=float)
    atr = np.ones(len(close))
    atr[8] = 2.2

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        minimum_impulse_atr=2.0,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    second = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    second_selected = next(item for item in second if item["selected"])
    assert second_selected["signal_held_count"] >= 2
    assert values["_FIB_SIGNAL_DIRECTION"][8] is None

    duplicate = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][9])
    duplicate_selected = next(item for item in duplicate if item["selected"])
    assert duplicate_selected["signal_held_count"] >= 2
    assert duplicate_selected["entry_valid"] is True
    assert values["_FIB_SIGNAL_DIRECTION"][9] is None

def test_fib_native_plan_uses_actual_progressive_signal_level():
    class Base:
        def _sr_stop_plan(self, i, execution_i=None):
            return {"passed": True, "applied": False, "reason": "BASE", "distance": 1.0}
        def _effective_trade_direction(self, _i):
            return "LONG"
        def _expected_entry_price(self, i, execution_i, direction):
            return 10.2

    class Probe(FibonacciRetracementMixin, Base):
        pass

    p = Probe.__new__(Probe)
    p.signal_strategy_mode = FIB_RETRACEMENT_MODE
    p.config = SimpleNamespace(
        strategy_timeframe_minutes=15,
        fib_stop_buffer_atr=0.0,
    )
    p.open = np.array([10.2])
    p.atr_values = np.array([1.0])
    p.fib_retracement = {
        # Close may still be nearest 0.382 after a bullish rejection, but the
        # progressive entry was actually armed and triggered at 0.500.
        "FIB_NEAREST_LEVEL": np.array([0.382]),
        "_FIB_SIGNAL_LEVEL": np.array([0.500]),
        "_FIB_IMPULSE_START_PRICE": np.array([8.0]),
        "_FIB_IMPULSE_END_PRICE": np.array([12.0]),
    }

    plan = p._fib_native_plan_values(0, "LONG")
    assert plan["nearest_level"] == 0.500
    assert plan["stop_level"] == 0.618
    assert np.isclose(plan["stop_boundary"], 12.0 - 0.618 * 4.0)


def test_fib_wick_through_786_invalidates_future_long_entry():
    # Confirmed LONG impulse: low@1=8.0 -> high@3=12.0.
    # 0.786 is 8.856. Candle 5 wicks below it but closes back above,
    # then candle 6 gives a bullish reaction near 0.618. The leg must stay
    # invalidated and cannot generate a later LONG signal.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 9.2, 9.4, 9.8], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 9.8, 10.0, 10.1], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 8.7, 9.3, 9.6], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 9.5, 9.8, 9.9], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    assert (12.0 - low[5]) / (12.0 - 8.0) >= 0.786
    assert values["_FIB_SIGNAL_DIRECTION"][5] is None
    assert values["_FIB_SIGNAL_DIRECTION"][6] is None
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None


def test_fib_wick_through_786_invalidates_future_short_entry():
    # Mirror case for a SHORT impulse: high@1=12.0 -> low@3=8.0.
    open_ = np.array([10.0, 11.8, 11.0, 8.5, 8.8, 10.8, 10.6, 10.2], dtype=float)
    high = np.array([10.2, 12.0, 11.2, 8.7, 9.1, 11.3, 10.7, 10.4], dtype=float)
    low = np.array([9.8, 11.6, 10.8, 8.0, 8.6, 10.2, 10.0, 10.0], dtype=float)
    close = np.array([10.0, 11.8, 11.0, 8.2, 8.9, 10.5, 10.2, 10.1], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    assert (high[5] - 8.0) / (12.0 - 8.0) >= 0.786
    assert values["_FIB_SIGNAL_DIRECTION"][5] is None
    assert values["_FIB_SIGNAL_DIRECTION"][6] is None
    assert values["_FIB_SIGNAL_DIRECTION"][7] is None


def test_inactive_candidate_keeps_786_invalidation_when_selected_later():
    # Older dominant LONG: low@1 -> high@4. Newer weaker LONG: low@8 -> high@10.
    # The newer candidate is confirmed but remains inactive while the older swing
    # still has sticky selection. Candle 12 wicks through the newer leg's 0.786
    # level without invalidating the older dominant leg. When the old leg ages
    # out of the 16-bar window, the newer candidate must not resurrect.
    close = np.array([
        14.0, 8.0, 10.0, 16.0, 20.0, 18.5, 17.0, 14.0,
        12.0, 15.0, 18.0, 16.0, 14.5, 15.0, 15.2, 15.1,
        15.3, 15.2, 15.4, 15.3, 15.2, 14.4, 15.0, 15.2,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    # Make candle 12 penetrate the newer LONG candidate's 0.786 level.
    # Newer span is low@8=11.8 -> high@10=18.2, so 0.786 ~= 13.17.
    low[12] = 13.0
    open_[12] = 14.2
    close[12] = 14.5
    high[12] = 14.8

    # Later bullish reaction around the newer leg's 0.618 level (~14.245).
    open_[21] = 14.1
    low[21] = 14.0
    high[21] = 14.8
    close[21] = 14.6

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # At candle 12, the older dominant swing is still selected, proving the
    # penetrated newer candidate was inactive when its invalidation happened.
    assert values["_FIB_IMPULSE_START_INDEX"][12] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][12] == 4

    newer_penetration = (high[10] - low[12]) / (high[10] - low[8])
    assert newer_penetration >= 0.786

    # Once the old swing ages out, the invalidated newer candidate must not be
    # resurrected as the selected entry Fib.
    assert not (
        values["_FIB_IMPULSE_START_INDEX"][21] == 8
        and values["_FIB_IMPULSE_END_INDEX"][21] == 10
    )
    assert values["_FIB_SIGNAL_DIRECTION"][21] is None


def test_inactive_candidate_keeps_progressive_zone_and_test_history():
    # Older dominant LONG: low@1 -> high@4. Newer weaker LONG: low@8 -> high@10.
    # The newer leg remains inactive at candle 12, where it penetrates far
    # enough to arm 0.500 and tests that level. When the older Fib ages out,
    # selecting the newer leg must restore that history instead of resetting it.
    close = np.array([
        14.0, 8.0, 10.0, 16.0, 20.0, 18.5, 17.0, 14.0,
        12.0, 15.0, 18.0, 16.0, 15.2, 15.4, 15.5, 15.6,
        15.7, 15.8, 15.9, 16.0, 16.1, 15.2, 15.4, 15.6,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    # Newer candidate geometry: low@8=11.8 -> high@10=18.2, so 0.500=15.0.
    # Candle 12 reaches through the 0.382->0.500 midpoint but stays shallower
    # than the midpoint to 0.618; it should permanently arm 0.500.
    open_[12] = 15.1
    low[12] = 14.9
    high[12] = 15.4
    close[12] = 15.2

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # The older structural Fib is still selected when the newer candidate's
    # state is updated, proving that the state was accumulated while inactive.
    assert values["_FIB_IMPULSE_START_INDEX"][12] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][12] == 4

    # Once the old candidate ages out, the newer valid candidate becomes active
    # with its previously armed 0.500 level and prior test count intact.
    assert values["_FIB_IMPULSE_START_INDEX"][21] == 8
    assert values["_FIB_IMPULSE_END_INDEX"][21] == 10
    assert np.isclose(values["_FIB_ARMED_LEVEL"][21], 0.500)
    assert values["FIB_TEST_COUNT"][21] >= 1.0


def test_fib_reaction_quality_rewards_respected_repeat_tests_without_linear_touch_bonus():
    # Newer LONG candidate is inactive while its 0.500 armed level is tested
    # twice with bullish closes. Reaction quality should rise because the level
    # is respected, not merely because raw test_count increased.
    close = np.array([
        14.0, 8.0, 10.0, 16.0, 20.0, 18.5, 17.0, 14.0,
        12.0, 15.0, 18.0, 16.0, 15.2, 15.3, 15.5, 15.6,
        15.7, 15.8, 15.9, 16.0, 16.1, 15.2, 15.4, 15.6,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    # Candidate low@8=11.8 -> high@10=18.2, so armed 0.500 is 15.0.
    # Candle 12 is first respected test.
    open_[12] = 15.05
    low[12] = 14.9
    high[12] = 15.4
    close[12] = 15.3
    # Candle 13 moves clearly away from the level (>0.5 ATR) without touching,
    # rearming the candidate for a genuinely distinct second reaction.
    open_[13] = 15.5
    low[13] = 15.4
    high[13] = 15.8
    close[13] = 15.6
    # Candle 14 then comes back and gives the second respected test.
    open_[14] = 15.05
    low[14] = 14.85
    high[14] = 15.5
    close[14] = 15.35

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    first_inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][12])
    second_inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][14])
    first = next(item for item in first_inventory if item["candidate_id"] == "LONG:8:10")
    second = next(item for item in second_inventory if item["candidate_id"] == "LONG:8:10")

    assert first["signal_level"] == 0.5
    assert first["signal_test_count"] == 1
    assert first["signal_held_count"] == 1
    assert first["prior_signal_held_count"] == 0
    assert first["prior_hold_eligible"] is False
    assert first["entry_valid"] is False
    # The first held reaction is visible in the audit counters immediately,
    # but it must not boost ranking on the same candle that created it.
    assert first["reaction_score"] == 0.0
    assert second["signal_test_count"] == 2
    assert second["signal_held_count"] == 2
    assert second["prior_signal_held_count"] >= 1
    assert second["prior_hold_eligible"] is True
    assert second["entry_valid"] is True
    assert second["signal_held_ratio"] == 1.0
    assert second["last_signal_rejection_atr"] > first["last_signal_rejection_atr"]
    # Candle 14 may score candle 12's completed held reaction, but not its own.
    assert second["reaction_score"] > 0.0
    assert second["reaction_score"] > first["reaction_score"]
    assert second["final_score"] > second["structural_score"] * (
        1.0 + second["confluence_score"]
    )


def test_invalidated_stronger_fib_does_not_hide_valid_secondary_candidate():
    # Build two confirmed LONG candidates. The older/stronger candidate is
    # invalidated by a deep wick, while the newer candidate remains valid.
    # Selection must move to the best valid candidate instead of keeping the
    # invalidated dominant Fib as a non-signalling blocker.
    close = np.array([
        14.0, 8.0, 10.0, 16.0, 20.0, 18.0, 16.0, 14.0,
        12.0, 15.0, 18.0, 16.0, 13.0, 15.0, 15.5, 15.8,
        16.0, 16.2,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    # At candle 12 the old low@1 -> high@4 leg is penetrated beyond 0.786.
    low[12] = 9.5
    open_[12] = 12.8
    close[12] = 13.0
    high[12] = 13.2

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    old_penetration = (high[4] - low[12]) / (high[4] - low[1])
    assert old_penetration >= 0.786

    # The invalidated old dominant leg must not remain selected after the wick.
    assert not (
        values["_FIB_IMPULSE_START_INDEX"][12] == 1
        and values["_FIB_IMPULSE_END_INDEX"][12] == 4
    )


def test_invalidated_fib_still_populates_generic_rule_evidence():
    # A sole LONG Fib is invalidated through 0.786. Entry must remain disabled,
    # but generic Fib evidence must continue to be populated on later bars.
    open_ = np.array([10.0, 8.2, 9.0, 11.5, 11.2, 9.2, 9.4, 9.8], dtype=float)
    high = np.array([10.2, 8.4, 9.2, 12.0, 11.4, 9.8, 10.0, 10.1], dtype=float)
    low = np.array([9.8, 8.0, 8.8, 11.3, 10.9, 8.7, 9.3, 9.6], dtype=float)
    close = np.array([10.0, 8.2, 9.0, 11.8, 11.1, 9.5, 9.8, 9.9], dtype=float)
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    assert values["_FIB_SIGNAL_DIRECTION"][6] is None
    assert np.isfinite(values["FIB_RETRACEMENT_DEPTH"][6])
    assert np.isfinite(values["FIB_NEAREST_LEVEL"][6])
    assert values["FIB_IMPULSE_DIRECTION"][6] == "LONG"
    assert values["FIB_REACTION_STATE"][6] != "UNKNOWN"


def test_invalid_active_extension_falls_back_to_valid_existing_leg():
    # Initial active LONG: low@1 -> high@4. A later higher high at 10 creates
    # an extension from the same anchor. On its confirmation bar (11), the wick
    # invalidates the longer extension but not the original leg. Selection must
    # therefore stay on/fall back to the valid original leg.
    close = np.array([
        14.0, 8.0, 10.0, 16.0, 20.0, 18.5, 17.5, 18.0,
        19.0, 20.5, 22.0, 18.0, 18.5, 19.0,
    ], dtype=float)
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    # Keep the confirmation-bar wick between the old leg's 0.786 threshold and
    # the longer extension's 0.786 threshold.
    low[11] = 10.7
    open_[11] = 17.8
    close[11] = 18.0
    high[11] = 18.2

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    old_penetration = (high[4] - low[11]) / (high[4] - low[1])
    extension_penetration = (high[10] - low[11]) / (high[10] - low[1])
    assert old_penetration < 0.786
    assert extension_penetration >= 0.786

    assert values["_FIB_IMPULSE_START_INDEX"][11] == 1
    assert values["_FIB_IMPULSE_END_INDEX"][11] == 4


def test_fib_candidate_state_memory_stays_bounded_by_recent_structure():
    # Repeated pivots over a long series should not make candidate lifecycle
    # memory grow with total history when the structural lookback is only 16.
    n = 320
    base = np.arange(n, dtype=float)
    close = 100.0 + np.where((base.astype(int) % 2) == 0, 2.0, -2.0)
    open_ = close.copy()
    high = close + 0.5
    low = close - 0.5
    atr = np.ones(n)

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    counts = values["_FIB_CANDIDATE_STATE_COUNT"]
    assert np.nanmax(counts) < 80
    assert counts[-1] < 80


def test_new_fib_replays_confirmation_window_invalidation():
    # low@2=8.0 -> high@6=12.0 is only confirmed at candle 8 with
    # pivot_strength=2. Candle 7 wicks through the 0.786 retracement before
    # confirmation, so the candidate must already be invalid when first exported.
    open_ = np.array([10.0, 9.5, 8.2, 9.0, 10.0, 11.0, 11.8, 9.0, 9.4, 9.6])
    high = np.array([10.4, 9.9, 8.6, 9.4, 10.4, 11.4, 12.0, 10.0, 9.8, 10.0])
    low = np.array([9.6, 9.1, 8.0, 8.7, 9.6, 10.6, 11.2, 8.5, 9.0, 9.2])
    close = np.array([10.0, 9.5, 8.2, 9.0, 10.0, 11.0, 11.8, 9.2, 9.4, 9.6])
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=2,
        dominant_lookback_bars=32,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][8])
    candidate = next(
        item for item in inventory if item["candidate_id"] == "LONG:2:6"
    )
    assert candidate["invalidated"] is True
    assert candidate["entry_valid"] is False


def test_fib_extension_competes_instead_of_overriding_stronger_active_candidate():
    # Build a dominant LONG, then a stronger/recent local LONG. A later higher
    # high creates an extension from the active local anchor, but the extension
    # is deliberately weaker because ATR is much larger on confirmation.
    close = np.array(
        [12, 8, 10, 16, 20, 18, 16, 14, 19, 18, 17, 16, 17, 18, 22, 19, 18, 18],
        dtype=float,
    )
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))
    atr[9] = 0.6   # local low@7 -> high@8 strength ~= 9 ATR
    atr[15] = 4.0  # active extension to high@14 is intentionally much weaker

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.95,
    )

    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][15])
    extension = next(
        item for item in inventory if item["candidate_id"] == "LONG:7:14"
    )
    selected = next(item for item in inventory if item["selected"])

    assert extension["entry_valid"] is False
    assert extension["prior_hold_eligible"] is False
    assert extension["structural_quality_eligible"] is False
    assert selected["candidate_id"] == "LONG:7:8"
    assert selected["structural_quality_eligible"] is True
    assert selected["live_score"] > extension["live_score"]
    assert values["_FIB_SELECTED_CANDIDATE_ID"][15] == "LONG:7:8"


def test_fib_local_replacement_default_is_five_percent_and_invalidates_old_cache():
    assert FIB_DOMINANT_REPLACEMENT_RATIO == 1.05
    assert FIB_MINIMUM_STRUCTURAL_COMPETITION_RATIO == 0.70
    assert FIB_MINIMUM_HOLD_REJECTION_ATR == 0.25
    assert FIB_RESEARCH_CONTEXT_VERSION == 21


def test_fib_tracks_recent_local_long_subswing_alongside_dominant_anchor():
    close = np.array(
        [12, 8, 10, 16, 20, 18, 16, 14, 16, 18, 19, 17, 16],
        dtype=float,
    )
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=1,
        dominant_lookback_bars=32,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # high@10 is confirmed on candle 11. The large Fib can still originate
    # from low@1, but the most recent confirmed local low@7 must also become
    # an independent candidate for the same high.
    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][11])
    ids = {item["candidate_id"] for item in inventory}
    assert "LONG:1:10" in ids
    assert "LONG:7:10" in ids

    local = next(item for item in inventory if item["candidate_id"] == "LONG:7:10")
    assert local["start_price"] == low[7]
    assert local["end_price"] == high[10]
    assert local["entry_valid"] is False
    assert local["prior_hold_eligible"] is False


def test_fib_rsi_confluence_resets_when_armed_level_advances():
    # Candidate first tests 0.382 with bullish RSI divergence, then a deeper
    # wick advances the armed level to 0.500 without touching that new level.
    # The old 0.382 RSI test must not continue to boost the candidate.
    open_ = np.array([10.0, 8.0, 9.0, 10.0, 12.0, 11.0, 10.5, 9.6, 10.0], dtype=float)
    high = np.array([10.2, 8.2, 9.2, 10.2, 12.2, 11.2, 10.8, 10.1, 10.2], dtype=float)
    low = np.array([9.8, 7.8, 8.8, 9.8, 11.8, 10.8, 10.0, 9.5, 9.8], dtype=float)
    close = np.array([10.0, 8.0, 9.0, 10.0, 12.0, 11.0, 10.6, 9.8, 10.0], dtype=float)
    atr = np.ones(len(close))
    ema50 = np.full(len(close), np.nan)
    ema100 = np.full(len(close), np.nan)
    ema200 = np.full(len(close), np.nan)
    rsi_values = np.array([50, 40, 45, 48, 55, 50, 52, 60, 58], dtype=float)

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        ema_50_values=ema50,
        ema_100_values=ema100,
        ema_200_values=ema200,
        rsi_values=rsi_values,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.0,
    )

    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][7])
    candidate = next(item for item in inventory if item["candidate_id"] == "LONG:1:4")
    assert candidate["signal_level"] == 0.5
    assert candidate["rsi_divergence"] in {"UNKNOWN", "NONE"}
    assert candidate["confluence_score"] == 0.0


def test_fib_candidate_confluence_can_promote_close_structural_competitor():
    # Two bullish candidates share the same high but have close structural
    # strength. The recent/local Fib is slightly weaker structurally, while its
    # armed 0.382 level sits directly on EMA100 and the dominant Fib does not.
    close = np.array(
        [10.0, 8.0, 9.0, 10.0, 11.0, 10.0, 9.2, 8.1, 9.5, 10.5, 12.0, 10.4],
        dtype=float,
    )
    open_ = close.copy()
    high = close + 0.1
    low = close - 0.1
    low[1] = 8.0
    low[7] = 8.1
    high[10] = 12.0
    atr = np.ones(len(close))
    atr[11] = 0.1

    # At candle 11 the local Fib's 0.382 level is:
    # 12 - .382 * (12 - 8.1) = 10.5102. The dominant candidate's same
    # level is 10.472, which is 0.382 ATR away at ATR=0.1 and therefore
    # outside the 0.25 ATR confluence window. This leaves the local Fib only
    # 2.5% weaker structurally, so its 3% EMA100 bonus can legitimately win.
    ema50 = np.full(len(close), np.nan)
    ema100 = np.full(len(close), np.nan)
    ema200 = np.full(len(close), np.nan)
    ema100[11] = 10.5102
    rsi_values = np.full(len(close), 50.0)

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=1,
        ema_50_values=ema50,
        ema_100_values=ema100,
        ema_200_values=ema200,
        rsi_values=rsi_values,
        dominant_lookback_bars=32,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.0,
    )

    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][11])
    dominant = next(item for item in inventory if item["candidate_id"] == "LONG:1:10")
    local = next(item for item in inventory if item["candidate_id"] == "LONG:7:10")

    assert dominant["structural_score"] > local["structural_score"]
    assert dominant["confluence_score"] == 0.0
    assert local["confluence_score"] >= 0.03
    assert local["ema_100_distance_atr"] <= 0.25
    assert local["final_score"] > dominant["final_score"]
    assert local["selected"] is True
    assert values["_FIB_SELECTED_CANDIDATE_ID"][11] == "LONG:7:10"


def test_fib_tracks_recent_local_short_subswing_alongside_dominant_anchor():
    close = np.array(
        [12, 20, 18, 14, 10, 12, 14, 16, 14, 12, 11, 13, 14],
        dtype=float,
    )
    open_ = close.copy()
    high = close + 0.2
    low = close - 0.2
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_,
        high,
        low,
        close,
        atr,
        pivot_strength=1,
        dominant_lookback_bars=32,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    # low@10 is confirmed on candle 11. Track both dominant high@1 and
    # recent local high@7 as independent SHORT candidates.
    inventory = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][11])
    ids = {item["candidate_id"] for item in inventory}
    assert "SHORT:1:10" in ids
    assert "SHORT:7:10" in ids

    local = next(item for item in inventory if item["candidate_id"] == "SHORT:7:10")
    assert local["start_price"] == high[7]
    assert local["end_price"] == low[10]
    assert local["entry_valid"] is False
    assert local["prior_hold_eligible"] is False


def test_fib_candidate_inventory_exposes_all_candidates_and_selected_leg():
    open_ = np.array([14.0, 8.0, 10.0, 16.0, 20.0, 18.0, 14.0, 12.0, 15.0, 18.0, 16.0, 15.0], dtype=float)
    high = open_ + 0.2
    low = open_ - 0.2
    close = open_.copy()
    atr = np.ones(len(close))

    values = fibonacci_retracement_arrays(
        open_, high, low, close, atr,
        pivot_strength=1,
        dominant_lookback_bars=16,
        dominant_recency_penalty=0.0,
        dominant_replacement_ratio=1.10,
    )

    payload = json.loads(values["_FIB_CANDIDATE_INVENTORY_JSON"][11])
    assert len(payload) >= 2
    assert sum(bool(item["selected"]) for item in payload) == 1
    selected = next(item for item in payload if item["selected"])
    assert values["_FIB_SELECTED_CANDIDATE_ID"][11] == selected["candidate_id"]
    assert {
        "candidate_id", "direction", "start_index", "end_index",
        "start_price", "end_price", "structural_strength_atr",
        "live_score", "structural_score", "confluence_score", "reaction_score",
        "final_score", "ema_50_distance_atr", "ema_100_distance_atr",
        "ema_200_distance_atr", "rsi_divergence", "rsi_divergence_code",
        "signal_test_count", "signal_held_count", "signal_held_ratio",
        "last_signal_rejection_atr", "bars_since_signal_test",
        "signal_level", "test_count", "invalidated",
        "prior_signal_held_count", "prior_hold_eligible",
        "structural_quality_eligible", "entry_valid", "selected",
    } <= set(selected)
