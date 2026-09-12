"""Research-only S/R detector fast paths with unchanged causal semantics.

The normal detector keeps general-purpose caches and resolves merged-zone state by
scanning every historical interaction key.  That is convenient for arbitrary
interactive access, but feature preparation is strictly chronological and can run
across hundreds of thousands of strategy candles.  On those long runs the
historical scan and repeated zone merging become avoidable hot spots.

These subclasses preserve the existing detector formulas and state transitions.
They only add indexes/caches around operations whose inputs have not changed:

* resolve a newly merged zone to the same earliest overlapping interaction state
  in O(number of source pivots) instead of scanning every historical zone key;
* reuse merged support/resistance zones while the detector is still on the same
  source index (especially valuable for 1h/4h/1d S/R evaluated on 15m candles);
* bound the strategy-timeframe presentation caches to the current candle.

No lookback, confirmation rule, ATR input, pivot rule, or S/R classification is
approximated or skipped.
"""
from __future__ import annotations

from typing import Any

from .higher_timeframe_sr import HigherTimeframeSRDetector
from .support_resistance import (
    SRInteractionState,
    SRLevelType,
    SupportResistanceDetector,
)


class _ResearchSRFastPathMixin:
    """Accelerate chronological research preparation without changing results."""

    def _ensure_research_fast_state(self) -> None:
        if hasattr(self, "_research_source_first_state"):
            return

        # The legacy implementation scans ``_interaction_state`` in insertion
        # order and copies the first state whose merged-zone source pivots
        # overlap.  Index each source pivot to that same earliest state so the
        # lookup remains exactly equivalent while avoiding an ever-growing scan.
        source_first: dict[tuple[str, int], tuple[int, dict[str, Any]]] = {}
        key_order: dict[tuple[str, tuple[int, ...]], int] = {}
        for order, (key, state) in enumerate(self._interaction_state.items()):
            key_order[key] = order
            for source_index in key[1]:
                source_first.setdefault((key[0], int(source_index)), (order, state))

        self._research_source_first_state = source_first
        self._research_interaction_key_order = key_order
        self._research_next_interaction_order = len(key_order)
        self._research_zone_cache: dict[
            str, tuple[tuple[int, float], list]
        ] = {}

    def _reset_incremental_state(self) -> None:
        super()._reset_incremental_state()
        self._research_source_first_state = {}
        self._research_interaction_key_order = {}
        self._research_next_interaction_order = 0
        self._research_zone_cache = {}

    def _seed_interaction_state(self, level) -> None:
        self._ensure_research_fast_state()
        key = self._zone_key(level)
        if key in self._interaction_state:
            return

        candidates = []
        for source_index in key[1]:
            candidate = self._research_source_first_state.get(
                (key[0], int(source_index))
            )
            if candidate is not None:
                candidates.append(candidate)

        if candidates:
            # Match the dict insertion-order scan used by the legacy detector.
            _, existing_state = min(candidates, key=lambda item: item[0])
            state = dict(existing_state)
        else:
            support = level.level_type == SRLevelType.SUPPORT
            state = {
                "state": (
                    SRInteractionState.APPROACHING_SUPPORT.value
                    if support
                    else SRInteractionState.APPROACHING_RESISTANCE.value
                ),
                "last_test_index": None,
                "test_count": 0,
                "pending_test_index": None,
                "rejection_atr": float("nan"),
                "held_index": None,
            }

        # Insert before delegating to the authoritative state-transition method.
        # That makes its historical overlap scan unnecessary while leaving all
        # break/test/hold calculations in the original implementation.
        self._interaction_state[key] = state
        order = self._research_next_interaction_order
        self._research_next_interaction_order += 1
        self._research_interaction_key_order[key] = order
        for source_index in key[1]:
            self._research_source_first_state.setdefault(
                (key[0], int(source_index)), (order, state)
            )

    def _update_zone_interaction(
        self,
        level,
        index,
        open_prices,
        high,
        low,
        close,
        atr,
    ) -> None:
        self._seed_interaction_state(level)
        super()._update_zone_interaction(
            level,
            index,
            open_prices,
            high,
            low,
            close,
            atr,
        )

    def _cached_zones(self, side: str, index: int, atr: float):
        self._ensure_research_fast_state()
        key = (int(index), float(atr))
        cached = self._research_zone_cache.get(side)
        if cached is not None and cached[0] == key:
            return cached[1]

        levels = self._confirmed_lows if side == "support" else self._confirmed_highs
        zones = self.zone_merger.merge_levels(levels, atr) if levels else []
        self._research_zone_cache[side] = (key, zones)
        return zones

    def _find_support_levels(self, high, low, index: int, atr: float):
        return self._cached_zones("support", index, atr)

    def _find_resistance_levels(self, high, low, index: int, atr: float):
        return self._cached_zones("resistance", index, atr)

    def _interaction_metrics_for_active_state(
        self,
        index: int,
        support: bool,
        wanted_state: str,
        atr: float,
    ) -> dict:
        zones = (
            self._find_support_levels(None, None, index, atr)
            if support
            else self._find_resistance_levels(None, None, index, atr)
        )
        for level in zones:
            state = self._interaction_state.get(self._zone_key(level), {})
            if state.get("state") == wanted_state:
                return self._interaction_metrics(level, index, support)
        return self._interaction_metrics(None, index, support)


class ResearchSupportResistanceDetector(
    _ResearchSRFastPathMixin,
    SupportResistanceDetector,
):
    """Strategy-timeframe detector optimized for one chronological research pass."""

    def analyze_price_location(
        self,
        index,
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        atr_values,
        direction,
    ):
        context = super().analyze_price_location(
            index,
            open_prices,
            high_prices,
            low_prices,
            close_prices,
            atr_values,
            direction,
        )

        # Feature preparation asks LONG then SHORT for the current bar and never
        # needs presentation caches for thousands of old bars.  Keep the current
        # bar so the opposite-direction call still shares the expensive base
        # context, but prevent multi-year runs from accumulating those objects.
        for key in list(self._base_context_cache):
            if key != index:
                self._base_context_cache.pop(key, None)
        for key in list(self._context_cache):
            if key[0] != index:
                self._context_cache.pop(key, None)
        for key in list(self._context_input_cache):
            if key != index:
                self._context_input_cache.pop(key, None)
        return context


class ResearchHigherTimeframeSRDetector(
    _ResearchSRFastPathMixin,
    HigherTimeframeSRDetector,
):
    """Higher-timeframe detector optimized for repeated strategy-price queries."""

    pass
