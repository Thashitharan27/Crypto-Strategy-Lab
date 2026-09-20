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

import numpy as np

from .higher_timeframe_sr import HigherTimeframeSRDetector
from .support_resistance import (
    LocationClassification,
    SRContext,
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
        states_by_source: dict[tuple[str, int], list[tuple[int, dict[str, Any]]]] = {}
        retired_sources: dict[str, set[int]] = {
            SRLevelType.SUPPORT.value: set(),
            SRLevelType.RESISTANCE.value: set(),
        }
        broken_states = {
            SRInteractionState.SUPPORT_BROKEN.value,
            SRInteractionState.RESISTANCE_BROKEN.value,
        }
        for key, state in self._interaction_state.items():
            order = key_order[key]
            for source_index in key[1]:
                states_by_source.setdefault(
                    (key[0], int(source_index)), []
                ).append((order, state))
            if state.get("state") in broken_states:
                retired_sources.setdefault(key[0], set()).update(
                    int(source_index) for source_index in key[1]
                )
        self._research_states_by_source = states_by_source
        self._research_retired_sources = retired_sources
        self._research_zone_cache: dict[
            str, tuple[tuple[tuple[int, float | None], ...], list]
        ] = {}

    def _reset_incremental_state(self) -> None:
        super()._reset_incremental_state()
        self._research_source_first_state = {}
        self._research_interaction_key_order = {}
        self._research_next_interaction_order = 0
        self._research_states_by_source = {}
        self._research_retired_sources = {
            SRLevelType.SUPPORT.value: set(),
            SRLevelType.RESISTANCE.value: set(),
        }
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

        broken_states = {
            SRInteractionState.SUPPORT_BROKEN.value,
            SRInteractionState.RESISTANCE_BROKEN.value,
        }
        candidates = [
            candidate
            for candidate in candidates
            if candidate[1].get("state") not in broken_states
        ]
        if candidates:
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
            source_key = (key[0], int(source_index))
            self._research_source_first_state.setdefault(
                source_key, (order, state)
            )
            self._research_states_by_source.setdefault(source_key, []).append(
                (order, state)
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
        key = self._zone_key(level)
        state = self._interaction_state.get(key)
        if state is not None and state.get("state") in {
            SRInteractionState.SUPPORT_BROKEN.value,
            SRInteractionState.RESISTANCE_BROKEN.value,
        }:
            self._research_retired_sources.setdefault(key[0], set()).update(
                int(source_index) for source_index in key[1]
            )

    def _retired_sources(self, level_type: SRLevelType) -> set[int]:
        self._ensure_research_fast_state()
        return set(
            self._research_retired_sources.get(level_type.value, set())
        )

    def _cached_zones(self, side: str, index: int, atr: float):
        self._ensure_research_fast_state()
        level_type = (
            SRLevelType.SUPPORT if side == "support" else SRLevelType.RESISTANCE
        )
        raw_levels = (
            self._confirmed_lows if side == "support" else self._confirmed_highs
        )
        retired = self._retired_sources(level_type)
        levels = [
            level for level in raw_levels if level.bar_index not in retired
        ]
        # Geometry is fixed at pivot confirmation. Cache until active pivot
        # membership changes, including retirement after a decisive break.
        key = tuple(
            (
                int(level.bar_index),
                float(level.anchor_atr)
                if level.anchor_atr is not None
                else None,
            )
            for level in levels
        )
        cached = self._research_zone_cache.get(side)
        if cached is not None and cached[0] == key:
            return cached[1]

        zones = self.zone_merger.merge_levels(levels, atr) if levels else []
        self._research_zone_cache[side] = (key, zones)
        return zones

    def _find_support_levels(self, high, low, index: int, atr: float):
        return self._cached_zones("support", index, atr)

    def _find_resistance_levels(self, high, low, index: int, atr: float):
        return self._cached_zones("resistance", index, atr)

    def _states_for_current_sources(
        self,
        *,
        support: bool,
    ) -> dict[int, dict[str, Any]]:
        """Return interaction states touching current pivots in insertion order."""
        self._ensure_research_fast_state()
        kind = (
            SRLevelType.SUPPORT.value
            if support
            else SRLevelType.RESISTANCE.value
        )
        current_levels = self._confirmed_lows if support else self._confirmed_highs
        candidates: dict[int, dict[str, Any]] = {}
        for level in current_levels:
            for order, state in self._research_states_by_source.get(
                (kind, int(level.bar_index)), ()
            ):
                candidates.setdefault(int(order), state)
        return candidates

    def _interaction_metrics_for_active_state(
        self,
        index: int,
        support: bool,
        wanted_state: str,
        atr: float,
    ) -> dict:
        # Equivalent to the authoritative full-history scan, but only states
        # that share a currently active source pivot can possibly match.
        del atr
        candidates = [
            (order, state)
            for order, state in self._states_for_current_sources(
                support=support
            ).items()
            if state.get("state") == wanted_state
        ]
        if not candidates:
            return self._interaction_metrics(None, index, support)
        order, state = max(
            candidates,
            key=lambda item: (
                item[1].get("held_index") or -1,
                item[1].get("last_test_index") or -1,
                -int(item[0]),
            ),
        )
        del order
        last_test = state.get("last_test_index")
        held_value = (
            SRInteractionState.SUPPORT_HELD.value
            if support
            else SRInteractionState.RESISTANCE_HELD.value
        )
        return {
            "state": wanted_state,
            "tested": bool(state.get("test_count", 0)),
            "held": wanted_state == held_value,
            "rejection_atr": state.get("rejection_atr", np.nan),
            "test_count": int(state.get("test_count", 0)),
            "bars_since_test": index - last_test if last_test is not None else None,
            "last_test_index": last_test,
        }

    def _latest_broken_zone(self, support: bool) -> dict:
        broken_state = (
            SRInteractionState.SUPPORT_BROKEN.value
            if support
            else SRInteractionState.RESISTANCE_BROKEN.value
        )
        candidates = []
        for order, state in self._states_for_current_sources(
            support=support
        ).items():
            if state.get("state") != broken_state:
                continue
            broken_index = state.get("broken_index")
            low = state.get("broken_zone_low")
            high = state.get("broken_zone_high")
            if broken_index is None or low is None or high is None:
                continue
            candidates.append(
                (
                    int(order),
                    {
                        "index": int(broken_index),
                        "low": float(low),
                        "high": float(high),
                    },
                )
            )
        if not candidates:
            return {"index": None, "low": None, "high": None}
        _order, result = max(
            candidates,
            key=lambda item: (item[1]["index"], -int(item[0])),
        )
        return result


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
    """Higher-timeframe detector optimized for repeated strategy-price queries.

    A 15m research run can ask the same completed 1h/4h/1d S/R candle about many
    different 15m prices. The structural zones and interaction state do not change
    until the next higher-timeframe candle completes, so cache that immutable
    snapshot once per HTF index and only recompute price-relative distances.
    """

    def _reset_incremental_state(self) -> None:
        super()._reset_incremental_state()
        self._research_external_snapshot_cache = None
        self._research_external_snapshot_builds = 0
        self._research_external_snapshot_reuses = 0

    @staticmethod
    def _research_finite_or_none(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if np.isfinite(numeric) else None

    def _research_external_snapshot(
        self,
        index,
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        atr_values,
    ):
        current_atr = float(atr_values[index])
        cached = getattr(self, "_research_external_snapshot_cache", None)
        if (
            cached is not None
            and cached["index"] == int(index)
            and cached["atr"] == current_atr
        ):
            self._research_external_snapshot_reuses = int(
                getattr(self, "_research_external_snapshot_reuses", 0)
            ) + 1
            return cached

        self._advance_to(
            index,
            open_prices,
            high_prices,
            low_prices,
            close_prices,
            atr_values,
        )
        support_levels = self._find_support_levels(
            high_prices, low_prices, index, current_atr
        )
        resistance_levels = self._find_resistance_levels(
            high_prices, low_prices, index, current_atr
        )
        support_metrics = {
            self._zone_key(level): self._interaction_metrics(level, index, True)
            for level in support_levels
        }
        resistance_metrics = {
            self._zone_key(level): self._interaction_metrics(level, index, False)
            for level in resistance_levels
        }
        broken_support = self._interaction_metrics_for_active_state(
            index,
            True,
            SRInteractionState.SUPPORT_BROKEN.value,
            current_atr,
        )
        broken_resistance = self._interaction_metrics_for_active_state(
            index,
            False,
            SRInteractionState.RESISTANCE_BROKEN.value,
            current_atr,
        )
        cached = {
            "index": int(index),
            "atr": current_atr,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "support_metrics": support_metrics,
            "resistance_metrics": resistance_metrics,
            "broken_support": broken_support,
            "broken_resistance": broken_resistance,
        }
        self._research_external_snapshot_cache = cached
        self._research_external_snapshot_builds = int(
            getattr(self, "_research_external_snapshot_builds", 0)
        ) + 1
        return cached

    def analyze_external_price(
        self,
        index: int,
        open_prices: np.ndarray,
        high_prices: np.ndarray,
        low_prices: np.ndarray,
        close_prices: np.ndarray,
        atr_values: np.ndarray,
        direction: str,
        evaluation_price: float,
    ) -> SRContext:
        direction = str(direction).upper()
        if index < self.swing_detector.pivot_left + self.swing_detector.pivot_right:
            return self._default_context()
        current_atr = float(atr_values[index])
        current_price = float(evaluation_price)
        if (
            not np.isfinite(current_atr)
            or current_atr <= 0
            or not np.isfinite(current_price)
        ):
            return self._default_context()

        snapshot = self._research_external_snapshot(
            index,
            open_prices,
            high_prices,
            low_prices,
            close_prices,
            atr_values,
        )
        support_levels = snapshot["support_levels"]
        resistance_levels = snapshot["resistance_levels"]
        nearest_support = self._nearest_level(
            support_levels, current_price, below=True
        )
        nearest_resistance = self._nearest_level(
            resistance_levels, current_price, below=False
        )
        support_dist_price, support_dist_atr = self._calculate_distance(
            current_price, nearest_support, current_atr
        )
        resistance_dist_price, resistance_dist_atr = self._calculate_distance(
            current_price, nearest_resistance, current_atr
        )
        location = self._classify_location(
            nearest_support,
            nearest_resistance,
            support_dist_atr,
            resistance_dist_atr,
        )
        rating = self._rate_location(location, direction)
        room = self._calculate_room_in_direction(
            nearest_support,
            nearest_resistance,
            current_price,
            direction,
            current_atr,
        )

        support_metrics = (
            snapshot["support_metrics"].get(self._zone_key(nearest_support))
            if nearest_support is not None
            else snapshot["broken_support"]
        )
        resistance_metrics = (
            snapshot["resistance_metrics"].get(self._zone_key(nearest_resistance))
            if nearest_resistance is not None
            else snapshot["broken_resistance"]
        )
        if support_metrics is None:
            support_metrics = self._interaction_metrics(None, index, True)
        if resistance_metrics is None:
            resistance_metrics = self._interaction_metrics(None, index, False)
        confirmation_rating = self._confirmation_rating(
            direction,
            support_metrics["state"],
            resistance_metrics["state"],
        )

        return SRContext(
            nearest_support_price=nearest_support.price if nearest_support else None,
            nearest_support_bar_index=nearest_support.bar_index if nearest_support else None,
            nearest_support_distance_atr=support_dist_atr,
            nearest_support_distance_price=support_dist_price,
            nearest_resistance_price=nearest_resistance.price if nearest_resistance else None,
            nearest_resistance_bar_index=nearest_resistance.bar_index if nearest_resistance else None,
            nearest_resistance_distance_atr=resistance_dist_atr,
            nearest_resistance_distance_price=resistance_dist_price,
            price_location=(
                location
                if isinstance(location, LocationClassification)
                else LocationClassification.NO_STRUCTURE
            ),
            trade_location_rating=rating,
            near_support=bool(
                np.isfinite(support_dist_atr)
                and support_dist_atr <= self.near_distance_atr
            ),
            near_resistance=bool(
                np.isfinite(resistance_dist_atr)
                and resistance_dist_atr <= self.near_distance_atr
            ),
            inside_support_zone=bool(
                nearest_support
                and nearest_support.zone_bottom <= current_price <= nearest_support.zone_top
            ),
            inside_resistance_zone=bool(
                nearest_resistance
                and nearest_resistance.zone_bottom <= current_price <= nearest_resistance.zone_top
            ),
            room_in_direction_atr=room,
            structure_conflict=bool(
                np.isfinite(support_dist_atr)
                and support_dist_atr <= self.near_distance_atr
                and np.isfinite(resistance_dist_atr)
                and resistance_dist_atr <= self.near_distance_atr
            ),
            support_state=support_metrics["state"],
            resistance_state=resistance_metrics["state"],
            support_tested=support_metrics["tested"],
            resistance_tested=resistance_metrics["tested"],
            support_held=support_metrics["held"],
            resistance_held=resistance_metrics["held"],
            support_rejection_atr=support_metrics["rejection_atr"],
            resistance_rejection_atr=resistance_metrics["rejection_atr"],
            support_test_count=support_metrics["test_count"],
            resistance_test_count=resistance_metrics["test_count"],
            bars_since_support_test=support_metrics["bars_since_test"],
            bars_since_resistance_test=resistance_metrics["bars_since_test"],
            support_last_test_index=support_metrics["last_test_index"],
            resistance_last_test_index=resistance_metrics["last_test_index"],
            confirmation_rating=confirmation_rating,
            support_zone_low=nearest_support.zone_bottom if nearest_support else None,
            support_zone_high=nearest_support.zone_top if nearest_support else None,
            resistance_zone_low=nearest_resistance.zone_bottom if nearest_resistance else None,
            resistance_zone_high=nearest_resistance.zone_top if nearest_resistance else None,
        )

    def research_zone_inventory(
        self,
        *,
        index: int,
        high: np.ndarray,
        low: np.ndarray,
        current_price: float,
        current_atr: float,
    ):
        """Project cached HTF structure onto one strategy price for diagnostics."""

        snapshot = getattr(self, "_research_external_snapshot_cache", None)
        if snapshot is None or snapshot["index"] != int(index):
            return None
        if not np.isfinite(current_atr) or current_atr <= 0:
            return []

        nearest_support = self._nearest_level(
            snapshot["support_levels"], current_price, below=True
        )
        nearest_resistance = self._nearest_level(
            snapshot["resistance_levels"], current_price, below=False
        )
        nearest_keys = {
            "SUPPORT": (
                self._zone_key(nearest_support)
                if nearest_support is not None
                else None
            ),
            "RESISTANCE": (
                self._zone_key(nearest_resistance)
                if nearest_resistance is not None
                else None
            ),
        }

        result = []
        for support, levels, metrics_by_key in (
            (True, snapshot["support_levels"], snapshot["support_metrics"]),
            (False, snapshot["resistance_levels"], snapshot["resistance_metrics"]),
        ):
            structure = "SUPPORT" if support else "RESISTANCE"
            for level in levels:
                key = self._zone_key(level)
                metrics = metrics_by_key[key]
                distance_price, distance_atr = self._calculate_distance(
                    current_price, level, current_atr
                )
                sources = tuple(int(value) for value in key[1])
                low_value = float(level.zone_bottom)
                high_value = float(level.zone_top)
                result.append(
                    {
                        "zone_id": f"{structure}:" + ",".join(map(str, sources)),
                        "structure": structure,
                        "zone_low": low_value,
                        "zone_high": high_value,
                        "anchor_price": float(level.price),
                        "pivot_bar_index": int(level.bar_index),
                        "confirmed_at_index": (
                            int(level.confirmed_at_index)
                            if level.confirmed_at_index is not None
                            else None
                        ),
                        "source_bar_indices": list(sources),
                        "source_count": len(sources),
                        "touch_count": int(level.touch_count),
                        "validation_rejection_atr": self._research_finite_or_none(
                            level.validation_rejection_atr
                        ),
                        "state": str(metrics["state"]),
                        "tested": bool(metrics["tested"]),
                        "held": bool(metrics["held"]),
                        "rejection_atr": self._research_finite_or_none(
                            metrics["rejection_atr"]
                        ),
                        "test_count": int(metrics["test_count"]),
                        "bars_since_test": (
                            int(metrics["bars_since_test"])
                            if metrics["bars_since_test"] is not None
                            else None
                        ),
                        "last_test_index": (
                            int(metrics["last_test_index"])
                            if metrics["last_test_index"] is not None
                            else None
                        ),
                        "distance_price": self._research_finite_or_none(
                            distance_price
                        ),
                        "distance_atr": self._research_finite_or_none(distance_atr),
                        "near": bool(
                            np.isfinite(distance_atr)
                            and distance_atr <= self.near_distance_atr
                        ),
                        "inside": bool(
                            low_value <= current_price <= high_value
                        ),
                        "nearest": key == nearest_keys[structure],
                    }
                )
        result.sort(
            key=lambda item: (
                0 if item["structure"] == "SUPPORT" else 1,
                float(item["zone_low"]),
                str(item["zone_id"]),
            )
        )
        return result
