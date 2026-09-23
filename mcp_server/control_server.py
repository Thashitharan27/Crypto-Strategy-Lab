"""Hardened facade for the unified Crypto Strategy Lab MCP server.

The full server implementation remains in ``control_server_impl``. This facade
adds recovery guarantees needed by accelerated walk-forward startup, routes MCP
decision tools through separated strategy-action/ChatGPT-view semantics,
preflights review-authored causal rules through the Strategy Builder compiler,
makes an already-frozen decision safely resumable if reveal was interrupted,
and settles canonical nested risk models without requiring legacy root fields.

* create_walk_forward_experiment does not report success until a verified
  read-back of the newly written hash chain succeeds;
* advance_walk_forward tolerates a very short create/advance overlap by waiting
  briefly for the experiment directory to become visible before returning the
  normal connection-safe error;
* the MCP ``final_action`` argument is retained as a legacy wire name but is
  interpreted only as ChatGPT's independent view. The executable strategy side
  is always taken from the captured ENTRY/VETO/FLIP result;
* teacher/loss/periodic review rules are canonicalized and compiled before an
  atomic review+rules batch is persisted, so invalid rule schemas cannot poison
  the immutable experiment chain;
* DECISION_FROZEN can resume directly into outcome reveal after a transport or
  serialization failure, and EVE outcome scalars are normalized to strict JSON
  before OUTCOME_REVEALED is appended;
* already-active prospective FLIP trades fall back to deterministic immutable
  1m replay when the flipped side has no unique EVE row;
* settlement prefers ``risk_model.risk_per_trade`` and nested ``initial_equity``
  while retaining legacy top-level ``risk_pct``/``initial_equity`` as fallbacks.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time
from typing import Any

from crypto_strategy_lab import walk_forward_orchestrator as _wf_orchestrator
from crypto_strategy_lab import walk_forward_review_facade as _wf_review_facade
from crypto_strategy_lab import walk_forward_candidate_engine as _wf_candidate_engine
from crypto_strategy_lab.walk_forward_opposite_replay import (
    replay_opposite_one_r as _replay_opposite_one_r,
)
from crypto_strategy_lab.walk_forward_prospective_flip_replay import (
    replay_flipped_candidate_one_r as _replay_flipped_candidate_one_r,
)
from crypto_strategy_lab.walk_forward_resume_safety import (
    install_resume_safety as _install_resume_safety,
)
from crypto_strategy_lab.walk_forward_review_facade import (
    record_walk_forward_review as _validated_record_walk_forward_review,
    record_walk_forward_teacher_review as _validated_record_walk_forward_teacher_review,
)
from crypto_strategy_lab.walk_forward_rule_validation import rule_event_schema as _rule_event_schema
from crypto_strategy_lab.walk_forward_research_policy import (
    decorate_review_packet as _decorate_review_packet,
)
from crypto_strategy_lab.walk_forward_settlement_compat import (
    install_settlement_compat as _install_settlement_compat,
    resolve_walk_forward_trade as _nested_risk_resolve_walk_forward_trade,
)
from . import control_server_impl as _impl

# Install before binding nested MCP tool globals below, so the stable tool names
# point at the resumable/JSON-safe and nested-risk-compatible implementations on
# every fresh MCP process.
_install_settlement_compat()
_install_resume_safety()

# Keep the public orchestrator facade aligned with the runtime implementation.
_wf_orchestrator.resolve_walk_forward_trade = _nested_risk_resolve_walk_forward_trade

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


_ORIGINAL_GET_NEXT_CANDIDATE = _impl._get_next_walk_forward_candidate
_ORIGINAL_TEACHER_LOSS_DECORATOR = _wf_orchestrator._decorate_teacher_loss_packet
_ORIGINAL_REVEAL_STRATEGY_ACTION = _wf_orchestrator._reveal_strategy_action_candidate


def _get_next_candidate_with_strategy_action(*args, **kwargs):
    result = _ORIGINAL_GET_NEXT_CANDIDATE(*args, **kwargs)
    if not isinstance(result, dict):
        return result
    updated = deepcopy(result)
    candidate = updated.get("candidate")
    if isinstance(candidate, dict):
        side = str(
            candidate.get("strategy_action")
            or candidate.get("rule_effective_side")
            or candidate.get("source_side")
            or ""
        ).strip().upper()
        if side in {"LONG", "SHORT"}:
            candidate["strategy_action"] = side
            updated["strategy_action"] = side
    return updated


def _decorate_teacher_loss_with_replay(control, reports, experiment_id, result):
    """Use immutable EVE first, then causally replay opposite 1R from 1m data."""
    updated = _ORIGINAL_TEACHER_LOSS_DECORATOR(
        control, reports, experiment_id, result
    )
    if not isinstance(updated, dict) or updated.get("status") != "TEACHER_LOSS_REVIEW_REQUIRED":
        return updated

    current = updated.get("opposite_side_outcome")
    if isinstance(current, dict) and current.get("available") is True:
        return updated

    teacher = updated.get("teacher")
    if not isinstance(teacher, dict):
        return updated
    side = str(teacher.get("side", "")).strip().upper()
    if side not in {"LONG", "SHORT"}:
        return updated
    opposite = "SHORT" if side == "LONG" else "LONG"

    store = _wf_orchestrator._impl._store(control)
    readback = store.read_fast(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", "")).strip()
    if not reference_run:
        return updated

    replay = _replay_opposite_one_r(
        control,
        reports,
        reference_run=reference_run,
        teacher=teacher,
        entry_context=updated.get("entry_context") or {},
        opposite_side=opposite,
    )
    updated["opposite_side_outcome"] = replay
    updated["flip_activation_allowed"] = bool(
        replay.get("available")
        and str((replay.get("outcome") or {}).get("result", "")).upper() == "WIN"
    )
    return updated


def _reveal_strategy_action_with_flip_replay(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    candidate_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Reveal EVE normally, with immutable 1m fallback only for active FLIP trades."""
    try:
        return _ORIGINAL_REVEAL_STRATEGY_ACTION(
            control,
            reports,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            operation_id=operation_id,
        )
    except ValueError as exc:
        if (
            "the frozen side has no unique immutable Every Viable Entry outcome at this signal"
            not in str(exc)
        ):
            raise

    store = _wf_orchestrator._impl._store(control)
    events = _wf_orchestrator._impl._events(store, experiment_id)
    reveal_op = _wf_orchestrator._impl._operation(operation_id, "reveal")
    existing = store._find_operation(events, reveal_op)
    if existing is not None or store._candidate_state(events, candidate_id) == "OUTCOME_REVEALED":
        return _ORIGINAL_REVEAL_STRATEGY_ACTION(
            control,
            reports,
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            operation_id=operation_id,
        )
    if store._candidate_state(events, candidate_id) != "DECISION_FROZEN":
        raise ValueError("prospective FLIP replay requires a durably frozen decision")

    candidate = (
        _wf_orchestrator._impl._candidate_capture(events, candidate_id).get("payload")
        or {}
    )
    source_side = str(candidate.get("source_side") or "").strip().upper()
    strategy_action = _wf_orchestrator._candidate_strategy_action(candidate)
    if not list(candidate.get("matched_flip_groups") or []):
        raise ValueError(
            "missing opposite EVE outcome is not eligible for replay because no active FLIP matched"
        )
    expected_flipped = "SHORT" if source_side == "LONG" else "LONG"
    if source_side not in {"LONG", "SHORT"} or strategy_action != expected_flipped:
        raise ValueError(
            "missing opposite EVE outcome is not eligible for replay because strategy_action "
            "is not the inverse source side"
        )

    frozen_event = _wf_orchestrator._impl._event_for_candidate(
        events, "DECISION_FROZEN", candidate_id
    )
    if frozen_event is None:
        raise ValueError("candidate is frozen but DECISION_FROZEN event is missing")
    frozen = frozen_event.get("payload") or {}
    stored_strategy = str(
        frozen.get("strategy_action") or frozen.get("final_action") or ""
    ).strip().upper()
    if stored_strategy != strategy_action:
        raise ValueError("frozen executable side does not match the captured FLIP strategy_action")
    chatgpt_view = str(
        frozen.get("chatgpt_view") or frozen.get("final_action") or ""
    ).strip().upper()

    readback = store.read_fast(experiment_id, recent_events=0)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(
        candidate.get("reference_run") or definition.get("reference_run") or ""
    ).strip()
    if not reference_run:
        raise ValueError("captured candidate and experiment definition have no reference_run")

    outcome = _replay_flipped_candidate_one_r(
        control,
        reports,
        reference_run=reference_run,
        candidate=candidate,
        strategy_action=strategy_action,
    )
    exit_time = outcome.get("exit_time")
    appended = store.append_event(
        experiment_id,
        "OUTCOME_REVEALED",
        {
            "candidate_id": candidate_id,
            "candidate_token": candidate.get("candidate_token"),
            "final_action": strategy_action,
            "strategy_action": strategy_action,
            "chatgpt_view": chatgpt_view or None,
            "chatgpt_agrees_with_strategy": (
                chatgpt_view == strategy_action
                if chatgpt_view in {"LONG", "SHORT"}
                else None
            ),
            "outcome_contract": _wf_orchestrator._impl.OUTCOME_CONTRACT,
            "outcome": outcome,
        },
        reveal_op,
        int(readback["sequence"]),
        str(readback["state_hash"]),
        effective_market_time=(
            str(exit_time) if exit_time else str(candidate.get("entry_time"))
        ),
        source="DETERMINISTIC_OUTCOME_FIREWALL_FLIP_REPLAY",
    )
    return {
        "contract": _wf_orchestrator._impl.OUTCOME_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": appended["sequence"],
        "state_hash": appended["state_hash"],
        "candidate_id": candidate_id,
        "strategy_action": strategy_action,
        "chatgpt_view": chatgpt_view or None,
        "outcome": outcome,
        "outcome_source": "IMMUTABLE_1M_INTRABAR_REPLAY",
        "idempotent_replay": False,
    }


