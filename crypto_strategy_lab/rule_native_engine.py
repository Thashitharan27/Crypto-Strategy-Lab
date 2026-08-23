"""Rule-aware native Data Lake simulator extensions.

DI pressure and support/resistance remain causal prepared features. This layer
only exposes those already-prepared values to the generic Entry/Veto rule
contract and neutralizes retired independent filtering paths.
"""
from __future__ import annotations

import numpy as np

from crypto_strategy_lab.data_lake_production_engine import (
    DataLakeProductionBacktestEngine,
)
from crypto_strategy_lab.strategy_rule_model import CATEGORICAL_VALUE_CODES


DI_PRESSURE_STATE_CODES = CATEGORICAL_VALUE_CODES["DI_PRESSURE_STATE"]

_SR_CATEGORICAL_FIELDS = {
    "SR_NEAR_SUPPORT": "near_support",
    "SR_NEAR_RESISTANCE": "near_resistance",
    "SR_INSIDE_SUPPORT_ZONE": "inside_support_zone",
    "SR_INSIDE_RESISTANCE_ZONE": "inside_resistance_zone",
    "SR_SUPPORT_STATE": "support_state",
    "SR_RESISTANCE_STATE": "resistance_state",
    "SR_SUPPORT_HELD": "support_held",
    "SR_RESISTANCE_HELD": "resistance_held",
    "SR_TRADE_LOCATION_RATING": "trade_location_rating",
}
_SR_NUMERIC_FIELDS = {
    "SR_ROOM_IN_DIRECTION_ATR": "room_in_direction_atr",
    "SR_SUPPORT_DISTANCE_ATR": "nearest_support_distance_atr",
    "SR_RESISTANCE_DISTANCE_ATR": "nearest_resistance_distance_atr",
    "SR_SUPPORT_REJECTION_ATR": "support_rejection_atr",
    "SR_RESISTANCE_REJECTION_ATR": "resistance_rejection_atr",
}
_SR_RULE_INDICATORS = frozenset((*_SR_CATEGORICAL_FIELDS, *_SR_NUMERIC_FIELDS))


class RuleAwareDataLakeProductionBacktestEngine(DataLakeProductionBacktestEngine):
    """Current native runtime with prepared research evidence available to rules."""

    def _di_pressure_filter_result(self, i):
        """Retired global pressure filter: Entry/Veto rules are authoritative."""
        del i
        return True, None

    def _should_reject_for_sr(self, i, direction, sr_context=None):
        """Retired S/R preset filter: Entry/Veto rules are authoritative."""
        del i, direction, sr_context
        return False, None

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

    def _prepared_sr_context(self, i, direction):
        """Return one O(1) prepared S/R context and reuse it for all rules at the row."""
        if direction not in {"LONG", "SHORT"}:
            return None
        if not getattr(getattr(self, "config", None), "enable_support_resistance_analysis", False):
            return None
        pending = getattr(self, "_pending_sr_context", None)
        if pending is not None and pending[0] == i and pending[1] == direction:
            return pending[2]
        context = self._analyze_support_resistance(i, direction)
        self._pending_sr_context = (i, direction, context)
        return context

    @staticmethod
    def _categorical_sr_value(indicator, raw):
        if hasattr(raw, "value"):
            raw = raw.value
        if isinstance(raw, (bool, np.bool_)):
            key = "TRUE" if bool(raw) else "FALSE"
        else:
            key = str(raw).upper()
        return CATEGORICAL_VALUE_CODES[indicator].get(key, np.nan)

    def _prepared_sr_value(self, i, direction, indicator):
        context = self._prepared_sr_context(i, direction)
        if context is None:
            return np.nan
        if indicator in _SR_CATEGORICAL_FIELDS:
            raw = getattr(context, _SR_CATEGORICAL_FIELDS[indicator])
            return self._categorical_sr_value(indicator, raw)
        if indicator in _SR_NUMERIC_FIELDS:
            raw = getattr(context, _SR_NUMERIC_FIELDS[indicator])
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return np.nan
            return value if np.isfinite(value) else np.nan
        raise KeyError(indicator)

    def _strategy_profile_rule_value(self, i, direction, profile, indicator):
        if indicator in {
            "DI_PRESSURE_STATE",
            "DI_SPREAD_CHANGE",
            "DIRECTIONAL_DI_CHANGE",
            "OPPOSING_DI_CHANGE",
        } and hasattr(self, "di_pressure_spread_change"):
            return self._prepared_pressure_value(i, direction, indicator)
        if indicator in _SR_RULE_INDICATORS:
            return self._prepared_sr_value(i, direction, indicator)
        return super()._strategy_profile_rule_value(i, direction, profile, indicator)
