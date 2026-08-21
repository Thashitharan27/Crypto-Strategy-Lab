from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features.futures_positioning import FuturesPositioningFeatureProvider


def klines(n: int = 6) -> pd.DataFrame:
    starts = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="4h")
    close = 100.0 + np.arange(n) * 2.0
    return pd.DataFrame(
        {
            "period_start": starts,
            "available_at": starts + pd.Timedelta(hours=4),
            "close": close,
            "source_fingerprint": "kline-source-a",
        }
    )


def metrics() -> pd.DataFrame:
    times = pd.to_datetime(
        [
            "2026-01-01T03:55:00Z",
            "2026-01-01T04:05:00Z",  # future relative to first candle close
            "2026-01-01T07:55:00Z",
            "2026-01-01T11:55:00Z",
            "2026-01-01T15:55:00Z",
            "2026-01-01T19:55:00Z",
            "2026-01-01T23:55:00Z",
        ],
        utc=True,
    )
    oi = [100.0, 999.0, 110.0, 105.0, 120.0, 126.0, 121.0]
    return pd.DataFrame(
        {
            "available_at": times,
            "open_interest": oi,
            "open_interest_value": np.asarray(oi) * 1000.0,
            "top_trader_account_long_short_ratio": [1.1, 9.9, 1.2, 0.9, 1.3, 1.4, 1.1],
            "top_trader_position_long_short_ratio": [1.05, 9.8, 1.1, 0.95, 1.2, 1.3, 1.0],
            "global_long_short_account_ratio": [0.95, 9.7, 1.0, 1.05, 1.1, 0.9, 0.85],
            "taker_long_short_volume_ratio": [1.2, 9.6, 0.8, 1.3, 1.4, 0.7, 0.9],
            "source_fingerprint": "metrics-source-a",
        }
    )


def request(frame: pd.DataFrame) -> DataRequest:
    return DataRequest(
        symbol="BTCUSDT",
        start=frame.period_start.iloc[0].to_pydatetime(),
        end=(frame.period_start.iloc[-1] + pd.Timedelta(hours=4)).to_pydatetime(),
        strategy_interval="4h",
        datasets=(DatasetKind.KLINES, DatasetKind.FUTURES_METRICS),
    )


def prepared(kline_frame=None, metrics_frame=None) -> pd.DataFrame:
    kline_frame = klines() if kline_frame is None else kline_frame
    metrics_frame = metrics() if metrics_frame is None else metrics_frame
    return FuturesPositioningFeatureProvider().compute(
        request(kline_frame),
        {
            DatasetKind.KLINES: kline_frame,
            DatasetKind.FUTURES_METRICS: metrics_frame,
        },
        {},
    )


def test_positioning_uses_latest_snapshot_available_at_candle_close() -> None:
    result = prepared()

    # 04:00 close must use 03:55 OI=100, never the 04:05 future snapshot OI=999.
    assert result.loc[0, "metrics_source_available_at"] == pd.Timestamp("2026-01-01T03:55:00Z")
    assert result.loc[0, "open_interest"] == 100.0
    assert result.loc[0, "metrics_age_seconds"] == 300.0

    # 08:00 close uses the 07:55 snapshot, so the deliberately huge 04:05 value
    # cannot contaminate the aligned series.
    assert result.loc[1, "metrics_source_available_at"] == pd.Timestamp("2026-01-01T07:55:00Z")
    assert result.loc[1, "open_interest"] == 110.0
    assert np.isclose(result.loc[1, "open_interest_change_1bar_pct"], 0.10)
    assert result.loc[1, "price_oi_state"] == "PRICE_UP_OI_UP"
    assert np.isclose(result.loc[0, "taker_long_short_volume_bias"], 0.2)

    assert bool((result["metrics_source_available_at"] <= result["available_at"]).all())


def test_future_metrics_mutation_cannot_change_past_positioning() -> None:
    source = metrics()
    before = prepared(metrics_frame=source)
    cutoff_time = pd.Timestamp("2026-01-01T12:00:00Z")

    changed = source.copy()
    changed.loc[changed.available_at > cutoff_time, "open_interest"] *= 100.0
    changed.loc[changed.available_at > cutoff_time, "taker_long_short_volume_ratio"] = 99.0
    after = prepared(metrics_frame=changed)

    past_rows = before.available_at <= cutoff_time
    columns = [
        "open_interest",
        "open_interest_change_1bar_pct",
        "open_interest_change_3bar_pct",
        "taker_long_short_volume_ratio",
        "taker_long_short_volume_bias",
        "price_oi_state",
    ]
    pdt.assert_frame_equal(
        before.loc[past_rows, columns].reset_index(drop=True),
        after.loc[past_rows, columns].reset_index(drop=True),
        check_dtype=False,
    )


def test_missing_optional_metrics_columns_remain_nan_without_breaking_alignment() -> None:
    sparse = metrics()[["available_at", "open_interest", "source_fingerprint"]].copy()
    result = prepared(metrics_frame=sparse)
    assert result["open_interest"].notna().all()
    assert result["top_trader_account_long_short_ratio"].isna().all()
    assert result["global_long_short_account_bias"].isna().all()
