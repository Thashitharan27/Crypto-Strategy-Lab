"""Derive causal strategy warm-up windows for bounded research requests."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd


_SIGNAL_EMA_PERIOD = 200
_SIGNAL_EMA_SAFETY_BARS = 5
_MIN_STATE_CONTEXT_DAYS = 22


def strategy_warmup_period(run_config) -> pd.Timedelta:
    """Return the history required before the user-selected research start.

    The simulator still owns trade timing. This window only ensures that
    execution-relevant rolling features arrive at the selected start with the
    same causal history they would have inside a longer run.
    """

    data = run_config.data
    features = run_config.features
    strategy = run_config.strategy

    strategy_minutes = int(data.strategy_timeframe_minutes)
    strategy_interval = pd.Timedelta(minutes=strategy_minutes)

    bars = max(
        int(features.atr_period) + 5,
        int(features.adx_period) * 2 + 5,
        int(features.bb_period) + 5,
        int(features.mean_reversion_period) + 5,
        int(features.mean_reversion_rsi_period) + 5,
        int(features.di_pressure_lookback) + 5,
        _SIGNAL_EMA_PERIOD + _SIGNAL_EMA_SAFETY_BARS,
    )
    duration = strategy_interval * bars

    momentum_hours = max(
        (int(profile.momentum_lookback_hours) for profile in strategy.profiles.values()),
        default=24,
    )
    duration = max(
        duration,
        pd.Timedelta(hours=momentum_hours),
        pd.Timedelta(days=_MIN_STATE_CONTEXT_DAYS),
    )

    if bool(features.enable_support_resistance_analysis):
        configured_sr_minutes = int(
            features.sr_timeframe_minutes or strategy_minutes
        )
        independent_sr_minutes = [
            strategy_minutes,
            *(
                minutes
                for minutes in (60, 240, 1440)
                if minutes > strategy_minutes and minutes % strategy_minutes == 0
            ),
        ]
        # Independent S/R outputs must be fully warmed at the research boundary.
        # Each timeframe gets its own pivot/lookback horizon; using one shared bar
        # count for 15m and 1d would give those settings very different meanings.
        for sr_minutes in sorted({configured_sr_minutes, *independent_sr_minutes}):
            if hasattr(features, "sr_detection_parameters"):
                detection = features.sr_detection_parameters(sr_minutes)
                pivot_left = int(detection["sr_pivot_left"])
                pivot_right = int(detection["sr_pivot_right"])
                lookback_bars = int(detection["sr_lookback_bars"])
            else:
                pivot_left = int(features.sr_pivot_left)
                pivot_right = int(features.sr_pivot_right)
                lookback_bars = int(features.sr_lookback_bars)
            sr_bars = (
                lookback_bars
                + max(pivot_left, pivot_right)
                + (
                    int(features.sr_hold_confirmation_bars)
                    if bool(features.enable_sr_hold_confirmation)
                    else 0
                )
                + 5
            )
            duration = max(duration, pd.Timedelta(minutes=sr_minutes * sr_bars))

    if str(features.market_regime_method).upper() == "ASSET_RETURN":
        duration = max(
            duration,
            pd.Timedelta(days=int(features.bull_regime_lookback_days)),
        )

    # Two strategy bars cover previous-value / candle-close boundary consumers
    # without rounding the whole window up to additional calendar days.
    return duration + (strategy_interval * 2)


def expand_strategy_request(request, run_config, *, earliest_start=None):
    """Expand only the strategy-history start while preserving the research end."""

    requested_start = pd.Timestamp(request.start)
    if requested_start.tzinfo is None:
        requested_start = requested_start.tz_localize("UTC")
    else:
        requested_start = requested_start.tz_convert("UTC")

    desired_start = requested_start - strategy_warmup_period(run_config)
    if earliest_start is not None:
        earliest = pd.Timestamp(earliest_start)
        if earliest.tzinfo is None:
            earliest = earliest.tz_localize("UTC")
        else:
            earliest = earliest.tz_convert("UTC")
        desired_start = max(desired_start, earliest)

    if desired_start >= requested_start:
        return request
    return replace(request, start=desired_start.to_pydatetime())
