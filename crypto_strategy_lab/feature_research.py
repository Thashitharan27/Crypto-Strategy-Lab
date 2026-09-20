"""Immutable feature-research artifacts and artifact-only DuckDB queries."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping

import duckdb
import pandas as pd


FEATURE_RESEARCH_ARTIFACT_CONTRACT = "feature_research_v1"
FEATURE_RESEARCH_ARTIFACT_VERSION = 1
REQUIRED_TRADE_COLUMNS = {
    "pair_id",
    "side",
    "entry_time",
    "exit_time",
    "pair_net_pnl",
    "pair_net_r",
    "research_signal_index",
    "research_signal_candle_open_time",
    "research_signal_available_at",
}
REQUIRED_CONTEXT_COLUMNS = {
    "strategy_index",
    "strategy_candle_open_time",
    "decision_available_at",
}
SR_ZONE_ARTIFACT_COLUMNS = (
    "strategy_index",
    "strategy_candle_open_time",
    "decision_available_at",
    "sr_timeframe",
    "sr_timeframe_minutes",
    "sr_completed_candle_time",
    "zone_id",
    "structure",
    "zone_low",
    "zone_high",
    "anchor_price",
    "pivot_bar_index",
    "confirmed_at_index",
    "source_bar_indices_json",
    "source_count",
    "touch_count",
    "validation_rejection_atr",
    "state",
    "tested",
    "held",
    "rejection_atr",
    "test_count",
    "bars_since_test",
    "last_test_index",
    "distance_price",
    "distance_atr",
    "near",
    "inside",
    "nearest",
)

# Lossless compact storage for completed-run S/R zone inventories.
SR_ZONE_SNAPSHOT_STORAGE_CONTRACT = "SNAPSHOT_JSON_V3"
SR_ZONE_SNAPSHOT_COLUMNS = (
    "strategy_index",
    "strategy_candle_open_time",
    "decision_available_at",
    "sr_timeframe",
    "sr_timeframe_minutes",
    "sr_completed_candle_time",
    "zone_count",
    "zone_inventory_json",
    "snapshot_sha256",
)

DEFAULT_METRICS = (
    "trades",
    "wins",
    "losses",
    "breakeven",
    "win_rate",
    "net_r",
    "avg_r",
    "net_pnl",
    "avg_pnl",
)


class ResearchArtifactError(ValueError):
    """A completed run research artifact is absent, corrupt, or inconsistent."""


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_TRADE_FINGERPRINT_COLUMNS = (
    "pair_id",
    "side",
    "entry_time",
    "exit_time",
    "pair_net_pnl",
    "pair_net_r",
    "research_signal_index",
    "research_signal_candle_open_time",
    "research_signal_available_at",
)
_TRADE_FINGERPRINT_DATETIME_COLUMNS = (
    "entry_time",
    "exit_time",
    "research_signal_candle_open_time",
    "research_signal_available_at",
)


def _canonical_identifier(value: Any) -> str:
    if pd.isna(value):
        return "<NA>"
    if isinstance(value, bool):
        return str(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isfinite(numeric) and numeric.is_integer():
        return str(int(numeric))
    return str(value)


def _trade_fingerprint(trades: pd.DataFrame) -> str:
    """Hash stable completed-trade semantics, not pandas/Parquet rendering details."""
    missing = set(_TRADE_FINGERPRINT_COLUMNS) - set(trades.columns)
    if missing:
        raise ResearchArtifactError(
            f"trade fingerprint missing required columns: {sorted(missing)}"
        )

    canonical = pd.DataFrame(index=range(len(trades)))
    canonical["pair_id"] = [
        _canonical_identifier(value) for value in trades["pair_id"].tolist()
    ]
    canonical["side"] = (
        trades["side"].astype("string").fillna("<NA>").str.upper().tolist()
    )

    for column in _TRADE_FINGERPRINT_DATETIME_COLUMNS:
        values = pd.to_datetime(trades[column], utc=True, errors="coerce")
        if bool(values.isna().any()):
            raise ResearchArtifactError(
                f"trade fingerprint contains invalid timestamp values: {column}"
            )
        canonical[column] = [str(pd.Timestamp(value).value) for value in values]

    for column in ("pair_net_pnl", "pair_net_r"):
        values = pd.to_numeric(trades[column], errors="coerce").to_numpy(float)
        if not all(math.isfinite(float(value)) for value in values):
            raise ResearchArtifactError(
                f"trade fingerprint contains non-finite numeric values: {column}"
            )
        canonical[column] = [float(value).hex() for value in values]

    signal_index = pd.to_numeric(
        trades["research_signal_index"], errors="coerce"
    ).to_numpy(float)
    if not all(
        math.isfinite(float(value)) and float(value).is_integer()
        for value in signal_index
    ):
        raise ResearchArtifactError(
            "trade fingerprint contains invalid research_signal_index values"
        )
    canonical["research_signal_index"] = [
        str(int(value)) for value in signal_index
    ]

    payload = json.dumps(
        canonical.loc[:, _TRADE_FINGERPRINT_COLUMNS].to_dict(orient="records"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def feature_context_frame(prepared) -> pd.DataFrame:
    """Flatten values already present in PreparedBacktestFrame without calculation."""
    values: dict[str, Any] = {
        "strategy_index": range(len(prepared)),
        "strategy_candle_open_time": prepared.timestamp,
        "decision_available_at": prepared.decision_available_at,
    }
    reserved = set(values)
    research_parity_columns: set[str] = set()

    excluded = {
        "timestamp",
        "strategy_interval",
        "decision_available_at",
        "research",
        "momentum_returns_by_hours",
        "open",
        "high",
        "low",
        "volume",
    }
    for field in fields(prepared):
        if field.name in excluded:
            continue
        candidate = getattr(prepared, field.name)
        if getattr(candidate, "ndim", None) != 1:
            continue
        if field.name in reserved:
            raise ResearchArtifactError(
                f"feature context column collision: {field.name}"
            )
        values[field.name] = candidate
        reserved.add(field.name)

    for hours, candidate in sorted(prepared.momentum_returns_by_hours.items()):
        name = f"momentum_return_{int(hours)}h"
        if name in reserved:
            raise ResearchArtifactError(f"feature context column collision: {name}")
        values[name] = candidate
        reserved.add(name)

    for block in prepared.research:
        available = f"{block.name}_feature_available_at"
        if available in reserved:
            raise ResearchArtifactError(
                f"feature context column collision: {available}"
            )
        values[available] = block.available_at
        reserved.add(available)
        research_parity_columns.add(available)
        for name, candidate in block.values.items():
            if name in reserved:
                raise ResearchArtifactError(
                    f"feature context column collision: {name}"
                )
            values[name] = candidate
            reserved.add(name)
            research_parity_columns.add(name)

    frame = pd.DataFrame(values)
    frame.attrs["research_parity_columns"] = tuple(sorted(research_parity_columns))
    return frame


def _empty_sr_zone_frame() -> pd.DataFrame:
    result = pd.DataFrame(
        {name: pd.Series(dtype="object") for name in SR_ZONE_SNAPSHOT_COLUMNS}
    )
    result["strategy_index"] = pd.Series(dtype="int64")
    result["sr_timeframe_minutes"] = pd.Series(dtype="int64")
    result["zone_count"] = pd.Series(dtype="int64")
    result["sr_timeframe"] = pd.Series(dtype="string")
    result["zone_inventory_json"] = pd.Series(dtype="string")
    result["snapshot_sha256"] = pd.Series(dtype="string")
    for name in (
        "strategy_candle_open_time",
        "decision_available_at",
        "sr_completed_candle_time",
    ):
        result[name] = pd.Series(dtype="datetime64[ns]")
    result = result.loc[:, SR_ZONE_SNAPSHOT_COLUMNS].copy()
    result.attrs["expanded_zone_rows"] = 0
    result.attrs["storage_contract"] = SR_ZONE_SNAPSHOT_STORAGE_CONTRACT
    return result


def _validate_sr_zone_inventory(
    zones: list[Any],
    *,
    inventory_column: str,
) -> None:
    """Validate every logical zone once, before persistence.

    Compact snapshots are parsed while they are already in memory. Performing
    the full semantic validation here avoids reparsing the same JSON after the
    parquet write while preserving the same all-zone quality guarantees.
    """
    seen: set[str] = set()
    nearest = {"SUPPORT": 0, "RESISTANCE": 0}
    for zone in zones:
        if not isinstance(zone, dict):
            raise ResearchArtifactError(
                f"S/R zone inventory row must be an object: {inventory_column}"
            )
        zone_id = str(zone.get("zone_id") or "").strip()
        structure = str(zone.get("structure") or "").upper()
        if not zone_id or zone_id in seen:
            raise ResearchArtifactError(
                f"S/R snapshot contains empty or duplicate zone identity: {inventory_column}"
            )
        seen.add(zone_id)
        if structure not in nearest:
            raise ResearchArtifactError(
                f"S/R snapshot contains invalid structure: {inventory_column}"
            )
        low = zone.get("zone_low")
        high = zone.get("zone_high")
        try:
            inverted = low is None or high is None or float(low) > float(high)
        except (TypeError, ValueError) as exc:
            raise ResearchArtifactError(
                f"S/R snapshot contains invalid zone geometry: {inventory_column}"
            ) from exc
        if inverted:
            raise ResearchArtifactError(
                f"S/R snapshot contains inverted zone geometry: {inventory_column}"
            )
        try:
            source_count = int(zone.get("source_count", 0) or 0)
            test_count = int(zone.get("test_count", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ResearchArtifactError(
                f"S/R snapshot contains invalid counters: {inventory_column}"
            ) from exc
        if source_count < 1:
            raise ResearchArtifactError(
                f"S/R snapshot contains invalid source_count: {inventory_column}"
            )
        if test_count < 0:
            raise ResearchArtifactError(
                f"S/R snapshot contains invalid test_count: {inventory_column}"
            )
        if bool(zone.get("nearest")):
            nearest[structure] += 1
    if any(count > 1 for count in nearest.values()):
        raise ResearchArtifactError(
            f"S/R snapshot contains multiple nearest zones for one side: {inventory_column}"
        )


def _sr_zone_inventory_frame(
    feature_context: pd.DataFrame,
    *,
    strategy_interval: str,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Persist exact per-candle S/R inventory snapshots without global expansion.

    Every detector-produced zone dictionary remains in zone_inventory_json.
    Consumers expand only the requested window, so geometry, lifecycle state,
    counters, distance fields, near/inside/nearest flags, and source pivots are
    preserved without creating one parquet row per active zone per candle.
    """
    strategy_minutes = int(pd.Timedelta(strategy_interval).total_seconds() // 60)
    specs = (
        ("strategy", strategy_minutes),
        ("1h", 60),
        ("4h", 240),
        ("1d", 1440),
    )
    records: list[dict[str, Any]] = []
    expanded_zone_rows = 0
    consumed: list[str] = (
        ["zone_inventory_json"]
        if "zone_inventory_json" in feature_context.columns
        else []
    )

    for label, minutes in specs:
        inventory_column = f"sr_{label}_zone_inventory_json"
        if inventory_column not in feature_context.columns:
            continue
        consumed.append(inventory_column)
        completed_column = f"sr_{label}_completed_candle_time"
        for row in feature_context.itertuples(index=False):
            payload = getattr(row, inventory_column, None)
            if payload is None or pd.isna(payload):
                continue
            payload_text = str(payload).strip()
            if not payload_text or payload_text == "[]":
                continue
            try:
                zones = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise ResearchArtifactError(
                    f"invalid S/R zone inventory JSON in {inventory_column}"
                ) from exc
            if not isinstance(zones, list):
                raise ResearchArtifactError(
                    f"S/R zone inventory must be a list: {inventory_column}"
                )
            _validate_sr_zone_inventory(
                zones,
                inventory_column=inventory_column,
            )
            zone_count = len(zones)
            if zone_count == 0:
                continue
            expanded_zone_rows += zone_count
            records.append(
                {
                    "strategy_index": int(getattr(row, "strategy_index")),
                    "strategy_candle_open_time": getattr(
                        row, "strategy_candle_open_time"
                    ),
                    "decision_available_at": getattr(row, "decision_available_at"),
                    "sr_timeframe": label,
                    "sr_timeframe_minutes": int(minutes),
                    "sr_completed_candle_time": (
                        getattr(row, completed_column)
                        if completed_column in feature_context.columns
                        else pd.NaT
                    ),
                    "zone_count": zone_count,
                    "zone_inventory_json": payload_text,
                    "snapshot_sha256": hashlib.sha256(
                        payload_text.encode("utf-8")
                    ).hexdigest(),
                }
            )

    if not records:
        return _empty_sr_zone_frame(), tuple(consumed)

    frame = pd.DataFrame.from_records(records, columns=SR_ZONE_SNAPSHOT_COLUMNS)
    for name in (
        "strategy_candle_open_time",
        "decision_available_at",
        "sr_completed_candle_time",
    ):
        parsed = pd.to_datetime(frame[name], utc=True, errors="coerce")
        frame[name] = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    frame["strategy_index"] = pd.to_numeric(
        frame["strategy_index"], errors="raise"
    ).astype("int64")
    frame["sr_timeframe_minutes"] = pd.to_numeric(
        frame["sr_timeframe_minutes"], errors="raise"
    ).astype("int64")
    frame["zone_count"] = pd.to_numeric(
        frame["zone_count"], errors="raise"
    ).astype("int64")
    frame["sr_timeframe"] = frame["sr_timeframe"].astype("string")
    frame["zone_inventory_json"] = frame["zone_inventory_json"].astype("string")
    frame["snapshot_sha256"] = frame["snapshot_sha256"].astype("string")
    frame = frame.loc[:, SR_ZONE_SNAPSHOT_COLUMNS].copy()
    frame.attrs["expanded_zone_rows"] = int(expanded_zone_rows)
    frame.attrs["storage_contract"] = SR_ZONE_SNAPSHOT_STORAGE_CONTRACT
    return frame, tuple(consumed)


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".parquet", dir=path.parent
    )
    os.close(fd)
    escaped = name.replace("'", "''")
    try:
        connection = duckdb.connect()
        try:
            connection.register("artifact_frame", frame)
            connection.execute(
                f"COPY artifact_frame TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            actual = connection.execute(
                f"SELECT count(*) FROM read_parquet('{escaped}')"
            ).fetchone()[0]
        finally:
            connection.close()
        if int(actual) != len(frame):
            raise ResearchArtifactError(
                "temporary parquet row count validation failed"
            )
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _validate_input_trades(trades: pd.DataFrame) -> None:
    missing = REQUIRED_TRADE_COLUMNS - set(trades.columns)
    if missing:
        raise ResearchArtifactError(
            f"completed trades missing required columns: {sorted(missing)}"
        )
    numeric_r = pd.to_numeric(trades["pair_net_r"], errors="coerce")
    if not numeric_r.map(math.isfinite).all():
        raise ResearchArtifactError(
            "pair_net_r must be finite for every completed trade"
        )


