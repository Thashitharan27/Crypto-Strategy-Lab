from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.data import DataRequest, DatasetKind, MarketKind
from crypto_strategy_lab.features import production_feature_registry
from feature_causality_harness import CausalityCase, assert_future_mutation_invariant


STRATEGY_INTERVAL = "4h"
STRATEGY_DELTA = pd.Timedelta(STRATEGY_INTERVAL)


def _request(klines: pd.DataFrame) -> DataRequest:
    return DataRequest(
        symbol="BTCUSDT",
        start=pd.Timestamp(klines.period_start.iloc[0]).to_pydatetime(),
        end=(pd.Timestamp(klines.period_start.iloc[-1]) + STRATEGY_DELTA).to_pydatetime(),
        strategy_interval=STRATEGY_INTERVAL,
        market=MarketKind.FUTURES_UM,
    )


def _klines(n: int = 300) -> pd.DataFrame:
    times = pd.date_range("2025-01-01", periods=n, freq=STRATEGY_INTERVAL, tz="UTC")
    phase = np.arange(n, dtype=float)
    center = 100.0 + phase * 0.035 + np.sin(phase / 6.0) * 4.0 + np.sin(phase / 19.0) * 2.0
    open_ = center + np.sin(phase / 5.0) * 0.35
    close = center + np.cos(phase / 4.0) * 0.55
    high = np.maximum(open_, close) + 1.4
    low = np.minimum(open_, close) - 1.4
    frame = pd.DataFrame(
        {
            "period_start": times,
            "period_end": times + STRATEGY_DELTA,
            "available_at": times + STRATEGY_DELTA,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0 + (phase % 31) * 3.0,
        }
    )
    frame.attrs["canonical_source_identity"] = "fixture-klines-v1"
    return frame


def _reference_klines(source: pd.DataFrame, offset: float, identity: str) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "period_start": source.period_start,
            "period_end": source.period_end,
            "available_at": source.available_at,
            "close": pd.to_numeric(source.close) + offset,
        }
    )
    frame.attrs["canonical_source_identity"] = identity
    return frame


def _metrics(source: pd.DataFrame) -> pd.DataFrame:
    times = pd.date_range(
        pd.Timestamp(source.period_start.iloc[0]) + pd.Timedelta(hours=1),
        pd.Timestamp(source.period_end.iloc[-1]),
        freq="2h",
        inclusive="left",
    )
    x = np.arange(len(times), dtype=float)
    frame = pd.DataFrame(
        {
            "event_time": times,
            "period_start": times,
            "available_at": times,
            "open_interest": 10_000.0 + x * 3.0,
            "open_interest_value": 1_000_000.0 + x * 250.0,
            "top_trader_account_long_short_ratio": 1.05 + np.sin(x / 11.0) * 0.1,
            "top_trader_position_long_short_ratio": 1.10 + np.cos(x / 13.0) * 0.1,
            "global_long_short_account_ratio": 0.95 + np.sin(x / 17.0) * 0.08,
            "taker_long_short_volume_ratio": 1.0 + np.cos(x / 7.0) * 0.12,
        }
    )
    frame.attrs["canonical_source_identity"] = "fixture-metrics-v1"
    return frame


def _funding(source: pd.DataFrame) -> pd.DataFrame:
    times = pd.date_range(
        pd.Timestamp(source.period_start.iloc[0]),
        pd.Timestamp(source.period_end.iloc[-1]),
        freq="8h",
        inclusive="left",
    )
    x = np.arange(len(times), dtype=float)
    frame = pd.DataFrame(
        {
            "event_time": times,
            "period_start": times,
            "available_at": times,
            "funding_rate": np.sin(x / 5.0) * 0.0002,
            "funding_interval_hours": 8.0,
        }
    )
    frame.attrs["canonical_source_identity"] = "fixture-funding-v1"
    return frame


