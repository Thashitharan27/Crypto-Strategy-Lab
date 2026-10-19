"""Finite cross-process B4 crash evidence check, isolated fixtures only.

A child intentionally exits abruptly after a torn journal write. This is not
a hardware power-loss or native worker process-kill certification.
"""
import os
import subprocess
import sys

import pytest

from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit
from crypto_strategy_lab.browser_release_rollback_review import inspect_b4_rollback_readiness
from crypto_strategy_lab.browser_release_audit import B4AuditJournal


def test_abrupt_child_exit_preserves_torn_audit_and_native_claims(tmp_path):
    audit_root = tmp_path / "audit"
    execution_root = tmp_path / "execution"
    audit_root.mkdir()
    execution_root.mkdir()
    request_claim = execution_root / ".guarded-request-interrupted.claim"
    worker_lock = execution_root / ".guarded-native-worker.lock"
    request_claim.mkdir()
    worker_lock.mkdir()
    marker = request_claim / "preserve.bin"
    marker.write_bytes(b"native ownership remains unknown")

    script = """
import os
import sys
from pathlib import Path
from crypto_strategy_lab.browser_release_audit import B4AuditJournal
root = Path(sys.argv[1])
journal = B4AuditJournal(root, 'crashed')
journal({'operation': 'JOB_SUBMIT', 'outcome': 'ATTEMPT'})
os.write(journal._fd, b'{"operation":')
os._exit(77)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(audit_root)],
        check=False, capture_output=True, text=True, timeout=20,
        env=os.environ.copy(),
    )
    assert result.returncode == 77, result.stderr
    journal_path = audit_root / "csl-b4-audit-crashed.jsonl"
    prior = journal_path.read_bytes()
    assert prior.endswith(b'{"operation":')
    audit = inspect_b4_audit(audit_root, "crashed")
    assert audit["status"] == "AUDIT_UNVERIFIED"
    assert audit["any_mutation_attempt"] is None

    # Fresh-session journal creation must not overwrite previous evidence.
    with pytest.raises(FileExistsError):
        B4AuditJournal(audit_root, "crashed")
    report = inspect_b4_rollback_readiness(
        audit_root=audit_root, session_id="crashed",
        execution_root=execution_root, request_id="interrupted",
    )
    assert report["status"] == "RELEASE_HELD"
    assert report["safe_to_replay"] is False
    assert report["safe_to_clear_locks"] is False
    assert report["production_activation_authorized"] is False
    assert "AUDIT_UNVERIFIED" in report["issues"]
    assert "REQUEST_CLAIM_REQUIRES_REVIEW" in report["issues"]
    assert "WORKER_LOCK_REQUIRES_REVIEW" in report["issues"]
    assert journal_path.read_bytes() == prior
    assert marker.read_bytes() == b"native ownership remains unknown"
    assert worker_lock.is_dir()