def _with_rule_schema(result):
    if not isinstance(result, dict):
        return result
    if result.get("status") not in {
        "TEACHER_REVIEW_REQUIRED",
        "TEACHER_LOSS_REVIEW_REQUIRED",
        "LOSS_REVIEW_REQUIRED",
        "PERIODIC_REVIEW_REQUIRED",
        "BOOTSTRAP_RESEARCH_REQUIRED",
    }:
        return result
    updated = deepcopy(result)
    updated.setdefault("rule_event_schema", _rule_event_schema())
    return _decorate_review_packet(updated)


# Patch both modules because the review facade imported the teacher decorator by
# value, while the orchestrator resolves its module global at call time.
_wf_orchestrator._decorate_teacher_loss_packet = _decorate_teacher_loss_with_replay
_wf_review_facade._decorate_teacher_loss_packet = _decorate_teacher_loss_with_replay

# Resume-safety and the normal submit path both resolve this module global at
# call time, so an already-frozen candidate can continue directly into replay.
_wf_orchestrator._reveal_strategy_action_candidate = (
    _reveal_strategy_action_with_flip_replay
)

# Patch the module globals referenced by the nested MCP tool functions. Existing
# tool names remain stable. Adding a new MCP action still requires one plugin
# schema reconnect after the updated server process is restarted.
_impl._get_next_walk_forward_candidate = _get_next_candidate_with_strategy_action
_impl._freeze_and_reveal_walk_forward_candidate = (
    _wf_orchestrator.freeze_and_reveal_walk_forward_view
)
_impl._submit_walk_forward_decision = _wf_orchestrator.submit_walk_forward_view
_impl._resolve_walk_forward_trade = _nested_risk_resolve_walk_forward_trade
_impl._advance_walk_forward = _wf_orchestrator.advance_walk_forward
_impl._record_walk_forward_review = _validated_record_walk_forward_review
_impl._record_walk_forward_teacher_review = _validated_record_walk_forward_teacher_review

