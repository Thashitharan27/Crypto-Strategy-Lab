from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_strategy_lab.data import DataRequest
from crypto_strategy_lab.data.backtest_service import _align_research_frame_to_strategy
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.research_adapters import native_simulator_config
from crypto_strategy_lab.research_warmup import (
    expand_strategy_request,
    strategy_warmup_period,
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
    assert strategy_warmup_period(config) == pd.Timedelta(days=210, hours=8)


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
        }
    )
    feature.attrs["feature_cache_key"] = "research-scope-key"

    aligned = _align_research_frame_to_strategy(feature, strategy)

    assert aligned["timestamp"].tolist() == times.tolist()
    assert np.isnan(aligned.loc[0, "value"])
    assert aligned.loc[1:, "value"].tolist() == [1.0, 2.0]
    assert aligned.loc[0, "available_at"] == strategy.loc[0, "available_at"]
    assert aligned.attrs["feature_cache_key"] == "research-scope-key"


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
