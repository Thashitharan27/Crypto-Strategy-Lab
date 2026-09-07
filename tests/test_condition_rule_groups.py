from types import SimpleNamespace

from crypto_strategy_lab.engine import BacktestEngine


class _GroupEngine(BacktestEngine):
    def _strategy_profile_entry_rule_matches(self, i, direction, profile, rule):
        del i, direction, profile
        return bool(rule["matched"])


def _engine():
    return object.__new__(_GroupEngine)


def _rule(*, action, kind, group, name, matched, rule_id):
    return {
        "action": action,
        "indicator": "ADX",
        "condition": "INSIDE",
        "minimum": 0.0,
        "maximum": 1.0,
        "_builder_id": rule_id,
        "_builder_kind": kind,
        "_builder_group_id": group,
        "_builder_group_name": name,
        "matched": matched,
    }


def test_entry_groups_are_and_inside_or_between_groups():
    engine = _engine()
    profile = SimpleNamespace(
        entry_rules=(
            # REQUIRED native matching means the desired condition failed.
            _rule(
                action="REJECT", kind="REQUIRED", group="a", name="Trend entry",
                matched=False, rule_id="a1",
            ),
            _rule(
                action="REJECT", kind="REQUIRED", group="a", name="Trend entry",
                matched=False, rule_id="a2",
            ),
            _rule(
                action="REJECT", kind="REQUIRED", group="b", name="Pullback entry",
                matched=True, rule_id="b1",
            ),
        )
    )

    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", "ANY"
    )
    assert not rejected
    assert detail is None

    profile.entry_rules[0]["matched"] = True
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", "ANY"
    )
    assert rejected
    assert "no Entry Group matched" in detail


def test_veto_and_flip_groups_require_all_conditions_inside_one_group():
    engine = _engine()
    veto_profile = SimpleNamespace(
        entry_rules=(
            _rule(
                action="REJECT", kind="VETO", group="v1", name="MR pocket",
                matched=True, rule_id="v1a",
            ),
            _rule(
                action="REJECT", kind="VETO", group="v1", name="MR pocket",
                matched=False, rule_id="v1b",
            ),
            _rule(
                action="REJECT", kind="VETO", group="v2", name="ADX pocket",
                matched=True, rule_id="v2a",
            ),
        )
    )
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", veto_profile, "REJECT", "ANY"
    )
    assert rejected
    assert detail == "Veto Group matched: ADX pocket"

    flip_profile = SimpleNamespace(
        entry_rules=(
            _rule(
                action="FLIP", kind="FLIP", group="f1", name="Reversal pocket",
                matched=True, rule_id="f1a",
            ),
            _rule(
                action="FLIP", kind="FLIP", group="f1", name="Reversal pocket",
                matched=True, rule_id="f1b",
            ),
        )
    )
    flipped, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", flip_profile, "FLIP", "ANY"
    )
    assert flipped
    assert detail == "Flip Group matched: Reversal pocket"


def test_native_rules_keep_historical_match_mode_and_are_mandatory():
    engine = _engine()
    profile = SimpleNamespace(
        entry_rules=(
            {
                "action": "REJECT",
                "indicator": "ADX",
                "condition": "INSIDE",
                "minimum": 0.0,
                "maximum": 1.0,
                "matched": True,
            },
        )
    )
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", "ANY"
    )
    assert rejected
    assert detail == "native rule set"


def test_runtime_fallback_preserves_old_ungrouped_builder_semantics():
    engine = _engine()
    required_a = _rule(
        action="REJECT", kind="REQUIRED", group="", name="",
        matched=False, rule_id="old-r1",
    )
    required_b = _rule(
        action="REJECT", kind="REQUIRED", group="", name="",
        matched=True, rule_id="old-r2",
    )
    veto_a = _rule(
        action="REJECT", kind="VETO", group="", name="",
        matched=False, rule_id="old-v1",
    )
    veto_b = _rule(
        action="REJECT", kind="VETO", group="", name="",
        matched=True, rule_id="old-v2",
    )
    for rule in (required_a, required_b, veto_a, veto_b):
        rule.pop("_builder_group_id")
        rule.pop("_builder_group_name")

    required_profile = SimpleNamespace(entry_rules=(required_a, required_b))
    rejected, _detail = engine._strategy_profile_rule_action_result(
        0, "LONG", required_profile, "REJECT", "ANY"
    )
    assert rejected  # old REQUIRED rows were one AND set; one failed => reject

    veto_profile = SimpleNamespace(entry_rules=(veto_a, veto_b))
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", veto_profile, "REJECT", "ANY"
    )
    assert rejected
    assert detail.startswith("Veto Group matched:")
