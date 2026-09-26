import numpy as np

from crypto_strategy_lab.fair_value_gap import first_revisit_context, first_revisit_signals
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
    _, features = first_revisit_context(high, low, close, atr)
    bullish = features["LONG"]
    assert bullish["FVG_GAP_SIZE_ATR"][5] == 0.5
    assert bullish["FVG_AGE_BARS"][5] == 3
    assert bullish["FVG_REVISIT_DEPTH_PCT"][5] == 0.5
    assert np.isnan(bullish["FVG_AGE_BARS"][6])
