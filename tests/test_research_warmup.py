from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_strategy_lab.data import DataRequest
from crypto_strategy_lab.data.backtest_service import (
    _align_research_frame_to_strategy,
    _support_resistance_cache_request,
)
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.research_adapters import native_simulator_config
from crypto_strategy_lab.research_warmup import (
    expand_strategy_request,
    strategy_warmup_period,
    support_resistance_history_period,
)


UTC = timezone.utc


def test_default_strategy_warmup_covers_signal_and_state_context() -> None:
    config = ResearchRunConfig()
    assert strategy_warmup_period(config) == pd.Timedelta(days=22, minutes=30)


def test_asset_return_regime_extends_warmup_to_regime_lookback() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        features=replace(
            base.features,
            market_regime_method="ASSET_RETURN",
            bull_regime_lookback_days=90,
        ),
    )
    assert strategy_warmup_period(config) == pd.Timedelta(days=90, minutes=30)


def test_daily_strategy_warmup_covers_ema_200_before_research_start() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        data=replace(
            base.data,
            strategy_timeframe_minutes=1440,
            use_intrabar_data=False,
        ),
    )
    assert strategy_warmup_period(config) == pd.Timedelta(days=207)


def test_support_resistance_warmup_uses_its_configured_timeframe() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        data=replace(
            base.data,
            strategy_timeframe_minutes=240,
            intrabar_timeframe_minutes=60,
        ),
        features=replace(
            base.features,
            enable_support_resistance_analysis=True,
            sr_timeframe_minutes=1440,
            sr_lookback_bars=200,
            sr_pivot_left=5,
            sr_pivot_right=5,
        ),
    )
    # v6 1D structure uses a one-year horizon plus pivot/ATR/hold warm-up.
    assert strategy_warmup_period(config) == pd.Timedelta(days=392, hours=8)


def test_multitimeframe_sr_warmup_covers_highest_independent_context() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        data=replace(
            base.data,
            strategy_timeframe_minutes=15,
            intrabar_timeframe_minutes=1,
        ),
        features=replace(
            base.features,
            enable_support_resistance_analysis=True,
            sr_timeframe_minutes=0,
            sr_lookback_bars=200,
            sr_pivot_left=5,
            sr_pivot_right=5,
        ),
    )
    # 1d is the highest independent context for a 15m strategy. v6 warms a
    # full one-year structural horizon plus pivot confirmation, ATR anchoring,
    # hold confirmation, and the normal strategy-bar safety margin.
    assert strategy_warmup_period(config) >= pd.Timedelta(days=392)


def test_v6_sr_warmup_covers_each_timeframe_structural_horizon() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        data=replace(
            base.data,
            strategy_timeframe_minutes=15,
            intrabar_timeframe_minutes=1,
        ),
        features=replace(
            base.features,
            enable_support_resistance_analysis=True,
        ),
    )

    duration = strategy_warmup_period(config)

    # Daily is the deepest prepared context and therefore governs this run.
    assert duration >= pd.Timedelta(days=392)
    assert config.features.sr_detection_parameters(15)["sr_lookback_bars"] == 672
    assert config.features.sr_detection_parameters(60)["sr_lookback_bars"] == 720
    assert config.features.sr_detection_parameters(240)["sr_lookback_bars"] == 540
    assert config.features.sr_detection_parameters(1440)["sr_lookback_bars"] == 365


def test_sr_cache_scope_is_independent_of_unrelated_outer_warmup() -> None:
    base = ResearchRunConfig()
    config = replace(
        base,
        data=replace(base.data, strategy_timeframe_minutes=15),
        features=replace(base.features, enable_support_resistance_analysis=True),
    )
    research_start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 7, 1, tzinfo=UTC)
    outer_a = DataRequest(
        symbol="BTCUSDT",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=end,
        strategy_interval="15m",
    )
    outer_b = replace(outer_a, start=datetime(2025, 1, 1, tzinfo=UTC))

    scoped_a = _support_resistance_cache_request(
        outer_a,
        research_start=research_start,
        features=config.features,
        strategy_minutes=15,
    )
    scoped_b = _support_resistance_cache_request(
        outer_b,
        research_start=research_start,
        features=config.features,
        strategy_minutes=15,
    )

    expected = (
        pd.Timestamp(research_start)
        - support_resistance_history_period(config.features, 15)
        - pd.Timedelta(minutes=30)
    )
    assert pd.Timestamp(scoped_a.start) == expected
    assert scoped_a.start == scoped_b.start
    assert scoped_a.end == scoped_b.end == end


