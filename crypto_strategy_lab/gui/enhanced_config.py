"""Extended configuration for research analytics and optional entry filters."""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.gui.config_logic import (
    DEFAULT_GUI_CONFIG,
    build_backtest_config,
    canonical_config_values,
    default_gui_config,
)


DI_PRESSURE_FILTER_DEFAULTS: dict[str, Any] = {
    "di_pressure_allow_expanding": True,
    "di_pressure_allow_contracting": True,
    "di_pressure_allow_mixed": True,
}

MEAN_REVERSION_V2_DEFAULTS: dict[str, Any] = {
    "mean_reversion_mean_type": "SMA",
    "mean_reversion_bb_stddevs": 2.0,
    "mean_reversion_rsi_period": 14,
    "mean_reversion_rsi_oversold": 30.0,
    "mean_reversion_rsi_overbought": 70.0,
    "mean_reversion_require_reentry": True,
    "mean_reversion_track_atr_distance": True,
    "mean_reversion_track_motion": True,
}

SR_HTF_DEFAULTS: dict[str, Any] = {
    # 0 means use the strategy timeframe exactly as before.
    "sr_timeframe_minutes": 0,
}

ENHANCED_DEFAULTS: dict[str, Any] = {
    **DI_PRESSURE_FILTER_DEFAULTS,
    **MEAN_REVERSION_V2_DEFAULTS,
    **SR_HTF_DEFAULTS,
}


@dataclass(frozen=True)
class EnhancedBacktestConfig(BacktestConfig):
    """BacktestConfig plus DI-pressure filtering, MR-v2, and higher-timeframe S/R settings."""

    di_pressure_allow_expanding: bool = True
    di_pressure_allow_contracting: bool = True
    di_pressure_allow_mixed: bool = True
    mean_reversion_mean_type: str = "SMA"
    mean_reversion_bb_stddevs: float = 2.0
    mean_reversion_rsi_period: int = 14
    mean_reversion_rsi_oversold: float = 30.0
    mean_reversion_rsi_overbought: float = 70.0
    mean_reversion_require_reentry: bool = True
    mean_reversion_track_atr_distance: bool = True
    mean_reversion_track_motion: bool = True
    sr_timeframe_minutes: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.enable_di_pressure_analysis and not any(
            (
                self.di_pressure_allow_expanding,
                self.di_pressure_allow_contracting,
                self.di_pressure_allow_mixed,
            )
        ):
            raise ValueError("At least one DI pressure state must be allowed when DI pressure analysis is enabled")

        mean_type = str(self.mean_reversion_mean_type).upper()
        object.__setattr__(self, "mean_reversion_mean_type", mean_type)
        if mean_type not in ("SMA", "EMA"):
            raise ValueError("mean_reversion_mean_type must be SMA or EMA")
        if self.mean_reversion_bb_stddevs <= 0:
            raise ValueError("mean_reversion_bb_stddevs must be positive")
        if self.mean_reversion_rsi_period <= 0:
            raise ValueError("mean_reversion_rsi_period must be positive")
        oversold = float(self.mean_reversion_rsi_oversold)
        overbought = float(self.mean_reversion_rsi_overbought)
        if not 0 <= oversold < overbought <= 100:
            raise ValueError("RSI thresholds must satisfy 0 <= oversold < overbought <= 100")

        sr_tf = int(self.sr_timeframe_minutes)
        object.__setattr__(self, "sr_timeframe_minutes", sr_tf)
        if sr_tf < 0:
            raise ValueError("sr_timeframe_minutes cannot be negative")
        if sr_tf:
            if sr_tf < self.strategy_timeframe_minutes:
                raise ValueError("S/R timeframe cannot be lower than the strategy timeframe")
            if sr_tf % self.strategy_timeframe_minutes != 0:
                raise ValueError("S/R timeframe must be an integer multiple of the strategy timeframe")


def enhanced_default_gui_config() -> dict[str, Any]:
    return {**default_gui_config(), **ENHANCED_DEFAULTS}


def _split_values(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = set(DEFAULT_GUI_CONFIG) | set(ENHANCED_DEFAULTS)
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"Unknown/retired configuration settings: {', '.join(unknown)}")
    base = {key: value for key, value in values.items() if key in DEFAULT_GUI_CONFIG}
    extras = {**ENHANCED_DEFAULTS, **{key: values[key] for key in ENHANCED_DEFAULTS if key in values}}
    return base, extras


def build_enhanced_backtest_config(values: dict[str, Any], require_paths: bool = True) -> EnhancedBacktestConfig:
    """Build the normal config, then preserve it exactly while adding enhanced fields."""
    base_values, extras = _split_values({**enhanced_default_gui_config(), **values})
    base = build_backtest_config(base_values, require_paths=require_paths)
    base_kwargs = {field.name: getattr(base, field.name) for field in fields(BacktestConfig)}
    return EnhancedBacktestConfig(**base_kwargs, **extras)


def save_enhanced_config_json(path: str | Path, values: dict[str, Any]) -> None:
    base_values, extras = _split_values({**enhanced_default_gui_config(), **values})
    payload = canonical_config_values(base_values)
    payload.update(extras)
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_enhanced_config_json(path: str | Path) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Configuration JSON must contain an object.")
    base_values, extras = _split_values({**enhanced_default_gui_config(), **loaded})
    from crypto_strategy_lab.gui.config_logic import _merged_current

    merged = _merged_current(base_values)
    merged.update(extras)
    return merged