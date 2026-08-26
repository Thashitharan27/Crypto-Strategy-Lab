from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.research_adapters import native_simulator_config
from crypto_strategy_lab.research_sampling import (
    StrategyResearchSamplingEngine,
    _annotate_episodes,
    _resolved_samples,
    _select_sampling_mode,
    build_context_breakdown,
    build_episode_table,
    build_sampling_summary,
    research_native_config,
)
from crypto_strategy_lab.research_sampling_reporting import (
    _episode_reporting_context,
    research_sampling_enabled,
)


def _viable_rows():
    return pd.DataFrame(
        [
            {"research_signal_index": 10, "side": "SHORT", "strategy_profile_key": "bear_short", "pair_net_r": 1.0, "entry_time": "2024-01-01", "exit_time": "2024-01-02", "short_exit_reason": "TP", "plus_di": 10.0, "minus_di": 35.0, "adx": 25.0, "market_regime": "BEAR"},
            {"research_signal_index": 11, "side": "SHORT", "strategy_profile_key": "bear_short", "pair_net_r": -1.0, "entry_time": "2024-01-02", "exit_time": "2024-01-03", "short_exit_reason": "SL", "plus_di": 12.0, "minus_di": 33.0, "adx": 28.0, "market_regime": "BEAR"},
            {"research_signal_index": 12, "side": "SHORT", "strategy_profile_key": "bear_short", "pair_net_r": 1.0, "entry_time": "2024-01-03", "exit_time": "2024-01-04", "short_exit_reason": "TP", "plus_di": 11.0, "minus_di": 31.0, "adx": 31.0, "market_regime": "BEAR"},
            {"research_signal_index": 13, "side": "LONG", "strategy_profile_key": "sideways_long", "pair_net_r": 1.0, "entry_time": "2024-01-04", "exit_time": "2024-01-05", "long_exit_reason": "TP", "plus_di": 22.0, "minus_di": 18.0, "adx": 18.0, "market_regime": "SIDEWAYS"},
            {"research_signal_index": 15, "side": "LONG", "strategy_profile_key": "sideways_long", "pair_net_r": -1.0, "entry_time": "2024-01-06", "exit_time": "2024-01-07", "long_exit_reason": "SL", "plus_di": 24.0, "minus_di": 17.0, "adx": 19.0, "market_regime": "SIDEWAYS"},
        ]
    )


def test_reporting_config_defaults_to_realistic_portfolio_mode():
    run = ResearchRunConfig()
    assert run.reporting.research_sampling_mode == "PORTFOLIO"
    assert run.reporting.research_sampling_interval_candles == 1
    assert not research_sampling_enabled(run.reporting)


def test_research_sampling_config_is_strict_and_persistent():
    run = ResearchRunConfig()
    reporting = replace(
        run.reporting,
        research_sampling_mode="FIXED_INTERVAL",
        research_sampling_interval_candles=3,
    )
    configured = replace(run, reporting=reporting)
    configured.validate()
    assert configured.to_dict()["reporting"]["research_sampling_mode"] == "FIXED_INTERVAL"
    assert research_sampling_enabled(configured.reporting)

    with pytest.raises(ValueError, match="invalid research sampling mode"):
        replace(run, reporting=replace(run.reporting, research_sampling_mode="UNKNOWN")).validate()
    with pytest.raises(ValueError, match="interval must be positive"):
        replace(run, reporting=replace(run.reporting, research_sampling_interval_candles=0)).validate()


def test_research_native_config_preserves_strategy_rules_and_per_trade_execution():
    run = ResearchRunConfig()
    strategy = replace(
        run.strategy,
        profiles={
            key: replace(
                profile,
                enabled=(key == "bear_short"),
                entry_rules=(
                    {"action": "REJECT", "indicator": "ADX", "condition": "INSIDE", "minimum": 0.0, "maximum": 20.0},
                ) if key == "bear_short" else (),
            )
            for key, profile in run.strategy.profiles.items()
        },
    )
    native = native_simulator_config(run.data, run.features, strategy, run.execution)
    research = research_native_config(native, 100)

    assert research.strategy_profiles["bear_short"].enabled
    assert research.strategy_profiles["bear_short"].entry_rules == native.strategy_profiles["bear_short"].entry_rules
    assert research.max_active_pairs == 202
    assert research.max_combined_effective_leverage is None
    assert research.max_effective_leverage_per_leg == native.max_effective_leverage_per_leg
    assert research.risk_per_leg == native.risk_per_leg
    assert research.tie_policy == native.tie_policy
    assert research.enable_daily_entry_schedule is False


