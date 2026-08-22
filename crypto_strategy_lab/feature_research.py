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
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd


FEATURE_RESEARCH_ARTIFACT_CONTRACT = "feature_research_v1"
FEATURE_RESEARCH_ARTIFACT_VERSION = 1
REQUIRED_TRADE_COLUMNS = {
    "pair_id", "side", "entry_time", "exit_time", "pair_net_pnl", "pair_net_r",
    "research_signal_index", "research_signal_candle_open_time",
    "research_signal_available_at",
}
DEFAULT_METRICS = (
    "trades", "wins", "losses", "breakeven", "win_rate",
    "net_r", "avg_r", "net_pnl", "avg_pnl",
)


class ResearchArtifactError(ValueError):
    """A run's immutable research artifact is absent, corrupt, or inconsistent."""


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


def feature_context_frame(prepared) -> pd.DataFrame:
    """Flatten values already present in a PreparedBacktestFrame (no calculation)."""
    values: dict[str, Any] = {
        "strategy_index": range(len(prepared)),
        "strategy_candle_open_time": prepared.timestamp,
        "decision_available_at": prepared.decision_available_at,
    }
    reserved = set(values)
    # Execution OHLCV arrays are deliberately not an analysis event/history
    # store. ``close`` is retained as prepared descriptive price context.
    excluded = {"timestamp", "strategy_interval", "decision_available_at", "research",
                "momentum_returns_by_hours", "open", "high", "low", "volume"}
    for field in fields(prepared):
        if field.name not in excluded:
            candidate = getattr(prepared, field.name)
            if getattr(candidate, "ndim", None) == 1:
                if field.name in reserved:
                    raise ResearchArtifactError(f"feature context column collision: {field.name}")
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
            raise ResearchArtifactError(f"feature context column collision: {available}")
        values[available] = block.available_at
        reserved.add(available)
        for name, candidate in block.values.items():
            if name in reserved:
                raise ResearchArtifactError(f"feature context column collision: {name}")
            values[name] = candidate
            reserved.add(name)
    return pd.DataFrame(values)


