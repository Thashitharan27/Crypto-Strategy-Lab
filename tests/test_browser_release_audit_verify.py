"""Read-only B4 audit validation must never repair or infer native success."""
import json
from pathlib import Path

import pytest

from crypto_strategy_lab.browser_release_audit import B4AuditJournal
from crypto_strategy_lab.browser_release_audit_verify import inspect_b4_audit


def test_verified_audit_bytes_do_not_establish_native_completion(tmp_path):
    with B4AuditJournal(tmp_path, "session1") as journal:
        journal({"operation": "AUTH", "outcome": "DENIED"})
        journal({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
    original = journal.path.read_bytes()
    result = inspect_b4_audit(tmp_path, "session1")
    assert result == {
        "status": "AUDIT_VERIFIED", "records": 2, "attempts": 1,
        "last_event_status": "ATTEMPT_ONLY",
    }
    assert journal.path.read_bytes() == original


def test_complete_outcome_is_only_recorded_outcome(tmp_path):
    with B4AuditJournal(tmp_path, "session2") as journal:
        journal({"operation": "CONFIG_SAVE", "outcome": "ATTEMPT"})
        journal({"operation": "CONFIG_SAVE", "outcome": "SUCCESS"})
    assert inspect_b4_audit(tmp_path, "session2") == {
        "status": "AUDIT_VERIFIED", "records": 2, "attempts": 1,
        "last_event_status": "RECORDED_OUTCOME",
    }


@pytest.mark.parametrize("bad_bytes", [
    b'{"operation":"AUTH","outcome":"DENIED"}',  # torn final newline
    b'{"operation":"AUTH","outcome":"DEN',
    b'{"operation":"AUTH","outcome":"DENIED","token":"secret"}\n',
    b'{"operation":"AUTH","outcome":"HACKED"}\n',
    b'{"operation":"UNKNOWN","outcome":"SUCCESS"}\n',
    b'{"operation":"AUTH","outcome":"ATTEMPT"}\n',
    b'{"outcome":"DENIED","operation":"AUTH"}\n',  # noncanonical encoding
    b'{"operation": "AUTH", "outcome": "DENIED"}\n',
    b'[]\n', b'\xff\n', b'\n', b'',
])
def test_corrupted_or_incomplete_journals_are_unverified_and_unchanged(tmp_path, bad_bytes):
    path = tmp_path / "csl-b4-audit-safe.jsonl"
    path.write_bytes(bad_bytes)
    assert inspect_b4_audit(tmp_path, "safe")["status"] == "AUDIT_UNVERIFIED"
    assert path.read_bytes() == bad_bytes


def test_missing_and_oversized_journal_fail_closed(tmp_path):
    assert inspect_b4_audit(tmp_path, "missing")["status"] == "AUDIT_UNVERIFIED"
    path = tmp_path / "csl-b4-audit-too-large.jsonl"
    with path.open("wb") as f:
        f.seek(8 * 1024 * 1024)
        f.write(b"\n")
    assert inspect_b4_audit(tmp_path, "too-large")["status"] == "AUDIT_UNVERIFIED"


@pytest.mark.parametrize("bad", ["", "../escape", "bad.name", "é", "A" * 65])
def test_invalid_session_id_fails_before_access(tmp_path, bad):
    with pytest.raises(ValueError):
        inspect_b4_audit(tmp_path, bad)


def test_symlinked_journal_and_root_rejected_without_following(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    hidden = source / "data.jsonl"
    hidden.write_bytes(b"private")
    root = tmp_path / "isolated"
    root.mkdir()
    link = root / "csl-b4-audit-safe.jsonl"
    try:
        link.symlink_to(hidden)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    assert inspect_b4_audit(root, "safe")["status"] == "AUDIT_UNVERIFIED"
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert inspect_b4_audit(alias, "safe")["status"] == "AUDIT_UNVERIFIED"
    assert hidden.read_bytes() == b"private"
