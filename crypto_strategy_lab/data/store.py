"""Single entry point for market data used by the future backtest pipeline."""

from __future__ import annotations

from pathlib import Path

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


class DataNotAvailableError(RuntimeError):
    """Raised when the catalog has no source coverage for a requested slice."""


class MarketDataStore:
    """Read-only view of raw Binance data plus disposable canonical caches."""

    def __init__(self, raw_root: Path, cache_root: Path = Path("cache")) -> None:
        self.raw_root = Path(raw_root)
        self.cache = CacheLayout(Path(cache_root))
        self.cache.ensure()
        self.catalog = DataCatalog(self.cache.catalog_db)
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
        target = self.cache.archive_parquet(record)
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        frame = self._adapter_for(record.dataset).read(record)
        if frame.empty:
            raise ValueError(f"Recognized Binance archive contains no rows: {record.path}")
        temporary = target.with_suffix(".tmp.parquet")
        if temporary.exists():
            temporary.unlink()
        with duckdb.connect() as con:
            con.register("canonical_frame", frame)
            escaped = str(temporary).replace("'", "''")
            con.execute(f"COPY canonical_frame TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        temporary.replace(target)
        return target

    @staticmethod
    def _projection(columns: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if columns is None:
            return None
        selected = tuple(dict.fromkeys(str(column) for column in columns))
        if not selected:
            raise ValueError("Projected dataset loads require at least one column")
        if "period_start" not in selected:
            raise ValueError("Projected dataset loads must include period_start")
        return selected

    def load_dataset(
        self,
        request: DataRequest,
        dataset: DatasetKind,
        *,
        interval: str | None = None,
        columns: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        """Load one canonical dataset for ``[request.start, request.end)``.

        ``columns`` is an optional internal fast path for consumers that need a
        small canonical projection. Projected reads let DuckDB apply Parquet
        column pruning and the request time predicate before materializing a
        pandas DataFrame. The default full-dataset path is intentionally kept
        unchanged for feature/research callers during the migration.
        """

        records = self.catalog.records_for(self.raw_root, request, dataset, interval)
        if not records:
            raise DataNotAvailableError(
                f"No catalog coverage for {request.symbol} {dataset.value} "
                f"interval={interval!r} from {request.start.isoformat()} to {request.end.isoformat()}"
            )
        parquet_paths = [self._ensure_canonical(record) for record in records]
        selected = self._projection(columns)
        with duckdb.connect() as con:
            relation = con.read_parquet([str(path) for path in parquet_paths])
            if selected is not None:
                available = set(relation.columns)
                missing = [column for column in selected if column not in available]
                if missing:
                    raise KeyError(f"Canonical dataset is missing projected columns: {missing}")
                start = request.start.isoformat().replace("'", "''")
                end = request.end.isoformat().replace("'", "''")
                relation = relation.filter(
                    f"period_start >= TIMESTAMPTZ '{start}' AND "
                    f"period_start < TIMESTAMPTZ '{end}'"
                )
                projection = ", ".join(
                    f'"{column.replace(chr(34), chr(34) * 2)}"' for column in selected
                )
                relation = relation.project(projection)
            frame = relation.df()
        if frame.empty:
            return frame
        starts = pd.to_datetime(frame["period_start"], utc=True)
        if selected is None:
            mask = (starts >= request.start) & (starts < request.end)
            frame = frame.loc[mask].copy()
            frame["period_start"] = starts.loc[mask]
        else:
            # The projected path was already filtered in DuckDB; normalize the
            # materialized timestamp without allocating another full-frame mask.
            frame["period_start"] = starts
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
        return frame.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)

    def load_klines(
        self,
        request: DataRequest,
        interval: str | None = None,
        *,
        columns: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        """Load canonical completed-candle records for a requested interval."""

        return self.load_dataset(
            request,
            DatasetKind.KLINES,
            interval=interval or request.strategy_interval,
            columns=columns,
        )
