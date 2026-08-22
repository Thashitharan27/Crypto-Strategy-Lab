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

from crypto_strategy_lab.data import DataRequest, DatasetKind, MarketDataStore


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
    """Fail loudly when a full canonical kline frame violates the native contract."""
    required = {
        "period_start", "period_end", "available_at", "open", "high", "low",
        "close", "volume", "symbol", "exchange", "market", "dataset", "interval",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing canonical columns: {missing}")
    if frame.empty:
        raise ValueError(f"{label} has no rows in the requested interval")
    starts = pd.to_datetime(frame["period_start"], utc=True, errors="raise")
    ends = pd.to_datetime(frame["period_end"], utc=True, errors="raise")
    available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    if not starts.is_monotonic_increasing or starts.duplicated().any():
        raise ValueError(f"{label} period_start must be strictly ordered and unique")
    if (ends < starts).any() or (available < ends).any():
        raise ValueError(f"{label} violates causal period/availability ordering")
    if starts.iloc[0] < pd.Timestamp(request.start) or starts.iloc[-1] >= pd.Timestamp(request.end):
        raise ValueError(f"{label} contains rows outside the requested interval")
    expected = {
        "symbol": request.symbol,
        "exchange": request.exchange,
        "market": request.market.value,
        "dataset": DatasetKind.KLINES.value,
    }
    for column, value in expected.items():
        if set(frame[column].astype(str)) != {str(value)}:
            raise ValueError(f"{label} has unexpected canonical {column} identity")
    if not frame.attrs.get("canonical_source_identity"):
        raise ValueError(f"{label} is missing canonical source provenance")


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
    validate_canonical_klines(strategy, request, "strategy klines")
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
        validate_canonical_klines(intrabar, intrabar_request, "intrabar klines")
        print(
            f"Intrabar rows: {len(intrabar)} | "
            f"{intrabar.period_start.min()} -> {intrabar.period_start.max()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
