"""Trade state and result models."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class Side(str, Enum): LONG="LONG"; SHORT="SHORT"
class ExitReason(str, Enum): TP="TP"; SL="SL"; BOTH_OPEN_TIMEOUT="BOTH_OPEN_TIMEOUT"; END_OF_DATA="END_OF_DATA"
class ExitSource(str, Enum): INTRABAR="1M_INTRABAR"; FALLBACK_15M="15M_FALLBACK"; END_OF_DATA="END_OF_DATA"

@dataclass
class Position:
    side: Side; entry_time: object; entry_index: int; entry_price: float; risk: float; sl: float; tp: float; quantity: float; risk_amount: float; entry_notional: float; atr_at_entry: float
    uncapped_quantity: float = 0.0; effective_leverage: float = 0.0; entry_fee: float = 0.0; exit_fee: float = 0.0
    exit_time: Optional[object] = None; exit_index: Optional[int] = None; exit_price: Optional[float] = None; exit_reason: Optional[ExitReason] = None; exit_source: Optional[ExitSource] = None
    gross_pnl: float = 0.0; fees: float = 0.0; gross_r: float = 0.0; net_pnl: float = 0.0; net_r: float = 0.0; price_r: float = 0.0; ambiguous: bool = False; missing_intrabar_data: bool = False; fallback_reason: Optional[str] = None
    @property
    def is_open(self) -> bool: return self.exit_time is None

@dataclass
class TradePair:
    pair_id: int; long: Position; short: Position; equity_before_trade: float; strategy_candle_open_time: object; strategy_entry_time: object; strategy_entry_price: float; leverage_capped: bool = False; equity_after_trade: Optional[float] = None; both_open_timeout_triggered: bool = False; timeout_minutes: Optional[int] = None; timeout_exit_time: Optional[object] = None
    @property
    def is_open(self) -> bool: return self.long.is_open or self.short.is_open
