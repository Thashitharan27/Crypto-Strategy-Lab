"""Read-only CSV adapter for migration parity comparisons.

Native run CSV schemas differ; an explicit field mapping avoids silently
guessing execution timestamps, fees, stop levels or PnL semantics.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping

from .trade_parity import TRADE_FIELDS, NUMERIC_FIELDS, ParityDifference, compare_trades


def read_mapped_trade_csv(
    path: str | Path,
    mapping: Mapping[str, str],
) -> list[dict[str, object]]:
    """Load existing trade_list.csv rows into the strict parity field contract.

    A field mapping is required for every normalized field. Do not synthesize
    missing data, including signal timestamps and exit reason codes.
    """
    missing_mapping = set(TRADE_FIELDS) - set(mapping)
    extra_mapping = set(mapping) - set(TRADE_FIELDS)
    if missing_mapping or extra_mapping:
        raise ValueError(f"invalid mapping: missing={sorted(missing_mapping)} extra={sorted(extra_mapping)}")
    source_names = [mapping[key] for key in TRADE_FIELDS]
    if any(not isinstance(name, str) or not name for name in source_names):
        raise ValueError("all source column names must be nonempty strings")
    if len(set(source_names)) != len(source_names):
        raise ValueError("multiple parity fields cannot share one source column")

    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing_columns = set(source_names) - columns
        if missing_columns:
            raise ValueError(f"missing trade columns: {sorted(missing_columns)}")
        rows = []
        for line_number, source in enumerate(reader, start=2):
            if None in source:
                raise ValueError(f"extra unlabelled columns on CSV line {line_number}")
            row: dict[str, object] = {}
            for field in TRADE_FIELDS:
                value = source[mapping[field]]
                if value is None or value == "":
                    raise ValueError(f"empty {field} on CSV line {line_number}")
                if field in NUMERIC_FIELDS:
                    try:
                        row[field] = float(value)
                    except ValueError as exc:
                        raise ValueError(f"invalid numeric {field} on CSV line {line_number}") from exc
                else:
                    row[field] = value
            rows.append(row)
    return rows


def compare_mapped_trade_csv(
    expected_path: str | Path,
    actual_path: str | Path,
    mapping: Mapping[str, str],
    *,
    abs_tol: float = 1e-10,
    rel_tol: float = 1e-10,
) -> list[ParityDifference]:
    """Compare two CSV artifacts without modifying either file."""
    return compare_trades(
        read_mapped_trade_csv(expected_path, mapping),
        read_mapped_trade_csv(actual_path, mapping),
        abs_tol=abs_tol, rel_tol=rel_tol,
    )
