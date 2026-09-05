"""Shared deterministic strategy primitives for research and live runtimes."""

from .rules import CORE_CONTRACT_VERSION, PROFILE_KEYS, RULE_INDICATORS
from .indicators import wilder_rsi
from .funding import funding_bias, funding_rule_evidence_at, funding_rule_evidence_series
from .positioning import positioning_evidence_series, ratio_bias_evidence_series
from .candles import (
    atr,
    bollinger_bands,
    causal_trailing_return,
    close_location,
    directional_pressure_features,
    directional_rule_evidence,
    true_range,
    utc_session_vwap,
    wilder_rma,
)
from .timeseries import asof_oi_zscore, oi_zscore_observations, rolling_time_zscore

__all__ = [
    "CORE_CONTRACT_VERSION",
    "PROFILE_KEYS",
    "RULE_INDICATORS",
    "wilder_rsi",
    "funding_bias",
    "funding_rule_evidence_at",
    "funding_rule_evidence_series",
    "positioning_evidence_series",
    "ratio_bias_evidence_series",
    "atr",
    "bollinger_bands",
    "causal_trailing_return",
    "close_location",
    "directional_pressure_features",
    "directional_rule_evidence",
    "true_range",
    "utc_session_vwap",
    "wilder_rma",
    "rolling_time_zscore",
    "oi_zscore_observations",
    "asof_oi_zscore",
]

__version__ = "0.1.0"
