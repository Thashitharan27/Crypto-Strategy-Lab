from datetime import datetime, timezone
import pandas as pd
from crypto_strategy_lab.data import (
    DataQualityStatus, DataRequest, DatasetKind, classify_archive_overlap, validate_dataset,
)


def request(interval="1h"):
    return DataRequest(symbol="BTCUSDT", start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 4, tzinfo=timezone.utc), strategy_interval=interval)


def candles():
    r = request(); starts = pd.date_range(r.start, r.end, freq="1h", inclusive="left")
    f = pd.DataFrame({"period_start": starts, "period_end": starts + pd.Timedelta("1h"),
        "available_at": starts + pd.Timedelta("1h"), "open": 2., "high": 3., "low": 1.,
        "close": 2., "volume": 1., "symbol": r.symbol, "exchange": r.exchange,
        "market": r.market.value, "dataset": "klines", "interval": "1h"})
    f.attrs["canonical_source_identity"] = "source-a"; return f


def test_complete_fixed_cadence_is_ok_and_gap_is_summarized():
    frame = candles()
    assert validate_dataset(frame, request(), DatasetKind.KLINES, interval="1h").status is DataQualityStatus.OK
    report = validate_dataset(frame.drop(index=[1, 2]), request(), DatasetKind.KLINES, interval="1h")
    issue = next(i for i in report.issues if i.code == "MISSING_INTERNAL_INTERVAL")
    assert issue.count == 2 and report.status is DataQualityStatus.ERROR


def test_event_stream_never_receives_regular_grid_issues():
    r = request(); times = pd.to_datetime([r.start, r.start + pd.Timedelta("3h")], utc=True)
    frame = pd.DataFrame({"event_time": times, "available_at": times, "funding_rate": [.1, -.2],
        "symbol": r.symbol, "exchange": r.exchange, "market": r.market.value,
        "dataset": "funding_rate"})
    frame.attrs["canonical_source_identity"] = "funding-a"
    report = validate_dataset(frame, r, DatasetKind.FUNDING_RATE, interval="1m")
    assert not any("GAP" in issue.code or "GRID" in issue.code for issue in report.issues)


def test_domain_rules_allow_ratio_above_one_and_reject_negative_values():
    r = request(); t = pd.date_range(r.start, periods=1, freq="1h")
    frame = pd.DataFrame({"period_start": t, "available_at": t, "open_interest": [1.],
        "long_short_ratio": [2.5], "symbol": r.symbol, "exchange": r.exchange,
        "market": r.market.value, "dataset": "metrics"})
    frame.attrs["canonical_source_identity"] = "metrics-a"
    assert not any(i.code == "INVALID_DOMAIN_VALUE" for i in validate_dataset(
        frame, r, DatasetKind.FUTURES_METRICS).issues)
    frame.loc[0, "long_short_ratio"] = -1
    assert any(i.code == "INVALID_DOMAIN_VALUE" for i in validate_dataset(
        frame, r, DatasetKind.FUTURES_METRICS).issues)


def test_archive_overlap_distinguishes_identical_and_conflicting():
    a = pd.DataFrame({"period_start": [1], "close": [2.]})
    assert classify_archive_overlap([a, a.copy()], ["period_start"])[-1].code == "IDENTICAL_ARCHIVE_OVERLAP"
    b = a.copy(); b.loc[0, "close"] = 3
    assert classify_archive_overlap([a, b], ["period_start"])[-1].severity is DataQualityStatus.ERROR
