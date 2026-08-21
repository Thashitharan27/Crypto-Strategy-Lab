"""Run the current backtest engine on a legacy-style reference and Data Lake v2.

This is a migration gate, not a production runner. When the original combined
CSV still exists, it remains the reference. When it has been removed, this tool
reconstructs an independent legacy-style OHLCV frame directly from the raw
Binance ZIP/CSV archives for the exact period recorded in the saved run log.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from io import TextIOWrapper
from itertools import chain
import json
from pathlib import Path
import re
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, DatasetKind, MarketDataStore
from crypto_strategy_lab.data.legacy_bridge import (
    compare_ohlcv_frames,
    compare_trade_frames,
    load_backtest_frames_from_store,
)
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.config_logic import build_backtest_config, load_config_json
from crypto_strategy_lab.loader import load_backtest_data
from crypto_strategy_lab.output_manager import load_config_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a legacy-style backtest data path with Data Lake v2 using the same engine/config"
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Current GUI config JSON or a saved output/<run>/config.json snapshot",
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--start",
        help="Optional UTC override for reconstructed-reference start (normally read from run log)",
    )
    parser.add_argument(
        "--end",
        help="Optional UTC exclusive end override for reconstructed reference (normally read from run log)",
    )
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--output", type=Path, default=Path("data_lake_backtest_parity.json"))
    return parser


def _load_parity_config(path: Path):
    """Load either the current GUI schema or an older saved run snapshot."""

    try:
        config = build_backtest_config(load_config_json(path), require_paths=True)
        print(f"Config source: current GUI config ({path})")
        return config, ()
    except ValueError as gui_error:
        try:
            # A saved run may legitimately reference a combined CSV that was
            # deleted after migration to the raw Binance data lake.
            config, ignored = load_config_snapshot(path, require_paths=False)
        except Exception as snapshot_error:
            raise ValueError(
                "Could not load config as either a current GUI config or a saved run snapshot.\n"
                f"GUI config error: {gui_error}\n"
                f"Saved run snapshot error: {snapshot_error}"
            ) from snapshot_error
        print(f"Config source: saved run snapshot ({path})")
        if ignored:
            print(
                "Ignored retired snapshot fields that no longer exist in the current engine: "
                + ", ".join(ignored)
            )
        return config, ignored


def _utc_timestamp(value: str) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        return result.tz_localize("UTC")
    return result.tz_convert("UTC")


def _period_from_saved_run(config_path: Path, strategy_minutes: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Recover the exact strategy-data window written by the GUI worker log."""

    log_path = config_path.parent / "log.txt"
    if not log_path.is_file():
        raise ValueError(
            f"Legacy CSV is missing and saved run log was not found: {log_path}. "
            "Supply --start and --end explicitly."
        )
    pattern = re.compile(r"^Period:\s*(.+?)\s+to\s+(.+?)\s*$")
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        start = _utc_timestamp(match.group(1))
        last_open = _utc_timestamp(match.group(2))
        return start, last_open + pd.Timedelta(minutes=strategy_minutes)
    raise ValueError(
        f"Could not find the recorded 'Period: ... to ...' line in {log_path}. "
        "Supply --start and --end explicitly."
    )


def _timestamp_to_ms(text: str) -> int:
    raw = int(float(text.strip()))
    magnitude = abs(raw)
    if magnitude >= 10**17:  # nanoseconds
        return raw // 1_000_000
    if magnitude >= 10**14:  # microseconds
        return raw // 1_000
    if magnitude >= 10**11:  # milliseconds
        return raw
    return raw * 1_000  # seconds, defensive fallback


