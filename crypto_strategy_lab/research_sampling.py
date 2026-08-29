"""Strategy-aware opportunity sampling for resilience research.

This module is deliberately separate from portfolio simulation.  It evaluates
only entries that the configured strategy would actually accept, but removes
portfolio suppression so viable opportunities can overlap.  Every synthetic
trade starts from the same research equity and uses the native execution engine
for stops, targets, timeout, fees, slippage and intrabar resolution.
"""
from __future__ import annotations

from dataclasses import replace
import time

import numpy as np
import pandas as pd

from crypto_strategy_lab.config import EntryMode
from crypto_strategy_lab.research_sampling_fast import ResearchSamplingFastExitMixin
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine


RESEARCH_SAMPLING_VERSION = "STRATEGY_OPPORTUNITY_V1"
RESEARCH_SAMPLING_MODES = {
    "PORTFOLIO",
    "EVERY_VIABLE_ENTRY",
    "FIXED_INTERVAL",
    "EPISODE_FIRST",
}


class StrategyResearchSamplingEngine(
    ResearchSamplingFastExitMixin,
    RuleAwareDataLakeProductionBacktestEngine,
):
    """Native engine variant that ignores portfolio overlap suppression only."""

    def _should_enter(self, i):
        # Research observations are not a portfolio. Existing open observations,
        # timeout history and max-active-pair limits must not suppress a new
        # opportunity. Strategy profile availability and the normal downstream
        # Entry/Veto rule evaluation remain authoritative.
        if not np.isfinite(self.risk[i]) or self.risk[i] <= 0:
            return False
        if not self._in_trading_window(i):
            return False
        return self._profile_context(i) is not None

    def _collect_closed_pairs(self, force=False):
        # Keep all observations on fixed independent research equity. The normal
        # engine may calculate a trade PnL, but no completed observation may alter
        # the sizing base of a later overlapping observation.
        still = []
        for pair in self.active_pairs:
            if force or not pair.is_open:
                pair.equity_after_trade = pair.equity_before_trade
                self.completed_pairs.append(pair)
            else:
                still.append(pair)
        self.active_pairs = still


def research_native_config(native_config, prepared_rows: int):
    """Remove portfolio constraints while preserving strategy and trade semantics."""
    return replace(
        native_config,
        entry_mode=EntryMode.EVERY_N_CANDLES,
        entry_interval=1,
        enable_daily_entry_schedule=False,
        max_active_pairs=max(1, int(prepared_rows) * 2 + 2),
        max_combined_effective_leverage=None,
    )


def _exit_reason(row: pd.Series) -> str:
    side = str(row.get("side", "")).lower()
    return str(row.get(f"{side}_exit_reason", "")).upper()


def _release_research_rejection_metadata(frame: pd.DataFrame) -> None:
    """Detach the legacy high-cardinality rejection payload before pandas copies.

    ``BacktestEngine.results_frame`` stores the engine's ``skipped_signals`` list
    in ``DataFrame.attrs`` for legacy callers. Strategy-resilience publication
    does not consume those per-rejection rows; the engine has already used them
    to produce its aggregate result counters. Pandas copies/deepcopies attrs, so
    carrying thousands of rejection dictionaries through episode/censor/selection
    transforms is pure overhead.

    Only the redundant attrs entry is removed. Trade rows, rejection counts,
    strategy decisions and every execution result remain unchanged.
    """
    frame.attrs.pop("skipped_signals", None)


