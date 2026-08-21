"""Production simulator composition for Data Lake v2.

The feature-injection adapter and the mature enhanced/SR-dynamic execution engine
are deliberately composed rather than forked. This preserves current strategy
semantics while stateless features migrate out of the simulator in small slices.
"""
from __future__ import annotations

from collections.abc import Mapping

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

_RESEARCH_META_COLUMNS = {"timestamp", "available_at"}


class DataLakeProductionBacktestEngine(DataLakeBacktestEngine, SRDynamicTPBacktestEngine):
    """Production engine with Data-Lake-prepared causal feature inputs."""

    def __init__(
        self,
        *args,
        structural_benchmark: pd.DataFrame | None = None,
        technical_features: pd.DataFrame | None = None,
        context_features: pd.DataFrame | None = None,
        support_resistance_features: pd.DataFrame | None = None,
        research_features: Mapping[str, pd.DataFrame] | None = None,
        **kwargs,
    ) -> None:
        # MarketContextFeatureProvider currently mirrors the base-engine MR/BB
        # block. Production uses the richer MR-v2 implementation, so keep this
        # cached frame available for research/manifests but do not overwrite the
        # production MR-v2 arrays until that provider is migrated separately.
        self.prepared_context_features = context_features
        self.support_resistance_features = support_resistance_features
        self.research_features: dict[str, pd.DataFrame] = {}
        self.research_output_columns: tuple[str, ...] = ()
        self.research_feature_available_columns: tuple[str, ...] = ()
        super().__init__(
            *args,
            structural_benchmark=structural_benchmark,
            technical_features=technical_features,
            context_features=None,
            **kwargs,
        )

        self._configure_support_resistance_feature(support_resistance_features)
        self._configure_research_features(research_features or {})

    def _configure_support_resistance_feature(
        self,
        support_resistance_features: pd.DataFrame | None,
    ) -> None:
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

    def _configure_research_features(self, frames: Mapping[str, pd.DataFrame]) -> None:
        """Validate optional research-only frames aligned to strategy candles."""
        output_columns: list[str] = []
        available_columns: list[str] = []
        used: set[str] = set()
        for name in sorted(frames):
            frame = frames[name]
            prepared, data_times = self._aligned_feature_frame(
                self.data,
                frame,
                f"research feature {name}",
            )
            self._assert_causal_availability(
                prepared,
                data_times,
                self.config,
                f"research feature {name}",
            )
            columns = [column for column in prepared.columns if column not in _RESEARCH_META_COLUMNS]
            duplicates = sorted(used.intersection(columns))
            if duplicates:
                raise ValueError(
                    f"Research feature {name} duplicates output columns: {duplicates}"
                )
            used.update(columns)
            output_columns.extend(columns)
            available_name = f"{name}_feature_available_at"
            available_columns.append(available_name)
            self.research_features[name] = prepared
        self.research_output_columns = tuple(output_columns)
        self.research_feature_available_columns = tuple(available_columns)

    def _attach_research_features_to_pair(self, pair, indicator_index: int) -> None:
        """Freeze research values from the exact completed signal candle used."""
        pair.research_signal_index = int(indicator_index)
        pair.research_signal_candle_open_time = pd.Timestamp(self.times[indicator_index])
        pair.research_signal_available_at = (
            pd.Timestamp(self.times[indicator_index]) + self.entry_delta
        )
        for name, frame in self.research_features.items():
            row = frame.iloc[indicator_index]
            setattr(pair, f"{name}_feature_available_at", row["available_at"])
            for column in frame.columns:
                if column in _RESEARCH_META_COLUMNS:
                    continue
                setattr(pair, column, row[column])

    def _open_pair(
        self,
        i,
        entry_filter_passed=True,
        entry_filter_reason="Strategy profile passed",
        schedule=None,
    ):
        indicator_index = schedule["indicator_index"] if schedule else i
        previous_pair_id = self.next_pair_id
        super()._open_pair(i, entry_filter_passed, entry_filter_reason, schedule)
        if self.next_pair_id == previous_pair_id + 1 and self.active_pairs:
            self._attach_research_features_to_pair(self.active_pairs[-1], indicator_index)

    def _build_result_row(self, pair, row_kind, positions):
        row = super()._build_result_row(pair, row_kind, positions)
        row["research_signal_index"] = getattr(pair, "research_signal_index", np.nan)
        row["research_signal_candle_open_time"] = getattr(
            pair, "research_signal_candle_open_time", None
        )
        row["research_signal_available_at"] = getattr(
            pair, "research_signal_available_at", None
        )
        for column in self.research_feature_available_columns:
            row[column] = getattr(pair, column, None)
        for column in self.research_output_columns:
            row[column] = getattr(pair, column, np.nan)
        return row

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