def _fingerprint(trades: pd.DataFrame) -> str:
    canonical = trades.sort_index(axis=1).to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ")
    return hashlib.sha256(canonical.encode()).hexdigest()


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".parquet", dir=path.parent)
    os.close(fd)
    try:
        connection = duckdb.connect()
        try:
            connection.register("artifact_frame", frame)
            connection.execute(f"COPY artifact_frame TO '{name.replace("'", "''")}' (FORMAT PARQUET)")
            actual = connection.execute(
                f"SELECT count(*) FROM read_parquet('{name.replace("'", "''")}')"
            ).fetchone()[0]
        finally:
            connection.close()
        if actual != len(frame):
            raise ResearchArtifactError("temporary parquet row count validation failed")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_research_artifacts(run_dir: Path, result, context) -> dict[str, Any]:
    """Publish validated immutable Parquets derived from this completed run."""
    started = time.perf_counter()
    run_dir = Path(run_dir)
    research_dir = run_dir / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    trades = result.trades.copy()
    missing = REQUIRED_TRADE_COLUMNS - set(trades.columns)
    if trades.empty:
        for column in missing:
            trades[column] = pd.Series(dtype=("float64" if column in {
                "pair_net_pnl", "pair_net_r", "research_signal_index"
            } else "object"))
        missing = set()
    if missing:
        raise ResearchArtifactError(f"completed trades missing required columns: {sorted(missing)}")
    numeric_r = pd.to_numeric(trades["pair_net_r"], errors="coerce")
    if not numeric_r.map(math.isfinite).all():
        raise ResearchArtifactError("pair_net_r must be finite for every completed trade")
    feature_context = feature_context_frame(context.prepared)
    if len(feature_context) != len(context.prepared):
        raise ResearchArtifactError("feature context row count differs from prepared frame")
    trades_path = research_dir / "trades.parquet"
    context_path = research_dir / "feature_context.parquet"
    _write_parquet_atomic(trades, trades_path)
    _write_parquet_atomic(feature_context, context_path)
    request = result.request
    manifest = {
        "artifact_contract": FEATURE_RESEARCH_ARTIFACT_CONTRACT,
        "artifact_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_artifact_schema_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
        "request": {"symbol": request.symbol, "start": request.start.isoformat(),
                    "end": request.end.isoformat(), "strategy_interval": request.strategy_interval,
                    "intrabar_interval": request.intrabar_interval},
        "prepared_cache_key": result.prepared_cache_key,
        "feature_cache_identities": result.feature_cache_metadata,
        "research_feature_identities": {
            name: metadata for name, metadata in result.feature_cache_metadata.items()
            if name not in {"core_directional", "production_market_context"}
        },
        "trade_row_count": len(trades), "feature_context_row_count": len(feature_context),
        "trades_parquet": "trades.parquet", "context_parquet": "feature_context.parquet",
        "trade_fingerprint": _fingerprint(trades),
        "artifact_write_seconds": time.perf_counter() - started,
        "artifact_sizes_bytes": {"trades": trades_path.stat().st_size,
                                 "feature_context": context_path.stat().st_size},
    }
    manifest_path = research_dir / "research_manifest.json"
    _atomic_json(manifest_path, manifest)
    # Opening performs full relational/key/causal/parity validation before the
    # run manifest is allowed to advertise this artifact.
    try:
        with ResearchQueryService(run_dir):
            pass
    except Exception:
        # A failed validation must not leave the publication marker behind.
        manifest_path.unlink(missing_ok=True)
        raise
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
        return cls(tuple(ResearchDimension(d["column"], d.get("alias"),
                                           tuple(d["boundaries"]) if d.get("boundaries") else None)
                         for d in value.get("dimensions", ())),
                   tuple(ResearchFilter(f["column"], f.get("operator", "="), f.get("value"))
                         for f in value.get("filters", ())),
                   tuple(value.get("metrics", DEFAULT_METRICS)))


def _ident(name: str) -> str:
    if not name or not name.replace("_", "a").isalnum():
        raise ValueError(f"invalid research column name: {name!r}")
    return f'"{name}"'


