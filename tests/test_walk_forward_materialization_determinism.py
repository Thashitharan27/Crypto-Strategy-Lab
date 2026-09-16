from crypto_strategy_lab.walk_forward_materialization import _executable_group


def test_executable_group_assigns_stable_condition_ids():
    payload = {
        "profile": "bull_long",
        "conditions": [
            {"indicator": "ADX", "condition": "GTE", "value": 20},
            {"indicator": "RSI", "condition": "LTE", "value": 70},
        ],
    }

    profile_a, group_a = _executable_group(
        payload,
        rule_id="ENTRY_015",
        rule_version="4",
    )
    profile_b, group_b = _executable_group(
        payload,
        rule_id="ENTRY_015",
        rule_version="4",
    )

    assert profile_a == profile_b == "bull_long"
    assert group_a == group_b
    assert [condition["id"] for condition in group_a["conditions"]] == [
        "wf_8caf703b5df3_1",
        "wf_cd1a8efe869b_2",
    ]


def test_rule_version_changes_generated_condition_identity():
    payload = {
        "profile": "bull_long",
        "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 20}],
    }

    _, first = _executable_group(payload, rule_id="ENTRY_015", rule_version="3")
    _, second = _executable_group(payload, rule_id="ENTRY_015", rule_version="4")

    assert first["conditions"][0]["id"] != second["conditions"][0]["id"]
