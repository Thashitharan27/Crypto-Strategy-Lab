"""Fail-closed interpretation of retained job states after a process restart.

This does not load or mutate manifests, retry jobs, or certify their outputs.
A durable recovery implementation must verify native completed-run provenance.
"""
from __future__ import annotations

_ALLOWED = frozenset({"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"})


def classify_recovered_job(request_id: str, previous_status: str) -> dict[str, str]:
    """Classify an untrusted pre-restart status without claiming completion."""
    if (not isinstance(request_id, str) or not request_id.isascii()
            or not (1 <= len(request_id) <= 100)
            or not all(c.isalnum() or c in "_-" for c in request_id)):
        raise ValueError("Invalid request identifier")
    if previous_status not in _ALLOWED:
        raise ValueError("Unknown retained job state")
    # Even a prior COMPLETED flag cannot prove durable output integrity.
    # Native manifests and artifacts must be verified independently.
    return {"request_id": request_id, "status": "RECOVERY_UNVERIFIED"}
