"""Command-line entry point for the dual long/short backtester."""

from __future__ import annotations

import argparse
import json
import traceback
from dataclasses import replace
from pathlib import Path

import pandas as pd

from crypto_strategy_lab.config import BacktestConfig, EntryMode, IntrabarMissingPolicy, PositionSizingMode, RiskMode, TiePolicy, BreakEvenMode, BreakEvenSameCandlePolicy, AdxFilterMode, BBWidthFilterMode, DISpreadFilterMode, TradeDirectionMode, DailyEntryMissedPolicy, AfterTP1StopMode, TP2ExitMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.loader import load_backtest_data, load_ohlcv_csv
from crypto_strategy_lab.plots import save_plots
from crypto_strategy_lab.statistics import adx_analysis, bb_width_analysis, di_spread_analysis, equity_curve, summarize
from crypto_strategy_lab.telemetry import add_journey_columns, double_sl_journey_analysis, save_journey_charts, trade_journey_analysis, winner_loser_journey_analysis, partial_take_profit_analysis
from crypto_strategy_lab.lifecycle import export_lifecycle_reports
from crypto_strategy_lab.support_resistance_analysis import generate_sr_analysis_reports
from crypto_strategy_lab.output_manager import create_run_dir, periodic_results, update_latest, write_config, write_run_info, write_trade_column_metadata
from crypto_strategy_lab.report_workbooks import build_backtest_workbook, build_indicator_workbook, build_performance_breakdowns
from crypto_strategy_lab.random_entry import decisions_frame, random_analysis, run_batch, comparison_row
from crypto_strategy_lab.config import EntryTimingMode