_ORIGINAL_CREATE_EXPERIMENT = (
    _impl.RuleAwareBacktestControlService.create_walk_forward_experiment
)
_ORIGINAL_ADVANCE_WALK_FORWARD = _impl._advance_walk_forward
_ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS = _impl._continue_walk_forward_autonomous
_CREATE_ADVANCE_GRACE_ATTEMPTS = 20
_CREATE_ADVANCE_GRACE_SECONDS = 0.1

_REVIEW_PACKET_CACHE_VERSION = 2
_RECOVERABLE_REVIEW_STATUSES = frozenset({
    "TEACHER_REVIEW_REQUIRED",
    "TEACHER_LOSS_REVIEW_REQUIRED",
    "TEACHER_FLIP_VALIDATION_INCONSISTENCY",
    "LOSS_REVIEW_REQUIRED",
    "PERIODIC_REVIEW_REQUIRED",
})


def _review_packet_cache_coordinates(args, kwargs):
    control = args[0] if args else kwargs.get("control")
    experiment_id = str(kwargs.get("experiment_id") or "").strip()
    expected_sequence = kwargs.get("expected_sequence")
    expected_state_hash = str(kwargs.get("expected_state_hash") or "").strip().lower()
    if (
        control is None
        or not experiment_id
        or expected_sequence is None
        or not expected_state_hash
    ):
        return None
    return control, experiment_id, int(expected_sequence), expected_state_hash


