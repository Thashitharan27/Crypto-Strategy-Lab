"""Event-sourced causal walk-forward experiment persistence.

This module is intentionally separate from the legacy Markdown walk-forward store.
The JSONL event stream is authoritative; any human-readable Markdown view can be
regenerated from the immutable experiment definition and events.
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


_SCHEMA_VERSION = 1
_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_EVENT_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 512 * 1024
_MAX_EVENT_BYTES = 128 * 1024
_MAX_RECENT_EVENTS = 500

REQUIRED_DEFINITION_FIELDS = {
    "symbol",
    "strategy_timeframe",
    "strategy",
    "stop_loss",
    "take_profit",
    "regime_method",
    "risk_model",
    "reference_run",
}

KNOWN_EVENT_TYPES = {
    "WF_CREATED",
    "TEACHER_RESOLVED",
    "CANDIDATE_CONTEXT_CAPTURED",
    "FEATURE_CONTEXT_INVALID",
    "DECISION_FROZEN",
    "OUTCOME_REVEALED",
    "TRADE_ENTERED",
    "TRADE_RESOLVED",
    "ENTRY_HYPOTHESIS_CREATED",
    "VETO_HYPOTHESIS_CREATED",
    "FLIP_HYPOTHESIS_CREATED",
    "HYPOTHESIS_REJECTED",
    "ENTRY_LEARNED",
    "ENTRY_REFINED",
    "VETO_LEARNED",
    "FLIP_LEARNED",
    "REVIEW_COMPLETED",
    "RULE_PROMOTED_TO_SHADOW",
    "RULE_PROMOTED_TO_LIVE",
    "RULE_RETIRED",
    "PHASE_CHANGED",
    "CHECKPOINT_CREATED",
    "MIGRATION_RECORDED",
}

RULE_EVENT_TYPES = {
    "ENTRY_LEARNED",
    "ENTRY_REFINED",
    "VETO_LEARNED",
    "FLIP_LEARNED",
}

PHASES = {"RESEARCH_WF", "VALIDATED", "SHADOW", "LIVE", "RETIRED"}
RULE_DEPLOYMENT_STATUSES = {"RESEARCH_ONLY", "SHADOW", "LIVE_ACTIVE", "RETIRED"}
LEDGERS = {"RESEARCH", "SHADOW", "LIVE"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_iso(value: str, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} cannot be empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 date/time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat()


def _json_object(value: Any, name: str, max_bytes: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    cloned = deepcopy(value)
    try:
        encoded = _canonical_json(cloned)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} exceeds {max_bytes} bytes")
    return cloned


class CausalExperimentStore:
    """Append-only event store for repeatable causal strategy experiments."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_experiment_id(experiment_id: str) -> str:
        value = str(experiment_id).strip()
        if not _EXPERIMENT_ID.fullmatch(value):
            raise ValueError(
                "experiment_id must be 1-160 characters using letters, numbers, '_', '-', or '.', "
                "and must start with a letter or number"
            )
        return value

    @staticmethod
    def _validate_operation_id(operation_id: str) -> str:
        value = str(operation_id).strip()
        if not _OPERATION_ID.fullmatch(value):
            raise ValueError(
                "operation_id must be 1-160 characters using letters, numbers, '_', '-', '.', or ':'"
            )
        return value

    @staticmethod
    def _validate_definition(definition: dict[str, Any]) -> dict[str, Any]:
        value = _json_object(definition, "definition", _MAX_MANIFEST_BYTES)
        missing = sorted(REQUIRED_DEFINITION_FIELDS - set(value))
        if missing:
            raise ValueError(f"definition is missing required fields: {', '.join(missing)}")
        for key in REQUIRED_DEFINITION_FIELDS:
            if value[key] in (None, "", [], {}):
                raise ValueError(f"definition field cannot be empty: {key}")
        if "initial_equity" in value:
            equity = float(value["initial_equity"])
            if equity <= 0:
                raise ValueError("initial_equity must be positive")
        if "risk_pct" in value:
            risk_pct = float(value["risk_pct"])
            if not 0 < risk_pct <= 100:
                raise ValueError("risk_pct must be greater than 0 and at most 100")
        return value

    @staticmethod
    def _validate_event_type(event_type: str) -> str:
        value = str(event_type).strip().upper()
        if not _EVENT_TYPE.fullmatch(value):
            raise ValueError("event_type must be upper snake case")
        if value not in KNOWN_EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {value}")
        return value

    def _dir(self, experiment_id: str) -> tuple[str, Path]:
        value = self._validate_experiment_id(experiment_id)
        path = self.root / value
        return value, path

    def _paths(self, experiment_id: str) -> tuple[str, Path, Path, Path]:
        value, directory = self._dir(experiment_id)
        return value, directory, directory / "manifest.json", directory / "events.jsonl"

    def _assert_safe_dir(self, directory: Path, *, must_exist: bool) -> None:
        if directory.parent.resolve() != self.root:
            raise ValueError("experiment path escapes the allowed experiment directory")
        if directory.is_symlink():
            raise ValueError("symlinked experiment directories are not allowed")
        if must_exist and not directory.is_dir():
            raise ValueError(f"causal experiment does not exist: {directory.name}")
        if not must_exist and directory.exists() and not directory.is_dir():
            raise ValueError("experiment target is not a directory")

    @staticmethod
    def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
        temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
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

    @staticmethod
    def _event_hash(record_without_hash: dict[str, Any]) -> str:
        return _sha256_json(record_without_hash)

    def _append_record(self, events_path: Path, record: dict[str, Any]) -> None:
        line = _canonical_json(record)
        if len(line.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError(f"event exceeds {_MAX_EVENT_BYTES} bytes")
        with events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_all_events(events_path: Path) -> list[dict[str, Any]]:
        if not events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with events_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid causal event JSON at line {line_number}") from exc
                events.append(event)
        return events

    @staticmethod
    def _verify_chain(events: list[dict[str, Any]]) -> tuple[int, str]:
        previous_hash = "0" * 64
        expected_sequence = 1
        for event in events:
            if event.get("sequence") != expected_sequence:
                raise ValueError("causal experiment event sequence is corrupted")
            if event.get("previous_state_hash") != previous_hash:
                raise ValueError("causal experiment hash chain is corrupted")
            stored_hash = event.get("resulting_state_hash")
            without_hash = dict(event)
            without_hash.pop("resulting_state_hash", None)
            computed_hash = _sha256_json(without_hash)
            if stored_hash != computed_hash:
                raise ValueError("causal experiment event hash is corrupted")
            previous_hash = stored_hash
            expected_sequence += 1
        return len(events), previous_hash

    @staticmethod
    def _find_operation(events: list[dict[str, Any]], operation_id: str) -> dict[str, Any] | None:
        for event in events:
            if event.get("operation_id") == operation_id:
                return event
        return None

    @staticmethod
    def _candidate_state(events: list[dict[str, Any]], candidate_id: str) -> str:
        state = "UNSEEN"
        for event in events:
            payload = event.get("payload") or {}
            if payload.get("candidate_id") != candidate_id:
                continue
            event_type = event.get("event_type")
            if event_type == "CANDIDATE_CONTEXT_CAPTURED":
                state = "ENTRY_CONTEXT_CAPTURED"
            elif event_type == "FEATURE_CONTEXT_INVALID":
                state = "INVALID"
            elif event_type == "DECISION_FROZEN":
                state = "DECISION_FROZEN"
            elif event_type == "OUTCOME_REVEALED":
                state = "OUTCOME_REVEALED"
            elif event_type == "TRADE_RESOLVED":
                state = "COMPLETE"
        return state

    @classmethod
    def _validate_event_semantics(
        cls,
        events: list[dict[str, Any]],
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if event_type in {
            "CANDIDATE_CONTEXT_CAPTURED",
            "FEATURE_CONTEXT_INVALID",
            "DECISION_FROZEN",
            "OUTCOME_REVEALED",
            "TRADE_ENTERED",
        }:
            candidate_id = str(payload.get("candidate_id", "")).strip()
            if not candidate_id:
                raise ValueError(f"{event_type} requires payload.candidate_id")
            current = cls._candidate_state(events, candidate_id)
            if event_type == "CANDIDATE_CONTEXT_CAPTURED" and current != "UNSEEN":
                raise ValueError(f"candidate {candidate_id} has already been captured")
            if event_type == "FEATURE_CONTEXT_INVALID" and current != "ENTRY_CONTEXT_CAPTURED":
                raise ValueError("feature invalidation requires captured candidate context")
            if event_type == "DECISION_FROZEN" and current != "ENTRY_CONTEXT_CAPTURED":
                raise ValueError("decision can only be frozen after candidate context is captured")
            if event_type == "OUTCOME_REVEALED" and current != "DECISION_FROZEN":
                raise ValueError("outcome cannot be revealed before a decision is frozen")
            if event_type == "TRADE_ENTERED" and current not in {"DECISION_FROZEN", "OUTCOME_REVEALED"}:
                raise ValueError("trade entry requires a frozen decision")

        if event_type == "TRADE_RESOLVED":
            candidate_id = str(payload.get("candidate_id", "")).strip()
            if candidate_id:
                current = cls._candidate_state(events, candidate_id)
                if current not in {"DECISION_FROZEN", "OUTCOME_REVEALED"}:
                    raise ValueError("prospective trade resolution requires a frozen decision")
            ledger = str(payload.get("ledger", "RESEARCH")).upper()
            if ledger not in LEDGERS:
                raise ValueError(f"ledger must be one of: {', '.join(sorted(LEDGERS))}")

        if event_type in RULE_EVENT_TYPES:
            required = {"rule_id", "rule_version", "effective_from", "reason", "evidence_source"}
            missing = sorted(key for key in required if payload.get(key) in (None, ""))
            if missing:
                raise ValueError(f"{event_type} missing rule metadata: {', '.join(missing)}")
            _parse_iso(str(payload["effective_from"]), "payload.effective_from")
            if event_type == "ENTRY_REFINED" and payload.get("supersedes_version") in (None, ""):
                raise ValueError("ENTRY_REFINED requires payload.supersedes_version")

        if event_type in {"RULE_PROMOTED_TO_SHADOW", "RULE_PROMOTED_TO_LIVE", "RULE_RETIRED"}:
            if payload.get("rule_id") in (None, "") or payload.get("rule_version") in (None, ""):
                raise ValueError(f"{event_type} requires payload.rule_id and payload.rule_version")

        if event_type == "PHASE_CHANGED":
            phase = str(payload.get("phase", "")).upper()
            if phase not in PHASES:
                raise ValueError(f"phase must be one of: {', '.join(sorted(PHASES))}")

    @staticmethod
    def _derive_state(manifest: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        phase = str(manifest.get("initial_phase", "RESEARCH_WF"))
        rules: dict[str, dict[str, Any]] = {}
        candidates: dict[str, str] = {}
        ledgers: dict[str, dict[str, Any]] = {
            "RESEARCH": {"equity": manifest.get("definition", {}).get("initial_equity")},
            "SHADOW": {"equity": None},
            "LIVE": {"equity": None},
        }
        last_review: dict[str, Any] | None = None

        for event in events:
            event_type = event.get("event_type")
            payload = event.get("payload") or {}
            candidate_id = payload.get("candidate_id")
            if candidate_id:
                if event_type == "CANDIDATE_CONTEXT_CAPTURED":
                    candidates[str(candidate_id)] = "ENTRY_CONTEXT_CAPTURED"
                elif event_type == "FEATURE_CONTEXT_INVALID":
                    candidates[str(candidate_id)] = "INVALID"
                elif event_type == "DECISION_FROZEN":
                    candidates[str(candidate_id)] = "DECISION_FROZEN"
                elif event_type == "OUTCOME_REVEALED":
                    candidates[str(candidate_id)] = "OUTCOME_REVEALED"
                elif event_type == "TRADE_RESOLVED":
                    candidates[str(candidate_id)] = "COMPLETE"

            if event_type == "PHASE_CHANGED":
                phase = str(payload["phase"]).upper()

            if event_type in RULE_EVENT_TYPES:
                key = f"{payload['rule_id']}@{payload['rule_version']}"
                rules[key] = {
                    "rule_id": payload["rule_id"],
                    "rule_version": payload["rule_version"],
                    "family": event_type.split("_", 1)[0],
                    "effective_from": payload["effective_from"],
                    "evidence_source": payload["evidence_source"],
                    "deployment_status": "RESEARCH_ONLY",
                    "learned_sequence": event["sequence"],
                    "supersedes_version": payload.get("supersedes_version"),
                }

            if event_type in {"RULE_PROMOTED_TO_SHADOW", "RULE_PROMOTED_TO_LIVE", "RULE_RETIRED"}:
                key = f"{payload['rule_id']}@{payload['rule_version']}"
                if key in rules:
                    status = {
                        "RULE_PROMOTED_TO_SHADOW": "SHADOW",
                        "RULE_PROMOTED_TO_LIVE": "LIVE_ACTIVE",
                        "RULE_RETIRED": "RETIRED",
                    }[event_type]
                    rules[key]["deployment_status"] = status

            if event_type == "TRADE_RESOLVED":
                ledger = str(payload.get("ledger", "RESEARCH")).upper()
                if "equity_after" in payload:
                    ledgers[ledger]["equity"] = payload["equity_after"]
                ledgers[ledger]["last_trade_sequence"] = event["sequence"]

            if event_type == "REVIEW_COMPLETED":
                last_review = {
                    "sequence": event["sequence"],
                    "effective_market_time": event.get("effective_market_time"),
                    "payload": payload,
                }

        return {
            "phase": phase,
            "rules": rules,
            "candidate_states": candidates,
            "ledgers": ledgers,
            "last_review": last_review,
        }

    def create(
        self,
        experiment_id: str,
        definition: dict[str, Any],
        operation_id: str,
        *,
        initial_phase: str = "RESEARCH_WF",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create an immutable experiment definition and the first WF_CREATED event."""
        definition = self._validate_definition(definition)
        operation_id = self._validate_operation_id(operation_id)
        phase = str(initial_phase).strip().upper()
        if phase not in PHASES:
            raise ValueError(f"initial_phase must be one of: {', '.join(sorted(PHASES))}")
        value, directory, manifest_path, events_path = self._paths(experiment_id)
        with self._lock:
            self._assert_safe_dir(directory, must_exist=False)
            if directory.exists():
                raise ValueError(f"causal experiment already exists: {value}")
            directory.mkdir(parents=False, exist_ok=False)
            manifest = {
                "schema_version": _SCHEMA_VERSION,
                "experiment_id": value,
                "created_at": _utc_now(),
                "initial_phase": phase,
                "definition": definition,
                "definition_sha256": _sha256_json(definition),
                "notes": notes,
            }
            encoded_manifest = _canonical_json(manifest)
            if len(encoded_manifest.encode("utf-8")) > _MAX_MANIFEST_BYTES:
                directory.rmdir()
                raise ValueError(f"manifest exceeds {_MAX_MANIFEST_BYTES} bytes")
            self._atomic_write_json(manifest_path, manifest)

            recorded_at = _utc_now()
            base_event = {
                "schema_version": _SCHEMA_VERSION,
                "event_id": uuid4().hex,
                "sequence": 1,
                "experiment_id": value,
                "event_type": "WF_CREATED",
                "operation_id": operation_id,
                "recorded_at": recorded_at,
                "event_time": recorded_at,
                "effective_market_time": None,
                "previous_state_hash": "0" * 64,
                "source": "SYSTEM",
                "payload": {
                    "definition_sha256": manifest["definition_sha256"],
                    "initial_phase": phase,
                },
            }
            base_event["resulting_state_hash"] = self._event_hash(base_event)
            self._append_record(events_path, base_event)
            return {
                "experiment_id": value,
                "definition_sha256": manifest["definition_sha256"],
                "sequence": 1,
                "state_hash": base_event["resulting_state_hash"],
                "phase": phase,
            }

    def read(self, experiment_id: str, recent_events: int = 100) -> dict[str, Any]:
        """Read immutable definition, verified chain head, derived state, and recent events."""
        if isinstance(recent_events, bool) or not isinstance(recent_events, int):
            raise ValueError("recent_events must be an integer")
        if not 0 <= recent_events <= _MAX_RECENT_EVENTS:
            raise ValueError(f"recent_events must be between 0 and {_MAX_RECENT_EVENTS}")
        value, directory, manifest_path, events_path = self._paths(experiment_id)
        with self._lock:
            self._assert_safe_dir(directory, must_exist=True)
            if manifest_path.is_symlink() or events_path.is_symlink():
                raise ValueError("symlinked experiment files are not allowed")
            if not manifest_path.is_file() or not events_path.is_file():
                raise ValueError("causal experiment files are incomplete")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("experiment_id") != value:
                raise ValueError("experiment manifest identity mismatch")
            if manifest.get("definition_sha256") != _sha256_json(manifest.get("definition")):
                raise ValueError("experiment definition hash mismatch")
            events = self._read_all_events(events_path)
            sequence, state_hash = self._verify_chain(events)
            tail = events[-recent_events:] if recent_events else []
            return {
                "experiment_id": value,
                "manifest": manifest,
                "sequence": sequence,
                "state_hash": state_hash,
                "derived_state": self._derive_state(manifest, events),
                "recent_events": tail,
            }

    def list_experiments(self) -> list[dict[str, Any]]:
        """List experiment identities without exposing arbitrary directory traversal."""
        rows: list[dict[str, Any]] = []
        with self._lock:
            for directory in sorted(self.root.iterdir(), key=lambda p: p.name):
                if not directory.is_dir() or directory.is_symlink() or not _EXPERIMENT_ID.fullmatch(directory.name):
                    continue
                manifest_path = directory / "manifest.json"
                events_path = directory / "events.jsonl"
                if not manifest_path.is_file() or not events_path.is_file():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    events = self._read_all_events(events_path)
                    sequence, state_hash = self._verify_chain(events)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                rows.append(
                    {
                        "experiment_id": directory.name,
                        "created_at": manifest.get("created_at"),
                        "definition_sha256": manifest.get("definition_sha256"),
                        "symbol": (manifest.get("definition") or {}).get("symbol"),
                        "strategy_timeframe": (manifest.get("definition") or {}).get("strategy_timeframe"),
                        "sequence": sequence,
                        "state_hash": state_hash,
                        "phase": self._derive_state(manifest, events)["phase"],
                    }
                )
        return rows

    def append_event(
        self,
        experiment_id: str,
        event_type: str,
        payload: dict[str, Any],
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        *,
        effective_market_time: str | None = None,
        event_time: str | None = None,
        source: str = "CHATGPT_RESEARCH",
    ) -> dict[str, Any]:
        """Append one idempotent causal event after optimistic sequence/hash validation."""
        event_type = self._validate_event_type(event_type)
        payload = _json_object(payload, "payload", _MAX_EVENT_BYTES)
        operation_id = self._validate_operation_id(operation_id)
        if isinstance(expected_sequence, bool) or not isinstance(expected_sequence, int) or expected_sequence < 1:
            raise ValueError("expected_sequence must be a positive integer")
        expected_hash = str(expected_state_hash).strip().lower()
        if not _HASH.fullmatch(expected_hash):
            raise ValueError("expected_state_hash must be a 64-character SHA-256 hex digest")
        effective = (
            _parse_iso(effective_market_time, "effective_market_time")
            if effective_market_time is not None
            else None
        )
        occurred = _parse_iso(event_time, "event_time") if event_time is not None else _utc_now()
        source_value = str(source).strip().upper()
        if not source_value:
            raise ValueError("source cannot be empty")

        value, directory, manifest_path, events_path = self._paths(experiment_id)
        with self._lock:
            self._assert_safe_dir(directory, must_exist=True)
            if manifest_path.is_symlink() or events_path.is_symlink():
                raise ValueError("symlinked experiment files are not allowed")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events = self._read_all_events(events_path)
            sequence, state_hash = self._verify_chain(events)

            existing = self._find_operation(events, operation_id)
            if existing is not None:
                return {
                    "experiment_id": value,
                    "idempotent_replay": True,
                    "sequence": existing["sequence"],
                    "state_hash": existing["resulting_state_hash"],
                    "event": existing,
                }

            if sequence != expected_sequence or state_hash != expected_hash:
                raise ValueError(
                    "causal experiment changed since it was read; read it again before appending"
                )

            self._validate_event_semantics(events, event_type, payload)
            recorded_at = _utc_now()
            record = {
                "schema_version": _SCHEMA_VERSION,
                "event_id": uuid4().hex,
                "sequence": sequence + 1,
                "experiment_id": value,
                "event_type": event_type,
                "operation_id": operation_id,
                "recorded_at": recorded_at,
                "event_time": occurred,
                "effective_market_time": effective,
                "previous_state_hash": state_hash,
                "source": source_value,
                "payload": payload,
            }
            record["resulting_state_hash"] = self._event_hash(record)
            self._append_record(events_path, record)
            new_events = [*events, record]
            return {
                "experiment_id": value,
                "idempotent_replay": False,
                "sequence": record["sequence"],
                "previous_state_hash": state_hash,
                "state_hash": record["resulting_state_hash"],
                "event": record,
                "derived_state": self._derive_state(manifest, new_events),
            }
