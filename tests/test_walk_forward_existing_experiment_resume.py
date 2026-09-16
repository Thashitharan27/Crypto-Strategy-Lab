from __future__ import annotations

from types import SimpleNamespace

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab import walk_forward_orchestrator_impl as orchestrator_impl
from crypto_strategy_lab.walk_forward_orchestrator import advance_walk_forward


EXPERIMENT_ID = "BTCUSDT_1D_WF_EXISTING_COMPAT_TEST"
REFERENCE_RUN = "BTCUSDT_1d_reference"


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
        "reference_run": REFERENCE_RUN,
        "initial_equity": 1000.0,
        "risk_pct": 1.0,
    }


def test_advance_resumes_frozen_candidate_using_definition_reference_run(
    tmp_path, monkeypatch
):
    control = SimpleNamespace(project_root=tmp_path)
    reports = object()
    store = CausalExperimentStore(tmp_path / "walk_forward_experiments")
    head = store.create(EXPERIMENT_ID, _definition(), "create:existing-compat")

    candidate_id = "2029"
    candidate = {
        "candidate_id": candidate_id,
        "candidate_token": "legacy-token-2029",
        "feature_hash": "legacy-feature-hash",
        "research_signal_index": 2029,
        "strategy_profile_key": "bull_long",
        "source_side": "LONG",
        "entry_time": "2025-12-20T00:00:00Z",
        "decision_available_at": "2025-12-20T00:00:00Z",
        "matched_entry_groups": ["ENTRY_032"],
        "context": {"adx": 25.0},
        # Intentionally no reference_run: this matches the older captured shape.
    }
    head = store.append_event(
        EXPERIMENT_ID,
        "CANDIDATE_CONTEXT_CAPTURED",
        candidate,
        "capture:2029",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-12-20T00:00:00Z",
    )
    head = store.append_event(
        EXPERIMENT_ID,
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate["candidate_token"],
            "final_action": "LONG",
            "confidence_pct": 70,
            "reasoning": "Previously frozen decision.",
            "state_hash_at_decision": head["state_hash"],
            "feature_hash": candidate["feature_hash"],
        },
        "freeze:2029",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-12-20T00:00:00Z",
    )

    observed = {}

    def fake_outcome(_reports, reference_run, captured, frozen_side):
        observed["reference_run"] = reference_run
        observed["candidate_id"] = captured["candidate_id"]
        observed["side"] = frozen_side
        return {
            "research_sample_id": "2029-LONG",
            "research_signal_index": 2029,
            "side": "LONG",
            "entry_time": "2025-12-20T00:00:00Z",
            "exit_time": "2025-12-21T00:00:00Z",
            "pair_net_r": -1.0,
            "net_r": -1.0,
            "result": "LOSS",
        }

    monkeypatch.setattr(
        orchestrator_impl, "_outcome_row_after_decision", fake_outcome
    )

    result = advance_walk_forward(
        control,
        reports,
        experiment_id=EXPERIMENT_ID,
        operation_id="advance:existing-compat",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )

    assert observed == {
        "reference_run": REFERENCE_RUN,
        "candidate_id": candidate_id,
        "side": "LONG",
    }
    assert result["status"] == "LOSS_REVIEW_REQUIRED"
    assert result["candidate_id"] == candidate_id
    assert result["settlement"]["equity_before"] == 1000.0
    assert result["settlement"]["equity_after"] == 990.0
    assert (
        store.read(EXPERIMENT_ID)["derived_state"]["candidate_states"][candidate_id]
        == "COMPLETE"
    )
