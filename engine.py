"""Event-driven dual long/short backtesting engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from atr import atr
from config import BacktestConfig, EntryMode, RiskMode, TiePolicy
from strategy import custom_entry_signal
from trade import ExitReason, Position, Side, TradePair


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
        self.atr_values = atr(self.high, self.low, self.close, self.config.atr_period)
        self.active_pairs: list[TradePair] = []
        self.completed_pairs: list[TradePair] = []
        self.next_pair_id = 1
        self.current_equity = config.initial_equity

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
        return atr(self.high, self.low, self.close, self.config.atr_period) * self.config.atr_multiplier

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
        risk = float(self.risk[i])
        stop_distance = self.config.sl_mult * risk
        risk_amount = self.current_equity * self.config.risk_per_leg
        quantity = risk_amount / stop_distance
        entry_fee_rate = self.config.maker_fee if self.config.use_maker_entry else self.config.taker_fee
        long = Position(
            Side.LONG, self.times[i], i, long_entry, risk,
            long_entry - stop_distance, long_entry + self.config.tp_mult * risk,
            quantity, risk_amount, long_entry * quantity, float(self.atr_values[i]),
            fees=long_entry * quantity * entry_fee_rate,
        )
        short = Position(
            Side.SHORT, self.times[i], i, short_entry, risk,
            short_entry + stop_distance, short_entry - self.config.tp_mult * risk,
            quantity, risk_amount, short_entry * quantity, float(self.atr_values[i]),
            fees=short_entry * quantity * entry_fee_rate,
        )
        self.active_pairs.append(TradePair(self.next_pair_id, long, short, self.current_equity))
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
            pos.ambiguous = True
            if self.config.tie_policy == TiePolicy.INTRABAR:
                raise NotImplementedError("Intrabar tie resolution requires lower timeframe data")
            use_tp = self.config.tie_policy == TiePolicy.OPTIMISTIC
        else:
            use_tp = hit_tp
        raw_exit = pos.tp if use_tp else pos.sl
        slip = 1 - self.config.slippage if pos.side == Side.LONG else 1 + self.config.slippage
        self._close_position(pos, i, raw_exit * slip, ExitReason.TP if use_tp else ExitReason.SL)

    def _close_position(self, pos: Position, i: int, exit_price: float, reason: ExitReason) -> None:
        exit_fee_rate = self.config.maker_fee if self.config.use_maker_exit else self.config.taker_fee
        gross = (exit_price - pos.entry_price) * pos.quantity if pos.side == Side.LONG else (pos.entry_price - exit_price) * pos.quantity
        exit_fee = exit_price * pos.quantity * exit_fee_rate
        pos.exit_time = self.times[i]
        pos.exit_index = i
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.gross_pnl = gross
        pos.fees += exit_fee
        pos.net_pnl = pos.gross_pnl - pos.fees
        pos.gross_r = pos.gross_pnl / pos.risk_amount
        pos.net_r = pos.net_pnl / pos.risk_amount

    def _force_close_end(self) -> None:
        last = len(self.data) - 1
        for pair in self.active_pairs:
            for pos in (pair.long, pair.short):
                if pos.is_open:
                    self._close_position(pos, last, self.close[last], ExitReason.END_OF_DATA)

    def _collect_closed_pairs(self, force: bool = False) -> None:
        still_open = []
        for pair in self.active_pairs:
            if force or not pair.is_open:
                pair_net = pair.long.net_pnl + pair.short.net_pnl
                self.current_equity += pair_net
                pair.equity_after_trade = self.current_equity
                self.completed_pairs.append(pair)
            else:
                still_open.append(pair)
        self.active_pairs = still_open

    def results_frame(self) -> pd.DataFrame:
        rows = []
        for pair in self.completed_pairs:
            gross = pair.long.gross_pnl + pair.short.gross_pnl
            fees = pair.long.fees + pair.short.fees
            net = pair.long.net_pnl + pair.short.net_pnl
            gross_r = pair.long.gross_r + pair.short.gross_r
            fee_r = fees / pair.long.risk_amount
            net_r = pair.long.net_r + pair.short.net_r
            exit_i = max(pair.long.exit_index or pair.long.entry_index, pair.short.exit_index or pair.short.entry_index)
            holding = pd.Timestamp(self.times[exit_i]) - pd.Timestamp(pair.long.entry_time)
            rows.append({
                "pair_id": pair.pair_id,
                "entry_time": pair.long.entry_time,
                "entry_price": self.close[pair.long.entry_index],
                "r_distance": pair.long.risk,
                "atr_at_entry": pair.long.atr_at_entry,
                "equity_before_trade": pair.equity_before_trade,
                "long_quantity": pair.long.quantity,
                "long_risk_amount": pair.long.risk_amount,
                "long_entry_notional": pair.long.entry_notional,
                "long_sl": pair.long.sl,
                "long_tp": pair.long.tp,
                "long_exit_time": pair.long.exit_time,
                "long_exit_price": pair.long.exit_price,
                "long_exit_reason": pair.long.exit_reason.value if pair.long.exit_reason else None,
                "long_gross_pnl": pair.long.gross_pnl,
                "long_fees": pair.long.fees,
                "long_net_pnl": pair.long.net_pnl,
                "long_gross_r": pair.long.gross_r,
                "long_net_r": pair.long.net_r,
                "short_quantity": pair.short.quantity,
                "short_risk_amount": pair.short.risk_amount,
                "short_entry_notional": pair.short.entry_notional,
                "short_sl": pair.short.sl,
                "short_tp": pair.short.tp,
                "short_exit_time": pair.short.exit_time,
                "short_exit_price": pair.short.exit_price,
                "short_exit_reason": pair.short.exit_reason.value if pair.short.exit_reason else None,
                "short_gross_pnl": pair.short.gross_pnl,
                "short_fees": pair.short.fees,
                "short_net_pnl": pair.short.net_pnl,
                "short_gross_r": pair.short.gross_r,
                "short_net_r": pair.short.net_r,
                "pair_gross_pnl": gross,
                "pair_total_fees": fees,
                "pair_net_pnl": net,
                "pair_gross_r": gross_r,
                "pair_fee_r": fee_r,
                "pair_net_r": net_r,
                "equity_after_trade": pair.equity_after_trade,
                "holding_bars": exit_i - pair.long.entry_index,
                "holding_hours": holding.total_seconds() / 3600,
                "holding_time": holding,
                "ambiguous_candle": pair.long.ambiguous or pair.short.ambiguous,
            })
        return pd.DataFrame(rows)