def _iter_csv_streams(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield path.name, stream
        return
    with zipfile.ZipFile(path) as archive:
        members = sorted(
            (item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")),
            key=lambda item: item.filename.lower(),
        )
        if not members:
            raise ValueError(f"{path} contains no CSV member")
        for member in members:
            with archive.open(member) as binary:
                with TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
                    yield f"{path.name}:{member.filename}", text


def _raw_reference_ohlcv(records, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Independently parse raw Binance kline archives into current-engine OHLCV."""

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[tuple[int, float, float, float, float, float]] = []
    for record in records:
        for label, stream in _iter_csv_streams(Path(record.path)):
            reader = csv.reader(stream)
            first = next(reader, None)
            if first is None:
                continue
            normalized = [str(cell).strip().lower().replace(" ", "_") for cell in first]
            has_header = normalized[0] in {"open_time", "timestamp", "time"}
            if has_header:
                aliases = {
                    "time": next((normalized.index(name) for name in ("open_time", "timestamp", "time") if name in normalized), None),
                    "open": normalized.index("open") if "open" in normalized else None,
                    "high": normalized.index("high") if "high" in normalized else None,
                    "low": normalized.index("low") if "low" in normalized else None,
                    "close": normalized.index("close") if "close" in normalized else None,
                    "volume": normalized.index("volume") if "volume" in normalized else None,
                }
                if any(value is None for value in aliases.values()):
                    raise ValueError(f"{label}: unsupported kline header {normalized}")
                data_rows = reader
            else:
                if len(first) < 6:
                    raise ValueError(f"{label}: expected at least six Binance kline columns")
                aliases = {"time": 0, "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}
                data_rows = chain((first,), reader)

            for row in data_rows:
                if not row or len(row) <= max(aliases.values()):
                    continue
                try:
                    timestamp_ms = _timestamp_to_ms(row[aliases["time"]])
                    if timestamp_ms < start_ms or timestamp_ms >= end_ms:
                        continue
                    rows.append(
                        (
                            timestamp_ms,
                            float(row[aliases["open"]]),
                            float(row[aliases["high"]]),
                            float(row[aliases["low"]]),
                            float(row[aliases["close"]]),
                            float(row[aliases["volume"]]),
                        )
                    )
                except (TypeError, ValueError):
                    continue

    if not rows:
        raise ValueError(f"Raw archive reconstruction produced no kline rows for {start} -> {end}")
    frame = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame.pop("timestamp_ms"), unit="ms", utc=True)
    frame = frame.sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="last")
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame["volume"] < 0)
    )
    return frame.loc[~invalid, ["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _window_intrabar(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    if frame is None:
        return None
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    return frame.loc[(timestamps >= start) & (timestamps < end)].reset_index(drop=True)


def main() -> int:
    args = build_parser().parse_args()
    config, ignored_config_fields = _load_parity_config(args.config)
    strategy_minutes = int(config.strategy_timeframe_minutes)
    original_strategy_exists = Path(config.input_csv).is_file()
    original_intrabar_exists = (
        not config.use_intrabar_data
        or config.intrabar_csv is None
        or Path(config.intrabar_csv).is_file()
    )
    use_original_legacy = original_strategy_exists and original_intrabar_exists

    store = MarketDataStore(args.raw_root, args.cache_root)
    archives = store.refresh_catalog()

    if use_original_legacy:
        reference_mode = "original_legacy_csv"
        legacy_strategy, legacy_intrabar = load_backtest_data(config)
        start = pd.Timestamp(legacy_strategy["timestamp"].min())
        end = pd.Timestamp(legacy_strategy["timestamp"].max()) + pd.Timedelta(minutes=strategy_minutes)
    else:
        reference_mode = "raw_archive_reconstruction"
        if args.start and args.end:
            start, end = _utc_timestamp(args.start), _utc_timestamp(args.end)
        elif args.start or args.end:
            raise ValueError("Use both --start and --end together")
        else:
            start, end = _period_from_saved_run(args.config, strategy_minutes)
        print(
            "Original combined CSV reference is unavailable; reconstructing an independent "
            f"legacy-style reference from raw Binance archives for {start} -> {end}"
        )

    intrabar_interval = (
        f"{int(config.intrabar_timeframe_minutes)}m"
        if config.use_intrabar_data and config.intrabar_csv
        else None
    )
    request = DataRequest(
        symbol=args.symbol,
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        strategy_interval=f"{strategy_minutes}m",
        intrabar_interval=intrabar_interval,
    )
    lake_strategy, lake_intrabar = load_backtest_frames_from_store(store, request)

    if use_original_legacy:
        legacy_strategy_window = legacy_strategy.loc[
            (legacy_strategy["timestamp"] >= request.start) & (legacy_strategy["timestamp"] < request.end)
        ].reset_index(drop=True)
        legacy_intrabar_window = _window_intrabar(legacy_intrabar, request.start, request.end)
    else:
        strategy_records = store.catalog.records_for(
            store.raw_root, request, DatasetKind.KLINES, request.strategy_interval
        )
        if not strategy_records:
            raise ValueError(f"No raw strategy kline archives found for {request.symbol} {request.strategy_interval}")
        legacy_strategy_window = _raw_reference_ohlcv(strategy_records, start, end)

        legacy_intrabar_window = None
        if request.intrabar_interval:
            intrabar_records = store.catalog.records_for(
                store.raw_root, request, DatasetKind.KLINES, request.intrabar_interval
            )
            if not intrabar_records:
                raise ValueError(f"No raw intrabar kline archives found for {request.symbol} {request.intrabar_interval}")
            legacy_intrabar_window = _raw_reference_ohlcv(intrabar_records, start, end)

    strategy_parity = compare_ohlcv_frames(
        legacy_strategy_window, lake_strategy, tolerance=args.tolerance
    )
    if legacy_intrabar_window is not None and lake_intrabar is not None:
        intrabar_parity = compare_ohlcv_frames(
            legacy_intrabar_window, lake_intrabar, tolerance=args.tolerance
        )
    else:
        intrabar_parity = None

    report: dict[str, object] = {
        "config_path": str(args.config),
        "reference_mode": reference_mode,
        "original_strategy_csv_exists": original_strategy_exists,
        "original_intrabar_csv_exists": original_intrabar_exists,
        "ignored_retired_config_fields": list(ignored_config_fields),
        "cataloged_archives": archives,
        "symbol": request.symbol,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "strategy_interval": request.strategy_interval,
        "intrabar_interval": request.intrabar_interval,
        "strategy_frame": {**asdict(strategy_parity), "exact": strategy_parity.exact},
        "intrabar_frame": (
            {**asdict(intrabar_parity), "exact": intrabar_parity.exact}
            if intrabar_parity is not None
            else None
        ),
    }

    frames_exact = strategy_parity.exact and (intrabar_parity is None or intrabar_parity.exact)
    if not frames_exact:
        report["engine_comparison_skipped"] = (
            "Candle parity failed; engine comparison was intentionally skipped to keep the failure localized."
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 2

    legacy_trades = BacktestEngine(legacy_strategy_window, config, legacy_intrabar_window).run()
    lake_trades = BacktestEngine(lake_strategy, config, lake_intrabar).run()
    trade_parity = compare_trade_frames(legacy_trades, lake_trades, tolerance=args.tolerance)
    report["trades"] = {**asdict(trade_parity), "exact": trade_parity.exact}
    report["exact"] = bool(frames_exact and trade_parity.exact)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["exact"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
