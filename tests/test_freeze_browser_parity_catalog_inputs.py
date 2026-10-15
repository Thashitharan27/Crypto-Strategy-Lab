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


def test_catalog_backed_freeze_hashes_existing_sources_without_refresh(tmp_path, monkeypatch, capsys):
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

    assert "PARTIAL SOURCE SCOPE ONLY" in capsys.readouterr().out
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


def test_strategy_warmup_sources_are_frozen_without_extending_intrabar_window(tmp_path):
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    dates = [
        ("4h", "2020-01-01", "2020-06-01"),
        ("4h", "2020-06-01", "2020-07-01"),
        ("1m", "2020-06-01", "2020-07-01"),
    ]
    rows = []
    for index, (interval, start, end) in enumerate(dates):
        path = raw / f"archive-{index}.zip"
        path.write_bytes(str(index).encode())
        rows.append(_record(
            raw, path, interval,
            datetime.fromisoformat(start).replace(tzinfo=UTC),
            datetime.fromisoformat(end).replace(tzinfo=UTC),
        ))
    MarketDataStore(raw, cache).catalog.sync_root(raw, rows)
    freeze_path = tmp_path / "freeze.json"
    assert main([
        "--raw-root", str(raw), "--cache-root", str(cache),
        "--manifest-json", str(freeze_path), "--commit-sha", "a" * 40,
        "--start", "2020-06-01T00:00:00Z", "--end", "2020-07-01T00:00:00Z",
        "--strategy-source-start", "2020-01-01T00:00:00Z",
        "--expected-strategy-records", "2", "--expected-intrabar-records", "1",
    ]) == 0
    result = json.loads(freeze_path.read_text())
    assert result["selection"]["strategy_source_start"] == "2020-01-01T00:00:00+00:00"
    assert result["selection"]["start"] == "2020-06-01T00:00:00+00:00"
    assert result["selection"]["strategy_record_count"] == 2
    assert result["selection"]["intrabar_record_count"] == 1


def test_strategy_source_start_must_not_exclude_requested_history(tmp_path):
    with pytest.raises(ValueError, match="must not be later"):
        main([
            "--raw-root", str(tmp_path / "raw"),
            "--cache-root", str(tmp_path / "cache"),
            "--manifest-json", str(tmp_path / "freeze.json"),
            "--commit-sha", "a" * 40,
            "--start", "2020-06-01T00:00:00Z",
            "--strategy-source-start", "2020-06-02T00:00:00Z",
        ])


def test_full_scope_freeze_fails_closed_if_context_archives_missing(tmp_path):
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    start = datetime(2020, 6, 1, tzinfo=UTC)
    end = datetime(2020, 7, 1, tzinfo=UTC)
    records = []
    for interval in ("4h", "1m"):
        archive = raw / f"{interval}.zip"
        archive.write_bytes(interval.encode())
        records.append(_record(raw, archive, interval, start, end))
    MarketDataStore(raw, cache).catalog.sync_root(raw, records)
    dest = tmp_path / "full-source-freeze.json"
    with pytest.raises(ValueError, match="no existing catalog records"):
        main([
            "--raw-root", str(raw), "--cache-root", str(cache),
            "--manifest-json", str(dest), "--commit-sha", "a" * 40,
            "--start", "2020-06-01T00:00:00Z",
            "--end", "2020-07-01T00:00:00Z",
            "--include-all-saved-datasets",
        ])
    assert not dest.exists()


def test_sparse_metrics_catalog_freeze_preserves_gaps(tmp_path):
    from tools.freeze_browser_parity_catalog_inputs import _catalog_files
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    a, b = raw / "metrics-01.zip", raw / "metrics-03.zip"
    a.write_bytes(b"original day one")
    b.write_bytes(b"original day three")
    start = datetime(2020, 6, 1, tzinfo=UTC)
    day2 = datetime(2020, 6, 2, tzinfo=UTC)
    day3 = datetime(2020, 6, 3, tzinfo=UTC)
    day4 = datetime(2020, 6, 4, tzinfo=UTC)
    from dataclasses import replace
    records = [
        replace(_record(raw, a, None, start, day2),
                dataset=DatasetKind.FUTURES_METRICS, frequency="daily"),
        replace(_record(raw, b, None, day3, day4),
                dataset=DatasetKind.FUTURES_METRICS, frequency="daily"),
    ]
    store = MarketDataStore(raw, cache)
    store.catalog.sync_root(raw, records)
    from crypto_strategy_lab.data import DataRequest
    request = DataRequest(
        symbol="BTCUSDT", start=start, end=day4,
        strategy_interval="4h", intrabar_interval="1m",
    )
    with pytest.raises(ValueError, match="coverage gap"):
        _catalog_files(store, request, None, DatasetKind.FUTURES_METRICS)
    files, metadata = _catalog_files(
        store, request, None, DatasetKind.FUTURES_METRICS,
        require_continuous_coverage=False,
    )
    assert len(files) == len(metadata) == 2
    assert {record["dataset"] for record in metadata.values()} == {"metrics"}


def test_full_scope_rejects_wrong_individual_group_count_before_hashing(tmp_path, monkeypatch):
    from tools import freeze_browser_parity_catalog_inputs as freeze
    from dataclasses import replace
    raw, cache = tmp_path / "raw", tmp_path / "cache"
    raw.mkdir()
    start, end = datetime(2020, 6, 1, tzinfo=UTC), datetime(2020, 7, 1, tzinfo=UTC)
    records = []
    for interval in ("4h", "1m", "1h", "5m"):
        source = raw / f"{interval}.zip"
        source.write_bytes(interval.encode())
        records.append(_record(raw, source, interval, start, end))
    MarketDataStore(raw, cache).catalog.sync_root(raw, records)
    original = freeze._catalog_files

    def selected(store, request, interval, dataset=DatasetKind.KLINES, **kwargs):
        if dataset == DatasetKind.KLINES and interval in ("4h", "1m"):
            return original(store, request, interval, dataset, **kwargs)
        return {"synthetic": raw / "1h.zip"}, {"synthetic": {}}

    monkeypatch.setattr(freeze, "_catalog_files", selected)
    output = tmp_path / "full.json"
    with pytest.raises(ValueError, match="saved source group count mismatch: klines/1h expected 98, found 1"):
        main(["--raw-root", str(raw), "--cache-root", str(cache),
              "--manifest-json", str(output), "--commit-sha", "a" * 40,
              "--start", "2020-06-01T00:00:00Z", "--end", "2020-07-01T00:00:00Z",
              "--include-all-saved-datasets"])
    assert not output.exists()
