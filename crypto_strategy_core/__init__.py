"""Shared deterministic strategy primitives for research and live runtimes."""

from .rules import CORE_CONTRACT_VERSION, PROFILE_KEYS, RULE_INDICATORS
from .indicators import wilder_rsi
from .timeseries import asof_oi_zscore, oi_zscore_observations, rolling_time_zscore

__all__ = [
    "CORE_CONTRACT_VERSION",
    "PROFILE_KEYS",
    "RULE_INDICATORS",
    "wilder_rsi",
    "rolling_time_zscore",
    "oi_zscore_observations",
    "asof_oi_zscore",
]

__version__ = "0.1.0"
