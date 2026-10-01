"""High-resolution causal Volume Profile from compact aggTrade volume-at-price."""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import pandas as pd


PROFILE_CONTEXTS = (60, 240, 1440)
PROFILE_FIELDS = (
    "position",
    "poc_distance_atr",
    "vah_distance_atr",
    "val_distance_atr",
    "near_hvn",
    "hvn_distance_atr",
    "hvn_strength",
    "room_long_atr",
    "room_short_atr",
    "low_volume_path_long",
    "low_volume_path_short",
    "value_migration",
    "accumulation_score",
    "distribution_score",
)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def _decode_bins(payload: object, log_step: float) -> dict[int, float]:
    if payload is None or payload is pd.NA:
        return {}
    try:
        rows = json.loads(str(payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    result: dict[int, float] = defaultdict(float)
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            price = float(row[0])
            volume = float(row[1])
        except (TypeError, ValueError):
            continue
        if not np.isfinite(price) or price <= 0 or not np.isfinite(volume) or volume <= 0:
            continue
        key = int(math.floor(math.log(price) / log_step))
        result[key] += volume
    return dict(result)


def _parquet_payload_rows(
    paths: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    """Stream minute volume-at-price payloads from compact Parquet caches.

    The full JSON column is intentionally never materialized into pandas.
    Separate forward iterators can be used for window entry/eviction so exact
    profiles remain bounded by the active price-bin map rather than history size.
    """
    if not paths:
        return
    # Preserve the aggregate loader's "last partition wins" precedence
    # explicitly. read_parquet(...)+any_value() is not deterministic when daily
    # and monthly archives overlap, and separate add/remove scans must make the
    # same choice for exact profile arithmetic.
    scans = []
    for partition_order, path in enumerate(paths):
        escaped = str(path).replace("'", "''")
        scans.append(
            "SELECT available_at, volume_at_price_json, "
            f"{partition_order} AS partition_order "
            f"FROM read_parquet('{escaped}') "
            "WHERE available_at >= ? AND available_at <= ?"
        )
    union_sql = " UNION ALL ".join(scans)
    parameters = []
    for _ in paths:
        parameters.extend([start.to_pydatetime(), end.to_pydatetime()])

    spill_root = Path(paths[0]).parent / "_duckdb_spill"
    spill_root.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(prefix="exact-profile-", dir=spill_root)
    connection = duckdb.connect()
    spill = str(Path(temporary.name)).replace("'", "''")
    try:
        connection.execute("SET memory_limit='512MB'")
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute(f"SET temp_directory='{spill}'")
        cursor = connection.execute(
            f"""
            SELECT available_at, volume_at_price_json
            FROM ({union_sql})
            QUALIFY row_number() OVER (
                PARTITION BY available_at
                ORDER BY partition_order DESC
            ) = 1
            ORDER BY available_at
            """,
            parameters,
        )
        while True:
            rows = cursor.fetchmany(4096)
            if not rows:
                break
            for available_at, payload in rows:
                yield pd.Timestamp(available_at, tz="UTC") if getattr(available_at, "tzinfo", None) is None else pd.Timestamp(available_at).tz_convert("UTC"), payload
    finally:
        connection.close()
        temporary.cleanup()


def _snapshot(
    bins: dict[int, float],
    *,
    price: float,
    atr: float,
    log_step: float,
    previous_poc: float | None,
    value_fraction: float,
    hvn_multiplier: float,
    near_hvn_atr: float,
    path_r: float,
):
    if not bins or not np.isfinite(price) or not np.isfinite(atr) or atr <= 0:
        return None
    keys = np.fromiter(bins.keys(), dtype=np.int64)
    volumes = np.fromiter((bins[int(k)] for k in keys), dtype=float)
    valid = np.isfinite(volumes) & (volumes > 0)
    keys, volumes = keys[valid], volumes[valid]
    if not len(keys):
        return None
    order = np.argsort(keys)
    keys, volumes = keys[order], volumes[order]
    centers = np.exp((keys.astype(float) + 0.5) * log_step)

    poc_index = int(np.argmax(volumes))
    poc = float(centers[poc_index])
    target = float(volumes.sum()) * float(value_fraction)
    left = right = poc_index
    covered = float(volumes[poc_index])
    while covered < target and (left > 0 or right < len(volumes) - 1):
        lv = volumes[left - 1] if left > 0 else -1.0
        rv = volumes[right + 1] if right < len(volumes) - 1 else -1.0
        if rv > lv:
            right += 1
            covered += float(volumes[right])
        else:
            left -= 1
            covered += float(volumes[left])
    val, vah = float(centers[left]), float(centers[right])

    median = float(np.median(volumes))
    max_volume = max(float(np.max(volumes)), 1e-12)
    hvn_mask = volumes >= median * float(hvn_multiplier)
    hvn_prices = centers[hvn_mask]
    hvn_volumes = volumes[hvn_mask]
    if len(hvn_prices):
        nearest = int(np.argmin(np.abs(hvn_prices - price)))
        nearest_hvn = float(hvn_prices[nearest])
        hvn_distance = abs(price - nearest_hvn) / atr
        hvn_strength = float(hvn_volumes[nearest] / max_volume)
        above = hvn_prices[hvn_prices > price]
        below = hvn_prices[hvn_prices < price]
        room_long = (float(np.min(above)) - price) / atr if len(above) else np.inf
        room_short = (price - float(np.max(below))) / atr if len(below) else np.inf
    else:
        nearest_hvn = np.nan
        hvn_distance = np.nan
        hvn_strength = np.nan
        room_long = room_short = np.inf

    def path_score(long_side: bool) -> float:
        target_price = price + path_r * atr if long_side else price - path_r * atr
        mask = (
            (centers > price) & (centers <= target_price)
            if long_side
            else (centers < price) & (centers >= target_price)
        )
        values = volumes[mask]
        if not len(values) or median <= 0:
            return np.nan
        return float(np.clip(1.0 - float(np.mean(values)) / median, 0.0, 1.0))

    if previous_poc is None or not np.isfinite(previous_poc):
        migration = "FLAT"
    else:
        delta = (poc - previous_poc) / atr
        migration = "UP" if delta > 0.25 else "DOWN" if delta < -0.25 else "FLAT"

    below_strength = float(np.max(volumes[centers <= price]) / max_volume) if np.any(centers <= price) else 0.0
    above_strength = float(np.max(volumes[centers >= price]) / max_volume) if np.any(centers >= price) else 0.0
    accumulation = 100.0 * np.clip(
        0.70 * below_strength + 0.30 * (1.0 if migration == "UP" else 0.5 if migration == "FLAT" else 0.0),
        0.0, 1.0,
    )
    distribution = 100.0 * np.clip(
        0.70 * above_strength + 0.30 * (1.0 if migration == "DOWN" else 0.5 if migration == "FLAT" else 0.0),
        0.0, 1.0,
    )
    position = "ABOVE_VAH" if price > vah else "BELOW_VAL" if price < val else "INSIDE_VALUE"
    return {
        "position": position,
        "poc": poc,
        "poc_distance_atr": (price - poc) / atr,
        "vah_distance_atr": (price - vah) / atr,
        "val_distance_atr": (price - val) / atr,
        "near_hvn": float(np.isfinite(hvn_distance) and hvn_distance <= near_hvn_atr),
        "hvn_distance_atr": hvn_distance,
        "hvn_strength": hvn_strength,
        "room_long_atr": room_long,
        "room_short_atr": room_short,
        "low_volume_path_long": path_score(True),
        "low_volume_path_short": path_score(False),
        "value_migration": migration,
        "accumulation_score": float(accumulation),
        "distribution_score": float(distribution),
        "nearest_hvn": nearest_hvn,
    }


def exact_profile_frame(
    aggregate: pd.DataFrame,
    strategy: pd.DataFrame,
    *,
    strategy_minutes: int,
    atr_period: int = 14,
    lookback_bars: int = 120,
    bin_bps: float = 5.0,
    value_fraction: float = 0.70,
    hvn_multiplier: float = 1.50,
    near_hvn_atr: float = 0.50,
    path_r: float = 3.0,
) -> pd.DataFrame:
    """Return exact-price-source VP evidence aligned to strategy decisions."""
    result = pd.DataFrame(index=np.arange(len(strategy)))
    for prefix in ("strategy", "1h", "4h", "1d"):
        for field in PROFILE_FIELDS:
            column = f"vp_exact_{prefix}_{field}"
            if field in {"position", "value_migration"}:
                result[column] = pd.Series(
                    [None] * len(strategy), index=result.index, dtype=object
                )
            else:
                result[column] = np.nan
    required_strategy = {"available_at", "open", "high", "low", "close"}
    parquet_paths = tuple(
        str(path)
        for path in aggregate.attrs.get("volume_at_price_parquet_paths", ())
    )
    inline_payloads = "volume_at_price_json" in aggregate.columns
    if (
        not required_strategy.issubset(strategy.columns)
        or (not inline_payloads and not parquet_paths)
    ):
        return result
    minute_end = pd.DatetimeIndex(pd.to_datetime(aggregate["available_at"], utc=True))
    payloads = (
        aggregate["volume_at_price_json"].reset_index(drop=True)
        if inline_payloads
        else None
    )
    decision = pd.DatetimeIndex(pd.to_datetime(strategy["available_at"], utc=True))
    close = pd.to_numeric(strategy["close"], errors="coerce").to_numpy(float)
    atr = _atr(strategy, atr_period).to_numpy(float)
    log_step = math.log1p(float(bin_bps) / 10000.0)
    if log_step <= 0:
        raise ValueError("volume profile bin_bps must be positive")

    contexts = [strategy_minutes, *[m for m in PROFILE_CONTEXTS if m >= strategy_minutes and m % strategy_minutes == 0]]
    contexts = list(dict.fromkeys(contexts))
    for minutes in contexts:
        prefix = "strategy" if minutes == strategy_minutes else {60:"1h",240:"4h",1440:"1d"}[minutes]
        window_minutes = int(lookback_bars) * int(minutes)
        active: dict[int, float] = defaultdict(float)
        left = right = 0
        add_rows = remove_rows = None
        next_add = next_remove = None
        if parquet_paths and len(minute_end):
            range_start = pd.Timestamp(minute_end[0])
            range_end = pd.Timestamp(minute_end[-1])
            add_rows = _parquet_payload_rows(parquet_paths, range_start, range_end)
            remove_rows = _parquet_payload_rows(parquet_paths, range_start, range_end)
            next_add = next(add_rows, None)
            next_remove = next(remove_rows, None)
        previous_context_poc = None
        current_anchor = None
        current_anchor_poc = None
        for i, when in enumerate(decision):
            anchor = when.floor(f"{minutes}min")
            if current_anchor is None or anchor != current_anchor:
                if current_anchor_poc is not None and np.isfinite(current_anchor_poc):
                    previous_context_poc = current_anchor_poc
                current_anchor = anchor
                window_start = anchor - pd.Timedelta(minutes=window_minutes)
                if parquet_paths:
                    while next_add is not None and next_add[0] <= anchor:
                        bins = _decode_bins(next_add[1], log_step)
                        for key, value in bins.items():
                            active[key] += value
                        next_add = next(add_rows, None)
                    while next_remove is not None and next_remove[0] <= window_start:
                        bins = _decode_bins(next_remove[1], log_step)
                        for key, value in bins.items():
                            updated = active.get(key, 0.0) - value
                            if updated <= 1e-12:
                                active.pop(key, None)
                            else:
                                active[key] = updated
                        next_remove = next(remove_rows, None)
                else:
                    while right < len(minute_end) and minute_end[right] <= anchor:
                        bins = _decode_bins(payloads.iat[right], log_step)
                        for key, value in bins.items():
                            active[key] += value
                        right += 1
                    while left < right and minute_end[left] <= window_start:
                        bins = _decode_bins(payloads.iat[left], log_step)
                        for key, value in bins.items():
                            updated = active.get(key, 0.0) - value
                            if updated <= 1e-12:
                                active.pop(key, None)
                            else:
                                active[key] = updated
                        left += 1

            # The accepted-volume structure is fixed until the next completed
            # context bucket, but distance/location remains relative to the
            # current strategy decision price and ATR.
            snap = _snapshot(
                active, price=close[i], atr=atr[i], log_step=log_step,
                previous_poc=previous_context_poc, value_fraction=value_fraction,
                hvn_multiplier=hvn_multiplier, near_hvn_atr=near_hvn_atr,
                path_r=path_r,
            )
            if snap is None:
                continue
            current_anchor_poc = snap["poc"]
            for field in PROFILE_FIELDS:
                result.loc[i, f"vp_exact_{prefix}_{field}"] = snap[field]
        if add_rows is not None:
            add_rows.close()
        if remove_rows is not None:
            remove_rows.close()
    return result
