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
