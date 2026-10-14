"""CSV artifact adapter coverage with tiny synthetic frozen reports."""
import csv

import pytest

from crypto_strategy_lab.trade_parity import TRADE_FIELDS, NUMERIC_FIELDS
from crypto_strategy_lab.trade_parity_artifacts import (
    compare_mapped_trade_csv,
    read_mapped_trade_csv,
)


def _write(path, rows, header=None):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _row():
    return {key: ("2.5" if key in NUMERIC_FIELDS else f"value-{key}") for key in TRADE_FIELDS}


def test_identical_csv_and_changed_exit(tmp_path):
    mapping = {key: f"old_{key}" for key in TRADE_FIELDS}
    source = {mapping[key]: value for key, value in _row().items()}
    first, second = tmp_path / "old.csv", tmp_path / "new.csv"
    _write(first, [source])
    _write(second, [source])
    assert compare_mapped_trade_csv(first, second, mapping) == []
    changed = dict(source)
    changed[mapping["exit_time"]] = "different-exit-time"
    _write(second, [changed])
    assert [d.field for d in compare_mapped_trade_csv(first, second, mapping)] == ["exit_time"]


def test_missing_source_column_rejected(tmp_path):
    path = tmp_path / "trades.csv"
    _write(path, [_row()])
    mapping = {key: key for key in TRADE_FIELDS}
    mapping["entry_time"] = "nonexistent"
    with pytest.raises(ValueError, match="missing trade columns"):
        read_mapped_trade_csv(path, mapping)


def test_mapping_must_be_explicit(tmp_path):
    path = tmp_path / "trades.csv"
    _write(path, [_row()])
    with pytest.raises(ValueError, match="invalid mapping"):
        read_mapped_trade_csv(path, {"entry_time": "entry_time"})


def test_empty_and_invalid_numeric_values_are_errors(tmp_path):
    path = tmp_path / "trades.csv"
    row = _row()
    row["fees"] = ""
    _write(path, [row])
    mapping = {key: key for key in TRADE_FIELDS}
    with pytest.raises(ValueError, match="empty fees"):
        read_mapped_trade_csv(path, mapping)
    row["fees"] = "not-a-number"
    _write(path, [row])
    with pytest.raises(ValueError, match="invalid numeric fees"):
        read_mapped_trade_csv(path, mapping)


def test_empty_report_with_header_is_supported(tmp_path):
    path = tmp_path / "trades.csv"
    path.write_text(",".join(TRADE_FIELDS) + "\n", encoding="utf-8")
    assert read_mapped_trade_csv(path, {key: key for key in TRADE_FIELDS}) == []
