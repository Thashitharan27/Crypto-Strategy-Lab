"""Default configuration for the dual long/short backtester."""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
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
    trade_direction: TradeDirectionMode = TradeDirectionMode.BOTH
    enable_strategy_profiles: bool = False
    strategy_profile_run_mode: str = "COMBINED_SHARED_CAPITAL"
    strategy_profiles: dict[str, StrategyProfile] = field(default_factory=default_profiles)
    enable_trailing_profit: bool = False
    enable_partial_take_profit: bool = False
    enable_partial_stop_loss: bool = False
    sl1_r: float = 0.5
    sl1_close_pct: float = 50.0
    sl2_r: float = 8.0
    tp1_r: float = 3.0
    tp1_close_pct: float = 50.0
    tp2_r: float = 12.0
    tp2_close_pct: float = 50.0
    stop_loss_r: float = 10.0
    after_tp1_stop_mode: AfterTP1StopMode = AfterTP1StopMode.KEEP_ORIGINAL_SL
    after_tp1_stop_offset_r: float = 0.0
    tp2_exit_mode: TP2ExitMode = TP2ExitMode.FIXED_TP2
    trail_activation_r: float = 3.0
    trail_activation_trigger: TrailActivationTrigger = TrailActivationTrigger.PRICE_REACHES_R
    trail_distance_r: float = 1.0
    trail_apply_to: TrailApplyTo = TrailApplyTo.BOTH
    trail_intrabar_mode: TrailIntrabarMode = TrailIntrabarMode.PESSIMISTIC
    enable_both_open_timeout: bool = False
    max_both_open_minutes: int = 480
    enable_remaining_leg_timeout_after_first_sl: bool = False
    remaining_leg_timeout_after_first_sl_minutes: int = 240
    enable_remaining_leg_timeout_profit_extension: bool = False
    remaining_leg_timeout_profit_threshold_r: float = 10.0
    enable_remaining_leg_checkpoint_score_extension: bool = False
    checkpoint_score_use_profit: bool = True
    checkpoint_score_min_profit_r: float = 0.85
    checkpoint_score_use_atr_pct: bool = True
    checkpoint_score_max_atr_pct: float = 0.08
    checkpoint_score_use_directional_di: bool = True
    checkpoint_score_min_directional_di: float = 2.3
    checkpoint_score_use_bb_width_pct: bool = True
    checkpoint_score_max_bb_width_pct: float = 0.349
    checkpoint_score_min_conditions: int = 3
    enable_first_sl_survivor_partial_close: bool = False
    first_sl_survivor_partial_close_pct: float = 25.0
    enable_checkpoint_zero_score_confirmation: bool = False
    checkpoint_zero_score_confirmations_required: int = 2
    checkpoint_zero_score_recheck_minutes: int = 120
    enable_reentry_gate_after_remaining_leg_timeout: bool = False
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
    bb_width_minimum: float = 0.012
    enable_skip_monday_entries: bool = False
    skip_monday_timezone: str = "UTC"
    enable_di_spread_filter: bool = False
    di_spread_filter_mode: DISpreadFilterMode = DISpreadFilterMode.DISABLED
    di_spread_maximum: float = 10.0
    di_spread_minimum: float = 0.0
    risk_per_leg: float = 0.005
    position_sizing_mode: PositionSizingMode = PositionSizingMode.PRICE_RISK
    entry_mode: EntryMode = EntryMode.WAIT_UNTIL_CLOSED
    entry_interval: int = 1
    vwap_breakout_lookback_hours: float = 4.0
    vwap_volume_lookback: int = 20
    vwap_volume_multiplier: float = 1.5
    vwap_slope_lookback: int = 1
    vwap_atr_pct_minimum: float = 0.0
    vwap_atr_pct_maximum: float = 1.0
    vwap_confirmation_mode: VWAPConfirmationMode = VWAPConfirmationMode.IMMEDIATE
    vwap_retest_window_candles: int = 4
    vwap_retest_tolerance_atr: float = 0.25
    enable_random_entry: bool = False
    entry_timing_mode: EntryTimingMode = EntryTimingMode.CURRENT
    random_entry_probability: float = 0.50
    random_seed: int = 42
    enable_coin_flip_sizing: bool = False
    coin_flip_seed: int = 42
    coin_flip_large_multiplier: float = 3.0
    coin_flip_small_multiplier: float = 1.0
    enable_di_direction_sizing: bool = False
    enable_di_direction_selection: bool = True
    enable_di_pressure_analysis: bool = True
    di_pressure_lookback: int = 3
    flip_filtered_di_direction: bool = False
    di_direction_minimum_spread: float = 30.0
    di_direction_long_minimum_spread: Optional[float] = None
    di_direction_short_minimum_spread: Optional[float] = None
    di_execution_mode: DIExecutionMode = DIExecutionMode.BOTH_SIDES
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
    enable_bull_long_r_step_trailing: bool = False
    bull_long_r_step_activation_r: float = 2.0
    bull_long_r_step_distance_r: float = 2.0
    bull_long_r_step_size_r: float = 1.0
    bull_long_r_step_maximum_r: float = 0.0
    bull_long_r_step_activation_close_pct: float = 0.0
    enable_directional_adx_filter: bool = False
    directional_long_adx_maximum: float = 60.0
    directional_short_adx_minimum: float = 25.0
    enable_long_momentum_filter: bool = False
    long_momentum_lookback_hours: int = 24
    long_momentum_minimum_return: float = 0.06
    enable_atr_checkpoint_tp_extension: bool = False
    atr_checkpoint_di_spread_minimum: float = 30.0
    atr_checkpoint_bb_width_minimum: float = 0.03
    atr_checkpoint_profit_lock_start: float = 3.0
    atr_checkpoint_profit_lock_distance: float = 1.0
    enable_biased_short_adx_cap: bool = False
    biased_short_adx_maximum: float = 50.0
    enable_short_vwap_distance_filter: bool = False
    short_vwap_minimum_distance_atr: float = 2.0
    enable_bull_regime_short_filter: bool = False
    market_regime_method: str = "ASSET_RETURN"
    structural_regime_sma_days: int = 200
    structural_regime_slope_lookback_days: int = 30
    structural_regime_benchmark_csv: Optional[Path] = None
    bull_regime_lookback_days: int = 90
    bull_regime_return_threshold: float = 0.20
    enable_bear_regime_adx_filter: bool = False
    bear_regime_adx_minimum: float = 25.0
    random_entry_start_mode: RandomEntryStartMode = RandomEntryStartMode.NEXT_FULL_CANDLE_AFTER_PAIR_CLOSE
    randomize_first_entry: bool = True
    max_random_wait_candles: int = 0
    enable_random_entry_batch: bool = False
    random_seed_start: int = 1
    random_seed_count: int = 100
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
    enable_indicator_lifecycle_analysis: bool = True
    lifecycle_phases: int = 4
    lifecycle_early_checkpoints: tuple[int, ...] = (15, 30, 60)
    lifecycle_minimum_bucket_sample: int = 20
    create_lifecycle_charts: bool = True
    lifecycle_flat_pattern_threshold_pct: float = 5.0
    save_feature_analysis_reports: bool = True
    save_indicator_analysis_reports: bool = True
    create_standard_charts: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_profiles", normalize_profiles(self.strategy_profiles))
        if self.strategy_profile_run_mode not in ("ISOLATED_PROFILES", "COMBINED_SHARED_CAPITAL", "BOTH"):
            raise ValueError("invalid strategy_profile_run_mode")
        if self.di_direction_long_minimum_spread is None:
            object.__setattr__(self, "di_direction_long_minimum_spread", self.di_direction_minimum_spread)
        if self.di_direction_short_minimum_spread is None:
            object.__setattr__(self, "di_direction_short_minimum_spread", self.di_direction_minimum_spread)
        if self.input_csv != Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv") and self.strategy_csv == Path(r"C:\CryptoBots\Binance Market Data\futures\usdm\BTCUSDT_15m.csv"):
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
        if self.tp1_r <= 0: raise ValueError("TP1_R must be greater than zero")
        if self.tp2_r <= self.tp1_r: raise ValueError("TP2_R must be greater than TP1_R")
        if self.stop_loss_r <= 0: raise ValueError("STOP_LOSS_R must be greater than zero")
        if self.sl1_r <= 0: raise ValueError("SL1_R must be greater than zero")
        if self.sl2_r <= self.sl1_r: raise ValueError("SL2_R must be greater than SL1_R")
        if not 0 < self.sl1_close_pct < 100: raise ValueError("SL1_CLOSE_PCT must be between 0 and 100")
        if self.tp1_close_pct <= 0 or self.tp2_close_pct <= 0: raise ValueError("TP close percentages must be greater than zero")
        if abs(self.tp1_close_pct + self.tp2_close_pct - 100.0) > 1e-9: raise ValueError("TP1_CLOSE_PCT + TP2_CLOSE_PCT must equal 100%")
        if self.adx_period <= 0: raise ValueError("adx_period must be positive")
        if self.adx_maximum < 0 or self.adx_minimum < 0: raise ValueError("ADX thresholds must be non-negative")
        if self.bb_period <= 0: raise ValueError("BB period must be positive")
        if self.bb_stddevs <= 0: raise ValueError("BB standard deviations must be positive")
        if self.bb_width_maximum < 0 or self.bb_width_minimum < 0: raise ValueError("BB width thresholds must be non-negative")
        if self.di_spread_maximum < 0 or self.di_spread_minimum < 0: raise ValueError("DI spread thresholds must be non-negative")
        if self.entry_interval <= 0: raise ValueError("entry_interval must be positive")
        if not 0 < self.random_entry_probability <= 1: raise ValueError("random_entry_probability must be greater than 0 and less than or equal to 1")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int): raise ValueError("random_seed must be an integer")
        if isinstance(self.coin_flip_seed, bool) or not isinstance(self.coin_flip_seed, int): raise ValueError("coin_flip_seed must be an integer")
        if self.coin_flip_large_multiplier <= 0 or self.coin_flip_small_multiplier <= 0: raise ValueError("coin-flip size multipliers must be positive")
        if self.coin_flip_large_multiplier <= self.coin_flip_small_multiplier: raise ValueError("coin_flip_large_multiplier must be greater than coin_flip_small_multiplier")
        if self.di_direction_minimum_spread < 0: raise ValueError("di_direction_minimum_spread must be non-negative")
        if self.di_direction_long_minimum_spread < 0: raise ValueError("di_direction_long_minimum_spread must be non-negative")
        if self.di_direction_short_minimum_spread < 0: raise ValueError("di_direction_short_minimum_spread must be non-negative")
        if not 1 <= self.di_pressure_lookback <= 100: raise ValueError("di_pressure_lookback must be between 1 and 100")
        if self.long_momentum_lookback_hours <= 0: raise ValueError("long_momentum_lookback_hours must be positive")
        if self.long_momentum_minimum_return <= -1: raise ValueError("long_momentum_minimum_return must be greater than -100%")
        if self.enable_long_momentum_filter and not self.enable_di_direction_sizing: raise ValueError("long momentum filter requires DI-direction sizing")
        if any(value <= 0 for value in regime_ratios): raise ValueError("DI regime reward/risk ratios must be positive")
        if self.bull_long_r_step_activation_r <= 0: raise ValueError("bull_long_r_step_activation_r must be positive")
        if self.bull_long_r_step_distance_r <= 0: raise ValueError("bull_long_r_step_distance_r must be positive")
        if self.bull_long_r_step_size_r <= 0: raise ValueError("bull_long_r_step_size_r must be positive")
        if self.bull_long_r_step_maximum_r < 0: raise ValueError("bull_long_r_step_maximum_r cannot be negative")
        if 0 < self.bull_long_r_step_maximum_r <= self.bull_long_r_step_activation_r: raise ValueError("bull_long_r_step_maximum_r must be zero or above the activation R")
        if not 0 <= self.bull_long_r_step_activation_close_pct < 100: raise ValueError("bull_long_r_step_activation_close_pct must be from 0 up to, but not including, 100")
        if self.enable_bull_long_r_step_trailing and self.enable_partial_take_profit: raise ValueError("bull-long R-step trailing cannot be combined with partial take profit")
        if self.enable_bull_long_r_step_trailing and self.enable_atr_checkpoint_tp_extension: raise ValueError("bull-long R-step trailing cannot be combined with ATR checkpoint TP extension")
        if self.enable_bull_long_r_step_trailing and self.enable_trailing_profit: raise ValueError("bull-long R-step trailing cannot be combined with the independent trailing stop")
        if self.directional_long_adx_maximum < 0: raise ValueError("directional_long_adx_maximum must be non-negative")
        if self.directional_short_adx_minimum < 0: raise ValueError("directional_short_adx_minimum must be non-negative")
        if self.enable_directional_adx_filter and not self.enable_di_direction_sizing: raise ValueError("direction-specific ADX filter requires DI-direction sizing")
        if self.atr_checkpoint_di_spread_minimum < 0: raise ValueError("atr_checkpoint_di_spread_minimum must be non-negative")
        if self.atr_checkpoint_bb_width_minimum < 0: raise ValueError("atr_checkpoint_bb_width_minimum must be non-negative")
        if self.atr_checkpoint_profit_lock_start < 1: raise ValueError("atr_checkpoint_profit_lock_start must be at least 1 ATR")
        if self.atr_checkpoint_profit_lock_distance <= 0: raise ValueError("atr_checkpoint_profit_lock_distance must be positive")
        if self.biased_short_adx_maximum < 0: raise ValueError("biased_short_adx_maximum must be non-negative")
        if self.enable_biased_short_adx_cap and not self.enable_di_direction_sizing: raise ValueError("biased-short ADX cap requires DI-direction sizing")
        if self.short_vwap_minimum_distance_atr < 0: raise ValueError("short_vwap_minimum_distance_atr must be non-negative")
        if self.enable_short_vwap_distance_filter and not self.enable_di_direction_sizing: raise ValueError("short VWAP-distance filter requires DI-direction sizing")
        if self.enable_atr_checkpoint_tp_extension and not self.enable_di_direction_sizing: raise ValueError("ATR checkpoint TP extension requires DI-direction sizing")
        if self.enable_atr_checkpoint_tp_extension and self.enable_partial_take_profit: raise ValueError("ATR checkpoint TP extension cannot be combined with partial take profit")
        if self.bull_regime_lookback_days <= 0: raise ValueError("bull_regime_lookback_days must be positive")
        if self.market_regime_method not in ("ASSET_RETURN", "BTC_STRUCTURAL", "ASSET_STRUCTURAL"): raise ValueError("market_regime_method must be ASSET_RETURN, BTC_STRUCTURAL, or ASSET_STRUCTURAL")
        if self.structural_regime_sma_days < 2: raise ValueError("structural_regime_sma_days must be at least 2")
        if self.structural_regime_slope_lookback_days < 1: raise ValueError("structural_regime_slope_lookback_days must be positive")
        if self.bull_regime_return_threshold <= -1: raise ValueError("bull_regime_return_threshold must be greater than -100%")
        if self.enable_bull_regime_short_filter and not self.enable_di_direction_sizing: raise ValueError("bull-regime short filter requires DI-direction sizing")
        if self.bear_regime_adx_minimum < 0: raise ValueError("bear_regime_adx_minimum must be non-negative")
        if self.enable_bear_regime_adx_filter and not self.enable_di_direction_sizing: raise ValueError("bear-regime ADX filter requires DI-direction sizing")
        if self.enable_coin_flip_sizing and self.enable_di_direction_sizing: raise ValueError("coin-flip sizing and DI-direction sizing cannot both be enabled")
        if self.flip_filtered_di_direction and not (self.enable_di_direction_sizing or self.enable_strategy_profiles): raise ValueError("filtered direction flip requires DI-direction sizing or strategy profiles")
        if self.enable_coin_flip_sizing and self.trade_direction not in (TradeDirectionMode.BOTH, TradeDirectionMode.BOTH_INDEPENDENT): raise ValueError("coin-flip sizing requires both long and short positions")
        if self.enable_coin_flip_sizing and (self.enable_partial_take_profit or self.enable_partial_stop_loss): raise ValueError("coin-flip sizing cannot be combined with partial TP or partial SL")
        if self.enable_di_direction_sizing and (self.enable_partial_take_profit or self.enable_partial_stop_loss): raise ValueError("DI-direction sizing cannot be combined with partial TP or partial SL")
        di_execution_value = self.di_execution_mode.value if isinstance(self.di_execution_mode, DIExecutionMode) else self.di_execution_mode
        if di_execution_value == DIExecutionMode.PREFERRED_SIDE_ONLY.value and not self.enable_di_direction_sizing: raise ValueError("preferred-side-only execution requires DI-direction sizing")
        if self.max_random_wait_candles < 0: raise ValueError("max_random_wait_candles must be >= 0")
        if self.random_seed_count <= 0: raise ValueError("random_seed_count must be positive")
        if self.max_active_pairs <= 0: raise ValueError("max_active_pairs must be positive")
        if self.fixed_r <= 0 or self.percent_r <= 0: raise ValueError("risk distances must be positive")
        if self.maker_fee < 0 or self.taker_fee < 0: raise ValueError("fee rates must be non-negative")
        if self.slippage < 0: raise ValueError("slippage must be non-negative")
        if self.max_effective_leverage_per_leg is not None and self.max_effective_leverage_per_leg <= 0: raise ValueError("max leverage per leg must be positive")
        if self.max_combined_effective_leverage is not None and self.max_combined_effective_leverage <= 0: raise ValueError("max combined leverage must be positive")
        if self.enable_both_open_timeout and self.max_both_open_minutes <= 0: raise ValueError("max_both_open_minutes must be > 0 when both-open timeout is enabled")
        if self.enable_remaining_leg_timeout_after_first_sl and self.remaining_leg_timeout_after_first_sl_minutes <= 0: raise ValueError("remaining_leg_timeout_after_first_sl_minutes must be > 0 when remaining-leg timeout is enabled")
        if self.enable_remaining_leg_timeout_profit_extension and not self.enable_remaining_leg_timeout_after_first_sl: raise ValueError("remaining-leg profit extension requires remaining-leg timeout to be enabled")
        if self.enable_remaining_leg_checkpoint_score_extension and not self.enable_remaining_leg_timeout_after_first_sl: raise ValueError("checkpoint score extension requires remaining-leg timeout to be enabled")
        if self.enable_remaining_leg_checkpoint_score_extension and self.enable_remaining_leg_timeout_profit_extension: raise ValueError("use either profit-only extension or checkpoint score extension, not both")
        if self.enable_first_sl_survivor_partial_close and self.enable_partial_take_profit: raise ValueError("first-SL survivor partial close cannot be combined with partial take profit")
        if self.enable_first_sl_survivor_partial_close and not (0 < self.first_sl_survivor_partial_close_pct < 100): raise ValueError("first_sl_survivor_partial_close_pct must be between 0 and 100")
        if self.enable_checkpoint_zero_score_confirmation and not self.enable_remaining_leg_checkpoint_score_extension: raise ValueError("zero-score confirmation requires checkpoint score extension")
        if self.enable_checkpoint_zero_score_confirmation and self.checkpoint_zero_score_confirmations_required < 2: raise ValueError("checkpoint_zero_score_confirmations_required must be at least 2")
        if self.enable_checkpoint_zero_score_confirmation and self.checkpoint_zero_score_recheck_minutes <= 0: raise ValueError("checkpoint_zero_score_recheck_minutes must be positive")
        if self.enable_reentry_gate_after_remaining_leg_timeout and not self.enable_remaining_leg_timeout_after_first_sl: raise ValueError("checkpoint re-entry gate requires remaining-leg timeout to be enabled")
        if self.remaining_leg_timeout_profit_threshold_r < 0: raise ValueError("remaining_leg_timeout_profit_threshold_r must be >= 0")
        if self.checkpoint_score_min_profit_r < 0: raise ValueError("checkpoint_score_min_profit_r must be >= 0")
        if self.checkpoint_score_max_atr_pct < 0: raise ValueError("checkpoint_score_max_atr_pct must be >= 0")
        if self.checkpoint_score_max_bb_width_pct < 0: raise ValueError("checkpoint_score_max_bb_width_pct must be >= 0")
        score_conditions = sum((self.checkpoint_score_use_profit, self.checkpoint_score_use_atr_pct, self.checkpoint_score_use_directional_di, self.checkpoint_score_use_bb_width_pct))
        if self.enable_remaining_leg_checkpoint_score_extension and score_conditions == 0: raise ValueError("checkpoint score extension requires at least one enabled condition")
        if self.enable_remaining_leg_checkpoint_score_extension and (self.checkpoint_score_min_conditions <= 0 or self.checkpoint_score_min_conditions > score_conditions): raise ValueError("checkpoint_score_min_conditions must be between 1 and the number of enabled checkpoint conditions")
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
        if isinstance(self.di_execution_mode, str): object.__setattr__(self, "di_execution_mode", DIExecutionMode(self.di_execution_mode))
        if isinstance(self.trail_apply_to, str): object.__setattr__(self, "trail_apply_to", TrailApplyTo(self.trail_apply_to))
        if isinstance(self.trail_intrabar_mode, str): object.__setattr__(self, "trail_intrabar_mode", TrailIntrabarMode(self.trail_intrabar_mode))
        if isinstance(self.trail_activation_trigger, str): object.__setattr__(self, "trail_activation_trigger", TrailActivationTrigger(self.trail_activation_trigger))
        if self.enable_trailing_profit and self.trail_activation_trigger == TrailActivationTrigger.AFTER_TP1 and not self.enable_partial_take_profit:
            raise ValueError("AFTER_TP1 trailing requires Partial Take Profit")
        if self.enable_trailing_profit and self.trail_activation_trigger == TrailActivationTrigger.AFTER_SL1 and not self.enable_partial_stop_loss:
            raise ValueError("AFTER_SL1 trailing requires Partial Stop Loss")
        if self.enable_trailing_profit and self.trail_activation_trigger == TrailActivationTrigger.AFTER_TP1_OR_SL1 and not (self.enable_partial_take_profit or self.enable_partial_stop_loss):
            raise ValueError("AFTER_TP1_OR_SL1 trailing requires a partial TP or SL ladder")
        if isinstance(self.after_tp1_stop_mode, str): object.__setattr__(self, "after_tp1_stop_mode", AfterTP1StopMode(self.after_tp1_stop_mode))
        if isinstance(self.tp2_exit_mode, str): object.__setattr__(self, "tp2_exit_mode", TP2ExitMode(self.tp2_exit_mode))
        # Migrate saved configurations from the former "TP2 replaced by
        # trailing" model. TP2 is now always terminal and trailing is an
        # independent protective stop activated after TP1.
        if self.tp2_exit_mode == TP2ExitMode.TRAILING_AFTER_TP1:
            object.__setattr__(self, "enable_trailing_profit", True)
            object.__setattr__(self, "trail_activation_trigger", TrailActivationTrigger.AFTER_TP1)
            object.__setattr__(self, "tp2_exit_mode", TP2ExitMode.FIXED_TP2)
        if isinstance(self.daily_entry_missed_policy, str): object.__setattr__(self, "daily_entry_missed_policy", DailyEntryMissedPolicy(self.daily_entry_missed_policy))
        if isinstance(self.entry_timing_mode, str): object.__setattr__(self, "entry_timing_mode", EntryTimingMode(self.entry_timing_mode))
        if isinstance(self.random_entry_start_mode, str): object.__setattr__(self, "random_entry_start_mode", RandomEntryStartMode(self.random_entry_start_mode))
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
        try:
            ZoneInfo(self.skip_monday_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("skip_monday_timezone must be a valid IANA timezone") from exc
        if self.telemetry_interval_minutes <= 0: raise ValueError("telemetry interval must be > 0")
        if self.lifecycle_phases != 4: raise ValueError("lifecycle_phases must currently be 4")
        if self.lifecycle_minimum_bucket_sample <= 0: raise ValueError("lifecycle minimum bucket sample must be positive")
        if self.lifecycle_flat_pattern_threshold_pct < 0: raise ValueError("lifecycle flat-pattern threshold must be non-negative")
        if isinstance(self.lifecycle_early_checkpoints, list): object.__setattr__(self, "lifecycle_early_checkpoints", tuple(int(v) for v in self.lifecycle_early_checkpoints))
        if any(v <= 0 for v in self.lifecycle_early_checkpoints): raise ValueError("lifecycle early checkpoints must be positive")
        if self.telemetry_interval_minutes % self.strategy_timeframe_minutes != 0: raise ValueError("telemetry interval must be a multiple of the strategy timeframe")
        if isinstance(self.comparison_timeout_minutes, list): object.__setattr__(self, "comparison_timeout_minutes", tuple(int(v) for v in self.comparison_timeout_minutes))
