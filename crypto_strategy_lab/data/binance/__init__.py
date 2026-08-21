"""Binance public-data archive adapters."""

from .discovery import discover_archives, infer_archive_record
from .events import FundingRateArchiveAdapter, FuturesMetricsArchiveAdapter
from .klines import KlineArchiveAdapter, KlineLikeArchiveAdapter

__all__ = [
    "FundingRateArchiveAdapter",
    "FuturesMetricsArchiveAdapter",
    "KlineArchiveAdapter",
    "KlineLikeArchiveAdapter",
    "discover_archives",
    "infer_archive_record",
]
