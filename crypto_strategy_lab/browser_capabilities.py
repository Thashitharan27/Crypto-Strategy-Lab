"""Read-only browser projection of authoritative CSL capability metadata.

This module does not define strategy or feature capabilities. It serializes the
existing control-rule workspace and production feature registry for the browser.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from crypto_strategy_lab.control_rule_workspace import strategy_capabilities
from crypto_strategy_lab.features import production_feature_registry


def _json_safe(value):
    """Serialize registry metadata without mutating authoritative defaults."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def feature_capabilities() -> list[dict]:
    """Return JSON-safe metadata from the authoritative production registry."""
    registry = production_feature_registry()
    result = []
    for name in registry.names():
        definition = registry.get(name).definition
        parameters = {}
        for parameter_name, spec in sorted(definition.parameters.items()):
            item = {"required": bool(spec.required)}
            if not spec.required:
                item["default"] = _json_safe(spec.default)
            parameters[parameter_name] = item
        result.append(
            {
                "name": definition.name,
                "version": definition.version,
                "required_datasets": [
                    dataset.value for dataset in definition.required_datasets
                ],
                "optional_datasets": [
                    dataset.value for dataset in definition.optional_datasets
                ],
                "required_features": list(definition.required_features),
                "warmup_bars": int(definition.warmup_bars),
                "availability_rule": definition.availability_rule,
                "parameters": parameters,
                "output_schema": {
                    field_name: {
                        "kind": field.kind,
                        "nullable": bool(field.nullable),
                    }
                    for field_name, field in definition.output_schema.items()
                },
                "parameterized_schema": definition.output_schema_factory is not None,
            }
        )
    return result


def browser_capabilities() -> dict:
    """Compose existing strategy/rule and feature metadata without mutation."""
    return {
        "strategy": strategy_capabilities(),
        "features": feature_capabilities(),
        "mode": "read-only",
    }
