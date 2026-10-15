import copy

import pandas as pd
import pytest

from tools.verify_browser_parity_provenance import verify_source_provenance


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
        "files": {label: {"sha256": "c" * 64, "bytes": 12} for label in fields},
        "selection": {
            "symbol": "BTCUSDT", "strategy_interval": "4h", "intrabar_interval": "1m",
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
