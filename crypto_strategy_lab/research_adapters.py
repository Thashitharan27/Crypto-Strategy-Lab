"""Bounded adapters around the proven native simulator implementation."""
from __future__ import annotations

from dataclasses import asdict

from .data_lake_production_engine import DataLakeProductionBacktestEngine
from .gui.enhanced_config import enhanced_default_gui_config, build_enhanced_backtest_config
from .strategy_profiles import StrategyProfile


def native_simulator_config(config):
    """Translate the composed contract only at the legacy simulator boundary."""
    values = enhanced_default_gui_config()
    for component in (config.data, config.features, config.strategy, config.execution, config.reporting):
        for name, value in asdict(component).items():
            if name != "profiles" and name in values:
                values[name] = value
    values["strategy_profiles"] = {
        key: asdict(StrategyProfile(**{
            **asdict(config.strategy.profiles[key]),
            **asdict(config.execution.profiles[key]),
        })) for key in config.strategy.profiles
    }
    # These are inert for from_prepared(); the adapter is not a serialized contract.
    values.update(input_csv="", intrabar_csv=None, output_dir=config.reporting.output_dir,
                  structural_regime_benchmark_csv=None, config_version=2)
    return build_enhanced_backtest_config(values, require_paths=False)


class NativeSimulator:
    """Composition adapter; deliberately not an engine subclass."""
    def run(self, prepared, intrabar, strategy, execution_config, *, native_config):
        engine = DataLakeProductionBacktestEngine.from_prepared(prepared, intrabar, native_config)
        return engine.run()


class NativeStrategyPolicy:
    """Prepared-fact policy supplied explicitly to the simulator boundary."""
    def bind(self, prepared, config):
        return self

