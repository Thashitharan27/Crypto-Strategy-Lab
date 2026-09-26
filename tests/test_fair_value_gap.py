import numpy as np

from crypto_strategy_lab.fair_value_gap import FairValueGapMixin, first_revisit_context, first_revisit_signals
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

    probe.fvg_target_boundaries["LONG"][0] = 16.3
    assert probe._fvg_target_plan(0)["reason"] == "FVG_TARGET_INSUFFICIENT_ROOM"
