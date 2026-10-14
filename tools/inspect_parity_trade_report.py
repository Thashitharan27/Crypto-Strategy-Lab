"""Inspect an existing offline trade_list.csv without modifying run outputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_strategy_lab.native_trade_schema_probe import inspect_native_trade_columns
from crypto_strategy_lab.run_manifest import file_sha256


def inspect_trade_report(path: str | Path) -> dict[str, object]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"missing trade report: {source}")
    result = inspect_native_trade_columns(source)
    return {
        "file_sha256": file_sha256(source),
        "file_bytes": source.stat().st_size,
        **result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trade_csv", type=Path, help="Existing native trade_list.csv")
    args = parser.parse_args(argv)
    report = inspect_trade_report(args.trade_csv)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["missing_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
