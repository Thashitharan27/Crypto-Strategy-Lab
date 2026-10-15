"""Read-only local parity check for existing saved native-v3 configurations.

Usage:
  python -m crypto_strategy_lab.browser_saved_config_parity PATH_TO_CONFIG.json

Prints hashes and never emits configuration values or authentication tokens.
Only the existing validated reader and serializer own config semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import load_data_lake_config


def _digest(value: dict) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def check(path: Path) -> dict:
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    native = load_data_lake_config(path)
    native.validate()
    expected = native.to_dict()
    projected = read_research_config(path)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        "file": path.name,
        "native_sha256": _digest(expected),
        "browser_reader_sha256": _digest(projected),
        "source_unchanged": before == after,
        "exact_match": expected == projected,
    }
    result["pass"] = result["source_unchanged"] and result["exact_match"]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="+", type=Path, help="Existing native v3 JSON configuration paths")
    args = parser.parse_args(argv)
    all_pass = True
    for path in args.configs:
        try:
            result = check(path.resolve(strict=True))
            print(json.dumps(result, sort_keys=True))
            all_pass = all_pass and result["pass"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(json.dumps({"file": path.name, "pass": False, "error_type": type(exc).__name__}))
            all_pass = False
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
