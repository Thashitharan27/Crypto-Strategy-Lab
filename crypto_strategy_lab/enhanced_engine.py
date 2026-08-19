"""Backtest engine extension for Bollinger + RSI mean-reversion telemetry."""
from __future__ import annotations

import numpy as np

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.indicators import lag, rsi
from crypto_strategy_lab.mean_reversion import distance_from_mean_atr
from crypto_strategy_lab.mean_reversion_v2 import (
    bb_zscore,
    bollinger_envelope,
    bollinger_reentry_flags,
    classify_bb_location,
    classify_rsi_state,
    classify_signal,
    moving_mean,
    signal_alignment,
    signal_direction,
)


class EnhancedBacktestEngine(BacktestEngine):
    """Preserve the trading engine and add record-only MR-v2 calculations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = self.config
        mean_type = str(getattr(config, "mean_reversion_mean_type", "EMA")).upper()
        period = int(config.mean_reversion_period)
        stddevs = float(getattr(config, "mean_reversion_bb_stddevs", 2.0))
        rsi_period = int(getattr(config, "mean_reversion_rsi_period", 14))
        oversold = float(getattr(config, "mean_reversion_rsi_oversold", 30.0))
        overbought = float(getattr(config, "mean_reversion_rsi_overbought", 70.0))

        self.mean_reversion_mean = moving_mean(self.close, period, mean_type)
        self.mean_reversion_distance_atr = distance_from_mean_atr(
            self.close, self.mean_reversion_mean, self.atr_values
        )
        self.mean_reversion_distance_atr_previous = lag(self.mean_reversion_distance_atr, 1)
        self.mean_reversion_sigma, self.mean_reversion_bb_upper, self.mean_reversion_bb_lower = bollinger_envelope(
            self.close, self.mean_reversion_mean, period, stddevs
        )
        self.mean_reversion_bb_zscore = bb_zscore(
            self.close, self.mean_reversion_mean, self.mean_reversion_sigma
        )
        self.mean_reversion_rsi_values = rsi(self.close, rsi_period)
        self.mean_reversion_long_reentry, self.mean_reversion_short_reentry = bollinger_reentry_flags(
            self.close,
            self.mean_reversion_bb_lower,
            self.mean_reversion_bb_upper,
            self.mean_reversion_rsi_values,
            oversold,
            overbought,
        )

    @staticmethod
    def _confirmed_alignment(reentry_direction: str, trade_direction: str | None) -> str:
        if reentry_direction not in ("LONG", "SHORT"):
            return "NO_SIGNAL"
        if trade_direction not in ("LONG", "SHORT"):
            return "UNKNOWN"
        return "AGREE" if trade_direction == reentry_direction else "DISAGREE"

    def _mean_reversion_snapshot(self, i, di_direction, trade_direction=None):
        result = super()._mean_reversion_snapshot(i, di_direction, trade_direction)
        config = self.config
        result.update(
            {
                "mean_reversion_mean_type": str(getattr(config, "mean_reversion_mean_type", "EMA")).upper(),
                "mean_reversion_bb_stddevs": float(getattr(config, "mean_reversion_bb_stddevs", 2.0)),
                "mean_reversion_rsi_period": int(getattr(config, "mean_reversion_rsi_period", 14)),
                "mean_reversion_rsi_oversold": float(getattr(config, "mean_reversion_rsi_oversold", 30.0)),
                "mean_reversion_rsi_overbought": float(getattr(config, "mean_reversion_rsi_overbought", 70.0)),
                "mean_reversion_require_reentry": bool(getattr(config, "mean_reversion_require_reentry", True)),
                "mean_reversion_track_atr_distance": bool(getattr(config, "mean_reversion_track_atr_distance", True)),
                "mean_reversion_track_motion": bool(getattr(config, "mean_reversion_track_motion", True)),
                "mean_reversion_bb_upper": np.nan,
                "mean_reversion_bb_lower": np.nan,
                "mean_reversion_bb_sigma": np.nan,
                "mean_reversion_bb_zscore": np.nan,
                "mean_reversion_bb_location": "UNKNOWN",
                "mean_reversion_rsi": np.nan,
                "mean_reversion_rsi_state": "UNKNOWN",
                "mean_reversion_long_reentry": False,
                "mean_reversion_short_reentry": False,
                "mean_reversion_reentry_confirmation": "NONE",
                "mean_reversion_signal": "UNKNOWN",
                "mean_reversion_signal_direction": "NONE",
                "mean_reversion_setup_strength": "UNKNOWN",
                "mean_reversion_distance_alignment": result.get("mean_reversion_alignment", "UNKNOWN"),
                "mean_reversion_signal_di_alignment": "UNKNOWN",
                "mean_reversion_signal_trade_alignment": "UNKNOWN",
                "bb_reentry": "NONE",
                "mr_signal": "NO_SIGNAL",
                "mr_signal_direction": "NONE",
                "mr_trade_alignment": "NO_SIGNAL",
            }
        )
        if not config.enable_mean_reversion_analysis:
            return result

        mean = float(self.mean_reversion_mean[i])
        upper = float(self.mean_reversion_bb_upper[i])
        lower = float(self.mean_reversion_bb_lower[i])
        sigma = float(self.mean_reversion_sigma[i])
        zscore = float(self.mean_reversion_bb_zscore[i])
        rsi_value = float(self.mean_reversion_rsi_values[i])
        close = float(self.close[i])
        long_reentry = bool(self.mean_reversion_long_reentry[i])
        short_reentry = bool(self.mean_reversion_short_reentry[i])
        oversold = float(getattr(config, "mean_reversion_rsi_oversold", 30.0))
        overbought = float(getattr(config, "mean_reversion_rsi_overbought", 70.0))
        require_reentry = bool(getattr(config, "mean_reversion_require_reentry", True))

        signal = classify_signal(
            close,
            lower,
            upper,
            rsi_value,
            oversold,
            overbought,
            long_reentry,
            short_reentry,
            require_reentry,
        )
        signal_dir = signal_direction(signal)
        di_alignment = signal_alignment(signal, di_direction)
        trade_alignment = signal_alignment(signal, trade_direction or di_direction)
        reentry_direction = "LONG" if long_reentry else ("SHORT" if short_reentry else "NONE")
        confirmed_signal = "CONFIRMED" if reentry_direction != "NONE" else "NO_SIGNAL"
        confirmed_trade_alignment = self._confirmed_alignment(
            reentry_direction, trade_direction or di_direction
        )

        result.update(
            {
                "mean_price": mean if np.isfinite(mean) else np.nan,
                "mean_reversion_bb_upper": upper if np.isfinite(upper) else np.nan,
                "mean_reversion_bb_lower": lower if np.isfinite(lower) else np.nan,
                "mean_reversion_bb_sigma": sigma if np.isfinite(sigma) else np.nan,
                "mean_reversion_bb_zscore": zscore if np.isfinite(zscore) else np.nan,
                "mean_reversion_bb_location": classify_bb_location(close, mean, lower, upper),
                "mean_reversion_rsi": rsi_value if np.isfinite(rsi_value) else np.nan,
                "mean_reversion_rsi_state": classify_rsi_state(rsi_value, oversold, overbought),
                "mean_reversion_long_reentry": long_reentry,
                "mean_reversion_short_reentry": short_reentry,
                "mean_reversion_reentry_confirmation": reentry_direction,
                "mean_reversion_signal": signal,
                "mean_reversion_signal_direction": signal_dir,
                "mean_reversion_setup_strength": "STRONG" if signal.startswith("STRONG_") else ("POTENTIAL" if signal.startswith("POTENTIAL_") else ("NEUTRAL" if signal == "NEUTRAL" else "UNKNOWN")),
                "mean_reversion_signal_di_alignment": di_alignment,
                "mean_reversion_signal_trade_alignment": trade_alignment,
                "bb_reentry": reentry_direction,
                "mr_signal": confirmed_signal,
                "mr_signal_direction": reentry_direction,
                "mr_trade_alignment": confirmed_trade_alignment,
                "mean_reversion_alignment": di_alignment,
                "mean_reversion_di_alignment": di_alignment,
                "mean_reversion_trade_alignment": trade_alignment,
            }
        )

        if not bool(getattr(config, "mean_reversion_track_atr_distance", True)):
            result.update(
                {
                    "mean_distance_atr": np.nan,
                    "mean_distance_atr_previous": np.nan,
                    "mean_distance_change_atr": np.nan,
                    "mean_reversion_state": "UNKNOWN",
                    "mean_reversion_strength": -1,
                    "mean_reversion_strength_label": "UNKNOWN",
                    "mean_reversion_distance_alignment": "UNKNOWN",
                }
            )
        if not bool(getattr(config, "mean_reversion_track_motion", True)):
            result["mean_distance_change_atr"] = np.nan
            result["mean_reversion_motion"] = "UNKNOWN"
        return result

    def _build_result_row(self, p, row_kind, positions):
        """Include all enhanced MR telemetry and simple confirmed aliases in trade_list.csv."""
        row = super()._build_result_row(p, row_kind, positions)
        fields = (
            "mean_reversion_mean_type",
            "mean_reversion_bb_stddevs",
            "mean_reversion_rsi_period",
            "mean_reversion_rsi_oversold",
            "mean_reversion_rsi_overbought",
            "mean_reversion_require_reentry",
            "mean_reversion_bb_upper",
            "mean_reversion_bb_lower",
            "mean_reversion_bb_sigma",
            "mean_reversion_bb_zscore",
            "mean_reversion_bb_location",
            "mean_reversion_rsi",
            "mean_reversion_rsi_state",
            "mean_reversion_long_reentry",
            "mean_reversion_short_reentry",
            "mean_reversion_reentry_confirmation",
            "mean_reversion_signal",
            "mean_reversion_signal_direction",
            "mean_reversion_setup_strength",
            "mean_reversion_distance_alignment",
            "mean_reversion_signal_di_alignment",
            "mean_reversion_signal_trade_alignment",
            "bb_reentry",
            "mr_signal",
            "mr_signal_direction",
            "mr_trade_alignment",
        )
        defaults = {
            "mean_reversion_bb_location": "UNKNOWN",
            "mean_reversion_rsi_state": "UNKNOWN",
            "mean_reversion_reentry_confirmation": "NONE",
            "mean_reversion_signal": "UNKNOWN",
            "mean_reversion_signal_direction": "NONE",
            "mean_reversion_setup_strength": "UNKNOWN",
            "mean_reversion_distance_alignment": "UNKNOWN",
            "mean_reversion_signal_di_alignment": "UNKNOWN",
            "mean_reversion_signal_trade_alignment": "UNKNOWN",
            "bb_reentry": "NONE",
            "mr_signal": "NO_SIGNAL",
            "mr_signal_direction": "NONE",
            "mr_trade_alignment": "NO_SIGNAL",
        }
        for field in fields:
            row[field] = getattr(p, field, defaults.get(field, np.nan))
        return row
