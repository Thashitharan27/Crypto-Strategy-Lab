from dataclasses import asdict

import pytest

from crypto_strategy_lab.data_lake_config import ExecutionProfileConfig
from crypto_strategy_lab.strategy_profiles import StrategyProfile
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    decompile_rules,
    new_rule,
    normalize_rule,
)


def test_required_di_spread_rule_compiles_to_reject_when_requirement_fails():
    rule = new_rule(kind="REQUIRED", evidence="DI_SPREAD")
    rule.update(operator="GTE", value=30.0, regime="ALL", side="ALL")

    strategy, execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(rule,),
    )

    assert set(strategy) == {
        "bull_long", "bull_short", "bear_long", "bear_short",
        "sideways_long", "sideways_short",
    }
    for key, profile in strategy.items():
        assert profile.enabled is True
        assert profile.flip_direction is False
        assert profile.reject_rule_match_mode == "ANY"
        assert len(profile.entry_rules) == 1
        native = profile.entry_rules[0]
        assert native["action"] == "REJECT"
        assert native["indicator"] == "DI_SPREAD"
        assert native["condition"] == "OUTSIDE"
        assert native["minimum"] == 30.0
        assert native["maximum"] > 1e300
        mature = StrategyProfile(**{
            **asdict(profile),
            **asdict(execution[key]),
        })
        mature.validate(key)


def test_required_expanding_pressure_compiles_as_categorical_requirement():
    rule = new_rule(kind="REQUIRED", evidence="DI_PRESSURE_STATE")
    rule.update(operator="IS", value="EXPANDING", regime="ALL", side="ALL")

    strategy, execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(rule,),
    )

    native = strategy["bull_long"].entry_rules[0]
    assert native["action"] == "REJECT"
    assert native["indicator"] == "DI_PRESSURE_STATE"
    assert native["condition"] == "OUTSIDE"
    assert native["minimum"] == native["maximum"] == 1.0
    StrategyProfile(**{
        **asdict(strategy["bull_long"]),
        **asdict(execution["bull_long"]),
    }).validate("bull_long")


def test_contracting_pressure_veto_rejects_matching_state():
    rule = new_rule(kind="VETO", evidence="DI_PRESSURE_STATE")
    rule.update(operator="IS", value="CONTRACTING")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        veto_rules=(rule,),
    )
    native = strategy["bear_short"].entry_rules[0]
    assert native["indicator"] == "DI_PRESSURE_STATE"
    assert native["condition"] == "INSIDE"
    assert native["minimum"] == native["maximum"] == 2.0


def test_pressure_state_supports_only_categorical_operators_and_values():
    with pytest.raises(ValueError, match="unsupported operator"):
        normalize_rule({
            "kind": "REQUIRED",
            "evidence": "DI_PRESSURE_STATE",
            "operator": "GTE",
            "value": "EXPANDING",
        })
    with pytest.raises(ValueError, match="unsupported value"):
        normalize_rule({
            "kind": "REQUIRED",
            "evidence": "DI_PRESSURE_STATE",
            "operator": "IS",
            "value": "UNKNOWN",
        })


def test_numeric_pressure_change_evidence_keeps_numeric_operators():
    rule = new_rule(kind="REQUIRED", evidence="DIRECTIONAL_DI_CHANGE")
    rule.update(operator="GTE", value=4.0)
    normalized = normalize_rule(rule)
    assert normalized["value"] == 4.0
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(normalized,),
    )
    native = strategy["bull_long"].entry_rules[0]
    assert native["indicator"] == "DIRECTIONAL_DI_CHANGE"
    assert native["condition"] == "OUTSIDE"
    assert native["minimum"] == 4.0


def test_scoped_veto_only_reaches_matching_regime_and_side():
    rule = new_rule(kind="VETO", evidence="ADX")
    rule.update(operator="LTE", value=20.0, regime="BULL", side="LONG")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        veto_rules=(rule,),
    )

    assert len(strategy["bull_long"].entry_rules) == 1
    native = strategy["bull_long"].entry_rules[0]
    assert native["condition"] == "INSIDE"
    assert native["maximum"] == 20.0
    assert not strategy["bull_short"].entry_rules
    assert not strategy["bear_long"].entry_rules


def test_long_only_trading_is_expressed_by_permissions_not_direction_override():
    long_permissions = ("BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG")
    rule = new_rule(kind="REQUIRED", evidence="DI_SPREAD")
    rule.update(operator="GTE", value=30.0, side="LONG")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=long_permissions,
        required_rules=(rule,),
    )

    assert strategy["bull_long"].enabled is True
    assert strategy["bull_short"].enabled is False
    assert strategy["bear_long"].enabled is True
    assert strategy["bear_short"].enabled is False
    assert strategy["sideways_long"].enabled is True
    assert strategy["sideways_short"].enabled is False
    assert all(profile.flip_direction is False for profile in strategy.values())
    assert len(strategy["bull_long"].entry_rules) == 1
    assert not strategy["bull_short"].entry_rules


def test_forced_long_and_short_direction_modes_are_retired():
    for retired in ("LONG_ONLY", "SHORT_ONLY"):
        with pytest.raises(ValueError, match="unsupported direction mode"):
            compile_profiles(
                direction_mode=retired,
                market_permissions=MARKET_PERMISSIONS,
            )


def test_builder_metadata_round_trips_scoped_rules_without_profile_ui():
    required = new_rule(kind="REQUIRED", evidence="RSI")
    required.update(
        operator="BETWEEN", value=20.0, value2=45.0,
        regime="BULL", side="LONG",
    )
    veto = new_rule(kind="VETO", evidence="DI_PRESSURE_STATE")
    veto.update(
        operator="IS", value="CONTRACTING", regime="ALL", side="SHORT"
    )

    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(required,),
        veto_rules=(veto,),
    )
    recovered = decompile_rules(strategy)

    assert recovered["REQUIRED"] == (normalize_rule(required),)
    assert recovered["VETO"] == (normalize_rule(veto),)
    assert recovered["FLIP"] == ()


def test_one_base_execution_plan_is_copied_to_internal_engine_inputs():
    base = ExecutionProfileConfig(
        stop_loss_multiple=3.0,
        reward_risk_ratio=2.0,
        break_even_enabled=True,
        break_even_activation_r=1.0,
    )
    _strategy, execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        base_execution=base,
    )
    assert all(profile == base for profile in execution.values())
