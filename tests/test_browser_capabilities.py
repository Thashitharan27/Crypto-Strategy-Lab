import json

from crypto_strategy_lab.browser_capabilities import (
    browser_capabilities,
    feature_capabilities,
)
from crypto_strategy_lab.control_rule_workspace import strategy_capabilities
from crypto_strategy_lab.features import production_feature_registry


def test_browser_strategy_capabilities_reuse_authoritative_control_contract():
    payload = browser_capabilities()

    assert payload["mode"] == "read-only"
    assert payload["strategy"] == strategy_capabilities()
    assert "ADX" in payload["strategy"]["indicators"]
    assert payload["strategy"]["rule_group_model"]["conditions_inside_group"] == "ALL"
    assert payload["strategy"]["rule_group_model"]["groups_inside_family"] == "OR"


def test_browser_feature_capabilities_project_production_registry_without_duplicate_names():
    registry = production_feature_registry()
    payload = feature_capabilities()

    assert [item["name"] for item in payload] == list(registry.names())
    assert len({item["name"] for item in payload}) == len(payload)

    by_name = {item["name"]: item for item in payload}
    for name in registry.names():
        definition = registry.get(name).definition
        item = by_name[name]
        assert item["version"] == definition.version
        assert item["required_datasets"] == [
            dataset.value for dataset in definition.required_datasets
        ]
        assert item["optional_datasets"] == [
            dataset.value for dataset in definition.optional_datasets
        ]
        assert item["required_features"] == list(definition.required_features)
        assert item["warmup_bars"] == definition.warmup_bars
        assert item["availability_rule"] == definition.availability_rule
        assert set(item["parameters"]) == set(definition.parameters)
        assert set(item["output_schema"]) == set(definition.output_schema)


def test_browser_capabilities_are_json_serializable():
    encoded = json.dumps(browser_capabilities(), sort_keys=True)
    assert '"mode": "read-only"' in encoded
