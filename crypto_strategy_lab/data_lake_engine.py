"""Execution engine adapter for the Data Lake v2 pipeline.

The legacy ``BacktestEngine`` still calculates several indicators internally.
This forward adapter injects versioned Data Lake feature outputs so ATR, ADX/DMI
and DI-pressure history are prepared once before simulator execution. Structural
regime data is likewise supplied by the caller rather than resolved from files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import crypto_strategy_lab.engine as engine_module
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.features.market_regime import structural_regime_values


_REQUIRED_TECHNICAL_COLUMNS = {
    "timestamp",
    "available_at",
    "atr",
    "atr_pct",
    "adx",
    "plus_di",
    "minus_di",
    "di_spread",
    "di_spread_1",
    "di_spread_3",
    "di_spread_5",
    "di_spread_change",
    "di_ratio",
    "plus_di_change",
    "minus_di_change",
    "di_pressure_spread_change",
    "long_directional_di_change",
    "long_opposing_di_change",
    "long_di_pressure_state",
    "short_directional_di_change",
    "short_opposing_di_change",
    "short_di_pressure_state",
}


class DataLakeBacktestEngine(BacktestEngine):
    """BacktestEngine with market regime and core indicators supplied externally."""

    def __init__(
        self,
        *args,
        structural_benchmark: pd.DataFrame | None = None,
        technical_features: pd.DataFrame | None = None,
        **kwargs,
    ):
        self.structural_benchmark = structural_benchmark
        self.technical_features = technical_features

        if technical_features is None:
            # Kept as a diagnostic fallback while the migration branch is open.
            # The Data Lake bundle always supplies prepared features.
            super().__init__(*args, **kwargs)
            self.technical_feature_source = "legacy_engine_fallback"
            return

        data = args[0] if args else kwargs.get("data")
        config = args[1] if len(args) > 1 else kwargs.get("config")
        if data is None or config is None:
            raise TypeError("DataLakeBacktestEngine requires strategy data and config")
        features = self._validate_technical_features(data, config, technical_features)
        self.technical_features = features

        # BacktestEngine imports atr/adx as module globals. Bind those two calls
        # to prepared arrays only during construction, then restore immediately.
        # This preserves the mature simulator without recalculating the features.
        original_atr = engine_module.atr
        original_adx = engine_module.adx
        prepared_atr = features["atr"].to_numpy(float)
        prepared_adx = features["adx"].to_numpy(float)
        prepared_plus = features["plus_di"].to_numpy(float)
        prepared_minus = features["minus_di"].to_numpy(float)
        expected_atr_period = int(features.attrs["atr_period"])
        expected_adx_period = int(features.attrs["adx_period"])

        def _atr_from_features(_high, _low, _close, period=14):
            if int(period) != expected_atr_period:
                raise ValueError(
                    f"Prepared ATR period is {expected_atr_period}, engine requested {period}"
                )
            return prepared_atr.copy()

        def _adx_from_features(_high, _low, _close, period=14):
            if int(period) != expected_adx_period:
                raise ValueError(
                    f"Prepared ADX period is {expected_adx_period}, engine requested {period}"
                )
            return prepared_adx.copy(), prepared_plus.copy(), prepared_minus.copy()

        engine_module.atr = _atr_from_features
        engine_module.adx = _adx_from_features
        try:
            super().__init__(*args, **kwargs)
        finally:
            engine_module.atr = original_atr
            engine_module.adx = original_adx

        # Use the provider's derived arrays as the source of truth as well. This
        # removes repeated lag/ratio calculations from each simulator instance.
        self.atr_values = prepared_atr
        self.adx_values = prepared_adx
        self.plus_di_values = prepared_plus
        self.minus_di_values = prepared_minus
        self.atr_pct_values = features["atr_pct"].to_numpy(float)
        self.di_spread = features["di_spread"].to_numpy(float)
        self.di_spread_1 = features["di_spread_1"].to_numpy(float)
        self.di_spread_3 = features["di_spread_3"].to_numpy(float)
        self.di_spread_5 = features["di_spread_5"].to_numpy(float)
        self.di_spread_change = features["di_spread_change"].to_numpy(float)
        self.di_ratio = features["di_ratio"].to_numpy(float)
        self.technical_feature_source = (
            f"{features.attrs.get('feature_name', 'core_directional')}@"
            f"{features.attrs.get('feature_version', 'unknown')}"
        )

    @staticmethod
    def _validate_technical_features(data, config, technical_features: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(_REQUIRED_TECHNICAL_COLUMNS - set(technical_features.columns))
        if missing:
            raise ValueError(f"Prepared technical feature frame is missing columns: {missing}")
        if len(data) != len(technical_features):
            raise ValueError(
                "Prepared technical feature rows do not match strategy rows: "
                f"{len(technical_features)} != {len(data)}"
            )

        features = technical_features.reset_index(drop=True).copy()
        data_times = pd.to_datetime(data["timestamp"], utc=True).reset_index(drop=True)
        feature_times = pd.to_datetime(features["timestamp"], utc=True).reset_index(drop=True)
        if not data_times.equals(feature_times):
            raise ValueError("Prepared technical feature timestamps do not match strategy candles")

        atr_period = int(features.attrs.get("atr_period", -1))
        adx_period = int(features.attrs.get("adx_period", -1))
        pressure_lookback = int(features.attrs.get("di_pressure_lookback", -1))
        if atr_period != int(config.atr_period):
            raise ValueError(f"Prepared ATR period {atr_period} != config {config.atr_period}")
        if adx_period != int(config.adx_period):
            raise ValueError(f"Prepared ADX period {adx_period} != config {config.adx_period}")
        if pressure_lookback != int(config.di_pressure_lookback):
            raise ValueError(
                f"Prepared DI pressure lookback {pressure_lookback} != config {config.di_pressure_lookback}"
            )

        available = pd.to_datetime(features["available_at"], utc=True)
        candle_end = data_times + pd.Timedelta(minutes=int(config.strategy_timeframe_minutes))
        if bool((available > candle_end).any()):
            raise ValueError("Prepared technical feature uses data unavailable at candle completion")
        return features

    def _di_pressure_snapshot(self, i, direction):
        """Read precomputed causal DI-pressure telemetry for one signal candle."""
        if self.technical_features is None:
            return super()._di_pressure_snapshot(i, direction)

        row = self.technical_features.iloc[i]
        plus = float(row["plus_di"])
        minus = float(row["minus_di"])
        lookback = int(self.config.di_pressure_lookback)
        result = {
            "plus_di": plus,
            "minus_di": minus,
            "directional_di": np.nan,
            "opposing_di": np.nan,
            "plus_di_change": np.nan,
            "minus_di_change": np.nan,
            "directional_di_change": np.nan,
            "opposing_di_change": np.nan,
            "di_spread": float(row["di_spread"]),
            "di_spread_change": np.nan,
            "di_pressure_state": "UNKNOWN",
            "di_pressure_lookback": lookback,
        }
        if direction not in ("LONG", "SHORT") or not np.isfinite(plus) or not np.isfinite(minus):
            return result

        if direction == "LONG":
            result["directional_di"] = plus
            result["opposing_di"] = minus
            directional_change = float(row["long_directional_di_change"])
            opposing_change = float(row["long_opposing_di_change"])
            pressure_state = str(row["long_di_pressure_state"])
        else:
            result["directional_di"] = minus
            result["opposing_di"] = plus
            directional_change = float(row["short_directional_di_change"])
            opposing_change = float(row["short_opposing_di_change"])
            pressure_state = str(row["short_di_pressure_state"])

        if not self.config.enable_di_pressure_analysis:
            return result
        plus_change = float(row["plus_di_change"])
        minus_change = float(row["minus_di_change"])
        spread_change = float(row["di_pressure_spread_change"])
        if not np.isfinite(plus_change) or not np.isfinite(minus_change):
            return result

        result["plus_di_change"] = plus_change
        result["minus_di_change"] = minus_change
        result["directional_di_change"] = directional_change
        result["opposing_di_change"] = opposing_change
        result["di_spread_change"] = spread_change
        result["di_pressure_state"] = pressure_state
        return result

    def _market_regime_array(self):
        if self.config.market_regime_method == "ASSET_RETURN":
            threshold = abs(float(self.config.bull_regime_return_threshold))
            return np.array(
                [
                    None
                    if not np.isfinite(value)
                    else (
                        "BULL"
                        if value >= threshold
                        else ("BEAR" if value <= -threshold else "SIDEWAYS")
                    )
                    for value in self.bull_regime_return_values
                ],
                dtype=object,
            )

        if self.structural_benchmark is None or self.structural_benchmark.empty:
            label = "Asset" if self.config.market_regime_method == "ASSET_STRUCTURAL" else "BTC"
            raise ValueError(
                f"{label} structural regime requires a prepared Data Lake benchmark frame"
            )

        return structural_regime_values(
            self.times,
            self.structural_benchmark,
            sma_days=int(self.config.structural_regime_sma_days),
            slope_lookback_days=int(self.config.structural_regime_slope_lookback_days),
        )
