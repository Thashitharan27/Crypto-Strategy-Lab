from types import SimpleNamespace

import numpy as np

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.ema_pullback import EMA_920_MODE, Ema920PullbackMixin
from crypto_strategy_lab.gui.rule_strategy_builder import DIRECTION_LABELS, EVIDENCE_LABELS
from crypto_strategy_lab.gui.v2_main_window import STRATEGY_TIMEFRAMES
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    infer_direction_mode,
)


def test_ema_920_strategy_is_first_class_authoring_option():
    strategy, _execution = compile_profiles(
        direction_mode=EMA_920_MODE,
        market_permissions=MARKET_PERMISSIONS,
    )
    assert infer_direction_mode(strategy) == EMA_920_MODE
    assert all(
        any(rule.get("_strategy_direction_mode") == EMA_920_MODE for rule in profile.entry_rules)
        for profile in strategy.values()
    )
    assert DIRECTION_LABELS[EMA_920_MODE] == "EMA 9/20 Pullback — Scalping"


def test_ema_920_evidence_and_scalping_timeframes_are_exposed():
    expected = {
        "EMA_9_DISTANCE_ATR", "EMA_20_DISTANCE_ATR", "EMA_9_20_SPREAD_ATR",
        "EMA_9_SLOPE_ATR", "EMA_20_SLOPE_ATR",
        "VOLUME_RATIO_20", "VOLUME_CHANGE_PCT",
    }
    assert expected <= set(RULE_INDICATORS)
    assert expected <= set(EVIDENCE_LABELS)
    assert STRATEGY_TIMEFRAMES[:2] == ("1m", "5m")


class _Base:
    def _configure_signal_features(self):
        return None

    def _infer_signal_strategy_mode(self):
        return "DI"

    def _selected_direction(self, _i):
        return "LONG"


class _Engine(Ema920PullbackMixin, _Base):
    pass


def _signal_engine():
    engine = _Engine()
    n = 30
    engine.config = SimpleNamespace(strategy_profiles={})
    engine.close = np.linspace(100.0, 103.0, n)
    engine.open = engine.close - 0.05
    engine.high = engine.close + 0.20
    engine.low = engine.close - 0.20
    engine.volume = np.full(n, 100.0)
    engine.atr_values = np.ones(n)
    engine._configure_signal_features()
    engine.signal_strategy_mode = EMA_920_MODE
    return engine


def test_ema_920_signal_requires_low_volume_pullback_then_volume_return():
    engine = _signal_engine()
    i = 25
    previous = i - 1
    # Force an unambiguous rising EMA trend and one pullback candle overlapping the band.
    engine.ema_9_values[i] = 102.0
    engine.ema_20_values[i] = 101.5
    engine.ema_9_values[previous] = 101.8
    engine.ema_20_values[previous] = 101.4
    engine.ema_9_slope_atr[i] = 0.2
    engine.ema_20_slope_atr[i] = 0.1
    engine.low[previous] = 101.6
    engine.high[previous] = 102.0
    engine.close[previous] = 101.6
    engine.volume_ratio_20[previous] = 0.7
    engine.volume[previous] = 70.0
    engine.volume[i] = 120.0
    engine.open[i] = 102.05
    engine.close[i] = 102.30
    assert engine._selected_direction(i) == "LONG"

    engine.volume[i] = 60.0
    assert engine._selected_direction(i) is None


def test_latest_micro_swing_uses_only_confirmed_pivots():
    engine = _signal_engine()
    engine.low[:] = 10.0
    engine.high[:] = 20.0
    # Pivot low at 10 is confirmed by bars 11 and 12; a newer low at 14 is not
    # a pivot because its right-hand confirmation bars are lower/equal.
    engine.low[8:13] = [9.0, 8.0, 5.0, 8.0, 9.0]
    swing = engine._latest_confirmed_micro_swing(14, "LONG")
    assert swing == (10, 5.0)
