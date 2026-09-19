from dataclasses import asdict

import pytest

from crypto_strategy_lab.control_rule_workspace import RuleWorkspace, strategy_capabilities
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    new_rule,
)


def _veto_group(group_id, state, motion, *, name=None, enabled=True):
    return {
        "id": group_id,
        "name": name or group_id,
        "enabled": enabled,
        "match_mode": "ALL",
        "conditions": [
            {"indicator": "MR_STATE", "condition": "EQUALS", "value": state},
            {"indicator": "MR_MOTION", "condition": "EQUALS", "value": motion},
        ],
    }


def test_capabilities_use_gui_labels_and_human_categorical_values():
    caps = strategy_capabilities()

    assert caps["rule_group_model"]["conditions_inside_group"] == "ALL"
    assert caps["rule_group_model"]["groups_inside_family"] == "OR"
    assert caps["rule_group_model"]["families"] == ["ENTRY", "VETO", "FLIP"]
    assert caps["indicators"]["MR_STATE"]["display_name"] == "MR — State"
    assert "ABOVE_MEAN" in caps["indicators"]["MR_STATE"]["values"]
    assert "STRONGLY_ABOVE_MEAN" in caps["indicators"]["MR_STATE"]["values"]
    assert caps["indicators"]["MR_STATE"]["conditions"] == ["EQUALS", "NOT_EQUALS"]
    assert caps["indicators"]["SR_OPPOSING_ROOM_TARGET_MULTIPLE"]["display_name"] == (
        "S/R — Opposing Room / Planned Target"
    )
    assert caps["indicators"]["SR_ENTRY_RELATION"]["values"]
    assert "SR_TRADE_LOCATION_RATING" not in caps["indicators"]
    assert "SR_ROOM_IN_DIRECTION_ATR" not in caps["indicators"]
    assert {
        item["id"]: item["display_name"] for item in caps["market_regime_methods"]
    }["ASSET_RETURN"] == "Asset trailing return"
    assert {
        item["id"]: item["display_name"] for item in caps["signal_strategies"]
    }["MTF_SR_REACTION"] == "MTF S/R Reaction — Adaptive HTF / Entry TF"


def test_three_bull_long_veto_groups_round_trip_without_numeric_codes():
    workspace = RuleWorkspace(ResearchRunConfig().to_dict())
    groups = [
        _veto_group("group_1", "ABOVE_MEAN", "AWAY_FROM_MEAN"),
        _veto_group("group_2", "STRONGLY_ABOVE_MEAN", "AWAY_FROM_MEAN"),
        {
            "id": "group_3",
            "name": "Weak toward-mean pocket",
            "enabled": True,
            "match_mode": "ALL",
            "conditions": [
                {"indicator": "MR_STATE", "condition": "EQUALS", "value": "ABOVE_MEAN"},
                {"indicator": "MR_MOTION", "condition": "EQUALS", "value": "TOWARD_MEAN"},
                {"indicator": "MR_STRENGTH", "condition": "EQUALS", "value": "WEAK"},
            ],
        },
    ]

    result = workspace.set_groups("bull_long", "VETO", groups)
    assert [group["id"] for group in result["groups"]] == ["group_1", "group_2", "group_3"]
    assert result["groups"][0]["conditions"][0]["value"] == "ABOVE_MEAN"
    assert result["groups"][1]["conditions"][0]["value"] == "STRONGLY_ABOVE_MEAN"

    compiled = workspace.to_config()
    native = compiled["strategy"]["profiles"]["bull_long"]["entry_rules"]
    group_1_native = [rule for rule in native if rule.get("_builder_group_id") == "group_1"]
    assert len(group_1_native) == 2
    mr_state = next(rule for rule in group_1_native if rule["indicator"] == "MR_STATE")
    assert mr_state["minimum"] == 4.0
    assert mr_state["maximum"] == 4.0
    assert mr_state["_builder_value"] == "ABOVE_MEAN"

    readback = RuleWorkspace(compiled).list_groups("bull_long", "VETO")
    assert [group["id"] for group in readback["groups"]] == ["group_1", "group_2", "group_3"]
    assert readback["groups"][2]["conditions"][2]["value"] == "WEAK"


