"""Shared-account replay from completed Every Viable Entry research outputs.

This module deliberately does not rerun indicators or strategy logic.  It consumes
validated ``research_sampling_trades`` artifacts produced by finalized completed
runs, treats those rows as candidate opportunities, and reapplies portfolio
occupancy/risk policy chronologically.

The resulting equity curve is a *closed-equity* replay.  The resilience artifacts
contain entry/exit outcomes but not a synchronized mark-to-market journey for every
candidate, so intratrade/mark-to-market drawdown is intentionally not claimed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import heapq
import json
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_lab.run_manifest import (
    RunArtifactError,
    artifact_path,
    atomic_json,
    load_completed_manifest,
)


PORTFOLIO_REPLAY_VERSION = "EVERY_VIABLE_PORTFOLIO_REPLAY_V1"
REQUIRED_SAMPLE_COLUMNS = {
    "research_sample_id",
    "research_sampling_mode",
    "research_signal_index",
    "side",
    "entry_time",
    "exit_time",
    "pair_net_r",
}


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def inspect_resilience_run(run_dir: Path | str) -> dict:
    """Return validated metadata for one Every Viable Entry completed run."""
    run_dir = Path(run_dir)
    manifest = load_completed_manifest(run_dir)
    sampling = manifest.get("research", {}).get("strategy_research_sampling")
    if not isinstance(sampling, dict):
        raise RunArtifactError("completed run has no strategy resilience sampling")
    mode = str(sampling.get("mode", "")).upper()
    if mode != "EVERY_VIABLE_ENTRY":
        raise RunArtifactError(
            "portfolio replay requires an Every Viable Entry resilience run"
        )
    # Resolve and hash-verify the candidate artifact now.  Discovery therefore
    # never offers a run whose portfolio input is missing or has been modified.
    samples_path = artifact_path(
        run_dir, manifest, "research_sampling_trades", verify=True
    )
    request = manifest.get("request", {})
    artifact = manifest.get("artifacts", {}).get("research_sampling_trades", {})
    symbol = str(request.get("symbol") or run_dir.name.split("_")[0]).upper()
    return {
        "run_dir": run_dir.resolve(),
        "run_id": str(manifest.get("run_id", run_dir.name)),
        "symbol": symbol,
        "strategy_timeframe": request.get("requested_strategy_interval"),
        "period_start": _utc(request.get("start")),
        "period_end": _utc(request.get("end")),
        "completed_at": manifest.get("run_completed_at"),
        "sampling_mode": mode,
        "candidate_rows": int(artifact.get("rows") or sampling.get("selected_rows") or 0),
        "samples_path": samples_path,
        "code_commit": manifest.get("code_commit"),
        "strategy_hash": manifest.get("hashes", {}).get("strategy_hash"),
        "execution_hash": manifest.get("hashes", {}).get("execution_hash"),
        "feature_config_hash": manifest.get("hashes", {}).get("feature_config_hash"),
        "data_config_hash": manifest.get("hashes", {}).get("data_config_hash"),
    }


def discover_resilience_runs(output_root: Path | str) -> list[dict]:
    """Find hash-valid Every Viable Entry runs directly below an output root."""
    root = Path(output_root)
    if not root.is_dir():
        return []
    rows = []
    for child in root.iterdir():
        if not child.is_dir() or not (child / "run_manifest.json").is_file():
            continue
        try:
            rows.append(inspect_resilience_run(child))
        except (RunArtifactError, OSError, ValueError, TypeError):
            continue
    rows.sort(
        key=lambda item: (str(item.get("completed_at") or ""), item["symbol"]),
        reverse=True,
    )
    return rows


def _read_candidates(metadata: dict, component_priority: int) -> pd.DataFrame:
    path = Path(metadata["samples_path"])
    with duckdb.connect() as con:
        frame = con.execute(
            "SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchdf()
    missing = sorted(REQUIRED_SAMPLE_COLUMNS - set(frame.columns))
    if missing:
        raise RunArtifactError(
            f"{metadata['symbol']} resilience candidates are missing columns: {missing}"
        )
    if frame.empty:
        result = frame.copy()
        for name in (
            "portfolio_asset",
            "portfolio_source_run_id",
            "portfolio_source_run_dir",
            "portfolio_candidate_key",
        ):
            result[name] = pd.Series(dtype="string")
        result["portfolio_component_priority"] = pd.Series(dtype="int64")
        return result

    frame = frame.copy()
    mode = frame["research_sampling_mode"].astype(str).str.upper()
    if not mode.eq("EVERY_VIABLE_ENTRY").all():
        raise RunArtifactError(
            f"{metadata['symbol']} candidate artifact mixes non Every Viable Entry rows"
        )
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="raise")
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="raise")
    if frame["exit_time"].lt(frame["entry_time"]).any():
        raise RunArtifactError(
            f"{metadata['symbol']} candidate artifact contains exit-before-entry rows"
        )
    frame["pair_net_r"] = pd.to_numeric(frame["pair_net_r"], errors="raise")
    if not np.isfinite(frame["pair_net_r"].to_numpy(dtype=float)).all():
        raise RunArtifactError(
            f"{metadata['symbol']} candidate artifact contains non-finite pair_net_r"
        )
    frame["portfolio_asset"] = metadata["symbol"]
    frame["portfolio_source_run_id"] = metadata["run_id"]
    frame["portfolio_source_run_dir"] = str(metadata["run_dir"])
    frame["portfolio_component_priority"] = int(component_priority)
    frame["portfolio_candidate_key"] = (
        metadata["symbol"]
        + ":"
        + metadata["run_id"]
        + ":"
        + frame["research_sample_id"].astype(str)
    )
    if frame["portfolio_candidate_key"].duplicated().any():
        raise RunArtifactError(
            f"{metadata['symbol']} portfolio candidate keys are not unique"
        )
    return frame


def _periodic(realized: pd.DataFrame, frequency: str, initial_equity: float) -> pd.DataFrame:
    columns = [
        "timestamp",
        "trade_count",
        "net_pnl",
        "ending_equity",
        "starting_equity",
        "return_percentage",
    ]
    if realized.empty:
        return pd.DataFrame(columns=columns)
    frame = realized.copy().set_index("timestamp")
    alternatives = {
        "ME": ("ME", "M"),
        "M": ("ME", "M"),
        "YE": ("YE", "Y"),
        "Y": ("YE", "Y"),
    }.get(frequency, (frequency,))
    last_error = None
    for compatible in alternatives:
        try:
            grouped = frame.resample(compatible).agg(
                trade_count=("portfolio_pnl", "size"),
                net_pnl=("portfolio_pnl", "sum"),
            )
            break
        except ValueError as exc:
            last_error = exc
    else:
        raise last_error
    grouped["ending_equity"] = float(initial_equity) + grouped["net_pnl"].cumsum()
    grouped["starting_equity"] = grouped["ending_equity"].shift(
        fill_value=float(initial_equity)
    )
    grouped["return_percentage"] = (
        grouped["net_pnl"] / grouped["starting_equity"] * 100.0
    )
    return grouped.reset_index()


def _maximum_losing_streak(monthly: pd.DataFrame) -> int:
    if monthly.empty:
        return 0
    negative = monthly["net_pnl"].lt(0).astype(int)
    groups = negative.ne(negative.shift()).cumsum()
    return int(negative.groupby(groups).sum().max())


def _replay(
    candidates: pd.DataFrame,
    *,
    initial_equity: float,
    risk_fraction: float,
    maximum_total_risk: float,
    maximum_open_positions: int,
    one_active_trade_per_symbol: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    frame = candidates.copy()
    defaults = {
        "portfolio_accepted": False,
        "portfolio_block_reason": "",
        "portfolio_entry_equity": np.nan,
        "portfolio_risk_amount": np.nan,
        "portfolio_open_risk_before": np.nan,
        "portfolio_open_positions_before": np.nan,
        "portfolio_pnl": np.nan,
        "portfolio_equity_after_exit": np.nan,
        "portfolio_exit_sequence": np.nan,
    }
    for name, value in defaults.items():
        frame[name] = value
    frame.loc[~frame["portfolio_in_scope"], "portfolio_block_reason"] = (
        "OUTSIDE_REPLAY_PERIOD"
    )

    equity = float(initial_equity)
    peak = equity
    closed_drawdown = 0.0
    active: dict[str, dict] = {}
    active_symbols: Counter[str] = Counter()
    exit_heap: list[tuple[int, int, str]] = []
    realized_rows: list[dict] = []
    maximum_observed_open_positions = 0
    maximum_observed_open_risk_fraction = 0.0
    accepted_sequence = 0
    exit_sequence = 0

    row_by_key = {
        str(key): index
        for index, key in zip(frame.index, frame["portfolio_candidate_key"])
    }

    def open_risk_amount() -> float:
        return float(sum(item["risk_amount"] for item in active.values()))

    def close_due(timestamp: pd.Timestamp | None = None, *, force: bool = False) -> None:
        nonlocal equity, peak, closed_drawdown, exit_sequence
        threshold = None if timestamp is None else int(timestamp.value)
        while exit_heap and (force or exit_heap[0][0] <= threshold):
            _exit_ns, _accepted_order, key = heapq.heappop(exit_heap)
            trade = active.pop(key, None)
            if trade is None:
                continue
            symbol = trade["asset"]
            active_symbols[symbol] -= 1
            if active_symbols[symbol] <= 0:
                del active_symbols[symbol]
            pnl = trade["risk_amount"] * trade["pair_net_r"]
            equity += pnl
            peak = max(peak, equity)
            drawdown = equity / peak - 1.0 if peak else 0.0
            closed_drawdown = min(closed_drawdown, drawdown)
            exit_sequence += 1
            realized_rows.append(
                {
                    "timestamp": trade["exit_time"],
                    "asset": symbol,
                    "portfolio_candidate_key": key,
                    "portfolio_result_multiple": trade["pair_net_r"],
                    "portfolio_risk_amount": trade["risk_amount"],
                    "portfolio_pnl": pnl,
                    "portfolio_equity": equity,
                    "portfolio_drawdown": drawdown,
                    "portfolio_exit_sequence": exit_sequence,
                }
            )
            frame_index = row_by_key[key]
            frame.at[frame_index, "portfolio_pnl"] = pnl
            frame.at[frame_index, "portfolio_equity_after_exit"] = equity
            frame.at[frame_index, "portfolio_exit_sequence"] = exit_sequence

    eligible = frame.loc[frame["portfolio_in_scope"]].sort_values(
        [
            "entry_time",
            "portfolio_asset",
            "research_signal_index",
            "portfolio_candidate_key",
        ],
        kind="stable",
    )

    for row in eligible.itertuples():
        entry_time = row.entry_time
        close_due(entry_time)
        key = str(row.portfolio_candidate_key)
        symbol = str(row.portfolio_asset)
        index = row.Index
        open_risk = open_risk_amount()
        open_positions = len(active)
        frame.at[index, "portfolio_open_risk_before"] = open_risk
        frame.at[index, "portfolio_open_positions_before"] = open_positions

        reason = ""
        if equity <= 0:
            reason = "NON_POSITIVE_EQUITY"
        elif one_active_trade_per_symbol and active_symbols.get(symbol, 0):
            reason = "SYMBOL_ACTIVE"
        elif open_positions >= maximum_open_positions:
            reason = "MAXIMUM_OPEN_POSITIONS"
        else:
            risk_amount = equity * risk_fraction
            risk_limit = equity * maximum_total_risk
            if open_risk + risk_amount > risk_limit + 1e-12:
                reason = "MAXIMUM_TOTAL_PORTFOLIO_RISK"

        if reason:
            frame.at[index, "portfolio_block_reason"] = reason
            continue

        risk_amount = equity * risk_fraction
        frame.at[index, "portfolio_accepted"] = True
        frame.at[index, "portfolio_entry_equity"] = equity
        frame.at[index, "portfolio_risk_amount"] = risk_amount
        accepted_sequence += 1
        active[key] = {
            "asset": symbol,
            "exit_time": row.exit_time,
            "pair_net_r": float(row.pair_net_r),
            "risk_amount": risk_amount,
        }
        active_symbols[symbol] += 1
        heapq.heappush(
            exit_heap,
            (int(row.exit_time.value), accepted_sequence, key),
        )
        maximum_observed_open_positions = max(
            maximum_observed_open_positions, len(active)
        )
        if equity > 0:
            maximum_observed_open_risk_fraction = max(
                maximum_observed_open_risk_fraction,
                open_risk_amount() / equity,
            )

    close_due(force=True)
    realized = pd.DataFrame(realized_rows)
    if not realized.empty:
        realized = realized.sort_values(
            ["timestamp", "portfolio_exit_sequence"], kind="stable"
        ).reset_index(drop=True)

    in_scope = frame["portfolio_in_scope"]
    accepted = frame["portfolio_accepted"]
    reasons = (
        frame.loc[in_scope & ~accepted, "portfolio_block_reason"]
        .value_counts()
        .to_dict()
    )
    replay_stats = {
        "candidate_rows_total": int(len(frame)),
        "candidate_rows_in_scope": int(in_scope.sum()),
        "accepted_trades": int(accepted.sum()),
        "blocked_candidates": int((in_scope & ~accepted).sum()),
        "blocked_by_reason": {str(key): int(value) for key, value in reasons.items()},
        "maximum_observed_open_positions": int(maximum_observed_open_positions),
        "maximum_observed_open_risk_fraction": float(
            maximum_observed_open_risk_fraction
        ),
        "ending_equity": float(equity),
        "closed_equity_maximum_drawdown_percentage": float(closed_drawdown * 100.0),
    }
    return frame, realized, replay_stats


def run_portfolio_replay(
    run_dirs: Iterable[Path | str],
    *,
    output_root: Path | str = "output/data_lake_v2",
    initial_equity: float = 1000.0,
    risk_per_trade: float = 0.01,
    maximum_total_risk: float = 0.05,
    maximum_open_positions: int = 5,
    one_active_trade_per_symbol: bool = True,
    common_period_only: bool = True,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, Path]:
    """Replay finalized Every Viable Entry outputs against one shared account."""
    paths = [Path(item) for item in run_dirs]
    if len(paths) < 2:
        raise ValueError("Portfolio replay requires at least two completed runs.")
    if initial_equity <= 0:
        raise ValueError("Initial equity must be positive.")
    if not 0 < float(risk_per_trade) <= float(maximum_total_risk) < 1:
        raise ValueError(
            "Portfolio risk settings must satisfy 0 < risk per trade <= maximum total risk < 100%."
        )
    if int(maximum_open_positions) <= 0:
        raise ValueError("Maximum open positions must be positive.")

    metadata = [inspect_resilience_run(path) for path in paths]
    symbols = [item["symbol"] for item in metadata]
    duplicates = sorted(symbol for symbol, count in Counter(symbols).items() if count > 1)
    if duplicates:
        raise ValueError(
            "Select only one finalized run per symbol; duplicates: "
            + ", ".join(duplicates)
        )

    # Same-timestamp capacity decisions are intentionally deterministic and
    # independent of GUI scan order.
    metadata.sort(key=lambda item: item["symbol"])
    common_start = max(item["period_start"] for item in metadata)
    common_end = min(item["period_end"] for item in metadata)
    if common_period_only and common_start >= common_end:
        raise ValueError("Selected runs do not share an overlapping replay period.")

    candidate_frames = [
        _read_candidates(item, priority)
        for priority, item in enumerate(metadata)
    ]
    candidates = pd.concat(candidate_frames, ignore_index=True, sort=False)
    if candidates.empty:
        raise ValueError("Selected Every Viable Entry runs contain no resolved candidates.")

    if common_period_only:
        candidates["portfolio_in_scope"] = (
            candidates["entry_time"].ge(common_start)
            & candidates["exit_time"].le(common_end)
        )
        replay_start, replay_end = common_start, common_end
    else:
        candidates["portfolio_in_scope"] = True
        replay_start = min(item["period_start"] for item in metadata)
        replay_end = max(item["period_end"] for item in metadata)

    candidates, realized, replay_stats = _replay(
        candidates,
        initial_equity=float(initial_equity),
        risk_fraction=float(risk_per_trade),
        maximum_total_risk=float(maximum_total_risk),
        maximum_open_positions=int(maximum_open_positions),
        one_active_trade_per_symbol=bool(one_active_trade_per_symbol),
    )

    monthly = _periodic(realized, "ME", float(initial_equity))
    yearly = _periodic(realized, "YE", float(initial_equity))
    component_rows = []
    for item in metadata:
        symbol = item["symbol"]
        rows = candidates[candidates["portfolio_asset"].eq(symbol)]
        accepted = rows[rows["portfolio_accepted"]]
        resolved_r = pd.to_numeric(accepted["pair_net_r"], errors="coerce")
        component_rows.append(
            {
                "asset": symbol,
                "source_run_id": item["run_id"],
                "source_run_dir": str(item["run_dir"]),
                "candidate_rows": int(len(rows)),
                "in_scope_candidates": int(rows["portfolio_in_scope"].sum()),
                "accepted_trades": int(len(accepted)),
                "blocked_candidates": int(
                    (rows["portfolio_in_scope"] & ~rows["portfolio_accepted"]).sum()
                ),
                "wins": int(resolved_r.gt(0).sum()),
                "losses": int(resolved_r.lt(0).sum()),
                "win_rate": float(resolved_r.gt(0).mean()) if len(resolved_r) else np.nan,
                "net_r_of_accepted_candidates": (
                    float(resolved_r.sum()) if len(resolved_r) else 0.0
                ),
                "portfolio_pnl_contribution": float(
                    pd.to_numeric(accepted["portfolio_pnl"], errors="coerce").sum()
                ),
            }
        )
    components = pd.DataFrame(component_rows)

    ending_equity = float(replay_stats["ending_equity"])
    summary = {
        "portfolio_replay_version": PORTFOLIO_REPLAY_VERSION,
        "source_population": "EVERY_VIABLE_ENTRY",
        "portfolio_assets": [item["symbol"] for item in metadata],
        "source_run_count": len(metadata),
        "initial_equity": float(initial_equity),
        "risk_per_trade": float(risk_per_trade),
        "maximum_total_portfolio_risk": float(maximum_total_risk),
        "maximum_open_positions_policy": int(maximum_open_positions),
        "one_active_trade_per_symbol": bool(one_active_trade_per_symbol),
        "common_period_only": bool(common_period_only),
        "replay_period_start": replay_start.isoformat(),
        "replay_period_end": replay_end.isoformat(),
        "same_timestamp_candidate_priority": "SYMBOL_ASCENDING",
        "same_timestamp_exit_policy": "PROCESS_EXITS_BEFORE_ENTRIES",
        **replay_stats,
        "total_return_percentage": (ending_equity / float(initial_equity) - 1.0) * 100.0,
        "positive_months": int((monthly["net_pnl"] > 0).sum()) if not monthly.empty else 0,
        "negative_months": int((monthly["net_pnl"] < 0).sum()) if not monthly.empty else 0,
        "maximum_losing_month_streak": _maximum_losing_streak(monthly),
        "worst_month_return_percentage": (
            float(monthly["return_percentage"].min()) if not monthly.empty else None
        ),
        "closed_equity_curve_valid": True,
        "mark_to_market_equity_curve_valid": False,
        "mark_to_market_drawdown_valid": False,
        "note": (
            "Candidates come from independently-sized Every Viable Entry resilience outputs. "
            "The replay reapplies shared-account occupancy and risk policy without rerunning strategy features."
        ),
    }

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    labels = "_".join(item["symbol"].replace("USDT", "") for item in metadata)
    run_dir = output_root / f"PORTFOLIO_REPLAY_{labels}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    candidates.to_csv(run_dir / "portfolio_candidate_replay.csv", index=False)
    realized.to_csv(run_dir / "portfolio_realized_equity.csv", index=False)
    monthly.to_csv(run_dir / "portfolio_monthly_results.csv", index=False)
    yearly.to_csv(run_dir / "portfolio_yearly_results.csv", index=False)
    components.to_csv(run_dir / "portfolio_components.csv", index=False)
    block_rows = [
        {"reason": reason, "candidates": count}
        for reason, count in summary["blocked_by_reason"].items()
    ]
    pd.DataFrame(block_rows, columns=["reason", "candidates"]).to_csv(
        run_dir / "portfolio_block_reasons.csv", index=False
    )
    source_payload = [
        {
            key: (str(value) if isinstance(value, Path) else value)
            for key, value in item.items()
            if key != "samples_path"
        }
        for item in metadata
    ]
    (run_dir / "portfolio_sources.json").write_text(
        json.dumps(source_payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    atomic_json(run_dir / "portfolio_summary.json", summary)
    (run_dir / "portfolio_summary.txt").write_text(
        "\n".join(f"{key}: {value}" for key, value in summary.items()) + "\n",
        encoding="utf-8",
    )
    return summary, candidates, realized, run_dir
