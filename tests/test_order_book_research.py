from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.order_book import OrderBookSnapshotStore
from crypto_strategy_lab.data.schemas import ArchiveRecord, DatasetKind, MarketKind
from crypto_strategy_lab.features.order_book import (OrderBookContextFeatureProvider,
                                                       book_depth_resource,
                                                       book_ticker_resource)

UTC = timezone.utc


def _record(dataset):
    return ArchiveRecord(raw_root=Path("."), path=Path("source.zip"), market=MarketKind.FUTURES_UM,
                         dataset=dataset, symbol="BTCUSDT", interval=None, frequency="daily",
                         period_start=datetime(2026, 1, 1, tzinfo=UTC),
                         period_end=datetime(2026, 1, 2, tzinfo=UTC), size_bytes=1,
                         mtime_ns=1, fingerprint="fixture")


def _strategy(decision="2026-01-01 12:00:00Z"):
    return pd.DataFrame({"period_start": pd.to_datetime([decision], utc=True),
                         "available_at": pd.to_datetime([decision], utc=True)})


def test_ticker_snapshot_is_causal_and_formulas_are_exact():
    events = pd.DataFrame({"event_time": pd.to_datetime([
        "2026-01-01 12:00:00Z", "2026-01-01 11:59:59.999Z"], utc=True, format="mixed"),
        "update_id": [2, 1], "best_bid_price": [50, 100], "best_bid_qty": [1, 4],
        "best_ask_price": [60, 102], "best_ask_qty": [1, 1]})
    compact = OrderBookSnapshotStore._compact_ticker(_record(DatasetKind.BOOK_TICKER), events)
    assert list(compact["available_at"]) == list(pd.to_datetime(["2026-01-01 12:00Z", "2026-01-01 12:01Z"], utc=True))
    provider = OrderBookContextFeatureProvider()
    result = provider.compute(None, {DatasetKind.KLINES: _strategy(), book_ticker_resource(): compact},
                              {"book_ticker_max_age_seconds": 5, "book_depth_max_age_seconds": 90})
    row = result.iloc[0]
    assert row.book_best_bid_price == 100
    assert row.book_spread == 2
    assert row.book_midprice == 101
    assert row.book_spread_bps == 2 / 101 * 10000
    assert row.book_imbalance_l1 == 3 / 5
    assert row.book_microprice == (102 * 4 + 100) / 5
    assert row.book_microprice_offset_bps == (row.book_microprice - 101) / 101 * 10000


def test_depth_partial_snapshot_retains_nan_and_band_formulas():
    percentages = [-5, -4, -3, -2, -1, 1, 2, 3, 4]
    events = pd.DataFrame({"event_time": pd.to_datetime(["2026-01-01 11:59:59Z"] * 9, utc=True),
                           "percentage": percentages,
                           "depth": [10, 10, 10, 10, 4, 1, 5, 5, 5],
                           "notional": [100] * 9})
    compact = OrderBookSnapshotStore._compact_depth(_record(DatasetKind.BOOK_DEPTH), events)
    assert not bool(compact.iloc[0].book_depth_snapshot_complete)
    assert np.isnan(compact.iloc[0].book_ask_depth_5pct)
    result = OrderBookContextFeatureProvider().compute(
        None, {DatasetKind.KLINES: _strategy(), book_depth_resource(): compact},
        {"book_ticker_max_age_seconds": 5, "book_depth_max_age_seconds": 90})
    assert result.iloc[0].book_bid_depth_1pct == 4
    assert result.iloc[0].book_ask_depth_1pct == 1
    assert result.iloc[0].book_depth_imbalance_1pct == 3 / 5
    assert result.iloc[0].book_depth_ratio_1pct == 4
    assert np.isnan(result.iloc[0].book_ask_depth_5pct)


def test_stale_ticker_values_are_masked():
    events = pd.DataFrame({"event_time": pd.to_datetime(["2026-01-01 11:59:40Z"], utc=True),
                           "update_id": [1], "best_bid_price": [100], "best_bid_qty": [4],
                           "best_ask_price": [102], "best_ask_qty": [1]})
    compact = OrderBookSnapshotStore._compact_ticker(_record(DatasetKind.BOOK_TICKER), events)
    result = OrderBookContextFeatureProvider().compute(
        None, {DatasetKind.KLINES: _strategy(), book_ticker_resource(): compact},
        {"book_ticker_max_age_seconds": 5, "book_depth_max_age_seconds": 90})
    assert bool(result.iloc[0].book_ticker_stale)
    assert np.isnan(result.iloc[0].book_spread)
