"""Versioned feature-store contracts."""

from .agg_trade_flow import (
    AGG_TRADE_FLOW_FEATURE_NAME,
    AGG_TRADE_FLOW_FEATURE_VERSION,
    AggTradeFlowFeatureProvider,
)
from .base import FeatureDataResource, FeatureDefinition, FeatureProvider, OutputField, ParameterDefinition
from .taker_flow import (TAKER_FLOW_CONTEXT_FEATURE_NAME, TAKER_FLOW_CONTEXT_FEATURE_VERSION,
                         TakerFlowContextFeatureProvider, taker_flow_resource)
from .basis import (
    BASIS_CONTEXT_FEATURE_NAME,
    BASIS_CONTEXT_FEATURE_VERSION,
    BasisContextFeatureProvider,
)
from .cache import FeatureFrameCache
from .context import (
    MARKET_CONTEXT_FEATURE_NAME,
    MARKET_CONTEXT_FEATURE_VERSION,
    MarketContextFeatureProvider,
)
from .funding import (
    FUNDING_CONTEXT_FEATURE_NAME,
    FUNDING_CONTEXT_FEATURE_VERSION,
    FundingContextFeatureProvider,
)
from .futures_positioning import (
    FUTURES_POSITIONING_FEATURE_NAME,
    FUTURES_POSITIONING_FEATURE_VERSION,
    FuturesPositioningFeatureProvider,
)
from .market_regime import (
    POLICY_MARKET_FEATURE_NAME,
    POLICY_MARKET_FEATURE_VERSION,
    PolicyMarketFeatureProvider,
)
from .production_context import (
    PRODUCTION_CONTEXT_FEATURE_NAME,
    PRODUCTION_CONTEXT_FEATURE_VERSION,
    ProductionContextFeatureProvider,
)
from .registry import FeatureRegistry
from .state_transition import StateTransitionDailyFeatureProvider
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
    "FeatureDataResource",
    "FeatureProvider",
    "OutputField",
    "ParameterDefinition",
    "FeatureRegistry",
    "FeatureFrameCache",
    "CORE_DIRECTIONAL_FEATURE_NAME",
    "CORE_DIRECTIONAL_FEATURE_VERSION",
    "CoreDirectionalFeatureProvider",
    "prepare_core_directional_features",
    "MARKET_CONTEXT_FEATURE_NAME",
    "MARKET_CONTEXT_FEATURE_VERSION",
    "MarketContextFeatureProvider",
    "PRODUCTION_CONTEXT_FEATURE_NAME",
    "PRODUCTION_CONTEXT_FEATURE_VERSION",
    "ProductionContextFeatureProvider",
    "POLICY_MARKET_FEATURE_NAME",
    "POLICY_MARKET_FEATURE_VERSION",
    "PolicyMarketFeatureProvider",
    "SUPPORT_RESISTANCE_FEATURE_NAME",
    "SUPPORT_RESISTANCE_FEATURE_VERSION",
    "PreparedSupportResistanceContextReader",
    "SR_CONTEXT_FIELDS",
    "SupportResistanceFeatureProvider",
    "FUTURES_POSITIONING_FEATURE_NAME",
    "FUTURES_POSITIONING_FEATURE_VERSION",
    "FuturesPositioningFeatureProvider",
    "FUNDING_CONTEXT_FEATURE_NAME",
    "FUNDING_CONTEXT_FEATURE_VERSION",
    "FundingContextFeatureProvider",
    "BASIS_CONTEXT_FEATURE_NAME",
    "BASIS_CONTEXT_FEATURE_VERSION",
    "BasisContextFeatureProvider",
    "AGG_TRADE_FLOW_FEATURE_NAME",
    "AGG_TRADE_FLOW_FEATURE_VERSION",
    "AggTradeFlowFeatureProvider",
    "TAKER_FLOW_CONTEXT_FEATURE_NAME", "TAKER_FLOW_CONTEXT_FEATURE_VERSION",
    "TakerFlowContextFeatureProvider", "taker_flow_resource",
]


def production_feature_registry(*, structural_benchmark=None) -> FeatureRegistry:
    """Return the authoritative catalog of native production/research features."""
    registry = FeatureRegistry()
    for provider in (
        CoreDirectionalFeatureProvider(),
        MarketContextFeatureProvider(),
        ProductionContextFeatureProvider(),
        PolicyMarketFeatureProvider(structural_benchmark=structural_benchmark),
        SupportResistanceFeatureProvider(),
        StateTransitionDailyFeatureProvider(),
        FuturesPositioningFeatureProvider(),
        FundingContextFeatureProvider(),
        BasisContextFeatureProvider(),
        TakerFlowContextFeatureProvider(),
        AggTradeFlowFeatureProvider(),
    ):
        registry.register(provider)
    return registry


__all__.append("production_feature_registry")
