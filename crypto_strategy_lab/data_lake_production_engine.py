"""Production simulator composition for Data Lake v2.

The feature-injection adapter and the mature enhanced/SR-dynamic execution engine
are deliberately composed rather than forked. This preserves current strategy
semantics while stateless features migrate out of the simulator in small slices.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

import crypto_strategy_lab.enhanced_engine as enhanced_engine_module
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

_REQUIRED_PRODUCTION_CONTEXT_COLUMNS = {
    "timestamp",
    "available_at",
    "mean_reversion_sigma",
    "mean_reversion_bb_upper",
    "mean_reversion_bb_lower",
    "mean_reversion_bb_zscore",
    "mean_reversion_rsi",
    "mean_reversion_long_reentry",
    "mean_reversion_short_reentry",
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
        self.prepared_context_features = context_features
        self.support_resistance_features = support_resistance_features
        self.research_features: dict[str, pd.DataFrame] = {}
        self.research_output_columns: tuple[str, ...] = ()
        self.research_feature_available_columns: tuple[str, ...] = ()

        data = args[0] if args else kwargs.get("data")
        config = args[1] if len(args) > 1 else kwargs.get("config")
        if data is None or config is None:
            raise TypeError("DataLakeProductionBacktestEngine requires strategy data and config")

        production_context = (
            self._validate_production_context(data, config, context_features)
            if context_features is not None
            else None
        )

        originals = None
        if production_context is not None:
            originals = self._install_enhanced_context_shims(config, production_context)
        try:
            super().__init__(
                *args,
                structural_benchmark=structural_benchmark,
                technical_features=technical_features,
                context_features=production_context,
                **kwargs,
            )
        finally:
            if originals is not None:
                self._restore_enhanced_context_shims(originals)

        if production_context is not None:
            # The enhanced engine is still the semantic authority; these arrays
            # are simply the precomputed values it would have produced itself.
            self.prepared_context_features = production_context
            self.mean_reversion_mean = production_context["mean_reversion_mean"].to_numpy(float)
            self.mean_reversion_distance_atr = production_context[
                "mean_reversion_distance_atr"
            ].to_numpy(float)
            self.mean_reversion_distance_atr_previous = production_context[
                "mean_reversion_distance_atr_previous"
            ].to_numpy(float)
            self.mean_reversion_sigma = production_context["mean_reversion_sigma"].to_numpy(float)
            self.mean_reversion_bb_upper = production_context[
                "mean_reversion_bb_upper"
            ].to_numpy(float)
            self.mean_reversion_bb_lower = production_context[
                "mean_reversion_bb_lower"
            ].to_numpy(float)
            self.mean_reversion_bb_zscore = production_context[
                "mean_reversion_bb_zscore"
            ].to_numpy(float)
            self.mean_reversion_rsi_values = production_context[
                "mean_reversion_rsi"
            ].to_numpy(float)
            self.mean_reversion_long_reentry = production_context[
                "mean_reversion_long_reentry"
            ].to_numpy(bool)
            self.mean_reversion_short_reentry = production_context[
                "mean_reversion_short_reentry"
            ].to_numpy(bool)
            self.context_feature_source = (
                f"{production_context.attrs.get('feature_name', 'production_market_context')}@"
                f"{production_context.attrs.get('feature_version', 'unknown')}"
            )

        self._configure_support_resistance_feature(support_resistance_features)
        self._configure_research_features(research_features or {})

    @classmethod
    def _validate_production_context(cls, data, config, frame: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(_REQUIRED_PRODUCTION_CONTEXT_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError(f"Prepared production context is missing columns: {missing}")
        prepared, data_times = cls._aligned_feature_frame(data, frame, "production market context")
        cls._assert_causal_availability(prepared, data_times, config, "production market context")

        expected = {
            "bb_period": int(config.bb_period),
            "bb_stddevs": float(config.bb_stddevs),
            "mean_reversion_period": int(config.mean_reversion_period),
            "mean_reversion_mean_type": str(getattr(config, "mean_reversion_mean_type", "SMA")).upper(),
            "mean_reversion_bb_stddevs": float(getattr(config, "mean_reversion_bb_stddevs", 2.0)),
            "mean_reversion_rsi_period": int(getattr(config, "mean_reversion_rsi_period", 14)),
            "mean_reversion_rsi_oversold": float(getattr(config, "mean_reversion_rsi_oversold", 30.0)),
            "mean_reversion_rsi_overbought": float(getattr(config, "mean_reversion_rsi_overbought", 70.0)),
        }
        for name, wanted in expected.items():
            actual = prepared.attrs.get(name)
            if isinstance(wanted, float):
                if actual is None or not np.isclose(float(actual), wanted):
                    raise ValueError(f"Prepared production context {name} does not match config")
            elif str(actual) != str(wanted):
                raise ValueError(f"Prepared production context {name} does not match config")
        return prepared

    @staticmethod
    def _install_enhanced_context_shims(config, context: pd.DataFrame):
        """Feed cached MR-v2 arrays through EnhancedBacktestEngine construction."""
        originals = (
            enhanced_engine_module.moving_mean,
            enhanced_engine_module.distance_from_mean_atr,
            enhanced_engine_module.bollinger_envelope,
            enhanced_engine_module.bb_zscore,
            enhanced_engine_module.rsi,
            enhanced_engine_module.bollinger_reentry_flags,
        )
        mean = context["mean_reversion_mean"].to_numpy(float)
        distance = context["mean_reversion_distance_atr"].to_numpy(float)
        sigma = context["mean_reversion_sigma"].to_numpy(float)
        upper = context["mean_reversion_bb_upper"].to_numpy(float)
        lower = context["mean_reversion_bb_lower"].to_numpy(float)
        zscore = context["mean_reversion_bb_zscore"].to_numpy(float)
        rsi_values = context["mean_reversion_rsi"].to_numpy(float)
        long_reentry = context["mean_reversion_long_reentry"].to_numpy(bool)
        short_reentry = context["mean_reversion_short_reentry"].to_numpy(bool)

        expected_period = int(config.mean_reversion_period)
        expected_mean_type = str(getattr(config, "mean_reversion_mean_type", "SMA")).upper()
        expected_stddevs = float(getattr(config, "mean_reversion_bb_stddevs", 2.0))
        expected_rsi_period = int(getattr(config, "mean_reversion_rsi_period", 14))
        expected_oversold = float(getattr(config, "mean_reversion_rsi_oversold", 30.0))
        expected_overbought = float(getattr(config, "mean_reversion_rsi_overbought", 70.0))

        def _moving_mean(_values, period, mean_type="SMA"):
            if int(period) != expected_period or str(mean_type).upper() != expected_mean_type:
                raise ValueError("Prepared MR mean settings do not match enhanced engine request")
            return mean.copy()

        def _distance(_close, _mean, _atr):
            return distance.copy()

        def _envelope(_values, _mean, period, stddevs=2.0):
            if int(period) != expected_period or not np.isclose(float(stddevs), expected_stddevs):
                raise ValueError("Prepared MR Bollinger settings do not match enhanced engine request")
            return sigma.copy(), upper.copy(), lower.copy()

        def _zscore(_close, _mean, _sigma):
            return zscore.copy()

        def _rsi(_values, period):
            if int(period) != expected_rsi_period:
                raise ValueError("Prepared MR RSI period does not match enhanced engine request")
            return rsi_values.copy()

        def _reentry(_close, _lower, _upper, _rsi, oversold, overbought):
            if not np.isclose(float(oversold), expected_oversold) or not np.isclose(
                float(overbought), expected_overbought
            ):
                raise ValueError("Prepared MR RSI thresholds do not match enhanced engine request")
            return long_reentry.copy(), short_reentry.copy()

        enhanced_engine_module.moving_mean = _moving_mean
        enhanced_engine_module.distance_from_mean_atr = _distance
        enhanced_engine_module.bollinger_envelope = _envelope
        enhanced_engine_module.bb_zscore = _zscore
        enhanced_engine_module.rsi = _rsi
        enhanced_engine_module.bollinger_reentry_flags = _reentry
        return originals

    @staticmethod
    def _restore_enhanced_context_shims(originals) -> None:
        (
            enhanced_engine_module.moving_mean,
            enhanced_engine_module.distance_from_mean_atr,
            enhanced_engine_module.bollinger_envelope,
            enhanced_engine_module.bb_zscore,
            enhanced_engine_module.rsi,
            enhanced_engine_module.bollinger_reentry_flags,
        ) = originals

    def _mean_reversion_snapshot(self, i, di_direction, trade_direction=None):
        """Preserve the mature enhanced MR-v2 snapshot using prepared arrays."""
        return SRDynamicTPBacktestEngine._mean_reversion_snapshot(
            self, i, di_direction, trade_direction
        )

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
