"""Rule-aware native Data Lake simulator extensions.

DI pressure remains a causal prepared feature.  This layer only exposes those
already-prepared values to the generic Entry/Veto rule contract and deliberately
neutralizes the retired global DI-pressure allow-list filter.
"""
from __future__ import annotations

import numpy as np

from crypto_strategy_lab.data_lake_production_engine import (
    DataLakeProductionBacktestEngine,
)


DI_PRESSURE_STATE_CODES = {
    "EXPANDING": 1.0,
    "CONTRACTING": 2.0,
    "MIXED": 3.0,
}


class RuleAwareDataLakeProductionBacktestEngine(DataLakeProductionBacktestEngine):
    """Current native runtime with DI-pressure evidence available to scoped rules."""

    def _di_pressure_filter_result(self, i):
        """Retired global pressure filter: Entry/Veto rules are authoritative."""
        del i
        return True, None

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator in {
            "DI_PRESSURE_STATE",
            "DI_SPREAD_CHANGE",
            "DIRECTIONAL_DI_CHANGE",
            "OPPOSING_DI_CHANGE",
        }:
            snapshot = self._di_pressure_snapshot(i, direction)
            if indicator == "DI_PRESSURE_STATE":
                return DI_PRESSURE_STATE_CODES.get(
                    str(snapshot.get("di_pressure_state", "UNKNOWN")).upper(),
                    np.nan,
                )
            field = {
                "DI_SPREAD_CHANGE": "di_spread_change",
                "DIRECTIONAL_DI_CHANGE": "directional_di_change",
                "OPPOSING_DI_CHANGE": "opposing_di_change",
            }[indicator]
            value = snapshot.get(field, np.nan)
            return float(value) if np.isfinite(value) else np.nan
        return super()._strategy_profile_rule_value(i, direction, profile, indicator)
