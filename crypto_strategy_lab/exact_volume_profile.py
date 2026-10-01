"""High-resolution causal Volume Profile from compact aggTrade volume-at-price."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import pandas as pd

from .progress import emit_progress


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


EXACT_PROFILE_CACHE_FORMAT_VERSION = 1
EXACT_PROFILE_ALGORITHM_VERSION = 1


def _exact_profile_cache_descriptor(
    aggregate: pd.DataFrame,
    strategy: pd.DataFrame,
    *,
    strategy_minutes: int,
    atr_period: int,
    lookback_bars: int,
    bin_bps: float,
    value_fraction: float,
    hvn_multiplier: float,
    near_hvn_atr: float,
    path_r: float,
):
    """Return a stable shared-cache descriptor, or None when provenance is incomplete.

    The cache intentionally excludes Entry/Veto/Flip rules and the rest of the
    strategy configuration. Exact VP depends only on immutable aggTrade
    volume-at-price evidence, strategy OHLCV, timeframe, and VP construction
    parameters. This lets many filter experiments reuse one expensive profile.
    """
    root = aggregate.attrs.get("exact_volume_profile_cache_root")
    scope = aggregate.attrs.get("exact_volume_profile_cache_scope")
    strategy_source = aggregate.attrs.get(
        "exact_volume_profile_strategy_source_identity"
    )
    parquet_paths = tuple(
        str(path)
        for path in aggregate.attrs.get("volume_at_price_parquet_paths", ())
    )
    if not root or not isinstance(scope, dict) or not strategy_source or not parquet_paths:
        return None

    source_partitions = []
    for order, path_text in enumerate(parquet_paths):
        path = Path(path_text)
        manifest = path.with_suffix(".json")
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            fingerprint = metadata["source_fingerprint"]
            schema_version = metadata["aggregate_schema_version"]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            # Never reuse a shared cache when immutable source provenance cannot
            # be established. The exact profile can still be calculated normally.
            return None
        source_partitions.append(
            {
                "order": order,
                "source_fingerprint": str(fingerprint),
                "aggregate_schema_version": int(schema_version),
                "source_period_start": metadata.get("source_period_start"),
                "source_period_end": metadata.get("source_period_end"),
            }
        )

    decisions = pd.to_datetime(strategy["available_at"], utc=True, errors="coerce")
    if decisions.isna().any() or not len(decisions):
        return None

    params = {
        "strategy_minutes": int(strategy_minutes),
        "atr_period": int(atr_period),
        "lookback_bars": int(lookback_bars),
        "bin_bps": float(bin_bps),
        "value_fraction": float(value_fraction),
        "hvn_multiplier": float(hvn_multiplier),
        "near_hvn_atr": float(near_hvn_atr),
        "path_r": float(path_r),
    }
    payload = {
        "cache_format_version": EXACT_PROFILE_CACHE_FORMAT_VERSION,
        "algorithm_version": EXACT_PROFILE_ALGORITHM_VERSION,
        "scope": {
            "exchange": str(scope.get("exchange", "")),
            "market": str(scope.get("market", "")),
            "symbol": str(scope.get("symbol", "")),
            "strategy_interval": str(scope.get("strategy_interval", "")),
        },
        "strategy_source_identity": str(strategy_source),
        "decision_start": pd.Timestamp(decisions.iloc[0]).isoformat(),
        "decision_end": pd.Timestamp(decisions.iloc[-1]).isoformat(),
        "row_count": int(len(strategy)),
        "parameters": params,
        "source_partitions": source_partitions,
    }
    key = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    directory = (
        Path(root)
        / "exact_volume_profile"
        / f"v{EXACT_PROFILE_CACHE_FORMAT_VERSION}"
        / payload["scope"]["market"]
        / payload["scope"]["symbol"]
        / payload["scope"]["strategy_interval"]
    )
    return key, directory / f"{key}.parquet", directory / f"{key}.json", payload


def _load_exact_profile_cache(descriptor):
    if descriptor is None:
        return None
    key, parquet, manifest, payload = descriptor
    if not parquet.is_file() or not manifest.is_file():
        return None
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            metadata.get("cache_format_version") != EXACT_PROFILE_CACHE_FORMAT_VERSION
            or metadata.get("algorithm_version") != EXACT_PROFILE_ALGORITHM_VERSION
            or metadata.get("cache_key") != key
            or metadata.get("identity") != payload
        ):
            return None
        spill_root = parquet.parent / "_duckdb_spill"
        spill_root.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(prefix="exact-vp-cache-", dir=spill_root)
        con = duckdb.connect()
        spill = str(Path(temporary.name)).replace("'", "''")
        try:
            con.execute("SET memory_limit='512MB'")
            con.execute("SET threads=1")
            con.execute("SET preserve_insertion_order=false")
            con.execute(f"SET temp_directory='{spill}'")
            frame = con.read_parquet(str(parquet)).df()
        finally:
            con.close()
            temporary.cleanup()
        expected_columns = {
            f"vp_exact_{prefix}_{field}"
            for prefix in ("strategy", "1h", "4h", "1d")
            for field in PROFILE_FIELDS
        }
        if len(frame) != int(payload["row_count"]) or set(frame.columns) != expected_columns:
            return None
        frame.attrs["exact_volume_profile_cache_hit"] = True
        frame.attrs["exact_volume_profile_cache_key"] = key
        return frame
    except Exception:
        # Shared VP cache is disposable. Corrupt/incomplete entries are misses.
        return None


def _store_exact_profile_cache(descriptor, frame: pd.DataFrame) -> None:
    if descriptor is None:
        return
    key, parquet, manifest, payload = descriptor
    parquet.parent.mkdir(parents=True, exist_ok=True)
    temp_parquet = parquet.with_suffix(".tmp.parquet")
    temp_manifest = manifest.with_suffix(".tmp.json")
    temp_parquet.unlink(missing_ok=True)
    temp_manifest.unlink(missing_ok=True)

    spill_root = parquet.parent / "_duckdb_spill"
    spill_root.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(prefix="exact-vp-cache-", dir=spill_root)
    con = duckdb.connect()
    spill = str(Path(temporary.name)).replace("'", "''")
    try:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET threads=1")
        con.execute("SET preserve_insertion_order=false")
        con.execute(f"SET temp_directory='{spill}'")
        con.register("exact_profile_frame", frame)
        escaped = str(temp_parquet).replace("'", "''")
        con.execute(
            f"COPY exact_profile_frame TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        con.unregister("exact_profile_frame")
    finally:
        con.close()
        temporary.cleanup()

    metadata = {
        "cache_format_version": EXACT_PROFILE_CACHE_FORMAT_VERSION,
        "algorithm_version": EXACT_PROFILE_ALGORITHM_VERSION,
        "cache_key": key,
        "identity": payload,
    }
    temp_manifest.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temp_parquet.replace(parquet)
    temp_manifest.replace(manifest)


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


def _partition_time_ranges(paths: tuple[str, ...]):
    """Return cached source coverage for each aggregate partition.

    Trade-aggregate manifests already record immutable source period bounds, so
    Exact Volume Profile can skip every partition that cannot overlap the
    current chunk instead of opening all historical Parquets repeatedly.
    """
    ranges = []
    for order, path_text in enumerate(paths):
        path = Path(path_text)
        manifest = path.with_suffix(".json")
        start = end = None
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            raw_start = metadata.get("source_period_start")
            raw_end = metadata.get("source_period_end")
            if raw_start:
                start = pd.Timestamp(raw_start)
                if start.tzinfo is None:
                    start = start.tz_localize("UTC")
                else:
                    start = start.tz_convert("UTC")
            if raw_end:
                end = pd.Timestamp(raw_end)
                if end.tzinfo is None:
                    end = end.tz_localize("UTC")
                else:
                    end = end.tz_convert("UTC")
        except Exception:
            # Old/corrupt manifests remain usable; they are treated as
            # potentially overlapping every chunk rather than silently skipped.
            start = end = None
        ranges.append((order, path, start, end))
    return ranges


def _parquet_payload_rows(
    paths: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    """Stream exact volume-at-price payloads with bounded memory.

    The historical range is processed one day at a time, but only Parquet
    partitions whose cached source period overlaps that day are opened. Later
    partitions overwrite duplicate minutes, preserving the existing precedence
    contract without re-scanning the full partition catalog for every day.
    """
    if not paths:
        return

    chunk_span = pd.Timedelta(days=1)
    exclusive_end = pd.Timestamp(end) + pd.Timedelta(minutes=1)
    chunk_start = pd.Timestamp(start)
    partition_ranges = _partition_time_ranges(paths)
    total_chunks = max(
        1,
        int(math.ceil((exclusive_end - chunk_start) / chunk_span)),
    )
    completed_chunks = 0
    progress = getattr(_parquet_payload_rows, "_progress_callback", None)

    spill_root = Path(paths[0]).parent / "_duckdb_spill"
    spill_root.mkdir(parents=True, exist_ok=True)

    while chunk_start < exclusive_end:
        chunk_end = min(chunk_start + chunk_span, exclusive_end)
        by_minute: dict[pd.Timestamp, object] = {}

        relevant = []
        for order, path, period_start, period_end in partition_ranges:
            if period_start is not None and period_end is not None:
                if period_end <= chunk_start or period_start >= chunk_end:
                    continue
            relevant.append((order, path))

        for _order, path in relevant:
            temporary = TemporaryDirectory(prefix="exact-profile-", dir=spill_root)
            connection = duckdb.connect()
            spill = str(Path(temporary.name)).replace("'", "''")
            try:
                connection.execute("SET memory_limit='512MB'")
                connection.execute("SET threads=1")
                connection.execute("SET preserve_insertion_order=false")
                connection.execute(f"SET temp_directory='{spill}'")
                cursor = connection.execute(
                    """
                    SELECT available_at, volume_at_price_json
                    FROM read_parquet(?)
                    WHERE available_at >= ? AND available_at < ?
                    """,
                    [
                        str(path),
                        chunk_start.to_pydatetime(),
                        chunk_end.to_pydatetime(),
                    ],
                )
                while True:
                    rows = cursor.fetchmany(64)
                    if not rows:
                        break
                    for available_at, payload in rows:
                        timestamp = (
                            pd.Timestamp(available_at, tz="UTC")
                            if getattr(available_at, "tzinfo", None) is None
                            else pd.Timestamp(available_at).tz_convert("UTC")
                        )
                        by_minute[timestamp] = payload
            finally:
                connection.close()
                temporary.cleanup()

        for timestamp in sorted(by_minute):
            yield timestamp, by_minute[timestamp]

        completed_chunks += 1
        emit_progress(
            progress,
            kind="cache",
            phase="exact_volume_profile",
            label="Exact Volume Profile",
            completed=completed_chunks,
            total=total_chunks,
            current=f"{chunk_start.date()} -> {chunk_end.date()}",
            detail=(
                f"Processed {completed_chunks}/{total_chunks} day-chunks; "
                f"scanned {len(relevant)} relevant aggregate partition(s)."
            ),
        )
        by_minute.clear()
        chunk_start = chunk_end

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
    _parquet_payload_rows._progress_callback = aggregate.attrs.get(
        "progress_callback"
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

    cache_descriptor = _exact_profile_cache_descriptor(
        aggregate,
        strategy,
        strategy_minutes=strategy_minutes,
        atr_period=atr_period,
        lookback_bars=lookback_bars,
        bin_bps=bin_bps,
        value_fraction=value_fraction,
        hvn_multiplier=hvn_multiplier,
        near_hvn_atr=near_hvn_atr,
        path_r=path_r,
    )
    cached = _load_exact_profile_cache(cache_descriptor)
    if cached is not None:
        emit_progress(
            aggregate.attrs.get("progress_callback"),
            kind="cache",
            phase="exact_volume_profile",
            label="Exact Volume Profile",
            completed=1,
            total=1,
            built=0,
            reused=1,
            current="Shared Exact Volume Profile cache reused",
            detail="Entry/Veto/Flip filters do not rebuild this cached profile.",
        )
        return cached

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

    _store_exact_profile_cache(cache_descriptor, result)
    if cache_descriptor is not None:
        result.attrs["exact_volume_profile_cache_hit"] = False
        result.attrs["exact_volume_profile_cache_key"] = cache_descriptor[0]
        emit_progress(
            aggregate.attrs.get("progress_callback"),
            kind="cache",
            phase="exact_volume_profile",
            label="Exact Volume Profile",
            completed=1,
            total=1,
            built=1,
            reused=0,
            current="Shared Exact Volume Profile cache saved",
            detail="Future runs with the same symbol/timeframe/VP inputs can reuse it.",
        )
    return result
