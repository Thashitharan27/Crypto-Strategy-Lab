"""Current configuration contract for Crypto Strategy Lab."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles, normalize_profiles


class RiskMode(str, Enum):
    FIXED = "FIXED"; PERCENT = "PERCENT"; ATR = "ATR"
class EntryMode(str, Enum):
    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"; CUSTOM = "CUSTOM"; VWAP_VOLUME_BREAKOUT = "VWAP_VOLUME_BREAKOUT"
class VWAPConfirmationMode(str, Enum):
    IMMEDIATE = "IMMEDIATE"; RETEST = "RETEST"
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
class DIExecutionMode(str, Enum):
    BOTH_SIDES = "BOTH_SIDES"; PREFERRED_SIDE_ONLY = "PREFERRED_SIDE_ONLY"
class DailyEntryMissedPolicy(str, Enum):
    SKIP_DAY = "SKIP_DAY"; NEXT_AVAILABLE_CANDLE = "NEXT_AVAILABLE_CANDLE"
class TrailApplyTo(str, Enum):
    BOTH = "BOTH"; LONG_ONLY = "LONG_ONLY"; SHORT_ONLY = "SHORT_ONLY"
class TrailIntrabarMode(str, Enum):
    PESSIMISTIC = "PESSIMISTIC"; OPTIMISTIC = "OPTIMISTIC"
class TrailActivationTrigger(str, Enum):
    PRICE_REACHES_R = "PRICE_REACHES_R"; AFTER_TP1 = "AFTER_TP1"; AFTER_SL1 = "AFTER_SL1"; AFTER_TP1_OR_SL1 = "AFTER_TP1_OR_SL1"
class AfterTP1StopMode(str, Enum):
    KEEP_ORIGINAL_SL = "KEEP_ORIGINAL_SL"; MOVE_TO_ENTRY = "MOVE_TO_ENTRY"; MOVE_TO_R_OFFSET = "MOVE_TO_R_OFFSET"
class TP2ExitMode(str, Enum):
    FIXED_TP2 = "FIXED_TP2"; TRAILING_AFTER_TP1 = "TRAILING_AFTER_TP1"
class EntryTimingMode(str, Enum):
    CURRENT = "CURRENT"; RANDOM_AFTER_PAIR_CLOSE = "RANDOM_AFTER_PAIR_CLOSE"
class RandomEntryStartMode(str, Enum):
    NEXT_CANDLE_AFTER_PAIR_CLOSE = "NEXT_CANDLE_AFTER_PAIR_CLOSE"; NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE = "NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE"


@dataclass(frozen=True)
class BacktestConfig:
    """Only settings belonging to the current GUI/Strategy Profile contract.

    Retired global strategy switches are deliberately not dataclass fields, so
    old JSON or direct constructor arguments cannot reactivate them. A small set
    of fixed class invariants remains temporarily while dead engine branches are
    removed; these values are not serialized or configurable.
    """

    input_csv: Path = Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv")
    strategy_csv: Path = Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv")
    intrabar_csv: Optional[Path] = Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_1m.csv")
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

    strategy_profile_run_mode: str = "COMBINED_SHARED_CAPITAL"
    strategy_profiles: dict[str, StrategyProfile] = field(default_factory=default_profiles)

    initial_equity: float = 1000.0
    risk_mode: RiskMode = RiskMode.ATR
    fixed_r: float = 100.0
    percent_r: float = 0.01
    atr_period: int = 14
    atr_multiplier: float = 1.0
    risk_per_leg: float = 0.005
    adx_period: int = 14
    bb_period: int = 20
    bb_stddevs: float = 2.0

    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED
    entry_interval: int = 1
    enable_di_direction_selection: bool = True
    enable_di_pressure_analysis: bool = True
    di_pressure_lookback: int = 3

    enable_support_resistance_analysis: bool = False
    sr_pivot_left: int = 5
    sr_pivot_right: int = 5
    sr_lookback_bars: int = 200
    sr_zone_width_atr: float = 0.5
    sr_near_distance_atr: float = 0.75
    enable_sr_hold_confirmation: bool = False
    sr_hold_confirmation_bars: int = 3
    sr_hold_confirmation_atr: float = 0.25
    sr_break_tolerance_atr: float = 0.25
    sr_break_basis: str = "CLOSE"
    sr_filter_mode: str = "ANALYSIS_ONLY"
    sr_long_avoid_near_resistance: bool = False
    sr_long_require_near_support: bool = False
    sr_long_block_broken_support: bool = False
    sr_long_min_room_to_resistance_atr: float = 0.0
    sr_short_avoid_near_support: bool = False
    sr_short_require_near_resistance: bool = False
    sr_short_block_broken_resistance: bool = False
    sr_short_min_room_to_support_atr: float = 0.0

    market_regime_method: str = "ASSET_RETURN"
    structural_regime_sma_days: int = 200
    structural_regime_slope_lookback_days: int = 30
    structural_regime_benchmark_csv: Optional[Path] = None
    bull_regime_lookback_days: int = 90
    bull_regime_return_threshold: float = 0.20

    enable_daily_entry_schedule: bool = False
    daily_entry_time: str = "00:00"
    daily_entry_timezone: str = "UTC"
    daily_entry_missed_policy: DailyEntryMissedPolicy = DailyEntryMissedPolicy.SKIP_DAY

    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    use_maker_entry: bool = False
    use_maker_exit: bool = False
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
    enable_indicator_lifecycle_analysis: bool = True
    lifecycle_phases: int = 4
    lifecycle_early_checkpoints: tuple[int, ...] = (15, 30, 60)
    lifecycle_minimum_bucket_sample: int = 20
    create_lifecycle_charts: bool = True
    lifecycle_flat_pattern_threshold_pct: float = 5.0
    save_feature_analysis_reports: bool = True
    save_indicator_analysis_reports: bool = True
    create_standard_charts: bool = True

    # Fixed current-engine invariants. These are intentionally NOT config fields.
    enable_strategy_profiles: ClassVar[bool] = True
    trade_direction: ClassVar[TradeDirectionMode] = TradeDirectionMode.BOTH
    enable_di_direction_sizing: ClassVar[bool] = True
    di_execution_mode: ClassVar[DIExecutionMode] = DIExecutionMode.PREFERRED_SIDE_ONLY
    flip_filtered_di_direction: ClassVar[bool] = False
    di_direction_minimum_spread: ClassVar[float] = 0.0
    di_direction_long_minimum_spread: ClassVar[float] = 0.0
    di_direction_short_minimum_spread: ClassVar[float] = 0.0
    position_sizing_mode: ClassVar[PositionSizingMode] = PositionSizingMode.PRICE_RISK

    sl_mult: ClassVar[float] = 2.0
    tp_mult: ClassVar[float] = 3.0
    enable_partial_take_profit: ClassVar[bool] = False
    enable_partial_stop_loss: ClassVar[bool] = False
    sl1_r: ClassVar[float] = 0.5
    sl1_close_pct: ClassVar[float] = 50.0
    sl2_r: ClassVar[float] = 2.0
    tp1_r: ClassVar[float] = 1.0
    tp1_close_pct: ClassVar[float] = 50.0
    tp2_r: ClassVar[float] = 2.0
    tp2_close_pct: ClassVar[float] = 50.0
    stop_loss_r: ClassVar[float] = 2.0
    after_tp1_stop_mode: ClassVar[AfterTP1StopMode] = AfterTP1StopMode.KEEP_ORIGINAL_SL
    after_tp1_stop_offset_r: ClassVar[float] = 0.0
    tp2_exit_mode: ClassVar[TP2ExitMode] = TP2ExitMode.FIXED_TP2
    enable_trailing_profit: ClassVar[bool] = False
    trail_activation_r: ClassVar[float] = 3.0
    trail_activation_trigger: ClassVar[TrailActivationTrigger] = TrailActivationTrigger.PRICE_REACHES_R
    trail_distance_r: ClassVar[float] = 1.0
    trail_apply_to: ClassVar[TrailApplyTo] = TrailApplyTo.BOTH
    trail_intrabar_mode: ClassVar[TrailIntrabarMode] = TrailIntrabarMode.PESSIMISTIC
    enable_be_after_opposite_sl: ClassVar[bool] = False
    be_mode: ClassVar[BreakEvenMode] = BreakEvenMode.ENTRY_PRICE
    be_offset_r: ClassVar[float] = 0.0
    be_same_candle_policy: ClassVar[BreakEvenSameCandlePolicy] = BreakEvenSameCandlePolicy.NEXT_CANDLE

    enable_both_open_timeout: ClassVar[bool] = False
    max_both_open_minutes: ClassVar[int] = 480
    timeout_exit_price: ClassVar[TimeoutExitPrice] = TimeoutExitPrice.OPEN
    comparison_timeout_minutes: ClassVar[tuple[int, ...]] = ()
    enable_remaining_leg_timeout_after_first_sl: ClassVar[bool] = False
    remaining_leg_timeout_after_first_sl_minutes: ClassVar[int] = 240
    enable_remaining_leg_timeout_profit_extension: ClassVar[bool] = False
    remaining_leg_timeout_profit_threshold_r: ClassVar[float] = 10.0
    enable_remaining_leg_checkpoint_score_extension: ClassVar[bool] = False
    checkpoint_score_use_profit: ClassVar[bool] = True
    checkpoint_score_min_profit_r: ClassVar[float] = 0.85
    checkpoint_score_use_atr_pct: ClassVar[bool] = True
    checkpoint_score_max_atr_pct: ClassVar[float] = 0.08
    checkpoint_score_use_directional_di: ClassVar[bool] = True
    checkpoint_score_min_directional_di: ClassVar[float] = 2.3
    checkpoint_score_use_bb_width_pct: ClassVar[bool] = True
    checkpoint_score_max_bb_width_pct: ClassVar[float] = 0.349
    checkpoint_score_min_conditions: ClassVar[int] = 3
    enable_first_sl_survivor_partial_close: ClassVar[bool] = False
    first_sl_survivor_partial_close_pct: ClassVar[float] = 25.0
    enable_checkpoint_zero_score_confirmation: ClassVar[bool] = False
    checkpoint_zero_score_confirmations_required: ClassVar[int] = 2
    checkpoint_zero_score_recheck_minutes: ClassVar[int] = 120
    enable_reentry_gate_after_remaining_leg_timeout: ClassVar[bool] = False

    enable_adx_filter: ClassVar[bool] = False
    adx_filter_mode: ClassVar[AdxFilterMode] = AdxFilterMode.DISABLED
    adx_maximum: ClassVar[float] = 25.0
    adx_minimum: ClassVar[float] = 20.0
    enable_bb_width_filter: ClassVar[bool] = False
    bb_width_filter_mode: ClassVar[BBWidthFilterMode] = BBWidthFilterMode.DISABLED
    bb_width_maximum: ClassVar[float] = 0.03
    bb_width_minimum: ClassVar[float] = 0.012
    enable_di_spread_filter: ClassVar[bool] = False
    di_spread_filter_mode: ClassVar[DISpreadFilterMode] = DISpreadFilterMode.DISABLED
    di_spread_maximum: ClassVar[float] = 10.0
    di_spread_minimum: ClassVar[float] = 0.0
    enable_skip_monday_entries: ClassVar[bool] = False
    skip_monday_timezone: ClassVar[str] = "UTC"

    enable_random_entry: ClassVar[bool] = False
    entry_timing_mode: ClassVar[EntryTimingMode] = EntryTimingMode.CURRENT
    random_entry_probability: ClassVar[float] = 0.5
    random_seed: ClassVar[int] = 42
    random_entry_start_mode: ClassVar[RandomEntryStartMode] = RandomEntryStartMode.NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE
    randomize_first_entry: ClassVar[bool] = True
    max_random_wait_candles: ClassVar[int] = 0
    enable_random_entry_batch: ClassVar[bool] = False
    random_seed_start: ClassVar[int] = 1
    random_seed_count: ClassVar[int] = 100
    enable_coin_flip_sizing: ClassVar[bool] = False
    coin_flip_seed: ClassVar[int] = 42
    coin_flip_large_multiplier: ClassVar[float] = 3.0
    coin_flip_small_multiplier: ClassVar[float] = 1.0

    vwap_breakout_lookback_hours: ClassVar[float] = 4.0
    vwap_volume_lookback: ClassVar[int] = 20
    vwap_volume_multiplier: ClassVar[float] = 1.5
    vwap_slope_lookback: ClassVar[int] = 1
    vwap_atr_pct_minimum: ClassVar[float] = 0.0
    vwap_atr_pct_maximum: ClassVar[float] = 1.0
    vwap_confirmation_mode: ClassVar[VWAPConfirmationMode] = VWAPConfirmationMode.IMMEDIATE
    vwap_retest_window_candles: ClassVar[int] = 4
    vwap_retest_tolerance_atr: ClassVar[float] = 0.25

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_profiles", normalize_profiles(self.strategy_profiles))
        if self.strategy_profile_run_mode not in ("ISOLATED_PROFILES", "COMBINED_SHARED_CAPITAL", "BOTH"):
            raise ValueError("invalid strategy_profile_run_mode")
        if self.input_csv != Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv") and self.strategy_csv == Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv"):
            object.__setattr__(self, "strategy_csv", self.input_csv)
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if self.strategy_timeframe_minutes <= 0 or self.intrabar_timeframe_minutes <= 0:
            raise ValueError("timeframes must be positive")
        if self.use_intrabar_data and self.intrabar_timeframe_minutes >= self.strategy_timeframe_minutes:
            raise ValueError("intrabar timeframe must be less than strategy timeframe")
        if not 0 < self.risk_per_leg < 1:
            raise ValueError("risk_per_leg must be between 0 and 1")
        if self.atr_period <= 0 or self.atr_multiplier <= 0:
            raise ValueError("ATR settings must be positive")
        if self.adx_period <= 0 or self.bb_period <= 0 or self.bb_stddevs <= 0:
            raise ValueError("indicator periods/settings must be positive")
        if self.entry_interval <= 0 or self.max_active_pairs <= 0:
            raise ValueError("entry_interval and max_active_pairs must be positive")
        if self.fixed_r <= 0 or self.percent_r <= 0:
            raise ValueError("risk distances must be positive")
        if self.maker_fee < 0 or self.taker_fee < 0 or self.slippage < 0:
            raise ValueError("fees and slippage must be non-negative")
        if self.max_effective_leverage_per_leg is not None and self.max_effective_leverage_per_leg <= 0:
            raise ValueError("max leverage per trade must be positive")
        if self.max_combined_effective_leverage is not None and self.max_combined_effective_leverage <= 0:
            raise ValueError("max portfolio leverage must be positive")
        if not 1 <= self.di_pressure_lookback <= 100:
            raise ValueError("di_pressure_lookback must be between 1 and 100")
        if self.market_regime_method not in ("ASSET_RETURN", "BTC_STRUCTURAL", "ASSET_STRUCTURAL"):
            raise ValueError("invalid market_regime_method")
        if self.structural_regime_sma_days < 2 or self.structural_regime_slope_lookback_days < 1:
            raise ValueError("structural regime periods are invalid")
        if self.bull_regime_lookback_days <= 0 or self.bull_regime_return_threshold <= -1:
            raise ValueError("asset-return regime settings are invalid")
        if self.sr_pivot_left < 1 or self.sr_pivot_right < 1 or self.sr_lookback_bars < 1:
            raise ValueError("support/resistance lookbacks must be positive")
        if self.sr_zone_width_atr < 0 or self.sr_near_distance_atr < 0 or self.sr_hold_confirmation_atr < 0 or self.sr_break_tolerance_atr < 0:
            raise ValueError("support/resistance ATR distances must be non-negative")
        if self.sr_filter_mode not in ("ANALYSIS_ONLY", "APPLY_ENTRY_RULES"):
            raise ValueError("invalid sr_filter_mode")
        if self.sr_break_basis not in ("CLOSE", "WICK"):
            raise ValueError("invalid sr_break_basis")
        if isinstance(self.intrabar_missing_policy, str):
            object.__setattr__(self, "intrabar_missing_policy", IntrabarMissingPolicy(self.intrabar_missing_policy))
        if isinstance(self.risk_mode, str):
            object.__setattr__(self, "risk_mode", RiskMode(self.risk_mode))
        if isinstance(self.entry_mode, str):
            object.__setattr__(self, "entry_mode", EntryMode(self.entry_mode))
        if isinstance(self.tie_policy, str):
            object.__setattr__(self, "tie_policy", TiePolicy(self.tie_policy))
        if isinstance(self.daily_entry_missed_policy, str):
            object.__setattr__(self, "daily_entry_missed_policy", DailyEntryMissedPolicy(self.daily_entry_missed_policy))
        try:
            hh, mm = [int(part) for part in str(self.daily_entry_time).split(":", 1)]
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
        except Exception as exc:
            raise ValueError("daily_entry_time must be HH:MM in 24-hour time") from exc
        if (hh * 60 + mm) % self.strategy_timeframe_minutes != 0:
            raise ValueError("daily_entry_time must align to the strategy timeframe")
        try:
            ZoneInfo(self.daily_entry_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("daily_entry_timezone must be a valid IANA timezone") from exc
        if self.telemetry_interval_minutes <= 0:
            raise ValueError("telemetry interval must be > 0")
        if self.lifecycle_phases != 4:
            raise ValueError("lifecycle_phases must currently be 4")
        if self.lifecycle_minimum_bucket_sample <= 0 or self.lifecycle_flat_pattern_threshold_pct < 0:
            raise ValueError("lifecycle settings are invalid")
        if isinstance(self.lifecycle_early_checkpoints, list):
            object.__setattr__(self, "lifecycle_early_checkpoints", tuple(int(v) for v in self.lifecycle_early_checkpoints))
        if any(v <= 0 for v in self.lifecycle_early_checkpoints):
            raise ValueError("lifecycle early checkpoints must be positive")
        if self.telemetry_interval_minutes % self.strategy_timeframe_minutes != 0:
            raise ValueError("telemetry interval must be a multiple of the strategy timeframe")
