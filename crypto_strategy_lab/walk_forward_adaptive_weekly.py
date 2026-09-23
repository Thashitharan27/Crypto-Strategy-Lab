"""Read-only evidence for native adaptive weekly walk-forward reviews.

The server computes descriptive evidence only. It never searches thresholds,
selects rules, or mutates ENTRY/VETO/FLIP state.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from crypto_strategy_lab import walk_forward_candidate_engine_impl as candidate_impl
from crypto_strategy_lab import walk_forward_rule_analytics as analytics


ADAPTIVE_EVIDENCE_CONTRACT = "adaptive_weekly_evidence_v1"


def _utc(value: Any, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError(f"{name} is missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _stats(values: list[float]) -> dict[str, Any]:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    breakevens = len(values) - wins - losses
    return {
        "trades": len(values),
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate_pct": round(100.0 * wins / len(values), 2) if values else None,
        "net_r": round(sum(values), 10) if values else 0.0,
        "average_r": round(sum(values) / len(values), 10) if values else None,
    }


def _artifact_path(manifest: dict[str, Any], run_dir: Path, key: str) -> Path:
    return candidate_impl._artifact(manifest, run_dir, key)


def _reference_rows(
    samples_path: Path,
    context_path: Path,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    with duckdb.connect(":memory:") as connection:
        sample_columns = candidate_impl._columns(connection, samples_path)
        context_columns = candidate_impl._columns(connection, context_path)
        required = {
            "research_signal_index",
            "strategy_profile_key",
            "side",
            "entry_time",
            "exit_time",
            "pair_net_r",
            "walk_forward_candidate_id",
            "walk_forward_candidate_source",
        }
        missing = required - set(sample_columns)
        if missing:
            raise ValueError(
                "paired source artifact is missing adaptive history columns: "
                + ", ".join(sorted(missing))
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
              AND CAST(t.exit_time AS TIMESTAMPTZ) > ?
              AND CAST(t.exit_time AS TIMESTAMPTZ) <= ?
            ORDER BY CAST(t.exit_time AS TIMESTAMPTZ),
                     CAST(t.research_signal_index AS BIGINT)
        """
        statement = connection.execute(
            sql, [start.to_pydatetime(), end.to_pydatetime()]
        )
        columns = [str(item[0]) for item in statement.description]
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        while True:
            batch = statement.fetchmany(4096)
            if not batch:
                break
            frame = pd.DataFrame.from_records(batch, columns=columns)
            for _, series in frame.iterrows():
                result.append(candidate_impl._row_maps(series))
        return result


def _opposite_net_r(
    samples_path: Path,
    *,
    candidate_id: str,
    target_side: str,
    boundary: pd.Timestamp,
) -> float | None:
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            f"""
            SELECT CAST(pair_net_r AS DOUBLE), CAST(exit_time AS TIMESTAMPTZ)
            FROM read_parquet('{candidate_impl._quote(samples_path)}')
            WHERE CAST(walk_forward_candidate_id AS VARCHAR)=?
              AND UPPER(CAST(side AS VARCHAR))=?
              AND NOT COALESCE(CAST(walk_forward_candidate_source AS BOOLEAN), FALSE)
            LIMIT 3
            """,
            [candidate_id, target_side],
        ).fetchall()
    if len(rows) != 1 or rows[0][0] is None or rows[0][1] is None:
        return None
    if _utc(rows[0][1], "opposite exit_time") > boundary:
        return None
    return float(rows[0][0])


