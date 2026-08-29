from __future__ import annotations

import numpy as np
import pandas as pd

import crypto_strategy_lab.research_sampling as research_sampling
from crypto_strategy_lab.research_sampling import (
    _annotate_episodes,
    _release_research_rejection_metadata,
    _resolved_samples,
    build_context_breakdown,
    build_episode_table,
    build_sampling_summary,
)


def _samples() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "research_signal_index": 10,
                "side": "SHORT",
                "strategy_profile_key": "bear_short",
                "pair_net_r": 1.0,
                "entry_time": "2024-01-01",
                "exit_time": "2024-01-02",
                "short_exit_reason": "TP",
                "long_exit_reason": None,
                "plus_di": 10.0,
                "minus_di": 35.0,
                "adx": 25.0,
                "market_regime": "BEAR",
                "di_pressure_state": "EXPANDING",
                "funding_bias": "POSITIVE",
            },
            {
                "research_signal_index": 11,
                "side": "SHORT",
                "strategy_profile_key": "bear_short",
                "pair_net_r": -1.0,
                "entry_time": "2024-01-02",
                "exit_time": "2024-01-03",
                "short_exit_reason": "SL",
                "long_exit_reason": None,
                "plus_di": 12.0,
                "minus_di": 33.0,
                "adx": 28.0,
                "market_regime": "BEAR",
                "di_pressure_state": "EXPANDING",
                "funding_bias": "NEGATIVE",
            },
            {
                "research_signal_index": 12,
                "side": "SHORT",
                "strategy_profile_key": "bear_short",
                "pair_net_r": 0.5,
                "entry_time": "2024-01-03",
                "exit_time": "2024-01-04",
                "short_exit_reason": "END_OF_DATA",
                "long_exit_reason": None,
                "plus_di": 11.0,
                "minus_di": 31.0,
                "adx": 31.0,
                "market_regime": "BEAR",
                "di_pressure_state": "MIXED",
                "funding_bias": "NEGATIVE",
            },
            {
                "research_signal_index": 13,
                "side": "LONG",
                "strategy_profile_key": "sideways_long",
                "pair_net_r": 1.0,
                "entry_time": "2024-01-04",
                "exit_time": "2024-01-05",
                "short_exit_reason": None,
                "long_exit_reason": "TP",
                "plus_di": 22.0,
                "minus_di": 18.0,
                "adx": 18.0,
                "market_regime": "SIDEWAYS",
                "di_pressure_state": "MIXED",
                "funding_bias": "POSITIVE",
            },
            {
                "research_signal_index": 15,
                "side": "LONG",
                "strategy_profile_key": "sideways_long",
                "pair_net_r": -1.0,
                "entry_time": "2024-01-06",
                "exit_time": "2024-01-07",
                "short_exit_reason": None,
                "long_exit_reason": "SL",
                "plus_di": 24.0,
                "minus_di": 17.0,
                "adx": 19.0,
                "market_regime": "SIDEWAYS",
                "di_pressure_state": "CONTRACTING",
                "funding_bias": "POSITIVE",
            },
        ]
    )
    return _annotate_episodes(frame)


def _legacy_resolved_samples(frame: pd.DataFrame) -> pd.DataFrame:
    def exit_reason(row: pd.Series) -> str:
        side = str(row.get("side", "")).lower()
        return str(row.get(f"{side}_exit_reason", "")).upper()

    mask = frame.apply(exit_reason, axis=1).ne("END_OF_DATA")
    return frame.loc[mask].copy().reset_index(drop=True)


