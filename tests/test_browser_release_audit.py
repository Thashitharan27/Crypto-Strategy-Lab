"""B4 journal tests do not use original files or enable a production listener."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from crypto_strategy_lab.browser_release_audit import B4AuditJournal


def test_journal_is_exclusive_private_and_persists_sanitized_order(tmp_path):
    keep = tmp_path / "keep.bin"
    keep.write_bytes(b"original")
    with B4AuditJournal(tmp_path, "review-1") as audit:
        audit({"operation": "AUTH", "outcome": "DENIED"})
        audit({"operation": "CONFIG_SAVE", "outcome": "SUCCESS"})
        assert audit.path.name == "csl-b4-audit-review-1.jsonl"
        with pytest.raises(FileExistsError):
            B4AuditJournal(tmp_path, "review-1")
    assert audit.path.read_bytes() == (
        b'{"operation":"AUTH","outcome":"DENIED"}\n'
        b'{"operation":"CONFIG_SAVE","outcome":"SUCCESS"}\n'
    )
    assert keep.read_bytes() == b"original"
    if os.name != "nt":
        assert audit.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match="closed"):
        audit({"operation": "AUTH", "outcome": "SUCCESS"})


@pytest.mark.parametrize("event", [
    {}, {"operation": "AUTH"}, {"operation": "AUTH", "outcome": "DENIED", "token": "secret"},
    {"operation": "AUTH", "outcome": "DENIED", "request_id": "private"},
    {"operation": "AUTH", "outcome": "DENIED\nsecret"},
    {"operation": "/private/data", "outcome": "SUCCESS"},
    {"operation": 1, "outcome": "SUCCESS"},
    {"operation": "AUTH", "outcome": 1},
    ["AUTH", "DENIED"],
])
def test_audit_refuses_unknown_fields_and_unsanitized_values(tmp_path, event):
    with B4AuditJournal(tmp_path, "safe") as audit:
        with pytest.raises(ValueError):
            audit(event)
    assert (tmp_path / "csl-b4-audit-safe.jsonl").read_bytes() == b""


@pytest.mark.parametrize("bad", ["", "../escape", "bad.name", "é", "x" * 65])
def test_audit_refuses_bad_session_ids_without_writes(tmp_path, bad):
    with pytest.raises(ValueError):
        B4AuditJournal(tmp_path, bad)
    assert not list(tmp_path.iterdir())


def test_audit_rejects_relative_missing_and_linked_roots(tmp_path):
    with pytest.raises(ValueError):
        B4AuditJournal(Path("relative"), "safe")
    with pytest.raises(ValueError):
        B4AuditJournal(tmp_path / "absent", "safe")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem links unavailable")
    with pytest.raises(ValueError):
        B4AuditJournal(alias, "safe")
    assert not (tmp_path / "csl-b4-audit-safe.jsonl").exists()


def test_audit_fsync_failure_is_observable_to_caller(tmp_path):
    with B4AuditJournal(tmp_path, "safe") as audit:
        with patch("crypto_strategy_lab.browser_release_audit.os.fsync",
                   side_effect=OSError("unavailable")):
            with pytest.raises(OSError, match="unavailable"):
                audit({"operation": "AUTH", "outcome": "DENIED"})
    # No assertion of durable success when fsync fails.


def test_audit_refuses_detached_named_path_before_append(tmp_path, monkeypatch):
    from crypto_strategy_lab import browser_release_audit as audit_module
    with B4AuditJournal(tmp_path, "identity") as audit:
        audit({"operation": "AUTH", "outcome": "DENIED"})
        before = audit.path.read_bytes()
        real_stat = audit_module.os.stat

        def changed_identity(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if str(path) != str(audit.path):
                return info
            class ReplacementStat:
                st_mode = info.st_mode
                st_dev = info.st_dev
                st_ino = info.st_ino + 1
            return ReplacementStat()

        monkeypatch.setattr(audit_module.os, "stat", changed_identity)
        with pytest.raises(OSError, match="identity changed"):
            audit({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
        assert audit.path.read_bytes() == before


def test_failed_fsync_latches_journal_against_followup_append(tmp_path):
    with B4AuditJournal(tmp_path, "fail-closed") as audit:
        event = {"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"}
        with patch("crypto_strategy_lab.browser_release_audit.os.fsync",
                   side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                audit(event)
        before = audit.path.read_bytes()
        with pytest.raises(OSError, match="previously failed"):
            audit({"operation": "JOB_SUBMIT", "outcome": "SUCCESS"})
        assert audit.path.read_bytes() == before
    # Existing evidence is retained for inspection, not repaired or replayed.


def test_partial_audit_write_failure_preserves_bytes_and_latches(tmp_path):
    from crypto_strategy_lab import browser_release_audit as audit_module

    with B4AuditJournal(tmp_path, "partial") as audit:
        audit({"operation": "AUTH", "outcome": "DENIED"})
        original = audit.path.read_bytes()
        real_write = audit_module.os.write
        writes = 0

        def partial_then_failure(fd, data):
            nonlocal writes
            writes += 1
            if writes == 1:
                return real_write(fd, data[:7])
            raise OSError("simulated disk full after partial append")

        with patch.object(audit_module.os, "write", side_effect=partial_then_failure):
            with pytest.raises(OSError, match="disk full"):
                audit({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
        partial = audit.path.read_bytes()
        assert partial.startswith(original)
        assert len(partial) == len(original) + 7
        with pytest.raises(OSError, match="previously failed"):
            audit({"operation": "JOB_SUBMIT", "outcome": "SUCCESS"})
        assert audit.path.read_bytes() == partial
    # Torn evidence is retained rather than repaired or falsely certified.


@pytest.mark.parametrize("operation", ["AUTH", "STATUS", "PROGRESS"])
def test_writer_rejects_attempts_that_its_inspector_cannot_validate(tmp_path, operation):
    from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit
    with B4AuditJournal(tmp_path, "schema") as audit:
        audit({"operation": "STATUS", "outcome": "SUCCESS"})
        before = audit.path.read_bytes()
        with pytest.raises(ValueError, match="mutation"):
            audit({"operation": operation, "outcome": "ATTEMPT"})
        assert audit.path.read_bytes() == before
    assert inspect_b4_audit(tmp_path, "schema")["status"] == "AUDIT_VERIFIED"


@pytest.mark.parametrize("limit", ["bytes", "records"])
def test_capacity_refusal_preserves_verifiable_evidence_and_latches(tmp_path, monkeypatch, limit):
    from crypto_strategy_lab import browser_release_audit as audit_module
    from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit
    event = {"operation": "STATUS", "outcome": "SUCCESS"}
    with B4AuditJournal(tmp_path, "capacity") as audit:
        audit(event)
        before = audit.path.read_bytes()
        # Small capacity fixture exercises the same boundary without 100,000
        # synchronous disk flushes. It does not certify disk-full durability.
        monkeypatch.setattr(audit_module, "_MAX_BYTES" if limit == "bytes" else "_MAX_RECORDS",
                            len(before) if limit == "bytes" else 1, raising=False)
        with pytest.raises(OSError, match="capacity"):
            audit({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
        assert audit.path.read_bytes() == before
        with pytest.raises(OSError, match="previously failed"):
            audit(event)
        assert inspect_b4_audit(tmp_path, "capacity")["status"] == "AUDIT_VERIFIED"
