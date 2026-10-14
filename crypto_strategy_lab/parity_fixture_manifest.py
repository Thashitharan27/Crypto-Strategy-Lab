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


def verify_frozen_fixture_files(
    expected_files: Mapping[str, Mapping[str, object]],
    files: Mapping[str, str | Path],
) -> None:
    """Fail closed unless supplied offline files match all frozen hashes and sizes.

    This checks fixture integrity only, not market-data completeness, execution
    reproducibility or trade-level parity.
    """
    if not expected_files or set(expected_files) != set(files):
        raise ValueError("fixture file labels do not match the frozen manifest")
    for name in sorted(expected_files):
        metadata = expected_files[name]
        if not isinstance(metadata, Mapping):
            raise ValueError(f"invalid frozen fixture metadata for {name}")
        expected_hash = metadata.get("sha256")
        expected_bytes = metadata.get("bytes")
        if (not isinstance(expected_hash, str) or len(expected_hash) != 64
            or any(c not in "0123456789abcdef" for c in expected_hash)
            or not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool)
            or expected_bytes < 0):
            raise ValueError(f"invalid frozen fixture digest for {name}")
        actual = file_fingerprint(files[name])
        if actual != {"sha256": expected_hash, "bytes": expected_bytes}:
            raise ValueError(f"frozen fixture mismatch: {name}")
