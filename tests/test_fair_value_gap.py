import numpy as np
import pandas as pd

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.fair_value_gap import (
    FairValueGapMixin,
    first_revisit_context,
    first_revisit_signals,
    higher_timeframe_fvg_context_alignment,
)
from crypto_strategy_lab.gui.rule_strategy_builder import EVIDENCE_LABELS
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    infer_direction_mode,
)


def test_first_revisit_is_after_formation_and_only_once():
    high = [10, 12, 13, 12.5, 14, 13, 12]
    low = [9, 10, 11, 11.5, 12, 10.5, 10]
    close = [9.5, 11, 12, 12.2, 13, 11.5, 11]
    signals = first_revisit_signals(high, low, close)
    # Gap (10, 11) forms on candle 2. The first revisit at candle 5
    # closes back above the gap; the next touch cannot signal again.
    assert list(signals) == [None, None, None, None, None, "LONG", None]


def test_bearish_revisit_and_no_future_knowledge():
    high = [12, 11, 10, 10.5, 11.5]
    low = [11, 9, 8, 8.5, 9]
    close = [11.5, 10, 9, 9, 9.5]
    assert first_revisit_signals(high, low, close)[3] == "SHORT"
    for end in range(1, len(close) + 1):
        whole = first_revisit_signals(high, low, close)
        prefix = first_revisit_signals(high[:end], low[:end], close[:end])
        assert np.array_equal(prefix, whole[:end])


def test_fvg_mode_round_trips_through_compiled_profiles():
    strategy, _ = compile_profiles(
        direction_mode="FAIR_VALUE_GAP",
        market_permissions=MARKET_PERMISSIONS,
    )
    assert infer_direction_mode(strategy) == "FAIR_VALUE_GAP"


def test_revisit_filters_use_formation_atr_and_first_touch():
    high = [10, 12, 13, 12.5, 14, 13, 12]
    low = [9, 10, 11, 11.5, 12, 10.5, 10]
    close = [9.5, 11, 12, 12.2, 13, 11.5, 11]
    atr = [1, 1, 2, 2, 2, 10, 10]
    _, features, boundaries, targets = first_revisit_context(high, low, close, atr)
    bullish = features["LONG"]
    assert bullish["FVG_GAP_SIZE_ATR"][5] == 0.5
    assert bullish["FVG_AGE_BARS"][5] == 3
    assert bullish["FVG_REVISIT_DEPTH_PCT"][5] == 0.5
    assert np.isnan(bullish["FVG_AGE_BARS"][6])
    assert boundaries["LONG"][5] == 10
    assert targets["LONG"][5] == 14


def test_fvg_stop_is_beyond_box_and_next_open_gap_through_is_rejected():
    class Base:
        def _effective_trade_direction(self, i):
            return self.direction

        def _expected_entry_price(self, i, execution_i, direction):
            return self.entry

        def _profile_context(self, i):
            return None, None, None, self.profile

    class Probe(FairValueGapMixin, Base):
        pass

    class Config:
        strategy_timeframe_minutes = 15
        fvg_target_buffer_atr = 0.05

    class Profile:
        reward_risk_ratio = 2.0

    probe = Probe()
    probe.config = Config()
    probe.signal_strategy_mode = "FAIR_VALUE_GAP"
    probe.profile = Profile()
    probe.direction = "LONG"
    probe.entry = 11.5
    probe.atr_values = np.array([2.0])
    probe.fvg_stop_boundaries = {"LONG": np.array([10.0]), "SHORT": np.array([12.0])}
    probe.fvg_target_boundaries = {"LONG": np.array([16.4]), "SHORT": np.array([3.0])}
    probe.open = np.array([11.5, 9.0])
    long_plan = probe._sr_stop_plan(0)
    assert np.isclose(long_plan["stop_price"], 9.9)
    assert np.isclose(long_plan["distance"], 1.6)
    assert probe._fvg_target_plan(0)["target_r"] == 2.0
    assert probe._sr_stop_plan(0, 1)["reason"] == "FVG_ENTRY_GAPPED_THROUGH_STOP"

    probe.direction = "SHORT"
    probe.entry = 10.0
    short_plan = probe._sr_stop_plan(0)
    assert np.isclose(short_plan["stop_price"], 12.1)
    assert np.isclose(short_plan["distance"], 2.1)
    assert probe._fvg_target_plan(0)["target_r"] == 2.0

    probe.fvg_target_boundaries["SHORT"][0] = 8.8
    assert probe._fvg_target_plan(0)["reason"] == "FVG_TARGET_INSUFFICIENT_ROOM"


