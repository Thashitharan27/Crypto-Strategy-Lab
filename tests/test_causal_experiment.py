from __future__ import annotations

import json

import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "1d",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 1.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": "BTCUSDT_1d_reference",
        "initial_equity": 2500.0,
        "risk_pct": 1.0,
        "decision_time": "WAIT_UNTIL_CLOSED",
        "feature_schema_version": 1,
        "fee_model_version": "native",
    }


def _create(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    created = store.create(
        "BTCUSDT_1D_DI_1R_WF001",
        _definition(),
        "create:BTC:001",
    )
    return store, created


def test_create_read_and_list_experiment(tmp_path):
    store, created = _create(tmp_path)

    assert created["sequence"] == 1
    assert created["phase"] == "RESEARCH_WF"
    assert len(created["state_hash"]) == 64

    readback = store.read("BTCUSDT_1D_DI_1R_WF001")
    assert readback["manifest"]["definition"]["reference_run"] == "BTCUSDT_1d_reference"
    assert readback["manifest"]["definition"]["periodic_review_policy"] == {
        "initial_anchor": "REFERENCE_PERIOD_START"
    }
    assert readback["manifest"]["definition"]["rule_update_policy"] == {
        "mode": "TRADE_BY_TRADE"
    }
    assert readback["sequence"] == 1
    assert readback["state_hash"] == created["state_hash"]
    assert readback["derived_state"]["phase"] == "RESEARCH_WF"

    rows = store.list_experiments()
    assert rows == [
        {
            "experiment_id": "BTCUSDT_1D_DI_1R_WF001",
            "created_at": readback["manifest"]["created_at"],
            "definition_sha256": readback["manifest"]["definition_sha256"],
            "symbol": "BTCUSDT",
            "strategy_timeframe": "1d",
            "sequence": 1,
            "state_hash": created["state_hash"],
            "phase": "RESEARCH_WF",
        }
    ]


def test_manual_periodic_review_anchor_policy_is_preserved(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["periodic_review_policy"] = {"initial_anchor": "manual"}

    store.create("BTC_MANUAL_REVIEW", definition, "create:manual")
    readback = store.read("BTC_MANUAL_REVIEW")

    assert readback["manifest"]["definition"]["periodic_review_policy"] == {
        "initial_anchor": "MANUAL"
    }



def test_bootstrap_protocol_starts_in_bootstrap_phase_and_anchors_reviews_at_wf_start(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["research_protocol"] = {
        "mode": "bootstrap_then_wf",
        "bootstrap_start": "2020-06-01T00:00:00Z",
        "walk_forward_start": "2022-06-01T00:00:00Z",
    }

    created = store.create("BTC_BOOTSTRAP_WF", definition, "create:bootstrap")
    readback = store.read("BTC_BOOTSTRAP_WF")

    assert created["phase"] == "BOOTSTRAP_RESEARCH"
    assert readback["derived_state"]["phase"] == "BOOTSTRAP_RESEARCH"
    assert readback["manifest"]["definition"]["research_protocol"] == {
        "mode": "BOOTSTRAP_THEN_WF",
        "bootstrap_start": "2020-06-01T00:00:00+00:00",
        "walk_forward_start": "2022-06-01T00:00:00+00:00",
    }
    assert readback["manifest"]["definition"]["periodic_review_policy"] == {
        "initial_anchor": "WALK_FORWARD_START"
    }



def test_bootstrap_monthly_summary_defaults_to_walk_forward_start(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["research_protocol"] = {
        "mode": "BOOTSTRAP_THEN_WF",
        "bootstrap_start": "2020-06-01T00:00:00Z",
        "walk_forward_start": "2022-06-01T00:00:00Z",
    }
    created = store.create("BTC_BOOTSTRAP_MONTHLY", definition, "create:bootstrap-monthly")
    store.append_event(
        "BTC_BOOTSTRAP_MONTHLY",
        "PHASE_CHANGED",
        {"phase": "RESEARCH_WF", "reason": "test cutoff"},
        "phase:bootstrap-monthly",
        created["sequence"],
        created["state_hash"],
        effective_market_time="2022-06-01T00:00:00Z",
    )

    summary = store.summarize_monthly("BTC_BOOTSTRAP_MONTHLY")

    assert [row["month"] for row in summary["months"]] == ["2022-06"]
    assert summary["totals"]["trades"] == 0

def test_bootstrap_protocol_rejects_invalid_training_window(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["research_protocol"] = {
        "mode": "BOOTSTRAP_THEN_WF",
        "bootstrap_start": "2022-06-01T00:00:00Z",
        "walk_forward_start": "2022-06-01T00:00:00Z",
    }

    with pytest.raises(ValueError, match="bootstrap_start must be before"):
        store.create("BTC_BAD_BOOTSTRAP_WF", definition, "create:bad-bootstrap")

def test_monthly_batch_oos_policy_is_normalized_and_frozen(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {"mode": "monthly_batch_oos"}

    store.create("BTC_MONTHLY_BATCH_WF", definition, "create:monthly-batch")
    readback = store.read("BTC_MONTHLY_BATCH_WF")

    assert readback["manifest"]["definition"]["rule_update_policy"] == {
        "mode": "MONTHLY_BATCH_OOS",
        "interval_months": 1,
        "freeze_between_reviews": True,
    }


def test_weekly_batch_oos_policy_is_normalized_and_frozen(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {"mode": "weekly_batch_oos"}

    store.create("BTC_WEEKLY_BATCH_WF", definition, "create:weekly-batch")
    readback = store.read("BTC_WEEKLY_BATCH_WF")

    assert readback["manifest"]["definition"]["rule_update_policy"] == {
        "mode": "WEEKLY_BATCH_OOS",
        "interval_weeks": 1,
        "freeze_between_reviews": True,
    }


def test_adaptive_weekly_oos_policy_normalizes_recent_windows(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "weekly_batch_oos",
        "adaptive": True,
    }

    store.create("BTC_ADAPTIVE_WEEKLY_WF", definition, "create:adaptive-weekly")
    readback = store.read("BTC_ADAPTIVE_WEEKLY_WF")

    assert readback["manifest"]["definition"]["rule_update_policy"] == {
        "mode": "WEEKLY_BATCH_OOS",
        "interval_weeks": 1,
        "freeze_between_reviews": True,
        "adaptive": {
            "enabled": True,
            "primary_lookback_weeks": 4,
            "context_lookback_weeks": 12,
            "objective": "NEXT_WEEK_OOS",
            "allow_keep": True,
            "allow_refine": True,
            "allow_retire": True,
            "allow_replace": True,
            "allow_flip": True,
            "benchmark_raw_strategy": True,
            "track_adaptation_lag": True,
            "track_rule_half_life": True,
        },
    }


def test_native_adaptive_weekly_object_contract_and_aliases(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "ADAPTIVE_WEEKLY",
        "adaptive": {
            "enabled": True,
            "primary_lookback_weeks": 1,
            "context_lookback_weeks": 4,
            "objective": "NEXT_WEEK_OOS",
            "allow_keep": True,
            "allow_refine": True,
            "allow_retire": True,
            "allow_replace": True,
            "allow_flip": True,
            "benchmark_raw_strategy": True,
        },
    }
    store.create("BTC_NATIVE_ADAPTIVE", definition, "create:native-adaptive")
    policy = store.read("BTC_NATIVE_ADAPTIVE")["manifest"]["definition"][
        "rule_update_policy"
    ]
    assert policy["mode"] == "WEEKLY_BATCH_OOS"
    assert policy["adaptive"]["enabled"] is True
    assert policy["adaptive"]["primary_lookback_weeks"] == 1
    assert policy["adaptive"]["context_lookback_weeks"] == 4

    alias_definition = _definition()
    alias_definition["adaptive_weekly"] = True
    alias_definition["adaptive_policy"] = {
        "primary_lookback_weeks": 1,
        "context_lookback_weeks": 4,
        "objective": "NEXT_WEEK_OOS",
    }
    store.create("BTC_ALIAS_ADAPTIVE", alias_definition, "create:alias-adaptive")
    normalized = store.read("BTC_ALIAS_ADAPTIVE")["manifest"]["definition"]
    assert "adaptive_weekly" not in normalized
    assert "adaptive_policy" not in normalized
    assert normalized["rule_update_policy"]["mode"] == "WEEKLY_BATCH_OOS"
    assert normalized["rule_update_policy"]["adaptive"]["enabled"] is True


def test_adaptive_policy_requires_weekly_batch_oos(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "MONTHLY_BATCH_OOS",
        "adaptive": True,
    }

    with pytest.raises(ValueError, match="adaptive rule updates require"):
        store.create("BTC_BAD_ADAPTIVE_MONTHLY", definition, "create:bad-adaptive")


def test_weekly_batch_oos_rejects_non_weekly_interval(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "WEEKLY_BATCH_OOS",
        "interval_weeks": 2,
        "freeze_between_reviews": True,
    }

    with pytest.raises(ValueError, match="interval_weeks must be 1"):
        store.create("BTC_BAD_WEEKLY_INTERVAL", definition, "create:bad-weekly")


def test_monthly_batch_oos_rejects_non_monthly_interval(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "MONTHLY_BATCH_OOS",
        "interval_months": 2,
        "freeze_between_reviews": True,
    }

    with pytest.raises(ValueError, match="interval_months must be 1"):
        store.create("BTC_BAD_MONTHLY_INTERVAL", definition, "create:bad-monthly")


def test_monthly_batch_oos_rejects_unfrozen_rules(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition["rule_update_policy"] = {
        "mode": "MONTHLY_BATCH_OOS",
        "interval_months": 1,
        "freeze_between_reviews": False,
    }

    with pytest.raises(ValueError, match="freeze_between_reviews=true"):
        store.create("BTC_BAD_MONTHLY_FREEZE", definition, "create:bad-freeze")


def test_definition_requires_experiment_identity_fields(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    definition = _definition()
    definition.pop("take_profit")

    with pytest.raises(ValueError, match="take_profit"):
        store.create("BTC_TEST", definition, "create:missing")


def test_context_freeze_reveal_state_machine(tmp_path):
    store, created = _create(tmp_path)
    experiment_id = "BTCUSDT_1D_DI_1R_WF001"

    captured = store.append_event(
        experiment_id,
        "CANDIDATE_CONTEXT_CAPTURED",
        {"candidate_id": "2021-05-05T00:00:00Z", "feature_hash": "abc123"},
        "candidate:2021-05-05:capture",
        created["sequence"],
        created["state_hash"],
        effective_market_time="2021-05-05T00:00:00Z",
    )
    assert captured["derived_state"]["candidate_states"]["2021-05-05T00:00:00Z"] == "ENTRY_CONTEXT_CAPTURED"

    with pytest.raises(ValueError, match="decision is frozen"):
        store.append_event(
            experiment_id,
            "OUTCOME_REVEALED",
            {"candidate_id": "2021-05-05T00:00:00Z", "net_r": 1.0},
            "candidate:2021-05-05:reveal-too-soon",
            captured["sequence"],
            captured["state_hash"],
        )

    frozen = store.append_event(
        experiment_id,
        "DECISION_FROZEN",
        {
            "candidate_id": "2021-05-05T00:00:00Z",
            "final_action": "LONG",
            "ai_side": "LONG",
            "ai_confidence": 74,
            "matched_entry_rule_versions": ["Entry15@v3"],
            "state_hash_at_decision": captured["state_hash"],
        },
        "candidate:2021-05-05:freeze",
        captured["sequence"],
        captured["state_hash"],
    )

    revealed = store.append_event(
        experiment_id,
        "OUTCOME_REVEALED",
        {"candidate_id": "2021-05-05T00:00:00Z", "net_r": 1.0},
        "candidate:2021-05-05:reveal",
        frozen["sequence"],
        frozen["state_hash"],
    )
    assert revealed["derived_state"]["candidate_states"]["2021-05-05T00:00:00Z"] == "OUTCOME_REVEALED"


def test_append_is_idempotent_by_operation_id(tmp_path):
    store, created = _create(tmp_path)
    kwargs = dict(
        experiment_id="BTCUSDT_1D_DI_1R_WF001",
        event_type="REVIEW_COMPLETED",
        payload={"cadence": "MONTHLY", "period": "2021-05"},
        operation_id="review:2021-05",
        expected_sequence=created["sequence"],
        expected_state_hash=created["state_hash"],
        effective_market_time="2021-05-31T23:59:59Z",
    )

    first = store.append_event(**kwargs)
    second = store.append_event(**kwargs)

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert second["sequence"] == first["sequence"]
    assert second["state_hash"] == first["state_hash"]
    assert store.read("BTCUSDT_1D_DI_1R_WF001")["sequence"] == 2


def test_stale_sequence_or_hash_is_rejected(tmp_path):
    store, created = _create(tmp_path)
    appended = store.append_event(
        "BTCUSDT_1D_DI_1R_WF001",
        "REVIEW_COMPLETED",
        {"cadence": "MONTHLY"},
        "review:first",
        created["sequence"],
        created["state_hash"],
    )
    assert appended["sequence"] == 2

    with pytest.raises(ValueError, match="changed since it was read"):
        store.append_event(
            "BTCUSDT_1D_DI_1R_WF001",
            "REVIEW_COMPLETED",
            {"cadence": "MONTHLY"},
            "review:stale",
            created["sequence"],
            created["state_hash"],
        )


def test_rule_events_require_precise_version_and_effective_time(tmp_path):
    store, created = _create(tmp_path)

    with pytest.raises(ValueError, match="rule metadata"):
        store.append_event(
            "BTCUSDT_1D_DI_1R_WF001",
            "ENTRY_LEARNED",
            {"rule_id": "Entry15"},
            "rule:Entry15:bad",
            created["sequence"],
            created["state_hash"],
        )

    learned = store.append_event(
        "BTCUSDT_1D_DI_1R_WF001",
        "ENTRY_LEARNED",
        {
            "rule_id": "Entry15",
            "rule_version": "v1",
            "effective_from": "2021-05-05T02:51:00Z",
            "reason": "Resolved teacher winner established structure",
            "evidence_source": "TEACHER",
            "learned_from_trade": "teacher-123",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 20}],
        },
        "rule:Entry15:v1",
        created["sequence"],
        created["state_hash"],
        effective_market_time="2021-05-05T02:51:00Z",
    )
    rule = learned["derived_state"]["rules"]["Entry15@v1"]
    assert rule["deployment_status"] == "RESEARCH_ONLY"
    assert rule["effective_from"] == "2021-05-05T02:51:00Z"

    with pytest.raises(ValueError, match="supersedes_version"):
        store.append_event(
            "BTCUSDT_1D_DI_1R_WF001",
            "ENTRY_REFINED",
            {
                "rule_id": "Entry15",
                "rule_version": "v2",
                "effective_from": "2021-06-01T00:00:00Z",
                "reason": "DI threshold refinement",
                "evidence_source": "PROSPECTIVE_WF",
            },
            "rule:Entry15:v2:bad",
            learned["sequence"],
            learned["state_hash"],
        )


def test_phase_and_rule_deployment_are_derived_from_events(tmp_path):
    store, created = _create(tmp_path)
    learned = store.append_event(
        "BTCUSDT_1D_DI_1R_WF001",
        "ENTRY_LEARNED",
        {
            "rule_id": "Entry1",
            "rule_version": "v1",
            "effective_from": "2021-01-01T00:00:00Z",
            "reason": "teacher evidence",
            "evidence_source": "TEACHER",
        },
        "rule:Entry1:v1",
        created["sequence"],
        created["state_hash"],
    )
    shadow = store.append_event(
        "BTCUSDT_1D_DI_1R_WF001",
        "RULE_PROMOTED_TO_SHADOW",
        {"rule_id": "Entry1", "rule_version": "v1"},
        "rule:Entry1:v1:shadow",
        learned["sequence"],
        learned["state_hash"],
    )
    phase = store.append_event(
        "BTCUSDT_1D_DI_1R_WF001",
        "PHASE_CHANGED",
        {"phase": "SHADOW", "reason": "walk-forward validated"},
        "phase:shadow",
        shadow["sequence"],
        shadow["state_hash"],
    )

    state = phase["derived_state"]
    assert state["phase"] == "SHADOW"
    assert state["rules"]["Entry1@v1"]["deployment_status"] == "SHADOW"


def test_hash_chain_detects_manual_event_tampering(tmp_path):
    store, _ = _create(tmp_path)
    events_path = tmp_path / "experiments" / "BTCUSDT_1D_DI_1R_WF001" / "events.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["initial_phase"] = "LIVE"
    events_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        store.read("BTCUSDT_1D_DI_1R_WF001")


def test_fast_index_matches_audit_and_hot_append_avoids_full_rescan(tmp_path, monkeypatch):
    store, created = _create(tmp_path)
    experiment_id = "BTCUSDT_1D_DI_1R_WF001"

    fast = store.read_fast(experiment_id, recent_events=10)
    audit = store.read(experiment_id, recent_events=10)
    assert fast["sequence"] == audit["sequence"] == 1
    assert fast["state_hash"] == audit["state_hash"]
    assert fast["derived_state"] == audit["derived_state"]

    directory = tmp_path / "experiments" / experiment_id
    assert (directory / "event_index.sqlite3").is_file()
    assert (directory / "head.json").is_file()
    assert (directory / "checkpoint.json").is_file()

    def fail_full_scan(_path):
        raise AssertionError("hot append unexpectedly rescanned the full JSONL chain")

    monkeypatch.setattr(store, "_read_all_events", fail_full_scan)
    appended = store.append_event(
        experiment_id,
        "REVIEW_COMPLETED",
        {"cadence": "WEEKLY", "period": "2021-W18"},
        "review:fast-index",
        created["sequence"],
        created["state_hash"],
        effective_market_time="2021-05-09T23:59:59Z",
    )

    assert appended["sequence"] == 2
    assert appended["fast_index_status"] == "CURRENT"
    assert store.read_fast(experiment_id, recent_events=1)["recent_events"][0]["operation_id"] == "review:fast-index"


def test_fast_index_invalidates_on_authoritative_event_tampering(tmp_path):
    store, _ = _create(tmp_path)
    experiment_id = "BTCUSDT_1D_DI_1R_WF001"
    store.read_fast(experiment_id)

    events_path = tmp_path / "experiments" / experiment_id / "events.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["initial_phase"] = "LIVE"
    events_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash"):
        store.read_fast(experiment_id)


def test_review_event_forces_fast_checkpoint_to_current_head(tmp_path):
    store, created = _create(tmp_path)
    experiment_id = "BTCUSDT_1D_DI_1R_WF001"

    appended = store.append_event(
        experiment_id,
        "REVIEW_COMPLETED",
        {"cadence": "WEEKLY", "period": "2021-W18"},
        "review:checkpoint",
        created["sequence"],
        created["state_hash"],
        effective_market_time="2021-05-09T23:59:59Z",
    )

    checkpoint_path = tmp_path / "experiments" / experiment_id / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["sequence"] == appended["sequence"]
    assert checkpoint["state_hash"] == appended["state_hash"]
    assert checkpoint["derived_state"]["last_review"]["sequence"] == appended["sequence"]
