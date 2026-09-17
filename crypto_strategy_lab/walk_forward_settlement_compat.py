"""Settlement compatibility for canonical nested walk-forward risk models.

New standardized experiments describe risk as a fractional equity allocation::

    risk_model = {
        "type": "percent_equity",
        "initial_equity": 1000.0,
        "risk_per_trade": 0.01,
    }

Older experiments store ``initial_equity`` and ``risk_pct`` at the definition
root, where ``risk_pct`` is expressed in percentage points (``1.0`` means 1%).
This module makes the nested form authoritative while preserving the legacy
fields as a fallback. It does not mutate immutable experiment definitions.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab import walk_forward_orchestrator_impl as _impl


_INSTALLED = False
_ORIGINAL_DERIVE_STATE = CausalExperimentStore._derive_state


def _risk_terms(definition: dict[str, Any]) -> tuple[Decimal, Decimal, str]:
    """Return (fraction, percentage-points, source) with nested risk preferred."""
    risk_model = definition.get("risk_model")
    if isinstance(risk_model, dict):
        nested = risk_model.get("risk_per_trade")
        if nested not in (None, ""):
            fraction = _impl._decimal(nested, "risk_model.risk_per_trade")
            if not Decimal("0") < fraction <= Decimal("1"):
                raise ValueError(
                    "risk_model.risk_per_trade must be greater than 0 and at most 1"
                )
            return fraction, fraction * Decimal("100"), "risk_model.risk_per_trade"

    legacy = definition.get("risk_pct")
    if legacy in (None, ""):
        raise ValueError(
            "immutable experiment definition has no risk_model.risk_per_trade "
            "or legacy risk_pct; cannot settle equity deterministically"
        )
    pct = _impl._decimal(legacy, "risk_pct")
    if not Decimal("0") < pct <= Decimal("100"):
        raise ValueError("risk_pct must be greater than 0 and at most 100")
    return pct / Decimal("100"), pct, "risk_pct"


def _initial_equity_raw(definition: dict[str, Any]) -> Any:
    """Prefer the canonical nested initial equity, then the legacy root field."""
    risk_model = definition.get("risk_model")
    if isinstance(risk_model, dict):
        nested = risk_model.get("initial_equity")
        if nested not in (None, ""):
            return nested
    return definition.get("initial_equity")


def _derive_state_with_nested_initial_equity(
    manifest: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Expose canonical initial equity before the first resolved trade."""
    state = _ORIGINAL_DERIVE_STATE(manifest, events)
    research = (state.get("ledgers") or {}).get("RESEARCH") or {}
    if research.get("equity") in (None, ""):
        definition = manifest.get("definition") or {}
        initial = _initial_equity_raw(definition)
        if initial not in (None, ""):
            # Validate now so malformed immutable definitions fail loudly rather
            # than silently advertising unusable ledger state.
            value = _impl._decimal(initial, "initial_equity")
            if value <= 0:
                raise ValueError("initial_equity must be positive")
            research["equity"] = _impl._money(value)
    return state


