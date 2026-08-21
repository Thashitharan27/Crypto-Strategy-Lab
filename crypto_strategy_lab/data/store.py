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
        return frame.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)

    def load_klines(self, request: DataRequest, interval: str | None = None) -> pd.DataFrame:
        """Load canonical completed-candle records for a requested interval."""

        return self.load_dataset(
            request,
            DatasetKind.KLINES,
            interval=interval or request.strategy_interval,
        )
