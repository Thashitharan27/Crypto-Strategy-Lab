"""Trade state and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, Enum):
    TP = "TP"
    SL = "SL"
    END_OF_DATA = "END_OF_DATA"


@dataclass
class Position:
    side: Side
    entry_time: object
    entry_index: int
    entry_price: float
    risk: float
    sl: float
    tp: float
    quantity: float
    risk_amount: float
    entry_notional: float
    atr_at_entry: float
    exit_time: Optional[object] = None
    exit_index: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    gross_pnl: float = 0.0
    fees: float = 0.0
    gross_r: float = 0.0
    net_pnl: float = 0.0
    net_r: float = 0.0
    ambiguous: bool = False

    @property
    def is_open(self) -> bool:
        return self.exit_time is None


@dataclass
class TradePair:
    pair_id: int
    long: Position
    short: Position
    equity_before_trade: float
    equity_after_trade: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.long.is_open or self.short.is_open