def _rule_matches(
    rows: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    record: dict[str, Any],
    base_config: dict[str, Any],
    samples_path: Path,
    boundary: pd.Timestamp,
) -> tuple[list[dict[str, Any]], int]:
    matched: list[dict[str, Any]] = []
    profile_available = 0
    family = str(record["family"])
    profile = str(record["profile"])
    for row, _feature_context in rows:
        row_profile = str(row.get("strategy_profile_key") or "").strip().lower()
        side = str(row.get("side") or "").strip().upper()
        if row_profile != profile or side not in {"LONG", "SHORT"}:
            continue
        profile_available += 1
        is_match, _details = candidate_impl._group_match(
            row, side, row_profile, record["group"], base_config
        )
        if not is_match:
            continue
        source_r_raw = row.get("pair_net_r")
        if source_r_raw is None or pd.isna(source_r_raw):
            continue
        source_r = float(source_r_raw)
        value: float | None
        if family == "ENTRY":
            value = source_r
        elif family == "VETO":
            # Positive means the VETO would have saved R; negative means it
            # contradicted a raw winner.
            value = -source_r
        elif family == "FLIP":
            candidate_id = str(row.get("walk_forward_candidate_id") or "").strip()
            target_side = "SHORT" if side == "LONG" else "LONG"
            value = (
                _opposite_net_r(
                    samples_path,
                    candidate_id=candidate_id,
                    target_side=target_side,
                    boundary=boundary,
                )
                if candidate_id
                else None
            )
        else:
            value = None
        if value is None:
            continue
        matched.append(
            {
                "value_r": float(value),
                "entry_time": str(row.get("entry_time") or ""),
                "resolved_time": str(row.get("exit_time") or ""),
                "source_side": side,
            }
        )
    return matched, profile_available


def _match_summary(
    matched: list[dict[str, Any]],
    *,
    profile_available: int,
) -> dict[str, Any]:
    values = [float(item["value_r"]) for item in matched]
    perf = _stats(values)
    perf.update(
        {
            "matches": len(values),
            "support_count": sum(value > 0 for value in values),
            "contradiction_count": sum(value < 0 for value in values),
            "profile_available_observations": int(profile_available),
            "last_match": matched[-1]["entry_time"] if matched else None,
            "last_resolved_match": matched[-1]["resolved_time"] if matched else None,
        }
    )
    return perf


def _adaptive_status(
    *,
    lifecycle_status: str,
    learning: dict[str, Any],
    recent: dict[str, Any],
) -> str:
    if lifecycle_status == "RETIRED":
        return "RETIRED"
    if int(recent["matches"]) == 0:
        return "DORMANT_NO_EXPOSURE"
    learning_net = float(learning.get("net_r") or 0.0)
    recent_net = float(recent.get("net_r") or 0.0)
    support = int(recent.get("support_count") or 0)
    contradictions = int(recent.get("contradiction_count") or 0)
    if learning.get("matches") and learning_net > 0 and recent_net < 0:
        return "DECAYING"
    if int(recent["matches"]) >= 3 and recent_net < 0 and contradictions > support:
        return "CONTRADICTED"
    if recent_net >= 0:
        learning_avg = learning.get("average_r")
        recent_avg = recent.get("average_r")
        if (
            contradictions > 0
            and learning_avg is not None
            and recent_avg is not None
            and float(recent_avg) < float(learning_avg)
        ):
            return "ACTIVE_WEAKENING"
        return "ACTIVE_SUPPORTED"
    return "ACTIVE_WEAKENING"


