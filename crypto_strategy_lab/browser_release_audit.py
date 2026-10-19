"""Isolated B4 audit journal, for review only; no production release switch.

Records only bounded operation/outcome identifiers, never request IDs, user
payloads, native paths, tokens or errors. The caller must supply an already
validated isolated directory. This writer is not a substitute for a release
decision about what to do when HTTP callback persistence fails.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import threading

from crypto_strategy_lab.browser_release_preflight import _nonlink_canonical_directory

_OPERATIONS = frozenset({"AUTH", "STATUS", "PROGRESS", "CANCEL", "CONFIG_SAVE", "JOB_SUBMIT"})
_OUTCOMES = frozenset({
    "DENIED", "SUCCESS", "INVALID_ID", "NOT_FOUND", "UNAVAILABLE",
    "INVALID_INPUT", "OVERSIZED", "INVALID_CONFIG", "PERSISTENCE_FAILED",
    "REJECTED", "EXECUTION_UNAVAILABLE", "ATTEMPT",
})
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_MUTATION_OPERATIONS = frozenset({"CONFIG_SAVE", "JOB_SUBMIT", "CANCEL"})
_MAX_BYTES = 8 * 1024 * 1024
_MAX_RECORDS = 100_000


class B4AuditJournal:
    """Exclusive-create per-session journal; append, flush and fsync each event."""

    def __init__(self, root: Path, session_id: str):
        if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
            raise ValueError("Unsafe B4 audit session ID")
        directory = _nonlink_canonical_directory(Path(root))
        self.path = directory / ("csl-b4-audit-" + session_id + ".jsonl")
        self._lock = threading.Lock()
        self._fd: int | None = None
        self._broken = False
        self._records = 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Audit destination must be a regular file")
            os.fsync(fd)
            self._fd = fd
        except BaseException:
            os.close(fd)
            raise

    def __call__(self, event: dict) -> None:
        if not isinstance(event, dict) or set(event) != {"operation", "outcome"}:
            raise ValueError("Audit event must have only operation and outcome")
        operation, outcome = event["operation"], event["outcome"]
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise ValueError("Unknown audit operation")
        if not isinstance(outcome, str) or outcome not in _OUTCOMES:
            raise ValueError("Unknown audit outcome")
        if outcome == "ATTEMPT" and operation not in _MUTATION_OPERATIONS:
            raise ValueError("Audit ATTEMPT requires a mutation operation")
        line = (json.dumps({"operation": operation, "outcome": outcome},
                           sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        with self._lock:
            if self._fd is None:
                raise RuntimeError("B4 audit journal is closed")
            if self._broken:
                raise OSError("B4 audit journal previously failed")
            try:
                # Refuse a detached/replaced journal destination. An opened
                # descriptor alone cannot prove its named evidence path survives.
                opened = os.fstat(self._fd)
                named = os.stat(self.path, follow_symlinks=False)
                if (not stat.S_ISREG(named.st_mode)
                        or opened.st_dev != named.st_dev
                        or opened.st_ino != named.st_ino):
                    raise OSError("B4 audit destination identity changed")
                if opened.st_size + len(line) > _MAX_BYTES or self._records >= _MAX_RECORDS:
                    raise OSError("B4 audit capacity exhausted")
                offset = 0
                while offset < len(line):
                    count = os.write(self._fd, line[offset:])
                    if count <= 0:
                        raise OSError("B4 audit write made no progress")
                    offset += count
                os.fsync(self._fd)
                self._records += 1
    
            except (OSError, RuntimeError):
                # A partial write or failed fsync leaves uncertain evidence.
                # Never append further records to a compromised session.
                self._broken = True
                raise

    def available(self) -> bool:
        """Read-only live admission signal; no capacity reservation is implied."""
        with self._lock:
            if self._fd is None or self._broken:
                return False
            try:
                opened = os.fstat(self._fd)
                named = os.stat(self.path, follow_symlinks=False)
                if (not stat.S_ISREG(named.st_mode)
                        or opened.st_dev != named.st_dev or opened.st_ino != named.st_ino
                        or opened.st_size >= _MAX_BYTES or self._records >= _MAX_RECORDS):
                    self._broken = True
            except (OSError, RuntimeError):
                self._broken = True
            return not self._broken

    def close(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
            if fd is not None:
                os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
