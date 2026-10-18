"""Explicit operator-only launcher for isolated B2/B3/B4 browser certification.

Normal browser_launcher remains read-only. This CLI does not configure normal
browser mutations, persist authorization or use original saved output roots.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from crypto_strategy_lab.browser_certification import (
    serve_isolated_browser_certification,
)
from crypto_strategy_lab.browser_readonly_service import build_browser_readonly_service


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CSL isolated browser certification only")
    parser.add_argument("--acknowledge-test-only", action="store_true",
                        help="Explicitly permit temporary guarded test endpoints")
    parser.add_argument("--static-root", type=Path, required=True,
                        help="Canonical absolute path to browser_ui/dist-certification")
    parser.add_argument("--evidence-root", type=Path, default=None,
                        help="Optional new absolute csl-browser-evidence-* directory for retaining only test outputs")
    parser.add_argument("--port", type=int, required=True,
                        help="Local-only test port (1-65535)")
    args = parser.parse_args(argv)
    # Refuse before even constructing the native application or inspecting the
    # operator Data Lake if a deliberate test-only acknowledgement is absent.
    if args.acknowledge_test_only is not True:
        parser.error("--acknowledge-test-only is mandatory for certification")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not args.static_root.is_absolute() or args.static_root.name != "dist-certification":
        parser.error("--static-root must be an absolute dist-certification directory")
    native = build_browser_readonly_service().application_service
    extra = {"evidence_root": args.evidence_root} if args.evidence_root is not None else {}
    serve_isolated_browser_certification(
        native_application=native,
        static_root=args.static_root,
        port=args.port,
        acknowledge_test_only=True,
        **extra,
    )


if __name__ == "__main__":
    main()
