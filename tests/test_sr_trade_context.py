from __future__ import annotations

from types import SimpleNamespace

import pytest

from crypto_strategy_lab.sr_trade_context import (
    derive_trade_sr_context,
    planned_trade_distances,
)


def _long_raw(
    *,
    support_distance_price=200.0,
    support_distance_atr=0.5,
    resistance_distance_price=600.0,
    resistance_distance_atr=1.5,
    near_support=True,
    near_resistance=False,
    inside_support=False,
    inside_resistance=False,
):
    return {
        "nearest_support_price": 800.0,
        "nearest_support_distance_price": support_distance_price,
        "nearest_support_distance_atr": support_distance_atr,
        "nearest_resistance_price": 1600.0,
        "nearest_resistance_distance_price": resistance_distance_price,
        "nearest_resistance_distance_atr": resistance_distance_atr,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "inside_support_zone": inside_support,
        "inside_resistance_zone": inside_resistance,
        "support_state": "SUPPORT_HELD",
        "resistance_state": "APPROACHING_RESISTANCE",
        "support_held": True,
        "resistance_held": False,
        "support_rejection_atr": 0.6,
        "resistance_rejection_atr": 0.1,
        "support_test_count": 3,
        "resistance_test_count": 1,
        "bars_since_support_test": 2,
        "bars_since_resistance_test": 8,
        "support_zone_low": 750.0,
        "support_zone_high": 850.0,
        "resistance_zone_low": 1600.0,
        "resistance_zone_high": 1700.0,
    }


def test_trade_context_separates_native_atr_strategy_atr_r_and_target_units():
    raw = _long_raw(
        resistance_distance_price=600.0,
        resistance_distance_atr=0.5,
    )
    result = derive_trade_sr_context(
        direction="LONG",
        raw=raw,
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=300.0,
        target_distance=900.0,
    )

    assert result["SR_ENTRY_RELATION"] == "NEAR_FAVORABLE_STRUCTURE"
    assert result["SR_FAVORABLE_STRUCTURE_STATE"] == "HELD"
    assert result["SR_OPPOSING_STRUCTURE_STATE"] == "APPROACHING"
    assert result["SR_OPPOSING_DISTANCE_NATIVE_ATR"] == pytest.approx(0.5)
    assert result["SR_OPPOSING_DISTANCE_STRATEGY_ATR"] == pytest.approx(6.0)
    assert result["SR_OPPOSING_ROOM_R"] == pytest.approx(2.0)
    assert result["SR_OPPOSING_ROOM_TARGET_MULTIPLE"] == pytest.approx(2.0 / 3.0)
    assert result["SR_TARGET_PATH"] == "OPPOSING_ZONE_BEFORE_TARGET"


def test_same_price_room_can_have_different_native_atr_but_same_trade_meaning():
    one_hour = derive_trade_sr_context(
        direction="LONG",
        raw=_long_raw(
            resistance_distance_price=600.0,
            resistance_distance_atr=3.0,
        ),
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=300.0,
        target_distance=900.0,
    )
    daily = derive_trade_sr_context(
        direction="LONG",
        raw=_long_raw(
            resistance_distance_price=600.0,
            resistance_distance_atr=0.5,
        ),
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=300.0,
        target_distance=900.0,
    )

    assert one_hour["SR_OPPOSING_DISTANCE_NATIVE_ATR"] == 3.0
    assert daily["SR_OPPOSING_DISTANCE_NATIVE_ATR"] == 0.5
    for field in (
        "SR_OPPOSING_DISTANCE_STRATEGY_ATR",
        "SR_OPPOSING_ROOM_R",
        "SR_OPPOSING_ROOM_TARGET_MULTIPLE",
        "SR_TARGET_PATH",
    ):
        assert one_hour[field] == daily[field]


