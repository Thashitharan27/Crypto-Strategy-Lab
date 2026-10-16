"""Read-only frozen trade CSV comparison; no strategy execution or artifact writes."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crypto_strategy_lab.run_manifest import file_sha256
from crypto_strategy_lab.trade_parity_artifacts import read_mapped_trade_csv
from crypto_strategy_lab.trade_parity import TRADE_FIELDS, NUMERIC_FIELDS, ParityDifference, compare_trades


def compare_reports(expected: Path, actual: Path, mapping_path: Path, *, actual_mapping_path: Path | None = None, abs_tol: float = 0, rel_tol: float = 0) -> dict:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or set(mapping) != set(TRADE_FIELDS):
        raise ValueError("mapping must contain exactly all normalized trade fields")
    actual_mapping_path = actual_mapping_path or mapping_path
    actual_mapping = json.loads(actual_mapping_path.read_text(encoding="utf-8"))
    if not isinstance(actual_mapping, dict) or set(actual_mapping) != set(TRADE_FIELDS):
        raise ValueError("actual mapping must contain exactly all normalized trade fields")
    differences = compare_trades(
        read_mapped_trade_csv(expected, mapping),
        read_mapped_trade_csv(actual, actual_mapping),
        abs_tol=abs_tol, rel_tol=rel_tol,
    )
    if abs_tol == 0 and rel_tol == 0:
        # Floats can erase differences between distinct decimal CSV prices.
        # Recheck source numeric values using exact decimal arithmetic.
        def raw_rows(path: Path):
            with path.open(newline="", encoding="utf-8-sig") as stream:
                return list(csv.DictReader(stream))

        seen = {(d.trade_index, d.field) for d in differences}
        for index, (left, right) in enumerate(zip(raw_rows(expected), raw_rows(actual))):
            for field in NUMERIC_FIELDS:
                if (index, field) in seen:
                    continue
                left_value, right_value = left[mapping[field]], right[actual_mapping[field]]
                if Decimal(left_value) != Decimal(right_value):
                    differences.append(ParityDifference(index, field, left_value, right_value))
    return {
        "status": "PASS" if not differences else "MISMATCH",
        "scope": "MAPPED_15_FIELD_TRADE_ROWS_ONLY",
        "historical_execution_certified": False,
        "expected_sha256": file_sha256(expected),
        "actual_sha256": file_sha256(actual),
        "mapping_sha256": file_sha256(mapping_path),
        "actual_mapping_sha256": file_sha256(actual_mapping_path),
        "difference_count": len(differences),
        "differences": [
            {"trade_index": d.trade_index, "field": d.field, "expected": d.expected, "actual": d.actual}
            for d in differences
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--actual-mapping", type=Path, default=None)
    parser.add_argument("--abs-tol", type=float, default=0)
    parser.add_argument("--rel-tol", type=float, default=0)
    args = parser.parse_args(argv)
    result = compare_reports(args.expected, args.actual, args.mapping, actual_mapping_path=args.actual_mapping, abs_tol=args.abs_tol, rel_tol=args.rel_tol)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
