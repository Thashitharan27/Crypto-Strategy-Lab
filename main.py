"""Command-line entry point for the dual long/short backtester."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from engine import BacktestEngine
from loader import load_ohlcv_csv
from plots import save_plots
from statistics import equity_curve, summarize


def enum_value(enum_cls):
    def parse(value: str):
        normalized = value.upper()
        try:
            return enum_cls(normalized)
        except ValueError:
            return enum_cls[normalized]
    return parse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dual long/short Binance OHLCV backtester")
    parser.add_argument("--input", type=Path, help="Binance OHLCV CSV path")
    parser.add_argument("--output-dir", type=Path, help="Directory for reports and charts")
    parser.add_argument("--risk-mode", type=enum_value(RiskMode), choices=list(RiskMode))
    parser.add_argument("--fixed-r", type=float)
    parser.add_argument("--percent-r", type=float)
    parser.add_argument("--atr-period", type=int)
    parser.add_argument("--atr-multiplier", type=float)
    parser.add_argument("--sl-mult", type=float)
    parser.add_argument("--tp-mult", type=float)
    parser.add_argument("--risk-per-leg", type=float)
    parser.add_argument("--initial-equity", type=float)
    parser.add_argument("--maker-fee", type=float)
    parser.add_argument("--taker-fee", type=float)
    parser.add_argument("--slippage", type=float)
    parser.add_argument("--tie-policy", type=enum_value(TiePolicy), choices=list(TiePolicy))
    parser.add_argument("--entry-mode", type=enum_value(EntryMode), choices=list(EntryMode))
    parser.add_argument("--entry-interval", type=int)
    parser.add_argument("--max-active-pairs", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig()
    overrides = {}
    for key, value in vars(args).items():
        if value is not None:
            overrides["input_csv" if key == "input" else key] = value
    config = replace(config, **overrides)

    data = load_ohlcv_csv(str(config.input_csv), config.timestamp_unit)
    trades = BacktestEngine(data, config).run()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(config.output_dir / "trade_list.csv", index=False)
    equity = equity_curve(trades, config.initial_equity)
    equity.to_csv(config.output_dir / "equity_curve.csv", index=False)
    save_plots(trades, equity, config.output_dir)
    summary = summarize(trades, config.initial_equity)
    (config.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
