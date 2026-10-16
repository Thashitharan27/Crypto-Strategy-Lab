"""Read-only frozen trade CSV comparison; no strategy execution or artifact writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_strategy_lab.run_manifest import file_sha256
from crypto_strategy_lab.trade_parity_artifacts import compare_mapped_trade_csv
from crypto_strategy_lab.trade_parity import TRADE_FIELDS


def compare_reports(expected: Path, actual: Path, mapping_path: Path, *, abs_tol: float = 0, rel_tol: float = 0) -> dict:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or set(mapping) != set(TRADE_FIELDS):
        raise ValueError("mapping must contain exactly all normalized trade fields")
    differences = compare_mapped_trade_csv(expected, actual, mapping, abs_tol=abs_tol, rel_tol=rel_tol)
    return {
        "status": "PASS" if not differences else "MISMATCH",
        "expected_sha256": file_sha256(expected),
        "actual_sha256": file_sha256(actual),
        "mapping_sha256": file_sha256(mapping_path),
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
    parser.add_argument("--abs-tol", type=float, default=0)
    parser.add_argument("--rel-tol", type=float, default=0)
    args = parser.parse_args(argv)
    result = compare_reports(args.expected, args.actual, args.mapping, abs_tol=args.abs_tol, rel_tol=args.rel_tol)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
