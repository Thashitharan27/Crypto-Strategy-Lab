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
