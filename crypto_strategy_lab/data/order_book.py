"""Bounded, content-addressed compact order-book research snapshots.

Only one immutable archive is materialized at a time. Public ``bookDepth`` is
kept as percentage-distance bands; this module never reconstructs price-level
L2 state and has no simulator dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

import duckdb
import numpy as np
import pandas as pd

from .query import DataRequest
from .schemas import ArchiveRecord, DatasetKind
from .store import DataNotAvailableError, MarketDataStore

BOOK_SNAPSHOT_SCHEMA_VERSION = 1
BOOK_SNAPSHOT_CACHE_FORMAT_VERSION = 1
BOOK_SNAPSHOT_INTERVAL = "1m"
EXPECTED_DEPTH_BANDS = (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)


@dataclass(frozen=True, slots=True)
class OrderBookSnapshotResult:
    frame: pd.DataFrame
    source_identity: str
    cache_hit: bool
    partitions_built: int
    partitions_reused: int
    source_event_count: int


class OrderBookSnapshotStore:
    """Build compact completed-minute snapshots from public Binance archives."""

    def __init__(self, store: MarketDataStore) -> None:
        self.store = store
        self.root = Path(store.cache.root) / "order_book"

    @staticmethod
    def _validate(dataset: DatasetKind, interval: str) -> None:
        if dataset not in {DatasetKind.BOOK_TICKER, DatasetKind.BOOK_DEPTH}:
            raise ValueError("order-book source must be BOOK_TICKER or BOOK_DEPTH")
        if interval != BOOK_SNAPSHOT_INTERVAL:
            raise ValueError("order-book compact base interval must be 1m")

    def _identity(self, record: ArchiveRecord, interval: str) -> str:
        payload = {"cache_format_version": BOOK_SNAPSHOT_CACHE_FORMAT_VERSION,
                   "schema_version": BOOK_SNAPSHOT_SCHEMA_VERSION, "interval": interval,
                   "exchange": record.exchange, "market": record.market.value,
                   "dataset": record.dataset.value, "symbol": record.symbol,
                   "source_fingerprint": record.fingerprint,
                   "adapter_contract": self.store._adapter_for(record.dataset).canonical_contract()}
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _paths(self, record: ArchiveRecord, interval: str, identity: str) -> tuple[Path, Path]:
        path = self.root / record.dataset.value / record.symbol / interval / f"{identity}.parquet"
        return path, path.with_suffix(".json")

    @staticmethod
    def _utc_ns(values) -> pd.Series:
        return pd.to_datetime(values, utc=True, errors="coerce").astype("datetime64[ns, UTC]")

    @classmethod
    def _compact_ticker(cls, record: ArchiveRecord, events: pd.DataFrame) -> pd.DataFrame:
        frame = events.copy()
        frame["event_time"] = cls._utc_ns(frame["event_time"])
        numeric = ("best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty")
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        valid = frame["event_time"].notna()
        valid &= frame["best_bid_price"].gt(0) & frame["best_ask_price"].gt(0)
        valid &= frame["best_bid_qty"].ge(0) & frame["best_ask_qty"].ge(0)
        valid &= frame["best_bid_price"].le(frame["best_ask_price"])
        frame = frame.loc[valid].sort_values(["event_time", "update_id"], kind="stable")
        frame["period_start"] = frame["event_time"].dt.floor("min")
        frame = frame.groupby("period_start", sort=True).tail(1)
        result = frame[["period_start", "event_time", *numeric]].rename(
            columns={"event_time": "source_event_at"})
        result["period_end"] = result["period_start"] + pd.Timedelta(minutes=1)
        result["available_at"] = result["period_end"]
        result["book_ticker_observed"] = True
        result["book_ticker_covered"] = True
        result["book_ticker_locked"] = result["best_bid_price"].eq(result["best_ask_price"])
        return result.reset_index(drop=True)

    @classmethod
    def _compact_depth(cls, record: ArchiveRecord, events: pd.DataFrame) -> pd.DataFrame:
        frame = events.copy()
        frame["event_time"] = cls._utc_ns(frame["event_time"])
        for column in ("percentage", "depth", "notional"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        valid = frame["event_time"].notna() & frame["percentage"].notna() & frame["percentage"].ne(0)
        valid &= np.isfinite(frame["depth"]) & frame["depth"].ge(0)
        valid &= np.isfinite(frame["notional"]) & frame["notional"].ge(0)
        frame = frame.loc[valid].sort_values(["event_time", "percentage"], kind="stable")
        rows = []
        for timestamp, group in frame.groupby("event_time", sort=True):
            row = {"source_event_at": timestamp,
                   "book_depth_snapshot_complete": set(EXPECTED_DEPTH_BANDS).issubset(set(group["percentage"]))}
            indexed = group.set_index("percentage")
            for band in range(1, 6):
                for side, percentage in (("bid", -band), ("ask", band)):
                    row[f"book_{side}_depth_{band}pct"] = indexed.at[percentage, "depth"] if percentage in indexed.index else np.nan
                    row[f"book_{side}_notional_{band}pct"] = indexed.at[percentage, "notional"] if percentage in indexed.index else np.nan
            rows.append(row)
        snapshots = pd.DataFrame(rows)
        if snapshots.empty:
            return snapshots
        snapshots["period_start"] = cls._utc_ns(snapshots["source_event_at"]).dt.floor("min")
        snapshots = snapshots.sort_values("source_event_at").groupby("period_start", sort=True).tail(1)
        snapshots["period_end"] = snapshots["period_start"] + pd.Timedelta(minutes=1)
        snapshots["available_at"] = snapshots["period_end"]
        snapshots["book_depth_observed"] = True
        snapshots["book_depth_covered"] = True
        return snapshots.reset_index(drop=True)

    def _read(self, record, interval, identity):
        parquet, manifest = self._paths(record, interval, identity)
        try:
            meta = json.loads(manifest.read_text())
            if meta.get("identity") != identity or meta.get("schema_version") != BOOK_SNAPSHOT_SCHEMA_VERSION:
                return None
            with duckdb.connect() as con:
                frame = con.read_parquet(str(parquet)).df()
            for column in ("period_start", "period_end", "available_at", "source_event_at"):
                if column in frame:
                    frame[column] = self._utc_ns(frame[column])
            return frame
        except Exception:
            return None

    def _write(self, record, interval, identity, frame):
        parquet, manifest = self._paths(record, interval, identity)
        parquet.parent.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}.{uuid4().hex}"
        tmp = parquet.with_suffix(f".{token}.tmp.parquet")
        tmp_manifest = manifest.with_suffix(f".{token}.tmp.json")
        with duckdb.connect() as con:
            con.register("snapshot", frame)
            con.execute(f"COPY snapshot TO '{str(tmp).replace(chr(39), chr(39)*2)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp_manifest.write_text(json.dumps({"identity": identity, "schema_version": BOOK_SNAPSHOT_SCHEMA_VERSION,
                                            "cache_format_version": BOOK_SNAPSHOT_CACHE_FORMAT_VERSION,
                                            "source_fingerprint": record.fingerprint, "row_count": len(frame)},
                                           sort_keys=True, indent=2) + "\n")
        tmp.replace(parquet); tmp_manifest.replace(manifest)

    @staticmethod
    def _combined(dataset, identities):
        digest = sha256(json.dumps(sorted(identities)).encode()).hexdigest()
        return f"order-book-snapshot-v{BOOK_SNAPSHOT_SCHEMA_VERSION}:{dataset.value}:{len(identities)}:{digest}"

    def source_identity(self, request: DataRequest, dataset: DatasetKind, *, interval: str = "1m") -> str:
        self._validate(dataset, interval)
        expanded = DataRequest(request.symbol, request.start - pd.Timedelta(minutes=1), request.end,
                               request.strategy_interval, market=request.market,
                               exchange=request.exchange, datasets=(dataset,))
        records = self.store.catalog.records_for(self.store.raw_root, expanded, dataset, None)
        if not records:
            raise DataNotAvailableError(f"No {dataset.value} coverage")
        return self._combined(dataset, [self._identity(r, interval) for r in records])

    def load(self, request: DataRequest, dataset: DatasetKind, *, interval: str = "1m") -> OrderBookSnapshotResult:
        self._validate(dataset, interval)
        expanded = DataRequest(request.symbol, request.start - pd.Timedelta(minutes=1), request.end,
                               request.strategy_interval, market=request.market,
                               exchange=request.exchange, datasets=(dataset,))
        records = self.store.catalog.records_for(self.store.raw_root, expanded, dataset, None)
        if not records:
            raise DataNotAvailableError(f"No {dataset.value} coverage")
        frames, identities, built, reused, event_count = [], [], 0, 0, 0
        for record in records:
            identity = self._identity(record, interval); identities.append(identity)
            compact = self._read(record, interval, identity)
            if compact is None:
                events = self.store._adapter_for(dataset).read(record); event_count += len(events)
                compact = (self._compact_ticker if dataset is DatasetKind.BOOK_TICKER else self._compact_depth)(record, events)
                if not compact.empty: self._write(record, interval, identity, compact)
                built += 1
            else: reused += 1
            if not compact.empty: frames.append(compact)
        if not frames:
            raise DataNotAvailableError(f"No valid {dataset.value} observations")
        combined = pd.concat(frames, ignore_index=True).sort_values("period_start", kind="stable")
        combined = combined.drop_duplicates("period_start", keep="last")
        grid = pd.date_range(pd.Timestamp(request.start).floor("min") - pd.Timedelta(minutes=1),
                             pd.Timestamp(request.end).ceil("min"), freq="1min", inclusive="left")
        combined = combined.set_index("period_start").reindex(grid).reset_index(names="period_start")
        prefix = "book_ticker" if dataset is DatasetKind.BOOK_TICKER else "book_depth"
        catalog_covered = pd.Series(False, index=combined.index)
        for record in records:
            if record.period_start is None or record.period_end is None:
                catalog_covered[:] = True
            else:
                catalog_covered |= (combined["period_start"] >= pd.Timestamp(record.period_start).floor("min")) & (combined["period_start"] < pd.Timestamp(record.period_end).ceil("min"))
        combined[f"{prefix}_covered"] = combined[f"{prefix}_covered"].fillna(catalog_covered).astype(bool)
        combined[f"{prefix}_observed"] = combined[f"{prefix}_observed"].fillna(False).astype(bool)
        combined["period_end"] = combined["period_start"] + pd.Timedelta(minutes=1)
        combined["available_at"] = combined["period_end"]
        return OrderBookSnapshotResult(combined, self._combined(dataset, identities), built == 0,
                                       built, reused, event_count)
