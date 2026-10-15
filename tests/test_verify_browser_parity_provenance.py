import copy
import json

import duckdb

import pandas as pd
import pytest

from tools.verify_browser_parity_provenance import verify_source_provenance, main


def _inputs():
    fields = {}
    rows = []
    for interval in ("4h", "1m"):
        fingerprint = ("a" if interval == "4h" else "b") * 64
        label = f"BTCUSDT_{interval}_0001_monthly"
        fields[label] = {
            "frequency": "monthly",
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2020-07-01T00:00:00+00:00",
            "catalog_fingerprint": fingerprint,
            "size_bytes": 12,
            "mtime_ns": 1234567890,
        }
        rows.append({
            "exchange": "binance", "market": "futures_um", "dataset": "klines",
            "symbol": "BTCUSDT", "interval": interval, "frequency": "monthly",
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2020-07-01T00:00:00+00:00",
            "raw_archive_fingerprint": fingerprint,
            "size_bytes": 12,
            "mtime_ns": 1234567890,
        })
    frozen = {
        "commit_sha": "1ad8a2161877260d9f1d790f583a82e065f8730e",
        "strategy_timeframe_minutes": 240,
        "intrabar_timeframe_minutes": 1,
        "files": {label: {"sha256": "c" * 64, "bytes": 12} for label in fields},
        "selection": {
            "symbol": "BTCUSDT", "strategy_interval": "4h", "intrabar_interval": "1m",
            "start": "2020-06-01T00:00:00+00:00", "end": "2026-09-01T00:00:00+00:00",
            "strategy_source_start": "2020-01-01T00:00:00+00:00",
            "strategy_record_count": 1, "intrabar_record_count": 1,
            "catalog_records": fields,
        },
    }
    return frozen, pd.DataFrame(rows)


def test_source_provenance_matches_original_catalog_metadata():
    freeze, saved = _inputs()
    assert verify_source_provenance(freeze, saved) == {"4h": 1, "1m": 1}


@pytest.mark.parametrize("field,value", [
    ("raw_archive_fingerprint", "d" * 64),
    ("period_end", "2020-07-02T00:00:00+00:00"),
    ("frequency", "daily"),
])
def test_source_provenance_rejects_identity_mismatch(field, value):
    freeze, saved = _inputs()
    saved.loc[0, field] = value
    with pytest.raises(ValueError, match="provenance mismatch"):
        verify_source_provenance(freeze, saved)


def test_source_provenance_rejects_missing_archive_or_duplicate():
    freeze, saved = _inputs()
    with pytest.raises(ValueError, match="provenance mismatch"):
        verify_source_provenance(freeze, saved.iloc[:1])
    with pytest.raises(ValueError, match="provenance mismatch"):
        verify_source_provenance(freeze, pd.concat([saved, saved.iloc[:1]], ignore_index=True))


def test_source_provenance_rejects_unhashed_catalog_entry():
    freeze, saved = _inputs()
    freeze = copy.deepcopy(freeze)
    freeze["files"].pop("BTCUSDT_1m_0001_monthly")
    with pytest.raises(ValueError, match="metadata and hashed file counts"):
        verify_source_provenance(freeze, saved)


def test_source_provenance_rejects_missing_saved_schema():
    freeze, saved = _inputs()
    with pytest.raises(ValueError, match="missing fields"):
        verify_source_provenance(freeze, saved.drop(columns=["raw_archive_fingerprint"]))


def test_cli_reads_real_parquet_with_existing_duckdb_dependency(tmp_path, capsys):
    frozen, saved = _inputs()
    manifest_path = tmp_path / "freeze.json"
    source_path = tmp_path / "source_archives.parquet"
    manifest_path.write_text(json.dumps(frozen), encoding="utf-8")
    with duckdb.connect(":memory:") as connection:
        connection.register("saved_source_rows", saved)
        quoted_path = str(source_path).replace(chr(39), chr(39) * 2)
        connection.execute(f"COPY saved_source_rows TO '{quoted_path}' (FORMAT PARQUET)")
    assert main([
        "--freeze-json", str(manifest_path),
        "--saved-provenance-parquet", str(source_path),
    ]) == 0
    output = capsys.readouterr().out
    assert "PARTIAL SOURCE SCOPE ONLY" in output
    assert "full 2,956-archive" in output
    assert "79-trade execution parity remain unverified" in output


