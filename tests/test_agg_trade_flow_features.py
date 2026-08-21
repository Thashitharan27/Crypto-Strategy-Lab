from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features.agg_trade_flow import AggTradeFlowFeatureProvider


def _klines() -> pd.DataFrame:
    starts = pd.date_range("2026-01-01T00:00:00Z", periods=3, freq="1h")
    return pd.DataFrame(
        {
            "period_start": starts,
            "period_end": starts + pd.Timedelta(hours=1),
            "available_at": starts + pd.Timedelta(hours=1),
            "close": [100.0, 101.0, 102.0],
            "source_fingerprint": "agg-flow-kline-source",
        }
    )


def _trades(include_future: bool = True) -> pd.DataFrame:
    event_time = pd.to_datetime(
        [
            "2026-01-01T00:10:00Z",
            "2026-01-01T00:20:00Z",
            "2026-01-01T01:00:00Z",  # exact boundary belongs to candle 2
            "2026-01-01T01:30:00Z",
        ]
        + (["2026-01-01T02:30:00Z"] if include_future else []),
        utc=True,
    )
    price = np.array([100.0, 101.0, 101.5, 100.5] + ([500.0] if include_future else []))
    quantity = np.array([2.0, 1.0, 3.0, 1.0] + ([100.0] if include_future else []))
    buyer_maker = np.array([False, True, False, True] + ([False] if include_future else []))
    first_id = np.array([1, 3, 4, 7] + ([8] if include_future else []))
    last_id = np.array([2, 3, 6, 7] + ([20] if include_future else []))
    return pd.DataFrame(
        {
            "event_time": event_time,
            "available_at": event_time,
            "price": price,
            "quantity": quantity,
            "quote_quantity": price * quantity,
            "is_buyer_maker": buyer_maker,
            "first_trade_id": first_id,
            "last_trade_id": last_id,
            "source_fingerprint": "agg-flow-event-source",
        }
    )


def _request() -> DataRequest:
    return DataRequest(
        symbol="BTCUSDT",
        start=pd.Timestamp("2026-01-01T00:00:00Z").to_pydatetime(),
        end=pd.Timestamp("2026-01-01T03:00:00Z").to_pydatetime(),
        strategy_interval="1h",
    )


def _compute(trades: pd.DataFrame) -> pd.DataFrame:
    return AggTradeFlowFeatureProvider().compute(
        _request(),
        {DatasetKind.KLINES: _klines(), DatasetKind.AGG_TRADES: trades},
        {},
    )


def test_agg_trade_flow_uses_end_exclusive_candle_boundaries() -> None:
    out = _compute(_trades())

    first = out.iloc[0]
    assert first["agg_trade_count"] == 2
    assert first["agg_underlying_trade_count"] == 3
    assert first["agg_taker_buy_base_volume"] == 2.0
    assert first["agg_taker_sell_base_volume"] == 1.0
    assert first["agg_taker_buy_sell_ratio"] == 2.0
    assert first["agg_taker_buy_share"] == 2.0 / 3.0
    assert first["agg_taker_imbalance"] == 1.0 / 3.0
    assert first["agg_aggressor_state"] == "BUY_PRESSURE"
    assert pd.Timestamp(first["agg_source_last_event_at"]) == pd.Timestamp("2026-01-01T00:20:00Z")

    second = out.iloc[1]
    assert second["agg_trade_count"] == 2
    assert second["agg_underlying_trade_count"] == 4
    assert second["agg_taker_buy_base_volume"] == 3.0
    assert second["agg_taker_sell_base_volume"] == 1.0
    # The 01:00 event must not leak backward into the 00:00-01:00 candle.
    assert second["agg_base_volume"] == 4.0


def test_future_agg_trade_mutation_cannot_change_past_flow() -> None:
    before = _compute(_trades(include_future=False))
    after = _compute(_trades(include_future=True))
    columns = [
        "agg_trade_count",
        "agg_underlying_trade_count",
        "agg_base_volume",
        "agg_taker_buy_base_volume",
        "agg_taker_sell_base_volume",
        "agg_taker_imbalance",
        "agg_aggressor_state",
        "agg_trade_vwap",
    ]
    pdt.assert_frame_equal(
        before.loc[:1, columns].reset_index(drop=True),
        after.loc[:1, columns].reset_index(drop=True),
        check_dtype=False,
    )


def test_agg_trade_flow_records_no_trade_candle_without_inventing_pressure() -> None:
    trades = _trades(include_future=False).iloc[:2].copy()
    out = _compute(trades)
    third = out.iloc[2]
    assert third["agg_trade_count"] == 0
    assert third["agg_base_volume"] == 0.0
    assert third["agg_aggressor_state"] == "NO_TRADES"
    assert np.isnan(third["agg_taker_imbalance"])
    assert pd.isna(third["agg_source_last_event_at"])
