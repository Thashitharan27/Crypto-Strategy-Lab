"""Offline CLI checks; synthetic rows are not historical certification."""
import csv
import json

from crypto_strategy_lab.trade_parity import TRADE_FIELDS, NUMERIC_FIELDS
from tools.compare_frozen_trade_csv import compare_reports, main


def _fixture(tmp_path):
    mapping = {field: field for field in TRADE_FIELDS}
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    row = {field: ("1" if field in NUMERIC_FIELDS else f"X-{field}") for field in TRADE_FIELDS}
    first = tmp_path / "original.csv"
    second = tmp_path / "replay.csv"
    for path in (first, second):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=TRADE_FIELDS)
            writer.writeheader()
            writer.writerow(row)
    return first, second, mapping_path, row


def test_comparison_cli_reports_frozen_hashes_and_pass(tmp_path, capsys):
    first, second, mapping, row = _fixture(tmp_path)
    assert main([str(first), str(second), "--mapping", str(mapping)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["difference_count"] == 0
    assert report["expected_sha256"] == report["actual_sha256"]
    assert len(report["mapping_sha256"]) == 64


def test_comparison_cli_fails_on_modified_fee(tmp_path, capsys):
    first, second, mapping, row = _fixture(tmp_path)
    row["fees"] = "2"
    with second.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    assert main([str(first), str(second), "--mapping", str(mapping)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "MISMATCH"
    assert report["differences"][0]["field"] == "fees"
    assert report["expected_sha256"] != report["actual_sha256"]


def test_zero_tolerance_detects_decimal_precision_loss(tmp_path):
    first, second, mapping, row = _fixture(tmp_path)
    row["entry_price"] = "1.0000000000000001"
    with second.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    report = compare_reports(first, second, mapping)
    assert report["status"] == "MISMATCH"
    assert any(d["field"] == "entry_price" for d in report["differences"])


def test_cli_runs_directly_from_tools_path(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    first, second, mapping, row = _fixture(tmp_path)
    cli = Path(__file__).resolve().parents[1] / "tools" / "compare_frozen_trade_csv.py"
    completed = subprocess.run(
        [sys.executable, str(cli), str(first), str(second), "--mapping", str(mapping)],
        cwd=tmp_path, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "PASS"
