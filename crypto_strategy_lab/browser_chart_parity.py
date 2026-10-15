"""Strict offline desktop/browser visualizer JSON parity comparison.

Usage: python -m crypto_strategy_lab.browser_chart_parity LEFT.json RIGHT.json
Neither the engine nor saved run data are opened or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _mismatches(left: Any, right: Any, path: str = "$"):
    if type(left) is not type(right):
        yield f"{path}: type {type(left).__name__} != {type(right).__name__}"
    elif isinstance(left, dict):
        for key in sorted(left.keys() | right.keys()):
            loc = path + "[" + json.dumps(key) + "]"
            if key not in left:
                yield f"{loc}: missing from desktop"
            elif key not in right:
                yield f"{loc}: missing from browser"
            else:
                yield from _mismatches(left[key], right[key], loc)
    elif isinstance(left, list):
        if len(left) != len(right):
            yield f"{path}: list length {len(left)} != {len(right)}"
        for index, (a, b) in enumerate(zip(left, right)):
            yield from _mismatches(a, b, f"{path}[{index}]")
    elif (isinstance(left, float) and left == 0.0 and right == 0.0
          and (str(left).startswith("-") != str(right).startswith("-"))):
        yield f"{path}: signed zero {left!r} != {right!r}"
    elif left != right:
        yield f"{path}: {left!r} != {right!r}"


def compare_payloads(desktop: Any, browser: Any) -> list[str]:
    """Report every exact structural/value mismatch, without exclusions."""
    return list(_mismatches(desktop, browser))


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path)
    parser.add_argument("browser", type=Path)
    parser.add_argument("--max-errors", type=int, default=20)
    args = parser.parse_args(argv)
    if args.max_errors < 1:
        parser.error("--max-errors must be positive")
    left = json.loads(args.desktop.read_text(encoding="utf-8"),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    right = json.loads(args.browser.read_text(encoding="utf-8"),
                       parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    differences = compare_payloads(left, right)
    print(f"Desktop canonical SHA256: {canonical_sha256(left)}")
    print(f"Browser canonical SHA256: {canonical_sha256(right)}")
    print(f"Exact chart payload parity: {'PASS' if not differences else 'FAIL'}")
    for item in differences[:args.max_errors]:
        print(item)
    if len(differences) > args.max_errors:
        print(f"... {len(differences) - args.max_errors} additional differences")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
