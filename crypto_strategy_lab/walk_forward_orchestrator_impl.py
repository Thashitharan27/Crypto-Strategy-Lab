"""High-throughput causal walk-forward orchestration.

This module removes MCP/chat round-trips only for deterministic work.  Human/
ChatGPT judgment remains mandatory for direction decisions, teacher learning,
loss review, and periodic review.

The critical outcome firewall is structural: ``freeze_and_reveal`` appends and
fsyncs DECISION_FROZEN before it opens the outcome-bearing paired Walk Forward
artifact. A crash after freezing is recoverable; retrying resumes from the
already-frozen decision and can never replace it.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from crypto_strategy_lab.causal_experiment import CausalExperimentStore, RULE_EVENT_TYPES
from crypto_strategy_lab.walk_forward_candidate_engine import (
    _artifact,
    _candidate_detail_row,
    _candidate_rows,
    _events,
    _max_event_time,
    _next_teacher,
    _open_candidate,
    _quote,
    _row_maps,
    _rule_decision,
    _safe_context,
    _sampling_mode,
    _utc_timestamp,
    get_next_walk_forward_candidate,
)
from crypto_strategy_lab.walk_forward_materialization import materialize_walk_forward_strategy
from crypto_strategy_lab.walk_forward_research_policy import (
    validate_loss_methodology,
    validate_periodic_methodology,
    validate_teacher_methodology,
)
from crypto_strategy_lab.walk_forward_teacher_compression import (
    AUTO_COMPRESSED_STATUS,
    TEACHER_COMPRESSION_CONTRACT,
    teacher_compression_decision,
)



ORCHESTRATOR_CONTRACT = "causal_walk_forward_orchestrator_v1"
DECISION_CONTRACT = "causal_walk_forward_frozen_decision_v1"
OUTCOME_CONTRACT = "causal_walk_forward_revealed_outcome_v1"
SETTLEMENT_CONTRACT = "causal_walk_forward_settlement_v1"

MONTHLY_BATCH_OOS_MODE = "MONTHLY_BATCH_OOS"
WEEKLY_BATCH_OOS_MODE = "WEEKLY_BATCH_OOS"
MONTHLY_BATCH_DEFERRED = "DEFERRED_TO_MONTHLY_BATCH"
WEEKLY_BATCH_DEFERRED = "DEFERRED_TO_WEEKLY_BATCH"
BATCH_OOS_MODES = frozenset({MONTHLY_BATCH_OOS_MODE, WEEKLY_BATCH_OOS_MODE})


def _rule_update_policy(definition: dict[str, Any]) -> dict[str, Any]:
    raw = definition.get("rule_update_policy") or {}
    mode = str(raw.get("mode", "TRADE_BY_TRADE")).strip().upper()
    if mode == MONTHLY_BATCH_OOS_MODE:
        return {
            "mode": MONTHLY_BATCH_OOS_MODE,
            "interval_months": 1,
            "freeze_between_reviews": True,
        }
    if mode == WEEKLY_BATCH_OOS_MODE:
        policy = {
            "mode": WEEKLY_BATCH_OOS_MODE,
            "interval_weeks": 1,
            "freeze_between_reviews": True,
            "adaptive": bool(raw.get("adaptive", False)),
        }
        if policy["adaptive"]:
            policy.update(
                {
                    "primary_lookback_weeks": int(
                        raw.get("primary_lookback_weeks", 4)
                    ),
                    "context_lookback_weeks": int(
                        raw.get("context_lookback_weeks", 12)
                    ),
                    "expire_unconfirmed_after_weeks": int(
                        raw.get("expire_unconfirmed_after_weeks", 12)
                    ),
                    "benchmark_raw_strategy": bool(
                        raw.get("benchmark_raw_strategy", True)
                    ),
                    "track_adaptation_lag": bool(
                        raw.get("track_adaptation_lag", True)
                    ),
                    "track_rule_half_life": bool(
                        raw.get("track_rule_half_life", True)
                    ),
                }
            )
        return policy
    return {"mode": "TRADE_BY_TRADE"}


def _batch_oos_mode(definition: dict[str, Any]) -> str | None:
    mode = _rule_update_policy(definition)["mode"]
    return mode if mode in BATCH_OOS_MODES else None


def _batch_oos_enabled(definition: dict[str, Any]) -> bool:
    return _batch_oos_mode(definition) is not None


def _monthly_batch_enabled(definition: dict[str, Any]) -> bool:
    return _batch_oos_mode(definition) == MONTHLY_BATCH_OOS_MODE


def _weekly_batch_enabled(definition: dict[str, Any]) -> bool:
    return _batch_oos_mode(definition) == WEEKLY_BATCH_OOS_MODE


def _effective_review_interval(
    definition: dict[str, Any], requested_months: int
) -> int:
    if _batch_oos_enabled(definition):
        return 1
    return int(requested_months)

_OUTCOME_FIELDS = (
    "research_sample_id",
    "research_signal_index",
    "walk_forward_candidate_id",
    "walk_forward_candidate_source",
    "walk_forward_source_side",
    "strategy_profile_key",
    "side",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "pair_net_r",
    "pair_net_pnl",
    "configured_sizing_budget_percentage",
    "position_sizing_stop_override_enabled",
    "position_sizing_stop_override_applied",
    "position_sizing_stop_multiple",
    "position_sizing_reference_distance",
    "actual_stop_as_sizing_r",
    "final_target_as_sizing_r",
    "physical_reward_risk_ratio",
    "planned_gross_stop_loss",
    "planned_gross_stop_risk_percentage",
    "estimated_all_in_stop_risk_percentage",
    "result_type",
    "long_exit_reason",
    "short_exit_reason",
    "long_exit_source",
    "short_exit_source",
    "holding_hours",
    "fees",
    "total_fees",
)


def _operation(base: str, suffix: str) -> str:
    raw = f"{str(base).strip()}:{suffix}"
    if len(raw) <= 160:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    keep = max(1, 160 - len(digest) - 1)
    return f"{raw[:keep]}:{digest}"


def _store(control: Any) -> CausalExperimentStore:
    return CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")


def _verified(
    control: Any,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> tuple[CausalExperimentStore, dict[str, Any], list[dict[str, Any]]]:
    store = _store(control)
    readback = store.read(experiment_id, recent_events=0)
    wanted_hash = str(expected_state_hash).strip().lower()
    if int(readback["sequence"]) != int(expected_sequence) or readback["state_hash"] != wanted_hash:
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again"
        )
    events = _events(store, experiment_id)
    sequence, state_hash = store._verify_chain(events)
    if sequence != int(expected_sequence) or state_hash != wanted_hash:
        raise ValueError("walk-forward event chain changed during orchestration")
    return store, readback, events


def _event_for_candidate(
    events: list[dict[str, Any]], event_type: str, candidate_id: str
) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload") or {}
        if str(payload.get("candidate_id", "")) == str(candidate_id):
            return event
    return None


def _candidate_capture(events: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    event = _event_for_candidate(events, "CANDIDATE_CONTEXT_CAPTURED", candidate_id)
    if event is None:
        raise ValueError(f"candidate context is not captured: {candidate_id}")
    return event


def _validate_decision_inputs(
    candidate: dict[str, Any],
    candidate_token: str,
    final_action: str,
    confidence_pct: int,
    reasoning: str,
) -> tuple[str, int, str]:
    token = str(candidate_token).strip()
    if not token or token != str(candidate.get("candidate_token", "")):
        raise ValueError("candidate_token does not match the captured candidate")
    side = str(final_action).strip().upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("final_action must be LONG or SHORT")
    if isinstance(confidence_pct, bool) or not isinstance(confidence_pct, int):
        raise ValueError("confidence_pct must be an integer")
    if not 0 <= confidence_pct <= 100:
        raise ValueError("confidence_pct must be between 0 and 100")
    text = str(reasoning).strip()
    if not text:
        raise ValueError("reasoning cannot be empty")
    if len(text) > 4000:
        raise ValueError("reasoning cannot exceed 4000 characters")
    return side, confidence_pct, text


def _same_frozen_decision(
    event: dict[str, Any], *, candidate_id: str, candidate_token: str,
    final_action: str, confidence_pct: int, reasoning: str,
) -> None:
    payload = event.get("payload") or {}
    expected = {
        "candidate_id": str(candidate_id),
        "candidate_token": str(candidate_token),
        "final_action": str(final_action),
        "confidence_pct": int(confidence_pct),
        "reasoning": str(reasoning),
    }
    actual = {key: payload.get(key) for key in expected}
    if actual != expected:
        raise ValueError("operation_id already froze a different walk-forward decision")


def _outcome_row_after_decision(
    reports: Any,
    reference_run: str,
    candidate: dict[str, Any],
    frozen_side: str,
) -> dict[str, Any]:
    """Read the exact frozen-side outcome. Call only after DECISION_FROZEN is durable."""
    manifest = reports.get_run_manifest(reference_run)
    if _sampling_mode(manifest) != "WALK_FORWARD":
        raise ValueError("reference run is not a WALK_FORWARD paired research run")
    run_dir = reports.resolve_run(reference_run)
    path = _artifact(manifest, run_dir, "research_sampling_trades")
    signal_index_raw = candidate.get("research_signal_index")
    source_side = str(candidate.get("source_side", "")).upper()
    sample_id = str(candidate.get("reference_sample_id") or "").strip()
    paired_candidate_id = str(
        candidate.get("reference_walk_forward_candidate_id") or ""
    ).strip()
    if not paired_candidate_id and signal_index_raw in (None, ""):
        raise ValueError(
            "paired outcome lookup requires walk_forward_candidate_id or research_signal_index"
        )
    signal_index = (
        int(signal_index_raw) if signal_index_raw not in (None, "") else None
    )
    source_profile = str(candidate.get("strategy_profile_key", "")).lower()
    regime = source_profile.rsplit("_", 1)[0] if "_" in source_profile else ""
    target_profile = f"{regime}_{frozen_side.lower()}" if regime else ""

    with duckdb.connect(":memory:") as connection:
        columns = [str(row[0]) for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{_quote(path)}')"
        ).fetchall()]
        required = {
            "research_signal_index", "side", "pair_net_r", "exit_time",
            "walk_forward_candidate_id",
        }
        missing = sorted(required - set(columns))
        if missing:
            raise ValueError(
                "Walk Forward paired artifact cannot resolve a frozen decision; missing: "
                + ", ".join(missing)
            )
        selected = [name for name in _OUTCOME_FIELDS if name in columns]
        escaped = ", ".join(f'"{name.replace(chr(34), chr(34) * 2)}"' for name in selected)
        if paired_candidate_id:
            where = (
                "CAST(walk_forward_candidate_id AS VARCHAR)=? "
                "AND UPPER(CAST(side AS VARCHAR))=?"
            )
            params: list[Any] = [paired_candidate_id, frozen_side]
        else:
            assert signal_index is not None
            where = (
                "CAST(research_signal_index AS BIGINT)=? "
                "AND UPPER(CAST(side AS VARCHAR))=?"
            )
            params = [signal_index, frozen_side]
            if frozen_side == source_side and sample_id and "research_sample_id" in columns:
                where += " AND CAST(research_sample_id AS VARCHAR)=?"
                params.append(sample_id)
            elif target_profile and "strategy_profile_key" in columns:
                where += " AND LOWER(CAST(strategy_profile_key AS VARCHAR))=?"
                params.append(target_profile)
        rows = connection.execute(
            f"SELECT {escaped} FROM read_parquet('{_quote(path)}') WHERE {where} LIMIT 3",
            params,
        ).fetchall()

    if len(rows) != 1:
        if frozen_side != source_side:
            raise ValueError(
                "the frozen side has no unique immutable paired Walk Forward outcome; "
                "decision remains frozen and no outcome was revealed"
            )
        raise ValueError("captured candidate has no unique immutable paired Walk Forward outcome")
    values = dict(zip(selected, rows[0]))
    if paired_candidate_id:
        actual_pair_id = str(values.get("walk_forward_candidate_id") or "").strip()
        if actual_pair_id != paired_candidate_id:
            raise ValueError(
                "paired outcome walk_forward_candidate_id does not match captured candidate"
            )
    actual_side = str(values.get("side") or "").upper()
    if actual_side != frozen_side:
        raise ValueError("paired outcome side does not match requested frozen side")
    if signal_index is not None and values.get("research_signal_index") is not None:
        if int(values["research_signal_index"]) != signal_index:
            raise ValueError(
                "paired outcome research_signal_index does not match captured candidate"
            )
    if (
        source_side in {"LONG", "SHORT"}
        and "walk_forward_source_side" in values
        and str(values.get("walk_forward_source_side") or "").upper() != source_side
    ):
        raise ValueError(
            "paired outcome walk_forward_source_side does not match captured source side"
        )
    if "entry_time" in values and candidate.get("entry_time"):
        actual = _utc_timestamp(values["entry_time"], "outcome entry_time")
        expected = _utc_timestamp(candidate["entry_time"], "candidate entry_time")
        if actual != expected:
            raise ValueError("frozen-side outcome entry_time does not match captured candidate")
    result = {key: _json_value(value) for key, value in values.items()}
    result["net_r"] = float(values["pair_net_r"])
    result["result"] = "WIN" if result["net_r"] > 0 else ("LOSS" if result["net_r"] < 0 else "BREAKEVEN")
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return _utc_timestamp(value, "timestamp").isoformat()
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _reveal_frozen_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
) -> dict[str, Any]:
    store = _store(control)
    events = _events(store, experiment_id)
    reveal_op = _operation(operation_id, "reveal")
    existing_op = store._find_operation(events, reveal_op)
    if existing_op is not None:
        return {
            "contract": OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": existing_op["sequence"],
            "state_hash": existing_op["resulting_state_hash"],
            "candidate_id": candidate_id,
            "outcome": deepcopy(existing_op.get("payload") or {}).get("outcome"),
            "idempotent_replay": True,
        }

    state = store._candidate_state(events, candidate_id)
    if state == "OUTCOME_REVEALED":
        revealed = _event_for_candidate(events, "OUTCOME_REVEALED", candidate_id)
        assert revealed is not None
        return {
            "contract": OUTCOME_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": revealed["sequence"],
            "state_hash": revealed["resulting_state_hash"],
            "candidate_id": candidate_id,
            "outcome": deepcopy(revealed.get("payload") or {}).get("outcome"),
            "idempotent_replay": True,
        }
    if state != "DECISION_FROZEN":
        raise ValueError("outcome can only be read after the decision is durably frozen")

    capture_event = _candidate_capture(events, candidate_id)
    candidate = capture_event.get("payload") or {}
    frozen_event = _event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    assert frozen_event is not None
    frozen = frozen_event.get("payload") or {}
    frozen_side = str(frozen.get("final_action", "")).upper()
    reference_run = str(candidate.get("reference_run", "")).strip()
    if not reference_run:
        raise ValueError("captured candidate has no reference_run")

    # OUTCOME FIREWALL: the outcome-bearing artifact is first opened here, after
    # DECISION_FROZEN has already been appended+fsynced by CausalExperimentStore.
    outcome = _outcome_row_after_decision(reports, reference_run, candidate, frozen_side)
    readback = store.read(experiment_id, recent_events=0)
    exit_time = outcome.get("exit_time")
    appended = store.append_event(
        experiment_id,
        "OUTCOME_REVEALED",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate.get("candidate_token"),
            "final_action": frozen_side,
            "outcome_contract": OUTCOME_CONTRACT,
            "outcome": outcome,
        },
        reveal_op,
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=str(exit_time) if exit_time else str(candidate.get("entry_time")),
        source="DETERMINISTIC_OUTCOME_FIREWALL",
    )
    return {
        "contract": OUTCOME_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": appended["sequence"],
        "state_hash": appended["state_hash"],
        "candidate_id": candidate_id,
        "outcome": outcome,
        "idempotent_replay": False,
    }


def freeze_and_reveal_walk_forward_candidate(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    candidate_token: str,
    final_action: str,
    confidence_pct: int,
    reasoning: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    """Durably freeze ChatGPT's decision, then and only then reveal exact outcome."""
    store = _store(control)
    events = _events(store, experiment_id)
    freeze_op = _operation(operation_id, "freeze")
    existing_freeze = store._find_operation(events, freeze_op)
    if existing_freeze is not None:
        candidate = _candidate_capture(events, candidate_id).get("payload") or {}
        side, confidence, text = _validate_decision_inputs(
            candidate, candidate_token, final_action, confidence_pct, reasoning
        )
        _same_frozen_decision(
            existing_freeze,
            candidate_id=candidate_id,
            candidate_token=candidate_token,
            final_action=side,
            confidence_pct=confidence,
            reasoning=text,
        )
        return _reveal_frozen_candidate(
            control, reports, experiment_id=experiment_id,
            candidate_id=candidate_id, operation_id=operation_id,
        )

    store, readback, events = _verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    candidate_event = _candidate_capture(events, candidate_id)
    candidate = candidate_event.get("payload") or {}
    side, confidence, text = _validate_decision_inputs(
        candidate, candidate_token, final_action, confidence_pct, reasoning
    )
    if store._candidate_state(events, candidate_id) != "ENTRY_CONTEXT_CAPTURED":
        raise ValueError("candidate is not waiting for a decision")
    frozen = store.append_event(
        experiment_id,
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate_token,
            "final_action": side,
            "confidence_pct": confidence,
            "reasoning": text,
            "state_hash_at_decision": str(expected_state_hash),
            "feature_hash": candidate.get("feature_hash"),
            "strategy_snapshot_sha256": candidate.get("strategy_snapshot_sha256"),
        },
        freeze_op,
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=str(candidate.get("decision_available_at") or candidate.get("entry_time")),
        source="CHATGPT_FROZEN_DECISION",
    )
    # CausalExperimentStore fsyncs the event before returning from append_event.
    return _reveal_frozen_candidate(
        control, reports, experiment_id=experiment_id,
        candidate_id=candidate_id, operation_id=operation_id,
    )


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0000000001")))


