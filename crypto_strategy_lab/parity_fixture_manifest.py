"""Immutable provenance manifest for existing offline regression inputs.

Read-only hashing only: does not execute strategies, access live systems,
download candles, or alter historical run output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .run_manifest import file_sha256


def file_fingerprint(path: str | Path) -> dict[str, object]:
    """Fingerprint exact file bytes; fail closed for missing/non-files."""
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"fixture input is not a file: {source}")
    return {"sha256": file_sha256(source), "bytes": source.stat().st_size}


def frozen_fixture_manifest(
    *,
    commit_sha: str,
    files: Mapping[str, str | Path],
    strategy_timeframe_minutes: int,
    intrabar_timeframe_minutes: int | None,
) -> dict[str, object]:
    """Create portable content fingerprints; never embed machine-local paths.

    Callers must supply explicit market-data files, config snapshots and actual
    run artifacts with distinct logical names. This method does not certify
    causality, completeness of 1m data or backtest parity.
    """
    if len(commit_sha) != 40 or any(c not in "0123456789abcdef" for c in commit_sha):
        raise ValueError("commit_sha must be a 40-character lowercase Git commit hash")
    if not isinstance(strategy_timeframe_minutes, int) or isinstance(strategy_timeframe_minutes, bool) or strategy_timeframe_minutes <= 0:
        raise ValueError("invalid strategy timeframe")
    if intrabar_timeframe_minutes is not None and (
        not isinstance(intrabar_timeframe_minutes, int)
        or isinstance(intrabar_timeframe_minutes, bool)
        or intrabar_timeframe_minutes <= 0
        or intrabar_timeframe_minutes > strategy_timeframe_minutes
    ):
        raise ValueError("invalid intrabar timeframe")
    if not files or any(not isinstance(k, str) or not k for k in files):
        raise ValueError("provide nonempty named fixture inputs")
    return {
        "contract_version": 1,
        "commit_sha": commit_sha,
        "strategy_timeframe_minutes": strategy_timeframe_minutes,
        "intrabar_timeframe_minutes": intrabar_timeframe_minutes,
        "files": {name: file_fingerprint(files[name]) for name in sorted(files)},
    }
