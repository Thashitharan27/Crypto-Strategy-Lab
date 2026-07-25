"""Default configuration for the dual long/short backtester."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
class BreakEvenMode(str, Enum):
    ENTRY_PRICE = "ENTRY_PRICE"; COST_ADJUSTED = "COST_ADJUSTED"; R_OFFSET = "R_OFFSET"
class BreakEvenSameCandlePolicy(str, Enum):
    NEXT_CANDLE = "NEXT_CANDLE"; PESSIMISTIC = "PESSIMISTIC"
class AdxFilterMode(str, Enum):
    DISABLED = "Disabled"; MAXIMUM = "ADX <= Maximum"; MINIMUM = "ADX >= Minimum"; RANGE = "Range"
class BBWidthFilterMode(str, Enum):
    DISABLED = "Disabled"; MAXIMUM = "Maximum Width"; MINIMUM = "Minimum Width"; RANGE = "Range"
class DISpreadFilterMode(str, Enum):
    DISABLED = "Disabled"; MAXIMUM = "Maximum Spread"; MINIMUM = "Minimum Spread"; RANGE = "Range"
class TradeDirectionMode(str, Enum):
    BOTH = "BOTH"; LONG_ONLY = "LONG_ONLY"; SHORT_ONLY = "SHORT_ONLY"; BOTH_INDEPENDENT = "BOTH_INDEPENDENT"
class DailyEntryMissedPolicy(str, Enum):
    SKIP_DAY = "SKIP_DAY"; NEXT_AVAILABLE_CANDLE = "NEXT_AVAILABLE_CANDLE"
class TrailApplyTo(str, Enum):
    BOTH = "BOTH"; LONG_ONLY = "LONG_ONLY"; SHORT_ONLY = "SHORT_ONLY"
class TrailIntrabarMode(str, Enum):
    PESSIMISTIC = "PESSIMISTIC"; OPTIMISTIC = "OPTIMISTIC"

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
    trade_direction: TradeDirectionMode = TradeDirectionMode.BOTH
    enable_trailing_profit: bool = False
    trail_activation_r: float = 3.0
    trail_distance_r: float = 1.0
    trail_apply_to: TrailApplyTo = TrailApplyTo.BOTH
    trail_intrabar_mode: TrailIntrabarMode = TrailIntrabarMode.PESSIMISTIC
    enable_both_open_timeout: bool = False
    max_both_open_minutes: int = 480
    enable_be_after_opposite_sl: bool = False
    be_mode: BreakEvenMode = BreakEvenMode.ENTRY_PRICE
    be_offset_r: float = 0.0
    be_same_candle_policy: BreakEvenSameCandlePolicy = BreakEvenSameCandlePolicy.NEXT_CANDLE
    timeout_exit_price: TimeoutExitPrice = TimeoutExitPrice.OPEN
    comparison_timeout_minutes: tuple[int, ...] = ()
    initial_equity: float = 1000.0
    sl_mult: float = 2.0; tp_mult: float = 3.0
    risk_mode: RiskMode = RiskMode.ATR
    fixed_r: float = 100.0; percent_r: float = 0.01
    atr_period: int = 14; atr_multiplier: float = 1.0
    enable_adx_filter: bool = False
    adx_period: int = 14
    adx_filter_mode: AdxFilterMode = AdxFilterMode.DISABLED
    adx_maximum: float = 25.0
    adx_minimum: float = 20.0
    bb_period: int = 20
    bb_stddevs: float = 2.0
    enable_bb_width_filter: bool = False
    bb_width_filter_mode: BBWidthFilterMode = BBWidthFilterMode.DISABLED
    bb_width_maximum: float = 0.03
    bb_width_minimum: float = 0.0
    enable_di_spread_filter: bool = False
    di_spread_filter_mode: DISpreadFilterMode = DISpreadFilterMode.DISABLED
    di_spread_maximum: float = 10.0
    di_spread_minimum: float = 0.0
    risk_per_leg: float = 0.005
    position_sizing_mode: PositionSizingMode = PositionSizingMode.PRICE_RISK
    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED
    entry_interval: int = 1
    enable_daily_entry_schedule: bool = False
    daily_entry_time: str = "00:00"
    daily_entry_timezone: str = "UTC"
    daily_entry_missed_policy: DailyEntryMissedPolicy = DailyEntryMissedPolicy.SKIP_DAY
    maker_fee: float = 0.0002; taker_fee: float = 0.0005
    use_maker_entry: bool = False; use_maker_exit: bool = False
    slippage: float = 0.0001
    tie_policy: TiePolicy = TiePolicy.PESSIMISTIC
    max_active_pairs: int = 1
    run_name: str = ""
    output_run_dir: Optional[Path] = None
    enable_trade_telemetry: bool = True
    save_full_telemetry_csv: bool = True
    save_trade_journey_summary: bool = True
    save_trade_journey_charts: bool = True
    telemetry_interval_minutes: int = 15

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
        if self.trail_activation_r <= 0: raise ValueError("trail_activation_r must be greater than 0")
        if self.trail_distance_r <= 0: raise ValueError("trail_distance_r must be greater than 0")
        if self.adx_period <= 0: raise ValueError("adx_period must be positive")
        if self.adx_maximum < 0 or self.adx_minimum < 0: raise ValueError("ADX thresholds must be non-negative")
        if self.bb_period <= 0: raise ValueError("BB period must be positive")
        if self.bb_stddevs <= 0: raise ValueError("BB standard deviations must be positive")
        if self.bb_width_maximum < 0 or self.bb_width_minimum < 0: raise ValueError("BB width thresholds must be non-negative")
        if self.di_spread_maximum < 0 or self.di_spread_minimum < 0: raise ValueError("DI spread thresholds must be non-negative")
        if self.entry_interval <= 0: raise ValueError("entry_interval must be positive")
        if self.max_active_pairs <= 0: raise ValueError("max_active_pairs must be positive")
        if self.fixed_r <= 0 or self.percent_r <= 0: raise ValueError("risk distances must be positive")
        if self.maker_fee < 0 or self.taker_fee < 0: raise ValueError("fee rates must be non-negative")
        if self.slippage < 0: raise ValueError("slippage must be non-negative")
        if self.max_effective_leverage_per_leg is not None and self.max_effective_leverage_per_leg <= 0: raise ValueError("max leverage per leg must be positive")
        if self.max_combined_effective_leverage is not None and self.max_combined_effective_leverage <= 0: raise ValueError("max combined leverage must be positive")
        if self.enable_both_open_timeout and self.max_both_open_minutes <= 0: raise ValueError("max_both_open_minutes must be > 0 when both-open timeout is enabled")
        if self.be_offset_r < 0: raise ValueError("be_offset_r must be >= 0")
        if isinstance(self.intrabar_missing_policy, str): object.__setattr__(self, "intrabar_missing_policy", IntrabarMissingPolicy(self.intrabar_missing_policy))
        if isinstance(self.position_sizing_mode, str): object.__setattr__(self, "position_sizing_mode", PositionSizingMode(self.position_sizing_mode))
        if isinstance(self.timeout_exit_price, str): object.__setattr__(self, "timeout_exit_price", TimeoutExitPrice(self.timeout_exit_price))
        if isinstance(self.be_mode, str): object.__setattr__(self, "be_mode", BreakEvenMode(self.be_mode))
        if isinstance(self.be_same_candle_policy, str): object.__setattr__(self, "be_same_candle_policy", BreakEvenSameCandlePolicy(self.be_same_candle_policy))
        if isinstance(self.adx_filter_mode, str): object.__setattr__(self, "adx_filter_mode", AdxFilterMode(self.adx_filter_mode))
        if isinstance(self.bb_width_filter_mode, str): object.__setattr__(self, "bb_width_filter_mode", BBWidthFilterMode(self.bb_width_filter_mode))
        if isinstance(self.di_spread_filter_mode, str): object.__setattr__(self, "di_spread_filter_mode", DISpreadFilterMode(self.di_spread_filter_mode))
        if isinstance(self.trade_direction, str): object.__setattr__(self, "trade_direction", TradeDirectionMode(self.trade_direction))
        if isinstance(self.trail_apply_to, str): object.__setattr__(self, "trail_apply_to", TrailApplyTo(self.trail_apply_to))
        if isinstance(self.trail_intrabar_mode, str): object.__setattr__(self, "trail_intrabar_mode", TrailIntrabarMode(self.trail_intrabar_mode))
        if isinstance(self.daily_entry_missed_policy, str): object.__setattr__(self, "daily_entry_missed_policy", DailyEntryMissedPolicy(self.daily_entry_missed_policy))
        try:
            hh, mm = [int(part) for part in str(self.daily_entry_time).split(":", 1)]
            if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
        except Exception as exc:
            raise ValueError("daily_entry_time must be HH:MM in 24-hour time") from exc
        if (hh * 60 + mm) % self.strategy_timeframe_minutes != 0:
            raise ValueError("daily_entry_time must align to the strategy timeframe")
        try:
            ZoneInfo(self.daily_entry_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("daily_entry_timezone must be a valid IANA timezone") from exc
        if self.telemetry_interval_minutes <= 0: raise ValueError("telemetry interval must be > 0")
        if self.telemetry_interval_minutes % self.strategy_timeframe_minutes != 0: raise ValueError("telemetry interval must be a multiple of the strategy timeframe")
        if self.enable_trade_telemetry and (self.strategy_timeframe_minutes != 15 or self.telemetry_interval_minutes != 15): raise ValueError("only 15-minute telemetry is currently supported when the strategy timeframe is 15 minutes")
        if isinstance(self.comparison_timeout_minutes, list): object.__setattr__(self, "comparison_timeout_minutes", tuple(int(v) for v in self.comparison_timeout_minutes))