def _existing_resolution(events: list[dict[str, Any]], candidate_id: str) -> dict[str, Any] | None:
    return _event_for_candidate(events, "TRADE_RESOLVED", candidate_id)


def resolve_walk_forward_trade(
    control: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    """Settle one revealed research trade from current ledger equity and immutable net R."""
    store = _store(control)
    events = _events(store, experiment_id)
    existing = _existing_resolution(events, candidate_id)
    if existing is not None:
        payload = deepcopy(existing.get("payload") or {})
        return {
            "contract": SETTLEMENT_CONTRACT,
            "experiment_id": experiment_id,
            "sequence": existing["sequence"],
            "state_hash": existing["resulting_state_hash"],
            "candidate_id": candidate_id,
            "settlement": payload,
            "idempotent_replay": True,
        }

    store, readback, events = _verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    if store._candidate_state(events, candidate_id) != "OUTCOME_REVEALED":
        raise ValueError("trade can only be settled after its outcome is revealed")
    capture = (_candidate_capture(events, candidate_id).get("payload") or {})
    frozen_event = _event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    revealed_event = _event_for_candidate(events, "OUTCOME_REVEALED", candidate_id)
    assert frozen_event is not None and revealed_event is not None
    frozen = frozen_event.get("payload") or {}
    revealed = revealed_event.get("payload") or {}
    outcome = revealed.get("outcome") or {}
    net_r = _decimal(outcome.get("net_r", outcome.get("pair_net_r")), "outcome net_r")

    definition = (readback.get("manifest") or {}).get("definition") or {}
    risk_pct_raw = definition.get("risk_pct")
    if risk_pct_raw in (None, ""):
        raise ValueError("immutable experiment definition has no risk_pct; cannot settle equity deterministically")
    risk_pct = _decimal(risk_pct_raw, "risk_pct")
    equity_raw = ((readback.get("derived_state") or {}).get("ledgers") or {}).get("RESEARCH", {}).get("equity")
    if equity_raw in (None, ""):
        equity_raw = definition.get("initial_equity")
    equity_before = _decimal(equity_raw, "research equity")
    risk_amount = equity_before * risk_pct / Decimal("100")
    net_pnl = risk_amount * net_r
    equity_after = equity_before + net_pnl
    result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
    exit_time = outcome.get("exit_time") or capture.get("entry_time")

    entered_op = _operation(operation_id, "entered")
    current_events = _events(store, experiment_id)
    entered = _event_for_candidate(current_events, "TRADE_ENTERED", candidate_id)
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
                "equity_before": _money(equity_before),
                "risk_pct": float(risk_pct),
                "risk_amount": _money(risk_amount),
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
            "risk_pct": float(risk_pct),
            "risk_amount": _money(risk_amount),
            "net_pnl": _money(net_pnl),
            "equity_before": _money(equity_before),
            "equity_after": _money(equity_after),
            "reference_outcome_sample_id": outcome.get("research_sample_id"),
            "settlement_contract": SETTLEMENT_CONTRACT,
        },
        _operation(operation_id, "resolved"),
        int(current["sequence"]),
        str(current["state_hash"]),
        effective_market_time=str(exit_time),
        source="DETERMINISTIC_LEDGER",
    )
    return {
        "contract": SETTLEMENT_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": resolved["sequence"],
        "state_hash": resolved["state_hash"],
        "candidate_id": candidate_id,
        "settlement": resolved["event"]["payload"],
        "idempotent_replay": False,
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows if row.get("net_r") is not None]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    return {
        "trades": len(values),
        "wins": wins,
        "losses": losses,
        "breakeven": len(values) - wins - losses,
        "win_rate": (wins / len(values)) if values else None,
        "net_r": sum(values) if values else 0.0,
        "average_r": (sum(values) / len(values)) if values else None,
    }


