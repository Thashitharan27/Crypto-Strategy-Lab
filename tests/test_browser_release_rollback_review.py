"""Rollback evidence is a manual review aid, not a mutation/release API."""
from unittest.mock import patch

from crypto_strategy_lab.browser_release_audit import B4AuditJournal
from crypto_strategy_lab.browser_release_rollback_review import inspect_b4_rollback_readiness


def test_clean_read_only_evidence_still_never_authorizes_activation(tmp_path):
    audit = tmp_path / "audit"
    execution = tmp_path / "execution"
    audit.mkdir()
    execution.mkdir()
    with B4AuditJournal(audit, "clean") as journal:
        journal({"operation": "AUTH", "outcome": "DENIED"})
    before = journal.path.read_bytes()
    result = inspect_b4_rollback_readiness(
        audit_root=audit, session_id="clean", execution_root=execution,
        request_id="missing",
    )
    assert result["issues"] == []
    assert result["status"] == "RELEASE_HELD"
    assert result["production_activation_authorized"] is False
    assert result["safe_to_replay"] is False
    assert result["safe_to_clear_locks"] is False
    assert journal.path.read_bytes() == before
    assert not list(execution.iterdir())


def test_interrupted_mutation_and_persisted_claims_require_review(tmp_path):
    audit = tmp_path / "audit"
    execution = tmp_path / "execution"
    audit.mkdir()
    execution.mkdir()
    claim = execution / ".guarded-request-crashed.claim"
    lock = execution / ".guarded-native-worker.lock"
    claim.mkdir()
    lock.mkdir()
    (claim / "evidence").write_bytes(b"retain")
    with B4AuditJournal(audit, "crash") as journal:
        journal({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
        journal({"operation": "STATUS", "outcome": "SUCCESS"})
    before = journal.path.read_bytes()
    result = inspect_b4_rollback_readiness(
        audit_root=audit, session_id="crash",
        execution_root=execution, request_id="crashed",
    )
    assert "MUTATION_ATTEMPT_REQUIRES_REVIEW" in result["issues"]
    assert "REQUEST_CLAIM_REQUIRES_REVIEW" in result["issues"]
    assert "WORKER_LOCK_REQUIRES_REVIEW" in result["issues"]
    assert result["audit"]["last_event_status"] == "RECORDED_OUTCOME"
    assert result["recovery"]["request_status"] == "RECOVERY_UNVERIFIED"
    assert journal.path.read_bytes() == before
    assert (claim / "evidence").read_bytes() == b"retain"
    assert lock.is_dir()


def test_missing_audit_is_not_evidence_of_no_mutation(tmp_path):
    result = inspect_b4_rollback_readiness(
        audit_root=tmp_path, session_id="missing",
        execution_root=tmp_path, request_id="missing",
    )
    assert "AUDIT_UNVERIFIED" in result["issues"]
    assert result["audit"]["any_mutation_attempt"] is None
    assert result["production_activation_authorized"] is False


def test_verified_saved_run_still_cannot_map_to_request(tmp_path):
    audit = tmp_path / "audit"
    execution = tmp_path / "execution"
    audit.mkdir()
    execution.mkdir()
    with B4AuditJournal(audit, "review") as journal:
        journal({"operation": "AUTH", "outcome": "DENIED"})
    with patch(
        "crypto_strategy_lab.browser_release_reconciliation.verify_recovered_run",
        return_value={"status": "ARTIFACTS_VERIFIED"},
    ):
        result = inspect_b4_rollback_readiness(
            audit_root=audit, session_id="review",
            execution_root=execution, request_id="request",
            run_folder_id="saved",
        )
    assert "RUN_PROVENANCE_UNVERIFIED" in result["issues"]
    assert result["recovery"]["saved_artifacts_status"] == "ARTIFACTS_VERIFIED"
    assert result["request_to_run_mapping"] == "UNVERIFIED"
    assert result["safe_to_replay"] is False
