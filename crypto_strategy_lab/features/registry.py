"""Authoritative feature graph resolution, execution and identity."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import inspect
import json
from typing import Mapping, Sequence

import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from .base import FeatureDefinition, FeatureProvider


@dataclass(frozen=True, slots=True)
class ResolvedFeature:
    definition: FeatureDefinition
    parameters: Mapping[str, object]
    effective_warmup_bars: int


class FeatureRegistry:
    """Owns the full graph; callers provide only requests, data and overrides."""

    def __init__(self) -> None:
        self._providers: dict[str, FeatureProvider] = {}

    def register(self, provider: FeatureProvider) -> None:
        name = provider.definition.name
        if name in self._providers:
            raise ValueError(f"Feature already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> FeatureProvider:
        try: return self._providers[name]
        except KeyError as exc: raise KeyError(f"Unknown feature: {name}") from exc

    def names(self) -> tuple[str, ...]: return tuple(sorted(self._providers))

    def dependency_order(self, feature_names: Sequence[str]) -> tuple[str, ...]:
        ordered, visiting, visited = [], [], set()
        def visit(name: str) -> None:
            if name in visited: return
            if name in visiting:
                raise ValueError("Feature dependency cycle detected: " + " -> ".join((*visiting, name)))
            visiting.append(name)
            definition = self.get(name).definition
            for dependency in sorted(definition.required_features): visit(dependency)
            visiting.pop(); visited.add(name); ordered.append(name)
        for name in sorted(set(feature_names)): visit(name)
        return tuple(ordered)

    def resolve(self, feature_names: Sequence[str], parameters: Mapping[str, Mapping[str, object]] | None = None) -> tuple[ResolvedFeature, ...]:
        overrides = parameters or {}
        unknown = sorted(set(overrides) - set(self.dependency_order(feature_names)))
        if unknown: raise ValueError(f"Parameters supplied for unrequested features: {unknown}")
        warmups: dict[str, int] = {}
        result = []
        for name in self.dependency_order(feature_names):
            definition = self.get(name).definition
            # Sequential transformations need their own history after their
            # deepest dependency: sum along the longest graph path.
            inherited = max((warmups[d] for d in definition.required_features), default=0)
            warmups[name] = inherited + definition.warmup_bars
            result.append(ResolvedFeature(definition, definition.normalize_parameters(overrides.get(name)), warmups[name]))
        return tuple(result)

    def effective_warmup(self, feature_names: Sequence[str]) -> int:
        return max((item.effective_warmup_bars for item in self.resolve(feature_names)), default=0)

    def required_datasets(self, feature_names: Sequence[str]) -> tuple[DatasetKind, ...]:
        kinds = {kind for item in self.resolve(feature_names) for kind in item.definition.required_datasets}
        return tuple(sorted(kinds, key=lambda item: item.value))

    @staticmethod
    def identity(resolved: ResolvedFeature, request: DataRequest, source_identities: Mapping[DatasetKind, str], dependency_identities: Mapping[str, str]) -> str:
        payload = {"feature": resolved.definition.name, "version": resolved.definition.version,
                   "request": request.cache_key(), "parameters": dict(resolved.parameters),
                   "sources": {k.value: source_identities[k] for k in sorted(resolved.definition.required_datasets, key=lambda x:x.value)},
                   "dependencies": {k: dependency_identities[k] for k in sorted(resolved.definition.required_features)}}
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def definition_hash(self, feature_names: Sequence[str]) -> str:
        payload = [{"name": x.definition.name, "version": x.definition.version,
                    "parameters": list(x.definition.parameters), "schema": {k:v.kind for k,v in x.definition.output_schema.items()},
                    "datasets": [d.value for d in x.definition.required_datasets], "dependencies": list(x.definition.required_features),
                    "warmup": x.definition.warmup_bars, "availability": x.definition.availability_rule}
                   for x in self.resolve(feature_names)]
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def execute(self, feature_names: Sequence[str], request: DataRequest,
                datasets: Mapping[DatasetKind, pd.DataFrame], *, parameters=None,
                cache=None, source_identities: Mapping[DatasetKind, str] | None = None) -> dict[str, pd.DataFrame]:
        frames, identities = {}, {}
        source_ids = source_identities or {k: cache._source_signature(v) if cache else "uncached" for k,v in datasets.items()}
        for resolved in self.resolve(feature_names, parameters):
            definition = resolved.definition
            missing = set(definition.required_datasets) - set(datasets)
            if missing: raise ValueError(f"Missing datasets for {definition.name}: {sorted(x.value for x in missing)}")
            identity = self.identity(resolved, request, source_ids, identities)
            frame = cache.load(definition, request, identity) if cache else None
            if frame is not None:
                try: definition.validate_output(frame)
                except ValueError: frame = None
            if frame is None:
                provider = self.get(definition.name)
                dependencies = {n: frames[n] for n in definition.required_features}
                if "feature_frames" in inspect.signature(provider.compute).parameters:
                    frame = provider.compute(request, datasets, resolved.parameters, dependencies)
                else:
                    frame = provider.compute(request, datasets, resolved.parameters)
                definition.validate_output(frame)
                frame.attrs.update(feature_cache_hit=False, feature_cache_key=identity,
                                   effective_warmup_bars=resolved.effective_warmup_bars)
                if cache: cache.store(definition, request, identity, frame)
            frames[definition.name], identities[definition.name] = frame, identity
        return frames
