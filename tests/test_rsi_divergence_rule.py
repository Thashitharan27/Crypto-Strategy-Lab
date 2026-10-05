from types import SimpleNamespace

import numpy as np

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_RULE_VALUES,
    CATEGORICAL_VALUE_CODES,
    rule_value_options,
)


def _engine(lows, highs, rsi_values):
    engine = object.__new__(BacktestEngine)
    engine.low = np.asarray(lows, dtype=float)
    engine.high = np.asarray(highs, dtype=float)
    engine.profile_rsi_values = {14: np.asarray(rsi_values, dtype=float)}
    return engine


def test_rsi_divergence_rule_contract_is_registered():
    assert "RSI_DIVERGENCE" in RULE_INDICATORS
    assert CATEGORICAL_RULE_VALUES["RSI_DIVERGENCE"] == ("BULLISH", "BEARISH", "NONE")
    assert CATEGORICAL_VALUE_CODES["RSI_DIVERGENCE"] == {
        "BULLISH": 1.0, "BEARISH": 2.0, "NONE": 3.0
    }
    assert rule_value_options("RSI_DIVERGENCE") == ("BULLISH", "BEARISH", "NONE")


def test_rsi_divergence_detects_causal_bullish_regular_divergence():
    # Current bar makes a lower low than the prior window, while RSI is >2
    # points above the RSI observed at that prior price low.
    lows = [110, 109, 108, 107, 106, 100, 104, 103, 102, 101, 99]
    highs = [x + 8 for x in lows]
    rsi_values = [55, 52, 49, 46, 43, 25, 35, 36, 37, 38, 31]
    engine = _engine(lows, highs, rsi_values)
    profile = SimpleNamespace(rsi_period=14)

    assert engine._strategy_profile_rule_value(
        10, "LONG", profile, "RSI_DIVERGENCE"
    ) == 1.0


def test_rsi_divergence_detects_causal_bearish_regular_divergence():
    highs = [90, 91, 92, 93, 94, 100, 96, 97, 98, 99, 101]
    lows = [x - 8 for x in highs]
    rsi_values = [45, 48, 51, 54, 57, 75, 65, 64, 63, 62, 69]
    engine = _engine(lows, highs, rsi_values)
    profile = SimpleNamespace(rsi_period=14)

    assert engine._strategy_profile_rule_value(
        10, "SHORT", profile, "RSI_DIVERGENCE"
    ) == 2.0


def test_rsi_divergence_uses_only_current_and_prior_bars():
    lows = [110, 109, 108, 107, 106, 100, 104, 103, 102, 101, 99, 80]
    highs = [x + 8 for x in lows]
    rsi_values = [55, 52, 49, 46, 43, 25, 35, 36, 37, 38, 31, 90]
    profile = SimpleNamespace(rsi_period=14)

    full = _engine(lows, highs, rsi_values)
    truncated = _engine(lows[:11], highs[:11], rsi_values[:11])
    assert full._strategy_profile_rule_value(
        10, "LONG", profile, "RSI_DIVERGENCE"
    ) == truncated._strategy_profile_rule_value(
        10, "LONG", profile, "RSI_DIVERGENCE"
    )
