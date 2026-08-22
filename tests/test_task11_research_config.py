from dataclasses import replace
import json
import pytest

from crypto_strategy_lab.data_lake_config import (
    ExecutionConfig, FeatureConfig, ReportingConfig, ResearchRunConfig,
    normalize_data_lake_config,
)


def test_v3_is_strict_and_flat_aliases_are_rejected():
    with pytest.raises(ValueError, match="Unknown Data Lake configuration sections"):
        normalize_data_lake_config({"config_version": 3, "atr_period": 7})
    with pytest.raises(ValueError, match="Unknown features settings"):
        normalize_data_lake_config({"config_version": 3, "features": {"output_dir": "x"}})


@pytest.mark.parametrize("component,field,value", [
    ("reporting", "output_dir", "elsewhere"),
    ("reporting", "create_standard_charts", True),
    ("execution", "maker_fee", .9),
    ("execution", "slippage", .1),
])
def test_non_market_configuration_does_not_change_feature_parameters(component, field, value):
    original = ResearchRunConfig()
    changed_part = replace(getattr(original, component), **{field: value})
    changed = replace(original, **{component: changed_part})
    assert changed.features.registry_parameters() == original.features.registry_parameters()


def test_feature_period_deterministically_changes_registry_parameters():
    original = ResearchRunConfig()
    changed = replace(original, features=replace(original.features, adx_period=21))
    assert changed.features.registry_parameters() != original.features.registry_parameters()
