from __future__ import annotations

from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features import FeatureDefinition, FeatureRegistry


class _Provider:
    definition = FeatureDefinition(
        name="open_interest",
        version="1",
        required_datasets=(DatasetKind.FUTURES_METRICS, DatasetKind.KLINES),
        output_columns=("oi_change_1h",),
        warmup_bars=12,
    )

    def compute(self, request, datasets, parameters):  # pragma: no cover - contract fixture
        raise NotImplementedError


def test_feature_registry_resolves_dependencies_and_versions() -> None:
    registry = FeatureRegistry()
    registry.register(_Provider())
    assert registry.names() == ("open_interest",)
    assert registry.required_datasets(["open_interest"]) == (
        DatasetKind.KLINES,
        DatasetKind.FUTURES_METRICS,
    )
    first_hash = registry.definition_hash(["open_interest"])
    assert len(first_hash) == 64
