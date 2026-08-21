"""Run the current backtest engine on legacy CSV data and Data Lake v2 data.

This is a migration gate, not a new production runner. It proves that replacing
strategy/intrabar CSV loading with MarketDataStore does not change trade results.
The existing BacktestEngine and strategy configuration are intentionally reused.

Example:
    python tools/data_lake_backtest_parity.py \
      --config "output/my_run/config.json" \
      --raw-root "C:\\CryptoBots\\Binance Market Data" \
      --symbol BTCUSDT
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

# Direct execution (``python tools/...py``) puts ``tools`` on sys.path instead of
# the repository root. Add the root explicitly so project imports work on a clean
# Windows checkout without requiring PYTHONPATH or an editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, MarketDataStore
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
        description="Compare the current CSV backtest with Data Lake v2 using the same engine/config"
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
            config, ignored = load_config_snapshot(path, require_paths=True)
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


def _window_intrabar(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    if frame is None:
        return None
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    return frame.loc[(timestamps >= start) & (timestamps < end)].reset_index(drop=True)


def main() -> int:
    args = build_parser().parse_args()
    config, ignored_config_fields = _load_parity_config(args.config)

    # Legacy path is the known-good reference for this migration gate.
    legacy_strategy, legacy_intrabar = load_backtest_data(config)
    strategy_minutes = int(config.strategy_timeframe_minutes)
    start = pd.Timestamp(legacy_strategy["timestamp"].min())
    end = pd.Timestamp(legacy_strategy["timestamp"].max()) + pd.Timedelta(minutes=strategy_minutes)
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
    store = MarketDataStore(args.raw_root, args.cache_root)
    archives = store.refresh_catalog()
    lake_strategy, lake_intrabar = load_backtest_frames_from_store(store, request)

    legacy_strategy_window = legacy_strategy.loc[
        (legacy_strategy["timestamp"] >= request.start) & (legacy_strategy["timestamp"] < request.end)
    ].reset_index(drop=True)
    legacy_intrabar_window = _window_intrabar(legacy_intrabar, request.start, request.end)

    strategy_parity = compare_ohlcv_frames(
        legacy_strategy_window,
        lake_strategy,
        tolerance=args.tolerance,
    )
    if legacy_intrabar_window is not None and lake_intrabar is not None:
        intrabar_parity = compare_ohlcv_frames(
            legacy_intrabar_window,
            lake_intrabar,
            tolerance=args.tolerance,
        )
    else:
        intrabar_parity = None

    report: dict[str, object] = {
        "config_path": str(args.config),
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
