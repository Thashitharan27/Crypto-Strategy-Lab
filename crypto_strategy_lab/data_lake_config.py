"""Strict, composition-oriented configuration for Data Lake research runs.

This module intentionally has no dependency on the legacy GUI configuration.
The native simulator compatibility conversion lives at the composition boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

CONFIG_VERSION = 3
PROFILE_KEYS = ("bull_long", "bull_short", "bear_long", "bear_short", "sideways_long", "sideways_short")


@dataclass(frozen=True)
class DataConfig:
    strategy_timeframe_minutes: int = 240
    intrabar_timeframe_minutes: int = 1
    use_intrabar_data: bool = True
    intrabar_missing_policy: str = "ERROR"


@dataclass(frozen=True)
class FeatureConfig:
    atr_period: int = 14
    adx_period: int = 14
    di_pressure_lookback: int = 3
    bb_period: int = 20
    bb_stddevs: float = 2.0
    mean_reversion_period: int = 20
    mean_reversion_mean_type: str = "SMA"
    mean_reversion_bb_stddevs: float = 2.0
    mean_reversion_rsi_period: int = 14
    mean_reversion_rsi_oversold: float = 30.0
    mean_reversion_rsi_overbought: float = 70.0
    mean_reversion_require_reentry: bool = True
    mean_reversion_track_atr_distance: bool = True
    mean_reversion_track_motion: bool = True
    enable_support_resistance_analysis: bool = False
    sr_timeframe_minutes: int = 0
    sr_pivot_left: int = 5
    sr_pivot_right: int = 5
    sr_lookback_bars: int = 200
    sr_zone_width_atr: float = .5
    sr_near_distance_atr: float = .75
    enable_sr_hold_confirmation: bool = False
    sr_hold_confirmation_bars: int = 3
    sr_hold_confirmation_atr: float = .25
    sr_break_tolerance_atr: float = .25
    sr_break_basis: str = "CLOSE"
    market_regime_method: str = "BTC_STRUCTURAL"
    structural_regime_sma_days: int = 200
    structural_regime_slope_lookback_days: int = 30
    bull_regime_lookback_days: int = 30
    bull_regime_return_threshold: float = 0.0
    include_agg_trade_flow: bool = False

    def registry_parameters(self) -> dict[str, dict[str, Any]]:
        directional = {k: getattr(self, k) for k in ("atr_period", "adx_period", "di_pressure_lookback")}
        context_names = ("bb_period", "bb_stddevs", "mean_reversion_period", "mean_reversion_mean_type",
                         "mean_reversion_bb_stddevs", "mean_reversion_rsi_period", "mean_reversion_rsi_oversold",
                         "mean_reversion_rsi_overbought", "mean_reversion_require_reentry")
        return {"core_directional": directional,
                "production_market_context": {k: getattr(self, k) for k in context_names}}


@dataclass(frozen=True)
class StrategyProfileConfig:
    enabled: bool = True
    flip_direction: bool = False
    entry_rules: tuple = ()
    flip_rule_match_mode: str = "ANY"
    reject_rule_match_mode: str = "ANY"
    rsi_period: int = 14
    momentum_lookback_hours: int = 24


@dataclass(frozen=True)
class ExecutionProfileConfig:
    reward_risk_ratio: float = 1.0
    risk_multiplier: float = 1.0
    stop_loss_multiple: float = 2.0
    partial_stop_enabled: bool = False
    sl1_r: float = .5
    sl1_close_pct: float = 50.0
    sl2_r: float = 2.0
    partial_profit_enabled: bool = False
    tp1_r: float = 1.0
    tp1_close_pct: float = 50.0
    tp2_r: float = 2.0
    trailing_enabled: bool = False
    trailing_activation_r: float = 3.0
    trailing_distance_r: float = 1.0
    break_even_enabled: bool = False
    break_even_activation_r: float = 1.0
    break_even_offset_r: float = 0.0
    timeout_enabled: bool = False
    timeout_minutes: int = 480
    r_step_trailing_enabled: bool = False
    r_step_activation_r: float = 2.0
    r_step_distance_r: float = 2.0
    r_step_size_r: float = 1.0
    r_step_maximum_r: float = 0.0
    r_step_activation_close_pct: float = 0.0
    atr_checkpoint_tp_extension_enabled: bool = False
    atr_checkpoint_di_spread_minimum: float = 30.0
    atr_checkpoint_bb_width_minimum: float = .03
    atr_checkpoint_profit_lock_start: float = 3.0
    atr_checkpoint_profit_lock_distance: float = 1.0


def _strategy_profiles(): return {key: StrategyProfileConfig() for key in PROFILE_KEYS}
def _execution_profiles(): return {key: ExecutionProfileConfig() for key in PROFILE_KEYS}


@dataclass(frozen=True)
class StrategyConfig:
    profiles: Mapping[str, StrategyProfileConfig] = field(default_factory=_strategy_profiles)
    strategy_profile_run_mode: str = "COMBINED_SHARED_CAPITAL"
    entry_mode: str = "WAIT_UNTIL_CLOSED"
    entry_interval: int = 1
    enable_di_direction_selection: bool = False
    enable_di_pressure_analysis: bool = False
    di_pressure_allow_expanding: bool = True
    di_pressure_allow_contracting: bool = True
    di_pressure_allow_mixed: bool = True
    enable_mean_reversion_analysis: bool = False
    sr_filter_mode: str = "ANALYSIS_ONLY"
    sr_long_avoid_near_resistance: bool = False
    sr_long_require_near_support: bool = False
    sr_long_block_broken_support: bool = False
    sr_long_min_room_to_resistance_atr: float = 0.0
    sr_short_avoid_near_support: bool = False
    sr_short_require_near_resistance: bool = False
    sr_short_block_broken_resistance: bool = False
    sr_short_min_room_to_support_atr: float = 0.0
    enable_daily_entry_schedule: bool = False
    daily_entry_time: str = "00:00"
    daily_entry_timezone: str = "UTC"
    daily_entry_missed_policy: str = "SKIP_DAY"


@dataclass(frozen=True)
class ExecutionConfig:
    profiles: Mapping[str, ExecutionProfileConfig] = field(default_factory=_execution_profiles)
    initial_equity: float = 1000.0
    risk_mode: str = "ATR"
    fixed_r: float = 100.0
    percent_r: float = .002
    atr_multiplier: float = 1.0
    risk_per_leg: float = .01
    max_effective_leverage_per_leg: float = 3.0
    max_combined_effective_leverage: float = 5.0
    maker_fee: float = .0002
    taker_fee: float = .0005
    use_maker_entry: bool = False
    use_maker_exit: bool = False
    slippage: float = .0005
    tie_policy: str = "PESSIMISTIC"
    max_active_pairs: int = 1
    zero_cost_comparison: bool = False
    sr_take_profit_mode: str = "FIXED_R"
    sr_take_profit_maximum_r: float = 3.0
    sr_take_profit_minimum_r: float = 1.5
    sr_take_profit_buffer_r: float = .2
    sr_take_profit_no_level_policy: str = "USE_FIXED_TP"


@dataclass(frozen=True)
class ReportingConfig:
    run_name: str = "DATA_LAKE_RUN"
    output_dir: str = "output/data_lake_v2"
    analysis_level: str = "STANDARD"
    enable_trade_telemetry: bool = False
    save_full_telemetry_csv: bool = False
    save_trade_journey_summary: bool = False
    save_trade_journey_charts: bool = False
    telemetry_interval_minutes: int = 240
    enable_indicator_lifecycle_analysis: bool = False
    lifecycle_phases: int = 4
    lifecycle_early_checkpoints: tuple = (15, 30, 60)
    lifecycle_minimum_bucket_sample: int = 20
    create_lifecycle_charts: bool = False
    lifecycle_flat_pattern_threshold_pct: float = 5.0
    save_feature_analysis_reports: bool = False
    save_indicator_analysis_reports: bool = False
    create_standard_charts: bool = False


@dataclass(frozen=True)
class ResearchRunConfig:
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    config_version: int = CONFIG_VERSION

    def validate(self, request=None) -> None:
        if self.data.use_intrabar_data and self.data.intrabar_timeframe_minutes >= self.data.strategy_timeframe_minutes:
            raise ValueError("intrabar timeframe must be smaller than strategy timeframe")
        if request is not None and request.strategy_interval != f"{self.data.strategy_timeframe_minutes}m":
            raise ValueError("DataRequest strategy interval disagrees with DataConfig")
        missing = {k for k, p in self.strategy.profiles.items() if p.enabled} - set(self.execution.profiles)
        if missing: raise ValueError("enabled strategy profiles lack execution profiles: " + ", ".join(sorted(missing)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strict(cls, raw, label):
    if not isinstance(raw, dict): raise ValueError(f"{label} must be an object")
    allowed = set(cls.__dataclass_fields__)
    unknown = sorted(set(raw) - allowed)
    if unknown: raise ValueError(f"Unknown {label} settings: " + ", ".join(unknown))
    return cls(**raw)


def _profiles(raw, strategy: bool):
    cls = StrategyProfileConfig if strategy else ExecutionProfileConfig
    if raw is None: return _strategy_profiles() if strategy else _execution_profiles()
    if not isinstance(raw, dict): raise ValueError("profiles must be an object")
    unknown = sorted(set(raw) - set(PROFILE_KEYS))
    if unknown: raise ValueError("unknown profile keys: " + ", ".join(unknown))
    return {key: _strict(cls, raw.get(key, {}), f"profiles.{key}") for key in PROFILE_KEYS}


def normalize_data_lake_config(values: dict[str, Any]) -> ResearchRunConfig:
    if not isinstance(values, dict): raise ValueError("Data Lake configuration JSON must contain an object")
    allowed = {"config_version", "data", "features", "strategy", "execution", "reporting"}
    unknown = sorted(set(values) - allowed)
    if unknown: raise ValueError("Unknown Data Lake configuration sections: " + ", ".join(unknown))
    if values.get("config_version") != CONFIG_VERSION: raise ValueError("Data Lake configuration version 3 is required.")
    sraw, eraw = dict(values.get("strategy", {})), dict(values.get("execution", {}))
    strategy_profiles = _profiles(sraw.pop("profiles", None), True)
    execution_profiles = _profiles(eraw.pop("profiles", None), False)
    parsed_strategy = _strict(StrategyConfig, sraw, "strategy")
    parsed_execution = _strict(ExecutionConfig, eraw, "execution")
    strategy_values = {k: v for k, v in parsed_strategy.__dict__.items() if k != "profiles"}
    execution_values = {k: v for k, v in parsed_execution.__dict__.items() if k != "profiles"}
    result = ResearchRunConfig(
        data=_strict(DataConfig, values.get("data", {}), "data"),
        features=_strict(FeatureConfig, values.get("features", {}), "features"),
        strategy=StrategyConfig(profiles=strategy_profiles, **strategy_values),
        execution=ExecutionConfig(profiles=execution_profiles, **execution_values),
        reporting=_strict(ReportingConfig, values.get("reporting", {}), "reporting"),
    )
    result.validate()
    return result


def default_data_lake_config() -> dict[str, Any]: return ResearchRunConfig().to_dict()
def load_data_lake_config(path: str | Path) -> ResearchRunConfig:
    return normalize_data_lake_config(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def build_data_lake_backtest_config(values: dict[str, Any]):
    """Compatibility API for callers already holding a v3 dictionary.

    Flat v2 input is deliberately not accepted. New Data Lake code must retain
    the returned ResearchRunConfig rather than treating this as its contract.
    """
    return normalize_data_lake_config(values)
