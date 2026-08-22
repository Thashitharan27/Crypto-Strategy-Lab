"""Typed, dataset-aware validation for canonical market data.

This module deliberately has no dependency on features, strategies, simulators,
or reporting.  A validated frame may therefore be handed to any downstream
consumer with the same operational contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .schemas import DatasetKind
from .timing import interval_to_timedelta

VALIDATION_CONTRACT_VERSION = "1"


class DataQualityStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    code: str
    severity: DataQualityStatus
    message: str
    count: int = 1
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "severity": self.severity.value,
            "message": self.message, "count": int(self.count),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "details": dict(sorted(self.details.items())),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DataQualityIssue":
        return cls(value["code"], DataQualityStatus(value["severity"]), value["message"],
                   int(value.get("count", 1)), value.get("first_timestamp"),
                   value.get("last_timestamp"), value.get("details", {}))


@dataclass(frozen=True, slots=True)
class DatasetQualityReport:
    dataset: str
    symbol: str
    interval: str | None
    required: bool
    requested_start: str
    requested_end: str
    observed_start: str | None
    observed_end: str | None
    complete_start: str | None
    complete_end: str | None
    row_count: int
    source_identity: str | None
    status: DataQualityStatus
    issues: tuple[DataQualityIssue, ...] = ()
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset, "symbol": self.symbol, "interval": self.interval,
            "required": self.required, "requested_start": self.requested_start,
            "requested_end": self.requested_end, "observed_start": self.observed_start,
            "observed_end": self.observed_end, "complete_start": self.complete_start,
            "complete_end": self.complete_end, "row_count": self.row_count,
            "source_identity": self.source_identity, "status": self.status.value,
            "issues": [item.to_dict() for item in self.issues], "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DatasetQualityReport":
        return cls(**{**value, "status": DataQualityStatus(value["status"]),
                      "issues": tuple(DataQualityIssue.from_dict(x) for x in value["issues"])})


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    datasets: tuple[DatasetQualityReport, ...]

    @property
    def overall_status(self) -> DataQualityStatus:
        statuses = {item.status for item in self.datasets}
        if DataQualityStatus.ERROR in statuses:
            return DataQualityStatus.ERROR
        if DataQualityStatus.WARN in statuses or DataQualityStatus.MISSING in statuses:
            return DataQualityStatus.WARN
        return DataQualityStatus.OK

    @property
    def issues(self) -> tuple[DataQualityIssue, ...]:
        return tuple(issue for report in self.datasets for issue in report.issues)

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": VALIDATION_CONTRACT_VERSION,
                "overall_status": self.overall_status.value,
                "datasets": [item.to_dict() for item in self.datasets],
                "summary": {"dataset_count": len(self.datasets),
                            "issue_count": len(self.issues)}}

    def raise_for_errors(self) -> None:
        errors = [i for i in self.datasets if i.status is DataQualityStatus.ERROR]
        if errors:
            detail = "; ".join(f"{r.dataset}: {', '.join(i.code for i in r.issues)}" for r in errors)
            raise DataQualityError(f"Required market data failed validation: {detail}", self)


class DataQualityError(ValueError):
    def __init__(self, message: str, report: DataQualityReport):
        super().__init__(message)
        self.report = report


@dataclass(frozen=True, slots=True)
class DatasetValidationContract:
    dataset: DatasetKind
    timeline: str
    timestamp_column: str
    logical_key: tuple[str, ...]
    required_columns: tuple[str, ...]
    numeric_fields: tuple[str, ...] = ()
    positive_fields: tuple[str, ...] = ()
    non_negative_fields: tuple[str, ...] = ()


_IDENTITY = ("symbol", "exchange", "market", "dataset", "available_at")
_CANDLE = ("period_start", "period_end", *_IDENTITY, "interval", "open", "high", "low", "close")
CONTRACTS: dict[DatasetKind, DatasetValidationContract] = {
    kind: DatasetValidationContract(kind, "fixed", "period_start", ("period_start",), _CANDLE,
        ("open", "high", "low", "close"), ("open", "high", "low", "close"),
        ("volume", "trade_count", "taker_buy_base_volume", "taker_buy_quote_volume"))
    for kind in (DatasetKind.KLINES, DatasetKind.MARK_PRICE_KLINES,
                 DatasetKind.INDEX_PRICE_KLINES, DatasetKind.PREMIUM_INDEX_KLINES)
}
CONTRACTS.update({
    DatasetKind.FUTURES_METRICS: DatasetValidationContract(
        DatasetKind.FUTURES_METRICS, "fixed", "period_start", ("period_start",),
        ("period_start", *_IDENTITY), non_negative_fields=("open_interest", "open_interest_value",
         "long_short_ratio", "top_trader_long_short_ratio", "taker_long_short_ratio")),
    DatasetKind.FUNDING_RATE: DatasetValidationContract(
        DatasetKind.FUNDING_RATE, "event", "event_time", ("event_time",),
        ("event_time", *_IDENTITY, "funding_rate"), numeric_fields=("funding_rate",),
        positive_fields=("funding_interval_hours",)),
    DatasetKind.AGG_TRADES: DatasetValidationContract(
        DatasetKind.AGG_TRADES, "event", "event_time", ("event_time", "agg_trade_id"),
        ("event_time", *_IDENTITY, "agg_trade_id", "price", "quantity"),
        positive_fields=("price",), non_negative_fields=("quantity", "agg_trade_id")),
    DatasetKind.TRADES: DatasetValidationContract(
        DatasetKind.TRADES, "event", "event_time", ("event_time", "trade_id"),
        ("event_time", *_IDENTITY, "trade_id", "price", "quantity"),
        positive_fields=("price",), non_negative_fields=("quantity", "trade_id")),
})


def _iso(value: Any) -> str | None:
    if value is None or pd.isna(value): return None
    return pd.Timestamp(value).isoformat()


def _issue(code, severity, message, mask=None, timestamps=None, **details):
    count = int(mask.sum()) if mask is not None else int(details.pop("count", 1))
    selected = timestamps[mask] if mask is not None and timestamps is not None else timestamps
    return DataQualityIssue(code, severity, message, count,
        _iso(selected.min()) if selected is not None and len(selected) else None,
        _iso(selected.max()) if selected is not None and len(selected) else None, details)


def _status(required: bool, issues: Iterable[DataQualityIssue], missing=False):
    issues = tuple(issues)
    if missing: return DataQualityStatus.ERROR if required else DataQualityStatus.MISSING
    if any(x.severity is DataQualityStatus.ERROR for x in issues):
        return DataQualityStatus.ERROR if required else DataQualityStatus.WARN
    return DataQualityStatus.WARN if issues else DataQualityStatus.OK


def validate_dataset(frame: pd.DataFrame | None, request, dataset: DatasetKind, *,
                     interval: str | None = None, required: bool = True,
                     source_identity: str | None = None) -> DatasetQualityReport:
    """Validate one canonical frame without manufacturing an event-stream grid."""
    contract = CONTRACTS[dataset]
    start, end = pd.Timestamp(request.start), pd.Timestamp(request.end)
    source_identity = source_identity or (frame.attrs.get("canonical_source_identity") if frame is not None else None)
    if frame is None or frame.empty:
        issue = DataQualityIssue("DATASET_MISSING", DataQualityStatus.ERROR if required else DataQualityStatus.MISSING,
                                 "No canonical rows are available for the requested range", 0)
        return DatasetQualityReport(dataset.value, request.symbol, interval, required, _iso(start), _iso(end),
                                    None, None, None, None, 0, source_identity,
                                    _status(required, (issue,), True), (issue,))
    issues: list[DataQualityIssue] = []
    missing = sorted(set(contract.required_columns) - set(frame.columns))
    if missing:
        issues.append(DataQualityIssue("MISSING_REQUIRED_COLUMN", DataQualityStatus.ERROR,
                                       f"Missing canonical columns: {missing}", len(missing), details={"columns": missing}))
    if not source_identity:
        issues.append(DataQualityIssue("MISSING_SOURCE_IDENTITY", DataQualityStatus.ERROR,
                                       "Canonical source identity is absent"))
    if contract.timestamp_column not in frame:
        timestamps = pd.Series([], dtype="datetime64[ns, UTC]")
    else:
        parsed = pd.to_datetime(frame[contract.timestamp_column], utc=True, errors="coerce")
        invalid = parsed.isna()
        if invalid.any(): issues.append(_issue("MALFORMED_TIMESTAMP", DataQualityStatus.ERROR,
                                               "Timeline timestamp is not parseable", invalid, parsed))
        timestamps = parsed
        if not parsed.dropna().is_monotonic_increasing:
            issues.append(DataQualityIssue("NON_MONOTONIC_TIMELINE", DataQualityStatus.ERROR,
                                           "Canonical timestamps are not monotonically increasing"))
    present_keys = [x for x in contract.logical_key if x in frame]
    if len(present_keys) == len(contract.logical_key):
        duplicate = frame.duplicated(present_keys, keep=False)
        if duplicate.any(): issues.append(_issue("DUPLICATE_LOGICAL_KEY", DataQualityStatus.ERROR,
                                                 "Canonical logical keys are duplicated", duplicate, timestamps))
    for column, expected in (("symbol", request.symbol), ("exchange", request.exchange),
                             ("market", request.market.value), ("dataset", dataset.value)):
        if column in frame and set(frame[column].dropna().astype(str)) != {str(expected)}:
            issues.append(DataQualityIssue("IDENTITY_MISMATCH", DataQualityStatus.ERROR,
                                           f"Canonical {column} does not match request", details={"column": column}))
    available = pd.to_datetime(frame.get("available_at"), utc=True, errors="coerce") if "available_at" in frame else None
    if available is not None:
        invalid = available.isna()
        if invalid.any(): issues.append(_issue("MALFORMED_AVAILABLE_AT", DataQualityStatus.ERROR,
                                               "available_at is missing or malformed", invalid, timestamps))
        comparison = pd.to_datetime(frame.get("period_end"), utc=True, errors="coerce") if contract.timeline == "fixed" and "period_end" in frame else timestamps
        early = available < comparison
        if early.any(): issues.append(_issue("NON_CAUSAL_AVAILABILITY", DataQualityStatus.ERROR,
                                             "available_at precedes the source observation", early, timestamps))
    if contract.timeline == "fixed" and "period_end" in frame:
        period_end = pd.to_datetime(frame.period_end, utc=True, errors="coerce")
        bad = timestamps >= period_end
        if bad.any(): issues.append(_issue("INVALID_PERIOD", DataQualityStatus.ERROR,
                                           "period_start must precede period_end", bad, timestamps))
    for column in contract.numeric_fields + contract.positive_fields + contract.non_negative_fields:
        if column not in frame: continue
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid = ~np.isfinite(values)
        if invalid.any(): issues.append(_issue("INVALID_NUMERIC", DataQualityStatus.ERROR,
                                               f"{column} must be finite", invalid, timestamps, column=column))
        invalid = values <= 0 if column in contract.positive_fields else values < 0
        if invalid.any(): issues.append(_issue("INVALID_DOMAIN_VALUE", DataQualityStatus.ERROR,
                                               f"{column} is outside its valid domain", invalid, timestamps, column=column))
    if all(x in frame for x in ("open", "high", "low", "close")):
        bad = ((frame.low > frame.high) | (frame.open < frame.low) | (frame.open > frame.high) |
               (frame.close < frame.low) | (frame.close > frame.high))
        if bad.any(): issues.append(_issue("INVALID_OHLC", DataQualityStatus.ERROR,
                                           "OHLC values violate candle bounds", bad, timestamps))
    for taker, total in (("taker_buy_base_volume", "volume"), ("taker_buy_quote_volume", "quote_volume")):
        if taker in frame and total in frame:
            bad = frame[taker] > frame[total] + np.maximum(frame[total].abs() * 1e-12, 1e-12)
            if bad.any(): issues.append(_issue("TAKER_VOLUME_EXCEEDS_TOTAL", DataQualityStatus.ERROR,
                                               f"{taker} exceeds {total}", bad, timestamps))
    complete_start, complete_end = _iso(start), _iso(end)
    if contract.timeline == "fixed" and interval and len(timestamps.dropna()):
        delta = interval_to_timedelta(interval)
        valid = timestamps.dropna()
        expected = pd.date_range(start=start, end=end, freq=delta, inclusive="left")
        missing_grid = expected.difference(pd.DatetimeIndex(valid))
        off_grid = valid[~((valid - start) % delta == pd.Timedelta(0))]
        if len(off_grid): issues.append(_issue("OFF_GRID_TIMESTAMP", DataQualityStatus.ERROR,
                                               "Fixed-cadence timestamps are off grid", timestamps=off_grid, count=len(off_grid)))
        if len(missing_grid):
            leading = missing_grid[missing_grid < valid.min()]
            trailing = missing_grid[missing_grid > valid.max()]
            internal = missing_grid[(missing_grid > valid.min()) & (missing_grid < valid.max())]
            for code, values, message in (("LEADING_COVERAGE_GAP", leading, "Leading fixed-cadence coverage is missing"),
                                          ("TRAILING_COVERAGE_GAP", trailing, "Trailing fixed-cadence coverage is missing"),
                                          ("MISSING_INTERNAL_INTERVAL", internal, "Internal fixed-cadence intervals are missing")):
                if len(values): issues.append(_issue(code, DataQualityStatus.ERROR, message,
                                                     timestamps=values, count=len(values)))
            complete_start = _iso(valid.min()) if len(leading) else _iso(start)
            complete_end = _iso(valid.max() + delta) if len(trailing) else _iso(end)
    observed_start = _iso(timestamps.min()) if len(timestamps) else None
    observed_end = _iso(timestamps.max()) if len(timestamps) else None
    return DatasetQualityReport(dataset.value, request.symbol, interval, required, _iso(start), _iso(end),
        observed_start, observed_end, complete_start, complete_end, len(frame), source_identity,
        _status(required, issues), tuple(issues))


def classify_archive_overlap(frames: Iterable[pd.DataFrame], logical_key: Iterable[str]) -> tuple[DataQualityIssue, ...]:
    """Classify immutable archive overlap without applying last-source-wins.

    Callers supply pre-resolution archive frames. Identical repeated rows are
    operational provenance (WARN); differing values for one key are corruption.
    """
    frames = tuple(frames)
    if len(frames) < 2: return ()
    combined = pd.concat(frames, ignore_index=True)
    keys = list(logical_key)
    duplicates = combined.duplicated(keys, keep=False)
    if not duplicates.any(): return ()
    overlap = combined.loc[duplicates]
    value_columns = [c for c in combined.columns if c not in keys]
    conflicts = 0
    for _, group in overlap.groupby(keys, dropna=False, sort=False):
        if any(group[column].nunique(dropna=False) > 1 for column in value_columns): conflicts += 1
    key_count = int(overlap.groupby(keys, dropna=False).ngroups)
    result = [DataQualityIssue("ARCHIVE_OVERLAP", DataQualityStatus.WARN,
                               "Raw archives contain overlapping logical keys", key_count)]
    if conflicts:
        result.append(DataQualityIssue("CONFLICTING_ARCHIVE_OVERLAP", DataQualityStatus.ERROR,
                                       "Overlapping archives disagree for a logical key", conflicts))
    else:
        result.append(DataQualityIssue("IDENTICAL_ARCHIVE_OVERLAP", DataQualityStatus.WARN,
                                       "Overlapping source rows are identical", key_count))
    return tuple(result)


class DataQualityCache:
    """Disposable atomic JSON cache, independent of L2/L3 identities."""
    def __init__(self, cache_root: Path): self.root = Path(cache_root) / "quality"
    def key(self, request, dataset, interval, required, source_identity):
        payload = (VALIDATION_CONTRACT_VERSION, dataset.value, interval, required, source_identity,
                   _iso(request.start), _iso(request.end), request.symbol)
        return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    def get_or_validate(self, frame, request, dataset, *, interval=None, required=True):
        source = frame.attrs.get("canonical_source_identity") if frame is not None else None
        key = self.key(request, dataset, interval, required, source); path = self.root / f"{key}.json"
        try:
            report = DatasetQualityReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
            return replace(report, cache_hit=True)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, AttributeError):
            pass
        report = validate_dataset(frame, request, dataset, interval=interval, required=required)
        self.root.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, path)
        return report


def validate_feature_timeline(definition, frame: pd.DataFrame, parameters=None) -> None:
    """Enforce generic output ordering and availability without parsing prose rules."""
    definition.validate_output(frame, parameters)
    time_col = "timestamp" if "timestamp" in frame else "date"
    times = pd.to_datetime(frame[time_col], utc=True, errors="coerce")
    available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    if times.isna().any() or available.isna().any(): raise ValueError("Feature timeline contains invalid timestamps")
    if not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Feature output timestamps must be ordered and unique")
    if (available < times).any(): raise ValueError("Feature available_at precedes its logical timestamp")
