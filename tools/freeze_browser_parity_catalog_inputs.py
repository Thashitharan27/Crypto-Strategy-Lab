"""Freeze parity inputs selected from the existing Data Lake catalog.

This operator-only utility never refreshes archive discovery, downloads data, or
runs the backtest engine. It trusts only catalog-selected source records, verifies
that each current file still matches the catalog's stored stat fingerprint, then
uses the existing parity fixture content-hash contract.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from crypto_strategy_lab.data import DataRequest, DatasetKind, MarketDataStore
from crypto_strategy_lab.data.cache import stat_fingerprint
from crypto_strategy_lab.parity_fixture_manifest import (
    frozen_fixture_manifest,
    verify_frozen_fixture_files,
)


def _utc(text: str) -> datetime:
    value = str(text).strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _catalog_files(store: MarketDataStore, request: DataRequest, interval: str):
    records = store.catalog.records_for(
        store.raw_root,
        request,
        DatasetKind.KLINES,
        interval,
    )
    if not records:
        raise ValueError(f"no existing catalog records for {request.symbol} {interval}")
    files: dict[str, Path] = {}
    metadata: dict[str, dict[str, object]] = {}
    for index, record in enumerate(records, start=1):
        path = Path(record.path)
        if not path.is_file():
            raise ValueError(f"catalog source is missing: {path}")
        stat = path.stat()
        if stat.st_size != int(record.size_bytes) or stat.st_mtime_ns != int(record.mtime_ns):
            raise ValueError(f"catalog source metadata changed: {path}")
        if stat_fingerprint(path, stat) != record.fingerprint:
            raise ValueError(f"catalog source fingerprint changed: {path}")
        label = f"BTCUSDT_{interval}_{index:04d}_{record.frequency}"
        files[label] = path
        metadata[label] = {
            "catalog_fingerprint": record.fingerprint,
            "period_start": record.period_start.isoformat() if record.period_start else None,
            "period_end": record.period_end.isoformat() if record.period_end else None,
            "frequency": record.frequency,
        }
    return files, metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--manifest-json", required=True, type=Path)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020-06-01T00:00:00Z")
    parser.add_argument("--end", default="2026-09-01T00:00:00Z")
    parser.add_argument("--strategy-interval", default="4h")
    parser.add_argument("--intrabar-interval", default="1m")
    parser.add_argument("--expected-strategy-records", type=int)
    parser.add_argument("--expected-intrabar-records", type=int)
    args = parser.parse_args(argv)

    if args.manifest_json.exists():
        parser.error("refusing to overwrite an existing frozen manifest")

    request = DataRequest(
        symbol=args.symbol,
        start=_utc(args.start),
        end=_utc(args.end),
        strategy_interval=args.strategy_interval,
        intrabar_interval=args.intrabar_interval,
    )
    store = MarketDataStore(args.raw_root, args.cache_root)

    strategy_files, strategy_meta = _catalog_files(
        store, request, request.strategy_interval
    )
    intrabar_files, intrabar_meta = _catalog_files(
        store, request, request.intrabar_interval
    )
    if (
        args.expected_strategy_records is not None
        and len(strategy_files) != args.expected_strategy_records
    ):
        raise ValueError(
            f"strategy catalog count mismatch: expected {args.expected_strategy_records}, "
            f"found {len(strategy_files)}"
        )
    if (
        args.expected_intrabar_records is not None
        and len(intrabar_files) != args.expected_intrabar_records
    ):
        raise ValueError(
            f"intrabar catalog count mismatch: expected {args.expected_intrabar_records}, "
            f"found {len(intrabar_files)}"
        )

    files = {**strategy_files, **intrabar_files}
    frozen = frozen_fixture_manifest(
        commit_sha=args.commit_sha,
        files=files,
        strategy_timeframe_minutes=240,
        intrabar_timeframe_minutes=1,
    )
    verify_frozen_fixture_files(frozen["files"], files)
    frozen["selection"] = {
        "symbol": request.symbol,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "strategy_interval": request.strategy_interval,
        "intrabar_interval": request.intrabar_interval,
        "strategy_record_count": len(strategy_files),
        "intrabar_record_count": len(intrabar_files),
        "catalog_records": {**strategy_meta, **intrabar_meta},
    }
    with args.manifest_json.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(frozen, sort_keys=True, indent=2) + "\n")
    print(
        f"Frozen {len(strategy_files)} {request.strategy_interval} and "
        f"{len(intrabar_files)} {request.intrabar_interval} catalog sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
