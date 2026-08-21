from __future__ import annotations

import pytest

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


class _CoreProvider:
    definition = FeatureDefinition(
        name="core",
        version="2",
        required_datasets=(DatasetKind.KLINES,),
        output_columns=("atr",),
    )


class _ChildProvider:
    definition = FeatureDefinition(
        name="child",
        version="1",
        required_datasets=(DatasetKind.FUNDING_RATE,),
        required_features=("core",),
        output_columns=("funding_atr",),
    )


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


def test_feature_registry_orders_feature_dependencies_before_dependants() -> None:
    registry = FeatureRegistry()
    registry.register(_ChildProvider())
    registry.register(_CoreProvider())
    assert registry.dependency_order(["child"]) == ("core", "child")
    assert registry.required_datasets(["child"]) == (
        DatasetKind.FUNDING_RATE,
        DatasetKind.KLINES,
    )
    child_hash = registry.definition_hash(["child"])
    core_hash = registry.definition_hash(["core"])
    assert child_hash != core_hash


def test_feature_registry_rejects_dependency_cycles() -> None:
    class _A:
        definition = FeatureDefinition(
            name="a", version="1", required_datasets=(DatasetKind.KLINES,),
            required_features=("b",), output_columns=("a",),
        )

    class _B:
        definition = FeatureDefinition(
            name="b", version="1", required_datasets=(DatasetKind.KLINES,),
            required_features=("a",), output_columns=("b",),
        )

    registry = FeatureRegistry()
    registry.register(_A())
    registry.register(_B())
    with pytest.raises(ValueError, match="cycle"):
        registry.dependency_order(["a"])
