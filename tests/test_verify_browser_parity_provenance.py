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
        }
        rows.append({
            "exchange": "binance", "market": "futures_um", "dataset": "klines",
            "symbol": "BTCUSDT", "interval": interval, "frequency": "monthly",
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2020-07-01T00:00:00+00:00",
            "raw_archive_fingerprint": fingerprint,
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


def test_cli_reads_real_parquet_with_existing_duckdb_dependency(tmp_path):
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