class ResearchQueryService:
    """Query only a run directory, its manifest, and its Parquet files."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        manifest_path = self.run_dir / "research" / "research_manifest.json"
        if not manifest_path.is_file():
            raise ResearchArtifactError("run does not contain Task-16 research artifacts")
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchArtifactError("research manifest is corrupt") from exc
        if (self.manifest.get("artifact_contract") != FEATURE_RESEARCH_ARTIFACT_CONTRACT or
                self.manifest.get("artifact_version") != FEATURE_RESEARCH_ARTIFACT_VERSION):
            raise ResearchArtifactError("incompatible feature research artifact version")
        self.connection = duckdb.connect()
        try:
            research = manifest_path.parent
            self._trades = research / self.manifest["trades_parquet"]
            self._context = research / self.manifest["context_parquet"]
            if not self._trades.is_file() or not self._context.is_file():
                raise ResearchArtifactError("research parquet artifact is missing")
            self._install_relations()
            self._validate()
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    @property
    def run_metadata(self) -> Mapping[str, Any]:
        return {**self.manifest["request"], "prepared_cache_key": self.manifest["prepared_cache_key"],
                "trade_count": self.manifest["trade_row_count"],
                "feature_identities": self.manifest["feature_cache_identities"]}

    def _install_relations(self):
        tp, cp = (str(p).replace("'", "''") for p in (self._trades, self._context))
        self.connection.execute(f"CREATE VIEW trades AS SELECT * FROM read_parquet('{tp}')")
        self.connection.execute(f"CREATE VIEW feature_context AS SELECT * FROM read_parquet('{cp}')")
        tcols = {row[0] for row in self.connection.execute("DESCRIBE trades").fetchall()}
        missing = REQUIRED_TRADE_COLUMNS - tcols
        if missing:
            raise ResearchArtifactError(f"trades parquet missing required columns: {sorted(missing)}")
        ccols = {row[0] for row in self.connection.execute("DESCRIBE feature_context").fetchall()}
        select = ["t.*"] + [f'c.{_ident(c)}' for c in sorted(ccols - tcols)]
        # Derived descriptive fields exist only in this relation.
        if {"plus_di", "minus_di"} <= ccols:
            select += ["CASE WHEN upper(t.side)='LONG' THEN c.plus_di WHEN upper(t.side)='SHORT' THEN c.minus_di END AS directional_di",
                       "CASE WHEN upper(t.side)='LONG' THEN c.minus_di WHEN upper(t.side)='SHORT' THEN c.plus_di END AS opposing_di"]
        self.connection.execute("CREATE VIEW trade_research AS SELECT " + ",".join(select) +
                                " FROM trades t JOIN feature_context c ON t.research_signal_index=c.strategy_index")
        self.columns = {row[0] for row in self.connection.execute("DESCRIBE trade_research").fetchall()}

    def _validate(self):
        tr, cr = self.connection.execute("SELECT (SELECT count(*) FROM trades), (SELECT count(*) FROM feature_context)").fetchone()
        if tr != self.manifest.get("trade_row_count") or cr != self.manifest.get("feature_context_row_count"):
            raise ResearchArtifactError("manifest and parquet row counts disagree")
        try:
            interval = pd.Timedelta(self.manifest["request"]["strategy_interval"])
        except (KeyError, ValueError) as exc:
            raise ResearchArtifactError("manifest strategy interval is invalid") from exc
        bad_context = self.connection.execute("""SELECT count(*) FROM (
          SELECT strategy_index, strategy_candle_open_time, decision_available_at,
                 lag(strategy_index) OVER (ORDER BY strategy_index) prior_i,
                 lag(strategy_candle_open_time) OVER (ORDER BY strategy_index) prior_t
          FROM feature_context) q WHERE strategy_index < 0 OR decision_available_at < strategy_candle_open_time
          OR decision_available_at > strategy_candle_open_time + ?
          OR (prior_i IS NULL AND strategy_index <> 0) OR (prior_i IS NOT NULL AND strategy_index <> prior_i+1)
          OR (prior_t IS NOT NULL AND strategy_candle_open_time <= prior_t)""", [interval.to_pytimedelta()]).fetchone()[0]
        if bad_context:
            raise ResearchArtifactError("feature context key, timeline, or availability is invalid")
        joined = self.connection.execute("SELECT count(*) FROM trade_research").fetchone()[0]
        if joined != tr:
            raise ResearchArtifactError("trade research_signal_index does not have exactly one context row")
        mismatch = self.connection.execute("""SELECT count(*) FROM trades t JOIN feature_context c
          ON t.research_signal_index=c.strategy_index WHERE
          t.research_signal_candle_open_time IS DISTINCT FROM c.strategy_candle_open_time OR
          t.research_signal_available_at IS DISTINCT FROM c.decision_available_at""").fetchone()[0]
        if mismatch:
            raise ResearchArtifactError("trade/context causal timestamp mismatch")
        tcols = {r[0] for r in self.connection.execute("DESCRIBE trades").fetchall()}
        ccols = {r[0] for r in self.connection.execute("DESCRIBE feature_context").fetchall()}
        ignored = {"research_signal_index", "research_signal_candle_open_time", "research_signal_available_at"}
        for column in sorted((tcols & ccols) - ignored):
            q = _ident(column)
            bad = self.connection.execute(f"""SELECT count(*) FROM trades t JOIN feature_context c
              ON t.research_signal_index=c.strategy_index
              WHERE t.{q} IS NOT NULL AND c.{q} IS NOT NULL AND t.{q} IS DISTINCT FROM c.{q}""").fetchone()[0]
            if bad:
                raise ResearchArtifactError(f"trade/context research-value mismatch: {column}")
        nonfinite = self.connection.execute("SELECT count(*) FROM trades WHERE NOT isfinite(pair_net_r)").fetchone()[0]
        if nonfinite:
            raise ResearchArtifactError("trades parquet contains non-finite pair_net_r")

    def _column(self, name: str) -> str:
        if name == "year":
            return "year(entry_time)"
        if name not in self.columns:
            raise ResearchArtifactError(f"requested research column unavailable in this run: {name}")
        return _ident(name)

    def query(self, spec: ResearchQuerySpec | Mapping[str, Any]) -> pd.DataFrame:
        if not isinstance(spec, ResearchQuerySpec):
            spec = ResearchQuerySpec.from_dict(spec)
        dimensions, aliases = [], []
        for dimension in spec.dimensions:
            expression = self._column(dimension.column)
            alias = dimension.alias or dimension.column
            if dimension.boundaries:
                bounds = tuple(float(v) for v in dimension.boundaries)
                if sorted(set(bounds)) != list(bounds):
                    raise ValueError("bucket boundaries must be strictly increasing")
                cases = [f"WHEN {expression} IS NULL OR isnan(try_cast({expression} AS DOUBLE)) THEN 'MISSING'"]
                for lo, hi in zip(bounds, bounds[1:]):
                    cases.append(f"WHEN {expression} >= {lo} AND {expression} < {hi} THEN '[{lo:g},{hi:g})'")
                cases += [f"WHEN {expression} < {bounds[0]} THEN '<{bounds[0]:g}'",
                          f"ELSE '[{bounds[-1]:g},+inf)'"]
                expression = "CASE " + " ".join(cases) + " END"
            else:
                expression = (f"CASE WHEN {expression} IS NULL OR "
                              f"isnan(try_cast({expression} AS DOUBLE)) THEN 'MISSING' "
                              f"ELSE cast({expression} AS VARCHAR) END")
            dimensions.append(f"{expression} AS {_ident(alias)}")
            aliases.append(_ident(alias))
        metric_sql = {
            "trades": "count(*) AS trades", "wins": "count(*) FILTER (WHERE pair_net_r>0) AS wins",
            "losses": "count(*) FILTER (WHERE pair_net_r<0) AS losses",
            "breakeven": "count(*) FILTER (WHERE pair_net_r=0) AS breakeven",
            "win_rate": "count(*) FILTER (WHERE pair_net_r>0)::DOUBLE/nullif(count(*),0) AS win_rate",
            "net_r": "sum(pair_net_r) AS net_r", "avg_r": "avg(pair_net_r) AS avg_r",
            "net_pnl": "sum(pair_net_pnl) AS net_pnl", "avg_pnl": "avg(pair_net_pnl) AS avg_pnl",
        }
        unknown = set(spec.metrics) - set(metric_sql)
        if unknown: raise ValueError(f"unsupported research metrics: {sorted(unknown)}")
        params, predicates = [], []
        operators = {"=", "!=", "<", "<=", ">", ">=", "IS NULL", "IS NOT NULL"}
        for item in spec.filters:
            op = item.operator.upper()
            if op not in operators: raise ValueError(f"unsupported filter operator: {op}")
            expression = self._column(item.column)
            if op.startswith("IS "):
                predicates.append(f"{expression} {op}")
            else:
                predicates.append(f"{expression} {op} ?")
                params.append(item.value)
        select = dimensions + [metric_sql[m] for m in spec.metrics]
        sql = "SELECT " + ",".join(select) + " FROM trade_research"
        if predicates: sql += " WHERE " + " AND ".join(predicates)
        if aliases: sql += " GROUP BY " + ",".join(str(i) for i in range(1, len(aliases)+1)) + " ORDER BY " + ",".join(aliases)
        return self.connection.execute(sql, params).fetchdf()
