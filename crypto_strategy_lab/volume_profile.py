"""Causal rolling Volume Profile evidence for strategy rules.

The profile is built only from completed candles available before the decision
timestamp.  With OHLCV input, each candle's volume is distributed uniformly
across the price bins crossed by that candle.  This is an approximation of
volume-at-price (not tick-exact market profile); when raw trade data is absent it
preserves causality and keeps the feature usable across the existing Data Lake.

Higher-timeframe profiles are reconstructed only from complete, contiguous
strategy-candle buckets and become visible after the higher-timeframe bar closes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


VOLUME_PROFILE_RULE_INDICATORS = frozenset({
    "VP_POSITION",
    "VP_POC_DISTANCE_ATR",
    "VP_VAH_DISTANCE_ATR",
    "VP_VAL_DISTANCE_ATR",
    "VP_NEAR_HVN",
    "VP_HVN_DISTANCE_ATR",
    "VP_HVN_STRENGTH",
    "VP_ROOM_TO_OPPOSING_HVN_ATR",
    "VP_LOW_VOLUME_PATH_SCORE",
    "VP_VALUE_MIGRATION",
    "VP_ACCUMULATION_SCORE",
    "VP_DISTRIBUTION_SCORE",
    "VP_BUY_ABSORPTION",
    "VP_SELL_ABSORPTION",
})

DEFAULT_LOOKBACK_BARS = 120
DEFAULT_BINS = 48
DEFAULT_VALUE_AREA_FRACTION = 0.70
DEFAULT_HVN_MULTIPLIER = 1.50
DEFAULT_NEAR_HVN_ATR = 0.50
DEFAULT_PATH_R = 3.0


@dataclass(frozen=True)
class _ProfileInput:
    timestamp: np.ndarray
    end: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def _as_utc(values) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True))


def _completed_context(engine, timeframe_minutes: int) -> _ProfileInput | None:
    """Return strategy or complete higher-TF bars, cached on the engine."""
    config = getattr(engine, "config", None)
    strategy_minutes = int(getattr(config, "strategy_timeframe_minutes", 0) or 0)
    requested = int(timeframe_minutes or 0)
    if requested in {0, strategy_minutes}:
        requested = strategy_minutes
    if strategy_minutes <= 0 or requested < strategy_minutes:
        return None
    if requested % strategy_minutes:
        return None

    cache = getattr(engine, "_volume_profile_context_cache", None)
    if cache is None:
        cache = {}
        engine._volume_profile_context_cache = cache
    if requested in cache:
        return cache[requested]

    ts = _as_utc(engine.times)
    open_ = np.asarray(engine.open, dtype=float)
    high = np.asarray(engine.high, dtype=float)
    low = np.asarray(engine.low, dtype=float)
    close = np.asarray(engine.close, dtype=float)
    volume = np.asarray(engine.volume, dtype=float)

    if requested == strategy_minutes:
        result = _ProfileInput(
            timestamp=ts.to_numpy(),
            end=(ts + pd.Timedelta(minutes=strategy_minutes)).to_numpy(),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        cache[requested] = result
        return result

    expected = requested // strategy_minutes
    frame = pd.DataFrame({
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    frame["bucket"] = frame["timestamp"].dt.floor(f"{requested}min")
    rows = []
    for bucket, group in frame.groupby("bucket", sort=True):
        if len(group) != expected:
            continue
        expected_times = pd.date_range(
            bucket, periods=expected, freq=f"{strategy_minutes}min"
        )
        actual_times = pd.DatetimeIndex(group["timestamp"])
        if not actual_times.equals(expected_times):
            continue
        rows.append((
            bucket,
            bucket + pd.Timedelta(minutes=requested),
            float(group["open"].iloc[0]),
            float(group["high"].max()),
            float(group["low"].min()),
            float(group["close"].iloc[-1]),
            float(group["volume"].sum()),
        ))
    if not rows:
        return None

    result = _ProfileInput(
        timestamp=np.asarray([row[0] for row in rows], dtype="datetime64[ns]"),
        end=np.asarray([row[1] for row in rows], dtype="datetime64[ns]"),
        open=np.asarray([row[2] for row in rows], dtype=float),
        high=np.asarray([row[3] for row in rows], dtype=float),
        low=np.asarray([row[4] for row in rows], dtype=float),
        close=np.asarray([row[5] for row in rows], dtype=float),
        volume=np.asarray([row[6] for row in rows], dtype=float),
    )
    cache[requested] = result
    return result


def _histogram(low, high, volume, bins: int):
    finite = (
        np.isfinite(low) & np.isfinite(high) & np.isfinite(volume)
        & (volume >= 0.0) & (high >= low)
    )
    if not np.any(finite):
        return None
    low = low[finite]
    high = high[finite]
    volume = volume[finite]
    bottom = float(np.min(low))
    top = float(np.max(high))
    if not np.isfinite(bottom) or not np.isfinite(top) or top <= bottom:
        return None

    edges = np.linspace(bottom, top, int(bins) + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    profile = np.zeros(int(bins), dtype=float)

    # OHLCV approximation: distribute each completed candle's volume evenly
    # across every profile bin crossed by its high-low range.
    for lo, hi, vol in zip(low, high, volume):
        mask = (centers >= lo) & (centers <= hi)
        count = int(mask.sum())
        if count:
            profile[mask] += vol / count
        else:
            typical = 0.5 * (lo + hi)
            nearest = int(np.argmin(np.abs(centers - typical)))
            profile[nearest] += vol
    return edges, centers, profile


def _value_area(profile: np.ndarray, poc: int, fraction: float):
    total = float(np.sum(profile))
    if not np.isfinite(total) or total <= 0:
        return poc, poc
    target = total * float(fraction)
    left = right = int(poc)
    covered = float(profile[poc])
    while covered < target and (left > 0 or right < len(profile) - 1):
        left_value = profile[left - 1] if left > 0 else -1.0
        right_value = profile[right + 1] if right < len(profile) - 1 else -1.0
        if right_value > left_value:
            right += 1
            covered += float(profile[right])
        else:
            left -= 1
            covered += float(profile[left])
    return left, right


def _profile_poc(low, high, volume, bins):
    built = _histogram(low, high, volume, bins)
    if built is None:
        return np.nan
    _edges, centers, profile = built
    return float(centers[int(np.argmax(profile))])


def _score_rejection(open_, high, low, close, direction: str) -> float:
    if not len(close):
        return 0.0
    take = min(5, len(close))
    o = open_[-take:]
    h = high[-take:]
    l = low[-take:]
    c = close[-take:]
    rng = h - l
    valid = np.isfinite(rng) & (rng > 0) & np.isfinite(o) & np.isfinite(c)
    if not np.any(valid):
        return 0.0
    if direction == "LONG":
        wick = np.divide(
            np.minimum(o, c) - l,
            rng,
            out=np.zeros_like(rng),
            where=valid,
        )
    else:
        wick = np.divide(
            h - np.maximum(o, c),
            rng,
            out=np.zeros_like(rng),
            where=valid,
        )
    return float(np.clip(np.nanmean(wick[valid]), 0.0, 1.0))


def _profile_snapshot(engine, i: int, direction: str, timeframe_minutes: int):
    config = getattr(engine, "config", None)
    strategy_minutes = int(getattr(config, "strategy_timeframe_minutes", 0) or 0)
    requested = int(timeframe_minutes or 0)
    requested = strategy_minutes if requested in {0, strategy_minutes} else requested

    key = (int(i), str(direction).upper(), requested)
    cache = getattr(engine, "_volume_profile_snapshot_cache", None)
    if cache is None:
        cache = {}
        engine._volume_profile_snapshot_cache = cache
    if key in cache:
        return cache[key]

    context = _completed_context(engine, requested)
    if context is None or i < 0 or i >= len(engine.times):
        cache[key] = None
        return None

    now = _as_utc([engine.times[i]])[0]
    ends = _as_utc(context.end)
    stop = int(ends.searchsorted(now, side="right"))
    lookback = int(getattr(config, "volume_profile_lookback_bars", DEFAULT_LOOKBACK_BARS))
    bins = int(getattr(config, "volume_profile_bins", DEFAULT_BINS))
    value_fraction = float(
        getattr(config, "volume_profile_value_area_fraction", DEFAULT_VALUE_AREA_FRACTION)
    )
    lookback = max(20, lookback)
    bins = max(12, min(200, bins))
    value_fraction = float(np.clip(value_fraction, 0.50, 0.95))

    if stop < lookback:
        cache[key] = None
        return None
    start = stop - lookback
    sl = slice(start, stop)
    built = _histogram(context.low[sl], context.high[sl], context.volume[sl], bins)
    if built is None:
        cache[key] = None
        return None
    edges, centers, profile = built

    signal_index = max(0, i - 1)
    price = float(engine.close[signal_index])
    atr = float(engine.atr_values[signal_index])
    if not np.isfinite(price) or not np.isfinite(atr) or atr <= 0:
        cache[key] = None
        return None

    poc_i = int(np.argmax(profile))
    poc = float(centers[poc_i])
    va_left, va_right = _value_area(profile, poc_i, value_fraction)
    val = float(edges[va_left])
    vah = float(edges[va_right + 1])

    positive = profile[profile > 0]
    median = float(np.median(positive)) if len(positive) else 0.0
    hvn_threshold = median * DEFAULT_HVN_MULTIPLIER
    hvn_indices = np.flatnonzero(profile >= hvn_threshold) if hvn_threshold > 0 else np.array([], dtype=int)
    if len(hvn_indices):
        nearest_i = int(hvn_indices[np.argmin(np.abs(centers[hvn_indices] - price))])
        nearest_hvn = float(centers[nearest_i])
        hvn_distance = abs(price - nearest_hvn) / atr
        hvn_strength = float(profile[nearest_i] / max(float(np.max(profile)), 1e-12))
    else:
        nearest_i = -1
        nearest_hvn = np.nan
        hvn_distance = np.nan
        hvn_strength = 0.0

    direction = str(direction).upper()
    if direction == "LONG":
        opposing = hvn_indices[centers[hvn_indices] > price] if len(hvn_indices) else np.array([], dtype=int)
        target = price + DEFAULT_PATH_R * atr
        path_mask = (centers > price) & (centers <= target)
    else:
        opposing = hvn_indices[centers[hvn_indices] < price] if len(hvn_indices) else np.array([], dtype=int)
        target = price - DEFAULT_PATH_R * atr
        path_mask = (centers < price) & (centers >= target)

    if len(opposing):
        opposing_i = int(opposing[np.argmin(np.abs(centers[opposing] - price))])
        room = abs(float(centers[opposing_i]) - price) / atr
    else:
        room = np.inf

    path_values = profile[path_mask]
    if len(path_values) and median > 0:
        path_ratio = float(np.mean(path_values) / median)
        low_volume_path = float(np.clip(1.0 - path_ratio, 0.0, 1.0))
    else:
        low_volume_path = np.nan

    half = max(20, lookback // 2)
    old_stop = max(start, stop - half)
    old_start = max(0, old_stop - half)
    old_poc = _profile_poc(
        context.low[old_start:old_stop],
        context.high[old_start:old_stop],
        context.volume[old_start:old_stop],
        bins,
    )
    migration_delta = (poc - old_poc) / atr if np.isfinite(old_poc) else np.nan
    if not np.isfinite(migration_delta) or abs(migration_delta) < 0.25:
        migration = "FLAT"
    else:
        migration = "UP" if migration_delta > 0 else "DOWN"

    # Location-weighted concentration: strong accepted volume below current
    # price is accumulation-like; above price is distribution-like.
    max_profile = max(float(np.max(profile)), 1e-12)
    below = profile[centers <= price]
    above = profile[centers >= price]
    below_strength = float(np.max(below) / max_profile) if len(below) else 0.0
    above_strength = float(np.max(above) / max_profile) if len(above) else 0.0
    long_rejection = _score_rejection(
        context.open[sl], context.high[sl], context.low[sl], context.close[sl], "LONG"
    )
    short_rejection = _score_rejection(
        context.open[sl], context.high[sl], context.low[sl], context.close[sl], "SHORT"
    )
    accumulation = 100.0 * np.clip(
        0.55 * below_strength
        + 0.25 * (1.0 if migration == "UP" else 0.5 if migration == "FLAT" else 0.0)
        + 0.20 * long_rejection,
        0.0,
        1.0,
    )
    distribution = 100.0 * np.clip(
        0.55 * above_strength
        + 0.25 * (1.0 if migration == "DOWN" else 0.5 if migration == "FLAT" else 0.0)
        + 0.20 * short_rejection,
        0.0,
        1.0,
    )

    if price > vah:
        position = "ABOVE_VAH"
    elif price < val:
        position = "BELOW_VAL"
    else:
        position = "INSIDE_VALUE"

    buy_absorption = np.nan
    sell_absorption = np.nan
    reader = getattr(engine, "_prepared_research_raw_value", None)
    if callable(reader) and i > 0:
        raw_delta = reader(i - 1, "taker_flow_context", "taker_delta_pct")
        try:
            delta = float(raw_delta)
        except (TypeError, ValueError):
            delta = np.nan
        if np.isfinite(delta):
            near_value = (
                (np.isfinite(hvn_distance) and hvn_distance <= DEFAULT_NEAR_HVN_ATR)
                or abs(price - poc) / atr <= DEFAULT_NEAR_HVN_ATR
            )
            # Aggressive sellers failing to push accepted value lower => buy absorption.
            buy_absorption = float(near_value and delta < -0.05 and price >= val)
            # Aggressive buyers failing to push accepted value higher => sell absorption.
            sell_absorption = float(near_value and delta > 0.05 and price <= vah)

    result = {
        "VP_POSITION": position,
        "VP_POC_DISTANCE_ATR": (price - poc) / atr,
        "VP_VAH_DISTANCE_ATR": (price - vah) / atr,
        "VP_VAL_DISTANCE_ATR": (price - val) / atr,
        "VP_NEAR_HVN": bool(np.isfinite(hvn_distance) and hvn_distance <= DEFAULT_NEAR_HVN_ATR),
        "VP_HVN_DISTANCE_ATR": hvn_distance,
        "VP_HVN_STRENGTH": hvn_strength,
        "VP_ROOM_TO_OPPOSING_HVN_ATR": room,
        "VP_LOW_VOLUME_PATH_SCORE": low_volume_path,
        "VP_VALUE_MIGRATION": migration,
        "VP_ACCUMULATION_SCORE": float(accumulation),
        "VP_DISTRIBUTION_SCORE": float(distribution),
        "VP_BUY_ABSORPTION": buy_absorption,
        "VP_SELL_ABSORPTION": sell_absorption,
        "_poc": poc,
        "_vah": vah,
        "_val": val,
        "_nearest_hvn": nearest_hvn,
    }
    cache[key] = result
    return result


class VolumeProfileMixin:
    """Expose rolling Volume Profile evidence to the native rule engine."""

    def _volume_profile_rule_value(
        self, i, direction, indicator, timeframe_minutes=0
    ):
        if indicator not in VOLUME_PROFILE_RULE_INDICATORS:
            raise KeyError(indicator)
        snapshot = _profile_snapshot(
            self, int(i), str(direction).upper(), int(timeframe_minutes or 0)
        )
        if snapshot is None:
            return np.nan
        raw = snapshot.get(indicator)
        if indicator in {"VP_POSITION", "VP_VALUE_MIGRATION"}:
            from crypto_strategy_lab.strategy_rule_model import CATEGORICAL_VALUE_CODES
            return CATEGORICAL_VALUE_CODES[indicator].get(str(raw).upper(), np.nan)
        if indicator in {"VP_NEAR_HVN"}:
            return 1.0 if bool(raw) else 0.0
        if indicator in {"VP_BUY_ABSORPTION", "VP_SELL_ABSORPTION"}:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return np.nan
            return value if np.isfinite(value) else np.nan
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return np.nan
        return value if np.isfinite(value) or np.isinf(value) else np.nan