def _annotate_episodes(frame: pd.DataFrame) -> pd.DataFrame:
    """Label uninterrupted stretches of the same viable configured setup."""
    if frame.empty:
        result = frame.copy()
        for name, dtype in (
            ("research_episode_id", "string"),
            ("research_episode_entry_number", "int64"),
            ("research_episode_viable_entries", "int64"),
        ):
            result[name] = pd.Series(dtype=dtype)
        return result

    required = {"research_signal_index", "side"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"research sampling rows are missing episode fields: {missing}")

    # Sort only narrow helper columns first. The previous implementation attached
    # helper columns to the full research frame and repeatedly copied a very wide
    # DataFrame. The stable sort keys and resulting row order are identical.
    signal_index = pd.to_numeric(
        frame["research_signal_index"], errors="raise"
    ).astype("int64").reset_index(drop=True)
    profile = frame.get(
        "strategy_profile_key", pd.Series("", index=frame.index, dtype="string")
    ).fillna("").astype(str).reset_index(drop=True)
    side = frame["side"].fillna("").astype(str).str.upper().reset_index(drop=True)
    keys = pd.DataFrame(
        {
            "research_signal_index": signal_index,
            "_profile_sort": profile,
            "_side_sort": side,
        }
    )
    order = keys.sort_values(
        ["research_signal_index", "_profile_sort", "_side_sort"], kind="stable"
    ).index.to_numpy()
    keys = keys.iloc[order].reset_index(drop=True)
    result = frame.iloc[order].copy().reset_index(drop=True)
    result["research_signal_index"] = keys["research_signal_index"].to_numpy()

    previous_index = keys["research_signal_index"].shift(1)
    previous_profile = keys["_profile_sort"].shift(1)
    previous_side = keys["_side_sort"].shift(1)
    new_episode = (
        previous_index.isna()
        | keys["research_signal_index"].ne(previous_index + 1)
        | keys["_profile_sort"].ne(previous_profile)
        | keys["_side_sort"].ne(previous_side)
    )
    episode_number = new_episode.cumsum().astype("int64")
    result["research_episode_id"] = episode_number.map(
        lambda value: f"episode-{int(value):06d}"
    )
    result["research_episode_entry_number"] = (
        result.groupby("research_episode_id", sort=False).cumcount() + 1
    ).astype("int64")
    result["research_episode_viable_entries"] = result.groupby(
        "research_episode_id", sort=False
    )["research_episode_id"].transform("size").astype("int64")
    return result


def _resolved_samples(frame: pd.DataFrame) -> pd.DataFrame:
    """Treat right-censored end-of-data observations as unknown, not losses."""
    if frame.empty:
        return frame.copy()

    # Preserve _exit_reason's exact side-aware behavior without Python row apply.
    side = frame["side"].fillna("").astype(str).str.upper()
    empty = pd.Series("", index=frame.index, dtype="string")
    long_reason = (
        frame["long_exit_reason"].fillna("").astype(str).str.upper()
        if "long_exit_reason" in frame.columns
        else empty
    )
    short_reason = (
        frame["short_exit_reason"].fillna("").astype(str).str.upper()
        if "short_exit_reason" in frame.columns
        else empty
    )
    reason = empty.copy()
    long_mask = side.eq("LONG")
    short_mask = side.eq("SHORT")
    reason.loc[long_mask] = long_reason.loc[long_mask].to_numpy()
    reason.loc[short_mask] = short_reason.loc[short_mask].to_numpy()
    mask = reason.ne("END_OF_DATA")
    return frame.loc[mask].copy().reset_index(drop=True)


def _select_sampling_mode(
    viable: pd.DataFrame,
    mode: str,
    interval_candles: int,
) -> pd.DataFrame:
    mode = str(mode).upper()
    interval = int(interval_candles)
    if mode not in RESEARCH_SAMPLING_MODES:
        raise ValueError(f"unsupported research sampling mode: {mode}")
    if interval <= 0:
        raise ValueError("research sampling interval must be positive")
    if mode == "PORTFOLIO":
        return viable.iloc[0:0].copy()
    if mode == "EVERY_VIABLE_ENTRY":
        return viable.copy().reset_index(drop=True)
    if mode == "EPISODE_FIRST":
        return viable.loc[viable["research_episode_entry_number"].eq(1)].copy().reset_index(drop=True)
    return viable.loc[
        (viable["research_episode_entry_number"] - 1).mod(interval).eq(0)
    ].copy().reset_index(drop=True)


