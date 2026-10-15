from datetime import datetime, timezone
import json

import pytest

from crypto_strategy_lab.data import DatasetKind, MarketDataStore, MarketKind
from crypto_strategy_lab.data.cache import stat_fingerprint
from crypto_strategy_lab.data.schemas import ArchiveRecord
from tools.freeze_browser_parity_catalog_inputs import main


UTC = timezone.utc


def _record(raw_root, path, interval, start, end):
    stat = path.stat()
    return ArchiveRecord(
        raw_root=raw_root,
        path=path,
        market=MarketKind.FUTURES_UM,
        dataset=DatasetKind.KLINES,
        symbol="BTCUSDT",
        interval=interval,
        frequency="monthly",
        period_start=start,
        period_end=end,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        fingerprint=stat_fingerprint(path, stat),
        exchange="binance",
    )


def test_catalog_backed_freeze_hashes_existing_sources_without_refresh(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    raw.mkdir()
    one_minute = raw / "BTCUSDT-1m-2020-06.zip"
    four_hour = raw / "BTCUSDT-4h-2020-06.zip"
    one_minute.write_bytes(b"original 1m bytes")
    four_hour.write_bytes(b"original 4h bytes")
    start = datetime(2020, 6, 1, tzinfo=UTC)
    end = datetime(2020, 7, 1, tzinfo=UTC)

    store = MarketDataStore(raw, cache)
    store.catalog.sync_root(
        raw,
        [
            _record(raw, one_minute, "1m", start, end),
            _record(raw, four_hour, "4h", start, end),
        ],
    )
    monkeypatch.setattr(
        MarketDataStore,
        "refresh_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not refresh")),
    )

    manifest = tmp_path / "freeze.json"
    assert main([
        "--raw-root", str(raw),
        "--cache-root", str(cache),
        "--manifest-json", str(manifest),
        "--commit-sha", "a" * 40,
        "--start", "2020-06-01T00:00:00Z",
        "--end", "2020-07-01T00:00:00Z",
        "--expected-strategy-records", "1",
        "--expected-intrabar-records", "1",
    ]) == 0

    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    assert frozen["selection"]["strategy_record_count"] == 1
    assert frozen["selection"]["intrabar_record_count"] == 1
    assert len(frozen["files"]) == 2
    assert frozen["strategy_timeframe_minutes"] == 240
    assert frozen["intrabar_timeframe_minutes"] == 1
    assert set(frozen["files"]) == {"BTCUSDT_4h_0001_monthly", "BTCUSDT_1m_0001_monthly"}
    assert all("sha256" in item for item in frozen["files"].values())


def test_catalog_backed_freeze_fails_when_source_changed_since_catalog(tmp_path):
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    raw.mkdir()
    source = raw / "BTCUSDT-4h-2020-06.zip"
    source.write_bytes(b"first bytes")
    start = datetime(2020, 6, 1, tzinfo=UTC)
    end = datetime(2020, 7, 1, tzinfo=UTC)
    store = MarketDataStore(raw, cache)
    store.catalog.sync_root(raw, [_record(raw, source, "4h", start, end)])
    source.write_bytes(b"changed bytes")

    with pytest.raises(ValueError, match="metadata changed|fingerprint changed"):
        main([
            "--raw-root", str(raw),
            "--cache-root", str(cache),
            "--manifest-json", str(tmp_path / "freeze.json"),
            "--commit-sha", "a" * 40,
            "--start", "2020-06-01T00:00:00Z",
            "--end", "2020-07-01T00:00:00Z",
        ])


@pytest.mark.parametrize("first_start, first_end, second_start, second_end", [
    ("2020-06-02", "2020-06-15", "2020-06-15", "2020-07-01"),
    ("2020-06-01", "2020-06-10", "2020-06-11", "2020-07-01"),
    ("2020-06-01", "2020-06-15", "2020-06-14", "2020-06-30"),
])
def test_catalog_freeze_rejects_boundary_and_internal_gaps(
    tmp_path, first_start, first_end, second_start, second_end,
):
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    records = []
    for interval in ("1m", "4h"):
        for index, (start, end) in enumerate((
            (first_start, first_end), (second_start, second_end)
        )):
            archive = raw / f"{interval}-{index}.zip"
            archive.write_bytes(f"{interval}-{index}".encode())
            records.append(_record(
                raw, archive, interval,
                datetime.fromisoformat(start).replace(tzinfo=UTC),
                datetime.fromisoformat(end).replace(tzinfo=UTC),
            ))
    MarketDataStore(raw, cache).catalog.sync_root(raw, records)
    dest = tmp_path / "freeze.json"
    with pytest.raises(ValueError, match="catalog coverage gap"):
        main([
            "--raw-root", str(raw), "--cache-root", str(cache),
            "--manifest-json", str(dest), "--commit-sha", "a" * 40,
            "--start", "2020-06-01T00:00:00Z",
            "--end", "2020-07-01T00:00:00Z",
        ])
    assert not dest.exists()


def test_catalog_freeze_allows_overlapping_source_periods(tmp_path):
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    records = []
    for interval in ("1m", "4h"):
        for index, (start, end) in enumerate((
            ("2020-06-01", "2020-06-20"), ("2020-06-15", "2020-07-01")
        )):
            archive = raw / f"{interval}-{index}.zip"
            archive.write_bytes(f"{interval}-{index}".encode())
            records.append(_record(
                raw, archive, interval,
                datetime.fromisoformat(start).replace(tzinfo=UTC),
                datetime.fromisoformat(end).replace(tzinfo=UTC),
            ))
    MarketDataStore(raw, cache).catalog.sync_root(raw, records)
    dest = tmp_path / "freeze.json"
    assert main([
        "--raw-root", str(raw), "--cache-root", str(cache),
        "--manifest-json", str(dest), "--commit-sha", "a" * 40,
        "--start", "2020-06-01T00:00:00Z",
        "--end", "2020-07-01T00:00:00Z",
    ]) == 0
    assert len(json.loads(dest.read_text())["files"]) == 4
