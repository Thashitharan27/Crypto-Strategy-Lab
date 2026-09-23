"""Event-sourced causal walk-forward experiment persistence.

This module is intentionally separate from the legacy Markdown walk-forward store.
The JSONL event stream is authoritative; any human-readable Markdown view can be
regenerated from the immutable experiment definition and events.
"""
from __future__ import annotations

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

PHASES = {"BOOTSTRAP_RESEARCH", "RESEARCH_WF", "VALIDATED", "SHADOW", "LIVE", "RETIRED"}
LEDGERS = {"RESEARCH", "SHADOW", "LIVE"}
EVIDENCE_SOURCES = {"BOOTSTRAP", "TEACHER", "PROSPECTIVE_WF", "SHADOW", "LIVE"}
RESEARCH_PROTOCOL_MODES = {"COLD_START", "BOOTSTRAP_THEN_WF"}
RULE_UPDATE_MODES = {"TRADE_BY_TRADE", "MONTHLY_BATCH_OOS", "WEEKLY_BATCH_OOS"}

DEFAULT_PERIODIC_REVIEW_POLICY = {"initial_anchor": "REFERENCE_PERIOD_START"}
DEFAULT_RULE_UPDATE_POLICY = {"mode": "TRADE_BY_TRADE"}


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
        protocol = value.get("research_protocol")
        if protocol is not None:
            if not isinstance(protocol, dict):
                raise ValueError("research_protocol must be an object")
            mode = str(protocol.get("mode", "")).strip().upper()
            if mode not in RESEARCH_PROTOCOL_MODES:
                raise ValueError(
                    "research_protocol.mode must be COLD_START or BOOTSTRAP_THEN_WF"
                )
            protocol["mode"] = mode
            if mode == "BOOTSTRAP_THEN_WF":
                walk_forward_start = protocol.get("walk_forward_start")
                if walk_forward_start in (None, ""):
                    raise ValueError(
                        "BOOTSTRAP_THEN_WF requires research_protocol.walk_forward_start"
                    )
                protocol["walk_forward_start"] = _parse_iso(
                    str(walk_forward_start), "research_protocol.walk_forward_start"
                )
                bootstrap_start = protocol.get("bootstrap_start")
                if bootstrap_start not in (None, ""):
                    protocol["bootstrap_start"] = _parse_iso(
                        str(bootstrap_start), "research_protocol.bootstrap_start"
                    )
                    if protocol["bootstrap_start"] >= protocol["walk_forward_start"]:
                        raise ValueError(
                            "research_protocol.bootstrap_start must be before walk_forward_start"
                        )
        policy = value.get("periodic_review_policy")
        if policy is not None:
            if not isinstance(policy, dict):
                raise ValueError("periodic_review_policy must be an object")
            anchor = str(policy.get("initial_anchor", "")).strip().upper()
            if anchor not in {"REFERENCE_PERIOD_START", "WALK_FORWARD_START", "MANUAL"}:
                raise ValueError(
                    "periodic_review_policy.initial_anchor must be "
                    "REFERENCE_PERIOD_START, WALK_FORWARD_START, or MANUAL"
                )
            if anchor == "WALK_FORWARD_START":
                mode = str(((value.get("research_protocol") or {}).get("mode", ""))).upper()
                if mode != "BOOTSTRAP_THEN_WF":
                    raise ValueError(
                        "WALK_FORWARD_START periodic anchor requires BOOTSTRAP_THEN_WF"
                    )
            policy["initial_anchor"] = anchor

        rule_update_policy = value.get("rule_update_policy")
        if rule_update_policy is not None:
            if not isinstance(rule_update_policy, dict):
                raise ValueError("rule_update_policy must be an object")
            mode = str(rule_update_policy.get("mode", "")).strip().upper()
            if mode not in RULE_UPDATE_MODES:
                raise ValueError(
                    "rule_update_policy.mode must be TRADE_BY_TRADE, MONTHLY_BATCH_OOS, or WEEKLY_BATCH_OOS"
                )
            rule_update_policy["mode"] = mode
            if mode in {"MONTHLY_BATCH_OOS", "WEEKLY_BATCH_OOS"}:
                interval_key = (
                    "interval_months"
                    if mode == "MONTHLY_BATCH_OOS"
                    else "interval_weeks"
                )
                other_interval_key = (
                    "interval_weeks"
                    if mode == "MONTHLY_BATCH_OOS"
                    else "interval_months"
                )
                interval = rule_update_policy.get(interval_key, 1)
                if isinstance(interval, bool):
                    raise ValueError(f"{mode} {interval_key} must be 1")
                try:
                    interval = int(interval)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{mode} {interval_key} must be 1") from exc
                if interval != 1:
                    raise ValueError(f"{mode} {interval_key} must be 1")
                freeze = rule_update_policy.get("freeze_between_reviews", True)
                if freeze is not True:
                    raise ValueError(
                        f"{mode} requires freeze_between_reviews=true"
                    )
                rule_update_policy[interval_key] = 1
                rule_update_policy.pop(other_interval_key, None)
                rule_update_policy["freeze_between_reviews"] = True
            else:
                rule_update_policy.pop("interval_months", None)
                rule_update_policy.pop("interval_weeks", None)
                rule_update_policy.pop("freeze_between_reviews", None)

            adaptive = rule_update_policy.get("adaptive", False)
            if not isinstance(adaptive, bool):
                raise ValueError("rule_update_policy.adaptive must be boolean")
            adaptive_keys = {
                "primary_lookback_weeks",
                "context_lookback_weeks",
                "expire_unconfirmed_after_weeks",
                "benchmark_raw_strategy",
                "track_adaptation_lag",
                "track_rule_half_life",
            }
            if adaptive:
                if mode != "WEEKLY_BATCH_OOS":
                    raise ValueError(
                        "adaptive rule updates require rule_update_policy.mode=WEEKLY_BATCH_OOS"
                    )
                numeric_defaults = {
                    "primary_lookback_weeks": 4,
                    "context_lookback_weeks": 12,
                    "expire_unconfirmed_after_weeks": 12,
                }
                normalized_numeric: dict[str, int] = {}
                for key, default in numeric_defaults.items():
                    raw = rule_update_policy.get(key, default)
                    if isinstance(raw, bool):
                        raise ValueError(f"rule_update_policy.{key} must be an integer")
                    try:
                        number = int(raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"rule_update_policy.{key} must be an integer"
                        ) from exc
                    if number < 1 or number > 104:
                        raise ValueError(
                            f"rule_update_policy.{key} must be between 1 and 104"
                        )
                    normalized_numeric[key] = number
                if (
                    normalized_numeric["context_lookback_weeks"]
                    < normalized_numeric["primary_lookback_weeks"]
                ):
                    raise ValueError(
                        "context_lookback_weeks must be >= primary_lookback_weeks"
                    )
                rule_update_policy.update(normalized_numeric)
                for key in (
                    "benchmark_raw_strategy",
                    "track_adaptation_lag",
                    "track_rule_half_life",
                ):
                    raw = rule_update_policy.get(key, True)
                    if not isinstance(raw, bool):
                        raise ValueError(f"rule_update_policy.{key} must be boolean")
                    rule_update_policy[key] = raw
                rule_update_policy["adaptive"] = True
            else:
                rule_update_policy["adaptive"] = False
                for key in adaptive_keys:
                    rule_update_policy.pop(key, None)
        return value

    @staticmethod
    def _validate_event_type(event_type: str) -> str:
        value = str(event_type).strip().upper()
        if not _EVENT_TYPE.fullmatch(value):
            raise ValueError("event_type must be upper snake case")
        if value not in KNOWN_EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {value}")
        if value == "WF_CREATED":
            raise ValueError("WF_CREATED is emitted only by create_walk_forward_experiment")
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

    @staticmethod
    def _rule_versions(events: list[dict[str, Any]]) -> set[tuple[str, str]]:
        versions: set[tuple[str, str]] = set()
        for event in events:
            if event.get("event_type") not in RULE_EVENT_TYPES:
                continue
            payload = event.get("payload") or {}
            versions.add((str(payload.get("rule_id")), str(payload.get("rule_version"))))
        return versions

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
            if event_type == "CANDIDATE_CONTEXT_CAPTURED":
                if current != "UNSEEN":
                    raise ValueError(f"candidate {candidate_id} has already been captured")
                if not str(payload.get("feature_hash", "")).strip():
                    raise ValueError("CANDIDATE_CONTEXT_CAPTURED requires payload.feature_hash")
            if event_type == "FEATURE_CONTEXT_INVALID" and current != "ENTRY_CONTEXT_CAPTURED":
                raise ValueError("feature invalidation requires captured candidate context")
            if event_type == "DECISION_FROZEN":
                if current != "ENTRY_CONTEXT_CAPTURED":
                    raise ValueError("decision can only be frozen after candidate context is captured")
                missing = [
                    key
                    for key in ("final_action", "state_hash_at_decision")
                    if payload.get(key) in (None, "")
                ]
                if missing:
                    raise ValueError(
                        "DECISION_FROZEN missing required fields: " + ", ".join(missing)
                    )
            if event_type == "OUTCOME_REVEALED" and current != "DECISION_FROZEN":
                raise ValueError("outcome cannot be revealed before a decision is frozen")
            if event_type == "TRADE_ENTERED" and current not in {"DECISION_FROZEN", "OUTCOME_REVEALED"}:
                raise ValueError("trade entry requires a frozen decision")

        if event_type == "TRADE_RESOLVED":
            candidate_id = str(payload.get("candidate_id", "")).strip()
            if candidate_id:
                current = cls._candidate_state(events, candidate_id)
                if current != "OUTCOME_REVEALED":
                    raise ValueError("prospective trade resolution requires a revealed outcome")
            ledger = str(payload.get("ledger", "RESEARCH")).upper()
            if ledger not in LEDGERS:
                raise ValueError(f"ledger must be one of: {', '.join(sorted(LEDGERS))}")

        if event_type in RULE_EVENT_TYPES:
            required = {"rule_id", "rule_version", "effective_from", "reason", "evidence_source"}
            missing = sorted(key for key in required if payload.get(key) in (None, ""))
            if missing:
                raise ValueError(f"{event_type} missing rule metadata: {', '.join(missing)}")
            _parse_iso(str(payload["effective_from"]), "payload.effective_from")
            evidence_source = str(payload["evidence_source"]).upper()
            if evidence_source not in EVIDENCE_SOURCES:
                raise ValueError(
                    f"evidence_source must be one of: {', '.join(sorted(EVIDENCE_SOURCES))}"
                )
            existing_versions = cls._rule_versions(events)
            key = (str(payload["rule_id"]), str(payload["rule_version"]))
            if key in existing_versions:
                raise ValueError("rule version already exists")
            if event_type == "ENTRY_REFINED":
                supersedes = payload.get("supersedes_version")
                if supersedes in (None, ""):
                    raise ValueError("ENTRY_REFINED requires payload.supersedes_version")
                if (str(payload["rule_id"]), str(supersedes)) not in existing_versions:
                    raise ValueError("ENTRY_REFINED supersedes an unknown rule version")

        if event_type in {"RULE_PROMOTED_TO_SHADOW", "RULE_PROMOTED_TO_LIVE", "RULE_RETIRED"}:
            if payload.get("rule_id") in (None, "") or payload.get("rule_version") in (None, ""):
                raise ValueError(f"{event_type} requires payload.rule_id and payload.rule_version")
            key = (str(payload["rule_id"]), str(payload["rule_version"]))
            if key not in cls._rule_versions(events):
                raise ValueError(f"{event_type} references an unknown rule version")

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
        if not isinstance(definition, dict):
            definition = self._validate_definition(definition)
        else:
            definition = deepcopy(definition)
            protocol = definition.get("research_protocol") or {}
            bootstrap_mode = (
                isinstance(protocol, dict)
                and str(protocol.get("mode", "")).strip().upper() == "BOOTSTRAP_THEN_WF"
            )
            definition.setdefault(
                "periodic_review_policy",
                {"initial_anchor": "WALK_FORWARD_START"}
                if bootstrap_mode
                else deepcopy(DEFAULT_PERIODIC_REVIEW_POLICY),
            )
            definition.setdefault(
                "rule_update_policy",
                deepcopy(DEFAULT_RULE_UPDATE_POLICY),
            )
            definition = self._validate_definition(definition)
        operation_id = self._validate_operation_id(operation_id)
        phase = str(initial_phase).strip().upper()
        protocol_mode = str(
            ((definition.get("research_protocol") or {}).get("mode", "COLD_START"))
        ).strip().upper()
        if protocol_mode == "BOOTSTRAP_THEN_WF" and phase == "RESEARCH_WF":
            phase = "BOOTSTRAP_RESEARCH"
        if phase == "BOOTSTRAP_RESEARCH" and protocol_mode != "BOOTSTRAP_THEN_WF":
            raise ValueError(
                "BOOTSTRAP_RESEARCH initial phase requires research_protocol.mode=BOOTSTRAP_THEN_WF"
            )
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
                "operation_fingerprint": _sha256_json(
                    {
                        "event_type": "WF_CREATED",
                        "definition_sha256": manifest["definition_sha256"],
                        "initial_phase": phase,
                    }
                ),
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

    def summarize_monthly(
        self,
        experiment_id: str,
        ledger: str = "RESEARCH",
        start_month: str | None = None,
        end_month: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate all resolved trades into calendar-month performance rows."""
        ledger_name = str(ledger).strip().upper()
        if ledger_name not in LEDGERS:
            raise ValueError(f"ledger must be one of: {', '.join(sorted(LEDGERS))}")

        month_pattern = re.compile(r"^\\d{4}-(0[1-9]|1[0-2])$")

        def validate_month(value: str | None, name: str) -> str | None:
            if value is None:
                return None
            text = str(value).strip()
            if not month_pattern.fullmatch(text):
                raise ValueError(f"{name} must use YYYY-MM")
            return text

        def month_next(value: str) -> str:
            year, month = (int(part) for part in value.split("-"))
            if month == 12:
                return f"{year + 1:04d}-01"
            return f"{year:04d}-{month + 1:02d}"

        def month_range(first: str, last: str) -> list[str]:
            rows: list[str] = []
            current = first
            while current <= last:
                rows.append(current)
                current = month_next(current)
            return rows

        requested_start = validate_month(start_month, "start_month")
        requested_end = validate_month(end_month, "end_month")

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

        definition = manifest.get("definition") or {}
        reference = definition.get("reference_provenance") or {}
        initial_equity = definition.get("initial_equity")
        if initial_equity in (None, "") and isinstance(definition.get("risk_model"), dict):
            initial_equity = definition["risk_model"].get("initial_equity")
        initial_equity = float(initial_equity) if initial_equity not in (None, "") else None

        aggregates: dict[str, dict[str, Any]] = {}
        latest_market_time: str | None = None
        first_trade_month: str | None = None
        last_trade_month: str | None = None

        for event in events:
            effective = event.get("effective_market_time")
            if effective:
                normalized = _parse_iso(str(effective), "effective_market_time")
                if latest_market_time is None or normalized > latest_market_time:
                    latest_market_time = normalized

            if event.get("event_type") != "TRADE_RESOLVED":
                continue
            payload = event.get("payload") or {}
            if str(payload.get("ledger", "RESEARCH")).upper() != ledger_name:
                continue

            resolved_at_raw = (
                event.get("effective_market_time")
                or event.get("event_time")
                or event.get("recorded_at")
            )
            if not resolved_at_raw:
                raise ValueError("TRADE_RESOLVED event has no usable time")
            resolved_at = _parse_iso(str(resolved_at_raw), "TRADE_RESOLVED time")
            month = resolved_at[:7]
            first_trade_month = month if first_trade_month is None else min(first_trade_month, month)
            last_trade_month = month if last_trade_month is None else max(last_trade_month, month)

            try:
                net_r = float(payload.get("net_r", 0.0))
            except (TypeError, ValueError) as exc:
                raise ValueError("TRADE_RESOLVED payload.net_r must be numeric") from exc
            net_pnl_raw = payload.get("net_pnl")
            if net_pnl_raw in (None, ""):
                before_raw = payload.get("equity_before")
                after_raw = payload.get("equity_after")
                if before_raw not in (None, "") and after_raw not in (None, ""):
                    net_pnl_raw = float(after_raw) - float(before_raw)
                else:
                    net_pnl_raw = 0.0
            try:
                net_pnl = float(net_pnl_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("TRADE_RESOLVED payload.net_pnl must be numeric") from exc

            result = str(payload.get("result", "")).upper()
            if result not in {"WIN", "LOSS", "BREAKEVEN"}:
                result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")

            row = aggregates.setdefault(
                month,
                {
                    "month": month,
                    "wins": 0,
                    "losses": 0,
                    "breakevens": 0,
                    "trades": 0,
                    "net_r": 0.0,
                    "net_pnl": 0.0,
                    "opening_equity": None,
                    "closing_equity": None,
                    "first_trade_time": None,
                    "last_trade_time": None,
                    "first_trade_sequence": None,
                    "last_trade_sequence": None,
                },
            )
            row["trades"] += 1
            row["wins"] += int(result == "WIN")
            row["losses"] += int(result == "LOSS")
            row["breakevens"] += int(result == "BREAKEVEN")
            row["net_r"] += net_r
            row["net_pnl"] += net_pnl

            if row["first_trade_time"] is None or resolved_at < row["first_trade_time"]:
                row["first_trade_time"] = resolved_at
                row["first_trade_sequence"] = event["sequence"]
                if payload.get("equity_before") not in (None, ""):
                    row["opening_equity"] = float(payload["equity_before"])
            if row["last_trade_time"] is None or resolved_at >= row["last_trade_time"]:
                row["last_trade_time"] = resolved_at
                row["last_trade_sequence"] = event["sequence"]
                if payload.get("equity_after") not in (None, ""):
                    row["closing_equity"] = float(payload["equity_after"])

        reference_start = reference.get("period_start")
        protocol = definition.get("research_protocol") or {}
        performance_start = (
            protocol.get("walk_forward_start")
            if isinstance(protocol, dict)
            and str(protocol.get("mode", "")).strip().upper() == "BOOTSTRAP_THEN_WF"
            else reference_start
        )
        default_start = None
        if performance_start:
            default_start = _parse_iso(str(performance_start), "performance period_start")[:7]
        default_start = default_start or first_trade_month or (latest_market_time[:7] if latest_market_time else None)

        default_end = latest_market_time[:7] if latest_market_time else last_trade_month
        default_end = default_end or default_start

        selected_start = requested_start or default_start
        selected_end = requested_end or default_end
        if selected_start is None or selected_end is None:
            return {
                "contract": "causal_walk_forward_monthly_summary_v1",
                "experiment_id": value,
                "ledger": ledger_name,
                "sequence": sequence,
                "state_hash": state_hash,
                "timezone": "UTC",
                "latest_market_time": latest_market_time,
                "months": [],
                "totals": {
                    "wins": 0,
                    "losses": 0,
                    "breakevens": 0,
                    "trades": 0,
                    "win_rate_pct": None,
                    "net_r": 0.0,
                    "net_pnl": 0.0,
                    "opening_equity": initial_equity,
                    "closing_equity": initial_equity,
                },
            }
        if selected_start > selected_end:
            raise ValueError("start_month cannot be after end_month")

        reference_start_time = (
            _parse_iso(str(performance_start), "performance period_start")
            if performance_start
            else None
        )
        rows: list[dict[str, Any]] = []
        carry_equity = initial_equity
        prior_months = sorted(month for month in aggregates if month < selected_start)
        if prior_months:
            prior_close = aggregates[prior_months[-1]].get("closing_equity")
            if prior_close not in (None, ""):
                carry_equity = float(prior_close)

        for month in month_range(selected_start, selected_end):
            source = aggregates.get(month)
            if source is None:
                row = {
                    "month": month,
                    "wins": 0,
                    "losses": 0,
                    "breakevens": 0,
                    "trades": 0,
                    "net_r": 0.0,
                    "net_pnl": 0.0,
                    "opening_equity": carry_equity,
                    "closing_equity": carry_equity,
                    "first_trade_time": None,
                    "last_trade_time": None,
                    "first_trade_sequence": None,
                    "last_trade_sequence": None,
                }
            else:
                row = dict(source)
                if row["opening_equity"] is None:
                    row["opening_equity"] = carry_equity
                if row["closing_equity"] is None and row["opening_equity"] is not None:
                    row["closing_equity"] = row["opening_equity"] + row["net_pnl"]

            if row["closing_equity"] is not None:
                carry_equity = float(row["closing_equity"])

            row["net_r"] = round(float(row["net_r"]), 10)
            row["net_pnl"] = round(float(row["net_pnl"]), 10)
            row["opening_equity"] = (
                round(float(row["opening_equity"]), 10)
                if row["opening_equity"] is not None
                else None
            )
            row["closing_equity"] = (
                round(float(row["closing_equity"]), 10)
                if row["closing_equity"] is not None
                else None
            )
            row["win_rate_pct"] = (
                round(100.0 * row["wins"] / row["trades"], 2) if row["trades"] else None
            )
            if row["opening_equity"] not in (None, 0) and row["closing_equity"] is not None:
                row["return_pct"] = round(
                    100.0 * (row["closing_equity"] / row["opening_equity"] - 1.0), 4
                )
            else:
                row["return_pct"] = None

            month_start = f"{month}-01T00:00:00+00:00"
            next_month_start = f"{month_next(month)}-01T00:00:00+00:00"
            row["partial"] = bool(
                (reference_start_time is not None and reference_start_time > month_start)
                or (latest_market_time is not None and latest_market_time < next_month_start)
            )
            rows.append(row)

        total_trades = sum(row["trades"] for row in rows)
        totals = {
            "wins": sum(row["wins"] for row in rows),
            "losses": sum(row["losses"] for row in rows),
            "breakevens": sum(row["breakevens"] for row in rows),
            "trades": total_trades,
            "win_rate_pct": (
                round(100.0 * sum(row["wins"] for row in rows) / total_trades, 2)
                if total_trades
                else None
            ),
            "net_r": round(sum(float(row["net_r"]) for row in rows), 10),
            "net_pnl": round(sum(float(row["net_pnl"]) for row in rows), 10),
            "opening_equity": rows[0]["opening_equity"] if rows else initial_equity,
            "closing_equity": rows[-1]["closing_equity"] if rows else initial_equity,
        }

        return {
            "contract": "causal_walk_forward_monthly_summary_v1",
            "experiment_id": value,
            "ledger": ledger_name,
            "sequence": sequence,
            "state_hash": state_hash,
            "timezone": "UTC",
            "latest_market_time": latest_market_time,
            "start_month": selected_start,
            "end_month": selected_end,
            "months": rows,
            "totals": totals,
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
        requested_event_time = (
            _parse_iso(event_time, "event_time") if event_time is not None else None
        )
        occurred = requested_event_time or _utc_now()
        source_value = str(source).strip().upper()
        if not source_value:
            raise ValueError("source cannot be empty")
        operation_fingerprint = _sha256_json(
            {
                "event_type": event_type,
                "payload": payload,
                "effective_market_time": effective,
                "requested_event_time": requested_event_time,
                "source": source_value,
            }
        )

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
                if existing.get("operation_fingerprint") != operation_fingerprint:
                    raise ValueError("operation_id was already used for a different causal mutation")
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

            if event_type == "DECISION_FROZEN":
                decision_hash = str(payload.get("state_hash_at_decision", "")).strip().lower()
                if decision_hash != state_hash:
                    raise ValueError(
                        "DECISION_FROZEN state_hash_at_decision must equal the current experiment state hash"
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
                "operation_fingerprint": operation_fingerprint,
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
