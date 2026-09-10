from crypto_strategy_lab.strategy_rule_model import (
    compile_profiles,
    decompile_rules,
    normalize_rule,
    rule_value_options,
)


def _mr_state_rule(value: str, *, operator: str = "IS", kind: str = "REQUIRED") -> dict:
    return {
        "id": f"mr-{value.lower()}-{operator.lower()}",
        "group_id": "mr-state-group",
        "group_name": "MR state",
        "group_enabled": True,
        "kind": kind,
        "evidence": "MR_STATE",
        "operator": operator,
        "value": value,
        "value2": None,
        "regime": "BULL",
        "side": "LONG",
    }


def test_mr_state_exposes_combined_presets_without_removing_exact_states():
    assert rule_value_options("MR_STATE") == (
        "STRONGLY_BELOW_MEAN",
        "BELOW_MEAN",
        "ANY_BELOW_MEAN",
        "NEAR_MEAN",
        "ABOVE_MEAN",
        "STRONGLY_ABOVE_MEAN",
        "ANY_ABOVE_MEAN",
    )


def test_any_below_mean_compiles_to_both_below_state_codes():
    rule = _mr_state_rule("ANY_BELOW_MEAN")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        required_rules=(rule,),
    )

    native = strategy["BULL_LONG"].entry_rules[0]
    assert native["condition"] == "OUTSIDE"
    assert native["minimum"] == 1.0
    assert native["maximum"] == 2.0

    restored = decompile_rules(strategy)["REQUIRED"]
    assert len(restored) == 1
    assert restored[0]["value"] == "ANY_BELOW_MEAN"


def test_any_above_mean_compiles_to_both_above_state_codes():
    rule = _mr_state_rule("ANY_ABOVE_MEAN")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        required_rules=(rule,),
    )

    native = strategy["BULL_LONG"].entry_rules[0]
    assert native["condition"] == "OUTSIDE"
    assert native["minimum"] == 4.0
    assert native["maximum"] == 5.0


def test_is_not_combined_preset_inverts_the_whole_combined_region():
    rule = _mr_state_rule("ANY_BELOW_MEAN", operator="IS_NOT")
    normalized = normalize_rule(rule)
    assert normalized["value"] == "ANY_BELOW_MEAN"
    assert normalized["operator"] == "IS_NOT"

    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        required_rules=(rule,),
    )

    native = strategy["BULL_LONG"].entry_rules[0]
    # REQUIRED + Is Not means reject when the state is inside the combined
    # below-mean region (Strongly Below or Below).
    assert native["condition"] == "INSIDE"
    assert native["minimum"] == 1.0
    assert native["maximum"] == 2.0


def test_exact_below_mean_keeps_exact_historical_meaning():
    rule = _mr_state_rule("BELOW_MEAN")
    strategy, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        required_rules=(rule,),
    )

    native = strategy["BULL_LONG"].entry_rules[0]
    assert native["condition"] == "OUTSIDE"
    assert native["minimum"] == native["maximum"] == 2.0
