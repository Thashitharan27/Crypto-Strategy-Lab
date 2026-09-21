"""Teacher chronology helpers for causal walk-forward learning.

Canonical paired WALK_FORWARD references use overlap-independent source rows as
teacher observations. Portfolio participation controls RESEARCH equity only; it
does not determine teacher eligibility. The paired artifact also persists the
exact opposite-side execution outcome, so resolved teacher losses can be reviewed
as FLIP evidence at any configured R:R without inferring the opposite result.
Loss review remains opt-in through the causal teacher-loss policy.
"""
from __future__ import annotations

import math
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

    Canonical WALK_FORWARD experiments learn from immutable paired source
    observations rather than from the portfolio trades artifact. The paired
    research population deliberately ignores portfolio overlap suppression, so a
    viable observation remains eligible teacher evidence even when
    WAIT_UNTIL_CLOSED would prevent it from becoming a RESEARCH-equity trade.

    Winners become reviewable at their immutable source-row exit. Paired teacher
    losses become reviewable only after BOTH sides resolve and only when the
    exact immutable opposite side is a WIN. Verified LOSS/LOSS and
    LOSS/BREAKEVEN pairs remain in the reference data/analytics but do not
    consume ChatGPT teacher review. Teacher evidence never changes equity.
    """
    artifacts = manifest.get("artifacts") or {}
    last = _candidate_impl._last_teacher_time(events)
    reviewed_pairs = _reviewed_teacher_pair_ids(events)
    minimum_entry = (
        _candidate_impl._utc_timestamp(minimum_entry_time, "teacher minimum_entry_time")
        if minimum_entry_time is not None
        else None
    )
    sampling_mode = _candidate_impl._sampling_mode(manifest)
    samples_available = (
        sampling_mode == "WALK_FORWARD"
        and "research_sampling_trades" in artifacts
    )

    rows: list[tuple[Any, ...]] = []
    names: list[str] = []

    if samples_available:
        samples_path = artifact_path(
            run_dir, manifest, "research_sampling_trades", verify=True
        )
        trades_path = (
            artifact_path(run_dir, manifest, "trades", verify=True)
            if "trades" in artifacts
            else None
        )
        with duckdb.connect(":memory:") as connection:
            sample_columns = set(_candidate_impl._columns(connection, samples_path))
            required_pair = {
                "walk_forward_candidate_id",
                "walk_forward_candidate_source",
                "side",
                "strategy_profile_key",
                "entry_time",
                "exit_time",
                "pair_net_r",
            }
            missing = sorted(required_pair - sample_columns)
            if missing:
                raise ValueError(
                    "paired WALK_FORWARD teacher source is missing columns: "
                    + ", ".join(missing)
                )

            sample_id_sql = (
                "CAST(research_sample_id AS VARCHAR)"
                if "research_sample_id" in sample_columns
                else "NULL::VARCHAR"
            )
            signal_index_sql = (
                "CAST(research_signal_index AS BIGINT)"
                if "research_signal_index" in sample_columns
                else "NULL::BIGINT"
            )

            episode_id_sql = (
                "CAST(research_episode_id AS VARCHAR)"
                if "research_episode_id" in sample_columns
                else "NULL::VARCHAR"
            )
            episode_entry_sql = (
                "CAST(research_episode_entry_number AS BIGINT)"
                if "research_episode_entry_number" in sample_columns
                else "NULL::BIGINT"
            )

            trade_match_cte = ""
            trade_join = ""
            legacy_pair_sql = "NULL::BIGINT"
            legacy_trade_sql = "NULL::VARCHAR"
            if trades_path is not None:
                trade_columns = set(_candidate_impl._columns(connection, trades_path))
                match_required = {
                    "pair_id",
                    "side",
                    "strategy_profile_key",
                    "entry_time",
                }
                if match_required.issubset(trade_columns):
                    legacy_trade_expr = (
                        "CAST(MIN(trade_id) AS VARCHAR)"
                        if "trade_id" in trade_columns
                        else "NULL::VARCHAR"
                    )
                    trade_match_cte = f"""
                    , trade_matches AS (
                        SELECT
                            CAST(entry_time AS TIMESTAMPTZ) AS entry_time,
                            UPPER(CAST(side AS VARCHAR)) AS side,
                            LOWER(CAST(strategy_profile_key AS VARCHAR)) AS profile,
                            COUNT(*) AS match_count,
                            MIN(pair_id) AS legacy_pair_id,
                            {legacy_trade_expr} AS legacy_trade_id
                        FROM read_parquet('{_candidate_impl._quote(trades_path)}')
                        GROUP BY 1, 2, 3
                    )
                    """
                    trade_join = """
                    LEFT JOIN trade_matches tm
                      ON tm.entry_time=s.entry_time
                     AND tm.side=s.side
                     AND tm.profile=s.profile
                    """
                    legacy_pair_sql = (
                        "CASE WHEN tm.match_count=1 THEN tm.legacy_pair_id ELSE NULL END"
                    )
                    legacy_trade_sql = (
                        "CASE WHEN tm.match_count=1 THEN tm.legacy_trade_id ELSE NULL END"
                    )

            sql = f"""
                WITH source_rows AS (
                    SELECT
                        CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                        {sample_id_sql} AS research_sample_id,
                        {signal_index_sql} AS research_signal_index,
                        {episode_id_sql} AS research_episode_id,
                        {episode_entry_sql} AS research_episode_entries_seen_so_far,
                        CAST(entry_time AS TIMESTAMPTZ) AS entry_time,
                        CAST(exit_time AS TIMESTAMPTZ) AS source_exit_time,
                        UPPER(CAST(side AS VARCHAR)) AS side,
                        LOWER(CAST(strategy_profile_key AS VARCHAR)) AS profile,
                        CAST(pair_net_r AS DOUBLE) AS pair_net_r
                    FROM read_parquet('{_candidate_impl._quote(samples_path)}')
                    WHERE COALESCE(
                        CAST(walk_forward_candidate_source AS BOOLEAN), FALSE
                    )
                ),
                opposite_rows AS (
                    SELECT
                        CAST(walk_forward_candidate_id AS VARCHAR) AS candidate_id,
                        COUNT(*) AS opposite_count,
                        MIN(UPPER(CAST(side AS VARCHAR))) AS side,
                        MIN(CAST(exit_time AS TIMESTAMPTZ)) AS exit_time,
                        MIN(CAST(pair_net_r AS DOUBLE)) AS pair_net_r
                    FROM read_parquet('{_candidate_impl._quote(samples_path)}')
                    WHERE NOT COALESCE(
                        CAST(walk_forward_candidate_source AS BOOLEAN), FALSE
                    )
                    GROUP BY 1
                )
                {trade_match_cte}
                SELECT
                    {legacy_pair_sql} AS legacy_pair_id,
                    {legacy_trade_sql} AS trade_id,
                    s.candidate_id AS teacher_observation_id,
                    s.side,
                    s.profile AS strategy_profile_key,
                    s.entry_time,
                    s.pair_net_r,
                    s.source_exit_time,
                    CASE
                        WHEN s.pair_net_r > 0 THEN s.source_exit_time
                        WHEN o.exit_time IS NOT NULL
                            THEN GREATEST(s.source_exit_time, o.exit_time)
                        ELSE NULL
                    END AS learning_resolution_time,
                    s.candidate_id AS walk_forward_candidate_id,
                    o.exit_time AS opposite_exit_time,
                    o.opposite_count,
                    o.side AS opposite_side,
                    o.pair_net_r AS opposite_pair_net_r,
                    s.research_sample_id,
                    s.research_signal_index,
                    s.research_episode_id,
                    s.research_episode_entries_seen_so_far
                FROM source_rows s
                LEFT JOIN opposite_rows o
                  ON o.candidate_id=s.candidate_id
                {trade_join}
                WHERE s.pair_net_r<>0
                ORDER BY learning_resolution_time, s.candidate_id
            """
            rows = connection.execute(sql).fetchall()
            names = [
                "legacy_pair_id",
                "trade_id",
                "teacher_observation_id",
                "side",
                "strategy_profile_key",
                "entry_time",
                "pair_net_r",
                "source_exit_time",
                "learning_resolution_time",
                "walk_forward_candidate_id",
                "opposite_exit_time",
                "opposite_count",
                "opposite_side",
                "opposite_pair_net_r",
                "research_sample_id",
                "research_signal_index",
                "research_episode_id",
                "research_episode_entries_seen_so_far",
            ]
    else:
        if "trades" not in artifacts:
            return None
        trades_path = artifact_path(run_dir, manifest, "trades", verify=True)
        with duckdb.connect(":memory:") as connection:
            trade_columns = set(_candidate_impl._columns(connection, trades_path))
            required = {"pair_id", "pair_net_r", "exit_time"}
            if required - trade_columns:
                return None
            optional = [
                name
                for name in ("trade_id", "side", "strategy_profile_key", "entry_time")
                if name in trade_columns
            ]
            selection = [
                f't."{name}"'
                for name in ["pair_id", *optional, "pair_net_r"]
            ]
            rows = connection.execute(
                f"""
                SELECT
                    {", ".join(selection)},
                    CAST(t.exit_time AS TIMESTAMPTZ) AS source_exit_time,
                    CAST(t.exit_time AS TIMESTAMPTZ) AS learning_resolution_time
                FROM read_parquet('{_candidate_impl._quote(trades_path)}') t
                WHERE t.pair_net_r > 0
                ORDER BY learning_resolution_time, CAST(t.pair_id AS VARCHAR)
                """
            ).fetchall()
            names = [
                "pair_id",
                *optional,
                "pair_net_r",
                "source_exit_time",
                "learning_resolution_time",
            ]

    for row in rows:
        values = dict(zip(names, row))
        if samples_available:
            legacy_pair_id = values.get("legacy_pair_id")
            observation_id = str(values.get("teacher_observation_id") or "").strip()
            teacher_id: Any = (
                legacy_pair_id
                if legacy_pair_id not in (None, "")
                else observation_id
            )
            values["pair_id"] = teacher_id
        pair_id = str(values.get("pair_id"))
        if pair_id in reviewed_pairs:
            continue

        if minimum_entry is not None:
            entry_raw = values.get("entry_time")
            if entry_raw is None:
                continue
            if (
                _candidate_impl._utc_timestamp(entry_raw, "teacher entry_time")
                < minimum_entry
            ):
                continue

        resolution_raw = values.get("learning_resolution_time")
        if resolution_raw is None:
            continue
        resolution = _candidate_impl._utc_timestamp(
            resolution_raw, "teacher learning_resolution_time"
        )
        # Never backfill teacher learning behind an already-processed teacher
        # boundary when upgrading an existing experiment. Fresh experiments see
        # every paired source observation in causal order.
        if last is not None and resolution < last:
            continue

        net_r = float(values.get("pair_net_r"))
        result = "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN")
        if result == "BREAKEVEN":
            continue
        if result == "LOSS":
            profile = str(values.get("strategy_profile_key") or "").lower()
            if (
                not samples_available
                or not bool(include_losses)
                or not profile_supports_teacher_loss_flip(manifest, profile)
                or not values.get("walk_forward_candidate_id")
                or values.get("opposite_exit_time") is None
            ):
                continue

            # Teacher losses are useful only as possible FLIP evidence. Resolve
            # the exact immutable counterfactual deterministically before
            # creating a ChatGPT review boundary. A verified LOSS/BREAKEVEN on
            # the opposite side has no positive directional thesis to judge and
            # is skipped as teacher material. Prospective ENTRY/FLIP trades are
            # completely separate and still settle/review normally.
            opposite_count = int(values.get("opposite_count") or 0)
            if opposite_count != 1:
                raise ValueError(
                    "paired teacher loss has no unique immutable opposite row; "
                    "inspection required"
                )
            expected_opposite = "SHORT" if str(values.get("side")).upper() == "LONG" else "LONG"
            opposite_side = str(values.get("opposite_side") or "").upper()
            if opposite_side != expected_opposite:
                raise ValueError(
                    "paired teacher loss opposite side does not match source side; "
                    "inspection required"
                )
            opposite_raw = values.get("opposite_pair_net_r")
            if opposite_raw is None:
                raise ValueError(
                    "paired teacher loss opposite result is missing; inspection required"
                )
            opposite_net_r = float(opposite_raw)
            if not math.isfinite(opposite_net_r):
                raise ValueError(
                    "paired teacher loss opposite result is not finite; inspection required"
                )
            if opposite_net_r <= 0:
                continue

        excluded = {
            "legacy_pair_id",
            "teacher_observation_id",
            "learning_resolution_time",
            "source_exit_time",
            "opposite_exit_time",
            "opposite_count",
            "opposite_side",
            "opposite_pair_net_r",
        }
        boundary = {
            key: _candidate_impl._json_safe(value)
            for key, value in values.items()
            if key not in excluded
        }
        boundary["pair_id"] = _candidate_impl._json_safe(values.get("pair_id"))
        boundary["result"] = result
        boundary["resolution_time"] = resolution.isoformat()
        boundary["source_trade_resolution_time"] = _candidate_impl._utc_timestamp(
            values["source_exit_time"], "teacher source_exit_time"
        ).isoformat()
        if samples_available:
            boundary["teacher_observation_source"] = "WALK_FORWARD_SOURCE_ROW"
            boundary["portfolio_overlap_suppression_applies"] = False
        else:
            boundary["teacher_observation_source"] = "PORTFOLIO_TRADE"
            boundary["portfolio_overlap_suppression_applies"] = True
        if values.get("opposite_exit_time") is not None:
            boundary["paired_opposite_resolution_time"] = (
                _candidate_impl._utc_timestamp(
                    values["opposite_exit_time"], "teacher opposite_exit_time"
                ).isoformat()
            )
        if result == "LOSS":
            boundary["paired_opposite_side"] = str(
                values.get("opposite_side") or ""
            ).upper()
            boundary["paired_opposite_net_r"] = float(
                values["opposite_pair_net_r"]
            )
        boundary["teacher_learning_mode"] = (
            TEACHER_WIN_MODE if result == "WIN" else TEACHER_LOSS_FLIP_MODE
        )
        return boundary, resolution

    return None

