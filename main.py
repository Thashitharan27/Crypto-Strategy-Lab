"""Command-line entry point for the dual long/short backtester."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from config import BacktestConfig
from engine import BacktestEngine
from loader import load_ohlcv_csv
from plots import save_plots
from statistics import equity_curve, summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dual long/short Binance OHLCV backtester")
    parser.add_argument("--input", type=Path, help="Binance OHLCV CSV path")
    parser.add_argument("--output-dir", type=Path, help="Directory for reports and charts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig()
    if args.input:
        config = replace(config, input_csv=args.input)
    if args.output_dir:
        config = replace(config, output_dir=args.output_dir)

    data = load_ohlcv_csv(str(config.input_csv), config.timestamp_unit)
    trades = BacktestEngine(data, config).run()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(config.output_dir / "trade_list.csv", index=False)
    equity = equity_curve(trades, config.initial_equity)
    equity.to_csv(config.output_dir / "equity_curve.csv", index=False)
    save_plots(trades, equity, config.output_dir)
    summary = summarize(trades)
    (config.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
