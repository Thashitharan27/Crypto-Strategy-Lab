"""Explicit operator-only launcher for isolated B2/B3/B4 browser certification.

Normal browser_launcher remains read-only. This CLI does not configure normal
browser mutations, persist authorization or use original saved output roots.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from crypto_strategy_lab.browser_certification import (
    serve_isolated_browser_certification,
)
from crypto_strategy_lab.browser_readonly_service import build_browser_readonly_service
from crypto_strategy_lab.paths import resolve_data_lake_runtime_paths


def _check_persistent_root_separation(root: Path, protected: list[Path]) -> None:
    """Reject a crash-test execution root intersecting known read/write sources."""
    candidate = Path(root).resolve(strict=False)
    for entry in protected:
        known = Path(entry).resolve(strict=False)
        if candidate == known or candidate in known.parents or known in candidate.parents:
            raise ValueError("Persistent certification root overlaps protected data")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CSL isolated browser certification only")
    parser.add_argument("--acknowledge-test-only", action="store_true",
                        help="Explicitly permit temporary guarded test endpoints")
    parser.add_argument("--static-root", type=Path, required=True,
                        help="Canonical absolute path to browser_ui/dist-certification")
    parser.add_argument("--frozen-config", type=Path, default=None,
                        help="Original native v3 config to seed read-only into test session")
    parser.add_argument("--evidence-root", type=Path, default=None,
                        help="Optional new absolute csl-browser-evidence-* directory for retaining only test outputs")
    parser.add_argument("--persistent-execution-root", type=Path, default=None,
                        help="Only for crash certification: pre-created marked csl-browser-crash-* root; reused across process restarts")
    parser.add_argument("--port", type=int, required=True,
                        help="Local-only test port (1-65535)")
    args = parser.parse_args(argv)
    # Refuse before even constructing the native application or inspecting the
    # operator Data Lake if a deliberate test-only acknowledgement is absent.
    if args.acknowledge_test_only is not True:
        parser.error("--acknowledge-test-only is mandatory for certification")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.persistent_execution_root is not None and args.evidence_root is not None:
        parser.error("--persistent-execution-root cannot be combined with --evidence-root")
    if not args.static_root.is_absolute() or args.static_root.name != "dist-certification":
        parser.error("--static-root must be an absolute dist-certification directory")
    # A native run can update caches and refresh the catalog; never point
    # test-only execution at the workstation's canonical writable cache.
    # The raw market-data root remains the established source of truth.
    paths = resolve_data_lake_runtime_paths()
    if args.persistent_execution_root is not None:
        # The marker alone cannot make an original input/cache directory safe
        # to write. Deny any overlap before constructing the native service.
        protected = [paths.raw_root, paths.cache_root, args.static_root]
        if args.frozen_config is not None:
            protected.append(args.frozen_config.parent)
        try:
            _check_persistent_root_separation(args.persistent_execution_root, protected)
        except ValueError as exc:
            parser.error(str(exc))
    with TemporaryDirectory(prefix="csl-browser-cert-cache-") as scratch:
        cache_root = Path(scratch).resolve() / "cache"
        cache_root.mkdir()
        native = build_browser_readonly_service(
            raw_root=paths.raw_root, cache_root=cache_root,
        ).application_service
        extra = {"evidence_root": args.evidence_root} if args.evidence_root is not None else {}
        if args.frozen_config is not None:
            extra["frozen_config_path"] = args.frozen_config
        if args.persistent_execution_root is not None:
            extra["persistent_execution_root"] = args.persistent_execution_root
        serve_isolated_browser_certification(
            native_application=native,
            static_root=args.static_root,
            port=args.port,
            acknowledge_test_only=True,
            **extra,
        )


if __name__ == "__main__":
    main()