def test_fvg_target_uses_selected_r_and_requires_buffered_room():
    class Profile:
        reward_risk_ratio = 1.0

    class Base:
        def _effective_trade_direction(self, i):
            return "LONG"

        def _expected_entry_price(self, i, execution_i, direction):
            return 11.5

        def _profile_context(self, i):
            return None, None, None, self.profile

    class Probe(FairValueGapMixin, Base):
        pass

    class Config:
        strategy_timeframe_minutes = 15
        fvg_target_buffer_atr = 0.05

    probe = Probe()
    probe.config = Config()
    probe.profile = Profile()
    probe.signal_strategy_mode = "FAIR_VALUE_GAP"
    probe.atr_values = np.array([2.0])
    probe.fvg_stop_boundaries = {"LONG": np.array([10.0]), "SHORT": np.array([12.0])}
    probe.fvg_target_boundaries = {"LONG": np.array([16.4]), "SHORT": np.array([3.0])}
    probe.open = np.array([11.5])

    for selected_r in (1.0, 2.0, 3.0):
        probe.profile.reward_risk_ratio = selected_r
        plan = probe._fvg_target_plan(0)
        assert plan["passed"]
        assert plan["target_r"] == selected_r
        assert np.isclose(plan["limit_price"], 16.3)

    probe.config.fvg_target_buffer_atr = 0.20
    assert np.isclose(probe._fvg_target_plan(0)["limit_price"], 16.0)

    probe.config.fvg_target_buffer_atr = 0.05
    probe.fvg_target_boundaries["LONG"][0] = 16.3
    assert probe._fvg_target_plan(0)["reason"] == "FVG_TARGET_INSUFFICIENT_ROOM"


def test_fvg_stop_boundary_distance_rule_is_execution_aware_and_exposed():
    indicator = "FVG_STOP_BOUNDARY_DISTANCE_ATR"
    assert indicator in RULE_INDICATORS
    assert EVIDENCE_LABELS[indicator] == "FVG Stop-Boundary Distance / ATR"

    class Base:
        def _expected_entry_price(self, i, execution_i, direction):
            index = i if execution_i is None else execution_i
            return float(self.open[index])

    class Probe(FairValueGapMixin, Base):
        pass

    probe = Probe()
    probe.open = np.array([11.0, 12.0])
    probe.atr_values = np.array([2.0, 2.0])
    probe.fvg_stop_boundaries = {
        "LONG": np.array([10.0, np.nan]),
        "SHORT": np.array([14.0, np.nan]),
    }
    probe._fvg_rule_execution_i = 1

    assert probe._strategy_profile_rule_value(0, "LONG", None, indicator) == 1.0
    assert probe._strategy_profile_rule_value(0, "SHORT", None, indicator) == 1.0

    probe._fvg_rule_execution_i = None
    assert probe._strategy_profile_rule_value(0, "LONG", None, indicator) == 0.5



def test_higher_timeframe_fvg_context_is_causal_and_overlap_gated():
    times = np.array(
        pd.date_range("2026-01-01T00:00:00Z", periods=14, freq="15min")
        .tz_localize(None)
        .to_numpy()
    )
    # Three complete 1h candles are formed by the first 12 strategy bars.
    # Hour 3 has a bullish FVG over hour 1: low(3)=102 > high(1)=100.
    high = np.array(
        [100, 99, 98, 97, 106, 108, 109, 110, 106, 107, 108, 109, 101.8, 100.2],
        dtype=float,
    )
    low = np.array(
        [95, 96, 96, 95, 103, 104, 105, 105, 102, 103, 104, 103, 100.5, 98.5],
        dtype=float,
    )
    close = np.array(
        [98, 98, 97, 96, 105, 107, 108, 109, 104, 105, 106, 107, 101.2, 99.0],
        dtype=float,
    )

    context = higher_timeframe_fvg_context_alignment(
        times, high, low, close, strategy_minutes=15, context_minutes=60
    )

    # The 1h FVG is unavailable until the third 1h formation candle closes.
    assert np.all(context["LONG"][:12] == 0.0)
    # First strategy bar after the completed HTF candle overlaps 100-102.
    assert context["LONG"][12] == 1.0
    # A close below the bullish context invalidates it on the next bar.
    assert context["LONG"][13] == 0.0
    assert np.all(context["SHORT"] == 0.0)


def test_fvg_direction_can_require_higher_timeframe_context():
    class Base:
        def _selected_direction(self, i):
            return "BASE"

    class Probe(FairValueGapMixin, Base):
        pass

    p = Probe()
    p.signal_strategy_mode = "FAIR_VALUE_GAP"
    p.config = type("Cfg", (), {"fvg_context_enabled": True})()
    p.fvg_first_revisit = np.array(["LONG", "LONG"], dtype=object)
    p.fvg_htf_context = {
        "LONG": np.array([0.0, 1.0]),
        "SHORT": np.array([0.0, 0.0]),
    }
    assert p._selected_direction(0) is None
    assert p._selected_direction(1) == "LONG"


def test_higher_timeframe_context_rule_is_exposed():
    assert "FVG_HTF_CONTEXT_ALIGNED" in RULE_INDICATORS
    assert EVIDENCE_LABELS["FVG_HTF_CONTEXT_ALIGNED"] == "Higher-TF FVG Context Aligned (0/1)"
