"""Offline operator CLI for the existing parity fixture hash contract.

No archive discovery, engine execution, downloads, or config mutation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_strategy_lab.parity_fixture_manifest import (
    frozen_fixture_manifest,
    verify_frozen_fixture_files,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-json", required=True, type=Path,
                        help="JSON object mapping stable labels to original local file paths")
    parser.add_argument("--manifest-json", required=True, type=Path,
                        help="Frozen manifest input/output path")
    parser.add_argument("--verify", action="store_true",
                        help="Validate files against an existing frozen manifest without writing")
    parser.add_argument("--commit-sha", help="Pinned historical run revision (freeze mode)")
    parser.add_argument("--strategy-minutes", type=int, default=240)
    parser.add_argument("--intrabar-minutes", type=int, default=1)
    args = parser.parse_args(argv)

    files = json.loads(args.files_json.read_text(encoding="utf-8"))
    if not isinstance(files, dict) or not files or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not v
        for k, v in files.items()
    ):
        parser.error("--files-json must be a nonempty label-to-path object")
    if args.verify:
        if args.commit_sha:
            parser.error("--commit-sha is only valid when freezing")
        frozen = json.loads(args.manifest_json.read_text(encoding="utf-8"))
        verify_frozen_fixture_files(frozen["files"], files)
        print(f"Verified {len(files)} content-hashed source files")
    else:
        if not args.commit_sha:
            parser.error("--commit-sha is required when freezing")
        if args.manifest_json.exists():
            parser.error("refusing to overwrite an existing frozen manifest")
        frozen = frozen_fixture_manifest(
            commit_sha=args.commit_sha,
            files=files,
            strategy_timeframe_minutes=args.strategy_minutes,
            intrabar_timeframe_minutes=args.intrabar_minutes,
        )
        # Freeze only after a successful full verification of the computed contents.
        verify_frozen_fixture_files(frozen["files"], files)
        args.manifest_json.write_text(
            json.dumps(frozen, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Frozen {len(files)} source files to {args.manifest_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
