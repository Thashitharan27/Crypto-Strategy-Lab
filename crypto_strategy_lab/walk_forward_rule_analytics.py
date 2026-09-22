"""Read-only analytics for event-sourced causal walk-forward experiments.

The authoritative JSONL chain remains the source of truth.  These helpers verify
that chain before reporting, reconstruct rule versions at each captured candidate,
and optionally replay causally blocked VETO opportunities against immutable
paired Walk Forward LONG/SHORT artifacts. Nothing in this module appends events
or changes strategy state.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
import math
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

from crypto_strategy_lab.causal_experiment import CausalExperimentStore, RULE_EVENT_TYPES
from crypto_strategy_lab import walk_forward_candidate_engine_impl as candidate_impl
from crypto_strategy_lab import walk_forward_materialization as materialization


RULE_PERFORMANCE_CONTRACT = "causal_walk_forward_rule_performance_v1"
PERIODIC_REVIEW_SUMMARY_CONTRACT = "causal_walk_forward_periodic_review_summary_v1"

_RULE_FAMILY = {
    "ENTRY_LEARNED": "ENTRY",
    "ENTRY_REFINED": "ENTRY",
    "VETO_LEARNED": "VETO",
    "FLIP_LEARNED": "FLIP",
}
_DEPLOYMENT_STATUS = {
    "RULE_PROMOTED_TO_SHADOW": "SHADOW",
    "RULE_PROMOTED_TO_LIVE": "LIVE_ACTIVE",
    "RULE_RETIRED": "RETIRED",
}
_VALID_FAMILIES = {"ALL", "ENTRY", "VETO", "FLIP"}


def _utc(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _optional_utc(value: Any, name: str) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    return _utc(value, name)


def _event_time(event: dict[str, Any]) -> pd.Timestamp | None:
    raw = (
        event.get("effective_market_time")
        or event.get("event_time")
        or event.get("recorded_at")
    )
    return _optional_utc(raw, "event time")


def _iso(value: pd.Timestamp | None) -> str | None:
    return value.isoformat() if value is not None else None


def _round(value: float | int | None, digits: int = 10) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _verified_experiment(
    control: Any,
    experiment_id: str,
) -> tuple[CausalExperimentStore, dict[str, Any], list[dict[str, Any]]]:
    store = CausalExperimentStore(Path(control.project_root) / "walk_forward_experiments")
    readback = store.read(experiment_id, recent_events=0)
    _value, directory, _manifest_path, events_path = store._paths(experiment_id)
    store._assert_safe_dir(directory, must_exist=True)
    events = store._read_all_events(events_path)
    sequence, state_hash = store._verify_chain(events)
    if sequence != int(readback["sequence"]) or state_hash != str(readback["state_hash"]):
        raise ValueError("walk-forward event chain changed during analytics")
    return store, readback, events


def _sample_strength(size: int) -> str:
    if size < 10:
        return "LOW_SAMPLE"
    if size < 30:
        return "MODERATE_SAMPLE"
    return "MATURE_SAMPLE"


def _wilson_ci95(wins: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    p = wins / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
        / denominator
    )
    return [round(100.0 * max(0.0, center - margin), 2), round(100.0 * min(1.0, center + margin), 2)]


def _performance(rows: Iterable[dict[str, Any]], value_key: str = "net_r") -> dict[str, Any]:
    ordered = sorted(
        [row for row in rows if row.get(value_key) is not None],
        key=lambda row: (row.get("resolved_time") or row.get("time") or "", row.get("candidate_id") or ""),
    )
    values = [float(row[value_key]) for row in ordered]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    breakevens = len(values) - wins - losses
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    current_loss_streak = 0
    max_loss_streak = 0
    streak = 0
    for value in values:
        if value < 0:
            streak += 1
            max_loss_streak = max(max_loss_streak, streak)
        else:
            streak = 0
    for value in reversed(values):
        if value < 0:
            current_loss_streak += 1
        else:
            break
    total = len(values)
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate_pct": round(100.0 * wins / total, 2) if total else None,
        "win_rate_ci95_pct": _wilson_ci95(wins, total),
        "net_r": _round(sum(values) if values else 0.0),
        "average_r": _round(sum(values) / total) if total else None,
        "gross_profit_r": _round(gross_profit),
        "gross_loss_r": _round(gross_loss),
        "profit_factor": _round(gross_profit / gross_loss) if gross_loss > 0 else None,
        "profit_factor_status": "DEFINED" if gross_loss > 0 else ("NO_LOSSES" if gross_profit > 0 else "NO_LOSS_BASE"),
        "current_loss_streak": current_loss_streak,
        "max_consecutive_losses": max_loss_streak,
        "sample_strength": _sample_strength(total),
    }


def _window_rows(
    rows: Iterable[dict[str, Any]],
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    time_key: str,
    start_exclusive: bool = False,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get(time_key)
        if raw in (None, ""):
            continue
        when = _utc(raw, time_key)
        if start is not None:
            if start_exclusive and when <= start:
                continue
            if not start_exclusive and when < start:
                continue
        if end is not None and when > end:
            continue
        selected.append(row)
    return selected


def _last_periodic_review(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    result = None
    for event in events:
        if event.get("event_type") != "REVIEW_COMPLETED":
            continue
        payload = event.get("payload") or {}
        kind = str(payload.get("review_type", "")).strip().upper()
        is_periodic = kind in {"PERIODIC", "QUARTERLY"} or (
            not kind and not payload.get("candidate_id")
        )
        if is_periodic and event.get("effective_market_time") not in (None, ""):
            result = event
    return result


def _initial_periodic_anchor(
    definition: dict[str, Any],
    events: list[dict[str, Any]],
    reports: Any | None = None,
) -> pd.Timestamp | None:
    # Match the orchestrator's PR #263 semantics: migrated experiments and
    # experiments without an explicit REFERENCE_PERIOD_START policy remain
    # unanchored until a real periodic review is recorded.
    if any(event.get("event_type") == "MIGRATION_RECORDED" for event in events):
        return None
    policy = definition.get("periodic_review_policy") or {}
    if not isinstance(policy, dict):
        return None
    anchor_mode = str(policy.get("initial_anchor", "")).strip().upper()
    if anchor_mode == "WALK_FORWARD_START":
        protocol = definition.get("research_protocol") or {}
        raw = protocol.get("walk_forward_start") if isinstance(protocol, dict) else None
        return _optional_utc(raw, "walk_forward_start")
    if anchor_mode != "REFERENCE_PERIOD_START":
        return None
    provenance = definition.get("reference_provenance") or {}
    raw = provenance.get("period_start") if isinstance(provenance, dict) else None
    if not raw and reports is not None:
        reference_run = str(definition.get("reference_run", "")).strip()
        if reference_run:
            manifest = reports.get_run_manifest(reference_run)
            request = manifest.get("request") or {}
            raw = request.get("start")
    return _optional_utc(raw, "reference period_start")


def _market_cursor(events: list[dict[str, Any]]) -> pd.Timestamp | None:
    # Market-time analytics must never use wall-clock recorded_at/event_time. A
    # historical WF can be created years after its reference period.
    present = [
        _utc(event["effective_market_time"], "effective_market_time")
        for event in events
        if event.get("effective_market_time") not in (None, "")
    ]
    return max(present) if present else None


def _rule_versions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    records: list[dict[str, Any]] = []

    for event in events:
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload") or {}
        sequence = int(event.get("sequence", 0))

        if event_type in RULE_EVENT_TYPES:
            rule_id = str(payload.get("rule_id", "")).strip()
            version = str(payload.get("rule_version", "")).strip()
            family = _RULE_FAMILY[event_type]
            key = (rule_id, version)
            inherited: dict[str, Any] | None = None
            supersedes = payload.get("supersedes_version")
            if supersedes not in (None, ""):
                previous_key = (rule_id, str(supersedes))
                previous = by_key.get(previous_key)
                if previous is None:
                    raise ValueError(
                        f"analytics found {rule_id}@{version} superseding unknown version {supersedes}"
                    )
                inherited = previous
                previous["lifecycle_status"] = "SUPERSEDED"
                previous["end_sequence"] = sequence
                previous["effective_until"] = payload.get("effective_from")
                previous["_effective_until_ts"] = _optional_utc(
                    payload.get("effective_from"),
                    f"{rule_id}@{supersedes} effective_until",
                )

            profile, group = materialization._executable_group(
                payload,
                rule_id=rule_id,
                rule_version=version,
                inherited=inherited,
            )
            effective_from = _optional_utc(
                payload.get("effective_from"),
                f"{rule_id}@{version} effective_from",
            )
            if effective_from is None:
                raise ValueError(f"rule {rule_id}@{version} has no effective_from")
            record = {
                "rule_id": rule_id,
                "rule_version": version,
                "rule_ref": f"{rule_id}@{version}",
                "family": family,
                "profile": profile,
                "group_id": str(group.get("id") or rule_id),
                "group_name": str(group.get("name") or rule_id),
                "group": deepcopy(group),
                "effective_from": effective_from.isoformat(),
                "_effective_from_ts": effective_from,
                "effective_until": None,
                "_effective_until_ts": None,
                "learned_sequence": sequence,
                "end_sequence": None,
                "evidence_source": payload.get("evidence_source"),
                "supersedes_version": supersedes,
                "lifecycle_status": "ACTIVE",
                "deployment_status": "RESEARCH_ONLY",
            }
            by_key[key] = record
            records.append(record)
            continue

        if event_type in _DEPLOYMENT_STATUS:
            key = (
                str(payload.get("rule_id", "")).strip(),
                str(payload.get("rule_version", "")).strip(),
            )
            record = by_key.get(key)
            if record is None:
                continue
            record["deployment_status"] = _DEPLOYMENT_STATUS[event_type]
            if event_type == "RULE_RETIRED":
                record["lifecycle_status"] = "RETIRED"
                record["end_sequence"] = sequence
                retired_at = _optional_utc(
                    event.get("effective_market_time"),
                    "RULE_RETIRED effective_market_time",
                )
                record["_effective_until_ts"] = retired_at
                record["effective_until"] = _iso(retired_at)

    records.sort(key=lambda row: (row["learned_sequence"], row["rule_id"], row["rule_version"]))
    return records


def _rule_ref_for_group(
    records: list[dict[str, Any]],
    *,
    family: str,
    profile: str,
    group_id: str,
    capture_sequence: int,
) -> tuple[str | None, str | None]:
    candidates = [
        record
        for record in records
        if record["family"] == family
        and record["profile"] == profile
        and record["group_id"] == group_id
        and int(record["learned_sequence"]) < int(capture_sequence)
        and (
            record.get("end_sequence") is None
            or int(capture_sequence) < int(record["end_sequence"])
        )
    ]
    if len(candidates) == 1:
        return str(candidates[0]["rule_ref"]), None
    if not candidates:
        return None, f"{family} group {group_id} at capture sequence {capture_sequence} has no attributable rule version"
    return None, (
        f"{family} group {group_id} at capture sequence {capture_sequence} is ambiguous across "
        + ", ".join(str(row["rule_ref"]) for row in candidates)
    )


def _trade_history(
    events: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    captures: dict[str, dict[str, Any]] = {}
    capture_sequences: dict[str, int] = {}
    decisions: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    for event in events:
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id", "")).strip()
        event_type = event.get("event_type")

        if event_type == "CANDIDATE_CONTEXT_CAPTURED" and candidate_id:
            captures[candidate_id] = payload
            capture_sequences[candidate_id] = int(event["sequence"])
            continue
        if event_type == "DECISION_FROZEN" and candidate_id:
            decisions[candidate_id] = payload
            continue
        if event_type != "TRADE_RESOLVED" or not candidate_id:
            continue
        if str(payload.get("ledger", "RESEARCH")).upper() != "RESEARCH":
            continue

        capture = captures.get(candidate_id, {})
        profile = str(capture.get("strategy_profile_key", "")).strip().lower()
        capture_sequence = capture_sequences.get(candidate_id, int(event["sequence"]))
        attribution: dict[str, list[str]] = {"ENTRY": [], "VETO": [], "FLIP": []}
        raw_groups = {
            "ENTRY": list(capture.get("matched_entry_groups") or []),
            "VETO": list(capture.get("matched_veto_groups") or []),
            "FLIP": list(capture.get("matched_flip_groups") or []),
        }
        for family, groups in raw_groups.items():
            for group_id in groups:
                ref, warning = _rule_ref_for_group(
                    records,
                    family=family,
                    profile=profile,
                    group_id=str(group_id),
                    capture_sequence=capture_sequence,
                )
                if ref is not None and ref not in attribution[family]:
                    attribution[family].append(ref)
                if warning is not None and warning not in warnings:
                    warnings.append(warning)

        net_r = float(payload.get("net_r", 0.0))
        resolved = _event_time(event)
        decision = decisions.get(candidate_id, {})
        rows.append(
            {
                "candidate_id": candidate_id,
                "capture_sequence": capture_sequence,
                "resolved_sequence": int(event["sequence"]),
                "entry_time": capture.get("entry_time") or event.get("effective_market_time"),
                "resolved_time": _iso(resolved),
                "profile": profile or None,
                "regime": profile.rsplit("_", 1)[0] if "_" in profile else (profile or None),
                "source_side": capture.get("source_side"),
                "strategy_action": (
                    decision.get("strategy_action")
                    or decision.get("final_action")
                    or capture.get("rule_effective_side")
                    or capture.get("source_side")
                ),
                "net_r": net_r,
                "result": str(payload.get("result") or ("WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN"))).upper(),
                "matched_entries": sorted(attribution["ENTRY"]),
                "matched_vetoes": sorted(attribution["VETO"]),
                "matched_flips": sorted(attribution["FLIP"]),
            }
        )
    rows.sort(key=lambda row: (row.get("resolved_time") or "", row["resolved_sequence"]))
    return rows, warnings


def _unique_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for row in rows:
        key = str(row.get("candidate_id") or f"{row.get('resolved_sequence')}:{row.get('resolved_time')}")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _rule_trade_rows(
    trades: list[dict[str, Any]],
    rule_ref: str,
    family: str,
) -> list[dict[str, Any]]:
    key = {
        "ENTRY": "matched_entries",
        "VETO": "matched_vetoes",
        "FLIP": "matched_flips",
    }[family]
    return [row for row in trades if rule_ref in row.get(key, [])]


def _periodic_windows(
    events: list[dict[str, Any]],
    cursor: pd.Timestamp | None,
    start_time: str | None,
    end_time: str | None,
) -> dict[str, dict[str, Any]]:
    selected_start = _optional_utc(start_time, "start_time")
    selected_end = _optional_utc(end_time, "end_time") or cursor
    if selected_start is not None and selected_end is not None and selected_start > selected_end:
        raise ValueError("start_time cannot be after end_time")
    last_review = _last_periodic_review(events)
    review_time = (
        _utc(last_review["effective_market_time"], "periodic review effective_market_time")
        if last_review is not None
        else None
    )

    windows: dict[str, dict[str, Any]] = {
        "lifetime": {"start": None, "end": cursor, "start_exclusive": False},
        "selected": {"start": selected_start, "end": selected_end, "start_exclusive": False},
        "last_month": {
            "start": cursor - pd.DateOffset(months=1) if cursor is not None else None,
            "end": cursor,
            "start_exclusive": True,
        },
        "last_3_months": {
            "start": cursor - pd.DateOffset(months=3) if cursor is not None else None,
            "end": cursor,
            "start_exclusive": True,
        },
        "since_last_periodic_review": {
            "start": review_time,
            "end": cursor,
            "start_exclusive": True,
        },
    }
    return windows


def _performance_windows(
    rows: list[dict[str, Any]],
    windows: dict[str, dict[str, Any]],
    *,
    time_key: str = "resolved_time",
    value_key: str = "net_r",
) -> dict[str, dict[str, Any]]:
    result = {}
    for name, window in windows.items():
        selected = _window_rows(
            rows,
            start=window["start"],
            end=window["end"],
            time_key=time_key,
            start_exclusive=bool(window.get("start_exclusive")),
        )
        result[name] = _performance(selected, value_key=value_key)
    return result


def _entry_overlap(
    trades: list[dict[str, Any]],
    windows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected_window = windows["selected"]
    selected = _window_rows(
        trades,
        start=selected_window["start"],
        end=selected_window["end"],
        time_key="resolved_time",
        start_exclusive=bool(selected_window.get("start_exclusive")),
    )
    per_rule: dict[str, dict[str, Any]] = {}
    combinations: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    refs = sorted({ref for row in selected for ref in row.get("matched_entries", [])})
    for ref in refs:
        associated = [row for row in selected if ref in row.get("matched_entries", [])]
        only = [row for row in associated if len(row.get("matched_entries", [])) == 1]
        shared = [row for row in associated if len(row.get("matched_entries", [])) > 1]
        partners = Counter(
            other
            for row in shared
            for other in row.get("matched_entries", [])
            if other != ref
        )
        per_rule[ref] = {
            "rule_only_trades": len(only),
            "shared_trades": len(shared),
            "rule_only_performance": _performance(only),
            "shared_performance": _performance(shared),
            "top_overlap_partners": [
                {"rule_ref": partner, "shared_trades": count}
                for partner, count in partners.most_common(10)
            ],
        }
    for row in selected:
        combo = tuple(sorted(set(row.get("matched_entries", []))))
        if len(combo) > 1:
            combinations[combo].append(row)
    combo_rows = []
    for combo, rows in combinations.items():
        combo_rows.append(
            {
                "entry_combination": list(combo),
                **_performance(rows),
            }
        )
    combo_rows.sort(key=lambda row: (-int(row["trades"]), tuple(row["entry_combination"])))
    return {
        "counting_note": (
            "One resolved trade remains one unique trade. Rule statistics are association statistics; "
            "a shared trade may contribute to multiple ENTRY rules and is not treated as independent evidence."
        ),
        "unique_selected_trades": len(_unique_rows(selected)),
        "per_rule": per_rule,
        "common_entry_combinations": combo_rows[:50],
        "entry_combinations_total": len(combo_rows),
    }


def _open_trade_intervals(
    events: list[dict[str, Any]],
    cursor: pd.Timestamp | None,
) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    captures: dict[str, pd.Timestamp] = {}
    ends: dict[str, pd.Timestamp] = {}
    for event in events:
        payload = event.get("payload") or {}
        candidate_id = str(payload.get("candidate_id", "")).strip()
        if not candidate_id:
            continue
        if event.get("event_type") == "CANDIDATE_CONTEXT_CAPTURED":
            # Candidate selection stops as soon as capture is durable, so the
            # busy interval starts at capture/entry market time rather than at
            # the later ChatGPT decision-availability timestamp.
            raw = event.get("effective_market_time") or payload.get("entry_time")
            if raw not in (None, ""):
                captures[candidate_id] = _utc(raw, "candidate capture market time")
        elif event.get("event_type") in {"TRADE_RESOLVED", "FEATURE_CONTEXT_INVALID"}:
            raw = event.get("effective_market_time")
            if raw not in (None, ""):
                ends[candidate_id] = _utc(raw, "candidate terminal effective_market_time")

    raw_intervals = []
    for candidate_id, start in captures.items():
        end = ends.get(candidate_id) or cursor
        if end is not None and end >= start:
            raw_intervals.append((start, end))
    raw_intervals.sort(key=lambda item: item[0])

    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in raw_intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return [item[0] for item in merged], [item[1] for item in merged]


def _inside_interval(
    when: pd.Timestamp,
    starts: list[pd.Timestamp],
    ends: list[pd.Timestamp],
) -> bool:
    index = bisect_right(starts, when) - 1
    # WAIT_UNTIL_CLOSED releases the scanner at the exact exit timestamp, so
    # the busy interval is [entry, exit), not [entry, exit].
    return index >= 0 and starts[index] <= when < ends[index]


def _active_rules_at(
    by_profile_family: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    profile: str,
    family: str,
    when: pd.Timestamp,
) -> list[dict[str, Any]]:
    result = []
    for record in by_profile_family.get((profile, family), []):
        start = record["_effective_from_ts"]
        end = record.get("_effective_until_ts")
        if start <= when and (end is None or when < end):
            result.append(record)
    return result


def _iter_reference_rows(
    samples_path: Path,
    context_path: Path,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    with duckdb.connect(":memory:") as connection:
        sample_columns = candidate_impl._columns(connection, samples_path)
        context_columns = candidate_impl._columns(connection, context_path)
        required_samples = {
            "research_signal_index",
            "strategy_profile_key",
            "side",
            "entry_time",
            "pair_net_r",
            "walk_forward_candidate_id",
            "walk_forward_candidate_source",
        }
        required_context = {"strategy_index", "decision_available_at"}
        missing_samples = required_samples - set(sample_columns)
        missing_context = required_context - set(context_columns)
        if missing_samples:
            raise ValueError(
                "Walk Forward paired artifact is missing VETO replay columns: "
                + ", ".join(sorted(missing_samples))
            )
        if missing_context:
            raise ValueError(
                "feature-context artifact is missing VETO replay columns: "
                + ", ".join(sorted(missing_context))
            )
        context_select = []
        for name in context_columns:
            escaped = name.replace('"', '""')
            alias = ("__ctx_" + name).replace('"', "")
            context_select.append(f'c."{escaped}" AS "{alias}"')
        sql = f"""
            SELECT t.*, {', '.join(context_select)}, prev.adx AS __wf_prev_adx
            FROM read_parquet('{candidate_impl._quote(samples_path)}') t
            JOIN read_parquet('{candidate_impl._quote(context_path)}') c
              ON CAST(t.research_signal_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)
            LEFT JOIN read_parquet('{candidate_impl._quote(context_path)}') prev
              ON CAST(prev.strategy_index AS BIGINT)=CAST(c.strategy_index AS BIGINT)-1
            WHERE COALESCE(CAST(t.walk_forward_candidate_source AS BOOLEAN), FALSE)
              AND CAST(t.entry_time AS TIMESTAMPTZ) >= ?
              AND CAST(t.entry_time AS TIMESTAMPTZ) <= ?
            ORDER BY CAST(t.entry_time AS TIMESTAMPTZ),
                     CAST(t.research_signal_index AS BIGINT),
                     UPPER(CAST(t.side AS VARCHAR))
        """
        statement = connection.execute(sql, [start.to_pydatetime(), end.to_pydatetime()])
        columns = [str(item[0]) for item in statement.description]
        while True:
            batch = statement.fetchmany(4096)
            if not batch:
                break
            frame = pd.DataFrame.from_records(batch, columns=columns)
            for _, series in frame.iterrows():
                yield series


def _opposite_paired_net_r(
    connection: duckdb.DuckDBPyConnection,
    samples_path: Path,
    *,
    candidate_id: str,
    target_side: str,
) -> float | None:
    rows = connection.execute(
        f"""
        SELECT pair_net_r
        FROM read_parquet('{candidate_impl._quote(samples_path)}')
        WHERE CAST(walk_forward_candidate_id AS VARCHAR)=?
          AND UPPER(CAST(side AS VARCHAR))=?
        LIMIT 3
        """,
        [str(candidate_id), target_side],
    ).fetchall()
    if len(rows) != 1 or rows[0][0] is None:
        return None
    return float(rows[0][0])


def _replay_veto_blocks(
    reports: Any,
    readback: dict[str, Any],
    events: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    cursor: pd.Timestamp | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    veto_records = [record for record in records if record["family"] == "VETO"]
    entry_records = [record for record in records if record["family"] == "ENTRY"]
    if not veto_records or not entry_records or cursor is None:
        return [], {
            "rows_scanned": 0,
            "blocked_opportunities_unique": 0,
            "unresolved_flip_counterfactuals": 0,
            "replay_complete_through": _iso(cursor),
        }

    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run", "")).strip()
    if not reference_run:
        raise ValueError("experiment definition has no reference_run for VETO replay")
    manifest = reports.get_run_manifest(reference_run)
    if candidate_impl._sampling_mode(manifest) != "WALK_FORWARD":
        raise ValueError(
            "VETO effectiveness requires a WALK_FORWARD paired reference run"
        )
    base_config = manifest.get("config")
    if not isinstance(base_config, dict):
        raise ValueError("reference run manifest does not contain a normalized config snapshot")
    base_config = deepcopy(base_config)
    run_dir = reports.resolve_run(reference_run)
    samples_path = candidate_impl._artifact(manifest, run_dir, "research_sampling_trades")
    context_path = candidate_impl._artifact(manifest, run_dir, "feature_context")

    first_veto = min(record["_effective_from_ts"] for record in veto_records)
    starts, ends = _open_trade_intervals(events, cursor)
    by_profile_family: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_profile_family[(record["profile"], record["family"])].append(record)

    rows_scanned = 0
    unresolved_flips = 0
    associations: list[dict[str, Any]] = []
    unique_blocked: set[tuple[int, str, str, str]] = set()

    with duckdb.connect(":memory:") as opposite_connection:
        for series in _iter_reference_rows(
            samples_path,
            context_path,
            start=first_veto,
            end=cursor,
        ):
            rows_scanned += 1
            row, feature_context = candidate_impl._row_maps(series)
            profile = str(row.get("strategy_profile_key", "")).strip().lower()
            side = str(row.get("side", "")).strip().upper()
            if side not in {"LONG", "SHORT"} or not profile:
                continue
            raw_decision = candidate_impl._present(feature_context, "decision_available_at")
            if raw_decision is None:
                raw_decision = row.get("signal_available_at", row.get("entry_time"))
            decision_time = _utc(raw_decision, "VETO replay decision time")
            if decision_time < first_veto or decision_time > cursor:
                continue
            if _inside_interval(decision_time, starts, ends):
                continue

            profile_cfg = ((base_config.get("strategy") or {}).get("profiles") or {}).get(profile) or {}
            if not bool(profile_cfg.get("enabled", False)):
                continue

            entry_rules = _active_rules_at(
                by_profile_family,
                profile=profile,
                family="ENTRY",
                when=decision_time,
            )
            if not entry_rules:
                continue
            entry_matches = []
            for rule in entry_rules:
                matched, _details = candidate_impl._group_match(
                    row, side, profile, rule["group"], base_config
                )
                if matched:
                    entry_matches.append(rule)
            if not entry_matches:
                continue

            veto_rules = _active_rules_at(
                by_profile_family,
                profile=profile,
                family="VETO",
                when=decision_time,
            )
            veto_matches = []
            for rule in veto_rules:
                matched, _details = candidate_impl._group_match(
                    row, side, profile, rule["group"], base_config
                )
                if matched:
                    veto_matches.append(rule)
            if not veto_matches:
                continue

            flip_matches = []
            for rule in _active_rules_at(
                by_profile_family,
                profile=profile,
                family="FLIP",
                when=decision_time,
            ):
                matched, _details = candidate_impl._group_match(
                    row, side, profile, rule["group"], base_config
                )
                if matched:
                    flip_matches.append(rule)

            signal_index = int(row["research_signal_index"])
            target_side = ("SHORT" if side == "LONG" else "LONG") if flip_matches else side
            hypothetical_r: float | None
            if target_side == side:
                raw_r = row.get("pair_net_r")
                hypothetical_r = float(raw_r) if raw_r is not None and not pd.isna(raw_r) else None
            else:
                pair_id = str(row.get("walk_forward_candidate_id") or "").strip()
                hypothetical_r = (
                    _opposite_paired_net_r(
                        opposite_connection,
                        samples_path,
                        candidate_id=pair_id,
                        target_side=target_side,
                    )
                    if pair_id
                    else None
                )
                if hypothetical_r is None:
                    unresolved_flips += 1

            entry_time = _utc(row.get("entry_time"), "VETO replay entry_time")
            opportunity_key = (signal_index, side, profile, entry_time.isoformat())
            unique_blocked.add(opportunity_key)
            matched_veto_refs = sorted(rule["rule_ref"] for rule in veto_matches)
            matched_entry_refs = sorted(rule["rule_ref"] for rule in entry_matches)
            matched_flip_refs = sorted(rule["rule_ref"] for rule in flip_matches)
            for rule in veto_matches:
                associations.append(
                    {
                        "opportunity_id": f"{signal_index}-{side.lower()}-{profile}-{entry_time.isoformat()}",
                        "research_signal_index": signal_index,
                        "time": decision_time.isoformat(),
                        "entry_time": entry_time.isoformat(),
                        "profile": profile,
                        "source_side": side,
                        "hypothetical_side_without_veto": target_side,
                        "hypothetical_net_r": hypothetical_r,
                        "rule_ref": rule["rule_ref"],
                        "matched_vetoes": matched_veto_refs,
                        "matched_entries": matched_entry_refs,
                        "matched_flips": matched_flip_refs,
                        "counterfactual_resolved": hypothetical_r is not None,
                    }
                )

    return associations, {
        "rows_scanned": rows_scanned,
        "blocked_opportunities_unique": len(unique_blocked),
        "veto_associations": len(associations),
        "unresolved_flip_counterfactuals": unresolved_flips,
        "replay_complete_through": cursor.isoformat(),
        "method": (
            "Read-only causal replay of EVE rows while the WF ledger was idle, using the rule versions "
            "effective at each decision time. Active FLIPs are respected when a unique opposite-side "
            "EVE outcome exists; unresolved opposite outcomes are reported and never guessed."
        ),
    }


def _veto_effectiveness(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    resolved = [row for row in selected if row.get("hypothetical_net_r") is not None]
    values = [float(row["hypothetical_net_r"]) for row in resolved]
    losses_avoided = sum(value < 0 for value in values)
    wins_blocked = sum(value > 0 for value in values)
    breakevens_blocked = len(values) - losses_avoided - wins_blocked
    hypothetical_net_r = sum(values)
    unique_ids = {str(row.get("opportunity_id")) for row in selected}
    resolved_ids = {str(row.get("opportunity_id")) for row in resolved}
    veto_only_ids = {
        str(row.get("opportunity_id"))
        for row in selected
        if len(row.get("matched_vetoes", [])) == 1
    }
    shared_ids = unique_ids - veto_only_ids
    return {
        "blocked_opportunities": len(unique_ids),
        "resolved_counterfactuals": len(resolved_ids),
        "unresolved_counterfactuals": len(unique_ids) - len(resolved_ids),
        "losses_avoided": losses_avoided,
        "wins_blocked": wins_blocked,
        "breakevens_blocked": breakevens_blocked,
        "veto_precision_pct": round(100.0 * losses_avoided / len(values), 2) if values else None,
        "hypothetical_net_r": _round(hypothetical_net_r),
        "net_r_saved": _round(-hypothetical_net_r),
        "veto_only_opportunities": len(veto_only_ids),
        "shared_veto_opportunities": len(shared_ids),
        "sample_strength": _sample_strength(len(values)),
    }


def _veto_windows(
    associations: list[dict[str, Any]],
    rule_ref: str,
    windows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    source = [row for row in associations if row.get("rule_ref") == rule_ref]
    result = {}
    for name, window in windows.items():
        selected = _window_rows(
            source,
            start=window["start"],
            end=window["end"],
            time_key="time",
            start_exclusive=bool(window.get("start_exclusive")),
        )
        result[name] = _veto_effectiveness(selected)
    return result


def _veto_overlap(
    associations: list[dict[str, Any]],
    windows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    window = windows["selected"]
    selected = _window_rows(
        associations,
        start=window["start"],
        end=window["end"],
        time_key="time",
        start_exclusive=bool(window.get("start_exclusive")),
    )
    by_opportunity: dict[str, dict[str, Any]] = {}
    for row in selected:
        by_opportunity.setdefault(str(row["opportunity_id"]), row)
    combos: Counter[tuple[str, ...]] = Counter(
        tuple(row.get("matched_vetoes", []))
        for row in by_opportunity.values()
        if len(row.get("matched_vetoes", [])) > 1
    )
    return {
        "unique_selected_blocked_opportunities": len(by_opportunity),
        "common_veto_combinations": [
            {"veto_combination": list(combo), "blocked_opportunities": count}
            for combo, count in combos.most_common(50)
        ],
        "veto_combinations_total": len(combos),
    }


def _public_rule_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": record["rule_id"],
        "rule_version": record["rule_version"],
        "rule_ref": record["rule_ref"],
        "family": record["family"],
        "profile": record["profile"],
        "regime": (
            record["profile"].rsplit("_", 1)[0]
            if "_" in record["profile"]
            else record["profile"]
        ),
        "group_id": record["group_id"],
        "group_name": record["group_name"],
        "effective_from": record["effective_from"],
        "effective_until": record.get("effective_until"),
        "learned_sequence": record["learned_sequence"],
        "end_sequence": record.get("end_sequence"),
        "evidence_source": record.get("evidence_source"),
        "supersedes_version": record.get("supersedes_version"),
        "lifecycle_status": record["lifecycle_status"],
        "deployment_status": record["deployment_status"],
    }


def _rule_flags(
    performance: dict[str, dict[str, Any]],
    previous_version: dict[str, Any] | None,
) -> list[str]:
    flags: list[str] = []
    lifetime = performance["lifetime"]
    recent = performance["last_3_months"]
    if lifetime["trades"] and float(lifetime["net_r"]) < 0:
        flags.append("LIFETIME_NEGATIVE_R")
    if recent["trades"] and float(recent["net_r"]) < 0:
        flags.append("LAST_3_MONTHS_NEGATIVE_R")
    if int(lifetime["current_loss_streak"]) >= 3:
        flags.append("CURRENT_LOSS_STREAK_3_PLUS")
    if previous_version is not None:
        current_avg = lifetime.get("average_r")
        previous_avg = previous_version.get("average_r")
        if current_avg is not None and previous_avg is not None and float(current_avg) < float(previous_avg):
            flags.append("CURRENT_VERSION_AVERAGE_R_BELOW_PREVIOUS")
    return flags


def summarize_walk_forward_rule_performance(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    family: str = "ALL",
    start_time: str | None = None,
    end_time: str | None = None,
    active_only: bool = False,
    include_versions: bool = True,
    include_overlap: bool = True,
    include_veto_effectiveness: bool = True,
) -> dict[str, Any]:
    """Summarize version-aware rule performance from the verified full causal chain."""
    selected_family = str(family).strip().upper()
    if selected_family not in _VALID_FAMILIES:
        raise ValueError("family must be ALL, ENTRY, VETO, or FLIP")
    if not isinstance(active_only, bool):
        raise ValueError("active_only must be boolean")
    if not isinstance(include_versions, bool) or not isinstance(include_overlap, bool):
        raise ValueError("include_versions and include_overlap must be boolean")
    if not isinstance(include_veto_effectiveness, bool):
        raise ValueError("include_veto_effectiveness must be boolean")

    _store, readback, events = _verified_experiment(control, experiment_id)
    cursor = _market_cursor(events)
    records = _rule_versions(events)
    trades, attribution_warnings = _trade_history(events, records)
    windows = _periodic_windows(events, cursor, start_time, end_time)

    eligible_records = [
        record
        for record in records
        if (selected_family == "ALL" or record["family"] == selected_family)
        and (not active_only or record["lifecycle_status"] == "ACTIVE")
    ]

    version_rows: list[dict[str, Any]] = []
    for record in eligible_records:
        associated = _rule_trade_rows(trades, record["rule_ref"], record["family"])
        performance = _performance_windows(associated, windows)
        version_rows.append(
            {
                **_public_rule_record(record),
                "performance": performance,
            }
        )

    previous_by_ref: dict[str, dict[str, Any]] = {}
    grouped_versions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped_versions[(record["family"], record["rule_id"])].append(record)
    for versions in grouped_versions.values():
        versions.sort(key=lambda row: int(row["learned_sequence"]))
        prior_perf = None
        for record in versions:
            if prior_perf is not None:
                previous_by_ref[record["rule_ref"]] = prior_perf
            prior_rows = _rule_trade_rows(trades, record["rule_ref"], record["family"])
            prior_perf = _performance(prior_rows)

    for row in version_rows:
        row["flags"] = _rule_flags(
            row["performance"],
            previous_by_ref.get(row["rule_ref"]),
        )

    family_rows: list[dict[str, Any]] = []
    grouped_selected: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in eligible_records:
        grouped_selected[(record["family"], record["rule_id"])].append(record)
    for (rule_family, rule_id), versions in sorted(grouped_selected.items()):
        refs = {record["rule_ref"] for record in versions}
        attribution_key = {
            "ENTRY": "matched_entries",
            "VETO": "matched_vetoes",
            "FLIP": "matched_flips",
        }[rule_family]
        family_trades = [
            row
            for row in trades
            if any(ref in row.get(attribution_key, []) for ref in refs)
        ]
        current = [
            record
            for record in versions
            if record["lifecycle_status"] == "ACTIVE"
        ]
        family_rows.append(
            {
                "rule_id": rule_id,
                "family": rule_family,
                "versions": [record["rule_version"] for record in versions],
                "current_version": (
                    max(current, key=lambda item: int(item["learned_sequence"]))["rule_version"]
                    if current
                    else None
                ),
                "performance": _performance_windows(_unique_rows(family_trades), windows),
            }
        )

    veto_associations: list[dict[str, Any]] = []
    veto_replay_meta: dict[str, Any] | None = None
    veto_rows: list[dict[str, Any]] = []
    veto_family_rows: list[dict[str, Any]] = []
    veto_overlap: dict[str, Any] | None = None
    if include_veto_effectiveness and selected_family in {"ALL", "VETO"}:
        if reports is None:
            raise ValueError("reports service is required when include_veto_effectiveness=true")
        veto_associations, veto_replay_meta = _replay_veto_blocks(
            reports,
            readback,
            events,
            records,
            cursor=cursor,
        )
        eligible_vetos = [record for record in eligible_records if record["family"] == "VETO"]
        for record in eligible_vetos:
            veto_rows.append(
                {
                    **_public_rule_record(record),
                    "effectiveness": _veto_windows(
                        veto_associations,
                        record["rule_ref"],
                        windows,
                    ),
                }
            )
        grouped_veto_families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in eligible_vetos:
            grouped_veto_families[record["rule_id"]].append(record)
        for rule_id, versions in sorted(grouped_veto_families.items()):
            refs = {record["rule_ref"] for record in versions}
            combined = [row for row in veto_associations if row.get("rule_ref") in refs]
            effectiveness = {}
            for window_name, window in windows.items():
                selected = _window_rows(
                    combined,
                    start=window["start"],
                    end=window["end"],
                    time_key="time",
                    start_exclusive=bool(window.get("start_exclusive")),
                )
                dedup: dict[str, dict[str, Any]] = {}
                for row in selected:
                    dedup.setdefault(str(row["opportunity_id"]), row)
                effectiveness[window_name] = _veto_effectiveness(dedup.values())
            veto_family_rows.append(
                {
                    "rule_id": rule_id,
                    "versions": [record["rule_version"] for record in versions],
                    "effectiveness": effectiveness,
                }
            )
        if include_overlap:
            veto_overlap = _veto_overlap(veto_associations, windows)

    entry_overlap = (
        _entry_overlap(trades, windows)
        if include_overlap and selected_family in {"ALL", "ENTRY"}
        else None
    )

    selected_window = windows["selected"]
    selected_trades = _window_rows(
        trades,
        start=selected_window["start"],
        end=selected_window["end"],
        time_key="resolved_time",
        start_exclusive=bool(selected_window.get("start_exclusive")),
    )
    trade_attribution = [
        {
            "candidate_id": row["candidate_id"],
            "resolved_time": row["resolved_time"],
            "profile": row["profile"],
            "strategy_action": row["strategy_action"],
            "result": row["result"],
            "net_r": row["net_r"],
            "matched_entries": row["matched_entries"],
            "matched_vetoes": row["matched_vetoes"],
            "matched_flips": row["matched_flips"],
        }
        for row in selected_trades
    ]

    public_windows = {
        name: {
            "start": _iso(window["start"]),
            "end": _iso(window["end"]),
            "start_exclusive": bool(window.get("start_exclusive")),
        }
        for name, window in windows.items()
    }
    return {
        "contract": RULE_PERFORMANCE_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": int(readback["sequence"]),
        "state_hash": str(readback["state_hash"]),
        "read_only": True,
        "ledger": "RESEARCH",
        "market_cursor": _iso(cursor),
        "family_filter": selected_family,
        "active_only": active_only,
        "windows": public_windows,
        "sample_strength_thresholds": {
            "LOW_SAMPLE": "0-9 resolved observations",
            "MODERATE_SAMPLE": "10-29 resolved observations",
            "MATURE_SAMPLE": "30+ resolved observations",
        },
        "unique_trade_performance": _performance_windows(trades, windows),
        "rule_versions": version_rows if include_versions else [],
        "rule_families": family_rows,
        "trade_attribution": trade_attribution,
        "entry_overlap": entry_overlap,
        "veto_effectiveness": veto_rows,
        "veto_family_effectiveness": veto_family_rows,
        "veto_overlap": veto_overlap,
        "veto_replay": veto_replay_meta,
        "attribution_warnings": attribution_warnings,
        "notes": [
            "Rule W/L and R are association statistics; overlapping ENTRY rules share the same underlying trade.",
            "Rule versions are attributed from the active immutable version at candidate capture sequence.",
            "VETO counterfactuals are read-only replay evidence and never alter the causal ledger.",
            "Flags are descriptive analytics only; they never activate, refine, retire, or backdate a rule.",
        ],
    }


def _group_performance(
    trades: list[dict[str, Any]],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    key: str,
) -> list[dict[str, Any]]:
    selected = _window_rows(
        trades,
        start=start,
        end=end,
        time_key="resolved_time",
        start_exclusive=True,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        value = str(row.get(key) or "UNKNOWN")
        grouped[value].append(row)
    return [
        {key: value, **_performance(rows)}
        for value, rows in sorted(grouped.items())
    ]


def _monthly_performance(
    trades: list[dict[str, Any]],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, Any]]:
    selected = _window_rows(
        trades,
        start=start,
        end=end,
        time_key="resolved_time",
        start_exclusive=True,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        month = _utc(row["resolved_time"], "resolved_time").strftime("%Y-%m")
        grouped[month].append(row)
    return [
        {"month": month, **_performance(rows)}
        for month, rows in sorted(grouped.items())
    ]


def _period_comparison(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    current_start: pd.Timestamp,
    previous_start: pd.Timestamp,
    split: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record["family"] == "VETO":
            continue
        associated = _rule_trade_rows(trades, record["rule_ref"], record["family"])
        current = _performance(
            _window_rows(
                associated,
                start=current_start,
                end=end,
                time_key="resolved_time",
                start_exclusive=True,
            )
        )
        previous = _performance(
            _window_rows(
                associated,
                start=previous_start,
                end=split,
                time_key="resolved_time",
                start_exclusive=True,
            )
        )
        if not current["trades"] and not previous["trades"]:
            continue
        current_avg = current.get("average_r")
        previous_avg = previous.get("average_r")
        if current_avg is None or previous_avg is None:
            direction = "INSUFFICIENT_COMPARABLE_SAMPLE"
        elif float(current_avg) > float(previous_avg):
            direction = "IMPROVING_AVERAGE_R"
        elif float(current_avg) < float(previous_avg):
            direction = "DETERIORATING_AVERAGE_R"
        else:
            direction = "UNCHANGED_AVERAGE_R"
        rows.append(
            {
                "rule_ref": record["rule_ref"],
                "family": record["family"],
                "profile": record["profile"],
                "previous_period": previous,
                "current_period": current,
                "average_r_delta": (
                    _round(float(current_avg) - float(previous_avg))
                    if current_avg is not None and previous_avg is not None
                    else None
                ),
                "net_r_delta": _round(float(current["net_r"]) - float(previous["net_r"])),
                "direction": direction,
            }
        )
    rows.sort(
        key=lambda row: (
            row["direction"] != "DETERIORATING_AVERAGE_R",
            float(row["average_r_delta"]) if row["average_r_delta"] is not None else 0.0,
            row["rule_ref"],
        )
    )
    return rows



def _monthly_batch_evidence(
    events: list[dict[str, Any]],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    teachers: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    teacher_results: Counter[str] = Counter()
    teacher_profiles: Counter[str] = Counter()

    for event in events:
        when = _event_time(event)
        if when is None or when <= start or when > end:
            continue
        payload = event.get("payload") or {}
        if not bool(payload.get("monthly_batch_deferred")):
            continue
        event_type = str(event.get("event_type") or "")
        if event_type == "TEACHER_RESOLVED":
            result = str(payload.get("result") or "UNKNOWN").upper()
            profile = str(payload.get("strategy_profile_key") or "UNKNOWN").lower()
            teacher_results[result] += 1
            teacher_profiles[profile] += 1
            teachers.append(
                {
                    "pair_id": payload.get("pair_id"),
                    "walk_forward_candidate_id": payload.get("walk_forward_candidate_id"),
                    "research_signal_index": payload.get("research_signal_index"),
                    "entry_time": payload.get("entry_time"),
                    "resolution_time": payload.get("resolution_time")
                    or event.get("effective_market_time"),
                    "strategy_profile_key": payload.get("strategy_profile_key"),
                    "side": payload.get("side"),
                    "result": result,
                    "pair_net_r": payload.get("pair_net_r"),
                    "teacher_learning_mode": payload.get("teacher_learning_mode"),
                    "paired_opposite_side": payload.get("paired_opposite_side"),
                    "paired_opposite_net_r": payload.get("paired_opposite_net_r"),
                }
            )
        elif event_type == "REVIEW_COMPLETED" and str(
            payload.get("review_type") or ""
        ).upper() == "LOSS":
            losses.append(
                {
                    "candidate_id": payload.get("candidate_id"),
                    "resolution_time": event.get("effective_market_time"),
                    "decision": payload.get("decision"),
                }
            )

    return {
        "contract": "monthly_batch_oos_evidence_v1",
        "period_start_exclusive": start.isoformat(),
        "period_end": end.isoformat(),
        "rules_frozen_during_period": True,
        "deferred_teacher_count": len(teachers),
        "deferred_teacher_results": dict(sorted(teacher_results.items())),
        "deferred_teacher_profiles": dict(sorted(teacher_profiles.items())),
        "deferred_teacher_observations": teachers,
        "deferred_loss_count": len(losses),
        "deferred_losses": losses,
        "review_instruction": (
            "Use this complete deferred evidence together with OOS trade/rule analytics. "
            "Any ENTRY/VETO/FLIP changes become effective only after this month-end review."
        ),
    }

def summarize_walk_forward_periodic_review(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    review_interval_months: int = 3,
    include_veto_effectiveness: bool = True,
) -> dict[str, Any]:
    """Build a read-only periodic review packet without recording a review or rule change."""
    if isinstance(review_interval_months, bool) or not isinstance(review_interval_months, int):
        raise ValueError("review_interval_months must be an integer")
    if not 1 <= review_interval_months <= 24:
        raise ValueError("review_interval_months must be between 1 and 24")

    _store, readback, events = _verified_experiment(control, experiment_id)
    cursor = _market_cursor(events)
    if cursor is None:
        raise ValueError("experiment has no market-time cursor")
    records = _rule_versions(events)
    trades, attribution_warnings = _trade_history(events, records)

    current_start = cursor - pd.DateOffset(months=review_interval_months)
    previous_start = cursor - pd.DateOffset(months=2 * review_interval_months)
    last_review = _last_periodic_review(events)
    last_review_time = (
        _utc(last_review["effective_market_time"], "periodic review effective_market_time")
        if last_review is not None
        else None
    )

    definition = (readback.get("manifest") or {}).get("definition") or {}
    learning_mode = str(definition.get("learning_mode", "TRADE_BY_TRADE")).strip().upper()
    batch_evidence = (
        _monthly_batch_evidence(events, start=current_start, end=cursor)
        if learning_mode == "MONTHLY_BATCH_OOS"
        else None
    )
    initial_anchor = _initial_periodic_anchor(definition, events, reports)
    anchor = last_review_time or initial_anchor
    due_time = (
        anchor + pd.DateOffset(months=review_interval_months)
        if anchor is not None
        else None
    )

    current_trades = _window_rows(
        trades,
        start=current_start,
        end=cursor,
        time_key="resolved_time",
        start_exclusive=True,
    )
    previous_trades = _window_rows(
        trades,
        start=previous_start,
        end=current_start,
        time_key="resolved_time",
        start_exclusive=True,
    )
    since_review_trades = (
        _window_rows(
            trades,
            start=last_review_time,
            end=cursor,
            time_key="resolved_time",
            start_exclusive=True,
        )
        if last_review_time is not None
        else trades
    )

    comparison = _period_comparison(
        trades,
        records,
        current_start=current_start,
        previous_start=previous_start,
        split=current_start,
        end=cursor,
    )
    deteriorating = [
        row for row in comparison if row["direction"] == "DETERIORATING_AVERAGE_R"
    ]
    improving = [
        row for row in comparison if row["direction"] == "IMPROVING_AVERAGE_R"
    ]

    newly_learned = [
        _public_rule_record(record)
        for record in records
        if current_start < record["_effective_from_ts"] <= cursor
    ]

    current_rule_samples = []
    for record in records:
        if record["family"] == "VETO":
            continue
        current = _performance(
            _window_rows(
                _rule_trade_rows(trades, record["rule_ref"], record["family"]),
                start=current_start,
                end=cursor,
                time_key="resolved_time",
                start_exclusive=True,
            )
        )
        if current["sample_strength"] == "LOW_SAMPLE":
            current_rule_samples.append(
                {
                    "rule_ref": record["rule_ref"],
                    "family": record["family"],
                    "profile": record["profile"],
                    "current_period_trades": current["trades"],
                    "sample_strength": current["sample_strength"],
                }
            )

    veto_current: list[dict[str, Any]] = []
    veto_previous: list[dict[str, Any]] = []
    veto_meta = None
    if include_veto_effectiveness:
        if reports is None:
            raise ValueError("reports service is required when include_veto_effectiveness=true")
        associations, veto_meta = _replay_veto_blocks(
            reports,
            readback,
            events,
            records,
            cursor=cursor,
        )
        for record in records:
            if record["family"] != "VETO":
                continue
            own = [row for row in associations if row.get("rule_ref") == record["rule_ref"]]
            current = _veto_effectiveness(
                _window_rows(
                    own,
                    start=current_start,
                    end=cursor,
                    time_key="time",
                    start_exclusive=True,
                )
            )
            previous = _veto_effectiveness(
                _window_rows(
                    own,
                    start=previous_start,
                    end=current_start,
                    time_key="time",
                    start_exclusive=True,
                )
            )
            if current["blocked_opportunities"] or previous["blocked_opportunities"]:
                veto_current.append(
                    {
                        "rule_ref": record["rule_ref"],
                        "profile": record["profile"],
                        **current,
                    }
                )
                veto_previous.append(
                    {
                        "rule_ref": record["rule_ref"],
                        "profile": record["profile"],
                        **previous,
                    }
                )

    overall_current = _performance(current_trades)
    overall_previous = _performance(previous_trades)
    current_avg = overall_current.get("average_r")
    previous_avg = overall_previous.get("average_r")
    if current_avg is None or previous_avg is None:
        overall_direction = "INSUFFICIENT_COMPARABLE_SAMPLE"
    elif float(current_avg) > float(previous_avg):
        overall_direction = "IMPROVING_AVERAGE_R"
    elif float(current_avg) < float(previous_avg):
        overall_direction = "DETERIORATING_AVERAGE_R"
    else:
        overall_direction = "UNCHANGED_AVERAGE_R"

    return {
        "contract": PERIODIC_REVIEW_SUMMARY_CONTRACT,
        "experiment_id": experiment_id,
        "sequence": int(readback["sequence"]),
        "state_hash": str(readback["state_hash"]),
        "read_only": True,
        "learning_mode": learning_mode,
        "rules_frozen_during_period": learning_mode == "MONTHLY_BATCH_OOS",
        "monthly_batch_evidence": batch_evidence,
        "review_interval_months": review_interval_months,
        "market_cursor": cursor.isoformat(),
        "review_anchor": {
            "source": "LAST_PERIODIC_REVIEW" if last_review_time is not None else (
                "REFERENCE_PERIOD_START" if initial_anchor is not None else None
            ),
            "time": _iso(anchor),
            "due_time": _iso(due_time),
            "overdue": bool(due_time is not None and cursor >= due_time),
            "last_periodic_review_sequence": int(last_review["sequence"]) if last_review is not None else None,
        },
        "periods": {
            "previous": {
                "start_exclusive": previous_start.isoformat(),
                "end": current_start.isoformat(),
                "performance": overall_previous,
            },
            "current": {
                "start_exclusive": current_start.isoformat(),
                "end": cursor.isoformat(),
                "performance": overall_current,
            },
            "since_last_periodic_review": {
                "start_exclusive": _iso(last_review_time),
                "end": cursor.isoformat(),
                "performance": _performance(since_review_trades),
            },
        },
        "overall_direction": overall_direction,
        "monthly_performance": _monthly_performance(
            trades,
            start=previous_start,
            end=cursor,
        ),
        "profile_performance": {
            "previous": _group_performance(
                trades, start=previous_start, end=current_start, key="profile"
            ),
            "current": _group_performance(
                trades, start=current_start, end=cursor, key="profile"
            ),
        },
        "regime_performance": {
            "previous": _group_performance(
                trades, start=previous_start, end=current_start, key="regime"
            ),
            "current": _group_performance(
                trades, start=current_start, end=cursor, key="regime"
            ),
        },
        "rule_period_comparison": comparison,
        "deteriorating_rules": deteriorating,
        "improving_rules": improving,
        "newly_learned_rules": newly_learned,
        "low_sample_rules_current_period": current_rule_samples,
        "veto_effectiveness": {
            "previous": veto_previous,
            "current": veto_current,
            "replay": veto_meta,
        } if include_veto_effectiveness else None,
        "attribution_warnings": attribution_warnings,
        "causal_judgment_note": (
            "This action only assembles evidence. It does not record REVIEW_COMPLETED, "
            "learn/refine/retire a rule, or backdate any change."
        ),
    }
