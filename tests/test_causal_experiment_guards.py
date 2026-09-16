import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore


def _definition():
    return {
        "symbol": "ETHUSDT",
        "strategy_timeframe": "4h",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "multiple": 1.0},
        "take_profit": {"type": "R", "multiple": 1.0},
        "regime_method": "ASSET_RETURN",
        "risk_model": "FIXED_FRACTIONAL",
        "reference_run": "ETHUSDT_4h_reference",
        "initial_equity": 2500.0,
        "risk_pct": 1.0,
    }


def _create(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    created = store.create("ETHUSDT_4H_DI_1R_WF001", _definition(), "create:eth:001")
    return store, created


def test_operation_id_cannot_be_reused_for_different_mutation(tmp_path):
    store, created = _create(tmp_path)
    first = store.append_event(
        "ETHUSDT_4H_DI_1R_WF001",
        "REVIEW_COMPLETED",
        {"cadence": "MONTHLY", "period": "2026-08"},
        "review:2026-08",
        created["sequence"],
        created["state_hash"],
    )
    assert first["sequence"] == 2

    with pytest.raises(ValueError, match="operation_id was already used"):
        store.append_event(
            "ETHUSDT_4H_DI_1R_WF001",
            "REVIEW_COMPLETED",
            {"cadence": "MONTHLY", "period": "2026-09"},
            "review:2026-08",
            first["sequence"],
            first["state_hash"],
        )


def test_decision_hash_must_match_exact_current_state(tmp_path):
    store, created = _create(tmp_path)
    captured = store.append_event(
        "ETHUSDT_4H_DI_1R_WF001",
        "CANDIDATE_CONTEXT_CAPTURED",
        {"candidate_id": "candidate-1", "feature_hash": "features-1"},
        "candidate:1:capture",
        created["sequence"],
        created["state_hash"],
    )

    with pytest.raises(ValueError, match="state_hash_at_decision"):
        store.append_event(
            "ETHUSDT_4H_DI_1R_WF001",
            "DECISION_FROZEN",
            {
                "candidate_id": "candidate-1",
                "final_action": "LONG",
                "state_hash_at_decision": created["state_hash"],
            },
            "candidate:1:freeze",
            captured["sequence"],
            captured["state_hash"],
        )


def test_prospective_trade_cannot_resolve_before_outcome_reveal(tmp_path):
    store, created = _create(tmp_path)
    captured = store.append_event(
        "ETHUSDT_4H_DI_1R_WF001",
        "CANDIDATE_CONTEXT_CAPTURED",
        {"candidate_id": "candidate-2", "feature_hash": "features-2"},
        "candidate:2:capture",
        created["sequence"],
        created["state_hash"],
    )
    frozen = store.append_event(
        "ETHUSDT_4H_DI_1R_WF001",
        "DECISION_FROZEN",
        {
            "candidate_id": "candidate-2",
            "final_action": "SHORT",
            "state_hash_at_decision": captured["state_hash"],
        },
        "candidate:2:freeze",
        captured["sequence"],
        captured["state_hash"],
    )

    with pytest.raises(ValueError, match="revealed outcome"):
        store.append_event(
            "ETHUSDT_4H_DI_1R_WF001",
            "TRADE_RESOLVED",
            {"candidate_id": "candidate-2", "ledger": "RESEARCH", "net_r": -1.0},
            "candidate:2:resolve-too-soon",
            frozen["sequence"],
            frozen["state_hash"],
        )


def test_rule_promotion_requires_known_version(tmp_path):
    store, created = _create(tmp_path)

    with pytest.raises(ValueError, match="unknown rule version"):
        store.append_event(
            "ETHUSDT_4H_DI_1R_WF001",
            "RULE_PROMOTED_TO_LIVE",
            {"rule_id": "Entry99", "rule_version": "v1"},
            "rule:Entry99:v1:live",
            created["sequence"],
            created["state_hash"],
        )
