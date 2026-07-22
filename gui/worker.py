"""QThread worker that runs the existing backtesting pipeline."""
from __future__ import annotations

import json, traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from config import BacktestConfig
from engine import BacktestEngine
from loader import load_ohlcv_csv
from plots import save_plots
from statistics import equity_curve, summarize

class BacktestWorker(QObject):
    status = Signal(str, int)
    log = Signal(str)
    finished = Signal(dict, object, object, object)
    failed = Signal(str, str)

    def __init__(self, config: BacktestConfig):
        super().__init__(); self.config = config; self._cancel = False

    @Slot()
    def cancel(self) -> None:
        self._cancel = True

    def _check(self):
        if self._cancel: raise RuntimeError("Backtest cancelled by user.")

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("Loading CSV...", 5)
            data = load_ohlcv_csv(str(self.config.input_csv), self.config.timestamp_unit)
            self.log.emit(f"Loaded {len(data):,} candles")
            self.log.emit(f"Period: {data['timestamp'].min()} to {data['timestamp'].max()}")
            self._check(); self.status.emit("Validating data...", 15)
            self._check(); self.status.emit("Calculating ATR...", 25)
            self.log.emit(f"Running {self.config.risk_mode.value}, ATR({self.config.atr_period}), multiplier {self.config.atr_multiplier}")
            self.status.emit("Running backtest...", 45)
            trades = BacktestEngine(data, self.config).run()
            self._check(); self.status.emit("Creating statistics...", 70)
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            trades.to_csv(self.config.output_dir / "trade_list.csv", index=False)
            equity = equity_curve(trades, self.config.initial_equity)
            equity.to_csv(self.config.output_dir / "equity_curve.csv", index=False)
            summary = summarize(trades, self.config.initial_equity)
            (self.config.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
            self._check(); self.status.emit("Saving charts...", 90)
            save_plots(trades, equity, self.config.output_dir)
            self.status.emit("Completed", 100)
            self.log.emit(f"Completed {len(trades):,} trade pairs")
            self.log.emit(f"Results saved to {self.config.output_dir}")
            self.finished.emit(summary, trades, equity, self.config.output_dir)
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