def test_expanded_strategy_request_clamps_to_available_history() -> None:
    request = DataRequest(
        symbol="BTCUSDT",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 2, 1, tzinfo=UTC),
        strategy_interval="15m",
        intrabar_interval="1m",
    )
    earliest = datetime(2025, 12, 20, tzinfo=UTC)
    expanded = expand_strategy_request(
        request,
        ResearchRunConfig(),
        earliest_start=earliest,
    )
    assert expanded.start == earliest
    assert expanded.end == request.end
    assert expanded.intrabar_interval == request.intrabar_interval


def test_optional_research_rows_are_padded_only_for_strategy_warmup() -> None:
    times = pd.date_range("2026-01-01", periods=3, freq="15min", tz="UTC")
    strategy = pd.DataFrame(
        {
            "period_start": times,
            "available_at": times + pd.Timedelta(minutes=15),
        }
    )
    feature = pd.DataFrame(
        {
            "timestamp": times[1:],
            "available_at": times[1:] + pd.Timedelta(minutes=15),
            "value": [1.0, 2.0],
            "funding_settlements_json": ["[]", "[[1,0.0001]]"],
        }
    )
    feature.attrs["feature_cache_key"] = "research-scope-key"

    aligned = _align_research_frame_to_strategy(feature, strategy)

    assert aligned["timestamp"].tolist() == times.tolist()
    assert np.isnan(aligned.loc[0, "value"])
    assert aligned.loc[1:, "value"].tolist() == [1.0, 2.0]
    assert aligned.loc[0, "available_at"] == strategy.loc[0, "available_at"]
    assert aligned.loc[0, "funding_settlements_json"] == "[]"
    assert aligned.loc[1:, "funding_settlements_json"].tolist() == [
        "[]",
        "[[1,0.0001]]",
    ]
    assert aligned.attrs["feature_cache_key"] == "research-scope-key"


def test_native_simulator_config_normalizes_profile_integer_looking_floats() -> None:
    base = ResearchRunConfig()
    strategy_profiles = dict(base.strategy.profiles)
    execution_profiles = dict(base.execution.profiles)
    strategy_profiles["bull_long"] = replace(
        strategy_profiles["bull_long"],
        rsi_period=14.0,
        momentum_lookback_hours=24.0,
    )
    execution_profiles["bull_long"] = replace(
        execution_profiles["bull_long"],
        timeout_minutes=480.0,
    )
    strategy = replace(base.strategy, profiles=strategy_profiles)
    execution = replace(base.execution, profiles=execution_profiles)

    native = native_simulator_config(
        base.data,
        base.features,
        strategy,
        execution,
    )

    profile = native.strategy_profiles["bull_long"]
    assert type(profile.rsi_period) is int
    assert type(profile.momentum_lookback_hours) is int
    assert type(profile.timeout_minutes) is int


def test_native_simulator_window_preserves_end_exclusive_request() -> None:
    config = ResearchRunConfig()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)

    native = native_simulator_config(
        config.data,
        config.features,
        config.strategy,
        config.execution,
        trading_start=start,
        trading_end=end,
    )

    native_start = pd.Timestamp(native.trading_start_date)
    native_end = pd.Timestamp(native.trading_end_date)
    assert native_start == pd.Timestamp(start).tz_localize(None)
    assert native_end + pd.Timedelta(nanoseconds=1) == pd.Timestamp(end).tz_localize(None)
