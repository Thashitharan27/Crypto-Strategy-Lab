"""Trade state and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Position:
    side: Side
    entry_time: object
    entry_index: int
    entry_price: float
    risk: float
    sl: float
    tp: float
    exit_time: Optional[object] = None
    exit_index: Optional[int] = None
    exit_price: Optional[float] = None
    result_r: Optional[float] = None
    gross_pnl: Optional[float] = None
    fees: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_time is None


@dataclass
class TradePair:
    pair_id: int
    long: Position
    short: Position

    @property
    def is_open(self) -> bool:
        return self.long.is_open or self.short.is_open
