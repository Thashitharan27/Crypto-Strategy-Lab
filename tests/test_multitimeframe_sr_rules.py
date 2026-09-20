from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import pandas as pd

from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.data.backtest_service import (
    _independent_sr_research_features,
    _sr_research_targets,
)
from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    new_rule,
    normalize_rule,
)


def _sr_frame(room: float) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=2, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": times,
            "available_at": times + pd.Timedelta(minutes=15),
            "long_room_in_direction_atr": [room, room],
            "short_room_in_direction_atr": [room + 1.0, room + 1.0],
            "long_support_state": ["SUPPORT_TESTING", "SUPPORT_HELD"],
            "short_support_state": ["NO_SUPPORT_NEARBY", "APPROACHING_SUPPORT"],
            "sr_completed_candle_time": times + pd.Timedelta(minutes=15),
        }
    )


def test_new_sr_rule_defaults_to_strategy_tf_but_legacy_rule_stays_configured() -> None:
    new = new_rule(kind="REQUIRED", evidence="SR_ROOM_IN_DIRECTION_ATR")
    assert new["sr_timeframe_minutes"] == 0

    legacy = normalize_rule(
        {
            "kind": "REQUIRED",
            "evidence": "SR_ROOM_IN_DIRECTION_ATR",
            "operator": "GTE",
            "value": 3.0,
            "value2": 0.0,
            "regime": "ALL",
            "side": "LONG",
        }
    )
    assert legacy["sr_timeframe_minutes"] is None


def test_sr_rule_timeframe_must_be_strategy_or_compatible_higher_tf() -> None:
    base = ResearchRunConfig()
    profiles = dict(base.strategy.profiles)
    profiles["bull_long"] = replace(
        profiles["bull_long"],
        entry_rules=(
            {
                "indicator": "SR_ROOM_IN_DIRECTION_ATR",
                "_builder_sr_timeframe_minutes": 60,
            },
        ),
    )
    config = replace(
        base,
        data=replace(
            base.data,
            strategy_timeframe_minutes=240,
            intrabar_timeframe_minutes=1,
        ),
        strategy=replace(base.strategy, profiles=profiles),
    )
    with pytest.raises(ValueError, match="compatible higher timeframe"):
        config.validate()


def test_sr_research_targets_keep_timeframes_independent_and_higher_only() -> None:
    assert _sr_research_targets(15) == (
        (15, "strategy"),
        (60, "1h"),
        (240, "4h"),
        (1440, "1d"),
    )
    assert _sr_research_targets(60) == (
        (60, "strategy"),
        (240, "4h"),
        (1440, "1d"),
    )
    assert _sr_research_targets(240) == (
        (240, "strategy"),
        (1440, "1d"),
    )
    assert _sr_research_targets(1440) == ((1440, "strategy"),)


def test_independent_sr_frames_get_separate_output_namespaces(tmp_path) -> None:
    primary = _sr_frame(1.5)
    calls: list[int] = []

    class Registry:
        def dependency_order(self, requested):
            assert requested == ["support_resistance"]
            return ("core_directional", "support_resistance")

        def execute(self, requested, request, datasets, *, parameters, cache):
            del request, datasets, cache
            assert requested == ["support_resistance"]
            minutes = int(parameters["support_resistance"]["sr_timeframe_minutes"])
            calls.append(minutes)
            return {"support_resistance": _sr_frame(minutes / 60.0)}

    progress_events = []
    store = SimpleNamespace(
        cache=SimpleNamespace(root=tmp_path),
        progress_callback=progress_events.append,
    )
    result = _independent_sr_research_features(
        store,
        Registry(),
        SimpleNamespace(),
        pd.DataFrame(),
        {
            "core_directional": {"atr_period": 14, "adx_period": 14},
            "support_resistance": {
                "atr_period": 14,
                "sr_timeframe_minutes": 15,
            },
        },
        primary,
        strategy_minutes=15,
    )

    assert tuple(result) == (
        "support_resistance_strategy",
        "support_resistance_1h",
        "support_resistance_4h",
        "support_resistance_1d",
    )
    assert calls == [60, 240, 1440]
    labels = [event.get("label") for event in progress_events]
    assert "S/R 15m ready" in labels
    assert "Preparing S/R 1h" in labels
    assert "S/R 1h ready" in labels
    assert "Preparing S/R 4h" in labels
    assert "S/R 4h ready" in labels
    assert "Preparing S/R 1d" in labels
    assert "S/R 1d ready" in labels
    assert "sr_strategy_long_room_in_direction_atr" in result[
        "support_resistance_strategy"
    ]
    assert "sr_1h_long_room_in_direction_atr" in result["support_resistance_1h"]
    assert "sr_4h_short_support_state" in result["support_resistance_4h"]
    assert "sr_1d_completed_candle_time" in result["support_resistance_1d"]


