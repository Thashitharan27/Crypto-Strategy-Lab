"""Production simulator composition for Data Lake v2.

The feature-injection adapter and the mature enhanced/SR-dynamic execution engine
are deliberately composed rather than forked. This preserves current strategy
semantics while stateless features migrate out of the simulator in small slices.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_strategy_lab.data_lake_engine import DataLakeBacktestEngine
from crypto_strategy_lab.features.support_resistance import (
    PreparedSupportResistanceContextReader,
    SR_CONTEXT_FIELDS,
)
from crypto_strategy_lab.sr_dynamic_tp_engine import SRDynamicTPBacktestEngine


_REQUIRED_SR_COLUMNS = {
    "timestamp",
    "available_at",
    *(
        f"{direction}_{field}"
        for direction in ("long", "short")
        for field in SR_CONTEXT_FIELDS
    ),
}


class DataLakeProductionBacktestEngine(DataLakeBacktestEngine, SRDynamicTPBacktestEngine):
    """Production engine with Data-Lake-prepared causal feature inputs."""

    def __init__(
        self,
        *args,
        structural_benchmark: pd.DataFrame | None = None,
        technical_features: pd.DataFrame | None = None,
        context_features: pd.DataFrame | None = None,
        support_resistance_features: pd.DataFrame | None = None,
        **kwargs,
    ) -> None:
        # MarketContextFeatureProvider currently mirrors the base-engine MR/BB
        # block. Production uses the richer MR-v2 implementation, so keep this
        # cached frame available for research/manifests but do not overwrite the
        # production MR-v2 arrays until that provider is migrated separately.
        self.prepared_context_features = context_features
        self.support_resistance_features = support_resistance_features
        super().__init__(
            *args,
            structural_benchmark=structural_benchmark,
            technical_features=technical_features,
            context_features=None,
            **kwargs,
        )

        if not self.config.enable_support_resistance_analysis:
            self.support_resistance_feature_source = "disabled"
            return

        strategy_minutes = int(self.config.strategy_timeframe_minutes)
        configured_minutes = int(getattr(self.config, "sr_timeframe_minutes", 0) or 0)
        effective_minutes = configured_minutes or strategy_minutes
        if effective_minutes > strategy_minutes:
            # EnhancedBacktestEngine owns the complete-bar higher-timeframe path.
            self.support_resistance_feature_source = "higher_timeframe_engine"
            return

        if support_resistance_features is None:
            self.support_resistance_feature_source = "legacy_detector_fallback"
            return

        prepared = self._validate_support_resistance_features(
            self.data,
            self.config,
            support_resistance_features,
        )
        self.support_resistance_features = prepared
        self.sr_detector = PreparedSupportResistanceContextReader(prepared)
        self.support_resistance_feature_source = (
            f"{prepared.attrs.get('feature_name', 'support_resistance')}@"
            f"{prepared.attrs.get('feature_version', 'unknown')}"
        )

    @classmethod
    def _validate_support_resistance_features(
        cls,
        data,
        config,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        missing = sorted(_REQUIRED_SR_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError(f"Prepared S/R feature frame is missing columns: {missing}")
        features, data_times = cls._aligned_feature_frame(data, frame, "support/resistance feature")
        cls._assert_causal_availability(features, data_times, config, "support/resistance feature")

        expected = {
            "pivot_left": int(config.sr_pivot_left),
            "pivot_right": int(config.sr_pivot_right),
            "lookback_bars": int(config.sr_lookback_bars),
            "zone_width_atr": float(config.sr_zone_width_atr),
            "near_distance_atr": float(config.sr_near_distance_atr),
            "enable_hold_confirmation": bool(config.enable_sr_hold_confirmation),
            "hold_confirmation_bars": int(config.sr_hold_confirmation_bars),
            "hold_confirmation_atr": float(config.sr_hold_confirmation_atr),
            "break_tolerance_atr": float(config.sr_break_tolerance_atr),
            "break_basis": str(config.sr_break_basis).upper(),
        }
        for name, wanted in expected.items():
            actual = features.attrs.get(f"parameter_{name}")
            if isinstance(wanted, float):
                if actual is None or not np.isclose(float(actual), wanted):
                    raise ValueError(f"Prepared S/R {name} does not match config")
            elif isinstance(wanted, bool):
                if bool(actual) != wanted:
                    raise ValueError(f"Prepared S/R {name} does not match config")
            elif str(actual) != str(wanted):
                raise ValueError(f"Prepared S/R {name} does not match config")
        return features
