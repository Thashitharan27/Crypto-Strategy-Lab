"""B4 crash reconciliation: read-only evidence, never ownership recovery.

Persisted request claims cannot be mapped reliably to native saved-run folder
IDs after worker loss. Inspection intentionally does not delete/replay a claim,
unlock the worker or label a request as completed, even when the operator
independently names a valid completed-run directory.
"""
from __future__ import annotations

from pathlib import Path
import re
import stat

from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run

_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z", re.ASCII)


def _safe_root(path: Path) -> Path | None:
    root = Path(path)
    try:
        if not root.is_absolute() or not root.is_dir():
            return None
        if root.resolve(strict=True) != root:
            return None
        for segment in (root, *root.parents):
            if segment.is_symlink():
                return None
            junction = getattr(segment, "is_junction", None)
            if callable(junction) and junction():
                return None
            if getattr(segment.lstat(), "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            ):
                return None
        return root
    except (OSError, RuntimeError, ValueError):
        return None


def _claimed_directory(root: Path, label: str) -> bool | None:
    path = root / label
    try:
        if path.is_symlink() or (
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            return None
        return path.is_dir()
    except FileNotFoundError:
        return False
    except (OSError, ValueError, RuntimeError):
        return None


def inspect_b4_recovery(
    execution_root: Path,
    request_id: str,
    *,
    run_folder_id: str | None = None,
) -> dict[str, str | bool | None]:
    """Describe intact claims and independently verified artifacts only.

    This is an evidence-only operator report, not a release API, claim
    reconciliation or resumption tool. An explicit run folder is NOT inferred
    to belong to the request; the two inspections remain separate.
    """
    if not isinstance(request_id, str) or _ID.fullmatch(request_id) is None:
        raise ValueError("Invalid request identifier")
    if run_folder_id is not None and (
        not isinstance(run_folder_id, str) or _ID.fullmatch(run_folder_id) is None
    ):
        raise ValueError("Invalid saved-run folder identifier")
    result: dict[str, str | bool | None] = {
        "request_id": request_id,
        "request_status": "RECOVERY_UNVERIFIED",
        "claim_present": None,
        "worker_lock_present": None,
        "saved_run_folder_id": run_folder_id,
        "saved_artifacts_status": "NOT_CHECKED",
        "request_to_run_mapping": "UNVERIFIED",
    }
    root = _safe_root(execution_root)
    if root is None:
        return result
    result["claim_present"] = _claimed_directory(
        root, ".guarded-request-" + request_id + ".claim"
    )
    result["worker_lock_present"] = _claimed_directory(
        root, ".guarded-native-worker.lock"
    )
    if run_folder_id is not None:
        result["saved_artifacts_status"] = verify_recovered_run(
            root, run_folder_id
        )["status"]
    return result
