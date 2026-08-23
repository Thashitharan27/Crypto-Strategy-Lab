from dataclasses import asdict

from crypto_strategy_lab.data_lake_config import ExecutionProfileConfig
from crypto_strategy_lab.strategy_profiles import StrategyProfile
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    decompile_rules,
    new_rule,
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
        # Extra builder metadata remains harmless to the mature engine contract.
        mature = StrategyProfile(**{
            **asdict(profile),
            **asdict(execution[key]),
        })
        mature.validate(key)


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


def test_long_only_is_permission_not_six_separate_strategies():
    long_permissions = ("BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG")
    rule = new_rule(kind="REQUIRED", evidence="DI_SPREAD")
    rule.update(operator="GTE", value=30.0, side="LONG")
    strategy, _execution = compile_profiles(
        direction_mode="LONG_ONLY",
        market_permissions=long_permissions,
        required_rules=(rule,),
    )

    # The engine can classify either original DI side, but both routes become one
    # actual LONG thesis. There is still only one candidate per strategy candle.
    assert strategy["bull_long"].enabled is True
    assert strategy["bull_short"].enabled is True
    assert strategy["bull_long"].flip_direction is False
    assert strategy["bull_short"].flip_direction is True
    assert len(strategy["bull_long"].entry_rules) == 1
    assert len(strategy["bull_short"].entry_rules) == 1


def test_builder_metadata_round_trips_scoped_rules_without_profile_ui():
    required = new_rule(kind="REQUIRED", evidence="RSI")
    required.update(operator="BETWEEN", value=20.0, value2=45.0, regime="BULL", side="LONG")
    veto = new_rule(kind="VETO", evidence="VWAP_DISTANCE")
    veto.update(operator="OUTSIDE", value=0.5, value2=1.5, regime="ALL", side="SHORT")

    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(required,),
        veto_rules=(veto,),
    )
    recovered = decompile_rules(strategy)

    assert recovered["REQUIRED"] == (required,)
    assert recovered["VETO"] == (veto,)
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