def _review_packet_cache_path(
    control: Any,
    experiment_id: str,
    sequence: int,
    state_hash: str,
    review_interval_months: int,
    teacher_loss_flip_enabled: bool,
) -> tuple[Any, Path]:
    store = _wf_orchestrator._impl._store(control)
    _value, directory = store._dir(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    cache_dir = directory / "review_packet_cache"
    if cache_dir.exists() and (cache_dir.is_symlink() or not cache_dir.is_dir()):
        raise ValueError("review packet cache path is not a safe directory")
    cache_dir.mkdir(parents=False, exist_ok=True)
    name = (
        f"review-{int(sequence)}-{str(state_hash).lower()}-"
        f"flip{int(bool(teacher_loss_flip_enabled))}-"
        f"months{int(review_interval_months)}.json"
    )
    return store, cache_dir / name


def _review_packet_cache_head(
    store: Any,
    experiment_id: str,
    sequence: int,
    state_hash: str,
) -> None:
    readback = store.read_fast(experiment_id, recent_events=0)
    if (
        int(readback.get("sequence", -1)) != int(sequence)
        or str(readback.get("state_hash") or "").lower() != str(state_hash).lower()
    ):
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again"
        )


def _review_packet_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _review_packet_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_review_packet_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _review_packet_json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _load_cached_review_packet(action, args, kwargs):
    coordinates = _review_packet_cache_coordinates(args, kwargs)
    if coordinates is None:
        return None
    control, experiment_id, sequence, state_hash = coordinates
    months = int(kwargs.get("review_interval_months", 3))
    flip_enabled = bool(_wf_candidate_engine._teacher_loss_flip_enabled())
    store, path = _review_packet_cache_path(
        control,
        experiment_id,
        sequence,
        state_hash,
        months,
        flip_enabled,
    )
    _review_packet_cache_head(store, experiment_id, sequence, state_hash)
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    if (
        int(envelope.get("version", -1)) != _REVIEW_PACKET_CACHE_VERSION
        or str(envelope.get("experiment_id") or "") != experiment_id
        or int(envelope.get("sequence", -1)) != sequence
        or str(envelope.get("state_hash") or "").lower() != state_hash
        or bool(envelope.get("teacher_loss_flip_enabled")) != flip_enabled
        or int(envelope.get("review_interval_months", -1)) != months
        or not isinstance(envelope.get("packet"), dict)
    ):
        return None
    _review_packet_cache_head(store, experiment_id, sequence, state_hash)
    packet = deepcopy(envelope["packet"])
    if action is _ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS:
        packet.setdefault(
            "autonomous_contract",
            _wf_orchestrator.AUTONOMOUS_ORCHESTRATOR_CONTRACT,
        )
        packet.setdefault(
            "autonomous",
            _wf_orchestrator._autonomous_metadata(
                continue_without_user=True,
                assistant_judgment_required=True,
                stop_reason="ASSISTANT_JUDGMENT_REQUIRED",
                scan_slices=0,
                scan_checkpoints=0,
                rows_scanned=0,
            ),
        )
    else:
        packet.pop("autonomous_contract", None)
        packet.pop("autonomous", None)
    packet["review_packet_cache"] = {
        "hit": True,
        "persisted": True,
        "sequence": sequence,
        "state_hash": state_hash,
    }
    return packet