def _resolved_history(events: list[dict[str, Any]], before_sequence: int | None = None) -> list[dict[str, Any]]:
    captures: dict[str, dict[str, Any]] = {}
    frozen: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for event in events:
        if before_sequence is not None and int(event.get("sequence", 0)) >= int(before_sequence):
            break
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id", ""))
        if event.get("event_type") == "CANDIDATE_CONTEXT_CAPTURED" and candidate_id:
            captures[candidate_id] = payload
        elif event.get("event_type") == "DECISION_FROZEN" and candidate_id:
            frozen[candidate_id] = payload
        elif event.get("event_type") == "TRADE_RESOLVED" and candidate_id and str(payload.get("ledger", "RESEARCH")).upper() == "RESEARCH":
            capture = captures.get(candidate_id, {})
            decision = frozen.get(candidate_id, {})
            rows.append({
                "candidate_id": candidate_id,
                "profile": capture.get("strategy_profile_key"),
                "side": decision.get("final_action"),
                "matched_entry_groups": list(capture.get("matched_entry_groups") or []),
                "net_r": payload.get("net_r"),
                "result": payload.get("result"),
            })
    return rows


def _review_completed_for_candidate(events: list[dict[str, Any]], candidate_id: str) -> bool:
    for event in reversed(events):
        if event.get("event_type") != "REVIEW_COMPLETED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("review_type", "")).upper() == "LOSS" and str(payload.get("candidate_id", "")) == candidate_id:
            return True
    return False


