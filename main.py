"""Command-line entry point for the dual long/short backtester."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from config import BacktestConfig, EntryMode, IntrabarMissingPolicy, PositionSizingMode, RiskMode, TiePolicy
from engine import BacktestEngine
from loader import load_backtest_data, load_ohlcv_csv
from plots import save_plots
from statistics import equity_curve, summarize
from output_manager import create_run_dir, periodic_results, update_latest, write_config, write_run_info, write_summary_txt, write_trade_column_metadata


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
    parser.add_argument("--input", type=Path, help="Backward-compatible strategy CSV path")
    parser.add_argument("--strategy-input", type=Path, dest="strategy_csv")
    parser.add_argument("--intrabar-input", type=Path, dest="intrabar_csv")
    parser.add_argument("--use-intrabar", action="store_true", default=None, dest="use_intrabar_data")
    parser.add_argument("--strategy-timeframe", type=int, dest="strategy_timeframe_minutes")
    parser.add_argument("--intrabar-timeframe", type=int, dest="intrabar_timeframe_minutes")
    parser.add_argument("--data-start", dest="data_start_date")
    parser.add_argument("--trading-start", dest="trading_start_date")
    parser.add_argument("--trading-end", dest="trading_end_date")
    parser.add_argument("--max-leverage-per-leg", type=float, dest="max_effective_leverage_per_leg")
    parser.add_argument("--max-combined-leverage", type=float, dest="max_combined_effective_leverage")
    parser.add_argument("--intrabar-missing-policy", type=enum_value(IntrabarMissingPolicy), choices=list(IntrabarMissingPolicy))
    parser.add_argument("--zero-cost-comparison", action="store_true", default=None)
    parser.add_argument("--output-dir", type=Path, help="Directory for reports and charts")
    parser.add_argument("--run-name", default=None, help="Optional run name prefix for the timestamped output folder")
    parser.add_argument("--risk-mode", type=enum_value(RiskMode), choices=list(RiskMode))
    parser.add_argument("--fixed-r", type=float)
    parser.add_argument("--percent-r", type=float)
    parser.add_argument("--atr-period", type=int)
    parser.add_argument("--atr-multiplier", type=float)
    parser.add_argument("--sl-mult", type=float)
    parser.add_argument("--tp-mult", type=float)
    parser.add_argument("--risk-per-leg", type=float)
    parser.add_argument("--position-sizing-mode", type=enum_value(PositionSizingMode), choices=list(PositionSizingMode))
    parser.add_argument("--all-in-risk-sizing", action="store_const", const=PositionSizingMode.ALL_IN_STOP_RISK, dest="position_sizing_mode")
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

    data, intrabar = load_backtest_data(config)
    engine = BacktestEngine(data, config, intrabar)
    trades = engine.run()
    output_root = config.output_dir
    run_dir = create_run_dir(config)
    write_config(config, run_dir)
    trades.to_csv(run_dir / "trade_list.csv", index=False)
    write_trade_column_metadata(run_dir)
    equity = equity_curve(trades, config.initial_equity)
    equity.to_csv(run_dir / "equity_curve.csv", index=False)
    periodic_results(trades, "ME").to_csv(run_dir / "monthly_results.csv", index=False)
    periodic_results(trades, "YE").to_csv(run_dir / "yearly_results.csv", index=False)
    chart_warnings = save_plots(trades, equity, run_dir / "charts")
    for warning in chart_warnings:
      print(f"WARNING: {warning}")
    summary = summarize(trades, config.initial_equity)
    summary.update({"use_intrabar_data": config.use_intrabar_data, "intrabar_csv": str(config.intrabar_csv) if config.intrabar_csv else None, "strategy_timeframe": config.strategy_timeframe_minutes, "intrabar_timeframe": config.intrabar_timeframe_minutes, "atr_timeframe": config.strategy_timeframe_minutes, "atr_period": config.atr_period, "atr_multiplier": config.atr_multiplier, "indicator_data_start": str(data.timestamp.min()), "data_start": config.data_start_date, "trading_start": config.trading_start_date, "trading_end": config.trading_end_date, "warmup_candles": engine.warmup_candle_count, "first_valid_atr_timestamp": str(engine.first_valid_atr_timestamp)})
    if config.zero_cost_comparison:
        ideal_cfg = replace(config, maker_fee=0, taker_fee=0, slippage=0, zero_cost_comparison=False)
        ideal_trades = BacktestEngine(data, ideal_cfg, intrabar).run()
        ideal = summarize(ideal_trades, ideal_cfg.initial_equity)
        summary["zero_cost_comparison"] = {"actual": {k: summary.get(k) for k in ("win_rate","total_net_r","ending_equity","total_return_percentage","profit_factor","maximum_drawdown")}, "zero_cost": {k: ideal.get(k) for k in ("win_rate","total_net_r","ending_equity","total_return_percentage","profit_factor","maximum_drawdown")}}
    if config.use_intrabar_data and summary.get("intrabar_exit_count") == 0:
        print("WARNING: use_intrabar_data=True but 1M_INTRABAR exit count is 0. Check intrabar path, overlap, and timestamp alignment.")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_summary_txt(summary, run_dir)
    write_run_info(config, summary, run_dir)
    (run_dir / "log.txt").write_text("Command-line backtest completed.\n")
    update_latest(output_root, run_dir)
    summary["output_dir"] = str(run_dir)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
