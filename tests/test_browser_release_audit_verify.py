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
        "last_event_status": "ATTEMPT_ONLY", "any_mutation_attempt": True,
    }
    assert journal.path.read_bytes() == original


def test_complete_outcome_is_only_recorded_outcome(tmp_path):
    with B4AuditJournal(tmp_path, "session2") as journal:
        journal({"operation": "CONFIG_SAVE", "outcome": "ATTEMPT"})
        journal({"operation": "CONFIG_SAVE", "outcome": "SUCCESS"})
    assert inspect_b4_audit(tmp_path, "session2") == {
        "status": "AUDIT_VERIFIED", "records": 2, "attempts": 1,
        "last_event_status": "RECORDED_OUTCOME", "any_mutation_attempt": True,
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


def test_later_unrelated_outcome_cannot_clear_earlier_attempt(tmp_path):
    with B4AuditJournal(tmp_path, "uncertain") as journal:
        journal({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
        journal({"operation": "STATUS", "outcome": "SUCCESS"})
    result = inspect_b4_audit(tmp_path, "uncertain")
    assert result["status"] == "AUDIT_VERIFIED"
    assert result["last_event_status"] == "RECORDED_OUTCOME"
    assert result["any_mutation_attempt"] is True
    assert result["attempts"] == 1


def test_journal_without_mutation_attempt_has_no_attempt_indicator(tmp_path):
    with B4AuditJournal(tmp_path, "readonly") as journal:
        journal({"operation": "AUTH", "outcome": "DENIED"})
        journal({"operation": "STATUS", "outcome": "NOT_FOUND"})
    result = inspect_b4_audit(tmp_path, "readonly")
    assert result["status"] == "AUDIT_VERIFIED"
    assert result["any_mutation_attempt"] is False
    assert result["attempts"] == 0


def test_unverified_journal_attempt_state_is_unknown(tmp_path):
    missing = inspect_b4_audit(tmp_path, "absent")
    assert missing["status"] == "AUDIT_UNVERIFIED"
    assert missing["any_mutation_attempt"] is None
    path = tmp_path / "csl-b4-audit-damaged.jsonl"
    path.write_bytes(b'{"operation":"JOB_SUBMIT","outcome":"ATTEMPT"}')
    damaged = inspect_b4_audit(tmp_path, "damaged")
    assert damaged["status"] == "AUDIT_UNVERIFIED"
    assert damaged["any_mutation_attempt"] is None



def test_audit_snapshot_raced_inode_metadata_fails_closed(tmp_path, monkeypatch):
    import os
    from crypto_strategy_lab import browser_release_audit_verify as verifier

    with B4AuditJournal(tmp_path, "raced") as journal:
        journal({"operation": "JOB_SUBMIT", "outcome": "ATTEMPT"})
    untouched = journal.path.read_bytes()
    real_fstat = os.fstat
    calls = 0

    def changed_metadata(fd):
        nonlocal calls
        calls += 1
        info = real_fstat(fd)
        if calls == 2:
            # Simulate an appended/rewritten journal racing the snapshot.
            class ChangedStat:
                st_dev = info.st_dev
                st_ino = info.st_ino
                st_size = info.st_size
                st_mtime_ns = info.st_mtime_ns + 1
                st_ctime_ns = info.st_ctime_ns
                st_mode = info.st_mode
            return ChangedStat()
        return info

    monkeypatch.setattr(verifier.os, "fstat", changed_metadata)
    result = verifier.inspect_b4_audit(tmp_path, "raced")
    assert result["status"] == "AUDIT_UNVERIFIED"
    assert result["any_mutation_attempt"] is None
    assert calls >= 2
    assert journal.path.read_bytes() == untouched


def test_replaced_named_journal_is_unverified(tmp_path, monkeypatch):
    import os
    from crypto_strategy_lab import browser_release_audit_verify as verifier

    with B4AuditJournal(tmp_path, "swap") as journal:
        journal({"operation": "AUTH", "outcome": "DENIED"})
    path = journal.path
    original_open = os.open
    swapped = False

    def replace_before_path_recheck(target, flags, *args, **kwargs):
        nonlocal swapped
        if str(target) == str(path) and not swapped:
            swapped = True
            replacement = tmp_path / "replacement.jsonl"
            replacement.write_bytes(
                b'{"operation":"JOB_SUBMIT","outcome":"ATTEMPT"}\\n'
            )
            os.replace(replacement, path)
        return original_open(target, flags, *args, **kwargs)

    # Swap only on the SECOND open, after the first descriptor is secured.
    opens = 0
    def open_with_swap(target, flags, *args, **kwargs):
        nonlocal opens
        if str(target) == str(path):
            opens += 1
            if opens == 2:
                return replace_before_path_recheck(target, flags, *args, **kwargs)
        return original_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "open", open_with_swap)
    result = verifier.inspect_b4_audit(tmp_path, "swap")
    assert swapped
    assert result["status"] == "AUDIT_UNVERIFIED"
    assert result["any_mutation_attempt"] is None
