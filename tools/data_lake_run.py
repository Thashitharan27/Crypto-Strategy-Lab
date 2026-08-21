"""Run one backtest directly from the Binance Data Lake v2 path.

This is the forward migration runner. It does not read strategy, intrabar or
structural-regime CSV files from the configuration. The JSON supplies strategy
settings only; market data comes from ``--raw-root`` through MarketDataStore.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data.backtest_service import load_backtest_bundle
from crypto_strategy_lab.data_lake_engine import DataLakeBacktestEngine
from crypto_strategy_lab.gui.config_logic import build_backtest_config, load_config_json


def _utc(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Crypto Strategy Lab directly from Data Lake v2")
    parser.add_argument("--config", required=True, type=Path, help="Current GUI configuration JSON")
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("cache"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="Inclusive UTC data start")
    parser.add_argument("--end", required=True, help="Exclusive UTC data end")
    parser.add_argument("--output-dir", type=Path, default=Path("output") / "data_lake_v2")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = build_backtest_config(load_config_json(args.config), require_paths=False)
    strategy_interval = f"{int(config.strategy_timeframe_minutes)}m"
    intrabar_interval = (
        f"{int(config.intrabar_timeframe_minutes)}m" if config.use_intrabar_data else None
    )
    request = DataRequest(
        symbol=args.symbol,
        start=_utc(args.start),
        end=_utc(args.end),
        strategy_interval=strategy_interval,
        intrabar_interval=intrabar_interval,
    )

    store = MarketDataStore(args.raw_root, args.cache_root)
    bundle = load_backtest_bundle(
        store,
        request,
        market_regime_method=config.market_regime_method,
        structural_regime_sma_days=config.structural_regime_sma_days,
        structural_regime_slope_lookback_days=config.structural_regime_slope_lookback_days,
    )
    engine = DataLakeBacktestEngine(
        bundle.strategy,
        config,
        bundle.intrabar,
        structural_benchmark=bundle.structural_benchmark,
    )
    trades = engine.run()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir / f"{request.symbol}_{request.strategy_interval}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    trades.to_csv(run_dir / "trade_list.csv", index=False)
    manifest = {
        "data_source": "binance_data_lake_v2",
        "raw_root": str(args.raw_root.resolve()),
        "cache_root": str(args.cache_root.resolve()),
        "config_path": str(args.config.resolve()),
        "request": {
            "symbol": request.symbol,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "strategy_interval": request.strategy_interval,
            "intrabar_interval": request.intrabar_interval,
        },
        "market_regime_method": config.market_regime_method,
        "structural_benchmark_symbol": bundle.structural_benchmark_symbol,
        "structural_benchmark_interval": bundle.structural_benchmark_interval,
        "strategy_rows": len(bundle.strategy),
        "intrabar_rows": len(bundle.intrabar) if bundle.intrabar is not None else 0,
        "benchmark_rows": len(bundle.structural_benchmark) if bundle.structural_benchmark is not None else 0,
        "trade_rows": len(trades),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({**manifest, "run_dir": str(run_dir.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
