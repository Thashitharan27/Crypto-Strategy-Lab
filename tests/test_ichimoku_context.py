from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pandas.testing as pdt

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features import production_feature_registry
from crypto_strategy_lab.features.ichimoku import (
    ICHIMOKU_CONTEXT_FEATURE_NAME,
    IchimokuContextFeatureProvider,
)
from crypto_strategy_lab.rule_native_engine import (
    RuleAwareDataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import compile_profiles, new_rule
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS


def _klines(n: int = 500) -> pd.DataFrame:
    times = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    x = np.arange(n, dtype=float)
    center = 100.0 + x * 0.04 + np.sin(x / 9.0) * 4.0
    open_ = center + np.sin(x / 5.0) * 0.25
    close = center + np.cos(x / 7.0) * 0.45
    return pd.DataFrame(
        {
            "period_start": times,
            "period_end": times + pd.Timedelta(minutes=15),
            "available_at": times + pd.Timedelta(minutes=15),
            "open": open_,
            "high": np.maximum(open_, close) + 1.2,
            "low": np.minimum(open_, close) - 1.2,
            "close": close,
            "volume": 100.0 + x % 17,
        }
    )


def _request(frame: pd.DataFrame) -> DataRequest:
    return DataRequest(
        symbol="BTCUSDT",
        start=frame.period_start.iloc[0].to_pydatetime(),
        end=(frame.period_start.iloc[-1] + pd.Timedelta(minutes=15)).to_pydatetime(),
        strategy_interval="15m",
    )


def _parameters(timeframe_minutes: int = 0) -> dict[str, object]:
    return {
        "timeframe_minutes": timeframe_minutes,
        "conversion_period": 9,
        "base_period": 26,
        "span_b_period": 52,
        "displacement": 26,
        "atr_period": 14,
    }


def test_registry_exposes_versioned_ichimoku_context() -> None:
    registry = production_feature_registry()
    assert ICHIMOKU_CONTEXT_FEATURE_NAME in registry.names()
    definition = registry.get(ICHIMOKU_CONTEXT_FEATURE_NAME).definition
    assert definition.version == "1"
    assert definition.warmup_bars == 78


def test_classic_ichimoku_uses_causal_visual_displacement() -> None:
    frame = _klines(180)
    provider = IchimokuContextFeatureProvider()
    output = provider.compute(
        _request(frame),
        {DatasetKind.KLINES: frame},
        _parameters(),
    )
    provider.definition.validate_output(output, _parameters())

    # Span B first exists after 52 completed candles. The cloud visible at the
    # current candle uses that value only after the 26-bar visual displacement.
    assert np.isnan(output.loc[50, "ichimoku_future_span_b"])
    assert np.isfinite(output.loc[51, "ichimoku_future_span_b"])
    assert np.isnan(output.loc[76, "ichimoku_current_span_b"])
    assert np.isfinite(output.loc[77, "ichimoku_current_span_b"])

    # Chikou confirmation is stored on today's row and compares against the
    # historical close; today's close is never written into a historical row.
    assert output.loc[25, "chikou_vs_price"] == "UNKNOWN"
    assert output.loc[26, "chikou_vs_price"] in {
        "ABOVE_PRICE",
        "BELOW_PRICE",
        "AT_PRICE",
    }
    assert output.loc[26, "timestamp"] == frame.loc[26, "period_start"]


def test_future_price_mutation_cannot_change_past_ichimoku_rows() -> None:
    frame = _klines(220)
    request = _request(frame)
    provider = IchimokuContextFeatureProvider()
    baseline = provider.compute(
        request,
        {DatasetKind.KLINES: frame},
        _parameters(),
    )

    cutoff = 130
    mutated = frame.copy()
    future = mutated.index > cutoff
    mutated.loc[future, ["open", "high", "low", "close"]] *= 1.7
    changed = provider.compute(
        request,
        {DatasetKind.KLINES: mutated},
        _parameters(),
    )

    pdt.assert_frame_equal(
        baseline.iloc[: cutoff + 1].reset_index(drop=True),
        changed.iloc[: cutoff + 1].reset_index(drop=True),
        check_dtype=False,
    )


def test_higher_timeframe_context_uses_only_completed_candles() -> None:
    frame = _klines(500)
    provider = IchimokuContextFeatureProvider()
    output = provider.compute(
        _request(frame),
        {DatasetKind.KLINES: frame},
        _parameters(60),
    )

    assert pd.isna(output.loc[0, "ichimoku_completed_candle_time"])
    first_completed = output.loc[3, "ichimoku_completed_candle_time"]
    assert first_completed == frame.loc[0, "period_start"]
    assert output.loc[3, "available_at"] == frame.loc[3, "available_at"]
    assert output.loc[3, "ichimoku_timeframe_minutes"] == 60.0

    available = output["ichimoku_completed_candle_time"].notna()
    selected = pd.to_datetime(
        output.loc[available, "ichimoku_completed_candle_time"], utc=True
    )
    decisions = pd.to_datetime(output.loc[available, "available_at"], utc=True)
    assert bool((selected < decisions).all())


def test_ichimoku_evidence_is_authorable_without_new_signal_mode() -> None:
    expected = {
        "ICH_PRICE_VS_CLOUD",
        "ICH_TK_STATE",
        "ICH_TK_CROSS",
        "ICH_KIJUN_DISTANCE_ATR",
        "ICH_FUTURE_CLOUD_STATE",
        "ICH_CLOUD_THICKNESS_ATR",
        "ICH_KUMO_TWIST",
        "ICH_CHIKOU_VS_PRICE",
    }
    assert expected <= set(RULE_INDICATORS)

    rule = new_rule(kind="REQUIRED", evidence="ICH_PRICE_VS_CLOUD")
    assert rule["operator"] == "IS"
    assert rule["value"] == "ABOVE_CLOUD"

    profiles, _execution = compile_profiles(
        direction_mode="DI",
        market_permissions=("BULL_LONG",),
        required_rules=(rule,),
    )
    native = profiles["bull_long"].entry_rules[0]
    assert native["indicator"] == "ICH_PRICE_VS_CLOUD"
    assert native["minimum"] == native["maximum"] == 1.0


def test_native_rules_read_prepared_ichimoku_context() -> None:
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.research_features = {
        "ichimoku_context": pd.DataFrame(
            {
                "price_vs_cloud": ["ABOVE_CLOUD"],
                "tk_state": ["BULLISH"],
                "tk_cross": ["NONE"],
                "tk_spread_atr": [0.35],
                "tenkan_distance_atr": [0.25],
                "kijun_distance_atr": [0.60],
                "kijun_slope_atr": [0.08],
                "kijun_flat_bars": [2.0],
                "current_cloud_state": ["BULLISH"],
                "future_cloud_state": ["BULLISH"],
                "cloud_thickness_atr": [0.70],
                "future_cloud_thickness_atr": [0.85],
                "kumo_twist": ["NONE"],
                "chikou_vs_price": ["ABOVE_PRICE"],
                "cloud_distance_atr": [0.40],
            }
        )
    }
    profile = SimpleNamespace()

    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "ICH_PRICE_VS_CLOUD"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "ICH_FUTURE_CLOUD_STATE"
    ) == 1.0
    assert engine._strategy_profile_rule_value(
        0, "LONG", profile, "ICH_KIJUN_DISTANCE_ATR"
    ) == 0.60
