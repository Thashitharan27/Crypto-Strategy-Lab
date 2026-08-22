"""Validate canonical Data Lake coverage, schema, provenance, and causality.

Example:
    python tools/data_lake_validate.py \
      --raw-root "C:\\CryptoBots\\Binance Market Data" \
      --symbol BTCUSDT --strategy-interval 15m --intrabar-interval 1m \
      --start 2025-01-01 --end 2025-02-01
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

# Direct execution (``python tools/...py``) puts ``tools`` on sys.path instead of
# the repository root. Add the root explicitly so project imports work on a clean
# Windows checkout without requiring PYTHONPATH or an editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import (
    DataQualityReport, DataRequest, DatasetKind, MarketDataStore, validate_dataset,
)


def _utc_datetime(text: str) -> datetime:
    return pd.Timestamp(text, tz="UTC").to_pydatetime()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and validate the Binance Data Lake v2 path")
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--strategy-interval", required=True)
    parser.add_argument("--intrabar-interval")
    parser.add_argument("--start", required=True, type=_utc_datetime)
    parser.add_argument("--end", required=True, type=_utc_datetime)
    return parser


def validate_canonical_klines(frame: pd.DataFrame, request: DataRequest, label: str) -> None:
    """Compatibility facade over the production validator."""
    dataset_report = validate_dataset(
        frame, request, DatasetKind.KLINES, interval=request.strategy_interval, required=True
    )
    # The legacy helper validates a supplied slice, which need not represent the
    # whole request. Full CLI and production paths use the unfiltered report.
    integrity = tuple(i for i in dataset_report.issues if "COVERAGE_GAP" not in i.code
                      and i.code != "MISSING_INTERNAL_INTERVAL")
    if any(i.severity.value == "ERROR" for i in integrity):
        raise ValueError(f"{label} failed canonical validation: {[i.code for i in integrity]}")


def print_report(report: DataQualityReport) -> None:
    print("\nDATA QUALITY")
    print(f"{'Dataset':28} {'Status':9} Details")
    for item in report.datasets:
        details = ", ".join(f"{issue.code} ({issue.count})" for issue in item.issues)
        print(f"{item.dataset + (' ' + item.interval if item.interval else ''):28} "
              f"{item.status.value:9} {details}")


def main() -> int:
    args = build_parser().parse_args()
    store = MarketDataStore(args.raw_root, args.cache_root)
    count = store.refresh_catalog()
    print(f"Cataloged archives: {count}")
    coverage = store.catalog.coverage(
        args.raw_root,
        market=DataRequest(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            strategy_interval=args.strategy_interval,
        ).market,
        dataset=DatasetKind.KLINES,
        symbol=args.symbol,
        interval=args.strategy_interval,
    )
    print(
        "Strategy kline coverage: "
        f"archives={coverage.archive_count}, first={coverage.first_period}, last={coverage.last_period}"
    )

    request = DataRequest(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        strategy_interval=args.strategy_interval,
        intrabar_interval=args.intrabar_interval,
    )
    strategy = store.load_klines(request, request.strategy_interval)
    reports = [validate_dataset(strategy, request, DatasetKind.KLINES,
                                interval=request.strategy_interval, required=True)]
    print(
        f"Strategy rows: {len(strategy)} | {strategy.period_start.min()} -> {strategy.period_start.max()}"
    )
    if request.intrabar_interval:
        intrabar_request = DataRequest(
            symbol=request.symbol,
            start=request.start,
            end=request.end,
            strategy_interval=request.intrabar_interval,
            market=request.market,
            exchange=request.exchange,
        )
        # Validation needs the full canonical contract. The narrower execution
        # projection is intentionally validated later by IntrabarExecutionData.
        intrabar = store.load_klines(intrabar_request, request.intrabar_interval)
        reports.append(validate_dataset(intrabar, intrabar_request, DatasetKind.KLINES,
                                        interval=request.intrabar_interval, required=True))
        print(
            f"Intrabar rows: {len(intrabar)} | "
            f"{intrabar.period_start.min()} -> {intrabar.period_start.max()}"
        )
    report = DataQualityReport(tuple(reports))
    print_report(report)
    report.raise_for_errors()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