def test_both_near_is_squeezed_not_favorable():
    raw = _long_raw(near_support=True, near_resistance=True)
    result = derive_trade_sr_context(
        direction="LONG",
        raw=raw,
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=300.0,
        target_distance=500.0,
    )
    assert result["SR_ENTRY_RELATION"] == "SQUEEZED_BETWEEN_STRUCTURES"


def test_short_automatically_treats_resistance_as_favorable_and_support_as_opposing():
    raw = _long_raw(
        support_distance_price=450.0,
        support_distance_atr=1.1,
        resistance_distance_price=50.0,
        resistance_distance_atr=0.2,
        near_support=False,
        near_resistance=True,
    )
    result = derive_trade_sr_context(
        direction="SHORT",
        raw=raw,
        strategy_atr=90.0,
        reference_price=1000.0,
        stop_distance=180.0,
        target_distance=360.0,
    )

    assert result["SR_ENTRY_RELATION"] == "NEAR_FAVORABLE_STRUCTURE"
    assert result["SR_FAVORABLE_STRUCTURE_STATE"] == "APPROACHING"
    assert result["SR_OPPOSING_STRUCTURE_STATE"] == "HELD"
    assert result["SR_OPPOSING_DISTANCE_NATIVE_ATR"] == pytest.approx(1.1)
    assert result["SR_OPPOSING_ROOM_R"] == pytest.approx(2.5)


def test_target_path_distinguishes_before_inside_and_beyond_opposing_zone():
    raw = _long_raw(resistance_distance_price=600.0, near_support=False)

    before = derive_trade_sr_context(
        direction="LONG",
        raw=raw,
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=200.0,
        target_distance=500.0,
    )
    inside = derive_trade_sr_context(
        direction="LONG",
        raw=raw,
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=200.0,
        target_distance=650.0,
    )
    beyond = derive_trade_sr_context(
        direction="LONG",
        raw=raw,
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=200.0,
        target_distance=800.0,
    )

    assert before["SR_TARGET_PATH"] == "TARGET_BEFORE_OPPOSING_ZONE"
    assert inside["SR_TARGET_PATH"] == "TARGET_INSIDE_OPPOSING_ZONE"
    assert beyond["SR_TARGET_PATH"] == "OPPOSING_ZONE_BEFORE_TARGET"


def test_missing_target_contract_is_explicit_not_misclassified_as_no_structure():
    result = derive_trade_sr_context(
        direction="LONG",
        raw=_long_raw(),
        strategy_atr=100.0,
        reference_price=1000.0,
        stop_distance=None,
        target_distance=None,
    )
    assert result["SR_OPPOSING_ROOM_R"] is None
    assert result["SR_OPPOSING_ROOM_TARGET_MULTIPLE"] is None
    assert result["SR_TARGET_PATH"] == "TARGET_CONTRACT_UNAVAILABLE"


def test_planned_trade_distances_follow_runtime_final_target_contract():
    normal = SimpleNamespace(
        partial_stop_enabled=False,
        stop_loss_multiple=1.0,
        partial_profit_enabled=False,
        reward_risk_ratio=3.0,
        r_step_trailing_enabled=False,
    )
    stop, target = planned_trade_distances(normal, 100.0)
    assert stop == 100.0
    assert target == 300.0

    partial = {
        "partial_stop_enabled": True,
        "sl2_r": 1.5,
        "partial_profit_enabled": True,
        "tp2_r": 2.0,
        "r_step_trailing_enabled": False,
    }
    stop, target = planned_trade_distances(partial, 100.0)
    assert stop == 150.0
    assert target == 300.0

    staircase = {
        "partial_stop_enabled": False,
        "stop_loss_multiple": 1.5,
        "partial_profit_enabled": False,
        "reward_risk_ratio": 3.0,
        "r_step_trailing_enabled": True,
        "r_step_maximum_r": 5.0,
    }
    stop, target = planned_trade_distances(staircase, 100.0)
    assert stop == 150.0
    assert target == 750.0
