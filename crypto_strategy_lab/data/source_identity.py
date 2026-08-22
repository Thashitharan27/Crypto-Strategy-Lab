"""Deterministic source identities derived without materializing market data."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

from .schemas import ArchiveRecord, DatasetKind


@dataclass(frozen=True, slots=True)
class SourceSignature:
    """Identity of the catalog partitions contributing to a requested slice.

    Archive fingerprints remain the primary content identity.  Coverage and file
    metadata are included so catalog corrections also invalidate derived data;
    the archive filename alone is never treated as source identity.
    """

    dataset: DatasetKind
    digest: str
    partition_count: int

    @classmethod
    def from_records(
        cls,
        dataset: DatasetKind,
        records: Iterable[ArchiveRecord],
    ) -> "SourceSignature":
        partitions = [
            {
                "exchange": record.exchange,
                "market": record.market.value,
                "dataset": record.dataset.value,
                "symbol": record.symbol,
                "interval": record.interval,
                "frequency": record.frequency,
                "period_start": record.period_start,
                "period_end": record.period_end,
                "size_bytes": record.size_bytes,
                "mtime_ns": record.mtime_ns,
                "fingerprint": record.fingerprint,
            }
            for record in records
        ]
        partitions.sort(
            key=lambda item: json.dumps(item, sort_keys=True, default=str)
        )
        payload = {"signature_version": 1, "dataset": dataset.value, "partitions": partitions}
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return cls(dataset, sha256(encoded).hexdigest(), len(partitions))

    def cache_identity(self) -> str:
        return f"catalog-v1:{self.dataset.value}:{self.partition_count}:{self.digest}"
