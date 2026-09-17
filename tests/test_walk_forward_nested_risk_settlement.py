from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path

from crypto_strategy_lab import walk_forward_orchestrator as orchestrator
from crypto_strategy_lab import walk_forward_orchestrator_impl as orchestrator_impl
from crypto_strategy_lab.walk_forward_candidate_engine import get_next_walk_forward_candidate
from crypto_strategy_lab.walk_forward_settlement_compat import (
    _risk_terms,
    install_settlement_compat,
    resolve_walk_forward_trade,
)


NESTED_EXPERIMENT_ID = "BTCUSDT_1D_WF_NESTED_RISK"


def _legacy_test_module():
    path = Path(__file__).with_name("test_walk_forward_orchestrator.py")
    spec = importlib.util.spec_from_file_location("wf_nested_risk_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nested_experiment(tmp_path, *, risk_per_trade: float = 0.01):
    helpers = _legacy_test_module()
    control, reports, store, _legacy_head = helpers._write_reference(tmp_path)

    definition = helpers._definition()
    definition.pop("initial_equity", None)
    definition.pop("risk_pct", None)
    definition["risk_model"] = {
        "type": "percent_equity",
        "initial_equity": 1000.0,
        "risk_per_trade": risk_per_trade,
    }
    head = store.create(NESTED_EXPERIMENT_ID, definition, "create:nested-risk")
    head = store.append_event(
        NESTED_EXPERIMENT_ID,
        "ENTRY_LEARNED",
        {
            "rule_id": "ENTRY_001",
            "rule_version": "1",
            "effective_from": "2025-01-01T00:00:00Z",
            "reason": "nested risk settlement test",
            "evidence_source": "TEACHER",
            "profile": "bull_long",
            "conditions": [{"indicator": "ADX", "condition": "GTE", "value": 30}],
        },
        "rule:nested-entry",
        head["sequence"],
        head["state_hash"],
        effective_market_time="2025-01-01T00:00:00Z",
    )
    candidate = get_next_walk_forward_candidate(
        control,
        reports,
        experiment_id=NESTED_EXPERIMENT_ID,
        operation_id="candidate:nested-risk",
        expected_sequence=head["sequence"],
        expected_state_hash=head["state_hash"],
    )
    captured = candidate["candidate"]
    revealed = orchestrator.freeze_and_reveal_walk_forward_view(
        control,
        reports,
        experiment_id=NESTED_EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        candidate_token=captured["candidate_token"],
        final_action="SHORT",
        confidence_pct=61,
        reasoning="Research-only short view; strategy remains long.",
        operation_id="decision:nested-risk",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
    )
    assert revealed["strategy_action"] == "LONG"
    assert revealed["chatgpt_view"] == "SHORT"
    assert revealed["outcome"]["net_r"] == -1.0
    return helpers, control, reports, store, captured, revealed


def test_nested_risk_model_settles_existing_revealed_loss_without_restart(tmp_path):
    install_settlement_compat()
    _helpers, control, _reports, store, captured, revealed = _nested_experiment(tmp_path)

    # The derived ledger is reconstructed from the immutable nested definition
    # even before the first prospective trade is resolved.
    before = store.read(NESTED_EXPERIMENT_ID)
    assert before["derived_state"]["ledgers"]["RESEARCH"]["equity"] == 1000.0
    assert before["derived_state"]["candidate_states"][captured["candidate_id"]] == "OUTCOME_REVEALED"

    settled = resolve_walk_forward_trade(
        control,
        experiment_id=NESTED_EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        operation_id="settlement:nested-risk",
        expected_sequence=revealed["sequence"],
        expected_state_hash=revealed["state_hash"],
    )

    payload = settled["settlement"]
    assert payload["result"] == "LOSS"
    assert payload["risk_source"] == "risk_model.risk_per_trade"
    assert payload["risk_per_trade"] == 0.01
    assert payload["risk_pct"] == 1.0
    assert payload["risk_amount"] == 10.0
    assert payload["net_pnl"] == -10.0
    assert payload["equity_before"] == 1000.0
    assert payload["equity_after"] == 990.0
    after = store.read(NESTED_EXPERIMENT_ID)
    assert after["derived_state"]["ledgers"]["RESEARCH"]["equity"] == 990.0
    assert after["derived_state"]["candidate_states"][captured["candidate_id"]] == "COMPLETE"


def test_legacy_root_risk_pct_remains_supported(tmp_path):
    helpers = _legacy_test_module()
    control, reports, store, head = helpers._write_reference(tmp_path)
    candidate = helpers._capture(control, reports, head)
    captured = candidate["candidate"]
    revealed = orchestrator.freeze_and_reveal_walk_forward_view(
        control,
        reports,
        experiment_id=helpers.EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        candidate_token=captured["candidate_token"],
        final_action="LONG",
        confidence_pct=70,
        reasoning="Legacy settlement compatibility.",
        operation_id="decision:legacy-risk",
        expected_sequence=candidate["sequence"],
        expected_state_hash=candidate["state_hash"],
    )
    settled = resolve_walk_forward_trade(
        control,
        experiment_id=helpers.EXPERIMENT_ID,
        candidate_id=captured["candidate_id"],
        operation_id="settlement:legacy-risk",
        expected_sequence=revealed["sequence"],
        expected_state_hash=revealed["state_hash"],
    )
    payload = settled["settlement"]
    assert payload["risk_source"] == "risk_pct"
    assert payload["risk_per_trade"] == 0.01
    assert payload["risk_pct"] == 1.0
    assert payload["risk_amount"] == 10.0
    assert payload["equity_after"] == 990.0


def test_nested_risk_is_authoritative_over_legacy_fallback():
    fraction, pct, source = _risk_terms(
        {
            "risk_model": {"risk_per_trade": 0.02},
            "risk_pct": 1.0,
        }
    )
    assert fraction == Decimal("0.02")
    assert pct == Decimal("2.00")
    assert source == "risk_model.risk_per_trade"


def test_mcp_routes_direct_and_accelerated_settlement_through_nested_compat():
    from mcp_server import control_server
    from mcp_server import control_server_impl

    assert control_server_impl._resolve_walk_forward_trade is resolve_walk_forward_trade
    assert orchestrator_impl.resolve_walk_forward_trade is resolve_walk_forward_trade
    assert orchestrator.resolve_walk_forward_trade is resolve_walk_forward_trade
    assert control_server._nested_risk_resolve_walk_forward_trade is resolve_walk_forward_trade