def _persist_review_packet(action, args, kwargs, result):
    if not isinstance(result, dict):
        return result
    status = str(result.get("status") or "")
    if status not in _RECOVERABLE_REVIEW_STATUSES:
        return result
    experiment_id = str(result.get("experiment_id") or kwargs.get("experiment_id") or "").strip()
    sequence = result.get("sequence")
    state_hash = str(result.get("state_hash") or "").strip().lower()
    control = args[0] if args else kwargs.get("control")
    if control is None or not experiment_id or sequence is None or not state_hash:
        return result
    months = int(kwargs.get("review_interval_months", 3))
    flip_enabled = bool(_wf_candidate_engine._teacher_loss_flip_enabled())
    store, path = _review_packet_cache_path(
        control,
        experiment_id,
        int(sequence),
        state_hash,
        months,
        flip_enabled,
    )
    _review_packet_cache_head(store, experiment_id, int(sequence), state_hash)
    packet = deepcopy(result)
    packet.pop("review_packet_cache", None)
    envelope = {
        "version": _REVIEW_PACKET_CACHE_VERSION,
        "experiment_id": experiment_id,
        "sequence": int(sequence),
        "state_hash": state_hash,
        "teacher_loss_flip_enabled": flip_enabled,
        "review_interval_months": months,
        "status": status,
        "packet": _review_packet_json_safe(packet),
    }
    temp = path.parent / (
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        text = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    _review_packet_cache_head(store, experiment_id, int(sequence), state_hash)
    updated = deepcopy(result)
    updated["review_packet_cache"] = {
        "hit": False,
        "persisted": True,
        "sequence": int(sequence),
        "state_hash": state_hash,
    }
    return updated


def _verified_create_walk_forward_experiment(
    self,
    experiment_id: str,
    definition: dict[str, Any],
    operation_id: str,
    initial_phase: str = "RESEARCH_WF",
    notes: str | None = None,
) -> dict[str, Any]:
    result = _ORIGINAL_CREATE_EXPERIMENT(
        self,
        experiment_id,
        definition,
        operation_id,
        initial_phase=initial_phase,
        notes=notes,
    )
    if not isinstance(result, dict) or result.get("ok") is False:
        return result

    readback = self.read_walk_forward_experiment(experiment_id, recent_events=1)
    if not isinstance(readback, dict) or readback.get("ok") is False:
        return {
            "ok": False,
            "operation": "create_walk_forward_experiment",
            "error_type": "PostCreateVerificationError",
            "error": "experiment was written but verified read-back failed",
            "connection_safe": True,
            "experiment_id": experiment_id,
            "created": True,
            "readback": readback,
            "instruction": (
                "Do not recreate blindly. Read/list the existing experiment first, "
                "then continue from its verified head."
            ),
        }

    created_sequence = int(result.get("sequence", -1))
    created_hash = str(result.get("state_hash", "")).lower()
    read_sequence = int(readback.get("sequence", -2))
    read_hash = str(readback.get("state_hash", "")).lower()
    if created_sequence != read_sequence or not created_hash or created_hash != read_hash:
        return {
            "ok": False,
            "operation": "create_walk_forward_experiment",
            "error_type": "PostCreateVerificationMismatch",
            "error": "experiment write/read-back head mismatch",
            "connection_safe": True,
            "experiment_id": experiment_id,
            "created": True,
            "created_sequence": created_sequence,
            "created_state_hash": created_hash,
            "read_sequence": read_sequence,
            "read_state_hash": read_hash,
            "instruction": (
                "Do not advance or recreate. Inspect the existing experiment head first."
            ),
        }

    verified = dict(result)
    verified["verified_readback"] = {
        "sequence": read_sequence,
        "state_hash": read_hash,
        "recent_event_count": len(readback.get("recent_events") or []),
    }
    return verified


def _with_create_advance_grace(action, *args, **kwargs):
    cached = _load_cached_review_packet(action, args, kwargs)
    if cached is not None:
        return cached

    last_error: ValueError | None = None
    for attempt in range(_CREATE_ADVANCE_GRACE_ATTEMPTS):
        try:
            result = _with_rule_schema(action(*args, **kwargs))
            return _persist_review_packet(action, args, kwargs, result)
        except ValueError as exc:
            if "causal experiment does not exist:" not in str(exc):
                raise
            last_error = exc
            if attempt + 1 < _CREATE_ADVANCE_GRACE_ATTEMPTS:
                time.sleep(_CREATE_ADVANCE_GRACE_SECONDS)
    assert last_error is not None
    raise last_error


def _advance_walk_forward_with_create_grace(*args, **kwargs):
    return _with_create_advance_grace(
        _ORIGINAL_ADVANCE_WALK_FORWARD, *args, **kwargs
    )


def _continue_walk_forward_autonomous_with_create_grace(*args, **kwargs):
    return _with_create_advance_grace(
        _ORIGINAL_CONTINUE_WALK_FORWARD_AUTONOMOUS, *args, **kwargs
    )


_impl.RuleAwareBacktestControlService.create_walk_forward_experiment = (
    _verified_create_walk_forward_experiment
)
_impl._advance_walk_forward = _advance_walk_forward_with_create_grace
_impl._continue_walk_forward_autonomous = (
    _continue_walk_forward_autonomous_with_create_grace
)
RuleAwareBacktestControlService = _impl.RuleAwareBacktestControlService


def main() -> None:
    return _impl.main()


if __name__ == "__main__":
    main()
