"""Default configuration for the dual long/short backtester."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

class RiskMode(str, Enum):
    FIXED = "FIXED"; PERCENT = "PERCENT"; ATR = "ATR"
class EntryMode(str, Enum):
    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"; CUSTOM = "CUSTOM"
class TiePolicy(str, Enum):
    PESSIMISTIC = "PESSIMISTIC"; OPTIMISTIC = "OPTIMISTIC"; INTRABAR = "INTRABAR"
class IntrabarMissingPolicy(str, Enum):
    ERROR = "ERROR"; WARN_AND_USE_15M = "WARN_AND_USE_15M"; WARN_AND_CONTINUE = "WARN_AND_CONTINUE"
class PositionSizingMode(str, Enum):
    PRICE_RISK = "PRICE_RISK"; ALL_IN_STOP_RISK = "ALL_IN_STOP_RISK"
class TimeoutExitPrice(str, Enum):
    OPEN = "OPEN"

@dataclass(frozen=True)
class BacktestConfig:
    input_csv: Path = Path("data/binance_ohlcv.csv")
    strategy_csv: Path = Path("data/BTCUSDT_15m.csv")
    intrabar_csv: Optional[Path] = Path("data/BTCUSDT_1m.csv")
    output_dir: Path = Path("output")
    timestamp_unit: Optional[str] = "ms"
    strategy_timeframe_minutes: int = 15
    intrabar_timeframe_minutes: int = 1
    use_intrabar_data: bool = True
    data_start_date: Optional[str] = None
    trading_start_date: Optional[str] = None
    trading_end_date: Optional[str] = None
    max_effective_leverage_per_leg: Optional[float] = None
    max_combined_effective_leverage: Optional[float] = None
    intrabar_missing_policy: IntrabarMissingPolicy = IntrabarMissingPolicy.WARN_AND_USE_15M
    zero_cost_comparison: bool = False
    enable_both_open_timeout: bool = False
    max_both_open_minutes: int = 480
    timeout_exit_price: TimeoutExitPrice = TimeoutExitPrice.OPEN
    comparison_timeout_minutes: tuple[int, ...] = ()
    initial_equity: float = 1000.0
    sl_mult: float = 2.0; tp_mult: float = 3.0
    risk_mode: RiskMode = RiskMode.ATR
    fixed_r: float = 100.0; percent_r: float = 0.01
    atr_period: int = 14; atr_multiplier: float = 1.0
    risk_per_leg: float = 0.005
    position_sizing_mode: PositionSizingMode = PositionSizingMode.PRICE_RISK
    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED
    entry_interval: int = 1
    maker_fee: float = 0.0002; taker_fee: float = 0.0005
    use_maker_entry: bool = False; use_maker_exit: bool = False
    slippage: float = 0.0001
    tie_policy: TiePolicy = TiePolicy.PESSIMISTIC
    max_active_pairs: int = 1
    run_name: str = ""
    output_run_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.input_csv != Path("data/binance_ohlcv.csv") and self.strategy_csv == Path("data/BTCUSDT_15m.csv"):
            object.__setattr__(self, "strategy_csv", self.input_csv)
        if self.initial_equity <= 0: raise ValueError("initial_equity must be positive")
        if self.strategy_timeframe_minutes <= 0: raise ValueError("strategy_timeframe_minutes must be positive")
        if self.intrabar_timeframe_minutes <= 0: raise ValueError("intrabar_timeframe_minutes must be positive")
        if self.use_intrabar_data and self.intrabar_timeframe_minutes >= self.strategy_timeframe_minutes: raise ValueError("intrabar timeframe must be less than strategy timeframe")
        if self.sl_mult <= 0 or self.tp_mult <= 0: raise ValueError("SL and TP multiples must be positive")
        if not 0 < self.risk_per_leg < 1: raise ValueError("risk_per_leg must be between 0 and 1")
        if self.atr_period <= 0: raise ValueError("atr_period must be positive")
        if self.atr_multiplier <= 0: raise ValueError("atr_multiplier must be positive")
        if self.entry_interval <= 0: raise ValueError("entry_interval must be positive")
        if self.max_active_pairs <= 0: raise ValueError("max_active_pairs must be positive")
        if self.fixed_r <= 0 or self.percent_r <= 0: raise ValueError("risk distances must be positive")
        if self.maker_fee < 0 or self.taker_fee < 0: raise ValueError("fee rates must be non-negative")
        if self.slippage < 0: raise ValueError("slippage must be non-negative")
        if self.max_effective_leverage_per_leg is not None and self.max_effective_leverage_per_leg <= 0: raise ValueError("max leverage per leg must be positive")
        if self.max_combined_effective_leverage is not None and self.max_combined_effective_leverage <= 0: raise ValueError("max combined leverage must be positive")
        if self.enable_both_open_timeout and self.max_both_open_minutes <= 0: raise ValueError("max_both_open_minutes must be > 0 when both-open timeout is enabled")
        if isinstance(self.intrabar_missing_policy, str): object.__setattr__(self, "intrabar_missing_policy", IntrabarMissingPolicy(self.intrabar_missing_policy))
        if isinstance(self.position_sizing_mode, str): object.__setattr__(self, "position_sizing_mode", PositionSizingMode(self.position_sizing_mode))
        if isinstance(self.timeout_exit_price, str): object.__setattr__(self, "timeout_exit_price", TimeoutExitPrice(self.timeout_exit_price))
        if isinstance(self.comparison_timeout_minutes, list): object.__setattr__(self, "comparison_timeout_minutes", tuple(int(v) for v in self.comparison_timeout_minutes))