def _empty_trade_schema(trades: pd.DataFrame) -> pd.DataFrame:
    """Give zero-trade runs a deterministic queryable minimum schema."""
    result = trades.copy()
    numeric = {"pair_net_pnl", "pair_net_r", "research_signal_index"}
    datetime_columns = {
        "entry_time",
        "exit_time",
        "research_signal_candle_open_time",
        "research_signal_available_at",
    }
    for column in REQUIRED_TRADE_COLUMNS - set(result.columns):
        if column in numeric:
            result[column] = pd.Series(dtype="float64")
        elif column in datetime_columns:
            result[column] = pd.Series(dtype="datetime64[ns, UTC]")
        else:
            result[column] = pd.Series(dtype="string")
    # Empty object columns can otherwise be inferred as INTEGER by DuckDB.
    # Normalize the fields used by SQL expressions even when the simulator
    # returned a zero-row frame with an existing but untyped column.
    result["side"] = result["side"].astype("string")
    return result


def write_research_artifacts(run_dir: Path, result, context, *, authoritative_layout: bool = False) -> dict[str, Any]:
    """Publish immutable Parquets derived only from this already-completed run."""
    started = time.perf_counter()
    run_dir = Path(run_dir)
    research_dir = run_dir / ("artifacts" if authoritative_layout else "research")
    research_dir.mkdir(parents=True, exist_ok=True)

    trades = result.trades.copy()
    if trades.empty:
        trades = _empty_trade_schema(trades)
    _validate_input_trades(trades)

    feature_context = feature_context_frame(context.prepared)
    if len(feature_context) != len(context.prepared):
        raise ResearchArtifactError(
            "feature context row count differs from prepared frame"
        )
    sr_zones, inventory_columns = _sr_zone_inventory_frame(
        feature_context,
        strategy_interval=result.request.strategy_interval,
    )
    research_parity = set(feature_context.attrs.get("research_parity_columns", ()))
    if inventory_columns:
        feature_context = feature_context.drop(columns=list(inventory_columns))
        research_parity.difference_update(inventory_columns)

    parity_candidates = research_parity
    parity_columns = sorted(parity_candidates & set(trades.columns))

    trades_path = research_dir / "trades.parquet"
    context_path = research_dir / "feature_context.parquet"
    sr_zones_path = research_dir / "sr_zones.parquet"

    _write_parquet_atomic(trades, trades_path)
    _write_parquet_atomic(feature_context, context_path)
    _write_parquet_atomic(sr_zones, sr_zones_path)

    request = result.request
    manifest = {
        "artifact_contract": FEATURE_RESEARCH_ARTIFACT_CONTRACT,
        "artifact_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_artifact_schema_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
        "request": {
            "symbol": request.symbol,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "strategy_interval": request.strategy_interval,
            "intrabar_interval": request.intrabar_interval,
        },
        "prepared_cache_key": result.prepared_cache_key,
        "feature_cache_identities": result.feature_cache_metadata,
        "research_feature_identities": {
            name: metadata
            for name, metadata in result.feature_cache_metadata.items()
            if name not in {"core_directional", "production_market_context"}
        },
        "trade_row_count": len(trades),
        "feature_context_row_count": len(feature_context),
        "sr_zone_row_count": len(sr_zones),
        "sr_zone_expanded_row_count": int(
            sr_zones.attrs.get("expanded_zone_rows", len(sr_zones))
        ),
        "sr_zone_storage_contract": str(
            sr_zones.attrs.get(
                "storage_contract", SR_ZONE_SNAPSHOT_STORAGE_CONTRACT
            )
        ),
        "trade_columns": list(trades.columns),
        "feature_context_columns": list(feature_context.columns),
        "trade_context_parity_columns": parity_columns,
        "trades_parquet": "trades.parquet",
        "context_parquet": "feature_context.parquet",
        "sr_zones_parquet": "sr_zones.parquet",
        "trade_fingerprint": _trade_fingerprint(trades),
        "trade_fingerprint_contract": "completed_trade_semantics_v1",
        "artifact_sha256": {
            "trades": _file_sha256(trades_path),
            "feature_context": _file_sha256(context_path),
            "sr_zones": _file_sha256(sr_zones_path),
        },
        "artifact_sizes_bytes": {
            "trades": trades_path.stat().st_size,
            "feature_context": context_path.stat().st_size,
            "sr_zones": sr_zones_path.stat().st_size,
        },
        "artifact_write_seconds": time.perf_counter() - started,
    }
    if not authoritative_layout:
        _atomic_json(research_dir / "research_manifest.json", manifest)
    return manifest