@pytest.mark.parametrize("key,value,error", [
    ("commit_sha", "a" * 40, "commit"),
    ("strategy_timeframe_minutes", 60, "timeframes"),
    ("intrabar_timeframe_minutes", 15, "timeframes"),
])
def test_provenance_rejects_wrong_baseline_identity(key, value, error):
    frozen, saved = _inputs()
    frozen[key] = value
    with pytest.raises(ValueError, match=error):
        verify_source_provenance(frozen, saved)


@pytest.mark.parametrize("field,value,error", [
    ("start", "2020-06-02T00:00:00Z", "trading window"),
    ("end", "2026-08-31T00:00:00Z", "trading window"),
    ("strategy_source_start", "2020-06-01T00:00:00Z", "warmup"),
])
def test_provenance_rejects_wrong_baseline_window(field, value, error):
    frozen, saved = _inputs()
    frozen["selection"][field] = value
    with pytest.raises(ValueError, match=error):
        verify_source_provenance(frozen, saved)


@pytest.mark.parametrize("invalid", ["NaT", None, "", "2020-01-01T00:00:00"])
def test_provenance_rejects_invalid_or_naive_warmup(invalid):
    frozen, saved = _inputs()
    frozen["selection"]["strategy_source_start"] = invalid
    with pytest.raises(ValueError, match="warmup start"):
        verify_source_provenance(frozen, saved)


@pytest.mark.parametrize("field,value", [("size_bytes", 13), ("mtime_ns", 999)])
def test_provenance_rejects_saved_source_stat_drift(field, value):
    frozen, saved = _inputs()
    saved.loc[0, field] = value
    with pytest.raises(ValueError, match="stat metadata mismatch"):
        verify_source_provenance(frozen, saved)


def test_provenance_rejects_frozen_stat_inconsistent_with_hashed_bytes():
    frozen, saved = _inputs()
    frozen["selection"]["catalog_records"]["BTCUSDT_4h_0001_monthly"]["size_bytes"] = 17
    with pytest.raises(ValueError, match="size disagrees"):
        verify_source_provenance(frozen, saved)


def test_full_scope_provenance_checks_2956_records_and_null_intervals():
    frozen, saved = _inputs()
    frozen["selection"]["source_scope"] = "all_saved_datasets"
    original_metadata = frozen["selection"]["catalog_records"]
    for record in original_metadata.values():
        record["dataset"] = "klines"
        record["interval"] = "4h" if record["catalog_fingerprint"].startswith("a") else "1m"
    additional = []
    for index in range(2954):
        label = f"BTCUSDT_metrics_none_{index:04d}_daily"
        fingerprint = f"{index:064x}"
        original_metadata[label] = {
            "dataset": "metrics", "interval": None, "frequency": "daily",
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2020-06-02T00:00:00+00:00",
            "catalog_fingerprint": fingerprint, "size_bytes": 12, "mtime_ns": 1234567890,
        }
        frozen["files"][label] = {"sha256": "c" * 64, "bytes": 12}
        additional.append({
            "exchange": "binance", "market": "futures_um", "dataset": "metrics",
            "symbol": "BTCUSDT", "interval": None, "frequency": "daily",
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2020-06-02T00:00:00+00:00",
            "raw_archive_fingerprint": fingerprint, "size_bytes": 12, "mtime_ns": 1234567890,
        })
    saved = pd.concat([saved, pd.DataFrame(additional)], ignore_index=True)
    assert verify_source_provenance(frozen, saved) == {
        "4h": 1, "1m": 1, "all_saved_sources": 2956,
    }
    saved.loc[saved["dataset"] == "metrics", "mtime_ns"] = 999
    with pytest.raises(ValueError, match="stat metadata mismatch"):
        verify_source_provenance(frozen, saved)


def test_unknown_full_scope_is_not_an_implicit_partial_verification():
    frozen, saved = _inputs()
    frozen["selection"]["source_scope"] = "unexpected"
    with pytest.raises(ValueError, match="unsupported source scope"):
        verify_source_provenance(frozen, saved)


@pytest.mark.parametrize("field,value,error", [
    ("period_start", None, "invalid or timezone-naive source period"),
    ("period_start", "NaT", "invalid or timezone-naive source period"),
    ("period_end", "2020-05-31T00:00:00+00:00", "invalid source period bounds"),
    ("period_start", "2020-06-01T00:00:00", "timezone-naive"),
])
def test_saved_archive_source_rejects_invalid_periods(field, value, error):
    frozen, saved = _inputs()
    saved[field] = saved[field].astype(object)
    saved.at[0, field] = value
    with pytest.raises(ValueError, match=error):
        verify_source_provenance(frozen, saved)