def test_rule_runtime_reads_selected_sr_timeframe_without_combining_contexts() -> None:
    engine = RuleAwareDataLakeProductionBacktestEngine.__new__(
        RuleAwareDataLakeProductionBacktestEngine
    )
    engine.config = SimpleNamespace(
        enable_support_resistance_analysis=True,
        strategy_timeframe_minutes=15,
    )
    engine.research_features = {
        "support_resistance_strategy": SimpleNamespace(
            values={
                "sr_strategy_long_room_in_direction_atr": np.array([1.0]),
                "sr_strategy_long_support_state": np.array(["APPROACHING_SUPPORT"]),
            }
        ),
        "support_resistance_1h": SimpleNamespace(
            values={
                "sr_1h_long_room_in_direction_atr": np.array([3.0]),
                "sr_1h_long_support_state": np.array(["SUPPORT_TESTING"]),
            }
        ),
        "support_resistance_4h": SimpleNamespace(
            values={
                "sr_4h_long_room_in_direction_atr": np.array([7.0]),
                "sr_4h_long_support_state": np.array(["SUPPORT_HELD"]),
            }
        ),
    }

    assert engine._prepared_sr_value_for_timeframe(
        0, "LONG", "SR_ROOM_IN_DIRECTION_ATR", 0
    ) == 1.0
    assert engine._prepared_sr_value_for_timeframe(
        0, "LONG", "SR_ROOM_IN_DIRECTION_ATR", 60
    ) == 3.0
    assert engine._prepared_sr_value_for_timeframe(
        0, "LONG", "SR_ROOM_IN_DIRECTION_ATR", 240
    ) == 7.0

    support_testing = engine._prepared_sr_value_for_timeframe(
        0, "LONG", "SR_SUPPORT_STATE", 60
    )
    support_held = engine._prepared_sr_value_for_timeframe(
        0, "LONG", "SR_SUPPORT_STATE", 240
    )
    assert support_testing != support_held


