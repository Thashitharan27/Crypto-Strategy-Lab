"""Read-only bounded verifier for isolated B4 operation/outcome audit journals.

A well-formed journal is NOT evidence of durable commit, native completion,
request identity, or request-to-run mapping. Never repair, truncate or replay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from crypto_strategy_lab.browser_release_audit import _OPERATIONS, _OUTCOMES
from crypto_strategy_lab.browser_release_preflight import _nonlink_canonical_directory

_SESSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_MAX_BYTES = 8 * 1024 * 1024
_MAX_RECORDS = 100_000


def inspect_b4_audit(root: Path, session_id: str) -> dict[str, str | int | bool | None]:
    """Read a single immutable snapshot; reject incomplete/corrupt evidence.

    No write, deletion, recovery decision or request ID is permitted. A
    verified journal proves only that its *currently readable* bytes match the
    bounded JSONL event contract, not that missing events were never emitted.
    """
    if not isinstance(session_id, str) or _SESSION.fullmatch(session_id) is None:
        raise ValueError("Unsafe B4 audit session ID")
    result: dict[str, str | int | bool | None] = {
        "status": "AUDIT_UNVERIFIED", "records": 0, "attempts": 0,
        "last_event_status": "UNKNOWN", "any_mutation_attempt": None,
    }
    try:
        directory = _nonlink_canonical_directory(Path(root))
        path = directory / ("csl-b4-audit-" + session_id + ".jsonl")
        if path.is_symlink():
            return result
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode) or not 0 < file_stat.st_size <= _MAX_BYTES:
                return result
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(_MAX_BYTES + 1)
            if len(data) != file_stat.st_size or not data.endswith(b"\n"):
                return result
            lines = data.splitlines()
            if not 0 < len(lines) <= _MAX_RECORDS:
                return result
            attempts = 0
            for line in lines:
                # The writer uses ASCII canonical JSON and a strict two-key schema.
                if len(line) > 128:
                    return result
                event = json.loads(line)
                if not isinstance(event, dict) or set(event) != {"operation", "outcome"}:
                    return result
                operation, outcome = event["operation"], event["outcome"]
                if not isinstance(operation, str) or operation not in _OPERATIONS:
                    return result
                if not isinstance(outcome, str) or outcome not in _OUTCOMES:
                    return result
                canonical = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("ascii")
                if line != canonical:
                    return result
                if outcome == "ATTEMPT":
                    if operation not in {"CONFIG_SAVE", "JOB_SUBMIT", "CANCEL"}:
                        return result
                    attempts += 1
            result["status"] = "AUDIT_VERIFIED"
            result["records"] = len(lines)
            result["attempts"] = attempts
            # Outcome rows have no request or operation correlation IDs. Even
            # a later SUCCESS cannot resolve an earlier ATTEMPT after a crash.
            result["any_mutation_attempt"] = attempts > 0
            result["last_event_status"] = "ATTEMPT_ONLY" if (
                json.loads(lines[-1])["outcome"] == "ATTEMPT"
            ) else "RECORDED_OUTCOME"
            return result
        finally:
            os.close(fd)
    except (OSError, ValueError, RuntimeError, TypeError, UnicodeError, json.JSONDecodeError):
        return result