def generate_strategy_research_samples(
    prepared,
    intrabar,
    native_config,
    *,
    mode: str,
    interval_candles: int = 1,
) -> pd.DataFrame:
    """Evaluate configured strategy opportunities without portfolio suppression."""
    normalized_mode = str(mode).upper()
    if normalized_mode not in RESEARCH_SAMPLING_MODES:
        raise ValueError(f"unsupported research sampling mode: {normalized_mode}")
    interval = int(interval_candles)
    if interval <= 0:
        raise ValueError("research sampling interval must be positive")
    if normalized_mode == "PORTFOLIO":
        empty = pd.DataFrame()
        empty.attrs["research_sampling"] = {
            "enabled": False,
            "mode": normalized_mode,
            "interval_candles": interval,
        }
        return empty

    config = research_native_config(native_config, len(prepared))
    engine = StrategyResearchSamplingEngine.from_prepared(prepared, intrabar, config)
    raw = engine.run()
    exit_optimization = engine.research_exit_optimization_stats()

    started = time.perf_counter()
    _release_research_rejection_metadata(raw)
    rejection_release_seconds = time.perf_counter() - started

    started = time.perf_counter()
    raw = _annotate_episodes(raw)
    episode_annotation_seconds = time.perf_counter() - started
    viable_episode_count = int(raw["research_episode_id"].nunique()) if not raw.empty else 0

    started = time.perf_counter()
    resolved = _resolved_samples(raw)
    censoring_seconds = time.perf_counter() - started

    started = time.perf_counter()
    selected = _select_sampling_mode(resolved, normalized_mode, interval)
    selection_seconds = time.perf_counter() - started

    if not selected.empty:
        selected["research_sampling_version"] = RESEARCH_SAMPLING_VERSION
        selected["research_sampling_mode"] = normalized_mode
        selected["research_sampling_interval_candles"] = interval
        selected["research_sampling_overlap_allowed"] = True
        selected["research_sampling_independent_equity"] = True
        selected["research_sampling_population"] = "STRATEGY_VIABLE"
        selected["research_sample_id"] = (
            selected["research_signal_index"].astype("int64").astype(str)
            + "-"
            + selected["side"].astype(str).str.upper()
            + "-"
            + selected["research_episode_id"].astype(str)
        )

    selected.attrs["research_sampling"] = {
        "version": RESEARCH_SAMPLING_VERSION,
        "enabled": True,
        "mode": normalized_mode,
        "interval_candles": interval,
        "strategy_timeframe_minutes": int(native_config.strategy_timeframe_minutes),
        "overlap_allowed": True,
        "independent_equity": True,
        "portfolio_exposure_ignored": True,
        "combined_leverage_cap_ignored": True,
        "per_trade_execution_semantics_preserved": True,
        **exit_optimization,
        "research_postprocess_kernel": "VECTORIZED_V2",
        "research_rejection_metadata_release_seconds": rejection_release_seconds,
        "research_episode_annotation_seconds": episode_annotation_seconds,
        "research_censoring_seconds": censoring_seconds,
        "research_sampling_selection_seconds": selection_seconds,
        "viable_entries": int(len(raw)),
        "resolved_viable_entries": int(len(resolved)),
        "selected_entries": int(len(selected)),
        "viable_episodes": viable_episode_count,
        "end_of_data_samples_censored": int(len(raw) - len(resolved)),
        "bayesian_cluster_key": "research_episode_id",
    }
    return selected


