"""Teacher chronology helpers for causal walk-forward learning.

Teacher/reference trades normally surface winners for ENTRY learning. Paired
walk-forward reference runs also persist the exact opposite-side execution
outcome for each source candidate, so resolved teacher losses can be reviewed as
FLIP evidence at any configured R:R without inferring the opposite result. Loss
review remains opt-in through the causal teacher-loss policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from crypto_strategy_lab import walk_forward_candidate_engine_impl as _candidate_impl
from crypto_strategy_lab.run_manifest import artifact_path


TEACHER_WIN_MODE = "ENTRY_FROM_WINNER"
TEACHER_LOSS_FLIP_MODE = "FLIP_FROM_LOSS_PAIRED"


def _execution_profiles(manifest: dict[str, Any]) -> dict[str, Any]:
    config = manifest.get("config") or {}
    execution_profiles = ((config.get("execution") or {}).get("profiles") or {})
    if execution_profiles:
        return execution_profiles
    # Compatibility fallback for any older normalized snapshots that stored the
    # execution fields with the strategy profiles.
    return ((config.get("strategy") or {}).get("profiles") or {})


def _profile_reward_risk_ratio(manifest: dict[str, Any], profile: str) -> float | None:
    profiles = _execution_profiles(manifest)
    values = profiles.get(str(profile).lower()) or {}
    raw = values.get("reward_risk_ratio")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def profile_supports_teacher_loss_flip(
    manifest: dict[str, Any], profile: str
) -> bool:
    """Return True when the immutable paired WF run contains this execution profile."""
    if _candidate_impl._sampling_mode(manifest) != "WALK_FORWARD":
        return False
    profiles = _execution_profiles(manifest)
    values = profiles.get(str(profile).lower())
    return isinstance(values, dict) and bool(values)


def _eligible_loss_profiles(manifest: dict[str, Any]) -> list[str]:
    profiles = _execution_profiles(manifest)
    return sorted(
        str(profile).lower()
        for profile in profiles
        if profile_supports_teacher_loss_flip(manifest, str(profile))
    )


def _reviewed_teacher_pair_ids(events: list[dict[str, Any]]) -> set[str]:
    reviewed: set[str] = set()
    for event in events:
        if event.get("event_type") != "TEACHER_RESOLVED":
            continue
        pair_id = (event.get("payload") or {}).get("pair_id")
        if pair_id not in (None, ""):
            reviewed.add(str(pair_id))
    return reviewed


def next_teacher_for_learning(
    manifest: dict[str, Any],
    run_dir: Path,
    events: list[dict[str, Any]],
    *,
    include_losses: bool = False,
) -> tuple[dict[str, Any], Any] | None:
    """Return the next causal teacher boundary.

    Winners always remain eligible for ENTRY review. When ``include_losses`` is
    false, only winners teach. When enabled for a paired WALK_FORWARD reference,
    losses are also eligible because their opposite-side outcome was simulated
    immutably at reference-run creation time. Break-even rows remain non-teaching.
    Already-recorded teacher pair ids are excluded explicitly so multiple trades
    sharing one resolution timestamp are not skipped.
    """
    if "trades" not in (manifest.get("artifacts") or {}):
        return None

    path = artifact_path(run_dir, manifest, "trades", verify=True)
    last = _candidate_impl._last_teacher_time(events)
    reviewed_pairs = _reviewed_teacher_pair_ids(events)

    with duckdb.connect(":memory:") as connection:
        columns = set(_candidate_impl._columns(connection, path))
        required = {"pair_id", "pair_net_r", "exit_time"}
        if required - columns:
            return None

        optional = [
            name
            for name in ("trade_id", "side", "strategy_profile_key", "entry_time")
            if name in columns
        ]
        selection = ["pair_id", *optional, "pair_net_r", "exit_time"]

        eligible_loss_profiles = _eligible_loss_profiles(manifest) if include_losses else []
        if "strategy_profile_key" in columns and eligible_loss_profiles:
            placeholders = ", ".join("?" for _ in eligible_loss_profiles)
            where = (
                "(pair_net_r > 0 OR (pair_net_r < 0 AND "
                f"LOWER(CAST(strategy_profile_key AS VARCHAR)) IN ({placeholders})))"
            )
            params: list[Any] = list(eligible_loss_profiles)
        else:
            # Safe fallback: without a paired immutable reference/profile, losses
            # cannot be used as FLIP evidence.
            where = "pair_net_r > 0"
            params = []

        if last is not None:
            # >= plus explicit pair-id de-duplication preserves teachers sharing
            # the same resolution timestamp.
            where += " AND CAST(exit_time AS TIMESTAMPTZ) >= ?"
            params.append(last.to_pydatetime())

        rows = connection.execute(
            f"SELECT {', '.join(selection)} FROM read_parquet('{_candidate_impl._quote(path)}') "
            f"WHERE {where} "
            "ORDER BY CAST(exit_time AS TIMESTAMPTZ), CAST(pair_id AS VARCHAR)",
            params,
        ).fetchall()

    for row in rows:
        values = dict(zip(selection, row))
        pair_id = str(values.get("pair_id"))
        if pair_id in reviewed_pairs:
            continue

        net_r = float(values.get("pair_net_r"))
        result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
        if result == "LOSS":
            profile = str(values.get("strategy_profile_key") or "").lower()
            if not include_losses or not profile_supports_teacher_loss_flip(manifest, profile):
                continue

        resolved = _candidate_impl._utc_timestamp(
            values.pop("exit_time"), "teacher exit_time"
        )
        boundary = {
            key: _candidate_impl._json_safe(value)
            for key, value in values.items()
        }
        boundary["result"] = result
        boundary["resolution_time"] = resolved.isoformat()
        boundary["teacher_learning_mode"] = (
            TEACHER_WIN_MODE if result == "WIN" else TEACHER_LOSS_FLIP_MODE
        )
        return boundary, resolved

    return None
