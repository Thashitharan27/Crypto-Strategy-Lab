"""Materialize causal walk-forward research into executable backtest snapshots.

The causal event stream remains the research source of truth.  This module
creates a deterministic Strategy Builder configuration at one verified chain
head and can use that immutable snapshot to create a normal DRAFT control run.
It deliberately never validates, starts, shadows, or promotes a run by itself.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from crypto_strategy_lab.causal_experiment import (
    CausalExperimentStore,
    RULE_EVENT_TYPES,
)
from crypto_strategy_lab.control_rule_workspace import RuleWorkspace
from crypto_strategy_lab.data_lake_config import PROFILE_KEYS
from crypto_strategy_lab.run_manifest import canonical_sha256


SNAPSHOT_CONTRACT = "causal_walk_forward_strategy_snapshot_v1"
RUN_PROVENANCE_CONTRACT = "causal_walk_forward_materialized_run_v1"
_RULE_FAMILY = {
    "ENTRY_LEARNED": "ENTRY",
    "ENTRY_REFINED": "ENTRY",
    "VETO_LEARNED": "VETO",
    "FLIP_LEARNED": "FLIP",
}
_PROMOTION_STATUS = {
    "RULE_PROMOTED_TO_SHADOW": "SHADOW",
    "RULE_PROMOTED_TO_LIVE": "LIVE_ACTIVE",
    "RULE_RETIRED": "RETIRED",
}


def _timeframe_minutes(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("timeframe cannot be boolean")
    if isinstance(value, (int, float)):
        numeric = int(value)
        if numeric <= 0 or float(value) != numeric:
            raise ValueError("timeframe must be a positive whole number of minutes")
        return numeric
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("timeframe cannot be empty")
    multipliers = {"m": 1, "h": 60, "d": 1440}
    suffix = text[-1]
    if suffix not in multipliers:
        return _timeframe_minutes(int(text))
    return int(text[:-1]) * multipliers[suffix]


def _profile_from_payload(payload: dict[str, Any], inherited: str | None = None) -> str:
    group = payload.get("group") if isinstance(payload.get("group"), dict) else {}
    raw = payload.get("profile", group.get("profile", inherited))
    if raw not in (None, ""):
        profile = str(raw).strip().lower()
        if profile not in PROFILE_KEYS:
            raise ValueError(f"unsupported rule profile: {raw}")
        return profile
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else group.get("scope")
    if isinstance(scope, dict):
        regime = str(scope.get("regime", "")).strip().lower()
        side = str(scope.get("side", "")).strip().lower()
        if regime and side and regime != "all" and side != "all":
            profile = f"{regime}_{side}"
            if profile in PROFILE_KEYS:
                return profile
    raise ValueError("executable rule is missing an exact profile")


def _stable_condition_id(rule_id: str, rule_version: str, index: int) -> str:
    digest = hashlib.sha256(
        f"{rule_id}@{rule_version}:{index}".encode("utf-8")
    ).hexdigest()[:12]
    return f"wf_{digest}_{index}"


def _executable_group(
    payload: dict[str, Any],
    *,
    rule_id: str,
    rule_version: str,
    inherited: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    prior = deepcopy(inherited or {})
    prior_group = prior.get("group") if isinstance(prior.get("group"), dict) else {}
    supplied_group = payload.get("group") if isinstance(payload.get("group"), dict) else {}
    merged_group = {**prior_group, **deepcopy(supplied_group)}

    inherited_profile = prior.get("profile")
    profile = _profile_from_payload(payload, inherited=inherited_profile)
    conditions = payload.get("conditions")
    if conditions is None:
        conditions = merged_group.get("conditions")
    if conditions is None:
        conditions = prior_group.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError(
            f"active rule {rule_id} has no executable conditions; migrate or refine it with a full rule definition"
        )

    normalized_conditions: list[dict[str, Any]] = []
    for index, raw_condition in enumerate(conditions, 1):
        if not isinstance(raw_condition, dict):
            raise ValueError(f"active rule {rule_id} contains a non-object condition")
        condition = deepcopy(raw_condition)
        if condition.get("id") in (None, ""):
            condition["id"] = _stable_condition_id(rule_id, rule_version, index)
        normalized_conditions.append(condition)

    group_id = str(
        payload.get("group_id")
        or merged_group.get("id")
        or merged_group.get("group_id")
        or rule_id
    ).strip()
    name = str(
        payload.get("name")
        or payload.get("group_name")
        or merged_group.get("name")
        or merged_group.get("group_name")
        or rule_id
    ).strip()
    enabled = payload.get("enabled", merged_group.get("enabled", True))
    match_mode = str(payload.get("match_mode", merged_group.get("match_mode", "ALL"))).upper()
    group = {
        "id": group_id,
        "name": name,
        "enabled": enabled,
        "match_mode": match_mode,
        "conditions": normalized_conditions,
    }
    return profile, group


def _active_rule_versions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    versions: dict[tuple[str, str], dict[str, Any]] = {}
    lifecycle: dict[tuple[str, str], str] = {}
    deployment: dict[tuple[str, str], str] = {}

    for event in events:
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload") or {}
        if event_type in RULE_EVENT_TYPES:
            rule_id = str(payload.get("rule_id", "")).strip()
            version = str(payload.get("rule_version", "")).strip()
            key = (rule_id, version)
            inherited: dict[str, Any] | None = None
            supersedes = payload.get("supersedes_version")
            if supersedes not in (None, ""):
                previous_key = (rule_id, str(supersedes))
                previous = versions.get(previous_key)
                if previous is None:
                    raise ValueError(
                        f"rule {rule_id}@{version} supersedes unknown version {supersedes}"
                    )
                inherited = previous
                lifecycle[previous_key] = "SUPERSEDED"
            profile, group = _executable_group(
                payload,
                rule_id=rule_id,
                rule_version=version,
                inherited=inherited,
            )
            record = {
                "rule_id": rule_id,
                "rule_version": version,
                "family": _RULE_FAMILY[event_type],
                "profile": profile,
                "group": group,
                "effective_from": payload.get("effective_from"),
                "learned_sequence": int(event["sequence"]),
                "evidence_source": payload.get("evidence_source"),
                "supersedes_version": supersedes,
            }
            versions[key] = record
            lifecycle[key] = "ACTIVE"
            deployment[key] = "RESEARCH_ONLY"
            continue

        if event_type in _PROMOTION_STATUS:
            key = (str(payload.get("rule_id", "")), str(payload.get("rule_version", "")))
            if key not in versions:
                raise ValueError(f"{event_type} references unknown rule version {key[0]}@{key[1]}")
            if event_type == "RULE_RETIRED":
                lifecycle[key] = "RETIRED"
            deployment[key] = _PROMOTION_STATUS[event_type]

    active_by_id: dict[str, list[tuple[str, str]]] = {}
    for key in versions:
        if lifecycle.get(key) == "ACTIVE":
            active_by_id.setdefault(key[0], []).append(key)
    ambiguous = {
        rule_id: keys for rule_id, keys in active_by_id.items() if len(keys) > 1
    }
    if ambiguous:
        text = ", ".join(
            f"{rule_id}: " + ", ".join(version for _, version in keys)
            for rule_id, keys in sorted(ambiguous.items())
        )
        raise ValueError(
            "multiple active versions exist for the same rule; retire or supersede the older version(s): "
            + text
        )

    result = []
    for key, record in versions.items():
        if lifecycle.get(key) != "ACTIVE":
            continue
        item = deepcopy(record)
        item["deployment_status"] = deployment.get(key, "RESEARCH_ONLY")
        result.append(item)
    result.sort(key=lambda row: (row["learned_sequence"], row["rule_id"], row["rule_version"]))
    return result


def _verified_experiment(
    project_root: Path,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    store = CausalExperimentStore(Path(project_root) / "walk_forward_experiments")
    readback = store.read(experiment_id, recent_events=0)
    sequence = int(readback["sequence"])
    state_hash = str(readback["state_hash"])
    if sequence != int(expected_sequence) or state_hash != str(expected_state_hash).strip().lower():
        raise ValueError(
            "walk-forward experiment changed since it was read; read the verified chain head again before materializing"
        )
    _value, directory, _manifest_path, events_path = store._paths(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    events = store._read_all_events(events_path)
    verified_sequence, verified_hash = store._verify_chain(events)
    if verified_sequence != sequence or verified_hash != state_hash:
        raise ValueError("walk-forward event chain changed during materialization")
    return readback["manifest"], events, state_hash


def _validate_reference_alignment(
    definition: dict[str, Any], reference_manifest: dict[str, Any], base_config: dict[str, Any]
) -> None:
    request = reference_manifest.get("request") or {}
    reference_symbol = str(request.get("symbol", "")).upper().replace("/", "").replace("-", "")
    expected_symbol = str(definition.get("symbol", "")).upper().replace("/", "").replace("-", "")
    if reference_symbol and expected_symbol and reference_symbol != expected_symbol:
        raise ValueError(
            f"reference run symbol {reference_symbol} does not match experiment symbol {expected_symbol}"
        )
    data = base_config.get("data") or {}
    expected_tf = _timeframe_minutes(definition["strategy_timeframe"])
    if int(data.get("strategy_timeframe_minutes", -1)) != expected_tf:
        raise ValueError("reference run strategy timeframe does not match immutable experiment definition")
    if definition.get("intrabar_timeframe") not in (None, ""):
        expected_intrabar = _timeframe_minutes(definition["intrabar_timeframe"])
        if int(data.get("intrabar_timeframe_minutes", -1)) != expected_intrabar:
            raise ValueError("reference run intrabar timeframe does not match immutable experiment definition")
    expected_regime = str(definition.get("regime_method", "")).upper()
    actual_regime = str((base_config.get("features") or {}).get("market_regime_method", "")).upper()
    if expected_regime and actual_regime and expected_regime != actual_regime:
        raise ValueError("reference run regime method does not match immutable experiment definition")


def materialize_walk_forward_strategy(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    expected_sequence: int,
    expected_state_hash: str,
    include_config: bool = False,
) -> dict[str, Any]:
    """Build an executable Strategy Builder snapshot at one verified causal head."""
    manifest, events, state_hash = _verified_experiment(
        control.project_root,
        experiment_id,
        expected_sequence,
        expected_state_hash,
    )
    definition = deepcopy(manifest["definition"])
    reference_run = str(definition["reference_run"])
    reference_manifest = reports.get_run_manifest(reference_run)
    base_config = reference_manifest.get("config")
    if not isinstance(base_config, dict):
        raise ValueError("reference run manifest does not contain a normalized config snapshot")
    base_config = deepcopy(base_config)
    _validate_reference_alignment(definition, reference_manifest, base_config)

    active_rules = _active_rule_versions(events)
    workspace = RuleWorkspace(base_config)
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
            f"explicitly migrate or remove them before materialization ({details})"
        )

    # The teacher/reference run supplies immutable non-rule settings, not the
    # learned production rule set.  Replace all builder rule families with the
    # causally active experiment rules.  Strategy built-ins remain compiler-owned.
    workspace.rules["REQUIRED"] = []
    workspace.rules["VETO"] = []
    workspace.rules["FLIP"] = []

    profiles_with_entry: set[str] = set()
    groups_by_profile: dict[str, dict[str, list[dict[str, Any]]]] = {
        profile: {"ENTRY": [], "VETO": [], "FLIP": []} for profile in PROFILE_KEYS
    }
    for rule in active_rules:
        profile = rule["profile"]
        family = rule["family"]
        group = deepcopy(rule["group"])
        built = workspace.add_group(profile, family, group)
        groups_by_profile[profile][family].append(built)
        if family == "ENTRY" and bool(built.get("enabled", True)):
            profiles_with_entry.add(profile)

    materialized_config = workspace.to_config()
    materialized_config.setdefault("reporting", {})["output_dir"] = str(control.output_root)
    original_profiles = (base_config.get("strategy") or {}).get("profiles") or {}
    for profile in PROFILE_KEYS:
        original_enabled = bool((original_profiles.get(profile) or {}).get("enabled", False))
        if profile in profiles_with_entry and not original_enabled:
            raise ValueError(
                f"active ENTRY rules exist for {profile}, but the immutable reference configuration disables that profile"
            )
        materialized_config["strategy"]["profiles"][profile]["enabled"] = (
            original_enabled and profile in profiles_with_entry
        )

    active_rule_versions = [
        {
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "family": rule["family"],
            "profile": rule["profile"],
            "deployment_status": rule["deployment_status"],
            "learned_sequence": rule["learned_sequence"],
        }
        for rule in active_rules
    ]
    snapshot_core = {
        "contract": SNAPSHOT_CONTRACT,
        "experiment_id": experiment_id,
        "experiment_sequence": int(expected_sequence),
        "experiment_state_hash": state_hash,
        "definition_sha256": manifest["definition_sha256"],
        "reference_run": reference_run,
        "reference_run_id": reference_manifest.get("run_id"),
        "symbol": definition["symbol"],
        "strategy_timeframe": definition["strategy_timeframe"],
        "active_rule_versions": active_rule_versions,
        "groups_by_profile": groups_by_profile,
        "materialized_config": materialized_config,
    }
    snapshot_sha256 = canonical_sha256(snapshot_core)
    result = {
        "contract": SNAPSHOT_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": int(expected_sequence),
        "state_hash": state_hash,
        "snapshot_sha256": snapshot_sha256,
        "reference_run": reference_run,
        "reference_run_id": reference_manifest.get("run_id"),
        "symbol": definition["symbol"],
        "strategy_timeframe": definition["strategy_timeframe"],
        "active_rule_versions": active_rule_versions,
        "rule_counts": {
            family: sum(1 for rule in active_rules if rule["family"] == family)
            for family in ("ENTRY", "VETO", "FLIP")
        },
        "enabled_profiles": sorted(profiles_with_entry),
        "groups_by_profile": groups_by_profile,
        "materialized_config_sha256": canonical_sha256(materialized_config),
    }
    if include_config:
        result["materialized_config"] = materialized_config
    return result


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlinked snapshot/provenance paths are not allowed")
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _persist_snapshot(control: Any, snapshot: dict[str, Any]) -> Path:
    experiment_id = snapshot["experiment_id"]
    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    _value, experiment_dir, _manifest_path, _events_path = store._paths(experiment_id)
    store._assert_safe_dir(experiment_dir, must_exist=True)
    snapshots = experiment_dir / "snapshots"
    snapshots.mkdir(parents=False, exist_ok=True)
    filename = (
        f"strategy_s{snapshot['sequence']}_{str(snapshot['state_hash'])[:12]}_"
        f"{str(snapshot['snapshot_sha256'])[:12]}.json"
    )
    path = snapshots / filename
    payload = deepcopy(snapshot)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical_sha256(existing) != canonical_sha256(payload):
            raise ValueError("immutable materialized strategy snapshot path already exists with different content")
        return path
    _atomic_json(path, payload)
    return path


def create_run_from_walk_forward_experiment(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    start: str,
    end: str,
    expected_sequence: int,
    expected_state_hash: str,
    run_name: str | None = None,
) -> dict[str, Any]:
    """Create one provenance-linked DRAFT run from the exact verified WF strategy snapshot."""
    snapshot = materialize_walk_forward_strategy(
        control,
        reports,
        experiment_id=experiment_id,
        expected_sequence=expected_sequence,
        expected_state_hash=expected_state_hash,
        include_config=True,
    )
    config = deepcopy(snapshot.pop("materialized_config"))
    chosen_name = str(run_name or f"WF_{experiment_id}_s{expected_sequence}").strip()
    created = control.create_run(
        symbol=snapshot["symbol"],
        start=start,
        end=end,
        config=config,
        run_name=chosen_name,
    )
    run_id = created["run_id"]
    provenance = {
        "contract": RUN_PROVENANCE_CONTRACT,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "experiment_sequence": snapshot["sequence"],
        "experiment_state_hash": snapshot["state_hash"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "reference_run": snapshot["reference_run"],
        "reference_run_id": snapshot["reference_run_id"],
        "active_rule_versions": snapshot["active_rule_versions"],
        "rule_counts": snapshot["rule_counts"],
        "enabled_profiles": snapshot["enabled_profiles"],
        "run_status_at_creation": created.get("status"),
    }
    try:
        snapshot_payload = {**snapshot, "materialized_config": config}
        snapshot_path = _persist_snapshot(control, snapshot_payload)
        job = control._job(run_id)
        provenance["strategy_snapshot_path"] = str(snapshot_path.relative_to(control.project_root))
        provenance["run_config_sha256"] = canonical_sha256(job.config)
        _atomic_json(job.state_dir / "walk_forward_provenance.json", provenance)
    except Exception:
        try:
            control.cancel_run(run_id)
        finally:
            raise
    created["walk_forward_provenance"] = provenance
    created["next_step"] = "Call validate_run on this DRAFT; start_run still requires the returned validation_token."
    return created
