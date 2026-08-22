from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features import (
    FeatureDefinition, FeatureRegistry, OutputField, ParameterDefinition,
    production_feature_registry,
)
from crypto_strategy_lab.features.technical import CORE_DIRECTIONAL_FEATURE_NAME


REQUEST = DataRequest(
    symbol="BTCUSDT", start=datetime(2026, 1, 1, tzinfo=UTC),
    end=datetime(2026, 1, 2, tzinfo=UTC), strategy_interval="4h",
)


class Provider:
    def __init__(self, name, *, version="1", dependencies=(), warmup=0, parameters=None):
        self.calls = 0
        self.definition = FeatureDefinition(
            name=name, version=version, required_datasets=(DatasetKind.KLINES,),
            required_features=dependencies, warmup_bars=warmup,
            parameters=parameters or {},
            output_schema={"value": OutputField("numeric", False)},
        )

    def compute(self, request, datasets, parameters, feature_frames=None):
        self.calls += 1
        return pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-01-01"], utc=True),
            "available_at": pd.to_datetime(["2026-01-01 04:00"], utc=True),
            "value": [float(parameters.get("period", 1))],
        })


def test_parameter_contract_defaults_normalizes_and_rejects_unknown() -> None:
    provider = Provider("a", parameters={"period": ParameterDefinition(int, 14)})
    definition = provider.definition
    assert definition.normalize_parameters() == {"period": 14}
    assert definition.normalize_parameters({"period": "20"}) == {"period": 20}
    with pytest.raises(ValueError, match="Unknown parameters"):
        definition.normalize_parameters({"typo": 1})


def test_required_parameter_and_output_schema_are_enforced() -> None:
    definition = Provider(
        "a", parameters={"period": ParameterDefinition(int)}
    ).definition
    with pytest.raises(ValueError, match="Missing required"):
        definition.normalize_parameters()
    with pytest.raises(ValueError, match="missing columns"):
        definition.validate_output(pd.DataFrame({"value": [1.0]}))
    bad = pd.DataFrame({"timestamp": ["not-datetime"], "available_at": ["no"], "value": ["x"]})
    with pytest.raises(ValueError, match="must be"):
        definition.validate_output(bad)


def test_graph_is_deterministic_deduplicated_and_propagates_warmup() -> None:
    registry = FeatureRegistry()
    leaf, left, right, root = (
        Provider("leaf", warmup=2), Provider("left", dependencies=("leaf",), warmup=3),
        Provider("right", dependencies=("leaf",), warmup=4),
        Provider("root", dependencies=("right", "left"), warmup=5),
    )
    for provider in (root, right, leaf, left): registry.register(provider)
    assert registry.dependency_order(["root"]) == ("leaf", "left", "right", "root")
    assert registry.effective_warmup(["root"]) == 11
    registry.execute(["root"], REQUEST, {DatasetKind.KLINES: pd.DataFrame()}, source_identities={DatasetKind.KLINES: "source"})
    assert leaf.calls == left.calls == right.calls == root.calls == 1


def test_identity_propagates_only_related_definition_and_parameters() -> None:
    def identities(child_version="1", period=14, unrelated_version="1"):
        registry = FeatureRegistry()
        child = Provider("child", version=child_version, parameters={"period": ParameterDefinition(int, 14)})
        parent = Provider("parent", dependencies=("child",))
        unrelated = Provider("unrelated", version=unrelated_version)
        for provider in (child, parent, unrelated): registry.register(provider)
        resolved = registry.resolve(["parent", "unrelated"], {"child": {"period": period}})
        values = {}; source = {DatasetKind.KLINES: "source"}
        for item in resolved:
            values[item.definition.name] = registry.identity(item, REQUEST, source, values)
        return values
    base = identities()
    changed_parameter = identities(period=20)
    assert base["child"] != changed_parameter["child"]
    assert base["parent"] != changed_parameter["parent"]
    assert base["unrelated"] == changed_parameter["unrelated"]
    changed_version = identities(child_version="2")
    assert base["parent"] != changed_version["parent"]


def test_production_registry_exposes_core_authoritative_metadata() -> None:
    registry = production_feature_registry()
    expected = {"core_directional", "production_market_context", "support_resistance",
                "state_transition_daily", "funding_context", "basis_context",
                "futures_positioning", "agg_trade_flow"}
    assert expected <= set(registry.names())
    core = registry.get(CORE_DIRECTIONAL_FEATURE_NAME).definition
    assert core.availability_rule == "current_completed_kline_available_at"
    assert set(core.parameters) == {"atr_period", "adx_period", "di_pressure_lookback"}
    daily = registry.get("state_transition_daily").definition
    assert daily.availability_rule == "daily_state_available_from_following_utc_midnight"
    context = registry.get("production_market_context").definition
    assert context.required_features == (CORE_DIRECTIONAL_FEATURE_NAME,)
