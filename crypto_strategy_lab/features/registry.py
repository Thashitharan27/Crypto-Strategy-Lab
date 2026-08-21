"""Registry that resolves feature data dependencies before a run begins."""

from __future__ import annotations

from hashlib import sha256
import json

from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureProvider


class FeatureRegistry:
    """Explicit feature composition replaces engine/GUI monkey-patching."""

    def __init__(self) -> None:
        self._providers: dict[str, FeatureProvider] = {}

    def register(self, provider: FeatureProvider) -> None:
        name = provider.definition.name
        if name in self._providers:
            raise ValueError(f"Feature already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> FeatureProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown feature: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def required_datasets(self, feature_names: list[str] | tuple[str, ...]) -> tuple[DatasetKind, ...]:
        dependencies: set[DatasetKind] = set()
        for name in feature_names:
            dependencies.update(self.get(name).definition.required_datasets)
        return tuple(sorted(dependencies, key=lambda item: item.value))

    def definition_hash(self, feature_names: list[str] | tuple[str, ...]) -> str:
        """Invalidate caches when feature version/dependency contracts change."""

        definitions = []
        for name in sorted(feature_names):
            definition = self.get(name).definition
            definitions.append(
                {
                    "name": definition.name,
                    "version": definition.version,
                    "required_datasets": sorted(item.value for item in definition.required_datasets),
                    "output_columns": list(definition.output_columns),
                    "warmup_bars": definition.warmup_bars,
                    "availability_rule": definition.availability_rule,
                }
            )
        payload = json.dumps(definitions, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(payload).hexdigest()