def test_trade_relative_sr_rule_uses_selected_timeframe_geometry_and_strategy_contract() -> None:
    engine = RuleAwareDataLakeProductionBacktestEngine.__new__(
        RuleAwareDataLakeProductionBacktestEngine
    )
    engine.config = SimpleNamespace(
        enable_support_resistance_analysis=True,
        strategy_timeframe_minutes=15,
        risk_mode="ATR",
        sr_take_profit_mode="FIXED_R",
    )
    engine.atr_values = np.array([100.0])
    engine.close = np.array([1000.0])
    engine.risk = np.array([100.0])
    engine.research_features = {
        "support_resistance_4h": SimpleNamespace(
            values={
                "sr_4h_long_nearest_support_price": np.array([800.0]),
                "sr_4h_long_nearest_support_distance_atr": np.array([0.5]),
                "sr_4h_long_nearest_support_distance_price": np.array([200.0]),
                "sr_4h_long_nearest_resistance_price": np.array([1600.0]),
                "sr_4h_long_nearest_resistance_distance_atr": np.array([0.75]),
                "sr_4h_long_nearest_resistance_distance_price": np.array([600.0]),
                "sr_4h_long_near_support": np.array([True]),
                "sr_4h_long_near_resistance": np.array([False]),
                "sr_4h_long_inside_support_zone": np.array([False]),
                "sr_4h_long_inside_resistance_zone": np.array([False]),
                "sr_4h_long_support_state": np.array(["SUPPORT_HELD"]),
                "sr_4h_long_resistance_state": np.array(["APPROACHING_RESISTANCE"]),
                "sr_4h_long_support_held": np.array([True]),
                "sr_4h_long_resistance_held": np.array([False]),
                "sr_4h_long_support_zone_low": np.array([750.0]),
                "sr_4h_long_support_zone_high": np.array([850.0]),
                "sr_4h_long_resistance_zone_low": np.array([1600.0]),
                "sr_4h_long_resistance_zone_high": np.array([1700.0]),
            }
        )
    }
    profile = SimpleNamespace(
        partial_stop_enabled=False,
        stop_loss_multiple=1.0,
        partial_profit_enabled=False,
        reward_risk_ratio=3.0,
        r_step_trailing_enabled=False,
    )

    assert engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_OPPOSING_DISTANCE_NATIVE_ATR",
        240,
        profile=profile,
    ) == pytest.approx(0.75)
    assert engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_OPPOSING_DISTANCE_STRATEGY_ATR",
        240,
        profile=profile,
    ) == pytest.approx(6.0)
    assert engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_OPPOSING_ROOM_R",
        240,
        profile=profile,
    ) == pytest.approx(6.0)
    assert engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_OPPOSING_ROOM_TARGET_MULTIPLE",
        240,
        profile=profile,
    ) == pytest.approx(2.0)

    relation = engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_ENTRY_RELATION",
        240,
        profile=profile,
    )
    assert relation == CATEGORICAL_VALUE_CODES["SR_ENTRY_RELATION"][
        "NEAR_FAVORABLE_STRUCTURE"
    ]


def test_trade_relative_sr_target_metrics_fail_closed_for_dynamic_execution() -> None:
    engine = RuleAwareDataLakeProductionBacktestEngine.__new__(
        RuleAwareDataLakeProductionBacktestEngine
    )
    engine.config = SimpleNamespace(
        enable_support_resistance_analysis=True,
        strategy_timeframe_minutes=15,
        risk_mode="ATR",
        sr_take_profit_mode="SR_CAPPED_R",
    )
    engine.atr_values = np.array([100.0])
    engine.close = np.array([1000.0])
    engine.risk = np.array([100.0])
    engine.research_features = {
        "support_resistance_4h": SimpleNamespace(
            values={
                "sr_4h_long_nearest_resistance_price": np.array([1600.0]),
                "sr_4h_long_nearest_resistance_distance_atr": np.array([0.75]),
                "sr_4h_long_nearest_resistance_distance_price": np.array([600.0]),
                "sr_4h_long_near_support": np.array([False]),
                "sr_4h_long_near_resistance": np.array([False]),
                "sr_4h_long_inside_support_zone": np.array([False]),
                "sr_4h_long_inside_resistance_zone": np.array([False]),
                "sr_4h_long_resistance_zone_low": np.array([1600.0]),
                "sr_4h_long_resistance_zone_high": np.array([1700.0]),
            }
        )
    }
    profile = SimpleNamespace(
        partial_stop_enabled=False,
        stop_loss_multiple=1.0,
        partial_profit_enabled=False,
        reward_risk_ratio=3.0,
        r_step_trailing_enabled=False,
    )

    value = engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_OPPOSING_ROOM_TARGET_MULTIPLE",
        240,
        profile=profile,
    )
    assert np.isnan(value)
    target_path = engine._prepared_sr_value_for_timeframe(
        0,
        "LONG",
        "SR_TARGET_PATH",
        240,
        profile=profile,
    )
    assert target_path == CATEGORICAL_VALUE_CODES["SR_TARGET_PATH"][
        "TARGET_CONTRACT_UNAVAILABLE"
    ]
