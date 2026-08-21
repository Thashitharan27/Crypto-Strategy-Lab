"""Feature provider contracts independent of the simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """Stable identity and dependencies for one derived research feature."""

    name: str
    version: str
    required_datasets: tuple[DatasetKind, ...]
    output_columns: tuple[str, ...]
    required_features: tuple[str, ...] = ()
    warmup_bars: int = 0
    availability_rule: str = "max_dependency_available_at"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("feature name must not be empty")
        if not self.version.strip():
            raise ValueError("feature version must not be empty")
        if not self.output_columns:
            raise ValueError("feature must declare output columns")
        if self.name in self.required_features:
            raise ValueError("feature cannot depend on itself")
        if self.warmup_bars < 0:
            raise ValueError("warmup_bars must be non-negative")


class FeatureProvider(Protocol):
    """Computes a causal feature frame from datasets and prepared dependencies."""

    definition: FeatureDefinition

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[DatasetKind, pd.DataFrame],
        parameters: Mapping[str, object],
        feature_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        ...
