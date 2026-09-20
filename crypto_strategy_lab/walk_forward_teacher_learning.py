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
    minimum_entry_time: Any | None = None,
) -> tuple[dict[str, Any], Any] | None:
    """Return the next causal teacher boundary.

    Winners become reviewable at their own immutable trade exit. Paired teacher
    losses become reviewable only after BOTH the source teacher trade and its
    immutable opposite-side WALK_FORWARD row have resolved. That delayed boundary
    allows arbitrary R:R FLIP evidence without reading future information at the
    source loss timestamp.
    """
    if "trades" not in (manifest.get("artifacts") or {}):
        return None

    trades_path = artifact_path(run_dir, manifest, "trades", verify=True)
    last = _candidate_impl._last_teacher_time(events)
    reviewed_pairs = _reviewed_teacher_pair_ids(events)
    minimum_entry = (
        _candidate_impl._utc_timestamp(minimum_entry_time, "teacher minimum_entry_time")
        if minimum_entry_time is not None
        else None
    )
    allow_paired_losses = (
        bool(include_losses)
        and _candidate_impl._sampling_mode(manifest) == "WALK_FORWARD"
        and "research_sampling_trades" in (manifest.get("artifacts") or {})
    )

    with duckdb.connect(":memory:") as connection:
        trade_columns = set(_candidate_impl._columns(connection, trades_path))
        required = {"pair_id", "pair_net_r", "exit_time"}
        if required - trade_columns:
            return None
        if allow_paired_losses and not {
            "side", "strategy_profile_key", "entry_time"
        }.issubset(trade_columns):
            allow_paired_losses = False

        optional = [
            name
            for name in ("trade_id", "side", "strategy_profile_key", "entry_time")
            if name in trade_columns
        ]
        selection = [f't."{name}"' for name in ["pair_id", *optional, "pair_net_r"]]

        if allow_paired_losses:
            samples_path = artifact_path(
                run_dir, manifest, "research_sampling_trades", verify=True
            )
            sample_columns = set(_candidate_impl._columns(connection, samples_path))
            required_pair = {
                "walk_forward_candidate_id",
                "walk_forward_candidate_source",
                "side",
                "strategy_profile_key",
                "entry_time",
                "exit_time",
            }
            if required_pair - sample_columns:
                allow_paired_losses = False

        if allow_paired_losses:
            # One validated WALK_FORWARD candidate has exactly one source row and
            # one opposite row. The loss becomes causally knowable for FLIP review
            # at the later of the teacher exit and opposite-side exit.
            sql = f"""
                WITH source_rows AS (
                    SELECT
                        CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                        CAST(entry_time AS TIMESTAMPTZ) AS entry_time,
                        UPPER(CAST(side AS VARCHAR)) AS side,
                        LOWER(CAST(strategy_profile_key AS VARCHAR)) AS profile
                    FROM read_parquet('{_candidate_impl._quote(samples_path)}')
                    WHERE COALESCE(
                        CAST(walk_forward_candidate_source AS BOOLEAN), FALSE
                    )
                ),
                opposite_rows AS (
                    SELECT
                        CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                        UPPER(CAST(side AS VARCHAR)) AS side,
                        CAST(exit_time AS TIMESTAMPTZ) AS exit_time
                    FROM read_parquet('{_candidate_impl._quote(samples_path)}')
                )
                SELECT
                    {", ".join(selection)},
                    CAST(t.exit_time AS TIMESTAMPTZ) AS source_exit_time,
                    CASE
                        WHEN t.pair_net_r > 0
                            THEN CAST(t.exit_time AS TIMESTAMPTZ)
                        ELSE GREATEST(
                            CAST(t.exit_time AS TIMESTAMPTZ),
                            o.exit_time
                        )
                    END AS learning_resolution_time,
                    s.candidate_id AS walk_forward_candidate_id,
                    o.exit_time AS opposite_exit_time
                FROM read_parquet('{_candidate_impl._quote(trades_path)}') t
                LEFT JOIN source_rows s
                  ON CAST(t.entry_time AS TIMESTAMPTZ)=s.entry_time
                 AND UPPER(CAST(t.side AS VARCHAR))=s.side
                 AND LOWER(CAST(t.strategy_profile_key AS VARCHAR))=s.profile
                LEFT JOIN opposite_rows o
                  ON o.candidate_id=s.candidate_id
                 AND o.side<>s.side
                WHERE (
                    t.pair_net_r > 0
                    OR (
                        t.pair_net_r < 0
                        AND s.candidate_id IS NOT NULL
                        AND o.exit_time IS NOT NULL
                    )
                )
                ORDER BY learning_resolution_time, CAST(t.pair_id AS VARCHAR)
            """
        else:
            sql = f"""
                SELECT
                    {", ".join(selection)},
                    CAST(t.exit_time AS TIMESTAMPTZ) AS source_exit_time,
                    CAST(t.exit_time AS TIMESTAMPTZ) AS learning_resolution_time,
                    NULL::VARCHAR AS walk_forward_candidate_id,
                    NULL::TIMESTAMPTZ AS opposite_exit_time
                FROM read_parquet('{_candidate_impl._quote(trades_path)}') t
                WHERE t.pair_net_r > 0
                ORDER BY learning_resolution_time, CAST(t.pair_id AS VARCHAR)
            """

        rows = connection.execute(sql).fetchall()
        names = [
            "pair_id",
            *optional,
            "pair_net_r",
            "source_exit_time",
            "learning_resolution_time",
            "walk_forward_candidate_id",
            "opposite_exit_time",
        ]

    for row in rows:
        values = dict(zip(names, row))
        pair_id = str(values.get("pair_id"))
        if pair_id in reviewed_pairs:
            continue
        if minimum_entry is not None:
            entry_raw = values.get("entry_time")
            if entry_raw is None:
                continue
            if _candidate_impl._utc_timestamp(entry_raw, "teacher entry_time") < minimum_entry:
                continue

        resolution = _candidate_impl._utc_timestamp(
            values["learning_resolution_time"], "teacher learning_resolution_time"
        )
        if last is not None and resolution < last:
            continue

        net_r = float(values.get("pair_net_r"))
        result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
        if result == "BREAKEVEN":
            continue
        if result == "LOSS":
            profile = str(values.get("strategy_profile_key") or "").lower()
            if (
                not allow_paired_losses
                or not profile_supports_teacher_loss_flip(manifest, profile)
                or not values.get("walk_forward_candidate_id")
            ):
                continue

        boundary = {
            key: _candidate_impl._json_safe(value)
            for key, value in values.items()
            if key not in {
                "learning_resolution_time",
                "source_exit_time",
                "opposite_exit_time",
            }
        }
        boundary["result"] = result
        boundary["resolution_time"] = resolution.isoformat()
        boundary["source_trade_resolution_time"] = _candidate_impl._utc_timestamp(
            values["source_exit_time"], "teacher source_exit_time"
        ).isoformat()
        if values.get("opposite_exit_time") is not None:
            boundary["paired_opposite_resolution_time"] = (
                _candidate_impl._utc_timestamp(
                    values["opposite_exit_time"], "teacher opposite_exit_time"
                ).isoformat()
            )
        boundary["teacher_learning_mode"] = (
            TEACHER_WIN_MODE if result == "WIN" else TEACHER_LOSS_FLIP_MODE
        )
        return boundary, resolution

    return None

