"""QThread worker that runs the existing backtesting pipeline."""
from __future__ import annotations

import json, time, traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from config import BacktestConfig
from engine import BacktestEngine
from loader import load_backtest_data
from plots import save_plots
from statistics import adx_analysis, equity_curve, summarize
from output_manager import create_run_dir, periodic_results, update_latest, write_config, write_run_info, write_summary_txt

class BacktestWorker(QObject):
    status = Signal(str, int)
    log = Signal(str)
    finished = Signal(dict, object, object, object)
    failed = Signal(str, str)

    def __init__(self, config: BacktestConfig):
        super().__init__(); self.config = config; self._cancel = False; self._started = 0.0; self._log_lines: list[str] = []

    @Slot()
    def cancel(self) -> None:
        self._cancel = True

    def _check(self):
        if self._cancel: raise RuntimeError("Backtest cancelled by user.")

    def _log(self, message: str) -> None:
        self._log_lines.append(str(message))
        self.log.emit(str(message))

    def _elapsed(self) -> float:
        return max(0.0, time.time() - self._started) if self._started else 0.0

    @staticmethod
    def _fmt_duration(seconds: float | None) -> str:
        if seconds is None or seconds == float("inf"):
            return "calculating"
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {secs}s"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def _emit_stage(self, stage: str, percent: int, processed: int = 0, total: int = 0, completed: int = 0, pair_total: int = 0, remaining: float | None = None) -> None:
        detail = (
            f"Stage: {stage} | Strategy candles: {processed:,} / {total:,} | "
            f"Completed pairs: {completed:,} / {pair_total:,} | "
            f"Elapsed: {self._fmt_duration(self._elapsed())} | ETA: {self._fmt_duration(remaining)}"
        )
        self.status.emit(detail, max(0, min(100, int(percent))))

    def _backtest_progress(self, processed: int, total: int, completed: int, opened: int) -> None:
        self._check()
        ratio = processed / total if total else 1.0
        percent = 20 + round(70 * ratio)
        elapsed = self._elapsed()
        remaining = (elapsed / ratio) - elapsed if ratio > 0 else None
        self._emit_stage("Backtesting", percent, processed, total, completed, opened, remaining)

    @Slot()
    def run(self) -> None:
        self._started = time.time()
        try:
            self._emit_stage("Loading data", 0)
            data, intrabar = load_backtest_data(self.config)
            self._emit_stage("Loading data", 10, 0, len(data))
            self._log(f"Loaded {len(data):,} strategy candles")
            if intrabar is not None: self._log(f"Loaded {len(intrabar):,} intrabar candles")
            self._log(f"Period: {data['timestamp'].min()} to {data['timestamp'].max()}")
            self._check(); self._emit_stage("ATR calculation", 10, 0, len(data))
            self._log(f"Running {self.config.risk_mode.value}, ATR({self.config.atr_period}), multiplier {self.config.atr_multiplier}")
            self._log(f"Intrabar config: use_intrabar_data={self.config.use_intrabar_data}, intrabar_csv={self.config.intrabar_csv}, intrabar_timeframe={self.config.intrabar_timeframe_minutes}m")
            engine = BacktestEngine(data, self.config, intrabar, progress_callback=self._backtest_progress, progress_interval=50)
            self._check(); self._emit_stage("ATR calculation", 20, 0, len(data))
            trades = engine.run()
            self._check(); self._emit_stage("Statistics", 90, len(data), len(data), len(trades), len(trades))
            equity = equity_curve(trades, self.config.initial_equity)
            summary = summarize(trades, self.config.initial_equity)
            summary.update({"use_intrabar_data": self.config.use_intrabar_data, "intrabar_csv": str(self.config.intrabar_csv) if self.config.intrabar_csv else None, "strategy_timeframe": self.config.strategy_timeframe_minutes, "intrabar_timeframe": self.config.intrabar_timeframe_minutes, "atr_period": self.config.atr_period, "atr_multiplier": self.config.atr_multiplier})
            if self.config.use_intrabar_data and summary.get("intrabar_exit_count") == 0:
                self._log("WARNING: use_intrabar_data=True but 1M_INTRABAR exit count is 0. Check intrabar path, overlap, and timestamp alignment.")
            self._check(); self._emit_stage("Saving outputs", 95, len(data), len(data), len(trades), len(trades))
            output_root = self.config.output_dir
            run_dir = create_run_dir(self.config)
            write_config(self.config, run_dir)
            trades.to_csv(run_dir / "trade_list.csv", index=False)
            import pandas as pd
            pd.DataFrame(trades.attrs.get("skipped_signals", [])).to_csv(run_dir / "skipped_signals.csv", index=False)
            adx_analysis(trades).to_csv(run_dir / "adx_analysis.csv", index=False)
            equity.to_csv(run_dir / "equity_curve.csv", index=False)
            periodic_results(trades, "ME").to_csv(run_dir / "monthly_results.csv", index=False)
            periodic_results(trades, "YE").to_csv(run_dir / "yearly_results.csv", index=False)
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
            write_summary_txt(summary, run_dir)
            write_run_info(self.config, summary, run_dir)
            for warning in save_plots(trades, equity, run_dir / "charts"):
              self.log.emit(f"WARNING: {warning}")
            update_latest(output_root, run_dir)
            self._emit_stage("Saving outputs", 100, len(data), len(data), len(trades), len(trades), 0)
            self._log(f"Completed {len(trades):,} trade pairs")
            self._log(f"Results saved to {run_dir}")
            (run_dir / "log.txt").write_text("\n".join(self._log_lines + ["Backtest completed from GUI worker."]) + "\n")
            self.finished.emit(summary, trades, equity, run_dir)
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