def _unreviewed_loss(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") != "TRADE_RESOLVED":
            continue
        payload = event.get("payload") or {}
        if str(payload.get("ledger", "RESEARCH")).upper() != "RESEARCH":
            continue
        if float(payload.get("net_r", 0.0)) >= 0:
            continue
        candidate_id = str(payload.get("candidate_id", ""))
        if candidate_id and not _review_completed_for_candidate(events, candidate_id):
            return event
    return None


def build_loss_review_packet(
    control: Any,
    *,
    experiment_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    store = _store(control)
    events = _events(store, experiment_id)
    resolved = _existing_resolution(events, candidate_id)
    if resolved is None or float((resolved.get("payload") or {}).get("net_r", 0.0)) >= 0:
        raise ValueError("candidate is not a resolved research loss")
    capture = _candidate_capture(events, candidate_id).get("payload") or {}
    frozen = (_event_for_candidate(events, "DECISION_FROZEN", candidate_id) or {}).get("payload") or {}
    revealed = (_event_for_candidate(events, "OUTCOME_REVEALED", candidate_id) or {}).get("payload") or {}
    history = _resolved_history(events, before_sequence=int(resolved["sequence"]))
    profile = capture.get("strategy_profile_key")
    side = frozen.get("final_action")
    entry_groups = list(capture.get("matched_entry_groups") or [])
    group_stats = {}
    for group_id in entry_groups:
        group_stats[str(group_id)] = _stats([
            row for row in history if group_id in row.get("matched_entry_groups", [])
        ])
    return {
        "contract": ORCHESTRATOR_CONTRACT,
        "status": "LOSS_REVIEW_REQUIRED",
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "decision": {
            "final_action": side,
            "confidence_pct": frozen.get("confidence_pct"),
            "reasoning": frozen.get("reasoning"),
        },
        "admission": {
            "strategy_profile_key": profile,
            "source_side": capture.get("source_side"),
            "rule_effective_side": capture.get("rule_effective_side"),
            "matched_entry_groups": entry_groups,
            "matched_veto_groups": list(capture.get("matched_veto_groups") or []),
            "matched_flip_groups": list(capture.get("matched_flip_groups") or []),
        },
        "outcome": deepcopy(revealed.get("outcome")),
        "settlement": deepcopy(resolved.get("payload")),
        "causal_history": {
            "all_prior_research_trades": _stats(history),
            "same_profile": _stats([row for row in history if row.get("profile") == profile]),
            "same_frozen_side": _stats([row for row in history if row.get("side") == side]),
            "entry_group_stats": group_stats,
        },
        "entry_context": deepcopy(capture.get("context")),
        "review_rule": "Do not force a veto. Learn/refine only if a repeatable failure mechanism is supported by evidence available by this loss resolution.",
    }


def _initial_periodic_review_anchor(
    reports: Any,
    definition: dict[str, Any],
    events: list[dict[str, Any]],
) -> pd.Timestamp | None:
    if any(event.get("event_type") == "MIGRATION_RECORDED" for event in events):
        return None

    policy = definition.get("periodic_review_policy") or {}
    if not isinstance(policy, dict):
        return None
    anchor_mode = str(policy.get("initial_anchor", "")).strip().upper()
    if anchor_mode == "WALK_FORWARD_START":
        protocol = definition.get("research_protocol") or {}
        raw = protocol.get("walk_forward_start") if isinstance(protocol, dict) else None
    elif anchor_mode == "REFERENCE_PERIOD_START":
        provenance = definition.get("reference_provenance") or {}
        raw = provenance.get("period_start") if isinstance(provenance, dict) else None
        if not raw:
            reference_run = str(definition.get("reference_run", "")).strip()
            if not reference_run:
                return None
            manifest = reports.get_run_manifest(reference_run)
            request = manifest.get("request") or {}
            raw = request.get("start")
    else:
        return None
    if not raw:
        return None
    return _utc_timestamp(raw, "initial periodic review anchor")


def _periodic_review_anchor(
    events: list[dict[str, Any]],
    initial_anchor: pd.Timestamp | None,
) -> tuple[dict[str, Any] | None, pd.Timestamp, str] | None:
    periodic = []
    for event in events:
        if event.get("event_type") != "REVIEW_COMPLETED":
            continue
        payload = event.get("payload") or {}
        kind = str(payload.get("review_type", "")).upper()
        if kind in {"PERIODIC", "QUARTERLY"} or (
            not kind and not payload.get("candidate_id")
        ):
            raw = event.get("effective_market_time")
            if raw:
                periodic.append(
                    (event, _utc_timestamp(raw, "review effective_market_time"))
                )

    if periodic:
        last_event, last_time = periodic[-1]
        return last_event, last_time, "REVIEW_COMPLETED"
    if initial_anchor is None:
        return None
    return None, initial_anchor, "REFERENCE_PERIOD_START"


def _next_periodic_review_time(
    events: list[dict[str, Any]],
    months: int,
    *,
    initial_anchor: pd.Timestamp | None = None,
) -> pd.Timestamp | None:
    anchor = _periodic_review_anchor(events, initial_anchor)
    if anchor is None:
        return None
    _, anchor_time, _ = anchor
    return anchor_time + pd.DateOffset(months=int(months))


def _periodic_review_due(
    events: list[dict[str, Any]],
    months: int,
    *,
    initial_anchor: pd.Timestamp | None = None,
    cap_history_at_due: bool = False,
) -> dict[str, Any] | None:
    anchor = _periodic_review_anchor(events, initial_anchor)
    if anchor is None:
        return None
    last_event, last_time, anchor_source = anchor

    cursor = _max_event_time(events)
    if cursor is None:
        return None
    due = last_time + pd.DateOffset(months=int(months))
    if cursor < due:
        return None

    history_end = due if cap_history_at_due else cursor
    history = []
    for event in events:
        if event.get("event_type") != "TRADE_RESOLVED":
            continue
        raw = event.get("effective_market_time")
        if not raw:
            continue
        when = _utc_timestamp(raw, "trade resolution time")
        if last_time < when <= history_end:
            history.append(event.get("payload") or {})

    return {
        "status": "PERIODIC_REVIEW_REQUIRED",
        "review_interval_months": int(months),
        "previous_review_sequence": last_event["sequence"] if last_event is not None else None,
        "previous_review_time": last_time.isoformat() if last_event is not None else None,
        "review_anchor_source": anchor_source,
        "review_anchor_time": last_time.isoformat(),
        "review_due_time": due.isoformat(),
        "review_window_end": history_end.isoformat(),
        "current_market_cursor": cursor.isoformat(),
        "period_trade_stats": _stats(history),
    }


def _weekly_review_due(
    events: list[dict[str, Any]],
    *,
    initial_anchor: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    anchor = _periodic_review_anchor(events, initial_anchor)
    if anchor is None:
        return None
    last_event, last_time, anchor_source = anchor
    cursor = _max_event_time(events)
    if cursor is None:
        return None
    due = last_time + pd.DateOffset(weeks=1)
    if cursor < due:
        return None

    history_end = due
    history = []
    for event in events:
        if event.get("event_type") != "TRADE_RESOLVED":
            continue
        raw = event.get("effective_market_time")
        if not raw:
            continue
        when = _utc_timestamp(raw, "trade resolution time")
        if last_time < when <= history_end:
            history.append(event.get("payload") or {})

    return {
        "status": "PERIODIC_REVIEW_REQUIRED",
        "review_interval_weeks": 1,
        "review_cadence": "WEEKLY",
        "previous_review_sequence": last_event["sequence"] if last_event is not None else None,
        "previous_review_time": last_time.isoformat() if last_event is not None else None,
        "review_anchor_source": anchor_source,
        "review_anchor_time": last_time.isoformat(),
        "review_due_time": due.isoformat(),
        "review_window_end": history_end.isoformat(),
        "current_market_cursor": cursor.isoformat(),
        "period_trade_stats": _stats(history),
    }


def _review_due(
    definition: dict[str, Any],
    events: list[dict[str, Any]],
    requested_months: int,
    *,
    initial_anchor: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    if _weekly_batch_enabled(definition):
        return _weekly_review_due(events, initial_anchor=initial_anchor)
    return _periodic_review_due(
        events,
        _effective_review_interval(definition, requested_months),
        initial_anchor=initial_anchor,
        cap_history_at_due=_batch_oos_enabled(definition),
    )


def _next_review_time(
    definition: dict[str, Any],
    events: list[dict[str, Any]],
    requested_months: int,
    *,
    initial_anchor: pd.Timestamp | None = None,
) -> pd.Timestamp | None:
    if _weekly_batch_enabled(definition):
        anchor = _periodic_review_anchor(events, initial_anchor)
        if anchor is None:
            return None
        return anchor[1] + pd.DateOffset(weeks=1)
    return _next_periodic_review_time(
        events,
        _effective_review_interval(definition, requested_months),
        initial_anchor=initial_anchor,
    )


def _teacher_review_packet(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    teacher_boundary: dict[str, Any],
) -> dict[str, Any]:
    store, readback, events = _verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    del store, events
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", ""))
    snapshot = materialize_walk_forward_strategy(
        control, reports, experiment_id=experiment_id,
        expected_sequence=expected_sequence, expected_state_hash=expected_state_hash,
        include_config=True,
    )
    packet: dict[str, Any] = {
        "contract": ORCHESTRATOR_CONTRACT,
        "status": "TEACHER_REVIEW_REQUIRED",
        "experiment_id": experiment_id,
        "teacher": {
            **deepcopy(teacher_boundary),
            "result": str(teacher_boundary.get("result", "WIN")).upper(),
        },
        "active_rule_versions": snapshot.get("active_rule_versions"),
        "rule_counts": snapshot.get("rule_counts"),
        "review_rule": "Teacher evidence may teach/refine ENTRY only; it never changes walk-forward equity.",
    }
    entry_raw = teacher_boundary.get("entry_time")
    side = str(teacher_boundary.get("side", "")).upper()
    profile = str(teacher_boundary.get("strategy_profile_key", "")).lower()
    if not entry_raw or side not in {"LONG", "SHORT"} or not profile:
        return packet
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    if _sampling_mode(manifest) != "WALK_FORWARD":
        return packet
    samples_path = _artifact(manifest, run_dir, "research_sampling_trades")
    context_path = _artifact(manifest, run_dir, "feature_context")
    entry_time = _utc_timestamp(entry_raw, "teacher entry_time")
    signal_index = teacher_boundary.get("research_signal_index")
    candidate_id = str(
        teacher_boundary.get("walk_forward_candidate_id") or ""
    ).strip()

    chosen = None
    if signal_index not in (None, ""):
        # Canonical paired WALK_FORWARD teachers already carry the exact source
        # identity. Hydrate that one row directly instead of scanning a time
        # window of the wide research/context artifacts.
        series = _candidate_detail_row(
            samples_path,
            context_path,
            int(signal_index),
            side,
        )
        row, context = _row_maps(series)
        actual_entry = _utc_timestamp(
            row.get("entry_time"), "teacher candidate entry_time"
        )
        actual_profile = str(row.get("strategy_profile_key", "")).lower()
        actual_candidate = str(row.get("walk_forward_candidate_id") or "").strip()
        if actual_entry != entry_time:
            raise ValueError(
                "exact teacher source row entry_time does not match teacher boundary"
            )
        if actual_profile != profile:
            raise ValueError(
                "exact teacher source row profile does not match teacher boundary"
            )
        if candidate_id and actual_candidate != candidate_id:
            raise ValueError(
                "exact teacher source row candidate id does not match teacher boundary"
            )
        chosen = (row, context)
    else:
        # Compatibility fallback for older reference artifacts that did not
        # persist research_signal_index in the teacher boundary.
        frame = _candidate_rows(samples_path, context_path, entry_time, 64)
        for _, series in frame.iterrows():
            row, context = _row_maps(series)
            if _utc_timestamp(
                row.get("entry_time"), "teacher candidate entry_time"
            ) != entry_time:
                break
            if (
                str(row.get("side", "")).upper() == side
                and str(row.get("strategy_profile_key", "")).lower() == profile
            ):
                chosen = (row, context)
                break
    if chosen is None:
        return packet
    row, context = chosen
    groups = (snapshot.get("groups_by_profile") or {}).get(profile)
    if groups is not None:
        packet["current_rule_coverage"] = _rule_decision(
            row, profile, side, groups, snapshot["materialized_config"]
        )
    packet["entry_context"] = _safe_context(
        row,
        context,
        direction=side,
        profile=profile,
        config=snapshot["materialized_config"],
    )
    trade_context = packet["entry_context"].get("trade_entry_context")
    if isinstance(trade_context, dict):
        # Teacher learning must not see the eventual episode length. Keep only
        # causal progress through the current observation and use an explicit
        # forward-only name in the ChatGPT-facing packet.
        entry_number = trade_context.pop("research_episode_entry_number", None)
        trade_context.pop("research_episode_viable_entries", None)
        if entry_number is not None:
            trade_context["research_episode_entries_seen_so_far"] = entry_number
    return packet


def _teacher_phase_metadata(
    packet: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    decision = teacher_compression_decision(packet, events)
    return {
        "teacher_phase_audit": deepcopy(decision.get("audit") or {}),
        "teacher_review_reason": decision.get("reason"),
        "compared_to_teacher_id": decision.get("compared_to_teacher_id"),
        "confirmation_of_teacher_id": decision.get("confirmation_of_teacher_id"),
        "confirmation_rule_ids": list(decision.get("confirmation_rule_ids") or []),
        "teacher_compression_action": decision.get("action"),
        "teacher_compression_contract": TEACHER_COMPRESSION_CONTRACT,
    }


def _append_auto_compressed_teacher(
    store: CausalExperimentStore,
    *,
    experiment_id: str,
    packet: dict[str, Any],
    decision: dict[str, Any],
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    teacher = deepcopy(packet.get("teacher") or {})
    resolution_raw = teacher.get("resolution_time")
    if resolution_raw in (None, ""):
        raise ValueError("teacher phase compression requires a causal resolution_time")
    resolution = _utc_timestamp(resolution_raw, "teacher compression resolution_time")
    audit = deepcopy(decision.get("audit") or {})
    teacher_id = str(
        teacher.get("pair_id")
        or teacher.get("walk_forward_candidate_id")
        or ""
    ).strip()
    reason = str(decision.get("reason") or "CORRELATED_PHASE_DUPLICATE").upper()
    payload = {
        **teacher,
        "review_decision": AUTO_COMPRESSED_STATUS,
        "teacher_review_status": AUTO_COMPRESSED_STATUS,
        "compression_reason": reason,
        "compression_contract": TEACHER_COMPRESSION_CONTRACT,
        "compared_to_teacher_id": decision.get("compared_to_teacher_id"),
        "teacher_phase_audit": audit,
        "phase_fingerprint": audit.get("phase_fingerprint"),
        "actionability_fingerprint": audit.get("actionability_fingerprint"),
        "structural_phase_fingerprint": audit.get("structural_fingerprint"),
        "active_rule_matches": list(audit.get("active_rule_matches") or []),
        "episode_review_count": decision.get("episode_review_count"),
        "episode_review_budget": decision.get("episode_review_budget"),
        "validated_rule_event_count": 0,
        "notes": (
            "Deterministically compressed because no new causal actionability "
            "required ChatGPT review; the immutable raw observation remains "
            "available for later analytics."
        ),
    }
    appended = store.append_event(
        experiment_id,
        "TEACHER_RESOLVED",
        payload,
        operation_id,
        int(expected_sequence),
        str(expected_state_hash),
        effective_market_time=resolution.isoformat(),
        source="DETERMINISTIC_TEACHER_COMPRESSION",
    )
    return {
        "sequence": int(appended["sequence"]),
        "state_hash": str(appended["state_hash"]),
        "teacher_id": teacher_id or None,
        "compression_reason": reason,
        "teacher_phase_audit": audit,
    }


def _batch_boundary_label(batch_mode: str) -> str:
    return "week-end" if batch_mode == WEEKLY_BATCH_OOS_MODE else "month-end"


def _batch_deferred_status(batch_mode: str) -> str:
    if batch_mode == WEEKLY_BATCH_OOS_MODE:
        return WEEKLY_BATCH_DEFERRED
    if batch_mode == MONTHLY_BATCH_OOS_MODE:
        return MONTHLY_BATCH_DEFERRED
    raise ValueError(f"unsupported batch OOS mode: {batch_mode}")


def _append_batch_teacher(
    store: CausalExperimentStore,
    *,
    experiment_id: str,
    teacher_boundary: dict[str, Any],
    teacher_packet: dict[str, Any],
    batch_mode: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    mode = str(batch_mode).strip().upper()
    deferred_status = _batch_deferred_status(mode)
    boundary_label = _batch_boundary_label(mode)
    resolution_raw = teacher_boundary.get("resolution_time")
    if resolution_raw in (None, ""):
        raise ValueError(f"{mode} teacher evidence requires resolution_time")
    resolution = _utc_timestamp(
        resolution_raw, f"{mode} teacher resolution_time"
    )
    payload = {
        **deepcopy(teacher_boundary),
        "review_decision": deferred_status,
        "teacher_review_status": deferred_status,
        "validated_rule_event_count": 0,
        "batch_entry_context": deepcopy(teacher_packet.get("entry_context")),
        "batch_current_rule_coverage": deepcopy(
            teacher_packet.get("current_rule_coverage")
        ),
        "batch_active_rule_versions": deepcopy(
            teacher_packet.get("active_rule_versions")
        ),
        "batch_oos_mode": mode,
        "notes": (
            "Teacher evidence and entry-time context were recorded without a rule "
            f"mutation because {mode} freezes the strategy until the "
            f"{boundary_label} review."
        ),
    }
    appended = store.append_event(
        experiment_id,
        "TEACHER_RESOLVED",
        payload,
        operation_id,
        int(expected_sequence),
        str(expected_state_hash),
        effective_market_time=resolution.isoformat(),
        source=f"DETERMINISTIC_{mode}",
    )
    return {
        "sequence": int(appended["sequence"]),
        "state_hash": str(appended["state_hash"]),
    }


def _freeze_batch_candidate(
    store: CausalExperimentStore,
    events: list[dict[str, Any]],
    *,
    experiment_id: str,
    candidate_id: str,
    batch_mode: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> dict[str, Any]:
    mode = str(batch_mode).strip().upper()
    if mode not in BATCH_OOS_MODES:
        raise ValueError(f"unsupported batch OOS mode: {mode}")
    candidate = _candidate_capture(events, candidate_id).get("payload") or {}
    strategy_action = str(
        candidate.get("strategy_action")
        or candidate.get("rule_effective_side")
        or candidate.get("source_side")
        or ""
    ).strip().upper()
    if strategy_action not in {"LONG", "SHORT"}:
        raise ValueError(
            f"{mode} candidate has no valid executable strategy action"
        )
    frozen = store.append_event(
        experiment_id,
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate.get("candidate_token"),
            "final_action": strategy_action,
            "strategy_action": strategy_action,
            "chatgpt_view": None,
            "chatgpt_confidence_pct": None,
            "chatgpt_reasoning": None,
            "state_hash_at_decision": str(expected_state_hash),
            "feature_hash": candidate.get("feature_hash"),
            "strategy_snapshot_sha256": candidate.get(
                "strategy_snapshot_sha256"
            ),
            "decision_mode": mode,
        },
        operation_id,
        int(expected_sequence),
        str(expected_state_hash),
        effective_market_time=str(
            candidate.get("decision_available_at") or candidate.get("entry_time")
        ),
        source=f"DETERMINISTIC_{mode}",
    )
    return {
        "sequence": int(frozen["sequence"]),
        "state_hash": str(frozen["state_hash"]),
    }


def _judgment_candidate(events: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    capture = _candidate_capture(events, candidate_id).get("payload") or {}
    return {
        "contract": ORCHESTRATOR_CONTRACT,
        "status": "CANDIDATE_DECISION_REQUIRED",
        "candidate": deepcopy(capture),
        "candidate_id": candidate_id,
        "candidate_token": capture.get("candidate_token"),
        "outcome_exposed": False,
    }


def advance_walk_forward(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    review_interval_months: int = 3,
    max_scan_rows: int = 250000,
    max_transitions: int = 20,
) -> dict[str, Any]:
    """Advance deterministic work until the next genuine judgment point."""
    if isinstance(max_transitions, bool) or not 1 <= int(max_transitions) <= 100:
        raise ValueError("max_transitions must be between 1 and 100")
    if isinstance(review_interval_months, bool) or not 1 <= int(review_interval_months) <= 24:
        raise ValueError("review_interval_months must be between 1 and 24")
    sequence = int(expected_sequence)
    state_hash = str(expected_state_hash)

    for step in range(int(max_transitions)):
        store, readback, events = _verified(control, experiment_id, sequence, state_hash)
        definition = (readback.get("manifest") or {}).get("definition") or {}
        batch_mode = _batch_oos_mode(definition)
        batch_oos = batch_mode is not None
        unresolved = _open_candidate(events)
        if unresolved is not None:
            candidate_id, state = unresolved
            if state == "ENTRY_CONTEXT_CAPTURED":
                if batch_oos:
                    frozen = _freeze_batch_candidate(
                        store,
                        events,
                        experiment_id=experiment_id,
                        candidate_id=candidate_id,
                        batch_mode=str(batch_mode),
                        operation_id=_operation(
                            operation_id, f"batch-freeze-{step}-{candidate_id}"
                        ),
                        expected_sequence=sequence,
                        expected_state_hash=state_hash,
                    )
                    sequence = int(frozen["sequence"])
                    state_hash = str(frozen["state_hash"])
                    continue
                result = _judgment_candidate(events, candidate_id)
                result.update(sequence=sequence, state_hash=state_hash)
                return result
            if state == "DECISION_FROZEN":
                revealed = _reveal_frozen_candidate(
                    control, reports, experiment_id=experiment_id,
                    candidate_id=candidate_id,
                    operation_id=_operation(operation_id, f"resume-{step}"),
                )
                sequence, state_hash = int(revealed["sequence"]), str(revealed["state_hash"])
                continue
            if state == "OUTCOME_REVEALED":
                settled = resolve_walk_forward_trade(
                    control, experiment_id=experiment_id, candidate_id=candidate_id,
                    operation_id=_operation(operation_id, f"settle-{step}"),
                    expected_sequence=sequence, expected_state_hash=state_hash,
                )
                sequence, state_hash = int(settled["sequence"]), str(settled["state_hash"])
                if (
                    str((settled.get("settlement") or {}).get("result")) == "LOSS"
                    and not batch_oos
                ):
                    packet = build_loss_review_packet(
                        control, experiment_id=experiment_id, candidate_id=candidate_id
                    )
                    packet.update(sequence=sequence, state_hash=state_hash)
                    return packet
                continue

        if not batch_oos:
            loss = _unreviewed_loss(events)
            if loss is not None:
                candidate_id = str((loss.get("payload") or {}).get("candidate_id"))
                packet = build_loss_review_packet(
                    control, experiment_id=experiment_id, candidate_id=candidate_id
                )
                packet.update(sequence=sequence, state_hash=state_hash)
                return packet

        initial_review_anchor = _initial_periodic_review_anchor(
            reports, definition, events
        )
        periodic = _review_due(
            definition,
            events,
            int(review_interval_months),
            initial_anchor=initial_review_anchor,
        )
        if periodic is not None:
            if periodic.get("previous_review_sequence") is None:
                policy = definition.get("periodic_review_policy") or {}
                periodic["review_anchor_source"] = str(
                    policy.get("initial_anchor", periodic.get("review_anchor_source"))
                ).strip().upper()
            periodic.update(
                contract=ORCHESTRATOR_CONTRACT,
                experiment_id=experiment_id,
                sequence=sequence,
                state_hash=state_hash,
                rule_update_policy=_rule_update_policy(definition),
            )
            if batch_oos:
                batch_packet = {
                    "mode": str(batch_mode),
                    "cadence": (
                        "WEEKLY"
                        if batch_mode == WEEKLY_BATCH_OOS_MODE
                        else "MONTHLY"
                    ),
                    "rules_frozen_during_period": True,
                    "mid_period_teacher_mutation_allowed": False,
                    "mid_period_loss_mutation_allowed": False,
                    "per_trade_chatgpt_decision_required": False,
                }
                periodic["batch_oos"] = batch_packet
                if batch_mode == MONTHLY_BATCH_OOS_MODE:
                    periodic["monthly_batch_oos"] = deepcopy(batch_packet)
                else:
                    periodic["weekly_batch_oos"] = deepcopy(batch_packet)
            return periodic

        next_review_time = _next_review_time(
            definition,
            events,
            int(review_interval_months),
            initial_anchor=initial_review_anchor,
        )
        scan = get_next_walk_forward_candidate(
            control, reports,
            experiment_id=experiment_id,
            operation_id=_operation(operation_id, f"scan-{step}-{sequence}"),
            expected_sequence=sequence,
            expected_state_hash=state_hash,
            max_scan_rows=max_scan_rows,
            stop_before_time=(
                next_review_time.isoformat()
                if next_review_time is not None
                else None
            ),
        )
        status = scan.get("status")
        if status == "TIME_BOUNDARY_DUE_FIRST":
            boundary_time = _utc_timestamp(
                scan.get("boundary_time"), "periodic review scan boundary"
            )
            checkpoint = store.append_event(
                experiment_id,
                "CHECKPOINT_CREATED",
                {
                    "checkpoint_type": "PERIODIC_REVIEW_BOUNDARY_V1",
                    "review_due_time": boundary_time.isoformat(),
                },
                _operation(operation_id, f"periodic-boundary-{step}"),
                sequence,
                state_hash,
                effective_market_time=boundary_time.isoformat(),
                source="DETERMINISTIC_ORCHESTRATOR",
            )
            sequence = int(checkpoint["sequence"])
            state_hash = str(checkpoint["state_hash"])
            continue
        if status == "CANDIDATE_CAPTURED":
            if batch_oos:
                sequence = int(scan["sequence"])
                state_hash = str(scan["state_hash"])
                continue
            return {
                "contract": ORCHESTRATOR_CONTRACT,
                "status": "CANDIDATE_DECISION_REQUIRED",
                "experiment_id": experiment_id,
                "sequence": scan["sequence"],
                "state_hash": scan["state_hash"],
                "candidate": scan["candidate"],
                "candidate_id": scan["candidate"]["candidate_id"],
                "candidate_token": scan["candidate"].get("candidate_token"),
                "scan": scan.get("scan"),
                "outcome_exposed": False,
            }
        if status == "TEACHER_DUE_FIRST":
            if batch_oos:
                teacher_packet = _teacher_review_packet(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    expected_sequence=sequence,
                    expected_state_hash=state_hash,
                    teacher_boundary=scan["teacher_boundary"],
                )
                deferred = _append_batch_teacher(
                    store,
                    experiment_id=experiment_id,
                    teacher_boundary=scan["teacher_boundary"],
                    teacher_packet=teacher_packet,
                    batch_mode=str(batch_mode),
                    operation_id=_operation(
                        operation_id, f"batch-teacher-{step}-{sequence}"
                    ),
                    expected_sequence=sequence,
                    expected_state_hash=state_hash,
                )
                sequence = int(deferred["sequence"])
                state_hash = str(deferred["state_hash"])
                continue
            packet = _teacher_review_packet(
                control, reports,
                experiment_id=experiment_id,
                expected_sequence=sequence,
                expected_state_hash=state_hash,
                teacher_boundary=scan["teacher_boundary"],
            )
            phase_decision = teacher_compression_decision(packet, events)
            if phase_decision.get("action") == "AUTO_COMPRESS":
                compressed = _append_auto_compressed_teacher(
                    store,
                    experiment_id=experiment_id,
                    packet=packet,
                    decision=phase_decision,
                    operation_id=_operation(
                        operation_id, f"teacher-compress-{step}-{sequence}"
                    ),
                    expected_sequence=sequence,
                    expected_state_hash=state_hash,
                )
                sequence = int(compressed["sequence"])
                state_hash = str(compressed["state_hash"])
                continue
            packet.update(
                sequence=sequence,
                state_hash=state_hash,
                scan=scan.get("scan"),
                **_teacher_phase_metadata(packet, events),
            )
            return packet
        if status == "NO_ELIGIBLE_CANDIDATE_IN_SCAN":
            return {
                "contract": ORCHESTRATOR_CONTRACT,
                "status": "NO_MORE_ACTION_IN_SCAN",
                "experiment_id": experiment_id,
                "sequence": sequence,
                "state_hash": state_hash,
                "scan": scan.get("scan"),
                "outcome_exposed": False,
            }
        raise ValueError(f"unexpected candidate scanner status: {status}")

    return {
        "contract": ORCHESTRATOR_CONTRACT,
        "status": "TRANSITION_LIMIT_REACHED",
        "experiment_id": experiment_id,
        "sequence": sequence,
        "state_hash": state_hash,
        "max_transitions": int(max_transitions),
    }


def submit_walk_forward_decision(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    candidate_token: str,
    final_action: str,
    confidence_pct: int,
    reasoning: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    auto_advance: bool = True,
    review_interval_months: int = 3,
) -> dict[str, Any]:
    """Freeze decision, reveal exact outcome, settle equity, then continue after wins."""
    revealed = freeze_and_reveal_walk_forward_candidate(
        control, reports,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        candidate_token=candidate_token,
        final_action=final_action,
        confidence_pct=confidence_pct,
        reasoning=reasoning,
        operation_id=operation_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
    )
    settled = resolve_walk_forward_trade(
        control,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        operation_id=_operation(operation_id, "settlement"),
        expected_sequence=int(revealed["sequence"]),
        expected_state_hash=str(revealed["state_hash"]),
    )
    settlement = settled.get("settlement") or {}
    readback = _store(control).read(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    if (
        str(settlement.get("result")) == "LOSS"
        and not _monthly_batch_enabled(definition)
    ):
        packet = build_loss_review_packet(
            control, experiment_id=experiment_id, candidate_id=candidate_id
        )
        packet.update(sequence=settled["sequence"], state_hash=settled["state_hash"])
        return packet
    if not auto_advance:
        return {
            "contract": ORCHESTRATOR_CONTRACT,
            "status": "TRADE_SETTLED",
            "experiment_id": experiment_id,
            "sequence": settled["sequence"],
            "state_hash": settled["state_hash"],
            "settlement": settlement,
        }
    return advance_walk_forward(
        control, reports,
        experiment_id=experiment_id,
        operation_id=_operation(operation_id, "advance"),
        expected_sequence=int(settled["sequence"]),
        expected_state_hash=str(settled["state_hash"]),
        review_interval_months=review_interval_months,
    )


def _append_rule_events(
    store: CausalExperimentStore,
    experiment_id: str,
    head: dict[str, Any],
    operation_id: str,
    rule_events: list[dict[str, Any]],
    *,
    evidence_source: str,
    effective_from: str,
    default_reason: str,
    allowed_types: set[str],
) -> dict[str, Any]:
    current = head
    for index, item in enumerate(rule_events):
        if not isinstance(item, dict):
            raise ValueError("rule_events must contain objects")
        event_type = str(item.get("event_type", "")).upper()
        if event_type not in allowed_types or event_type not in RULE_EVENT_TYPES:
            raise ValueError(f"unsupported rule event for this review: {event_type}")
        payload = deepcopy(item.get("payload") or {})
        payload.setdefault("evidence_source", evidence_source)
        payload.setdefault("effective_from", effective_from)
        payload.setdefault("reason", default_reason or "walk-forward review")
        current = store.append_event(
            experiment_id,
            event_type,
            payload,
            _operation(operation_id, f"rule-{index + 1}"),
            int(current["sequence"]),
            str(current["state_hash"]),
            effective_market_time=effective_from,
            source="CHATGPT_RESEARCH",
        )
    return current


def record_walk_forward_review(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    review_type: str,
    decision: str,
    notes: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    candidate_id: str | None = None,
    rule_events: list[dict[str, Any]] | None = None,
    loss_diagnosis: str | None = None,
    failure_mechanism: str | None = None,
    periodic_rule_action: str | None = None,
    periodic_rationale: str | None = None,
    auto_advance: bool = True,
    review_interval_months: int = 3,
) -> dict[str, Any]:
    """Record a loss/periodic judgment and optional causal rule mutations, then continue."""
    store, readback, events = _verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    kind = str(review_type).strip().upper()
    if kind not in {"LOSS", "PERIODIC", "QUARTERLY"}:
        raise ValueError("review_type must be LOSS or PERIODIC/QUARTERLY")
    text = str(notes).strip()
    if not str(decision).strip():
        raise ValueError("decision cannot be empty")
    definition = (readback.get("manifest") or {}).get("definition") or {}
    batch_due = None
    if _batch_oos_enabled(definition) and kind in {"PERIODIC", "QUARTERLY"}:
        initial_anchor = _initial_periodic_review_anchor(
            reports, definition, events
        )
        batch_due = _review_due(
            definition,
            events,
            int(review_interval_months),
            initial_anchor=initial_anchor,
        )
        if batch_due is None:
            raise ValueError(
                "batch OOS periodic review cannot be recorded before its scheduled boundary"
            )
        effective = _utc_timestamp(
            batch_due["review_due_time"], "batch OOS scheduled review boundary"
        )
    else:
        effective = _max_event_time(events)
        if effective is None:
            raise ValueError("review requires an established market-time cursor")
    subject = str(candidate_id or "").strip()
    if kind == "LOSS":
        pending = _unreviewed_loss(events)
        if pending is None:
            raise ValueError("there is no unresolved loss review")
        pending_id = str((pending.get("payload") or {}).get("candidate_id", ""))
        if not subject:
            subject = pending_id
        if subject != pending_id:
            raise ValueError(f"loss review must resolve pending candidate {pending_id}")
    methodology = (
        validate_loss_methodology(
            list(rule_events or []),
            loss_diagnosis=loss_diagnosis,
            failure_mechanism=failure_mechanism,
        )
        if kind == "LOSS"
        else validate_periodic_methodology(
            list(rule_events or []),
            periodic_rule_action=periodic_rule_action,
            periodic_rationale=periodic_rationale,
        )
    )
    payload = {
        "review_type": "PERIODIC" if kind == "QUARTERLY" else kind,
        "candidate_id": subject or None,
        "decision": str(decision).strip().upper(),
        "notes": text,
        "reviewed_state_hash": str(expected_state_hash),
        **methodology,
    }
    if batch_due is not None:
        payload["scheduled_review_due_time"] = str(batch_due["review_due_time"])
        payload["review_observed_market_cursor"] = str(
            batch_due.get("current_market_cursor") or batch_due["review_due_time"]
        )
    reviewed = store.append_event(
        experiment_id,
        "REVIEW_COMPLETED",
        payload,
        _operation(operation_id, "review"),
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=effective.isoformat(),
        source="CHATGPT_RESEARCH",
    )
    allowed = (
        {"VETO_LEARNED", "ENTRY_REFINED", "FLIP_LEARNED"}
        if kind == "LOSS"
        else set(RULE_EVENT_TYPES)
    )
    current = _append_rule_events(
        store,
        experiment_id,
        reviewed,
        operation_id,
        list(rule_events or []),
        evidence_source="PROSPECTIVE_WF",
        effective_from=effective.isoformat(),
        default_reason=text,
        allowed_types=allowed,
    )
    if not auto_advance:
        return {
            "contract": ORCHESTRATOR_CONTRACT,
            "status": "REVIEW_RECORDED",
            "experiment_id": experiment_id,
            "sequence": current["sequence"],
            "state_hash": current["state_hash"],
        }
    return advance_walk_forward(
        control, reports,
        experiment_id=experiment_id,
        operation_id=_operation(operation_id, "advance"),
        expected_sequence=int(current["sequence"]),
        expected_state_hash=str(current["state_hash"]),
        review_interval_months=review_interval_months,
    )


def record_walk_forward_teacher_review(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    teacher_pair_id: str,
    decision: str,
    notes: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    rule_events: list[dict[str, Any]] | None = None,
    setup_thesis: str | None = None,
    entry_family: str | None = None,
    auto_advance: bool = True,
    review_interval_months: int = 3,
) -> dict[str, Any]:
    """Record the next teacher winner review and optional ENTRY learning, then continue."""
    store, readback, events = _verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", ""))
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    teacher = _next_teacher(manifest, run_dir, events)
    if teacher is None:
        raise ValueError("there is no unresolved teacher winner")
    boundary, resolution_time = teacher
    if str(boundary.get("pair_id")) != str(teacher_pair_id):
        raise ValueError(
            f"next teacher is pair {boundary.get('pair_id')}, not {teacher_pair_id}"
        )
    teacher_result = str(boundary.get("result", "WIN")).upper()
    methodology = validate_teacher_methodology(
        list(rule_events or []),
        teacher_result=teacher_result,
        setup_thesis=setup_thesis,
        entry_family=entry_family,
    )
    reviewed = store.append_event(
        experiment_id,
        "TEACHER_RESOLVED",
        {
            **deepcopy(boundary),
            "result": teacher_result,
            "review_decision": str(decision).strip().upper(),
            "notes": str(notes).strip(),
            **methodology,
        },
        _operation(operation_id, "teacher"),
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=resolution_time.isoformat(),
        source="CHATGPT_RESEARCH",
    )
    current = _append_rule_events(
        store,
        experiment_id,
        reviewed,
        operation_id,
        list(rule_events or []),
        evidence_source="TEACHER",
        effective_from=resolution_time.isoformat(),
        default_reason=str(notes).strip(),
        allowed_types={"ENTRY_LEARNED", "ENTRY_REFINED"},
    )
    if not auto_advance:
        return {
            "contract": ORCHESTRATOR_CONTRACT,
            "status": "TEACHER_REVIEW_RECORDED",
            "experiment_id": experiment_id,
            "sequence": current["sequence"],
            "state_hash": current["state_hash"],
        }
    return advance_walk_forward(
        control, reports,
        experiment_id=experiment_id,
        operation_id=_operation(operation_id, "advance"),
        expected_sequence=int(current["sequence"]),
        expected_state_hash=str(current["state_hash"]),
        review_interval_months=review_interval_months,
    )
