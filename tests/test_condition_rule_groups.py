from types import SimpleNamespace

import numpy as np
import pandas as pd

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import (
    MARKET_PERMISSIONS,
    compile_profiles,
    new_rule,
)


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


def test_bull_long_mr_state_and_motion_veto_only_rejects_the_intersection():
    group_id = "bull-long-mr-extension"
    state = new_rule(
        kind="VETO",
        evidence="MR_STATE",
        group_id=group_id,
        group_name="Above mean and extending",
        regime="BULL",
        side="LONG",
    )
    state.update(operator="IS", value="ABOVE_MEAN")
    motion = new_rule(
        kind="VETO",
        evidence="MR_MOTION",
        group_id=group_id,
        group_name="Above mean and extending",
        regime="BULL",
        side="LONG",
    )
    motion.update(operator="IS", value="AWAY_FROM_MEAN")

    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        veto_rules=(state, motion),
    )
    profile = profiles["bull_long"]

    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.config = SimpleNamespace(enable_mean_reversion_analysis=True)
    engine.mean_reversion_state = np.array(["ABOVE_MEAN"], dtype=object)
    engine.mean_reversion_motion = np.array(["AWAY_FROM_MEAN"], dtype=object)

    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", profile.reject_rule_match_mode
    )
    assert rejected
    assert detail == "Veto Group matched: Above mean and extending"

    # Same state without the second condition must remain tradable.
    engine.mean_reversion_motion = np.array(["TOWARD_MEAN"], dtype=object)
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", profile.reject_rule_match_mode
    )
    assert not rejected
    assert detail is None

    # Same motion without ABOVE_MEAN must also remain tradable.
    engine.mean_reversion_state = np.array(["NEAR_MEAN"], dtype=object)
    engine.mean_reversion_motion = np.array(["AWAY_FROM_MEAN"], dtype=object)
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", profile.reject_rule_match_mode
    )
    assert not rejected
    assert detail is None



def _trace_engine():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.times = np.array([np.datetime64("2026-01-01T00:00:00")])
    engine.entry_delta = pd.Timedelta(minutes=15)
    engine.adx_values = np.array([24.0], dtype=float)
    engine.di_spread = np.array([10.0], dtype=float)
    engine.strategy_rule_trace_rows = []
    engine._strategy_rule_trace_keys = set()
    engine._strategy_rule_trace_active = None
    engine.signal_strategy_mode = "DI"
    return engine


def test_rule_trace_observes_runtime_short_circuit_without_re_evaluating_later_conditions():
    entry_group = "entry-trend"
    required_adx = new_rule(
        kind="REQUIRED", evidence="ADX", group_id=entry_group,
        group_name="Trend entry", regime="BULL", side="LONG",
    )
    required_adx.update(operator="GTE", value=20.0)
    required_spread = new_rule(
        kind="REQUIRED", evidence="DI_SPREAD", group_id=entry_group,
        group_name="Trend entry", regime="BULL", side="LONG",
    )
    required_spread.update(operator="GTE", value=5.0)

    veto_group = "veto-overheat"
    veto_adx = new_rule(
        kind="VETO", evidence="ADX", group_id=veto_group,
        group_name="Overheated", regime="BULL", side="LONG",
    )
    veto_adx.update(operator="GTE", value=40.0)
    veto_spread = new_rule(
        kind="VETO", evidence="DI_SPREAD", group_id=veto_group,
        group_name="Overheated", regime="BULL", side="LONG",
    )
    veto_spread.update(operator="GTE", value=5.0)

    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(required_adx, required_spread),
        veto_rules=(veto_adx, veto_spread),
    )
    profile = profiles["bull_long"]
    engine = _trace_engine()
    engine._begin_strategy_rule_trace(0, "BULL", "LONG", "bull_long", profile)
    rejected, _detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", profile.reject_rule_match_mode
    )
    assert not rejected
    engine._finish_strategy_rule_trace(True, "passed")

    rows = engine.strategy_rule_trace_rows
    entry = [row for row in rows if row["rule_kind"] == "REQUIRED"]
    veto = [row for row in rows if row["rule_kind"] == "VETO"]
    assert len(entry) == 2 and all(row["condition_evaluated"] for row in entry)
    assert all(row["condition_passed"] for row in entry)
    assert all(row["group_matched"] for row in entry)

    assert len(veto) == 2
    assert veto[0]["condition_evaluated"] is True
    assert veto[0]["condition_passed"] is False
    assert veto[1]["condition_evaluated"] is False
    assert veto[0]["group_evaluated"] is True
    assert veto[0]["group_matched"] is False


def test_rule_trace_marks_missing_required_evidence_as_evaluated_failure():
    rule = new_rule(
        kind="REQUIRED", evidence="ADX", group_id="entry-adx",
        group_name="ADX entry", regime="BULL", side="LONG",
    )
    rule.update(operator="GTE", value=20.0)
    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=MARKET_PERMISSIONS,
        required_rules=(rule,),
    )
    profile = profiles["bull_long"]
    engine = _trace_engine()
    engine.adx_values[0] = np.nan

    engine._begin_strategy_rule_trace(0, "BULL", "LONG", "bull_long", profile)
    rejected, _detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", profile.reject_rule_match_mode
    )
    assert rejected
    engine._finish_strategy_rule_trace(False, "missing ADX")

    row = engine.strategy_rule_trace_rows[0]
    assert row["condition_evaluated"] is True
    assert row["evidence_available"] is False
    assert row["condition_passed"] is False
    assert row["group_evaluated"] is True
    assert row["group_matched"] is False


def test_muted_required_group_does_not_reject_clean_baseline():
    engine = _engine()
    muted_required = _rule(
        action="REJECT",
        kind="REQUIRED",
        group="muted-entry",
        name="Experimental entry filters",
        matched=True,
        rule_id="mr1",
    )
    muted_required["_builder_group_enabled"] = False
    profile = SimpleNamespace(entry_rules=(muted_required,))

    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", "ANY"
    )
    assert not rejected
    assert detail is None


def test_muted_veto_and_flip_groups_have_zero_runtime_effect():
    engine = _engine()

    muted_veto = _rule(
        action="REJECT",
        kind="VETO",
        group="muted-veto",
        name="Muted veto",
        matched=True,
        rule_id="mv1",
    )
    muted_veto["_builder_group_enabled"] = False
    veto_profile = SimpleNamespace(entry_rules=(muted_veto,))
    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", veto_profile, "REJECT", "ANY"
    )
    assert not rejected
    assert detail is None

    muted_flip = _rule(
        action="FLIP",
        kind="FLIP",
        group="muted-flip",
        name="Muted flip",
        matched=True,
        rule_id="mf1",
    )
    muted_flip["_builder_group_enabled"] = False
    flip_profile = SimpleNamespace(entry_rules=(muted_flip,))
    flipped, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", flip_profile, "FLIP", "ANY"
    )
    assert not flipped
    assert detail is None


def test_muted_and_active_required_groups_only_consider_active_group():
    engine = _engine()
    muted = _rule(
        action="REJECT",
        kind="REQUIRED",
        group="muted",
        name="Muted entry",
        matched=False,
        rule_id="m1",
    )
    muted["_builder_group_enabled"] = False
    active = _rule(
        action="REJECT",
        kind="REQUIRED",
        group="active",
        name="Active entry",
        matched=True,
        rule_id="a1",
    )
    profile = SimpleNamespace(entry_rules=(muted, active))

    rejected, detail = engine._strategy_profile_rule_action_result(
        0, "LONG", profile, "REJECT", "ANY"
    )
    assert rejected
    assert "Active entry" in detail
    assert "Muted entry" not in detail