def build_adaptive_source_history(
    control: Any,
    reports: Any,
    *,
    experiment_id: str,
    end: pd.Timestamp,
    policy: dict[str, Any],
) -> dict[str, Any]:
    _store, readback, events = analytics._verified_experiment(control, experiment_id)
    definition = (readback.get("manifest") or {}).get("definition") or {}
    reference_run = str(definition.get("reference_run") or "").strip()
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    base_config = manifest.get("config")
    if not isinstance(base_config, dict):
        raise ValueError("reference run has no normalized config for adaptive history")
    samples_path = _artifact_path(manifest, run_dir, "research_sampling_trades")
    context_path = _artifact_path(manifest, run_dir, "feature_context")

    records = analytics._rule_versions(events)
    context_weeks = int(policy["context_lookback_weeks"])
    primary_weeks = int(policy["primary_lookback_weeks"])
    context_start = end - pd.DateOffset(weeks=context_weeks)
    primary_start = end - pd.DateOffset(weeks=primary_weeks)
    context_rows = _reference_rows(
        samples_path, context_path, start=context_start, end=end
    )
    recent_records = [
        record
        for record in records
        if record["lifecycle_status"] == "ACTIVE"
        or (
            record.get("_effective_until_ts") is not None
            and record["_effective_until_ts"] > context_start
        )
    ]

    rule_rows: list[dict[str, Any]] = []
    for record in recent_records:
        learned_at = record["_effective_from_ts"]
        learning_start = learned_at - pd.DateOffset(weeks=1)
        learning_rows = _reference_rows(
            samples_path,
            context_path,
            start=learning_start,
            end=learned_at,
        )
        learning_matches, learning_available = _rule_matches(
            learning_rows,
            record=record,
            base_config=base_config,
            samples_path=samples_path,
            boundary=learned_at,
        )
        learning = _match_summary(
            learning_matches, profile_available=learning_available
        )

        recent_start = max(primary_start, learned_at)
        recent_rows = [
            pair
            for pair in context_rows
            if _utc(pair[0].get("exit_time"), "source exit_time") > recent_start
        ]
        recent_matches, recent_available = _rule_matches(
            recent_rows,
            record=record,
            base_config=base_config,
            samples_path=samples_path,
            boundary=end,
        )
        recent = _match_summary(
            recent_matches, profile_available=recent_available
        )

        weekly_history: list[dict[str, Any]] = []
        bucket_start = max(learned_at, context_start)
        age = 0
        while bucket_start < end:
            bucket_end = min(bucket_start + pd.DateOffset(weeks=1), end)
            bucket_rows = [
                pair
                for pair in context_rows
                if bucket_start
                < _utc(pair[0].get("exit_time"), "source exit_time")
                <= bucket_end
            ]
            bucket_matches, bucket_available = _rule_matches(
                bucket_rows,
                record=record,
                base_config=base_config,
                samples_path=samples_path,
                boundary=bucket_end,
            )
            weekly_history.append(
                {
                    "age_week": age + 1,
                    "start_exclusive": bucket_start.isoformat(),
                    "end_inclusive": bucket_end.isoformat(),
                    **_match_summary(
                        bucket_matches, profile_available=bucket_available
                    ),
                }
            )
            bucket_start = bucket_end
            age += 1

        age_weeks = max(
            0, int((end - learned_at).total_seconds() // (7 * 24 * 3600))
        )
        status = _adaptive_status(
            lifecycle_status=str(record["lifecycle_status"]),
            learning=learning,
            recent=recent,
        )
        rule_rows.append(
            {
                "rule_id": record["rule_id"],
                "rule_version": record["rule_version"],
                "rule_ref": record["rule_ref"],
                "family": record["family"],
                "profile": record["profile"],
                "learned_at": learned_at.isoformat(),
                "age_weeks": age_weeks,
                "learning_window": {
                    "start_exclusive": learning_start.isoformat(),
                    "end_inclusive": learned_at.isoformat(),
                    **learning,
                },
                "weekly_history": weekly_history,
                "recent_window": {
                    "weeks": primary_weeks,
                    "start_exclusive": recent_start.isoformat(),
                    "end_inclusive": end.isoformat(),
                    **recent,
                },
                "recent_matches": recent["matches"],
                "recent_wins": recent["wins"],
                "recent_losses": recent["losses"],
                "recent_net_r": recent["net_r"],
                "support_count": recent["support_count"],
                "contradiction_count": recent["contradiction_count"],
                "regime_available_observations": recent[
                    "profile_available_observations"
                ],
                "last_match": recent["last_match"],
                "status": status,
                "lifecycle_note": (
                    "Descriptive only. The server never retires/refines/replaces a "
                    "rule from this status; ChatGPT must record any structural change."
                ),
                "metric_semantics": (
                    "executed R"
                    if record["family"] in {"ENTRY", "FLIP"}
                    else "R saved by blocking the raw source trade"
                ),
            }
        )

    return {
        "available": True,
        "contract": ADAPTIVE_EVIDENCE_CONTRACT,
        "basis": (
            "paired immutable source observations resolved by each causal boundary; "
            "rule matching is descriptive and performs no threshold search"
        ),
        "primary_lookback_weeks": primary_weeks,
        "context_lookback_weeks": context_weeks,
        "rules": rule_rows,
        "status_values": [
            "ACTIVE_SUPPORTED",
            "ACTIVE_WEAKENING",
            "DORMANT_NO_EXPOSURE",
            "DECAYING",
            "CONTRADICTED",
            "RETIRED",
        ],
    }


def _pick_column(columns: set[str], choices: tuple[str, ...]) -> str | None:
    for name in choices:
        if name in columns:
            return name
    return None


def build_raw_strategy_benchmark(
    reports: Any,
    *,
    definition: dict[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
    adaptive_prospective: list[dict[str, Any]],
) -> dict[str, Any]:
    reference_run = str(definition.get("reference_run") or "").strip()
    manifest = reports.get_run_manifest(reference_run)
    run_dir = reports.resolve_run(reference_run)
    trades_path = _artifact_path(manifest, run_dir, "trades")
    config = manifest.get("config") or {}

    with duckdb.connect(":memory:") as connection:
        columns = set(candidate_impl._columns(connection, trades_path))
        r_col = _pick_column(columns, ("net_r", "pair_net_r", "r_multiple"))
        exit_col = _pick_column(columns, ("exit_time", "resolved_time"))
        entry_col = _pick_column(columns, ("entry_time", "signal_time"))
        side_col = _pick_column(columns, ("side", "direction"))
        profile_col = _pick_column(columns, ("strategy_profile_key", "profile"))
        if r_col is None or exit_col is None:
            raise ValueError(
                "reference portfolio trades do not expose net R and exit_time"
            )
        selects = [
            f'CAST("{r_col}" AS DOUBLE) AS net_r',
            f'CAST("{exit_col}" AS TIMESTAMPTZ) AS exit_time',
        ]
        selects.append(
            f'CAST("{entry_col}" AS TIMESTAMPTZ) AS entry_time'
            if entry_col
            else "NULL AS entry_time"
        )
        selects.append(
            f'UPPER(CAST("{side_col}" AS VARCHAR)) AS side'
            if side_col
            else "NULL AS side"
        )
        selects.append(
            f'LOWER(CAST("{profile_col}" AS VARCHAR)) AS profile'
            if profile_col
            else "NULL AS profile"
        )
        rows = connection.execute(
            f"""
            SELECT {', '.join(selects)}
            FROM read_parquet('{candidate_impl._quote(trades_path)}')
            WHERE CAST("{exit_col}" AS TIMESTAMPTZ) > ?
              AND CAST("{exit_col}" AS TIMESTAMPTZ) <= ?
            ORDER BY CAST("{exit_col}" AS TIMESTAMPTZ)
            """,
            [start.to_pydatetime(), end.to_pydatetime()],
        ).fetchall()

    values = [float(row[0]) for row in rows if row[0] is not None]
    raw = _stats(values)
    adaptive_values = [
        float(row["net_r"])
        for row in adaptive_prospective
        if row.get("net_r") is not None
    ]
    adaptive = _stats(adaptive_values)

    def find_config(key: str, node: Any) -> Any:
        if isinstance(node, dict):
            if key in node:
                return node[key]
            for child in node.values():
                found = find_config(key, child)
                if found is not None:
                    return found
        return None

    return {
        "available": True,
        "benchmark_kind": "RAW_REFERENCE_PORTFOLIO",
        "reference_run": reference_run,
        "window": {
            "start_exclusive": start.isoformat(),
            "end_inclusive": end.isoformat(),
        },
        "execution_contract": {
            "entry_mode": find_config("entry_mode", config),
            "max_active_pairs": find_config("max_active_pairs", config),
            "strategy_profile_run_mode": find_config(
                "strategy_profile_run_mode", config
            ),
            "risk_model": deepcopy(definition.get("risk_model")),
            "risk_pct_legacy": definition.get("risk_pct"),
            "fees_slippage": "inherited from immutable reference run outcomes",
        },
        "raw_strategy": raw,
        "frozen_adaptive_oos": adaptive,
        "adaptive_value_added": {
            "trade_count_delta": adaptive["trades"] - raw["trades"],
            "net_r_delta": round(
                float(adaptive["net_r"]) - float(raw["net_r"]), 10
            ),
            "win_rate_pct_delta": (
                round(
                    float(adaptive["win_rate_pct"]) - float(raw["win_rate_pct"]),
                    2,
                )
                if adaptive["win_rate_pct"] is not None
                and raw["win_rate_pct"] is not None
                else None
            ),
        },
        "note": (
            "Raw uses the reference run's actual portfolio trades, not the paired "
            "teacher population, so its WAIT_UNTIL_CLOSED/capital/profile behavior "
            "and configured fees/slippage are preserved."
        ),
    }
