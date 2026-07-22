"""Default configuration for the dual long/short backtester."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class RiskMode(str, Enum):
    FIXED = "FIXED"
    PERCENT = "PERCENT"
    ATR = "ATR"


class EntryMode(str, Enum):
    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"
    EVERY_N_CANDLES = "EVERY_N_CANDLES"
    CUSTOM = "CUSTOM"


class TiePolicy(str, Enum):
    PESSIMISTIC = "PESSIMISTIC"
    OPTIMISTIC = "OPTIMISTIC"
    INTRABAR = "INTRABAR"


@dataclass(frozen=True)
class BacktestConfig:
    input_csv: Path = Path("data/binance_ohlcv.csv")
    output_dir: Path = Path("output")
    timestamp_unit: Optional[str] = "ms"
    initial_equity: float = 1000.0
    sl_mult: float = 2.0
    tp_mult: float = 3.0
    risk_mode: RiskMode = RiskMode.ATR
    fixed_r: float = 100.0
    percent_r: float = 0.01
    atr_period: int = 14
    atr_multiplier: float = 1.0
    risk_per_leg: float = 0.005
    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED
    entry_interval: int = 1
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    use_maker_entry: bool = False
    use_maker_exit: bool = False
    slippage: float = 0.0001
    tie_policy: TiePolicy = TiePolicy.PESSIMISTIC
    max_active_pairs: int = 1

    def __post_init__(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if self.sl_mult <= 0 or self.tp_mult <= 0:
            raise ValueError("SL and TP multiples must be positive")
        if not 0 < self.risk_per_leg < 1:
            raise ValueError("risk_per_leg must be between 0 and 1")
        if self.atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if self.atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive")
        if self.entry_interval <= 0:
            raise ValueError("entry_interval must be positive")
        if self.max_active_pairs <= 0:
            raise ValueError("max_active_pairs must be positive")
        if self.fixed_r <= 0 or self.percent_r <= 0:
            raise ValueError("risk distances must be positive")
        if self.maker_fee < 0 or self.taker_fee < 0:
            raise ValueError("fee rates must be non-negative")
        if self.slippage < 0:
            raise ValueError("slippage must be non-negative")
