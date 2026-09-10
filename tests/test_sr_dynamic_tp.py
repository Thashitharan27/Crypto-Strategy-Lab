from types import SimpleNamespace

import numpy as np
import pytest

from crypto_strategy_lab.gui.enhanced_config import (
    build_enhanced_backtest_config,
    enhanced_default_gui_config,
)
from crypto_strategy_lab.sr_dynamic_tp_engine import SRDynamicTPBacktestEngine
from crypto_strategy_lab.trade import Side


def test_dynamic_tp_defaults_preserve_fixed_r_baseline():
    values = enhanced_default_gui_config()
    assert values["sr_stop_timeframe_minutes"] == 0
    assert values["sr_stop_buffer_atr"] == 0.25
    assert values["sr_stop_maximum_atr"] == 3.0
    assert values["sr_stop_no_level_policy"] == "USE_ATR_STOP"
    assert values["sr_take_profit_timeframe_minutes"] == -1
    assert values["sr_take_profit_mode"] == "FIXED_R"
    assert values["sr_take_profit_maximum_r"] == 3.0
    assert values["sr_take_profit_minimum_r"] == 1.5
    assert values["sr_take_profit_buffer_r"] == 0.20
    assert values["sr_take_profit_no_level_policy"] == "USE_FIXED_TP"


def test_dynamic_tp_config_validates_minimum_not_above_maximum():
    values = enhanced_default_gui_config()
    values.update(
        {
            "sr_take_profit_mode": "SR_CAPPED_R",
            "enable_support_resistance_analysis": True,
            "sr_take_profit_minimum_r": 3.5,
            "sr_take_profit_maximum_r": 3.0,
        }
    )
    with pytest.raises(ValueError, match="minimum TP cannot exceed maximum TP"):
        build_enhanced_backtest_config(values, require_paths=False)


def _fake_engine(resistance=102.0, support=98.0):
    engine = object.__new__(SRDynamicTPBacktestEngine)
    engine.config = SimpleNamespace(
        sr_take_profit_mode="SR_CAPPED_R",
        sr_take_profit_maximum_r=3.0,
        sr_take_profit_minimum_r=1.5,
        sr_take_profit_buffer_r=0.20,
        sr_take_profit_no_level_policy="USE_FIXED_TP",
        enable_daily_entry_schedule=False,
        slippage=0.0,
    )
    engine.risk = np.array([1.0])
    engine.close = np.array([100.0])
    engine.open = np.array([100.0])
    profile = SimpleNamespace(partial_stop_enabled=False, stop_loss_multiple=1.0)
    engine._profile_context = lambda _i: ("BULL", "LONG", "BULL_LONG", profile)
    engine._effective_trade_direction = lambda _i: "LONG"
    engine._analyze_support_resistance = lambda _i, _direction: SimpleNamespace(
        nearest_resistance_price=resistance,
        nearest_support_price=support,
    )
    return engine


def test_sr_capped_tp_allows_trade_when_room_after_buffer_meets_minimum():
    engine = _fake_engine(resistance=102.0)
    passed, reason = engine._sr_tp_filter_result(0)
    assert passed is True
    assert reason is None


def test_sr_capped_tp_rejects_trade_when_room_after_buffer_is_too_small():
    engine = _fake_engine(resistance=101.5)
    passed, reason = engine._sr_tp_filter_result(0)
    assert passed is False
    assert reason == "SR_TP_INSUFFICIENT_ROOM"


def test_sr_capped_tp_can_reject_when_no_opposing_level_exists():
    engine = _fake_engine(resistance=None)
    engine.config.sr_take_profit_no_level_policy = "REJECT_TRADE"
    passed, reason = engine._sr_tp_filter_result(0)
    assert passed is False
    assert reason == "SR_TP_NO_OPPOSING_LEVEL"


def _fake_structural_stop_engine(*, boundary=96.0, maximum_atr=3.0, no_level_policy="USE_ATR_STOP"):
    engine = object.__new__(SRDynamicTPBacktestEngine)
    engine.config = SimpleNamespace(
        risk_mode="SR_STRUCTURE",
        sr_stop_timeframe_minutes=60,
        sr_stop_buffer_atr=0.25,
        sr_stop_maximum_atr=maximum_atr,
        sr_stop_no_level_policy=no_level_policy,
        strategy_timeframe_minutes=15,
        sr_timeframe_minutes=0,
        enable_daily_entry_schedule=False,
        slippage=0.0,
    )
    engine.atr_values = np.array([2.0])
    engine.close = np.array([100.0])
    engine.open = np.array([100.0])
    engine._effective_trade_direction = lambda _i: "LONG"
    engine._sr_value_for_timeframe = (
        lambda _i, _direction, field, _timeframe:
        boundary if field in {"support_zone_low", "nearest_support_price"} else None
    )
    return engine


def test_structural_stop_uses_outer_zone_edge_plus_atr_buffer():
    engine = _fake_structural_stop_engine(boundary=96.0)
    plan = engine._sr_stop_plan(0)
    assert plan["passed"] is True
    assert plan["applied"] is True
    assert plan["stop_price"] == pytest.approx(95.5)
    assert plan["distance"] == pytest.approx(4.5)
    assert plan["distance_atr"] == pytest.approx(2.25)


def test_structural_stop_rejects_when_required_structure_is_too_far():
    engine = _fake_structural_stop_engine(boundary=90.0, maximum_atr=3.0)
    plan = engine._sr_stop_plan(0)
    assert plan["passed"] is False
    assert plan["reason"] == "SR_STOP_TOO_WIDE"


def test_structural_stop_can_fall_back_to_atr_or_reject_when_no_level_exists():
    fallback = _fake_structural_stop_engine(boundary=None, no_level_policy="USE_ATR_STOP")
    fallback_plan = fallback._sr_stop_plan(0)
    assert fallback_plan["passed"] is True
    assert fallback_plan["applied"] is False
    assert fallback_plan["reason"] == "NO_LEVEL_USE_ATR_STOP"

    reject = _fake_structural_stop_engine(boundary=None, no_level_policy="REJECT_TRADE")
    reject_plan = reject._sr_stop_plan(0)
    assert reject_plan["passed"] is False
    assert reject_plan["reason"] == "SR_STOP_NO_VALID_LEVEL"


def test_structural_sr_target_can_extend_beyond_the_fixed_r_baseline():
    engine = object.__new__(SRDynamicTPBacktestEngine)
    engine.config = SimpleNamespace(
        sr_take_profit_mode="SR_LEVEL",
        sr_take_profit_timeframe_minutes=60,
        sr_take_profit_maximum_r=3.0,
        sr_take_profit_minimum_r=1.0,
        sr_take_profit_buffer_r=0.20,
    )
    engine._sr_value_for_timeframe = lambda *_args: 106.0
    position = SimpleNamespace(
        side=Side.LONG,
        entry_price=100.0,
        risk=2.0,
        tp=102.0,
        partial_tp_enabled=False,
    )
    pair = SimpleNamespace(positions=lambda: [position])

    engine._apply_sr_take_profit(0, pair)

    assert position.sr_take_profit_applied is True
    assert position.sr_take_profit_reason == "SR_LEVEL_TARGET"
    assert position.sr_take_profit_target_r == pytest.approx(2.8)
    assert position.tp == pytest.approx(105.6)
