"""Restricted persistent state store for causal walk-forward research.

The store deliberately exposes only named Markdown snapshots plus a derived JSONL
audit log beneath one fixed directory. It is not a general-purpose filesystem API.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4


_STATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
_MAX_EVENT_BYTES = 64 * 1024
_MAX_RECENT_EVENTS = 200


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WalkForwardStateStore:
    """Persist bounded walk-forward state without exposing arbitrary file writes."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_state_id(state_id: str) -> str:
        value = str(state_id).strip()
        if not _STATE_ID.fullmatch(value):
            raise ValueError(
                "state_id must be 1-128 characters using only letters, numbers, '_' or '-', "
                "and must start with a letter or number"
            )
        return value

    @staticmethod
    def _validate_markdown(markdown: str) -> str:
        if not isinstance(markdown, str):
            raise ValueError("markdown must be a string")
        size = len(markdown.encode("utf-8"))
        if size > _MAX_MARKDOWN_BYTES:
            raise ValueError(f"markdown exceeds {_MAX_MARKDOWN_BYTES} bytes")
        return markdown

    @staticmethod
    def _validate_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
        if event is None:
            return None
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        value = deepcopy(event)
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("event must be JSON-serializable") from exc
        if len(encoded.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError(f"event exceeds {_MAX_EVENT_BYTES} bytes")
        return value

    def _paths(self, state_id: str) -> tuple[str, Path, Path]:
        value = self._validate_state_id(state_id)
        state_path = self.root / f"{value}_state.md"
        event_path = self.root / f"{value}_events.jsonl"
        return value, state_path, event_path

    def _assert_safe_target(self, path: Path, *, must_exist: bool) -> None:
        if path.parent.resolve() != self.root:
            raise ValueError("walk-forward path escapes the allowed state directory")
        if path.is_symlink():
            raise ValueError("symlinked walk-forward state files are not allowed")
        if must_exist:
            if not path.is_file():
                raise ValueError(f"walk-forward state does not exist: {path.stem}")
        elif path.exists() and not path.is_file():
            raise ValueError("walk-forward state target is not a regular file")

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _append_record(self, event_path: Path, record: dict[str, Any]) -> None:
        self._assert_safe_target(event_path, must_exist=False)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(line.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError(f"audit record exceeds {_MAX_EVENT_BYTES} bytes")
        with event_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _recent_events(self, event_path: Path, limit: int) -> list[dict[str, Any]]:
        if limit == 0 or not event_path.exists():
            return []
        self._assert_safe_target(event_path, must_exist=True)
        with event_path.open("r", encoding="utf-8") as handle:
            lines = deque(handle, maxlen=limit)
        return [json.loads(line) for line in lines if line.strip()]

    def create(
        self,
        state_id: str,
        markdown: str,
        initial_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one canonical Markdown state and its audit log; never overwrite."""
        markdown = self._validate_markdown(markdown)
        initial_event = self._validate_event(initial_event)
        value, state_path, event_path = self._paths(state_id)
        with self._lock:
            self._assert_safe_target(state_path, must_exist=False)
            self._assert_safe_target(event_path, must_exist=False)
            if state_path.exists() or event_path.exists():
                raise ValueError(f"walk-forward state already exists: {value}")
            digest = _sha256_text(markdown)
            self._atomic_write_text(state_path, markdown)
            self._append_record(
                event_path,
                {
                    "kind": "STATE_CREATED",
                    "recorded_at": _utc_now(),
                    "state_id": value,
                    "state_sha256": digest,
                    "event": initial_event,
                },
            )
            return {
                "state_id": value,
                "state_file": state_path.name,
                "event_file": event_path.name,
                "sha256": digest,
                "bytes": len(markdown.encode("utf-8")),
            }

    def read(self, state_id: str, recent_events: int = 50) -> dict[str, Any]:
        """Read the canonical Markdown snapshot and a bounded tail of audit events."""
        if isinstance(recent_events, bool) or not isinstance(recent_events, int):
            raise ValueError("recent_events must be an integer")
        if not 0 <= recent_events <= _MAX_RECENT_EVENTS:
            raise ValueError(f"recent_events must be between 0 and {_MAX_RECENT_EVENTS}")
        value, state_path, event_path = self._paths(state_id)
        with self._lock:
            self._assert_safe_target(state_path, must_exist=True)
            markdown = state_path.read_text(encoding="utf-8")
            return {
                "state_id": value,
                "state_file": state_path.name,
                "event_file": event_path.name,
                "sha256": _sha256_text(markdown),
                "bytes": len(markdown.encode("utf-8")),
                "markdown": markdown,
                "recent_events": self._recent_events(event_path, recent_events),
            }

    def update(
        self,
        state_id: str,
        markdown: str,
        expected_sha256: str,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically replace the snapshot only if the caller read the current version."""
        markdown = self._validate_markdown(markdown)
        event = self._validate_event(event)
        expected = str(expected_sha256).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("expected_sha256 must be a 64-character SHA-256 hex digest")
        value, state_path, event_path = self._paths(state_id)
        with self._lock:
            self._assert_safe_target(state_path, must_exist=True)
            before = state_path.read_text(encoding="utf-8")
            before_hash = _sha256_text(before)
            if before_hash != expected:
                raise ValueError(
                    "walk-forward state changed since it was read; read the state again before updating"
                )
            after_hash = _sha256_text(markdown)
            self._atomic_write_text(state_path, markdown)
            self._append_record(
                event_path,
                {
                    "kind": "STATE_UPDATED",
                    "recorded_at": _utc_now(),
                    "state_id": value,
                    "before_sha256": before_hash,
                    "state_sha256": after_hash,
                    "event": event,
                },
            )
            return {
                "state_id": value,
                "state_file": state_path.name,
                "event_file": event_path.name,
                "previous_sha256": before_hash,
                "sha256": after_hash,
                "bytes": len(markdown.encode("utf-8")),
            }

    def append_event(self, state_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Append one immutable audit event linked to the current Markdown hash."""
        payload = self._validate_event(event)
        assert payload is not None
        value, state_path, event_path = self._paths(state_id)
        with self._lock:
            self._assert_safe_target(state_path, must_exist=True)
            markdown = state_path.read_text(encoding="utf-8")
            digest = _sha256_text(markdown)
            self._append_record(
                event_path,
                {
                    "kind": "EVENT",
                    "recorded_at": _utc_now(),
                    "state_id": value,
                    "state_sha256": digest,
                    "event": payload,
                },
            )
            return {
                "state_id": value,
                "event_file": event_path.name,
                "state_sha256": digest,
                "appended": True,
            }
