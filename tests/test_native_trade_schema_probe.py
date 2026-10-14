import csv

import pytest

from crypto_strategy_lab.native_trade_schema_probe import (
    NATIVE_REQUIRED_COLUMNS, NATIVE_LEG_FIELDS, inspect_native_trade_columns,
)


def _header(path, fields):
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(fields)


def test_reports_missing_columns_without_inventing_values(tmp_path):
    path = tmp_path / "trade_list.csv"
    _header(path, ["trade_id", "entry_time"])
    result = inspect_native_trade_columns(path)
    assert "pair_net_pnl" in result["missing_required"]
    assert result["full_leg_coverage"] == {"long": False, "short": False}


def test_complete_synthetic_schema(tmp_path):
    path = tmp_path / "trade_list.csv"
    fields = sorted(NATIVE_REQUIRED_COLUMNS) + [
        f"{side}_{field}" for side in ("long", "short") for field in NATIVE_LEG_FIELDS
    ]
    _header(path, fields)
    result = inspect_native_trade_columns(path)
    assert result["missing_required"] == []
    assert all(result["full_leg_coverage"].values())
    assert result["columns"] == fields


def test_duplicate_headers_are_rejected(tmp_path):
    path = tmp_path / "trade_list.csv"
    _header(path, ["trade_id", "trade_id"])
    with pytest.raises(ValueError, match="duplicate"):
        inspect_native_trade_columns(path)
