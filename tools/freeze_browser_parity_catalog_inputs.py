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
from crypto_strategy_lab.data.timing import interval_to_timedelta
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


def _catalog_files(store: MarketDataStore, request: DataRequest, interval: str | None, dataset: DatasetKind = DatasetKind.KLINES, *, require_continuous_coverage: bool = True):
    records = store.catalog.records_for(
        store.raw_root,
        request,
        dataset,
        interval,
    )
    if not records:
        raise ValueError(f"no existing catalog records for {request.symbol} {interval}")
    # Archive-level period metadata must cover the complete requested range.
    # Overlap is allowed (the canonical loader handles overlapping partitions),
    # but a gap or unknown bound cannot establish an offline parity fixture.
    cursor = request.start
    for record in sorted(records, key=lambda r: (r.period_start or request.end, str(r.path))):
        if record.period_start is None or record.period_end is None:
            raise ValueError(f"unknown catalog period for {request.symbol} {interval}")
        if record.period_end <= record.period_start:
            raise ValueError(f"invalid catalog period for {request.symbol} {interval}")
        if require_continuous_coverage and record.period_start > cursor:
            raise ValueError(f"catalog coverage gap for {request.symbol} {interval} at {cursor.isoformat()}")
        if record.period_end > cursor:
            cursor = record.period_end
    if require_continuous_coverage and cursor < request.end:
        raise ValueError(f"catalog coverage gap for {request.symbol} {interval} at {cursor.isoformat()}")
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
        label = f"{request.symbol}_{interval}_{index:04d}_{record.frequency}" if dataset == DatasetKind.KLINES else f"{request.symbol}_{dataset.value}_{interval or 'none'}_{index:04d}_{record.frequency}"
        files[label] = path
        metadata[label] = {
            "catalog_fingerprint": record.fingerprint,
            "size_bytes": int(record.size_bytes),
            "mtime_ns": int(record.mtime_ns),
            "period_start": record.period_start.isoformat() if record.period_start else None,
            "period_end": record.period_end.isoformat() if record.period_end else None,
            "frequency": record.frequency,
            "dataset": dataset.value,
            "interval": interval,
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
    parser.add_argument("--strategy-source-start", help="Optional earlier 4h warmup source start (UTC); defaults to requested start")
    parser.add_argument("--strategy-interval", default="4h")
    parser.add_argument("--intrabar-interval", default="1m")
    parser.add_argument("--include-all-saved-datasets", action="store_true", help="Also freeze every dataset/interval in the original 2,956-source inventory")
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
    strategy_source_start = _utc(args.strategy_source_start) if args.strategy_source_start else request.start
    if strategy_source_start > request.start:
        raise ValueError('strategy source start must not be later than requested start')
    strategy_request = DataRequest(
        symbol=request.symbol, start=strategy_source_start, end=request.end,
        strategy_interval=request.strategy_interval, intrabar_interval=request.intrabar_interval,
        exchange=request.exchange, market=request.market,
    )
    store = MarketDataStore(args.raw_root, args.cache_root)

    strategy_files, strategy_meta = _catalog_files(
        store, strategy_request, request.strategy_interval
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

    extra_files: dict[str, Path] = {}
    extra_meta: dict[str, dict[str, object]] = {}
    if args.include_all_saved_datasets:
        groups = ((DatasetKind.KLINES, "1h"), (DatasetKind.KLINES, "5m"),
                  (DatasetKind.INDEX_PRICE_KLINES, "4h"),
                  (DatasetKind.MARK_PRICE_KLINES, "4h"),
                  (DatasetKind.PREMIUM_INDEX_KLINES, "4h"),
                  (DatasetKind.FUNDING_RATE, None), (DatasetKind.FUTURES_METRICS, None))
        for dataset, interval in groups:
            matched_files, matched_meta = _catalog_files(
                store, request, interval, dataset,
                require_continuous_coverage=(dataset != DatasetKind.FUTURES_METRICS),
            )
            extra_files.update(matched_files)
            extra_meta.update(matched_meta)
        if len(extra_files) != 2757:
            raise ValueError(f"additional saved source count mismatch: expected 2757, found {len(extra_files)}")
    files = {**strategy_files, **intrabar_files, **extra_files}
    strategy_minutes = int(
        interval_to_timedelta(request.strategy_interval).total_seconds() // 60
    )
    intrabar_minutes = int(
        interval_to_timedelta(request.intrabar_interval).total_seconds() // 60
    )
    frozen = frozen_fixture_manifest(
        commit_sha=args.commit_sha,
        files=files,
        strategy_timeframe_minutes=strategy_minutes,
        intrabar_timeframe_minutes=intrabar_minutes,
    )
    verify_frozen_fixture_files(frozen["files"], files)
    frozen["selection"] = {
        "symbol": request.symbol,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "strategy_interval": request.strategy_interval,
        "strategy_source_start": strategy_source_start.isoformat(),
        "intrabar_interval": request.intrabar_interval,
        "strategy_record_count": len(strategy_files),
        "intrabar_record_count": len(intrabar_files),
        "catalog_records": {**strategy_meta, **intrabar_meta, **extra_meta},
        "additional_record_count": len(extra_files),
        "source_scope": "all_saved_datasets" if args.include_all_saved_datasets else "execution_klines_only",
    }
    with args.manifest_json.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(frozen, sort_keys=True, indent=2) + "\n")
    if args.include_all_saved_datasets:
        print(f"Frozen {len(files)} total catalog sources (including {len(extra_files)} context sources)")
        print("SOURCE INVENTORY ONLY: historical feature and 79-trade execution parity remain unverified.")
    else:
        print(
            f"PARTIAL SOURCE SCOPE ONLY: frozen {len(strategy_files)} {request.strategy_interval} "
            f"and {len(intrabar_files)} {request.intrabar_interval} catalog sources"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
