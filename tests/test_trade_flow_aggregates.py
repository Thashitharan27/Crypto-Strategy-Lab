from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.data.binance.trades import TradesArchiveAdapter
from crypto_strategy_lab.data.schemas import ArchiveRecord, DatasetKind, MarketKind
from crypto_strategy_lab.data.trade_aggregates import TradeAggregateStore
from crypto_strategy_lab.features.trade_flow import TradeFlowContextFeatureProvider, trade_flow_resource
from crypto_strategy_lab.data.query import DataRequest


def record(path: Path, dataset=DatasetKind.TRADES):
    return ArchiveRecord(path.parent, path, MarketKind.FUTURES_UM, dataset, "BTCUSDT", None,
                         "daily", datetime(2026,1,1,tzinfo=UTC), datetime(2026,1,2,tzinfo=UTC),
                         path.stat().st_size, path.stat().st_mtime_ns, "source", "binance")


def test_raw_trades_adapter_direction_and_microseconds(tmp_path):
    path = tmp_path / "trades.csv"
    path.write_text("trade_id,price,quantity,quote_quantity,transact_time,is_buyer_maker\n"
                    "1,100,2,200,1767225599999000,false\n2,101,1,101,1767225600000000,true\n")
    frame = TradesArchiveAdapter().read(record(path))
    assert frame.taker_side.tolist() == ["BUY", "SELL"]
    assert frame.available_at.equals(frame.event_time)
    assert frame.event_time.iloc[0] == pd.Timestamp("2025-12-31 23:59:59.999Z")


def test_exact_aggregate_and_boundary(tmp_path):
    path = tmp_path / "trades.csv"; path.write_text("x")
    rec = record(path)
    events = pd.DataFrame({"event_time": pd.to_datetime(["2026-01-01 11:59:59.999Z", "2026-01-01 12:00:00Z"], format="mixed"),
        "trade_id": [1,2], "price": [100.,110.], "quantity": [2.,1.], "quote_quantity": [200.,110.],
        "is_buyer_maker": [False,True]})
    out = TradeAggregateStore._aggregate(rec, events, None)
    first = out.loc[out.period_start == pd.Timestamp("2026-01-01 11:59Z")].iloc[0]
    second = out.loc[out.period_start == pd.Timestamp("2026-01-01 12:00Z")].iloc[0]
    assert first.available_at == pd.Timestamp("2026-01-01 12:00Z")
    assert first.source_event_count == first.underlying_trade_count == 1
    assert first.aggressive_buy_base_volume == 2 and first.trade_delta_base == 2
    assert first.weighted_price_sum / first.base_volume == 100
    assert second.aggressive_sell_base_volume == 1 and second.trade_delta_base == -1


def test_provider_rejects_raw_event_resource_and_preserves_coverage():
    request = DataRequest("BTCUSDT", datetime(2026,1,1,tzinfo=UTC), datetime(2026,1,2,tzinfo=UTC), "1m")
    klines = pd.DataFrame({"period_start": pd.to_datetime(["2026-01-01 00:00Z"]),
                           "available_at": pd.to_datetime(["2026-01-01 00:01Z"])})
    raw = pd.DataFrame({"trade_id": [1]})
    with pytest.raises(ValueError, match="raw trade-event"):
        TradeFlowContextFeatureProvider().compute(request, {DatasetKind.KLINES: klines,
            trade_flow_resource(DatasetKind.TRADES): raw},
            {"trade_flow_source":"TRADES", "trade_flow_windows":("1m",)})


@pytest.mark.parametrize("source", [DatasetKind.AGG_TRADES, DatasetKind.TRADES])
def test_future_aggregate_mutation_cannot_change_past(source):
    starts = pd.date_range("2026-01-01", periods=120, freq="1min", tz="UTC")
    agg = pd.DataFrame({"period_start": starts, "period_end": starts + pd.Timedelta(minutes=1),
        "available_at": starts + pd.Timedelta(minutes=1), "trade_flow_source_covered": True,
        "underlying_trade_count": 1, "source_event_count": 1, "base_volume": 1., "quote_volume": 100.,
        "aggressive_buy_base_volume": 1., "aggressive_sell_base_volume": 0., "trade_delta_base": 1.,
        "weighted_price_sum": 100., "last_event_at": starts + pd.Timedelta(seconds=30)})
    klines = pd.DataFrame({"period_start": starts, "available_at": starts + pd.Timedelta(minutes=1)})
    request = DataRequest("BTCUSDT", starts[0].to_pydatetime(), (starts[-1]+pd.Timedelta(minutes=1)).to_pydatetime(), "1m")
    provider = TradeFlowContextFeatureProvider(); resource = trade_flow_resource(source)
    params = {"trade_flow_source": source.name, "trade_flow_windows": ("1m","5m","1h")}
    before = provider.compute(request, {DatasetKind.KLINES: klines, resource: agg}, params)
    cutoff = starts[60]
    changed = agg.copy(); changed.loc[changed.available_at > cutoff, "trade_delta_base"] = -99.
    after = provider.compute(request, {DatasetKind.KLINES: klines, resource: changed}, params)
    mask = before.available_at <= cutoff
    pd.testing.assert_frame_equal(before.loc[mask].reset_index(drop=True), after.loc[mask].reset_index(drop=True))
