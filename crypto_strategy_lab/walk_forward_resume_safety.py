"""Recovery helpers for partially completed causal walk-forward decisions.

A ChatGPT decision is intentionally fsynced before the outcome-bearing EVE artifact
is opened.  If reveal then fails, the candidate is left in DECISION_FROZEN and
must be resumable without rewriting or replacing the frozen research judgment.

This module also normalizes DuckDB/Pandas/Python scalar values returned by the
outcome lookup into strict JSON values before OUTCOME_REVEALED is appended.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
import math
from typing import Any

import pandas as pd

from crypto_strategy_lab import walk_forward_orchestrator as orchestrator


_impl = orchestrator._impl
_ORIGINAL_FREEZE_AND_REVEAL = orchestrator.freeze_and_reveal_walk_forward_view
_ORIGINAL_OUTCOME_ROW = _impl._outcome_row_after_decision
_INSTALLED = False


def json_safe_value(value: Any) -> Any:
    """Convert runtime/DB scalar types into strict JSON-compatible values."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return _impl._utc_timestamp(value, "timestamp").isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe_value(value.item())
        except (TypeError, ValueError):
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _json_safe_outcome_row(*args, **kwargs) -> dict[str, Any]:
    """Run the immutable lookup, then guarantee append/response serialization."""
    outcome = _ORIGINAL_OUTCOME_ROW(*args, **kwargs)
    safe = json_safe_value(outcome)
    if not isinstance(safe, dict):
        raise ValueError("walk-forward outcome must be an object")
    try:
        json.dumps(safe, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("walk-forward outcome is not JSON-serializable") from exc
    return safe


def _view_input(chatgpt_view: str | None, final_action: str | None) -> str:
    if chatgpt_view is not None and final_action is not None:
        if str(chatgpt_view).strip().upper() != str(final_action).strip().upper():
            raise ValueError("chatgpt_view and legacy final_action disagree")
    raw = chatgpt_view if chatgpt_view is not None else final_action
    if raw is None:
        raise ValueError("chatgpt_view must be LONG or SHORT")
    return str(raw)


def _validate_matching_frozen_view(
    frozen: dict[str, Any],
    *,
    candidate_token: str,
    strategy_action: str,
    chatgpt_view: str,
    confidence_pct: int,
    reasoning: str,
) -> bool:
    """Validate a retry against the already durable frozen event.

    Returns True for the new strategy_action/chatgpt_view schema and False for a
    legacy frozen event whose final_action was the executable decision itself.
    """
    stored_token = str(frozen.get("candidate_token") or "")
    if stored_token != str(candidate_token):
        raise ValueError("candidate_token does not match the already-frozen candidate")

    new_schema = "chatgpt_view" in frozen or "strategy_action" in frozen
    if new_schema:
        stored_strategy = str(
            frozen.get("strategy_action") or frozen.get("final_action") or ""
        ).strip().upper()
        stored_view = str(
            frozen.get("chatgpt_view") or ""
        ).strip().upper()
        stored_confidence = frozen.get(
            "chatgpt_confidence_pct", frozen.get("confidence_pct")
        )
        stored_reasoning = frozen.get(
            "chatgpt_reasoning", frozen.get("reasoning")
        )
        if (
            stored_strategy != strategy_action
            or stored_view != chatgpt_view
            or stored_confidence != confidence_pct
            or stored_reasoning != reasoning
        ):
            raise ValueError(
                "retry does not match the already-frozen strategy action/ChatGPT view"
            )
        return True

    stored_action = str(frozen.get("final_action") or "").strip().upper()
    stored_confidence = frozen.get("confidence_pct")
    stored_reasoning = frozen.get("reasoning")
    if (
        stored_action != chatgpt_view
        or stored_confidence != confidence_pct
        or stored_reasoning != reasoning
    ):
        raise ValueError("retry does not match the already-frozen legacy decision")
    return False


def resume_safe_freeze_and_reveal_walk_forward_view(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    candidate_token: str,
    confidence_pct: int,
    reasoning: str,
    operation_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    chatgpt_view: str | None = None,
    final_action: str | None = None,
) -> dict[str, Any]:
    """Freeze normally, or resume reveal from an already-frozen matching view."""
    raw_view = _view_input(chatgpt_view, final_action)
    store, _readback, events = _impl._verified(
        control, experiment_id, expected_sequence, expected_state_hash
    )
    candidate = (_impl._candidate_capture(events, candidate_id).get("payload") or {})
    strategy_action = orchestrator._candidate_strategy_action(candidate)
    view, confidence, text = _impl._validate_decision_inputs(
        candidate, candidate_token, raw_view, confidence_pct, reasoning
    )
    state = store._candidate_state(events, candidate_id)

    if state == "ENTRY_CONTEXT_CAPTURED":
        return _ORIGINAL_FREEZE_AND_REVEAL(
            control,
            reports,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            candidate_token=candidate_token,
            chatgpt_view=view,
            confidence_pct=confidence,
            reasoning=text,
            operation_id=operation_id,
            expected_sequence=expected_sequence,
            expected_state_hash=expected_state_hash,
        )

    if state not in {"DECISION_FROZEN", "OUTCOME_REVEALED"}:
        raise ValueError(
            "candidate is not waiting for a ChatGPT view and has no resumable frozen outcome"
        )

    frozen_event = _impl._event_for_candidate(events, "DECISION_FROZEN", candidate_id)
    if frozen_event is None:
        raise ValueError("candidate state is frozen but DECISION_FROZEN event is missing")
    frozen = frozen_event.get("payload") or {}
    new_schema = _validate_matching_frozen_view(
        frozen,
        candidate_token=candidate_token,
        strategy_action=strategy_action,
        chatgpt_view=view,
        confidence_pct=confidence,
        reasoning=text,
    )

    if new_schema:
        return orchestrator._reveal_strategy_action_candidate(
            control,
            reports,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            operation_id=operation_id,
            expected_sequence=expected_sequence,
            expected_state_hash=expected_state_hash,
        )
    return orchestrator._reveal_frozen_candidate(
        control,
        reports,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        operation_id=operation_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
    )


def install_resume_safety() -> None:
    """Patch the orchestrator facade once, preserving all public tool names."""
    global _INSTALLED
    if _INSTALLED:
        return
    _impl._json_value = json_safe_value
    _impl._outcome_row_after_decision = _json_safe_outcome_row
    orchestrator.freeze_and_reveal_walk_forward_view = (
        resume_safe_freeze_and_reveal_walk_forward_view
    )
    _INSTALLED = True
