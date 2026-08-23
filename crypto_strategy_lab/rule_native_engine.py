"""Rule-aware native Data Lake simulator extensions.

DI pressure remains a causal prepared feature. This layer only exposes those
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

    def _prepared_pressure_value(self, i, direction, indicator):
        """Read pressure rule evidence directly from the already-prepared arrays."""
        if indicator == "DI_SPREAD_CHANGE":
            value = float(self.di_pressure_spread_change[i])
            return value if np.isfinite(value) else np.nan

        if direction == "LONG":
            directional = self.long_directional_di_change
            opposing = self.long_opposing_di_change
            states = self.long_di_pressure_state
        elif direction == "SHORT":
            directional = self.short_directional_di_change
            opposing = self.short_opposing_di_change
            states = self.short_di_pressure_state
        else:
            return np.nan

        if indicator == "DIRECTIONAL_DI_CHANGE":
            value = float(directional[i])
            return value if np.isfinite(value) else np.nan
        if indicator == "OPPOSING_DI_CHANGE":
            value = float(opposing[i])
            return value if np.isfinite(value) else np.nan
        if indicator == "DI_PRESSURE_STATE":
            return DI_PRESSURE_STATE_CODES.get(str(states[i]).upper(), np.nan)
        raise KeyError(indicator)

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator in {
            "DI_PRESSURE_STATE",
            "DI_SPREAD_CHANGE",
            "DIRECTIONAL_DI_CHANGE",
            "OPPOSING_DI_CHANGE",
        } and hasattr(self, "di_pressure_spread_change"):
            return self._prepared_pressure_value(i, direction, indicator)
        return super()._strategy_profile_rule_value(i, direction, profile, indicator)
