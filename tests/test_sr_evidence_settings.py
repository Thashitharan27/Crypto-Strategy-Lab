from dataclasses import replace

from crypto_strategy_lab.data_lake_config import FeatureConfig, ResearchRunConfig
from crypto_strategy_lab.features.support_resistance import SupportResistanceFeatureProvider
from crypto_strategy_lab.research_warmup import strategy_warmup_period


def test_hold_confirmation_is_the_normal_feature_default():
    features = FeatureConfig()
    assert features.enable_sr_hold_confirmation is True
    definition = SupportResistanceFeatureProvider().definition
    assert definition.parameters["enable_sr_hold_confirmation"].default is True


def test_timeframe_detection_overrides_inherit_shared_values_until_set():
    features = FeatureConfig(sr_pivot_left=5, sr_pivot_right=5, sr_lookback_bars=200)
    assert features.sr_detection_parameters(15) == {
        "sr_pivot_left": 5,
        "sr_pivot_right": 5,
        "sr_lookback_bars": 200,
    }
    tuned = replace(
        features,
        sr_1d_pivot_left=3,
        sr_1d_pivot_right=2,
        sr_1d_lookback_bars=120,
    )
    assert tuned.sr_detection_parameters(1440) == {
        "sr_pivot_left": 3,
        "sr_pivot_right": 2,
        "sr_lookback_bars": 120,
    }
    # Other timeframes remain untouched.
    assert tuned.sr_detection_parameters(60)["sr_pivot_right"] == 5


def test_registry_carries_raw_overrides_so_each_independent_context_can_resolve_itself():
    features = FeatureConfig(
        enable_support_resistance_analysis=True,
        sr_1h_pivot_right=4,
        sr_4h_lookback_bars=150,
    )
    params = features.registry_parameters(strategy_timeframe_minutes=15)["support_resistance"]
    assert params["enable_sr_hold_confirmation"] is True
    assert params["sr_1h_pivot_right"] == 4
    assert params["sr_4h_lookback_bars"] == 150
    # Primary 15m still uses shared values because its overrides are unset.
    assert params["sr_pivot_right"] == 5
    assert params["sr_lookback_bars"] == 200


def test_sr_warmup_uses_timeframe_specific_horizon():
    base = ResearchRunConfig()
    shared = replace(
        base,
        features=replace(
            base.features,
            enable_support_resistance_analysis=True,
            sr_pivot_left=5,
            sr_pivot_right=5,
            sr_lookback_bars=200,
        ),
    )
    shorter_daily = replace(
        shared,
        features=replace(
            shared.features,
            sr_1d_pivot_left=2,
            sr_1d_pivot_right=2,
            sr_1d_lookback_bars=100,
        ),
    )
    assert strategy_warmup_period(shorter_daily) < strategy_warmup_period(shared)
