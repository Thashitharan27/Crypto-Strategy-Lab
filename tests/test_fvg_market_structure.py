import numpy as np

from crypto_strategy_lab.fair_value_gap import (
    _fvg_market_structure_features,
    first_revisit_context,
)


def test_market_structure_events_are_causal_and_not_repeated():
    high = np.array([10.0, 12.0, 11.0, 13.0, 10.0, 9.0, 9.5])
    low = np.array([8.0, 9.0, 8.5, 10.0, 8.0, 7.5, 8.0])
    open_ = np.array([9.0, 10.0, 10.0, 11.0, 9.5, 8.8, 8.2])
    close = np.array([9.5, 11.0, 9.0, 12.5, 9.0, 8.0, 9.0])
    atr = np.ones(len(close))

    features = _fvg_market_structure_features(
        high, low, open_, close, atr, swing_strength=1
    )

    # Swing high 12 is confirmed at candle 2, then broken once at candle 3.
    assert features["bos_long"][3] == 1.0
    assert np.sum(features["bos_long"]) == 1.0

    # Candle 4 wicks below the latest confirmed swing low and closes back above.
    assert features["sweep_long"][4] == 1.0
    assert features["bars_since_sweep_long"][4] == 0.0

    # Candle 5 closes below that swing after the bullish break: bearish CHoCH.
    assert features["choch_short"][5] == 1.0
    assert features["bars_since_choch_short"][5] == 0.0
    assert np.isnan(features["bars_since_bos_long"][5])


def test_market_structure_prefix_does_not_depend_on_future_candles():
    high = np.array([10.0, 12.0, 11.0, 13.0, 10.0, 9.0, 9.5])
    low = np.array([8.0, 9.0, 8.5, 10.0, 8.0, 7.5, 8.0])
    open_ = np.array([9.0, 10.0, 10.0, 11.0, 9.5, 8.8, 8.2])
    close = np.array([9.5, 11.0, 9.0, 12.5, 9.0, 8.0, 9.0])
    atr = np.ones(len(close))

    whole = _fvg_market_structure_features(
        high, low, open_, close, atr, swing_strength=1
    )
    for end in range(1, len(close) + 1):
        prefix = _fvg_market_structure_features(
            high[:end], low[:end], open_[:end], close[:end], atr[:end],
            swing_strength=1,
        )
        for key in whole:
            assert np.allclose(
                prefix[key], whole[key][:end], equal_nan=True
            ), key


def test_fvg_revisit_carries_formation_displacement_not_revisit_displacement():
    high = [10, 12, 13, 12.5, 14, 13, 12]
    low = [9, 10, 11, 11.5, 12, 10.5, 10]
    open_ = [9.2, 10.5, 11.2, 12.0, 12.2, 12.9, 11.5]
    close = [9.5, 11, 12, 12.2, 13, 11.5, 11]
    atr = [1, 1, 2, 2, 2, 10, 10]

    _, features, _, _ = first_revisit_context(
        high, low, close, atr, open_=open_, swing_strength=1
    )
    bullish = features["LONG"]

    # The gap forms at candle 2 and revisits at candle 5. Evidence must remain
    # anchored to the formation candle, not the later outcome/revisit candle.
    assert np.isclose(bullish["FVG_DISPLACEMENT_BODY_ATR"][5], 0.4)
    assert np.isclose(bullish["FVG_DISPLACEMENT_BODY_RATIO"][5], 0.4)
    assert np.isclose(bullish["FVG_DISPLACEMENT_CLOSE_LOCATION"][5], 0.5)