def _legacy_episode_table(samples: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "research_episode_id",
        "episode_start_time",
        "episode_end_time",
        "strategy_profile_key",
        "side",
        "sampled_entries",
        "viable_entries",
        "wins",
        "losses",
        "entry_win_rate",
        "episode_net_r",
        "episode_avg_r",
        "episode_positive",
    ]
    frame = samples.copy()
    frame["pair_net_r"] = pd.to_numeric(frame.get("pair_net_r"), errors="coerce")
    frame["_win"] = frame["pair_net_r"].gt(0)
    frame["_entry_time"] = pd.to_datetime(
        frame.get("entry_time"), utc=True, errors="coerce"
    )
    rows = []
    for episode_id, group in frame.groupby("research_episode_id", sort=False):
        net_r = float(group["pair_net_r"].sum(min_count=1))
        finite = group["pair_net_r"].dropna()
        wins = int(group["_win"].sum())
        entries = int(len(group))
        rows.append(
            {
                "research_episode_id": episode_id,
                "episode_start_time": group["_entry_time"].min(),
                "episode_end_time": group["_entry_time"].max(),
                "strategy_profile_key": group.get(
                    "strategy_profile_key", pd.Series([None])
                ).iloc[0],
                "side": str(group["side"].iloc[0]).upper(),
                "sampled_entries": entries,
                "viable_entries": int(
                    group["research_episode_viable_entries"].max()
                ),
                "wins": wins,
                "losses": entries - wins,
                "entry_win_rate": (wins / entries) if entries else np.nan,
                "episode_net_r": net_r,
                "episode_avg_r": float(finite.mean()) if not finite.empty else np.nan,
                "episode_positive": bool(np.isfinite(net_r) and net_r > 0),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _legacy_context_breakdown(samples: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "dimension",
        "value",
        "entries",
        "episodes",
        "wins",
        "win_rate",
        "avg_r",
        "net_r",
    ]
    frame = samples.copy()
    frame["pair_net_r"] = pd.to_numeric(frame["pair_net_r"], errors="coerce")
    frame["_win"] = frame["pair_net_r"].gt(0)
    side = frame["side"].astype(str).str.upper()
    plus_di = pd.to_numeric(frame.get("plus_di"), errors="coerce")
    minus_di = pd.to_numeric(frame.get("minus_di"), errors="coerce")
    directional_di = plus_di.where(side.eq("LONG"), minus_di)
    frame["research_di_bucket"] = pd.cut(
        directional_di,
        [-np.inf, 10, 20, 30, 40, np.inf],
        labels=["<10", "10-20", "20-30", "30-40", "40+"],
        right=False,
    ).astype("string")
    adx = pd.to_numeric(frame.get("adx"), errors="coerce")
    frame["research_adx_bucket"] = pd.cut(
        adx,
        [-np.inf, 20, 30, 40, np.inf],
        labels=["<20", "20-30", "30-40", "40+"],
        right=False,
    ).astype("string")
    dimensions = [
        "strategy_profile_key",
        "market_regime",
        "research_di_bucket",
        "research_adx_bucket",
        "di_pressure_state",
        "mean_reversion_state",
        "funding_bias",
        "oi_vs_price_state_1h",
    ]
    rows = []
    for dimension in dimensions:
        if dimension not in frame.columns:
            continue
        available = frame.loc[frame[dimension].notna()].copy()
        if available.empty:
            continue
        for value, group in available.groupby(dimension, dropna=False, sort=True):
            entries = int(len(group))
            wins = int(group["_win"].sum())
            r = group["pair_net_r"]
            rows.append(
                {
                    "dimension": dimension,
                    "value": str(value),
                    "entries": entries,
                    "episodes": int(group["research_episode_id"].nunique()),
                    "wins": wins,
                    "win_rate": wins / entries if entries else np.nan,
                    "avg_r": float(r.mean()) if r.notna().any() else np.nan,
                    "net_r": (
                        float(r.sum(min_count=1)) if r.notna().any() else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def test_research_rejection_attrs_are_detached_before_wide_postprocessing():
    frame = _samples()
    frame.attrs["skipped_signals"] = [
        {"entry_filter_reason": "ADX"} for _ in range(5000)
    ]
    frame.attrs["small_metadata"] = {"keep": True}

    _release_research_rejection_metadata(frame)
    annotated = _annotate_episodes(frame)

    assert "skipped_signals" not in frame.attrs
    assert "skipped_signals" not in annotated.attrs
    assert annotated.attrs["small_metadata"] == {"keep": True}


def test_vectorized_end_of_data_censoring_matches_legacy_row_logic():
    frame = _samples()
    expected = _legacy_resolved_samples(frame)
    actual = _resolved_samples(frame)

    pd.testing.assert_frame_equal(actual, expected)


def test_vectorized_episode_table_matches_legacy_aggregation():
    samples = _resolved_samples(_samples())
    expected = _legacy_episode_table(samples)
    actual = build_episode_table(samples)

    pd.testing.assert_frame_equal(actual, expected, check_dtype=True)


def test_vectorized_context_breakdown_matches_legacy_aggregation():
    samples = _resolved_samples(_samples())
    expected = _legacy_context_breakdown(samples)
    actual = build_context_breakdown(samples)

    pd.testing.assert_frame_equal(actual, expected, check_dtype=True)


def test_sampling_summary_reuses_precomputed_episode_table(monkeypatch):
    samples = _resolved_samples(_samples())
    episodes = build_episode_table(samples)
    expected = build_sampling_summary(samples, {"mode": "EVERY_VIABLE_ENTRY"})

    def unexpected_rebuild(_samples):
        raise AssertionError("episode table should be reused")

    monkeypatch.setattr(research_sampling, "build_episode_table", unexpected_rebuild)
    actual = build_sampling_summary(
        samples,
        {"mode": "EVERY_VIABLE_ENTRY"},
        episodes=episodes,
    )

    assert actual == expected
