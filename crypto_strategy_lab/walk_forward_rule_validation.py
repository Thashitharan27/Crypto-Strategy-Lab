"""Preflight and atomically persist causal walk-forward review rule mutations.

Review-authored rules must compile through the same Strategy Builder workspace used
by walk-forward materialization *before* any causal event is committed.  This
module also provides one atomic multi-event write for a review plus its rule
mutations, so schema/compiler failures cannot leave a half-written review chain.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from crypto_strategy_lab import causal_experiment as causal
from crypto_strategy_lab.causal_experiment import CausalExperimentStore, RULE_EVENT_TYPES
from crypto_strategy_lab.control_rule_workspace import RuleWorkspace
from crypto_strategy_lab.data_lake_config import PROFILE_KEYS
from crypto_strategy_lab import walk_forward_materialization as materialization


RULE_EVENT_SCHEMA_CONTRACT = "causal_walk_forward_rule_event_schema_v1"
PERIODIC_RULE_EVENT_TYPES = frozenset({*RULE_EVENT_TYPES, "RULE_RETIRED"})


def rule_event_schema() -> dict[str, Any]:
    """Return the canonical rule-event shape expected from causal reviews."""
    return {
        "contract": RULE_EVENT_SCHEMA_CONTRACT,
        "event_types": {
            "teacher_review": ["ENTRY_LEARNED", "ENTRY_REFINED"],
            "loss_review": ["VETO_LEARNED", "ENTRY_REFINED", "FLIP_LEARNED"],
            "periodic_review": sorted(PERIODIC_RULE_EVENT_TYPES),
        },
        "payload_required": ["rule_id", "rule_version", "profile", "conditions"],
        "lifecycle_payload_required": {
            "RULE_RETIRED": ["rule_id", "rule_version"],
        },
        "condition_canonical": {
            "required": ["indicator", "condition"],
            "indicator": (
                "Use a canonical Strategy Builder indicator id from get_strategy_capabilities, "
                "for example DIRECTIONAL_DI_RATIO, ADX, TAKER_BUY_SELL_RATIO, or MR_STATE."
            ),
            "condition": "EQUALS, NOT_EQUALS, GT, GTE, LT, LTE, BETWEEN, or OUTSIDE as supported by the indicator",
            "numeric": "Use value, or minimum+maximum for BETWEEN/OUTSIDE.",
            "categorical": "Use value from the indicator's advertised values.",
            "support_resistance": "Optional sr_timeframe/sr_timeframe_minutes when supported.",
        },
        "accepted_input_aliases": {
            "feature": "indicator (key alias only; the value must still resolve to a Strategy Builder indicator)",
            "op": "condition/operator",
            "evidence": "indicator",
            "operator": "condition/operator",
        },
        "example": {
            "event_type": "ENTRY_LEARNED",
            "payload": {
                "rule_id": "ENTRY_001",
                "rule_version": "1",
                "profile": "sideways_long",
                "conditions": [
                    {
                        "indicator": "DIRECTIONAL_DI_RATIO",
                        "condition": "GTE",
                        "value": 1.25,
                    }
                ],
            },
        },
        "note": (
            "Raw research-column names are not automatically treated as Strategy Builder indicators. "
            "For example, use DIRECTIONAL_DI_RATIO rather than the ambiguous raw column name di_ratio."
        ),
    }


def _full_events(
    store: CausalExperimentStore,
    experiment_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    readback = store.read_fast(experiment_id, recent_events=0)
    events = store.indexed_events(experiment_id)
    confirmed = store.read_fast(experiment_id, recent_events=0)
    if (
        int(confirmed["sequence"]) != int(readback["sequence"])
        or str(confirmed["state_hash"]) != str(readback["state_hash"])
    ):
        raise ValueError("walk-forward event chain changed during rule preflight")
    return readback, events


def _verified_prefix(
    store: CausalExperimentStore,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    readback, events = _full_events(store, experiment_id)
    sequence = int(expected_sequence)
    wanted_hash = str(expected_state_hash).strip().lower()
    head_sequence = int(readback["sequence"])
    head_hash = str(readback["state_hash"])

    # Normal review writes are pinned to the current head.  The sidecar has
    # already been reconciled against the authoritative JSONL file signature, so
    # avoid rehashing the whole chain here.
    if sequence == head_sequence and wanted_hash == head_hash:
        return readback, events, events

    # Historical-prefix validation is rare and remains a full authoritative
    # verification path so callers cannot materialize a stale intermediate head.
    _value, directory, _manifest_path, events_path = store._paths(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    authoritative = store._read_all_events(events_path)
    store._verify_chain(authoritative)
    if sequence < 1 or sequence > len(authoritative):
        raise ValueError("expected walk-forward sequence is not present in the verified chain")
    prefix = authoritative[:sequence]
    prefix_sequence, prefix_hash = store._verify_chain(prefix)
    if prefix_sequence != sequence or prefix_hash != wanted_hash:
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again before recording a review"
        )
    return readback, authoritative, prefix


def _friendly_condition(condition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise ValueError("each rule condition must be an object")
    result = deepcopy(condition)
    if result.get("indicator") in (None, "") and result.get("evidence") in (None, ""):
        if result.get("feature") not in (None, ""):
            result["indicator"] = result["feature"]
    if result.get("condition") in (None, "") and result.get("operator") in (None, ""):
        if result.get("op") not in (None, ""):
            result["condition"] = result["op"]
    result.pop("feature", None)
    result.pop("op", None)
    return result


def _friendly_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    conditions = value.get("conditions")
    if conditions is None and isinstance(value.get("group"), dict):
        conditions = value["group"].get("conditions")
    if conditions is not None:
        if not isinstance(conditions, list):
            raise ValueError("rule payload conditions must be a list")
        value["conditions"] = [_friendly_condition(item) for item in conditions]
    if isinstance(value.get("group"), dict):
        group = deepcopy(value["group"])
        group.pop("conditions", None)
        if group:
            value["group"] = group
        else:
            value.pop("group", None)
    return value


def _empty_workspace(base_config: dict[str, Any]) -> RuleWorkspace:
    workspace = RuleWorkspace(deepcopy(base_config))
    legacy_counts = workspace.workspace().get("legacy_native_rule_counts", {})
    legacy_profiles = {
        profile: int(count)
        for profile, count in legacy_counts.items()
        if int(count) > 0
    }
    if legacy_profiles:
        details = ", ".join(
            f"{profile}={count}" for profile, count in sorted(legacy_profiles.items())
        )
        raise ValueError(
            "reference run contains legacy native entry rules that are not part of the causal rule ledger; "
            f"explicitly migrate or remove them before learning new causal rules ({details})"
        )
    workspace.rules["REQUIRED"] = []
    workspace.rules["VETO"] = []
    workspace.rules["FLIP"] = []
    return workspace


def _reference_config(
    readback: dict[str, Any], reports: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    definition = deepcopy((readback.get("manifest") or {}).get("definition") or {})
    reference_run = str(definition.get("reference_run", "")).strip()
    if not reference_run:
        raise ValueError("experiment definition has no reference_run")
    reference_manifest = reports.get_run_manifest(reference_run)
    base_config = reference_manifest.get("config")
    if not isinstance(base_config, dict):
        raise ValueError("reference run manifest does not contain a normalized config snapshot")
    base_config = deepcopy(base_config)
    materialization._validate_reference_alignment(definition, reference_manifest, base_config)
    return base_config, definition


def _canonicalize_one_rule(
    projected_events: list[dict[str, Any]],
    raw_payload: dict[str, Any],
    event_type: str,
    base_config: dict[str, Any],
) -> dict[str, Any]:
    payload = _friendly_payload(raw_payload)
    rule_id = str(payload.get("rule_id", "")).strip()
    version = str(payload.get("rule_version", "")).strip()
    if not rule_id or not version:
        raise ValueError(f"{event_type} requires payload.rule_id and payload.rule_version")

    # Let the materializer's own active-version/inheritance logic assemble the
    # proposed executable group before the Strategy Builder compiler validates it.
    synthetic = {
        "sequence": len(projected_events) + 1,
        "event_type": event_type,
        "payload": payload,
    }
    active = materialization._active_rule_versions([*projected_events, synthetic])
    record = next(
        (
            row
            for row in active
            if str(row.get("rule_id")) == rule_id
            and str(row.get("rule_version")) == version
        ),
        None,
    )
    if record is None:
        raise ValueError(f"proposed rule {rule_id}@{version} did not become an active executable rule")

    workspace = _empty_workspace(base_config)
    built = workspace.add_group(
        str(record["profile"]),
        str(record["family"]),
        deepcopy(record["group"]),
    )
    # to_config invokes the same compiler used by materialization and normal GUI
    # control, catching indicator/operator/value problems before persistence.
    workspace.to_config()

    canonical = deepcopy(payload)
    canonical["profile"] = str(record["profile"])
    canonical["group_id"] = built["id"]
    canonical["name"] = built["name"]
    canonical["enabled"] = bool(built["enabled"])
    canonical["match_mode"] = built["match_mode"]
    canonical["conditions"] = deepcopy(built["conditions"])
    canonical.pop("scope", None)
    canonical.pop("group", None)
    return canonical


def _compile_projected_rules(
    projected_events: list[dict[str, Any]],
    base_config: dict[str, Any],
) -> None:
    active_rules = materialization._active_rule_versions(projected_events)
    workspace = _empty_workspace(base_config)
    profiles_with_entry: set[str] = set()
    for rule in active_rules:
        built = workspace.add_group(
            str(rule["profile"]),
            str(rule["family"]),
            deepcopy(rule["group"]),
        )
        if str(rule["family"]) == "ENTRY" and bool(built.get("enabled", True)):
            profiles_with_entry.add(str(rule["profile"]))
    workspace.to_config()

    original_profiles = (base_config.get("strategy") or {}).get("profiles") or {}
    for profile in PROFILE_KEYS:
        original_enabled = bool((original_profiles.get(profile) or {}).get("enabled", False))
        if profile in profiles_with_entry and not original_enabled:
            raise ValueError(
                f"active ENTRY rules exist for {profile}, but the immutable reference configuration disables that profile"
            )


def preflight_rule_events(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    rule_events: list[dict[str, Any]],
    evidence_source: str,
    effective_from: str,
    default_reason: str,
    allowed_types: set[str],
) -> dict[str, Any]:
    """Canonicalize and compile every proposed rule without mutating the chain."""
    if not isinstance(rule_events, list):
        raise ValueError("rule_events must be a list")
    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    readback, _all, prefix = _verified_prefix(
        store, experiment_id, expected_sequence, expected_state_hash
    )
    base_config, _definition = _reference_config(readback, reports)
    projected = deepcopy(prefix)
    canonical_events: list[dict[str, Any]] = []

    for index, item in enumerate(rule_events):
        if not isinstance(item, dict):
            raise ValueError("rule_events must contain objects")
        event_type = str(item.get("event_type", "")).strip().upper()
        if event_type not in allowed_types or event_type not in PERIODIC_RULE_EVENT_TYPES:
            raise ValueError(f"unsupported rule event for this review: {event_type}")
        payload = _friendly_payload(item.get("payload") or {})
        payload.setdefault("evidence_source", evidence_source)
        payload.setdefault("effective_from", effective_from)
        payload.setdefault("reason", default_reason or "walk-forward review")

        if event_type == "RULE_RETIRED":
            rule_id = str(payload.get("rule_id", "")).strip()
            rule_version = str(payload.get("rule_version", "")).strip()
            if not rule_id or not rule_version:
                raise ValueError(
                    "RULE_RETIRED requires payload.rule_id and payload.rule_version"
                )
            active_keys = {
                (str(row.get("rule_id")), str(row.get("rule_version")))
                for row in materialization._active_rule_versions(projected)
            }
            if (rule_id, rule_version) not in active_keys:
                raise ValueError(
                    f"RULE_RETIRED target is not currently active: "
                    f"{rule_id}@{rule_version}"
                )
            store._validate_event_semantics(projected, event_type, payload)
            synthetic = {
                "sequence": len(projected) + 1,
                "event_type": event_type,
                "payload": deepcopy(payload),
            }
            projected.append(synthetic)
            canonical_events.append(
                {
                    "event_type": event_type,
                    "payload": payload,
                    "index": index + 1,
                }
            )
            continue

        # Validate metadata/lifecycle first, then compile/canonicalize the rule.
        store._validate_event_semantics(projected, event_type, payload)
        payload = _canonicalize_one_rule(projected, payload, event_type, base_config)
        store._validate_event_semantics(projected, event_type, payload)

        synthetic = {
            "sequence": len(projected) + 1,
            "event_type": event_type,
            "payload": deepcopy(payload),
        }
        projected.append(synthetic)
        canonical_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "index": index + 1,
            }
        )

    # Compile the entire projected active rule set together. This catches group-id
    # collisions, inherited refinement problems, disabled-profile conflicts, and
    # any other materialization error before the first review event is written.
    _compile_projected_rules(projected, base_config)
    return {
        "canonical_rule_events": canonical_events,
        "rule_event_schema": rule_event_schema(),
        "projected_active_rule_count": len(materialization._active_rule_versions(projected)),
    }


def _prepare_spec(spec: dict[str, Any]) -> dict[str, Any]:
    event_type = CausalExperimentStore._validate_event_type(str(spec.get("event_type", "")))
    payload = causal._json_object(spec.get("payload") or {}, "payload", causal._MAX_EVENT_BYTES)
    operation_id = CausalExperimentStore._validate_operation_id(str(spec.get("operation_id", "")))
    effective = (
        causal._parse_iso(spec["effective_market_time"], "effective_market_time")
        if spec.get("effective_market_time") is not None
        else None
    )
    requested_event_time = (
        causal._parse_iso(spec["event_time"], "event_time")
        if spec.get("event_time") is not None
        else None
    )
    source = str(spec.get("source", "CHATGPT_RESEARCH")).strip().upper()
    if not source:
        raise ValueError("source cannot be empty")
    fingerprint = causal._sha256_json(
        {
            "event_type": event_type,
            "payload": payload,
            "effective_market_time": effective,
            "requested_event_time": requested_event_time,
            "source": source,
        }
    )
    return {
        "event_type": event_type,
        "payload": payload,
        "operation_id": operation_id,
        "effective_market_time": effective,
        "requested_event_time": requested_event_time,
        "source": source,
        "operation_fingerprint": fingerprint,
    }


def append_events_atomic(
    store: CausalExperimentStore,
    *,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Commit a validated review+rules batch without rewriting historical JSONL."""
    if not specs:
        raise ValueError("atomic event batch cannot be empty")
    prepared = [_prepare_spec(spec) for spec in specs]
    wanted_hash = str(expected_state_hash).strip().lower()
    if not causal._HASH.fullmatch(wanted_hash):
        raise ValueError("expected_state_hash must be a 64-character SHA-256 hex digest")

    value, directory, manifest_path, events_path = store._paths(experiment_id)
    with store._lock:
        store._assert_safe_dir(directory, must_exist=True)
        if manifest_path.is_symlink() or events_path.is_symlink():
            raise ValueError("symlinked experiment files are not allowed")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("definition_sha256") != causal._sha256_json(manifest.get("definition")):
            raise ValueError("experiment definition hash mismatch")

        index = store._ensure_event_index(manifest, events_path)
        snapshot = index.snapshot()
        sequence = int(snapshot["sequence"])
        state_hash = str(snapshot["state_hash"])

        existing = [index.operation(item["operation_id"]) for item in prepared]
        if all(item is not None for item in existing):
            for found, requested in zip(existing, prepared):
                assert found is not None
                if found.get("operation_fingerprint") != requested["operation_fingerprint"]:
                    raise ValueError("operation_id was already used for a different causal mutation")
            last = existing[-1]
            assert last is not None
            return {
                "experiment_id": value,
                "idempotent_replay": True,
                "sequence": int(last["sequence"]),
                "state_hash": str(last["resulting_state_hash"]),
                "events": deepcopy(existing),
                "derived_state": deepcopy(snapshot["derived_state"]),
            }
        if any(item is not None for item in existing):
            raise ValueError(
                "atomic review batch is only partially present; read and inspect the verified chain before retrying"
            )
        if sequence != int(expected_sequence) or state_hash != wanted_hash:
            raise ValueError(
                "causal experiment changed since it was read; read it again before appending"
            )

        # Only rule lifecycle history is needed for batch semantic validation.
        projected_semantics = index.events(
            event_types=RULE_EVENT_TYPES
            | {"RULE_PROMOTED_TO_SHADOW", "RULE_PROMOTED_TO_LIVE", "RULE_RETIRED"}
        )
        new_records: list[dict[str, Any]] = []
        previous_hash = state_hash
        next_sequence = sequence
        next_state = deepcopy(snapshot["derived_state"])

        for requested in prepared:
            payload = requested["payload"]
            store._validate_event_semantics(
                projected_semantics, requested["event_type"], payload
            )
            recorded_at = causal._utc_now()
            occurred = requested["requested_event_time"] or recorded_at
            next_sequence += 1
            record = {
                "schema_version": causal._SCHEMA_VERSION,
                "event_id": uuid4().hex,
                "sequence": next_sequence,
                "experiment_id": value,
                "event_type": requested["event_type"],
                "operation_id": requested["operation_id"],
                "operation_fingerprint": requested["operation_fingerprint"],
                "recorded_at": recorded_at,
                "event_time": occurred,
                "effective_market_time": requested["effective_market_time"],
                "previous_state_hash": previous_hash,
                "source": requested["source"],
                "payload": payload,
            }
            record["resulting_state_hash"] = store._event_hash(record)
            encoded = causal._canonical_json(record)
            if len(encoded.encode("utf-8")) > causal._MAX_EVENT_BYTES:
                raise ValueError(f"event exceeds {causal._MAX_EVENT_BYTES} bytes")
            new_records.append(record)
            if requested["event_type"] in RULE_EVENT_TYPES or requested["event_type"] in {
                "RULE_PROMOTED_TO_SHADOW",
                "RULE_PROMOTED_TO_LIVE",
                "RULE_RETIRED",
            }:
                projected_semantics.append(record)
            store._apply_event_to_derived_state(next_state, record)
            previous_hash = record["resulting_state_hash"]

        # Append the new batch only.  Roll back to the original byte length on an
        # in-process write/fsync failure; historical bytes are never recopied.
        original_size = events_path.stat().st_size
        batch_text = "".join(
            causal._canonical_json(event) + "\n" for event in new_records
        )
        try:
            with events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(batch_text)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            with events_path.open("r+b") as handle:
                handle.truncate(original_size)
                handle.flush()
                os.fsync(handle.fileno())
            raise

        try:
            index.record_batch_appended(
                events=new_records,
                derived_state=next_state,
                events_path=events_path,
                definition_sha256=str(manifest["definition_sha256"]),
                force_checkpoint=True,
            )
            fast_index_status = "CURRENT"
        except Exception:
            # JSONL is authoritative. A later fast read will notice the file
            # signature mismatch and rebuild/verify the sidecar before use.
            fast_index_status = "STALE_REBUILD_REQUIRED"

        return {
            "experiment_id": value,
            "idempotent_replay": False,
            "sequence": next_sequence,
            "state_hash": previous_hash,
            "events": deepcopy(new_records),
            "derived_state": next_state,
            "fast_index_status": fast_index_status,
        }