def build_episode_table(samples: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sampled outcomes at the correlation-cluster/episode level."""
    columns = [
        "research_episode_id", "episode_start_time", "episode_end_time",
        "strategy_profile_key", "side", "sampled_entries", "viable_entries",
        "wins", "losses", "entry_win_rate", "episode_net_r", "episode_avg_r",
        "episode_positive",
    ]
    if samples.empty:
        return pd.DataFrame(columns=columns)

    # Aggregate only the narrow columns used by the episode artifact instead of
    # copying the full research feature matrix once per group.
    pair_net_r = pd.to_numeric(samples["pair_net_r"], errors="coerce")
    entry_time = pd.to_datetime(samples["entry_time"], utc=True, errors="coerce")
    profile = (
        samples["strategy_profile_key"]
        if "strategy_profile_key" in samples.columns
        else pd.Series(None, index=samples.index, dtype="object")
    )
    viable_entries = pd.to_numeric(
        samples["research_episode_viable_entries"], errors="raise"
    ).astype("int64")
    frame = pd.DataFrame(
        {
            "research_episode_id": samples["research_episode_id"],
            "_entry_time": entry_time,
            "strategy_profile_key": profile,
            "side": samples["side"],
            "_viable_entries": viable_entries,
            "_pair_net_r": pair_net_r,
            "_win": pair_net_r.gt(0),
        },
        index=samples.index,
    )
    grouped = frame.groupby("research_episode_id", sort=False)
    sampled_entries = grouped.size().astype("int64")
    result = pd.DataFrame(index=sampled_entries.index)
    result["episode_start_time"] = grouped["_entry_time"].min()
    result["episode_end_time"] = grouped["_entry_time"].max()

    first = frame.drop_duplicates("research_episode_id", keep="first").set_index(
        "research_episode_id"
    )
    result["strategy_profile_key"] = first["strategy_profile_key"].reindex(result.index)
    result["side"] = first["side"].reindex(result.index).map(
        lambda value: str(value).upper()
    )
    result["sampled_entries"] = sampled_entries
    result["viable_entries"] = grouped["_viable_entries"].max().astype("int64")
    result["wins"] = grouped["_win"].sum().astype("int64")
    result["losses"] = result["sampled_entries"] - result["wins"]
    result["entry_win_rate"] = result["wins"] / result["sampled_entries"]
    result["episode_net_r"] = grouped["_pair_net_r"].sum(min_count=1)
    result["episode_avg_r"] = grouped["_pair_net_r"].mean()
    net_r_values = result["episode_net_r"].to_numpy(dtype=float)
    result["episode_positive"] = np.isfinite(net_r_values) & (net_r_values > 0)
    result = result.reset_index()
    return result[columns]


def build_sampling_summary(
    samples: pd.DataFrame,
    metadata: dict | None = None,
    *,
    episodes: pd.DataFrame | None = None,
) -> dict:
    """Return entry-level and episode-level resilience statistics."""
    metadata = dict(metadata or samples.attrs.get("research_sampling", {}))
    if episodes is None:
        episodes = build_episode_table(samples)
    r = pd.to_numeric(samples.get("pair_net_r", pd.Series(dtype=float)), errors="coerce")
    wins = int(r.gt(0).sum())
    entries = int(len(samples))
    episode_count = int(len(episodes))
    positive_episodes = int(episodes["episode_positive"].sum()) if episode_count else 0

    summary = {
        **metadata,
        "synthetic_entries": entries,
        "wins": wins,
        "losses": entries - wins,
        "entry_win_rate": (wins / entries) if entries else None,
        "average_r_per_entry": float(r.mean()) if r.notna().any() else None,
        "net_r": float(r.sum(min_count=1)) if r.notna().any() else None,
        "unique_episodes": episode_count,
        "positive_episodes": positive_episodes,
        "negative_or_flat_episodes": episode_count - positive_episodes,
        "episode_success_rate": (positive_episodes / episode_count) if episode_count else None,
        "average_sampled_entries_per_episode": float(episodes["sampled_entries"].mean()) if episode_count else None,
        "median_sampled_entries_per_episode": float(episodes["sampled_entries"].median()) if episode_count else None,
        "average_episode_r": float(episodes["episode_net_r"].mean()) if episode_count else None,
    }
    if episode_count:
        best = episodes.loc[episodes["episode_net_r"].idxmax()]
        worst = episodes.loc[episodes["episode_net_r"].idxmin()]
        summary["best_episode"] = {
            "research_episode_id": best["research_episode_id"],
            "net_r": float(best["episode_net_r"]),
        }
        summary["worst_episode"] = {
            "research_episode_id": worst["research_episode_id"],
            "net_r": float(worst["episode_net_r"]),
        }
    else:
        summary["best_episode"] = None
        summary["worst_episode"] = None

    for output_name, candidates in (
        ("average_mae_r", ("mae_r", "max_adverse_excursion_r")),
        ("average_mfe_r", ("mfe_r", "max_favorable_excursion_r")),
    ):
        source = next((name for name in candidates if name in samples.columns), None)
        if source is not None:
            values = pd.to_numeric(samples[source], errors="coerce")
            summary[output_name] = float(values.mean()) if values.notna().any() else None
    return summary


def build_context_breakdown(samples: pd.DataFrame) -> pd.DataFrame:
    """Compact entry/episode outcome table across available research context."""
    columns = ["dimension", "value", "entries", "episodes", "wins", "win_rate", "avg_r", "net_r"]
    if samples.empty:
        return pd.DataFrame(columns=columns)

    pair_net_r = pd.to_numeric(samples["pair_net_r"], errors="coerce")
    wins = pair_net_r.gt(0)
    side = samples["side"].fillna("").astype(str).str.upper()
    plus_di = (
        pd.to_numeric(samples["plus_di"], errors="coerce")
        if "plus_di" in samples.columns
        else pd.Series(np.nan, index=samples.index, dtype=float)
    )
    minus_di = (
        pd.to_numeric(samples["minus_di"], errors="coerce")
        if "minus_di" in samples.columns
        else pd.Series(np.nan, index=samples.index, dtype=float)
    )
    directional_di = plus_di.where(side.eq("LONG"), minus_di)
    research_di_bucket = pd.cut(
        directional_di,
        [-np.inf, 10, 20, 30, 40, np.inf],
        labels=["<10", "10-20", "20-30", "30-40", "40+"],
        right=False,
    ).astype("string")
    adx = (
        pd.to_numeric(samples["adx"], errors="coerce")
        if "adx" in samples.columns
        else pd.Series(np.nan, index=samples.index, dtype=float)
    )
    research_adx_bucket = pd.cut(
        adx,
        [-np.inf, 20, 30, 40, np.inf],
        labels=["<20", "20-30", "30-40", "40+"],
        right=False,
    ).astype("string")

    dimensions: list[tuple[str, pd.Series]] = []
    for name in ("strategy_profile_key", "market_regime"):
        if name in samples.columns:
            dimensions.append((name, samples[name]))
    dimensions.extend(
        [
            ("research_di_bucket", research_di_bucket),
            ("research_adx_bucket", research_adx_bucket),
        ]
    )
    for name in (
        "di_pressure_state",
        "mean_reversion_state",
        "funding_bias",
        "oi_vs_price_state_1h",
    ):
        if name in samples.columns:
            dimensions.append((name, samples[name]))

    chunks: list[pd.DataFrame] = []
    episode_ids = samples["research_episode_id"]
    for dimension, values in dimensions:
        available = values.notna()
        if not bool(available.any()):
            continue
        narrow = pd.DataFrame(
            {
                "_value": values.loc[available],
                "_episode": episode_ids.loc[available],
                "_win": wins.loc[available],
                "_r": pair_net_r.loc[available],
            }
        )
        grouped = narrow.groupby("_value", dropna=False, sort=True)
        entries = grouped.size().astype("int64")
        aggregate = pd.DataFrame(index=entries.index)
        aggregate["entries"] = entries
        aggregate["episodes"] = grouped["_episode"].nunique().astype("int64")
        aggregate["wins"] = grouped["_win"].sum().astype("int64")
        aggregate["win_rate"] = aggregate["wins"] / aggregate["entries"]
        aggregate["avg_r"] = grouped["_r"].mean()
        aggregate["net_r"] = grouped["_r"].sum(min_count=1)
        aggregate = aggregate.reset_index().rename(columns={"_value": "value"})
        aggregate.insert(0, "dimension", dimension)
        aggregate["value"] = aggregate["value"].map(str)
        chunks.append(aggregate[columns])

    if not chunks:
        return pd.DataFrame(columns=columns)
    return pd.concat(chunks, ignore_index=True)