def resolve_walk_forward_trade(
    control: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    """Settle a revealed trade using canonical nested risk with legacy fallback."""
    store = _impl._store(control)
    events = _impl._events(store, experiment_id)
    existing = _impl._existing_resolution(events, candidate_id)
    if existing is not None:
        payload = deepcopy(existing.get("payload") or {})
        return {
            "contract": _impl.SETTLEMENT_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": existing["sequence"],
            "state_hash": existing["resulting_state_hash"],
            "candidate_id": candidate_id,
            "settlement": payload,
            "idempotent_replay": True,
        }

    store, readback, events = _impl._verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    if store._candidate_state(events, candidate_id) != "OUTCOME_REVEALED":
        raise ValueError("trade can only be settled after its outcome is revealed")

    capture = (_impl._candidate_capture(events, candidate_id).get("payload") or {})
    frozen_event = _impl._event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    revealed_event = _impl._event_for_candidate(events, "OUTCOME_REVEALED", candidate_id)
    assert frozen_event is not None and revealed_event is not None
    frozen = frozen_event.get("payload") or {}
    revealed = revealed_event.get("payload") or {}
    outcome = revealed.get("outcome") or {}
    net_r = _impl._decimal(
        outcome.get("net_r", outcome.get("pair_net_r")), "outcome net_r"
    )

    definition = (readback.get("manifest") or {}).get("definition") or {}
    risk_fraction, risk_pct, risk_source = _risk_terms(definition)

    equity_raw = (
        ((readback.get("derived_state") or {}).get("ledgers") or {})
        .get("RESEARCH", {})
        .get("equity")
    )
    if equity_raw in (None, ""):
        equity_raw = _initial_equity_raw(definition)
    if equity_raw in (None, ""):
        raise ValueError(
            "immutable experiment definition has no risk_model.initial_equity "
            "or legacy initial_equity; cannot settle equity deterministically"
        )
    equity_before = _impl._decimal(equity_raw, "research equity")
    if equity_before <= 0:
        raise ValueError("research equity must be positive")

    risk_amount = equity_before * risk_fraction
    net_pnl = risk_amount * net_r
    equity_after = equity_before + net_pnl
    result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
    exit_time = outcome.get("exit_time") or capture.get("entry_time")

    entered_op = _impl._operation(operation_id, "entered")
    current_events = _impl._events(store, experiment_id)
    entered = _impl._event_for_candidate(current_events, "TRADE_ENTERED", candidate_id)
    if entered is None:
        current = store.read(experiment_id, recent_events=0)
        store.append_event(
            experiment_id,
            "TRADE_ENTERED",
            {
                "candidate_id": candidate_id,
                "candidate_token": capture.get("candidate_token"),
                "ledger": "RESEARCH",
                "final_action": frozen.get("final_action"),
                "equity_before": _impl._money(equity_before),
                # Canonical fractional value plus legacy percentage-points alias.
                "risk_per_trade": float(risk_fraction),
                "risk_pct": float(risk_pct),
                "risk_source": risk_source,
                "risk_amount": _impl._money(risk_amount),
            },
            entered_op,
            int(current["sequence"]),
            str(current["state_hash"]),
            effective_market_time=str(capture.get("entry_time")),
            source="DETERMINISTIC_LEDGER",
        )

    current = store.read(experiment_id, recent_events=0)
    resolved = store.append_event(
        experiment_id,
        "TRADE_RESOLVED",
        {
            "candidate_id": candidate_id,
            "candidate_token": capture.get("candidate_token"),
            "ledger": "RESEARCH",
            "final_action": frozen.get("final_action"),
            "result": result,
            "net_r": float(net_r),
            "risk_per_trade": float(risk_fraction),
            "risk_pct": float(risk_pct),
            "risk_source": risk_source,
            "risk_amount": _impl._money(risk_amount),
            "net_pnl": _impl._money(net_pnl),
            "equity_before": _impl._money(equity_before),
            "equity_after": _impl._money(equity_after),
            "reference_outcome_sample_id": outcome.get("research_sample_id"),
            "settlement_contract": _impl.SETTLEMENT_CONTRACT,
        },
        _impl._operation(operation_id, "resolved"),
        int(current["sequence"]),
        str(current["state_hash"]),
        effective_market_time=str(exit_time),
        source="DETERMINISTIC_LEDGER",
    )
    payload = deepcopy(resolved.get("event") or {}).get("payload") or {}
    return {
        "contract": _impl.SETTLEMENT_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": resolved["sequence"],
        "state_hash": resolved["state_hash"],
        "candidate_id": candidate_id,
        "settlement": payload,
        "idempotent_replay": False,
    }


def install_settlement_compat() -> None:
    """Patch the runtime module used by accelerated orchestration and store reads."""
    global _INSTALLED
    if _INSTALLED:
        return
    _impl.resolve_walk_forward_trade = resolve_walk_forward_trade
    CausalExperimentStore._derive_state = staticmethod(
        _derive_state_with_nested_initial_equity
    )
    _INSTALLED = True
