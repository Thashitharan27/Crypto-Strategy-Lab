"""Validate Data Lake v2 coverage and optionally compare it with a legacy CSV.

Example:
    python tools/data_lake_validate.py \
      --raw-root "C:\\CryptoBots\\Binance Market Data" \
      --symbol BTCUSDT --strategy-interval 15m --intrabar-interval 1m \
      --start 2025-01-01 --end 2025-02-01 \
      --legacy-strategy-csv "C:\\path\\BTCUSDT_15m.csv"
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from crypto_strategy_lab.data import DataRequest, DatasetKind, MarketDataStore
from crypto_strategy_lab.data.legacy_bridge import compare_ohlcv_frames, load_backtest_frames_from_store
from crypto_strategy_lab.loader import load_ohlcv_csv


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
    parser.add_argument("--legacy-strategy-csv", type=Path)
    parser.add_argument("--timestamp-unit", default="ms")
    return parser


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
    strategy, intrabar = load_backtest_frames_from_store(store, request)
    print(
        f"Strategy rows: {len(strategy)} | {strategy.timestamp.min()} -> {strategy.timestamp.max()}"
    )
    if intrabar is not None:
        print(f"Intrabar rows: {len(intrabar)} | {intrabar.timestamp.min()} -> {intrabar.timestamp.max()}")

    if args.legacy_strategy_csv:
        legacy = load_ohlcv_csv(str(args.legacy_strategy_csv), timestamp_unit=args.timestamp_unit)
        window = legacy.loc[(legacy.timestamp >= request.start) & (legacy.timestamp < request.end)].reset_index(drop=True)
        parity = compare_ohlcv_frames(strategy, window)
        print(f"Legacy parity exact: {parity.exact}")
        print(
            f"rows new/legacy={parity.rows_left}/{parity.rows_right}, "
            f"timestamp_mismatches={parity.timestamp_mismatches}, "
            f"value_mismatches={parity.value_mismatches}"
        )
        print(f"max_abs_diff={parity.max_abs_diff}")
        return 0 if parity.exact else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