def _agg_trades(source: pd.DataFrame) -> pd.DataFrame:
    rows = []
    agg_id = 1
    for i, row in source.iterrows():
        for hours, maker, scale in ((1, False, 0.999), (2, True, 1.001)):
            event = pd.Timestamp(row.period_start) + pd.Timedelta(hours=hours)
            rows.append(
                {
                    "event_time": event,
                    "period_start": event,
                    "available_at": event,
                    "agg_trade_id": agg_id,
                    "price": float(row.close) * scale,
                    "quantity": 1.0 + (i % 7) * 0.1,
                    "is_buyer_maker": maker,
                    "first_trade_id": agg_id * 2,
                    "last_trade_id": agg_id * 2 + 1,
                }
            )
            agg_id += 1
    frame = pd.DataFrame(rows)
    frame.attrs["canonical_source_identity"] = "fixture-agg-v1"
    return frame


def _structural_benchmark() -> pd.DataFrame:
    times = pd.date_range("2024-12-01", periods=24 * 90, freq="1h", tz="UTC")
    x = np.arange(len(times), dtype=float)
    close = 80.0 + x * 0.012 + np.sin(x / 40.0) * 3.0
    frame = pd.DataFrame(
        {
            "period_start": times,
            "available_at": times + pd.Timedelta(hours=1),
            "close": close,
        }
    )
    return frame


def _registry(context):
    return production_feature_registry(structural_benchmark=context.get("structural_benchmark"))


