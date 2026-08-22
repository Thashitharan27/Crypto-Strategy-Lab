"""Centralized market-data access for Crypto Strategy Lab."""

from .query import DataRequest
from .schemas import ArchiveRecord, Coverage, DatasetKind, MarketKind
from .store import DataNotAvailableError, MarketDataStore
from .source_identity import SourceSignature
from .quality import (
    DataQualityCache, DataQualityError, DataQualityIssue, DataQualityReport,
    DataQualityStatus, DatasetQualityReport, DatasetValidationContract,
    classify_archive_overlap, validate_dataset, validate_feature_timeline,
)

__all__ = [
    "ArchiveRecord",
    "Coverage",
    "DataNotAvailableError",
    "DataRequest",
    "DatasetKind",
    "MarketDataStore",
    "MarketKind",
    "SourceSignature",
    "DataQualityCache", "DataQualityError", "DataQualityIssue", "DataQualityReport",
    "DataQualityStatus", "DatasetQualityReport", "DatasetValidationContract",
    "classify_archive_overlap", "validate_dataset", "validate_feature_timeline",
]
