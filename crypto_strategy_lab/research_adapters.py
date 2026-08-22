"""Bounded composition adapters around the proven native simulator implementation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace
import time

from .data_lake_production_engine import DataLakeProductionBacktestEngine
from .gui.enhanced_config import enhanced_default_gui_config, build_enhanced_backtest_config
from .strategy_profiles import StrategyProfile


@dataclass(frozen=True)
class BoundNativeStrategyPolicy:
    """The strategy policy explicitly bound to one prepared market-fact frame."""

    config: object


@dataclass(frozen=True)
class PreparedPolicyConfig:
    """Only policy-market inputs physically materialized into PreparedBacktestFrame."""

    strategy_timeframe_minutes: int
    market_regime_method: str
    bull_regime_lookback_days: int
    bull_regime_return_threshold: float
    structural_regime_sma_days: int
    structural_regime_slope_lookback_days: int
    strategy_profiles: dict[str, object]
    market_symbol: str = "POLICY"


def prepared_policy_config(run_config) -> PreparedPolicyConfig:
    """Project the composed config to the exact inputs that participate in L3."""

    profiles = {
        key: SimpleNamespace(
            rsi_period=int(profile.rsi_period),
            momentum_lookback_hours=int(profile.momentum_lookback_hours),
        )
        for key, profile in run_config.strategy.profiles.items()
    }
    return PreparedPolicyConfig(
        strategy_timeframe_minutes=int(run_config.data.strategy_timeframe_minutes),
        market_regime_method=str(run_config.features.market_regime_method),
        bull_regime_lookback_days=int(run_config.features.bull_regime_lookback_days),
        bull_regime_return_threshold=float(run_config.features.bull_regime_return_threshold),
        structural_regime_sma_days=int(run_config.features.structural_regime_sma_days),
        structural_regime_slope_lookback_days=int(
            run_config.features.structural_regime_slope_lookback_days
        ),
        strategy_profiles=profiles,
    )


def native_simulator_config(data_config, feature_config, strategy_config, execution_config):
    """Translate composition only at the mature simulator boundary.

    ReportingConfig is intentionally absent: report/output changes cannot alter
    simulation configuration or L3 identity. The returned EnhancedBacktestConfig
    is an implementation adapter, not the authoritative serialized contract.
    """

    values = enhanced_default_gui_config()
    for component in (data_config, feature_config, strategy_config, execution_config):
        for name, value in asdict(component).items():
            if name != "profiles" and name in values:
                values[name] = value
    values["strategy_profiles"] = {
        key: asdict(
            StrategyProfile(
                **{
                    **asdict(strategy_config.profiles[key]),
                    **asdict(execution_config.profiles[key]),
                }
            )
        )
        for key in strategy_config.profiles
    }
    # Inert compatibility fields required by the mature config constructor.
    # Telemetry/reporting is owned outside the simulator in the composed path;
    # using the strategy interval here only satisfies the legacy validation rule.
    values.update(
        input_csv="",
        intrabar_csv=None,
        output_dir="output",
        structural_regime_benchmark_csv=None,
        telemetry_interval_minutes=int(data_config.strategy_timeframe_minutes),
        enable_trade_telemetry=False,
        save_full_telemetry_csv=False,
        save_trade_journey_summary=False,
        save_trade_journey_charts=False,
        enable_indicator_lifecycle_analysis=False,
        config_version=2,
    )
    return build_enhanced_backtest_config(values, require_paths=False)


class NativeSimulator:
    """Composition adapter; deliberately not an engine subclass."""

    def __init__(self):
        self.last_engine_init_seconds = 0.0
        self.last_simulation_seconds = 0.0

    def run(
        self,
        prepared,
        intrabar,
        strategy,
        execution_config,
        *,
        data_config,
        feature_config,
    ):
        if not isinstance(strategy, BoundNativeStrategyPolicy):
            raise TypeError("NativeSimulator requires a bound strategy policy")
        native_config = native_simulator_config(
            data_config,
            feature_config,
            strategy.config,
            execution_config,
        )
        started = time.perf_counter()
        engine = DataLakeProductionBacktestEngine.from_prepared(
            prepared, intrabar, native_config
        )
        self.last_engine_init_seconds = time.perf_counter() - started
        started = time.perf_counter()
        trades = engine.run()
        self.last_simulation_seconds = time.perf_counter() - started
        return trades


class NativeStrategyPolicy:
    """Prepared-fact strategy policy supplied explicitly to the simulator boundary."""

    def bind(self, prepared, config):
        # Prepared facts are immutable; binding establishes explicit strategy
        # ownership without moving indicator or fill logic into this adapter.
        del prepared
        return BoundNativeStrategyPolicy(config)
