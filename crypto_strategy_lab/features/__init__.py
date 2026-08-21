"""Versioned feature-store contracts."""

from .base import FeatureDefinition, FeatureProvider
from .cache import FeatureFrameCache
from .context import (
    MARKET_CONTEXT_FEATURE_NAME,
    MARKET_CONTEXT_FEATURE_VERSION,
    MarketContextFeatureProvider,
)
from .futures_positioning import (
    FUTURES_POSITIONING_FEATURE_NAME,
    FUTURES_POSITIONING_FEATURE_VERSION,
    FuturesPositioningFeatureProvider,
)
from .registry import FeatureRegistry
from .support_resistance import (
    SUPPORT_RESISTANCE_FEATURE_NAME,
    SUPPORT_RESISTANCE_FEATURE_VERSION,
    PreparedSupportResistanceContextReader,
    SR_CONTEXT_FIELDS,
    SupportResistanceFeatureProvider,
)
from .technical import (
    CORE_DIRECTIONAL_FEATURE_NAME,
    CORE_DIRECTIONAL_FEATURE_VERSION,
    CoreDirectionalFeatureProvider,
    prepare_core_directional_features,
)

__all__ = [
    "FeatureDefinition",
    "FeatureProvider",
    "FeatureRegistry",
    "FeatureFrameCache",
    "CORE_DIRECTIONAL_FEATURE_NAME",
    "CORE_DIRECTIONAL_FEATURE_VERSION",
    "CoreDirectionalFeatureProvider",
    "prepare_core_directional_features",
    "MARKET_CONTEXT_FEATURE_NAME",
    "MARKET_CONTEXT_FEATURE_VERSION",
    "MarketContextFeatureProvider",
    "SUPPORT_RESISTANCE_FEATURE_NAME",
    "SUPPORT_RESISTANCE_FEATURE_VERSION",
    "PreparedSupportResistanceContextReader",
    "SR_CONTEXT_FIELDS",
    "SupportResistanceFeatureProvider",
    "FUTURES_POSITIONING_FEATURE_NAME",
    "FUTURES_POSITIONING_FEATURE_VERSION",
    "FuturesPositioningFeatureProvider",
]