def enum_value(enum_cls):
    def parse(value: str):
        normalized = value.upper()
        try:
            return enum_cls(value)
        except ValueError:
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
    parser.add_argument("--trade-direction", type=enum_value(TradeDirectionMode), choices=list(TradeDirectionMode))
    parser.add_argument("--trade-direction-comparison", action="store_true", help="Run BOTH, LONG_ONLY, and SHORT_ONLY comparison report")
    parser.add_argument("--enable-partial-take-profit", action="store_true", default=None)
    parser.add_argument("--enable-partial-stop-loss", action="store_true", default=None)
    parser.add_argument("--sl1-r", type=float)
    parser.add_argument("--sl1-close-pct", type=float)
    parser.add_argument("--sl2-r", type=float)
    parser.add_argument("--tp1-r", type=float)
    parser.add_argument("--tp1-close-pct", type=float)
    parser.add_argument("--tp2-r", type=float)
    parser.add_argument("--tp2-close-pct", type=float)
    parser.add_argument("--stop-loss-r", type=float)
    parser.add_argument("--after-tp1-stop-mode", type=enum_value(AfterTP1StopMode), choices=list(AfterTP1StopMode))
    parser.add_argument("--after-tp1-stop-offset-r", type=float)
    parser.add_argument("--tp2-exit-mode", type=enum_value(TP2ExitMode), choices=list(TP2ExitMode))
    parser.add_argument("--enable-both-open-timeout", action="store_true", default=None)
    parser.add_argument("--max-both-open-minutes", type=int)
    parser.add_argument("--enable-remaining-leg-timeout-after-first-sl", action="store_true", default=None)
    parser.add_argument("--remaining-leg-timeout-after-first-sl-minutes", type=int)
    parser.add_argument("--enable-remaining-leg-timeout-profit-extension", action="store_true", default=None)
    parser.add_argument("--remaining-leg-timeout-profit-threshold-r", type=float)
    parser.add_argument("--enable-remaining-leg-checkpoint-score-extension", action="store_true", default=None)
    parser.add_argument("--no-checkpoint-score-profit", action="store_false", default=None, dest="checkpoint_score_use_profit")
    parser.add_argument("--checkpoint-score-min-profit-r", type=float)
    parser.add_argument("--no-checkpoint-score-atr", action="store_false", default=None, dest="checkpoint_score_use_atr_pct")
    parser.add_argument("--checkpoint-score-max-atr-pct", type=float)
    parser.add_argument("--no-checkpoint-score-directional-di", action="store_false", default=None, dest="checkpoint_score_use_directional_di")
    parser.add_argument("--checkpoint-score-min-directional-di", type=float)
    parser.add_argument("--no-checkpoint-score-bb-width", action="store_false", default=None, dest="checkpoint_score_use_bb_width_pct")
    parser.add_argument("--checkpoint-score-max-bb-width-pct", type=float)
    parser.add_argument("--checkpoint-score-min-conditions", type=int)
    parser.add_argument("--enable-first-sl-survivor-partial-close", action="store_true", default=None)
    parser.add_argument("--first-sl-survivor-partial-close-pct", type=float)
    parser.add_argument("--enable-checkpoint-zero-score-confirmation", action="store_true", default=None)
    parser.add_argument("--checkpoint-zero-score-confirmations-required", type=int)
    parser.add_argument("--checkpoint-zero-score-recheck-minutes", type=int)
    parser.add_argument("--enable-reentry-gate-after-remaining-leg-timeout", action="store_true", default=None)
    parser.add_argument("--timeout-comparison", action="store_true", help="Compare no timeout plus 2/4/6/8/12 hour both-open timeout runs")
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
    parser.add_argument("--enable-daily-entry-schedule", action="store_true", default=None)
    parser.add_argument("--daily-entry-time", default=None)
    parser.add_argument("--daily-entry-timezone", default=None)
    parser.add_argument("--daily-entry-missed-policy", type=enum_value(DailyEntryMissedPolicy), choices=list(DailyEntryMissedPolicy))
    parser.add_argument("--enable-skip-monday-entries", action="store_true", default=None)
    parser.add_argument("--skip-monday-timezone", default=None)
    parser.add_argument("--daily-entry-comparison", action="store_true", help="Compare continuous mode and daily 00:00/08:00/12:00/16:00 UTC schedules")
    parser.add_argument("--max-active-pairs", type=int)
    parser.add_argument("--enable-be-after-opposite-sl", action="store_true", default=None)
    parser.add_argument("--be-mode", type=enum_value(BreakEvenMode), choices=list(BreakEvenMode))
    parser.add_argument("--be-offset-r", type=float)
    parser.add_argument("--be-same-candle-policy", type=enum_value(BreakEvenSameCandlePolicy), choices=list(BreakEvenSameCandlePolicy))
    parser.add_argument("--be-comparison", action="store_true", help="Compare BE disabled, entry-price, cost-adjusted, +0.1R, and +0.25R runs")
    parser.add_argument("--enable-adx-filter", action="store_true", default=None)
    parser.add_argument("--adx-period", type=int)
    parser.add_argument("--adx-filter-mode", type=enum_value(AdxFilterMode), choices=list(AdxFilterMode))
    parser.add_argument("--adx-maximum", type=float)
    parser.add_argument("--adx-minimum", type=float)
    parser.add_argument("--adx-comparison", action="store_true", help="Compare ADX disabled and maximum-threshold filters")
    parser.add_argument("--enable-bb-width-filter", action="store_true", default=None)
    parser.add_argument("--bb-width-filter-mode", type=enum_value(BBWidthFilterMode), choices=list(BBWidthFilterMode))
    parser.add_argument("--bb-width-maximum", type=float)
    parser.add_argument("--bb-width-minimum", type=float, help="Raw BB width; use 0.012 for 1.2 percent")
    parser.add_argument("--bb-width-comparison", action="store_true", help="Compare BB width disabled and maximum-width filters")
    parser.add_argument("--enable-di-spread-filter", action="store_true", default=None)
    parser.add_argument("--di-spread-filter-mode", type=enum_value(DISpreadFilterMode), choices=list(DISpreadFilterMode))
    parser.add_argument("--di-spread-maximum", type=float)
    parser.add_argument("--di-spread-minimum", type=float)
    parser.add_argument("--di-spread-comparison", action="store_true", help="Compare DI spread disabled and maximum-spread filters")
    parser.add_argument("--disable-trade-telemetry", action="store_false", default=None, dest="enable_trade_telemetry")
    parser.add_argument("--no-full-telemetry-csv", action="store_false", default=None, dest="save_full_telemetry_csv")
    parser.add_argument("--no-trade-journey-summary", action="store_false", default=None, dest="save_trade_journey_summary")
    parser.add_argument("--no-trade-journey-charts", action="store_false", default=None, dest="save_trade_journey_charts")
    parser.add_argument("--telemetry-interval-minutes", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig()
    overrides = {}
    for key, value in vars(args).items():
        if value is not None and key not in ("timeout_comparison", "be_comparison", "adx_comparison", "bb_width_comparison", "di_spread_comparison", "trade_direction_comparison", "daily_entry_comparison"):
            overrides["input_csv" if key == "input" else key] = value
    config = replace(config, **overrides)

    data, intrabar = load_backtest_data(config)
    engine = BacktestEngine(data, config, intrabar)
    trades = engine.run()
    telemetry = engine.telemetry_frame()
    if config.enable_trade_telemetry:
        trades = add_journey_columns(trades, telemetry)
    output_root = config.output_dir
    run_dir = create_run_dir(config)
    write_config(config, run_dir)
    output_failures = []

    def run_output_step(label: str, action):
        print(f"{label}...")
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - output exports must continue independently.
            tb = traceback.format_exc()
            output_failures.append({"step": label, "error": str(exc), "traceback": tb})
            print(f"ERROR while {label}: {exc}")
            print(tb)
            return None

    run_output_step("Saving trade_list.csv", lambda: trades.to_csv(run_dir / "trade_list.csv", index=False))
    if engine.random_entry_active:
        run_output_step("Saving random_entry_decisions.csv", lambda: decisions_frame(engine.random_entry_decisions).to_csv(run_dir / "random_entry_decisions.csv", index=False))
        run_output_step("Saving random_entry_analysis.csv", lambda: random_analysis(trades, engine.random_entry_decisions, config).to_csv(run_dir / "random_entry_analysis.csv", index=False))
        baseline_cfg=replace(config,enable_random_entry=False,entry_timing_mode=EntryTimingMode.CURRENT,enable_random_entry_batch=False)
        baseline_trades=BacktestEngine(data,baseline_cfg,intrabar).run()
        run_output_step("Saving random_vs_baseline_comparison.csv", lambda: pd.DataFrame([comparison_row("CURRENT",None,baseline_trades,config.initial_equity),comparison_row("RANDOM_AFTER_PAIR_CLOSE",config.random_seed,trades,config.initial_equity)]).to_csv(run_dir / "random_vs_baseline_comparison.csv",index=False))
        if config.enable_random_entry_batch:
            batch, batch_stats=run_batch(data,intrabar,config)
            run_output_step("Saving random_entry_batch_summary.csv",lambda:batch.to_csv(run_dir / "random_entry_batch_summary.csv",index=False))
            run_output_step("Saving random_entry_batch_statistics.csv",lambda:batch_stats.to_csv(run_dir / "random_entry_batch_statistics.csv",index=False))
    run_output_step("Building partial_take_profit_analysis", lambda: partial_take_profit_analysis(trades).to_csv(run_dir / "partial_take_profit_analysis.csv", index=False))
    if config.enable_trade_telemetry:
        if config.save_full_telemetry_csv:
            run_output_step("Saving telemetry", lambda: telemetry.to_csv(run_dir / "trade_telemetry.csv", index=False))
        if config.save_trade_journey_summary:
            run_output_step("Building trade_journey_analysis", lambda: trade_journey_analysis(trades).to_csv(run_dir / "trade_journey_analysis.csv", index=False))
            run_output_step("Building winner_loser_journey_analysis", lambda: winner_loser_journey_analysis(trades).to_csv(run_dir / "winner_loser_journey_analysis.csv", index=False))
            run_output_step("Building double_sl_journey_analysis", lambda: double_sl_journey_analysis(trades, telemetry).to_csv(run_dir / "double_sl_journey_analysis.csv", index=False))
        if config.enable_indicator_lifecycle_analysis:
            run_output_step("Building indicator lifecycle reports", lambda: export_lifecycle_reports(trades, telemetry, run_dir, phases=config.lifecycle_phases, checkpoints=config.lifecycle_early_checkpoints, minimum_sample=config.lifecycle_minimum_bucket_sample, charts=config.create_lifecycle_charts, flat_threshold_pct=config.lifecycle_flat_pattern_threshold_pct))
    run_output_step("Saving skipped_signals.csv", lambda: pd.DataFrame(trades.attrs.get("skipped_signals", [])).to_csv(run_dir / "skipped_signals.csv", index=False))
    run_output_step("Saving skipped_daily_entries.csv", lambda: pd.DataFrame(trades.attrs.get("skipped_daily_entries", [])).to_csv(run_dir / "skipped_daily_entries.csv", index=False))
    indicator_tables = {"ADX": adx_analysis(trades), "BB Width": bb_width_analysis(trades), "DI Spread": di_spread_analysis(trades)}
    run_output_step("Saving indicator analysis workbook", lambda: build_indicator_workbook(indicator_tables, run_dir))
    run_output_step("Building support/resistance analysis", lambda: generate_sr_analysis_reports(trades, run_dir))
    run_output_step("Saving trade column metadata", lambda: write_trade_column_metadata(run_dir))
    equity = equity_curve(trades, config.initial_equity)
    run_output_step("Saving equity_curve.csv", lambda: equity.to_csv(run_dir / "equity_curve.csv", index=False))
    monthly, yearly = periodic_results(trades, "ME"), periodic_results(trades, "YE")
    chart_warnings = run_output_step("Saving charts", lambda: save_plots(trades, equity, run_dir / "charts")) or []
    if config.enable_trade_telemetry and config.save_trade_journey_charts:
        chart_warnings.extend(run_output_step("Saving journey charts", lambda: save_journey_charts(trades, telemetry, run_dir / "charts")) or [])
    for warning in chart_warnings:
      print(f"WARNING: {warning}")
    summary = summarize(trades, config.initial_equity)
    summary.update({"trade_direction": config.trade_direction.value, "use_intrabar_data": config.use_intrabar_data,"both_open_timeout_enabled":config.enable_both_open_timeout,"max_both_open_minutes":config.max_both_open_minutes, "intrabar_csv": str(config.intrabar_csv) if config.intrabar_csv else None, "strategy_timeframe": config.strategy_timeframe_minutes, "intrabar_timeframe": config.intrabar_timeframe_minutes, "atr_timeframe": config.strategy_timeframe_minutes, "atr_period": config.atr_period, "atr_multiplier": config.atr_multiplier, "indicator_data_start": str(data.timestamp.min()), "data_start": config.data_start_date, "trading_start": config.trading_start_date, "trading_end": config.trading_end_date, "warmup_candles": engine.warmup_candle_count, "first_valid_atr_timestamp": str(engine.first_valid_atr_timestamp)})

    if args.timeout_comparison:
        rows = []
        for label, minutes, enabled in [("No timeout", 0, False), ("2 hours", 120, True), ("4 hours", 240, True), ("6 hours", 360, True), ("8 hours", 480, True), ("12 hours", 720, True)]:
            cmp_cfg = replace(config, enable_both_open_timeout=enabled, max_both_open_minutes=minutes or config.max_both_open_minutes)
            cmp_trades = BacktestEngine(data, cmp_cfg, intrabar).run()
            cmp_summary = summarize(cmp_trades, cmp_cfg.initial_equity)
            combos = cmp_summary.get("exit_combinations", {})
            rows.append({"duration": label, "total_pairs": cmp_summary.get("total_pairs"), "win_rate": cmp_summary.get("win_rate"), "double_sl_count": combos.get("Long SL / Short SL", {}).get("count", 0), "timeout_count": cmp_summary.get("pairs_closed_by_both_open_timeout", 0), "net_pnl": float(cmp_trades["pair_net_pnl"].sum()) if not cmp_trades.empty else 0.0, "total_return": cmp_summary.get("total_return_percentage"), "profit_factor": cmp_summary.get("profit_factor"), "maximum_drawdown": cmp_summary.get("maximum_drawdown"), "total_fees": cmp_summary.get("total_fees")})
        summary["both_open_timeout_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "both_open_timeout_comparison.csv", index=False)
    if args.be_comparison:
        rows=[]
        scenarios=[("BE disabled", False, BreakEvenMode.ENTRY_PRICE, 0.0),("Entry-price BE", True, BreakEvenMode.ENTRY_PRICE, 0.0),("Cost-adjusted BE", True, BreakEvenMode.COST_ADJUSTED, 0.0),("BE +0.1R", True, BreakEvenMode.R_OFFSET, 0.1),("BE +0.25R", True, BreakEvenMode.R_OFFSET, 0.25)]
        for label,enabled,mode,offset in scenarios:
            cmp_cfg=replace(config, enable_be_after_opposite_sl=enabled, be_mode=mode, be_offset_r=offset)
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run(); cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity); combos=cmp_summary.get("exit_combinations", {})
            normal=sum(v.get("count",0) for k,v in combos.items() if k in ("Long TP / Short SL","Long SL / Short TP"))
            rows.append({"scenario":label,"total_pairs":cmp_summary.get("total_pairs"),"normal_tp_sl_pairs":normal,"double_sl_pairs":combos.get("Long SL / Short SL",{}).get("count",0),"be_exits":cmp_summary.get("remaining_legs_stopped_at_be"),"tp_after_be_trigger":cmp_summary.get("remaining_legs_reaching_tp_after_be_move"),"net_pnl":float(cmp_trades["pair_net_pnl"].sum()) if not cmp_trades.empty else 0.0,"total_fees":cmp_summary.get("total_fees"),"profit_factor":cmp_summary.get("profit_factor"),"maximum_drawdown":cmp_summary.get("maximum_drawdown"),"ending_equity":cmp_summary.get("ending_equity")})
        summary["be_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "be_comparison.csv", index=False)
    if args.adx_comparison:
        rows=[]
        scenarios=[("ADX disabled", False, AdxFilterMode.DISABLED, config.adx_maximum)] + [(f"Maximum {v}", True, AdxFilterMode.MAXIMUM, float(v)) for v in (15,20,25,30,35)]
        for label,enabled,mode,max_adx in scenarios:
            cmp_cfg=replace(config, enable_adx_filter=enabled, adx_filter_mode=mode, adx_maximum=max_adx)
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run(); cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity); combos=cmp_summary.get("exit_combinations", {})
            rows.append({"scenario":label,"return":cmp_summary.get("total_return_percentage"),"profit_factor":cmp_summary.get("profit_factor"),"max_drawdown":cmp_summary.get("maximum_drawdown"),"double_sl":combos.get("Long SL / Short SL",{}).get("count",0),"fees":cmp_summary.get("total_fees"),"win_rate":cmp_summary.get("win_rate")})
        summary["adx_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "adx_comparison.csv", index=False)

    if args.bb_width_comparison:
        rows=[]
        scenarios=[("BB width disabled", False, BBWidthFilterMode.DISABLED, config.bb_width_maximum)] + [(f"Maximum {v}%", True, BBWidthFilterMode.MAXIMUM, v/100.0) for v in (2,3,4,5,6)]
        for label,enabled,mode,max_width in scenarios:
            cmp_cfg=replace(config, enable_bb_width_filter=enabled, bb_width_filter_mode=mode, bb_width_maximum=max_width)
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run(); cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity); combos=cmp_summary.get("exit_combinations", {})
            rows.append({"scenario":label,"return":cmp_summary.get("total_return_percentage"),"win_rate":cmp_summary.get("win_rate"),"double_sl":combos.get("Long SL / Short SL",{}).get("count",0),"profit_factor":cmp_summary.get("profit_factor"),"max_drawdown":cmp_summary.get("maximum_drawdown"),"fees":cmp_summary.get("total_fees")})
        summary["bb_width_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "bb_width_comparison.csv", index=False)
    if args.di_spread_comparison:
        rows=[]
        scenarios=[("DI spread disabled", False, DISpreadFilterMode.DISABLED, config.di_spread_maximum)] + [(f"Maximum {v}", True, DISpreadFilterMode.MAXIMUM, float(v)) for v in (5,10,15,20)]
        for label,enabled,mode,max_spread in scenarios:
            cmp_cfg=replace(config, enable_di_spread_filter=enabled, di_spread_filter_mode=mode, di_spread_maximum=max_spread)
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run(); cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity); combos=cmp_summary.get("exit_combinations", {})
            rows.append({"scenario":label,"return":cmp_summary.get("total_return_percentage"),"win_rate":cmp_summary.get("win_rate"),"double_sl":combos.get("Long SL / Short SL",{}).get("count",0),"profit_factor":cmp_summary.get("profit_factor"),"max_drawdown":cmp_summary.get("maximum_drawdown"),"fees":cmp_summary.get("total_fees")})
        summary["di_spread_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "di_spread_comparison.csv", index=False)

    if args.daily_entry_comparison:
        rows=[]
        scenarios=[("Continuous re-entry", False, config.daily_entry_time), ("Daily 00:00 UTC", True, "00:00"), ("Daily 08:00 UTC", True, "08:00"), ("Daily 12:00 UTC", True, "12:00"), ("Daily 16:00 UTC", True, "16:00")]
        for label, enabled, entry_time in scenarios:
            cmp_cfg=replace(config, enable_daily_entry_schedule=enabled, daily_entry_time=entry_time, daily_entry_timezone="UTC")
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run(); cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity)
            rows.append({"scenario":label,"Trades":cmp_summary.get("total_trades"),"Win rate":cmp_summary.get("win_rate"),"Net PnL":float(cmp_trades["pair_net_pnl"].sum()) if not cmp_trades.empty else 0.0,"Profit factor":cmp_summary.get("profit_factor"),"Maximum drawdown":cmp_summary.get("maximum_drawdown"),"Average holding time":cmp_summary.get("average_holding_time"),"Total fees":cmp_summary.get("total_fees"),"Skipped days":cmp_summary.get("days_without_trades")})
        summary["daily_entry_comparison"] = rows
        pd.DataFrame(rows).to_csv(run_dir / "daily_entry_comparison.csv", index=False)

    if args.trade_direction_comparison:
        rows=[]
        for label, mode in [("BOTH", TradeDirectionMode.BOTH), ("LONG", TradeDirectionMode.LONG_ONLY), ("SHORT", TradeDirectionMode.SHORT_ONLY)]:
            cmp_cfg=replace(config, trade_direction=mode)
            cmp_trades=BacktestEngine(data, cmp_cfg, intrabar).run()
            cmp_summary=summarize(cmp_trades, cmp_cfg.initial_equity)
            rows.append({"Metric":"values","mode":label,"Trades":cmp_summary.get("total_trades"),"Win %":cmp_summary.get("win_rate"),"Net PnL":float(cmp_trades["pair_net_pnl"].sum()) if not cmp_trades.empty else 0.0,"Profit Factor":cmp_summary.get("profit_factor"),"Max Drawdown":cmp_summary.get("maximum_drawdown"),"Avg Hold":cmp_summary.get("average_holding_time"),"Fees":cmp_summary.get("total_fees"),"Avg Winner":cmp_summary.get("average_winner"),"Avg Loser":cmp_summary.get("average_loser")})
        comparison=pd.DataFrame(rows).set_index("mode").drop(columns=["Metric"]).T.reset_index().rename(columns={"index":"Metric"})
        summary["trade_direction_comparison"] = comparison.to_dict(orient="records")
        comparison.to_csv(run_dir / "trade_direction_comparison.csv", index=False)
    if config.zero_cost_comparison:
        ideal_cfg = replace(config, maker_fee=0, taker_fee=0, slippage=0, zero_cost_comparison=False)
        ideal_trades = BacktestEngine(data, ideal_cfg, intrabar).run()
        ideal = summarize(ideal_trades, ideal_cfg.initial_equity)
        summary["zero_cost_comparison"] = {"actual": {k: summary.get(k) for k in ("win_rate","total_net_r","ending_equity","total_return_percentage","profit_factor","maximum_drawdown")}, "zero_cost": {k: ideal.get(k) for k in ("win_rate","total_net_r","ending_equity","total_return_percentage","profit_factor","maximum_drawdown")}}
    if output_failures:
        summary["failed_output_reports"] = output_failures
        print("WARNING: Some output reports failed: " + ", ".join(f["step"] for f in output_failures))
    if config.use_intrabar_data and summary.get("intrabar_exit_count") == 0:
        print("WARNING: use_intrabar_data=True but 1M_INTRABAR exit count is 0. Check intrabar path, overlap, and timestamp alignment.")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    market_regime, direction_regime = build_performance_breakdowns(trades)
    run_output_step("Saving backtest report workbook", lambda: build_backtest_workbook(summary, config, run_dir, monthly, yearly, market_regime, direction_regime))
    write_run_info(config, summary, run_dir)
    (run_dir / "log.txt").write_text("Command-line backtest completed.\n")
    update_latest(output_root, run_dir)
    summary["output_dir"] = str(run_dir)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
