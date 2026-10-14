import csv
import hashlib

from tools.inspect_parity_trade_report import inspect_trade_report, main
from crypto_strategy_lab.native_trade_schema_probe import NATIVE_REQUIRED_COLUMNS


def test_probe_reads_frozen_native_header(tmp_path, capsys):
    p = tmp_path / "trade_list.csv"
    with p.open("w", newline="", encoding="utf-8") as out:
        csv.writer(out).writerow(sorted(NATIVE_REQUIRED_COLUMNS))
    report = inspect_trade_report(p)
    assert report["missing_required"] == []
    assert report["file_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert main([str(p)]) == 0
    assert '"file_sha256"' in capsys.readouterr().out


def test_probe_fails_closed_on_incomplete_header(tmp_path):
    p = tmp_path / "trade_list.csv"
    p.write_text("trade_id,entry_time\\n", encoding="utf-8")
    assert main([str(p)]) == 1