def test_add_update_mute_unmute_delete_touch_only_target_group():
    workspace = RuleWorkspace(ResearchRunConfig().to_dict())
    first = workspace.add_group(
        "bull_long", "VETO", _veto_group("veto_a", "ABOVE_MEAN", "AWAY_FROM_MEAN")
    )
    workspace.add_group(
        "bull_long", "VETO", _veto_group("veto_b", "STRONGLY_ABOVE_MEAN", "AWAY_FROM_MEAN")
    )

    assert first["id"] == "veto_a"
    workspace.update_group(
        "veto_b",
        {
            "name": "Updated B",
            "conditions": [
                {"indicator": "MR_STATE", "condition": "EQUALS", "value": "NEAR_MEAN"}
            ],
        },
    )
    groups = {group["id"]: group for group in workspace.list_groups("bull_long", "VETO")["groups"]}
    assert groups["veto_a"]["conditions"][0]["value"] == "ABOVE_MEAN"
    assert groups["veto_b"]["name"] == "Updated B"
    assert groups["veto_b"]["conditions"][0]["value"] == "NEAR_MEAN"

    workspace.set_group_enabled("veto_a", False)
    groups = {group["id"]: group for group in workspace.list_groups("bull_long", "VETO")["groups"]}
    assert groups["veto_a"]["enabled"] is False
    assert groups["veto_b"]["enabled"] is True

    workspace.set_group_enabled("veto_a", True)
    assert {
        group["id"]: group for group in workspace.list_groups("bull_long", "VETO")["groups"]
    }["veto_a"]["enabled"] is True

    deleted = workspace.delete_group("veto_b")
    assert deleted["id"] == "veto_b"
    assert [
        group["id"] for group in workspace.list_groups("bull_long", "VETO")["groups"]
    ] == ["veto_a"]


def test_group_any_mode_is_rejected_in_favor_of_multiple_or_groups():
    workspace = RuleWorkspace(ResearchRunConfig().to_dict())
    group = _veto_group("bad_logic", "ABOVE_MEAN", "AWAY_FROM_MEAN")
    group["match_mode"] = "ANY"

    with pytest.raises(ValueError, match="Represent OR logic as multiple groups"):
        workspace.add_group("bull_long", "VETO", group)


def test_gui_display_indicator_alias_is_accepted():
    workspace = RuleWorkspace(ResearchRunConfig().to_dict())
    created = workspace.add_group(
        "bull_long",
        "VETO",
        {
            "id": "alias_test",
            "conditions": [
                {"indicator": "MR — State", "condition": "EQUALS", "value": "Above Mean"}
            ],
        },
    )
    assert created["conditions"][0]["indicator"] == "MR_STATE"
    assert created["conditions"][0]["value"] == "ABOVE_MEAN"


def test_profile_replacement_preserves_shared_scope_builder_group():
    shared = new_rule(
        kind="VETO",
        evidence="ADX",
        group_id="shared_veto",
        group_name="Shared ADX veto",
        regime="ALL",
        side="ALL",
    )
    shared.update(operator="LT", value=10.0, value2=10.0)
    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        veto_rules=(shared,),
    )
    config = ResearchRunConfig().to_dict()
    config["strategy"]["profiles"] = {
        key: asdict(value) for key, value in profiles.items()
    }

    workspace = RuleWorkspace(config)
    workspace.set_groups(
        "bull_long",
        "VETO",
        [_veto_group("exact_bull_long", "ABOVE_MEAN", "AWAY_FROM_MEAN")],
    )

    ids = [group["id"] for group in workspace.list_groups("bull_long", "VETO")["groups"]]
    assert "shared_veto" in ids
    assert "exact_bull_long" in ids
    bear_ids = [group["id"] for group in workspace.list_groups("bear_long", "VETO")["groups"]]
    assert bear_ids == ["shared_veto"]


def test_legacy_native_rules_are_preserved_and_reported_as_warning():
    config = ResearchRunConfig().to_dict()
    config["strategy"]["profiles"]["bull_long"]["entry_rules"] = (
        {
            "action": "REJECT",
            "indicator": "ADX",
            "condition": "INSIDE",
            "minimum": 0.0,
            "maximum": 20.0,
        },
    )
    workspace = RuleWorkspace(config)
    readback = workspace.workspace("bull_long")
    assert readback["legacy_native_rule_counts"]["bull_long"] == 1
    assert readback["warnings"]

    workspace.add_group(
        "bull_long", "VETO", _veto_group("new_veto", "ABOVE_MEAN", "AWAY_FROM_MEAN")
    )
    rebuilt = workspace.to_config()
    rules = rebuilt["strategy"]["profiles"]["bull_long"]["entry_rules"]
    assert any(rule.get("indicator") == "ADX" and "_builder_id" not in rule for rule in rules)
    assert any(rule.get("_builder_group_id") == "new_veto" for rule in rules)
