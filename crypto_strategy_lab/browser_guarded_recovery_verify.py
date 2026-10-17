"""Read-only verification of recovered completed-run artifacts.

No restart/resume or mutation is performed; native manifest rules remain the
only authority for a completed persisted run.
"""
from pathlib import Path
import re

from crypto_strategy_lab.run_manifest import (
    RunArtifactError, artifact_path, load_completed_manifest,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def verify_recovered_run(output_root: Path, run_id: str) -> dict[str, str]:
    if not isinstance(run_id, str) or _SAFE_ID.fullmatch(run_id) is None:
        raise ValueError("Invalid run identifier")
    root = Path(output_root)
    if not root.is_absolute() or not root.is_dir() or any(
        part == ".." for part in root.parts
    ) or any(part.is_symlink() for part in (root, *root.parents)):
        return {"run_id": run_id, "status": "RECOVERY_UNVERIFIED"}
    canonical = root.resolve(strict=True)
    if canonical != root:
        return {"run_id": run_id, "status": "RECOVERY_UNVERIFIED"}
    root = canonical
    candidate = root / run_id
    if candidate.is_symlink() or not candidate.is_dir():
        return {"run_id": run_id, "status": "RECOVERY_UNVERIFIED"}
    try:
        manifest = load_completed_manifest(candidate)
        # Verify all cataloged artifacts, not only the summary.
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            raise RunArtifactError("No cataloged artifacts")
        for name in artifacts:
            artifact_path(candidate, manifest, name, verify=True)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, AttributeError):
        return {"run_id": run_id, "status": "RECOVERY_UNVERIFIED"}
    return {"run_id": run_id, "status": "ARTIFACTS_VERIFIED"}
