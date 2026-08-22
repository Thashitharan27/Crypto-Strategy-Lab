"""Single entry point for market data used by the future backtest pipeline."""

from __future__ import annotations

from pathlib import Path
import json

import duckdb
import pandas as pd

from .binance.discovery import discover_archives
from .binance.events import FundingRateArchiveAdapter, FuturesMetricsArchiveAdapter
from .binance.klines import KlineArchiveAdapter, KlineLikeArchiveAdapter
from .binance.trades import AggTradesArchiveAdapter
from .cache import CacheLayout
from .catalog import DataCatalog
from .query import DataRequest
from .schemas import ArchiveRecord, DatasetKind
from .source_identity import SourceSignature, canonical_partition_identity


class DataNotAvailableError(RuntimeError):
    """Raised when the catalog has no source coverage for a requested slice."""


class MarketDataStore:
    """Read-only view of raw Binance data plus disposable canonical caches."""

    def __init__(self, raw_root: Path, cache_root: Path = Path("cache")) -> None:
        self.raw_root = Path(raw_root)
        self.cache = CacheLayout(Path(cache_root))
        self.cache.ensure()
        self.catalog = DataCatalog(self.cache.catalog_db)
        self.canonical_cache_events = {"hit": 0, "miss": 0}
        self._adapters = {
            DatasetKind.KLINES: KlineArchiveAdapter(),
            DatasetKind.MARK_PRICE_KLINES: KlineLikeArchiveAdapter(DatasetKind.MARK_PRICE_KLINES),
            DatasetKind.INDEX_PRICE_KLINES: KlineLikeArchiveAdapter(DatasetKind.INDEX_PRICE_KLINES),
            DatasetKind.PREMIUM_INDEX_KLINES: KlineLikeArchiveAdapter(DatasetKind.PREMIUM_INDEX_KLINES),
            DatasetKind.FUTURES_METRICS: FuturesMetricsArchiveAdapter(),
            DatasetKind.FUNDING_RATE: FundingRateArchiveAdapter(),
            DatasetKind.AGG_TRADES: AggTradesArchiveAdapter(),
        }

    def refresh_catalog(self) -> int:
        records = discover_archives(self.raw_root)
        self.catalog.sync_root(self.raw_root, records)
        return len(records)

    def _adapter_for(self, dataset: DatasetKind):
        try:
            return self._adapters[dataset]
        except KeyError as exc:
            raise NotImplementedError(
                f"Canonical adapter for {dataset.value!r} is registered in the architecture "
                "but has not been migrated yet"
            ) from exc

    def _ensure_canonical(self, record: ArchiveRecord) -> Path:
        adapter = self._adapter_for(record.dataset)
        contract = adapter.canonical_contract()
        identity = canonical_partition_identity(record, contract)
        target = self.cache.archive_parquet(record, identity)
        manifest = self.cache.archive_manifest(record, identity)
        if target.is_file() and manifest.is_file():
            try:
                metadata = json.loads(manifest.read_text(encoding="utf-8"))
                if metadata.get("canonical_identity") == identity:
                    with duckdb.connect() as con:
                        con.execute("SELECT * FROM read_parquet(?) LIMIT 0", [str(target)])
                    self.canonical_cache_events["hit"] += 1
                    return target
            except Exception:
                pass
        self.canonical_cache_events["miss"] += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        frame = adapter.read(record)
        if frame.empty:
            raise ValueError(f"Recognized Binance archive contains no rows: {record.path}")
        temporary = target.with_suffix(".tmp.parquet")
        temporary_manifest = manifest.with_suffix(".tmp.json")
        if temporary.exists():
            temporary.unlink()
        with duckdb.connect() as con:
            con.register("canonical_frame", frame)
            escaped = str(temporary).replace("'", "''")
            con.execute(f"COPY canonical_frame TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        temporary_manifest.write_text(json.dumps({
            "cache_format_version": 1, "canonical_identity": identity,
            "raw_source_fingerprint": record.fingerprint, "contract": contract,
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        temporary_manifest.replace(manifest)
        return target

    def canonical_source_identity(self, request, dataset, *, interval=None) -> SourceSignature:
        records = self.catalog.records_for(self.raw_root, request, dataset, interval)
        if not records:
            raise DataNotAvailableError(f"No catalog coverage for {request.symbol} {dataset.value}")
        adapter = self._adapter_for(dataset)
        return SourceSignature.from_canonical_identities(dataset, [
            canonical_partition_identity(record, adapter.canonical_contract()) for record in records
        ])

    def load_dataset(
        self,
        request: DataRequest,
        dataset: DatasetKind,
        *,
        interval: str | None = None,
    ) -> pd.DataFrame:
        """Load one canonical dataset for `[request.start, request.end)`."""

        records = self.catalog.records_for(self.raw_root, request, dataset, interval)
        if not records:
            raise DataNotAvailableError(
                f"No catalog coverage for {request.symbol} {dataset.value} "
                f"interval={interval!r} from {request.start.isoformat()} to {request.end.isoformat()}"
            )
        parquet_paths = [self._ensure_canonical(record) for record in records]
        with duckdb.connect() as con:
            frame = con.read_parquet([str(path) for path in parquet_paths]).df()
        if frame.empty:
            return frame
        starts = pd.to_datetime(frame["period_start"], utc=True)
        mask = (starts >= request.start) & (starts < request.end)
        frame = frame.loc[mask].copy()
        frame["period_start"] = starts.loc[mask]
        for column in ("event_time", "period_end", "available_at"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column], utc=True)
        sort_column = "event_time" if "event_time" in frame.columns else "period_start"

        if "agg_trade_id" in frame.columns:
            sort_columns = [sort_column, "agg_trade_id"]
            subset = [column for column in ("symbol", "agg_trade_id") if column in frame.columns]
        elif "trade_id" in frame.columns:
            sort_columns = [sort_column, "trade_id"]
            subset = [column for column in ("symbol", "trade_id") if column in frame.columns]
        else:
            sort_columns = [sort_column]
            subset = [column for column in ("symbol", "interval", sort_column) if column in frame.columns]

        frame = frame.sort_values(sort_columns, kind="stable")
        frame = frame.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)
        frame.attrs["canonical_source_identity"] = self.canonical_source_identity(
            request, dataset, interval=interval
        ).cache_identity()
        return frame

    def source_signature(
        self,
        request: DataRequest,
        dataset: DatasetKind,
        *,
        interval: str | None = None,
    ) -> SourceSignature:
        """Return catalog-based identity without reading canonical or raw rows."""

        records = self.catalog.records_for(self.raw_root, request, dataset, interval)
        if not records:
            raise DataNotAvailableError(
                f"No catalog coverage for {request.symbol} {dataset.value} "
                f"interval={interval!r} from {request.start.isoformat()} to {request.end.isoformat()}"
            )
        return self.canonical_source_identity(request, dataset, interval=interval)

    def load_execution_klines(
        self,
        request: DataRequest,
        interval: str | None = None,
    ) -> pd.DataFrame:
        """Load only the canonical columns needed by intrabar execution.

        The request predicate, OHLCV projection, overlap resolution, and ordering
        happen inside DuckDB so large execution frames do not materialize
        provenance metadata that the simulator cannot consume. Cross-archive
        duplicates use the same precedence as ``load_dataset``: catalog order is
        stable and the last matching archive wins.
        """

        effective_interval = interval or request.intrabar_interval or request.strategy_interval
        records = self.catalog.records_for(
            self.raw_root,
            request,
            DatasetKind.KLINES,
            effective_interval,
        )
        if not records:
            raise DataNotAvailableError(
                f"No catalog coverage for {request.symbol} {DatasetKind.KLINES.value} "
                f"interval={effective_interval!r} from {request.start.isoformat()} "
                f"to {request.end.isoformat()}"
            )

        parquet_paths = [str(self._ensure_canonical(record).resolve()) for record in records]
        precedence_rows = [(path, rank) for rank, path in enumerate(parquet_paths)]
        with duckdb.connect() as con:
            con.execute(
                "CREATE TEMP TABLE execution_source_precedence "
                "(path VARCHAR PRIMARY KEY, source_rank INTEGER NOT NULL)"
            )
            con.executemany(
                "INSERT INTO execution_source_precedence VALUES (?, ?)",
                precedence_rows,
            )
            frame = con.execute(
                """
                WITH ranked AS (
                    SELECT
                        source.period_start,
                        source.open,
                        source.high,
                        source.low,
                        source.close,
                        source.volume,
                        ROW_NUMBER() OVER (
                            PARTITION BY source.period_start
                            ORDER BY precedence.source_rank DESC
                        ) AS duplicate_rank
                    FROM read_parquet(?, filename = true) AS source
                    JOIN execution_source_precedence AS precedence
                      ON source.filename = precedence.path
                    WHERE source.period_start >= ? AND source.period_start < ?
                )
                SELECT period_start, open, high, low, close, volume
                FROM ranked
                WHERE duplicate_rank = 1
                ORDER BY period_start
                """,
                [parquet_paths, request.start, request.end],
            ).df()
        if frame.empty:
            return frame

        frame["period_start"] = pd.to_datetime(frame["period_start"], utc=True)
        return frame.reset_index(drop=True)

    def load_klines(self, request: DataRequest, interval: str | None = None) -> pd.DataFrame:
        """Load canonical completed-candle records for a requested interval."""

        return self.load_dataset(
            request,
            DatasetKind.KLINES,
            interval=interval or request.strategy_interval,
        )