def _mutate_future_klines(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    frame.loc[mask, ["open", "high", "low", "close"]] *= 1.35
    frame.loc[mask, "volume"] *= 2.0


def _mutate_future_metrics(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    for column in (
        "open_interest",
        "open_interest_value",
        "top_trader_account_long_short_ratio",
        "top_trader_position_long_short_ratio",
        "global_long_short_account_ratio",
        "taker_long_short_volume_ratio",
    ):
        frame.loc[mask, column] *= 1.7


def _mutate_future_funding(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    frame.loc[mask, "funding_rate"] = frame.loc[mask, "funding_rate"] * -3.0 + 0.0007


def _mutate_future_reference(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    frame.loc[mask, "close"] *= 1.4


def _mutate_future_agg(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    frame.loc[mask, "price"] *= 1.2
    frame.loc[mask, "quantity"] *= 3.0
    frame.loc[mask, "is_buyer_maker"] = ~frame.loc[mask, "is_buyer_maker"].astype(bool)


def _mutate_future_benchmark(frame: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    mask = pd.to_datetime(frame.available_at, utc=True) > cutoff
    assert mask.any()
    frame.loc[mask, "close"] *= 1.6


def _core_parameters():
    return {
        "core_directional": {
            "atr_period": 7,
            "adx_period": 6,
            "di_pressure_lookback": 3,
        }
    }


def _market_parameters():
    return {
        **_core_parameters(),
        "market_context": {
            "bb_period": 12,
            "bb_stddevs": 2.0,
            "mean_reversion_period": 10,
        },
    }


def _production_parameters():
    return {
        **_core_parameters(),
        "production_market_context": {
            "bb_period": 12,
            "bb_stddevs": 2.0,
            "mean_reversion_period": 10,
            "mean_reversion_mean_type": "SMA",
            "mean_reversion_bb_stddevs": 2.0,
            "mean_reversion_rsi_period": 7,
            "mean_reversion_rsi_oversold": 30.0,
            "mean_reversion_rsi_overbought": 70.0,
            "mean_reversion_require_reentry": True,
        },
    }


def _support_parameters():
    return {
        **_core_parameters(),
        "support_resistance": {
            "atr_period": 7,
            "sr_timeframe_minutes": 240,
            "sr_pivot_left": 2,
            "sr_pivot_right": 2,
            "sr_lookback_bars": 60,
            "sr_zone_width_atr": 0.5,
            "sr_near_distance_atr": 0.75,
            "enable_sr_hold_confirmation": False,
            "sr_hold_confirmation_bars": 3,
            "sr_hold_confirmation_atr": 0.25,
            "sr_break_tolerance_atr": 0.25,
            "sr_break_basis": "CLOSE",
        },
    }


def _cases() -> list[CausalityCase]:
    klines = _klines()
    request = _request(klines)
    mark = _reference_klines(klines, 0.25, "fixture-mark-v1")
    index = _reference_klines(klines, -0.15, "fixture-index-v1")
    premium = _reference_klines(klines, 0.05, "fixture-premium-v1")
    metrics = _metrics(klines)
    funding = _funding(klines)
    agg = _agg_trades(klines)

    return [
        CausalityCase(
            "core_directional", _registry, request,
            {DatasetKind.KLINES: klines}, _core_parameters(),
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "market_context", _registry, request,
            {DatasetKind.KLINES: klines}, _market_parameters(),
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "production_market_context", _registry, request,
            {DatasetKind.KLINES: klines}, _production_parameters(),
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "policy_market_context", _registry, request,
            {DatasetKind.KLINES: klines},
            {"policy_market_context": {
                "market_regime_method": "ASSET_RETURN",
                "bull_regime_lookback_days": 5,
                "bull_regime_return_threshold": 0.02,
                "structural_regime_sma_days": 5,
                "structural_regime_slope_lookback_days": 2,
                "momentum_lookback_hours": (8, 24),
            }},
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "policy_market_context", _registry, request,
            {DatasetKind.KLINES: klines},
            {"policy_market_context": {
                "market_regime_method": "BTC_STRUCTURAL",
                "bull_regime_lookback_days": 5,
                "bull_regime_return_threshold": 0.02,
                "structural_regime_sma_days": 5,
                "structural_regime_slope_lookback_days": 2,
                "momentum_lookback_hours": (8, 24),
            }},
            {DatasetKind.KLINES: _mutate_future_klines},
            context={"structural_benchmark": _structural_benchmark()},
            future_context_mutators={"structural_benchmark": _mutate_future_benchmark},
        ),
        CausalityCase(
            "support_resistance", _registry, request,
            {DatasetKind.KLINES: klines}, _support_parameters(),
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "state_transition_daily", _registry, request,
            {DatasetKind.KLINES: klines},
            {"state_transition_daily": {
                "regime_lookback_days": 5,
                "bull_return_threshold": 0.02,
                "bear_return_threshold": -0.02,
                "volatility_lookback_days": 5,
                "volatility_reference_days": 20,
                "volatility_low_quantile": 0.33,
                "volatility_high_quantile": 0.67,
                "minimum_state_observations": 5,
                "minimum_trade_observations": 5,
            }},
            {DatasetKind.KLINES: _mutate_future_klines},
        ),
        CausalityCase(
            "futures_positioning", _registry, request,
            {DatasetKind.KLINES: klines, DatasetKind.FUTURES_METRICS: metrics}, {},
            {
                DatasetKind.KLINES: _mutate_future_klines,
                DatasetKind.FUTURES_METRICS: _mutate_future_metrics,
            },
        ),
        CausalityCase(
            "funding_context", _registry, request,
            {DatasetKind.KLINES: klines, DatasetKind.FUNDING_RATE: funding}, {},
            {
                DatasetKind.KLINES: _mutate_future_klines,
                DatasetKind.FUNDING_RATE: _mutate_future_funding,
            },
        ),
        CausalityCase(
            "basis_context", _registry, request,
            {
                DatasetKind.KLINES: klines,
                DatasetKind.MARK_PRICE_KLINES: mark,
                DatasetKind.INDEX_PRICE_KLINES: index,
                DatasetKind.PREMIUM_INDEX_KLINES: premium,
            },
            {},
            {
                DatasetKind.KLINES: _mutate_future_klines,
                DatasetKind.MARK_PRICE_KLINES: _mutate_future_reference,
                DatasetKind.INDEX_PRICE_KLINES: _mutate_future_reference,
                DatasetKind.PREMIUM_INDEX_KLINES: _mutate_future_reference,
            },
        ),
        CausalityCase(
            "agg_trade_flow", _registry, request,
            {DatasetKind.KLINES: klines, DatasetKind.AGG_TRADES: agg}, {},
            {
                DatasetKind.KLINES: _mutate_future_klines,
                DatasetKind.AGG_TRADES: _mutate_future_agg,
            },
        ),
    ]


@pytest.mark.parametrize("case", _cases(), ids=[
    "core-directional-di",
    "market-context-mr",
    "production-context-mr-v2",
    "policy-regime-asset-return",
    "policy-regime-structural",
    "support-resistance",
    "state-transition-daily",
    "futures-positioning",
    "funding-context",
    "basis-context",
    "agg-trade-flow",
])
def test_registered_feature_is_invariant_to_future_source_mutation(case: CausalityCase) -> None:
    assert_future_mutation_invariant(case)
