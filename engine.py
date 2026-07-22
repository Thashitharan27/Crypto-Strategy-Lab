"""Event-driven dual long/short backtesting engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from atr import atr
from config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from strategy import custom_entry_signal
from trade import Position, Side, TradePair


class BacktestEngine:
    def __init__(self, data: pd.DataFrame, config: BacktestConfig):
        self.data = data
        self.config = config
        self.high = data["high"].to_numpy(float)
        self.low = data["low"].to_numpy(float)
        self.close = data["close"].to_numpy(float)
        self.open = data["open"].to_numpy(float)
        self.times = data["timestamp"].to_numpy()
        self.risk = self._risk_array()
        self.active_pairs: list[TradePair] = []
        self.completed_pairs: list[TradePair] = []
        self.next_pair_id = 1

    def run(self) -> pd.DataFrame:
        for i in range(len(self.data)):
            self._update_positions(i)
            self._collect_closed_pairs()
            if self._should_enter(i):
                self._open_pair(i)
        self._force_close_end()
        self._collect_closed_pairs(force=True)
        return self.results_frame()

    def _risk_array(self) -> np.ndarray:
        if self.config.risk_mode == RiskMode.FIXED:
            return np.full(len(self.data), self.config.fixed_r, dtype=float)
        if self.config.risk_mode == RiskMode.PERCENT:
            return self.close * self.config.percent_r
        return atr(self.high, self.low, self.close, self.config.atr_period)

    def _should_enter(self, i: int) -> bool:
        if not np.isfinite(self.risk[i]) or self.risk[i] <= 0:
            return False
        if len(self.active_pairs) >= self.config.max_active_pairs:
            return False
        mode = self.config.entry_mode
        if mode == EntryMode.WAIT_UNTIL_CLOSED:
            return not self.active_pairs
        if mode == EntryMode.EVERY_N_CANDLES:
            return i % self.config.entry_interval == 0
        if mode == EntryMode.CUSTOM:
            arrays = {"open": self.open, "high": self.high, "low": self.low, "close": self.close}
            return custom_entry_signal(i, arrays, len(self.active_pairs))
        return False

    def _open_pair(self, i: int) -> None:
        raw_entry = self.close[i]
        long_entry = raw_entry * (1 + self.config.slippage)
        short_entry = raw_entry * (1 - self.config.slippage)
        risk = self.risk[i]
        entry_fee_rate = self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee
        long = Position(Side.LONG, self.times[i], i, long_entry, risk,
                        long_entry - self.config.sl_mult * risk,
                        long_entry + self.config.tp_mult * risk,
                        fees=long_entry * entry_fee_rate)
        short = Position(Side.SHORT, self.times[i], i, short_entry, risk,
                         short_entry + self.config.sl_mult * risk,
                         short_entry - self.config.tp_mult * risk,
                         fees=short_entry * entry_fee_rate)
        self.active_pairs.append(TradePair(self.next_pair_id, long, short))
        self.next_pair_id += 1

    def _update_positions(self, i: int) -> None:
        for pair in self.active_pairs:
            for pos in (pair.long, pair.short):
                if pos.is_open and i > pos.entry_index:
                    self._maybe_exit(pos, i)

    def _maybe_exit(self, pos: Position, i: int) -> None:
        hit_tp = self.high[i] >= pos.tp if pos.side == Side.LONG else self.low[i] <= pos.tp
        hit_sl = self.low[i] <= pos.sl if pos.side == Side.LONG else self.high[i] >= pos.sl
        if not (hit_tp or hit_sl):
            return
        if hit_tp and hit_sl:
            if self.config.tie_policy == TiePolicy.INTRABAR:
                raise NotImplementedError("Intrabar tie resolution requires lower timeframe data")
            use_tp = self.config.tie_policy == TiePolicy.OPTIMISTIC
        else:
            use_tp = hit_tp
        raw_exit = pos.tp if use_tp else pos.sl
        slip = 1 - self.config.slippage if pos.side == Side.LONG else 1 + self.config.slippage
        self._close_position(pos, i, raw_exit * slip)

    def _close_position(self, pos: Position, i: int, exit_price: float) -> None:
        exit_fee_rate = self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        gross = exit_price - pos.entry_price if pos.side == Side.LONG else pos.entry_price - exit_price
        pos.exit_time = self.times[i]
        pos.exit_index = i
        pos.exit_price = exit_price
        pos.gross_pnl = gross
        pos.result_r = gross / pos.risk
        pos.fees += exit_price * exit_fee_rate

    def _force_close_end(self) -> None:
        last = len(self.data) - 1
        for pair in self.active_pairs:
            for pos in (pair.long, pair.short):
                if pos.is_open:
                    self._close_position(pos, last, self.close[last])

    def _collect_closed_pairs(self, force: bool = False) -> None:
        still_open = []
        for pair in self.active_pairs:
            if force or not pair.is_open:
                self.completed_pairs.append(pair)
            else:
                still_open.append(pair)
        self.active_pairs = still_open

    def results_frame(self) -> pd.DataFrame:
        rows = []
        for pair in self.completed_pairs:
            fees = pair.long.fees + pair.short.fees
            gross = (pair.long.gross_pnl or 0) + (pair.short.gross_pnl or 0)
            net = gross - fees
            exit_i = max(pair.long.exit_index or 0, pair.short.exit_index or 0)
            rows.append({
                "pair_id": pair.pair_id, "entry_time": pair.long.entry_time,
                "entry_price": pair.long.entry_price, "long_exit_time": pair.long.exit_time,
                "long_exit_price": pair.long.exit_price, "short_exit_time": pair.short.exit_time,
                "short_exit_price": pair.short.exit_price, "long_result_r": pair.long.result_r,
                "short_result_r": pair.short.result_r, "gross_pnl": gross, "fees": fees,
                "net_pnl": net, "net_r": (pair.long.result_r or 0) + (pair.short.result_r or 0),
                "holding_time": self.times[exit_i] - pair.long.entry_time,
            })
        return pd.DataFrame(rows)