def test_research_engine_ignores_open_overlap_but_still_requires_strategy_context():
    engine = object.__new__(StrategyResearchSamplingEngine)
    engine.risk = np.ones(3)
    engine.active_pairs = [object(), object(), object()]
    engine._in_trading_window = lambda i: True
    engine._profile_context = lambda i: ("BEAR", "SHORT", "bear_short", object()) if i != 1 else None

    assert engine._should_enter(0)
    assert not engine._should_enter(1)
    assert engine._should_enter(2)


def test_episode_ids_break_on_gap_direction_or_profile_change():
    result = _annotate_episodes(_viable_rows())
    assert result["research_episode_id"].tolist() == [
        "episode-000001", "episode-000001", "episode-000001",
        "episode-000002", "episode-000003",
    ]
    assert result["research_episode_entry_number"].tolist() == [1, 2, 3, 1, 1]
    assert result["research_episode_viable_entries"].tolist() == [3, 3, 3, 1, 1]


def test_sampling_modes_are_episode_anchored_not_global_index_anchored():
    viable = _annotate_episodes(_viable_rows())
    every = _select_sampling_mode(viable, "EVERY_VIABLE_ENTRY", 99)
    fixed = _select_sampling_mode(viable, "FIXED_INTERVAL", 2)
    first = _select_sampling_mode(viable, "EPISODE_FIRST", 99)

    assert every["research_signal_index"].tolist() == [10, 11, 12, 13, 15]
    assert fixed["research_signal_index"].tolist() == [10, 12, 13, 15]
    assert first["research_signal_index"].tolist() == [10, 13, 15]


def test_end_of_data_is_censored_before_outcome_reporting():
    frame = _annotate_episodes(_viable_rows())
    frame.loc[2, "short_exit_reason"] = "END_OF_DATA"
    resolved = _resolved_samples(frame)
    assert resolved["research_signal_index"].tolist() == [10, 11, 13, 15]
    # Episode identity was assigned before censoring, so the cluster membership remains stable.
    assert resolved.loc[resolved["research_signal_index"].eq(11), "research_episode_viable_entries"].iloc[0] == 3


def test_cluster_aware_summary_reports_entries_and_episodes_separately():
    samples = _annotate_episodes(_viable_rows())
    samples["research_sample_id"] = [f"sample-{i}" for i in range(len(samples))]
    samples["research_sampling_mode"] = "EVERY_VIABLE_ENTRY"
    episodes = build_episode_table(samples)
    episodes, episode_reporting = _episode_reporting_context(episodes, samples)
    summary = build_sampling_summary(samples, {"mode": "EVERY_VIABLE_ENTRY"})
    summary.update(episode_reporting)
    context = build_context_breakdown(samples)

    assert len(episodes) == 3
    assert episodes["episode_start_year"].tolist() == [2024, 2024, 2024]
    assert episodes["market_regime"].tolist() == ["BEAR", "SIDEWAYS", "SIDEWAYS"]
    assert summary["synthetic_entries"] == 5
    assert summary["unique_episodes"] == 3
    assert summary["entry_win_rate"] == pytest.approx(3 / 5)
    assert summary["episode_success_rate"] == pytest.approx(2 / 3)
    assert summary["average_sampled_entries_per_episode"] == pytest.approx(5 / 3)
    assert summary["average_viable_entries_per_episode"] == pytest.approx(5 / 3)
    assert summary["episodes_by_year"] == {"2024": 3}
    assert summary["episodes_by_regime"] == {"BEAR": 1, "SIDEWAYS": 2}
    assert summary["bayesian_effective_cluster_units"] == 3
    assert {"research_di_bucket", "research_adx_bucket", "market_regime"} <= set(context["dimension"])
