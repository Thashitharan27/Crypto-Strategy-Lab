"""Guard the recorded historical BTCUSDT parity baseline against silent drift.

This test reads committed evidence only; it never opens local market data,
replays trades, or claims the browser's execution path is certified.
"""
import json
from pathlib import Path


CERTIFICATE = (
    Path(__file__).resolve().parents[1]
    / "docs/certification/browser_historical_replay_2026-10-15.json"
)


def test_frozen_historical_trade_parity_certificate_contract():
    certificate = json.loads(CERTIFICATE.read_text(encoding="utf-8"))
    assert certificate["certification_version"] == 1
    assert certificate["status"] == "PASS"
    assert certificate["browser_execution_authorized"] is False
    assert certificate["pr_501_hold"] is True

    original = certificate["original"]
    assert original["run_id"] == "BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f"
    assert original["trade_csv_sha256"] == "14d0577968a9ee50916aa9b4d2431cec238812f5bc290f9b315531ff541eacbe"
    assert original["trade_parquet_sha256"] == "736c1673a468501ae42b25e4afdf036dfa8eb8b9c2449406341d3511258202f2"

    comparisons = certificate["comparisons"]
    prepared = comparisons["prepared_frame"]
    assert (prepared["rows_original"], prepared["rows_replay"]) == (14610, 14610)
    assert (prepared["columns_original"], prepared["columns_replay"]) == (464, 464)
    assert prepared["result"] == "EXACT PREPARED-FRAME MATCH"
    assert prepared["content_hash"] is None

    native = comparisons["native_trades"]
    assert (native["rows_original"], native["rows_replay"]) == (79, 79)
    assert (native["columns_original"], native["columns_replay"]) == (877, 877)
    assert native["result"] == "EXACT NATIVE-TRADE MATCH"
    assert native["trade_fingerprint_original"] == native["trade_fingerprint_replay"]
    assert native["trade_fingerprint_original"] == "b02ff222d0337b3ddf950fd23372a92d81320704ea032805a121c47b71ddf94c"

    assert comparisons["config_hash_classification"] == {
        "strategy": "MATCH", "data": "MATCH",
        "execution": "MATCH", "feature": "EXPECTED_DIFFERENCE_ONLY",
        "feature_difference": 'current config adds fib_structure_quality_mode="BASELINE" default',
    }
