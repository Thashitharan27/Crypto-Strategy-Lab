"""B4 rollback evidence snapshot; strictly read-only and never activation approval.

This combines existing independent audit and native ownership inspections.
It cannot establish request-to-run provenance or authorize lock removal.
"""
from __future__ import annotations

from pathlib import Path

from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit
from crypto_strategy_lab.browser_release_reconciliation import inspect_b4_recovery


def inspect_b4_rollback_readiness(
    *, audit_root: Path, session_id: str, execution_root: Path,
    request_id: str, run_folder_id: str | None = None,
) -> dict[str, object]:
    """Report conservative review requirements without altering any root.

    Even fully readable evidence is insufficient to infer native completion,
    physical durability, safe replay, or permission for production activation.
    """
    audit = inspect_b4_audit(audit_root, session_id)
    recovery = inspect_b4_recovery(
        execution_root, request_id, run_folder_id=run_folder_id,
    )
    issues: list[str] = []
    if audit["status"] != "AUDIT_VERIFIED":
        issues.append("AUDIT_UNVERIFIED")
    elif audit["any_mutation_attempt"] is not False:
        issues.append("MUTATION_ATTEMPT_REQUIRES_REVIEW")
    if recovery["claim_present"] is not False:
        issues.append("REQUEST_CLAIM_REQUIRES_REVIEW")
    if recovery["worker_lock_present"] is not False:
        issues.append("WORKER_LOCK_REQUIRES_REVIEW")
    if run_folder_id is not None:
        issues.append("RUN_PROVENANCE_UNVERIFIED")
        if recovery["saved_artifacts_status"] != "ARTIFACTS_VERIFIED":
            issues.append("SAVED_ARTIFACTS_UNVERIFIED")
    return {
        "status": "RELEASE_HELD",
        "production_activation_authorized": False,
        "safe_to_replay": False,
        "safe_to_clear_locks": False,
        "request_to_run_mapping": "UNVERIFIED",
        "issues": issues,
        "audit": audit,
        "recovery": recovery,
    }
