"""Hardened facade for the unified Crypto Strategy Lab MCP server.

The full server implementation remains in ``control_server_impl``.  This facade
adds two recovery guarantees needed by accelerated walk-forward startup:

* create_walk_forward_experiment does not report success until a verified
  read-back of the newly written hash chain succeeds;
* advance_walk_forward tolerates a very short create/advance overlap by waiting
  briefly for the experiment directory to become visible before returning the
  normal connection-safe error.
"""
from __future__ import annotations

import time
from typing import Any

from . import control_server_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_ORIGINAL_CREATE_EXPERIMENT = (
    _impl.RuleAwareBacktestControlService.create_walk_forward_experiment
)
_ORIGINAL_ADVANCE_WALK_FORWARD = _impl._advance_walk_forward
_CREATE_ADVANCE_GRACE_ATTEMPTS = 20
_CREATE_ADVANCE_GRACE_SECONDS = 0.1


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


def _advance_walk_forward_with_create_grace(*args, **kwargs):
    last_error: ValueError | None = None
    for attempt in range(_CREATE_ADVANCE_GRACE_ATTEMPTS):
        try:
            return _ORIGINAL_ADVANCE_WALK_FORWARD(*args, **kwargs)
        except ValueError as exc:
            if "causal experiment does not exist:" not in str(exc):
                raise
            last_error = exc
            if attempt + 1 < _CREATE_ADVANCE_GRACE_ATTEMPTS:
                time.sleep(_CREATE_ADVANCE_GRACE_SECONDS)
    assert last_error is not None
    raise last_error


_impl.RuleAwareBacktestControlService.create_walk_forward_experiment = (
    _verified_create_walk_forward_experiment
)
_impl._advance_walk_forward = _advance_walk_forward_with_create_grace
RuleAwareBacktestControlService = _impl.RuleAwareBacktestControlService


def main() -> None:
    return _impl.main()


if __name__ == "__main__":
    main()
