from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_core.rules import RULE_INDICATORS
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    is_context_timeframe_evidence,
    rule_value_options,
)
from crypto_strategy_lab.volume_profile import (
    VOLUME_PROFILE_RULE_INDICATORS,
    VolumeProfileMixin,
    _profile_snapshot,
)


class Probe(VolumeProfileMixin):
    pass


def _probe(*, minutes=60, count=80):
    engine = Probe()
    engine.config = SimpleNamespace(
        strategy_timeframe_minutes=minutes,
        volume_profile_lookback_bars=20,
        volume_profile_bins=24,
        volume_profile_value_area_fraction=0.70,
    )
    engine.times = pd.date_range(
        "2026-01-01", periods=count, freq=f"{minutes}min", tz="UTC"
    ).to_numpy()
    base = 100.0 + np.sin(np.arange(count) / 7.0)
    engine.open = base - 0.1
    engine.high = base + 0.7
    engine.low = base - 0.7
    engine.close = base + 0.1
    engine.volume = np.full(count, 10.0)
    engine.atr_values = np.full(count, 1.0)
    engine.research_features = {}
    return engine


def test_volume_profile_rule_contract_is_registered():
    assert VOLUME_PROFILE_RULE_INDICATORS <= set(RULE_INDICATORS)
    assert is_context_timeframe_evidence("VP_POSITION")
    assert rule_value_options("VP_POSITION") == (
        "ABOVE_VAH", "INSIDE_VALUE", "BELOW_VAL"
    )
    assert CATEGORICAL_VALUE_CODES["VP_VALUE_MIGRATION"] == {
        "UP": 1.0, "DOWN": 2.0, "FLAT": 3.0
    }


def test_profile_uses_only_completed_bars_before_decision():
    left = _probe()
    right = _probe()
    decision_i = 50

    # A huge future print must not alter the historical decision snapshot.
    right.volume[decision_i:] = 1_000_000.0
    right.high[decision_i:] += 50.0
    right.low[decision_i:] += 50.0
    right.close[decision_i:] += 50.0

    a = _profile_snapshot(left, decision_i, "LONG", 60)
    b = _profile_snapshot(right, decision_i, "LONG", 60)
    assert a is not None and b is not None
    for key in (
        "VP_POC_DISTANCE_ATR",
        "VP_HVN_DISTANCE_ATR",
        "VP_ACCUMULATION_SCORE",
        "VP_LOW_VOLUME_PATH_SCORE",
    ):
        assert a[key] == pytest.approx(b[key], nan_ok=True)


def test_higher_timeframe_profile_ignores_incomplete_context_bucket():
    engine = _probe(minutes=15, count=120)
    decision_i = 101  # 01:15 into the current 1h bucket.
    baseline = _profile_snapshot(engine, decision_i, "LONG", 60)
    assert baseline is not None

    changed = _probe(minutes=15, count=120)
    # Mutate strategy candles at/after the decision; none are completed input.
    changed.volume[decision_i:] = 1_000_000.0
    changed.high[decision_i:] += 25.0
    changed.low[decision_i:] += 25.0
    changed.close[decision_i:] += 25.0
    candidate = _profile_snapshot(changed, decision_i, "LONG", 60)
    assert candidate is not None
    assert candidate["VP_POC_DISTANCE_ATR"] == pytest.approx(
        baseline["VP_POC_DISTANCE_ATR"]
    )


def test_rule_value_supports_strategy_and_higher_timeframe_context():
    engine = _probe(minutes=15, count=160)
    strategy_value = engine._volume_profile_rule_value(
        140, "LONG", "VP_ACCUMULATION_SCORE", 0
    )
    htf_value = engine._volume_profile_rule_value(
        140, "LONG", "VP_ACCUMULATION_SCORE", 60
    )
    assert np.isfinite(strategy_value)
    assert np.isfinite(htf_value)
    assert 0.0 <= strategy_value <= 100.0
    assert 0.0 <= htf_value <= 100.0


def test_position_and_near_hvn_are_categorical_native_codes():
    engine = _probe()
    position = engine._volume_profile_rule_value(50, "LONG", "VP_POSITION", 0)
    near = engine._volume_profile_rule_value(50, "LONG", "VP_NEAR_HVN", 0)
    assert position in CATEGORICAL_VALUE_CODES["VP_POSITION"].values()
    assert near in {0.0, 1.0}