@dataclass(frozen=True)
class ResearchDimension:
    column: str
    alias: str | None = None
    boundaries: tuple[float, ...] | None = None


@dataclass(frozen=True)
class ResearchFilter:
    column: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class ResearchQuerySpec:
    dimensions: tuple[ResearchDimension, ...] = ()
    filters: tuple[ResearchFilter, ...] = ()
    metrics: tuple[str, ...] = DEFAULT_METRICS

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchQuerySpec":
        return cls(
            dimensions=tuple(
                ResearchDimension(
                    item["column"],
                    item.get("alias"),
                    tuple(item["boundaries"])
                    if item.get("boundaries") is not None
                    else None,
                )
                for item in value.get("dimensions", ())
            ),
            filters=tuple(
                ResearchFilter(
                    item["column"],
                    item.get("operator", "="),
                    item.get("value"),
                )
                for item in value.get("filters", ())
            ),
            metrics=tuple(value.get("metrics", DEFAULT_METRICS)),
        )


def _ident(name: str) -> str:
    if not name or not name.replace("_", "a").isalnum():
        raise ValueError(f"invalid research column name: {name!r}")
    return f'"{name}"'


def _artifact_path(research_dir: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ResearchArtifactError("research parquet path is invalid")
    relative = Path(value)
    if relative.is_absolute() or relative.name != value or ".." in relative.parts:
        raise ResearchArtifactError("research parquet path must be a local file name")
    return research_dir / relative


class ResearchQueryService:
    """Query only a completed run directory, manifest, and immutable Parquets."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        try:
            from .run_manifest import artifact_path, load_completed_manifest
            run_manifest = load_completed_manifest(self.run_dir)
            trades_path = artifact_path(self.run_dir, run_manifest, "trades")
            context_path = artifact_path(self.run_dir, run_manifest, "feature_context")
            research = run_manifest.get("research", {})
            self.manifest = research
        except Exception as exc:
            legacy_path = self.run_dir / "research" / "research_manifest.json"
            if not legacy_path.is_file():
                raise ResearchArtifactError("run does not contain Task-16 or valid Task-17 research artifacts") from exc
            try:
                self.manifest = json.loads(legacy_path.read_text(encoding="utf-8"))
                trades_path = _artifact_path(legacy_path.parent, self.manifest.get("trades_parquet"))
                context_path = _artifact_path(legacy_path.parent, self.manifest.get("context_parquet"))
            except Exception as legacy_exc:
                raise ResearchArtifactError("research manifest is corrupt") from legacy_exc

        self.connection = duckdb.connect()
        self.last_query_seconds: float | None = None
        try:
            self._trades = trades_path
            self._context = context_path
            sr_zones_name = self.manifest.get("sr_zones_parquet")
            self._sr_zones = (
                self._context.parent / str(sr_zones_name)
                if isinstance(sr_zones_name, str) and sr_zones_name
                else None
            )
            if not self._trades.is_file() or not self._context.is_file():
                raise ResearchArtifactError("research parquet artifact is missing")
            if self._sr_zones is not None and not self._sr_zones.is_file():
                raise ResearchArtifactError("S/R zone research artifact is missing")
            self._validate_file_hashes()
            self._install_relations()
            self._validate()
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def run_metadata(self) -> Mapping[str, Any]:
        return {
            **self.manifest["request"],
            "prepared_cache_key": self.manifest["prepared_cache_key"],
            "trade_count": self.manifest["trade_row_count"],
            "feature_identities": self.manifest["feature_cache_identities"],
            "artifact_sizes_bytes": self.manifest.get("artifact_sizes_bytes", {}),
        }

    def _validate_file_hashes(self) -> None:
        expected = self.manifest.get("artifact_sha256")
        if not isinstance(expected, Mapping):
            raise ResearchArtifactError("research artifact hashes are missing")
        actual = {
            "trades": _file_sha256(self._trades),
            "feature_context": _file_sha256(self._context),
        }
        if self._sr_zones is not None:
            actual["sr_zones"] = _file_sha256(self._sr_zones)
        comparable_expected = {
            key: value
            for key, value in dict(expected).items()
            if key in actual
        }
        if actual != comparable_expected:
            raise ResearchArtifactError("research parquet artifact hash mismatch")

    def _install_relations(self) -> None:
        trade_path = str(self._trades).replace("'", "''")
        context_path = str(self._context).replace("'", "''")
        self.connection.execute(
            f"CREATE VIEW trades AS SELECT * FROM read_parquet('{trade_path}')"
        )
        self.connection.execute(
            f"CREATE VIEW feature_context AS SELECT * FROM read_parquet('{context_path}')"
        )

        trade_columns = {
            row[0] for row in self.connection.execute("DESCRIBE trades").fetchall()
        }
        missing = REQUIRED_TRADE_COLUMNS - trade_columns
        if missing:
            raise ResearchArtifactError(
                f"trades parquet missing required columns: {sorted(missing)}"
            )

        context_columns = {
            row[0]
            for row in self.connection.execute("DESCRIBE feature_context").fetchall()
        }
        missing_context = REQUIRED_CONTEXT_COLUMNS - context_columns
        if missing_context:
            raise ResearchArtifactError(
                "feature context parquet missing required columns: "
                f"{sorted(missing_context)}"
            )

        select = ["t.*"] + [
            f"c.{_ident(column)}"
            for column in sorted(context_columns - trade_columns)
        ]
        if {"plus_di", "minus_di"} <= context_columns:
            select.extend(
                [
                    "CASE WHEN upper(cast(t.side AS VARCHAR))='LONG' THEN c.plus_di "
                    "WHEN upper(cast(t.side AS VARCHAR))='SHORT' THEN c.minus_di "
                    "END AS directional_di",
                    "CASE WHEN upper(cast(t.side AS VARCHAR))='LONG' THEN c.minus_di "
                    "WHEN upper(cast(t.side AS VARCHAR))='SHORT' THEN c.plus_di "
                    "END AS opposing_di",
                ]
            )
        self.connection.execute(
            "CREATE VIEW trade_research AS SELECT "
            + ",".join(select)
            + " FROM trades t JOIN feature_context c "
            "ON t.research_signal_index=c.strategy_index"
        )
        self.columns = {
            row[0]
            for row in self.connection.execute("DESCRIBE trade_research").fetchall()
        }
        self._trade_columns = trade_columns
        self._context_columns = context_columns

    def _validate(self) -> None:
        trade_rows, context_rows = self.connection.execute(
            "SELECT (SELECT count(*) FROM trades), "
            "(SELECT count(*) FROM feature_context)"
        ).fetchone()
        if (
            int(trade_rows) != self.manifest.get("trade_row_count")
            or int(context_rows) != self.manifest.get("feature_context_row_count")
        ):
            raise ResearchArtifactError("manifest and parquet row counts disagree")

        if list(self.manifest.get("trade_columns", [])) != list(
            self.connection.execute("DESCRIBE trades").fetchdf()["column_name"]
        ):
            raise ResearchArtifactError("manifest and trades parquet schema disagree")
        if list(self.manifest.get("feature_context_columns", [])) != list(
            self.connection.execute("DESCRIBE feature_context").fetchdf()["column_name"]
        ):
            raise ResearchArtifactError(
                "manifest and feature-context parquet schema disagree"
            )

        try:
            interval = pd.Timedelta(self.manifest["request"]["strategy_interval"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchArtifactError("manifest strategy interval is invalid") from exc

        bad_context = self.connection.execute(
            """
            SELECT count(*) FROM (
              SELECT strategy_index, strategy_candle_open_time, decision_available_at,
                     lag(strategy_index) OVER (ORDER BY strategy_index) prior_i,
                     lag(strategy_candle_open_time) OVER (ORDER BY strategy_index) prior_t
              FROM feature_context
            ) q
            WHERE strategy_index < 0
               OR decision_available_at < strategy_candle_open_time
               OR decision_available_at > strategy_candle_open_time + ?
               OR (prior_i IS NULL AND strategy_index <> 0)
               OR (prior_i IS NOT NULL AND strategy_index <> prior_i + 1)
               OR (prior_t IS NOT NULL AND strategy_candle_open_time <= prior_t)
            """,
            [interval.to_pytimedelta()],
        ).fetchone()[0]
        if bad_context:
            raise ResearchArtifactError(
                "feature context key, timeline, or availability is invalid"
            )

        bad_signal_index = self.connection.execute(
            """
            SELECT count(*) FROM trades
            WHERE research_signal_index IS NULL
               OR research_signal_index <> floor(research_signal_index)
            """
        ).fetchone()[0]
        if bad_signal_index:
            raise ResearchArtifactError("trade research_signal_index is invalid")

        joined = self.connection.execute(
            "SELECT count(*) FROM trade_research"
        ).fetchone()[0]
        if int(joined) != int(trade_rows):
            raise ResearchArtifactError(
                "trade research_signal_index does not have exactly one context row"
            )

        mismatch = self.connection.execute(
            """
            SELECT count(*) FROM trades t
            JOIN feature_context c
              ON t.research_signal_index=c.strategy_index
            WHERE t.research_signal_candle_open_time
                    IS DISTINCT FROM c.strategy_candle_open_time
               OR t.research_signal_available_at
                    IS DISTINCT FROM c.decision_available_at
            """
        ).fetchone()[0]
        if mismatch:
            raise ResearchArtifactError("trade/context causal timestamp mismatch")

        parity_columns = self.manifest.get("trade_context_parity_columns", [])
        if not isinstance(parity_columns, list):
            raise ResearchArtifactError("trade/context parity column list is invalid")
        for column in parity_columns:
            if column not in self._trade_columns or column not in self._context_columns:
                raise ResearchArtifactError(
                    f"trade/context parity column unavailable: {column}"
                )
            quoted = _ident(column)
            bad = self.connection.execute(
                f"""
                SELECT count(*) FROM trades t
                JOIN feature_context c
                  ON t.research_signal_index=c.strategy_index
                WHERE t.{quoted} IS NOT NULL
                  AND c.{quoted} IS NOT NULL
                  AND t.{quoted} IS DISTINCT FROM c.{quoted}
                """
            ).fetchone()[0]
            if bad:
                raise ResearchArtifactError(
                    f"trade/context research-value mismatch: {column}"
                )

        nonfinite = self.connection.execute(
            "SELECT count(*) FROM trades WHERE NOT isfinite(pair_net_r)"
        ).fetchone()[0]
        if nonfinite:
            raise ResearchArtifactError(
                "trades parquet contains non-finite pair_net_r"
            )

        if self.manifest.get("trade_fingerprint_contract") != "completed_trade_semantics_v1":
            raise ResearchArtifactError("trade fingerprint contract is invalid")
        actual_fingerprint = _trade_fingerprint(
            self.connection.execute("SELECT * FROM trades").fetchdf()
        )
        if actual_fingerprint != self.manifest.get("trade_fingerprint"):
            raise ResearchArtifactError("trade artifact fingerprint mismatch")

    def _column(self, name: str) -> str:
        if name == "year":
            return "year(entry_time)"
        if name not in self.columns:
            raise ResearchArtifactError(
                f"requested research column unavailable in this run: {name}"
            )
        return _ident(name)

    def query(self, spec: ResearchQuerySpec | Mapping[str, Any]) -> pd.DataFrame:
        if not isinstance(spec, ResearchQuerySpec):
            spec = ResearchQuerySpec.from_dict(spec)

        started = time.perf_counter()
        dimensions: list[str] = []
        aliases: list[str] = []
        for dimension in spec.dimensions:
            expression = self._column(dimension.column)
            alias = dimension.alias or dimension.column
            alias_sql = _ident(alias)
            if dimension.boundaries is not None:
                bounds = tuple(float(value) for value in dimension.boundaries)
                if len(bounds) < 1 or tuple(sorted(set(bounds))) != bounds:
                    raise ValueError(
                        "bucket boundaries must be unique and strictly increasing"
                    )
                numeric = f"try_cast({expression} AS DOUBLE)"
                cases = [
                    f"WHEN {numeric} IS NULL OR isnan({numeric}) THEN 'MISSING'"
                ]
                for low, high in zip(bounds, bounds[1:]):
                    cases.append(
                        f"WHEN {numeric} >= {low} AND {numeric} < {high} "
                        f"THEN '[{low:g},{high:g})'"
                    )
                cases.append(
                    f"WHEN {numeric} < {bounds[0]} THEN '<{bounds[0]:g}'"
                )
                cases.append(f"ELSE '[{bounds[-1]:g},+inf)'")
                expression = "CASE " + " ".join(cases) + " END"
            else:
                expression = (
                    f"CASE WHEN {expression} IS NULL THEN 'MISSING' "
                    f"ELSE cast({expression} AS VARCHAR) END"
                )
            dimensions.append(f"{expression} AS {alias_sql}")
            aliases.append(alias_sql)

        metric_sql = {
            "trades": "count(*) AS trades",
            "wins": "count(*) FILTER (WHERE pair_net_r > 0) AS wins",
            "losses": "count(*) FILTER (WHERE pair_net_r < 0) AS losses",
            "breakeven": "count(*) FILTER (WHERE pair_net_r = 0) AS breakeven",
            "win_rate": (
                "count(*) FILTER (WHERE pair_net_r > 0)::DOUBLE / "
                "nullif(count(*), 0) AS win_rate"
            ),
            "net_r": "sum(pair_net_r) AS net_r",
            "avg_r": "avg(pair_net_r) AS avg_r",
            "net_pnl": "sum(pair_net_pnl) AS net_pnl",
            "avg_pnl": "avg(pair_net_pnl) AS avg_pnl",
        }
        unknown = set(spec.metrics) - set(metric_sql)
        if unknown:
            raise ValueError(
                f"unsupported research metrics: {sorted(unknown)}"
            )

        params: list[Any] = []
        predicates: list[str] = []
        operators = {"=", "!=", "<", "<=", ">", ">=", "IS NULL", "IS NOT NULL"}
        for item in spec.filters:
            operator = item.operator.upper()
            if operator not in operators:
                raise ValueError(f"unsupported filter operator: {operator}")
            expression = self._column(item.column)
            if operator.startswith("IS "):
                predicates.append(f"{expression} {operator}")
            else:
                predicates.append(f"{expression} {operator} ?")
                params.append(item.value)

        select = dimensions + [metric_sql[name] for name in spec.metrics]
        sql = "SELECT " + ",".join(select) + " FROM trade_research"
        if predicates:
            sql += " WHERE " + " AND ".join(predicates)
        if aliases:
            positions = ",".join(str(index) for index in range(1, len(aliases) + 1))
            sql += " GROUP BY " + positions + " ORDER BY " + ",".join(aliases)

        result = self.connection.execute(sql, params).fetchdf()
        self.last_query_seconds = time.perf_counter() - started
        result.attrs["query_seconds"] = self.last_query_seconds
        return result
