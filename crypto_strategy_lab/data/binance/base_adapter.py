"""Shared helpers for reading raw Binance ZIP/CSV archives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator
import zipfile

import pandas as pd

from ..schemas import ArchiveRecord, DatasetKind


class BinanceArchiveAdapter(ABC):
    """Exchange-specific schema adapter; never computes research features."""

    dataset: DatasetKind

    @abstractmethod
    def read(self, record: ArchiveRecord) -> pd.DataFrame:
        """Normalize one raw source archive into a canonical DataFrame."""


@contextmanager
def open_csv_stream(path: Path) -> Iterator[BinaryIO]:
    """Yield a binary CSV stream from either a .csv or Binance .zip archive."""

    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"No CSV member found in Binance archive: {path}")
            # Binance public archives normally contain one CSV. Choosing the
            # largest member is robust to metadata/checksum sidecars.
            member = max(members, key=lambda name: archive.getinfo(name).file_size)
            with archive.open(member, "r") as stream:
                yield stream
        return
    with path.open("rb") as stream:
        yield stream
