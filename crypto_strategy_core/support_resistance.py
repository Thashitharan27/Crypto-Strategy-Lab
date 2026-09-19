"""Causal support/resistance zones built from confirmed rejection structure."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np
from numpy.typing import NDArray


class SRLevelType(Enum):
    """Type of support/resistance level."""
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class LocationClassification(Enum):
    """Structural location classification."""
    NEAR_SUPPORT = "NEAR_SUPPORT"
    NEAR_RESISTANCE = "NEAR_RESISTANCE"
    BETWEEN_LEVELS = "BETWEEN_LEVELS"
    NO_STRUCTURE = "NO_STRUCTURE"


class TradeLocationRating(Enum):
    """Trade location quality relative to direction."""
    GOOD_LOCATION = "GOOD_LOCATION"
    NEUTRAL_LOCATION = "NEUTRAL_LOCATION"
    BAD_LOCATION = "BAD_LOCATION"


class SRInteractionState(Enum):
    """Causal interaction state for an active support or resistance zone."""
    NO_SUPPORT_NEARBY = "NO_SUPPORT_NEARBY"
    APPROACHING_SUPPORT = "APPROACHING_SUPPORT"
    SUPPORT_TESTING = "SUPPORT_TESTING"
    SUPPORT_HELD = "SUPPORT_HELD"
    SUPPORT_BROKEN = "SUPPORT_BROKEN"
    NO_RESISTANCE_NEARBY = "NO_RESISTANCE_NEARBY"
    APPROACHING_RESISTANCE = "APPROACHING_RESISTANCE"
    RESISTANCE_TESTING = "RESISTANCE_TESTING"
    RESISTANCE_HELD = "RESISTANCE_HELD"
    RESISTANCE_BROKEN = "RESISTANCE_BROKEN"


@dataclass
class SRLevel:
    """A single support or resistance level."""
    price: float
    level_type: SRLevelType
    bar_index: int  # where it was confirmed
    first_touch_index: int  # earliest touch
    touch_count: int = 1
    confirmed_at_index: Optional[int] = None  # after pivot_right delay
    anchor_atr: Optional[float] = None  # ATR known when the pivot became usable
    validation_rejection_atr: float = float("nan")
    zone_bottom: Optional[float] = None
    zone_top: Optional[float] = None
    source_bar_indices: tuple[int, ...] = ()
    
    def __post_init__(self):
        if self.zone_bottom is None:
            self.zone_bottom = self.price
        if self.zone_top is None:
            self.zone_top = self.price


@dataclass
class SRContext:
    """Support/resistance context for an entry candidate."""
    nearest_support_price: Optional[float]
    nearest_support_bar_index: Optional[int]
    nearest_support_distance_atr: float
    nearest_support_distance_price: float
    
    nearest_resistance_price: Optional[float]
    nearest_resistance_bar_index: Optional[int]
    nearest_resistance_distance_atr: float
    nearest_resistance_distance_price: float
    
    price_location: LocationClassification
    trade_location_rating: TradeLocationRating
    
    near_support: bool  # within near_distance_atr of support
    near_resistance: bool  # within near_distance_atr of resistance
    
    inside_support_zone: bool
    inside_resistance_zone: bool
    
    room_in_direction_atr: float  # ATR distance to opposing structure
    structure_conflict: bool = False  # simultaneously near support and resistance
    support_state: str = SRInteractionState.NO_SUPPORT_NEARBY.value
    resistance_state: str = SRInteractionState.NO_RESISTANCE_NEARBY.value
    support_tested: bool = False
    resistance_tested: bool = False
    support_held: bool = False
    resistance_held: bool = False
    support_rejection_atr: float = float("nan")
    resistance_rejection_atr: float = float("nan")
    support_test_count: int = 0
    resistance_test_count: int = 0
    bars_since_support_test: Optional[int] = None
    bars_since_resistance_test: Optional[int] = None
    support_last_test_index: Optional[int] = None
    resistance_last_test_index: Optional[int] = None
    confirmation_rating: str = "NEUTRAL"
    support_zone_low: Optional[float] = None
    support_zone_high: Optional[float] = None
    resistance_zone_low: Optional[float] = None
    resistance_zone_high: Optional[float] = None
    support_last_break_index: Optional[int] = None
    resistance_last_break_index: Optional[int] = None
    support_broken_zone_low: Optional[float] = None
    support_broken_zone_high: Optional[float] = None
    resistance_broken_zone_low: Optional[float] = None
    resistance_broken_zone_high: Optional[float] = None


def _positive_integral(value, name: str) -> int:
    """Return a positive integer without silently truncating fractional input."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a positive integer")
    try:
        numeric = float(value)
        result = int(numeric)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if not np.isfinite(numeric) or numeric != result or result < 1:
        raise ValueError(f"{name} must be a positive integer")
    return result


class SwingDetector:
    """Detects swing highs and swing lows with no look-ahead bias."""
    
    def __init__(
        self,
        pivot_left: int = 5,
        pivot_right: int = 5,
        min_bars_between: int = 1
    ):
        """
        Args:
            pivot_left: candles to left of candidate peak/valley
            pivot_right: candles to right of candidate peak/valley (enforces confirmation delay)
            min_bars_between: minimum bars between adjacent swings
        """
        self.pivot_left = _positive_integral(pivot_left, "pivot_left")
        self.pivot_right = _positive_integral(pivot_right, "pivot_right")
        self.min_bars_between = _positive_integral(
            min_bars_between, "min_bars_between"
        )
        
    def detect_swing_highs(
        self, high: NDArray[np.float64], index: int
    ) -> list[int]:
        """
        Detect swing highs available at candle index.
        
        A swing high at bar i is only available from bar i + pivot_right onward.
        This prevents look-ahead bias.
        
        Example:
            pivot_left=2, pivot_right=2
            Swing high at bar 100 only available from bar 102 onward
        
        Args:
            high: numpy array of high prices (full history)
            index: current candle index (where we're evaluating)
            
        Returns:
            List of bar indices where swing highs were confirmed
        """
        swings = []
        # Scan from pivot_left to current - pivot_right (cutoff for confirmation)
        cutoff = index - self.pivot_right
        if cutoff < self.pivot_left:
            return swings
            
        for i in range(self.pivot_left, cutoff + 1):
            # Check if high[i] is the highest within the pivot window
            # Left: from i-pivot_left to i-1
            # Right: from i+1 to i+pivot_right
            left_start = max(0, i - self.pivot_left)
            right_end = min(len(high), i + self.pivot_right + 1)
            
            left_slice = high[left_start:i]
            right_slice = high[i + 1:right_end]
            
            if len(left_slice) == 0 or len(right_slice) == 0:
                continue
            
            left_max = np.max(left_slice)
            right_max = np.max(right_slice)
            
            # high[i] must be > at least one of left/right (strict for one)
            # and >= all values (non-strict for other)
            if high[i] > left_max and high[i] >= right_max:
                # Ensure min gap from previous swing
                if not swings or (i - swings[-1] >= self.min_bars_between):
                    swings.append(i)
            elif high[i] >= left_max and high[i] > right_max:
                # Ensure min gap from previous swing
                if not swings or (i - swings[-1] >= self.min_bars_between):
                    swings.append(i)
        
        return swings
    
    def detect_swing_lows(
        self, low: NDArray[np.float64], index: int
    ) -> list[int]:
        """
        Detect swing lows available at candle index.
        
        Mirrors detect_swing_highs() logic but for lows.
        A swing low at bar i is only available from bar i + pivot_right onward.
        
        Args:
            low: numpy array of low prices (full history)
            index: current candle index
            
        Returns:
            List of bar indices where swing lows were confirmed
        """
        swings = []
        cutoff = index - self.pivot_right
        if cutoff < self.pivot_left:
            return swings
            
        for i in range(self.pivot_left, cutoff + 1):
            left_start = max(0, i - self.pivot_left)
            right_end = min(len(low), i + self.pivot_right + 1)
            
            left_slice = low[left_start:i]
            right_slice = low[i + 1:right_end]
            
            if len(left_slice) == 0 or len(right_slice) == 0:
                continue
            
            left_min = np.min(left_slice)
            right_min = np.min(right_slice)
            
            # low[i] must be < at least one of left/right (strict for one)
            # and <= all values (non-strict for other)
            if low[i] < left_min and low[i] <= right_min:
                if not swings or (i - swings[-1] >= self.min_bars_between):
                    swings.append(i)
            elif low[i] <= left_min and low[i] < right_min:
                if not swings or (i - swings[-1] >= self.min_bars_between):
                    swings.append(i)
        
        return swings


class SRZoneMerger:
    """Merge already-defined rejection zones without rewriting their geometry."""

    def __init__(
        self,
        zone_width_atr: float = 0.15,
        zone_padding_atr: float = 0.10,
        max_cluster_span_atr: float = 0.50,
    ):
        """
        Historical config names are retained at the storage/API boundary.

        zone_width_atr:
            Maximum edge-to-edge gap allowed when two confirmed rejection zones
            are merged.
        zone_padding_atr:
            Minimum single-zone width in ATR units. Runtime pivots already carry
            concrete wick/body bounds; this value is only a legacy fallback here.
        max_cluster_span_atr:
            Maximum merged-zone span in ATR units.
        """
        self.zone_width_atr = max(0.0, float(zone_width_atr))
        self.zone_padding_atr = max(0.0, float(zone_padding_atr))
        self.max_cluster_span_atr = max(0.0, float(max_cluster_span_atr))

    @staticmethod
    def _anchored_atr(level: SRLevel, fallback_atr: float | None) -> float:
        anchor = level.anchor_atr
        if anchor is not None:
            try:
                value = float(anchor)
            except (TypeError, ValueError):
                value = float("nan")
            if np.isfinite(value) and value > 0:
                return value
        if level.confirmed_at_index is not None:
            return float("nan")
        try:
            fallback = float(fallback_atr)
        except (TypeError, ValueError):
            fallback = float("nan")
        return fallback if np.isfinite(fallback) and fallback > 0 else float("nan")

    def _bounds(
        self, level: SRLevel, fallback_atr: float | None
    ) -> tuple[float, float]:
        low = float(level.zone_bottom if level.zone_bottom is not None else level.price)
        high = float(level.zone_top if level.zone_top is not None else level.price)
        if high < low:
            low, high = high, low
        if high > low:
            return low, high

        anchor = self._anchored_atr(level, fallback_atr)
        if np.isfinite(anchor) and anchor > 0 and self.zone_padding_atr > 0:
            half = 0.5 * self.zone_padding_atr * anchor
            return float(level.price) - half, float(level.price) + half
        return low, high

    def merge_levels(
        self, levels: list[SRLevel], atr: float | None = None
    ) -> list[SRLevel]:
        if not levels:
            return []

        sorted_levels = sorted(
            levels,
            key=lambda item: self._bounds(item, atr)[0],
        )
        merged: list[SRLevel] = []
        current_zone = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            current_low = min(self._bounds(item, atr)[0] for item in current_zone)
            current_high = max(self._bounds(item, atr)[1] for item in current_zone)
            next_low, next_high = self._bounds(level, atr)

            anchors = [
                self._anchored_atr(item, atr)
                for item in (*current_zone, level)
            ]
            finite = [value for value in anchors if np.isfinite(value) and value > 0]
            reference_atr = min(finite) if len(finite) == len(anchors) else float("nan")

            edge_gap = max(0.0, next_low - current_high)
            proposed_low = min(current_low, next_low)
            proposed_high = max(current_high, next_high)
            proposed_span = proposed_high - proposed_low

            within_gap = (
                np.isfinite(reference_atr)
                and edge_gap <= self.zone_width_atr * reference_atr
            )
            within_span = (
                np.isfinite(reference_atr)
                and proposed_span <= self.max_cluster_span_atr * reference_atr
            )
            if within_gap and within_span:
                current_zone.append(level)
            else:
                merged.append(self._finalize_zone(current_zone, atr))
                current_zone = [level]

        merged.append(self._finalize_zone(current_zone, atr))
        return merged

    def _finalize_zone(
        self, zone_levels: list[SRLevel], fallback_atr: float | None
    ) -> SRLevel:
        level_type = zone_levels[0].level_type
        prices = [float(level.price) for level in zone_levels]
        lows = [self._bounds(level, fallback_atr)[0] for level in zone_levels]
        highs = [self._bounds(level, fallback_atr)[1] for level in zone_levels]
        anchors = [
            self._anchored_atr(level, fallback_atr) for level in zone_levels
        ]
        finite_anchors = [value for value in anchors if np.isfinite(value) and value > 0]

        result = SRLevel(
            price=min(prices) if level_type == SRLevelType.SUPPORT else max(prices),
            level_type=level_type,
            bar_index=max(level.bar_index for level in zone_levels),
            first_touch_index=min(level.first_touch_index for level in zone_levels),
            touch_count=sum(level.touch_count for level in zone_levels),
            confirmed_at_index=max(
                (
                    level.confirmed_at_index
                    if level.confirmed_at_index is not None
                    else level.bar_index
                )
                for level in zone_levels
            ),
            anchor_atr=min(finite_anchors) if finite_anchors else None,
            validation_rejection_atr=max(
                (
                    float(level.validation_rejection_atr)
                    for level in zone_levels
                    if np.isfinite(level.validation_rejection_atr)
                ),
                default=float("nan"),
            ),
            source_bar_indices=tuple(
                sorted(
                    {
                        source
                        for level in zone_levels
                        for source in (
                            level.source_bar_indices or (level.bar_index,)
                        )
                    }
                )
            ),
        )
        result.zone_bottom = min(lows)
        result.zone_top = max(highs)
        return result


class SupportResistanceDetector:
    """Detects and manages support/resistance levels incrementally."""
    
    def __init__(
        self,
        pivot_left: int = 5,
        pivot_right: int = 5,
        lookback_bars: int = 200,
        zone_width_atr: float = 0.15,
        zone_padding_atr: float = 0.10,
        max_cluster_span_atr: float = 0.50,
        min_rejection_atr: float = 0.50,
        near_distance_atr: float = 0.75,
        enable_hold_confirmation: bool = True,
        hold_confirmation_bars: int = 3,
        hold_confirmation_atr: float = 0.25,
        break_tolerance_atr: float = 0.25,
        break_basis: str = "CLOSE",
    ):
        """
        Args:
            pivot_left: bars to left for swing detection
            pivot_right: bars to right for swing detection (delays level availability)
            lookback_bars: how many historical bars to scan for levels
            zone_width_atr: merge rejection zones whose edges are within this ATR distance
            zone_padding_atr: minimum rejection-zone width in ATR units
            max_cluster_span_atr: maximum rejection/merged-zone width in ATR units
            min_rejection_atr: minimum causal displacement required to validate a pivot
            near_distance_atr: distance to be considered "near" a level
        """
        self.swing_detector = SwingDetector(
            pivot_left=pivot_left, pivot_right=pivot_right
        )
        self.zone_merger = SRZoneMerger(
            zone_width_atr=zone_width_atr,
            zone_padding_atr=zone_padding_atr,
            max_cluster_span_atr=max_cluster_span_atr,
        )
        self.lookback_bars = _positive_integral(lookback_bars, "lookback_bars")
        self.zone_width_atr = float(zone_width_atr)
        self.zone_padding_atr = float(zone_padding_atr)
        self.max_cluster_span_atr = float(max_cluster_span_atr)
        self.min_rejection_atr = max(0.0, float(min_rejection_atr))
        self.near_distance_atr = near_distance_atr
        self.enable_hold_confirmation = bool(enable_hold_confirmation)
        self.hold_confirmation_bars = _positive_integral(
            hold_confirmation_bars, "hold_confirmation_bars"
        )
        self.hold_confirmation_atr = max(0.0, float(hold_confirmation_atr))
        self.break_tolerance_atr = max(0.0, float(break_tolerance_atr))
        self.break_basis = str(break_basis).upper()
        self._confirmed_highs: list[SRLevel] = []
        self._confirmed_lows: list[SRLevel] = []
        self._last_processed_index = -1
        self._base_context_cache: dict[int, tuple] = {}
        self._context_cache: dict[tuple[int, str], SRContext] = {}
        self._context_input_cache: dict[int, tuple[float, float]] = {}
        self._interaction_state: dict[tuple[str, tuple[int, ...]], dict] = {}

    def _reset_incremental_state(self) -> None:
        self._confirmed_highs.clear()
        self._confirmed_lows.clear()
        self._last_processed_index = -1
        self._base_context_cache.clear()
        self._context_cache.clear()
        self._context_input_cache.clear()
        self._interaction_state.clear()

    def _is_swing_high(self, high: NDArray[np.float64], index: int) -> bool:
        left = high[index - self.swing_detector.pivot_left:index]
        right = high[index + 1:index + self.swing_detector.pivot_right + 1]
        if len(left) == 0 or len(right) == 0:
            return False
        return (high[index] > np.max(left) and high[index] >= np.max(right)) or (
            high[index] >= np.max(left) and high[index] > np.max(right)
        )

    def _is_swing_low(self, low: NDArray[np.float64], index: int) -> bool:
        left = low[index - self.swing_detector.pivot_left:index]
        right = low[index + 1:index + self.swing_detector.pivot_right + 1]
        if len(left) == 0 or len(right) == 0:
            return False
        return (low[index] < np.min(left) and low[index] <= np.min(right)) or (
            low[index] <= np.min(left) and low[index] < np.min(right)
        )

    def _pivot_zone_bounds(
        self,
        *,
        support: bool,
        pivot_index: int,
        open_prices: NDArray,
        high: NDArray,
        low: NDArray,
        close: NDArray,
        anchor_atr: float,
    ) -> tuple[float, float]:
        """Build a rejection zone from the pivot candle wick/body geometry."""
        open_ = float(open_prices[pivot_index])
        close_ = float(close[pivot_index])
        minimum_width = self.zone_padding_atr * anchor_atr
        maximum_width = self.max_cluster_span_atr * anchor_atr
        if maximum_width < minimum_width:
            maximum_width = minimum_width

        if support:
            bottom = float(low[pivot_index])
            raw_top = float(min(open_, close_))
            width = max(0.0, raw_top - bottom)
            width = min(max(width, minimum_width), maximum_width)
            return bottom, bottom + width

        top = float(high[pivot_index])
        raw_bottom = float(max(open_, close_))
        width = max(0.0, top - raw_bottom)
        width = min(max(width, minimum_width), maximum_width)
        return top - width, top

    @staticmethod
    def _pivot_rejection_atr(
        *,
        support: bool,
        pivot_index: int,
        confirmation_index: int,
        close: NDArray,
        zone_bottom: float,
        zone_top: float,
        anchor_atr: float,
    ) -> float:
        if not np.isfinite(anchor_atr) or anchor_atr <= 0:
            return float("nan")
        start = min(pivot_index + 1, confirmation_index)
        window = np.asarray(close[start:confirmation_index + 1], dtype=float)
        window = window[np.isfinite(window)]
        if not len(window):
            return 0.0
        if support:
            displacement = max(0.0, float(np.max(window)) - zone_top)
        else:
            displacement = max(0.0, zone_bottom - float(np.min(window)))
        return displacement / anchor_atr

    def _make_confirmed_level(
        self,
        *,
        support: bool,
        pivot_index: int,
        confirmation_index: int,
        open_prices: NDArray,
        high: NDArray,
        low: NDArray,
        close: NDArray,
        atr_values: NDArray,
    ) -> Optional[SRLevel]:
        if confirmation_index >= len(atr_values):
            return None
        anchor_atr = float(atr_values[confirmation_index])
        if not np.isfinite(anchor_atr) or anchor_atr <= 0:
            return None

        zone_bottom, zone_top = self._pivot_zone_bounds(
            support=support,
            pivot_index=pivot_index,
            open_prices=open_prices,
            high=high,
            low=low,
            close=close,
            anchor_atr=anchor_atr,
        )
        rejection = self._pivot_rejection_atr(
            support=support,
            pivot_index=pivot_index,
            confirmation_index=confirmation_index,
            close=close,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            anchor_atr=anchor_atr,
        )
        if not np.isfinite(rejection) or rejection < self.min_rejection_atr:
            return None

        return SRLevel(
            price=float(low[pivot_index] if support else high[pivot_index]),
            level_type=SRLevelType.SUPPORT if support else SRLevelType.RESISTANCE,
            bar_index=pivot_index,
            first_touch_index=pivot_index,
            confirmed_at_index=confirmation_index,
            anchor_atr=anchor_atr,
            validation_rejection_atr=rejection,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            source_bar_indices=(pivot_index,),
        )

    def _append_confirmed_level(self, levels: list[SRLevel], level: SRLevel) -> None:
        if levels and level.bar_index - levels[-1].bar_index < self.swing_detector.min_bars_between:
            return
        levels.append(level)

    def _expire_levels(self, index: int) -> None:
        cutoff = index - self.lookback_bars
        self._confirmed_highs = [level for level in self._confirmed_highs if level.bar_index >= cutoff]
        self._confirmed_lows = [level for level in self._confirmed_lows if level.bar_index >= cutoff]

    def _zone_key(self, level: SRLevel) -> tuple[str, tuple[int, ...]]:
        sources = level.source_bar_indices or (level.bar_index,)
        return level.level_type.value, tuple(sorted(sources))

    def _update_zone_interaction(self, level: SRLevel, index: int, open_prices: NDArray, high: NDArray, low: NDArray, close: NDArray, atr: float) -> None:
        key = self._zone_key(level)
        state = self._interaction_state.get(key)
        if state is None:
            level_sources = set(key[1])
            for existing_key, existing_state in self._interaction_state.items():
                if (
                    existing_key[0] == key[0]
                    and level_sources.intersection(existing_key[1])
                    and existing_state.get("state")
                    not in {
                        SRInteractionState.SUPPORT_BROKEN.value,
                        SRInteractionState.RESISTANCE_BROKEN.value,
                    }
                ):
                    state = dict(existing_state)
                    self._interaction_state[key] = state
                    break
        if state is None:
            state = {
            "state": SRInteractionState.APPROACHING_SUPPORT.value if level.level_type == SRLevelType.SUPPORT else SRInteractionState.APPROACHING_RESISTANCE.value,
            "last_test_index": None, "test_count": 0, "pending_test_index": None,
            "rejection_atr": np.nan, "held_index": None,
            }
            self._interaction_state[key] = state
        if not np.isfinite(atr) or atr <= 0:
            return
        support = level.level_type == SRLevelType.SUPPORT
        break_price = low[index] if self.break_basis == "WICK" else close[index]
        broken = (break_price < level.zone_bottom - atr * self.break_tolerance_atr) if support else (break_price > level.zone_top + atr * self.break_tolerance_atr)
        if broken:
            state.update(
                state=(
                    SRInteractionState.SUPPORT_BROKEN.value
                    if support
                    else SRInteractionState.RESISTANCE_BROKEN.value
                ),
                pending_test_index=None,
                broken_index=index,
                broken_zone_low=float(level.zone_bottom),
                broken_zone_high=float(level.zone_top),
            )
            return
        tested = low[index] <= level.zone_top and high[index] >= level.zone_bottom
        if tested:
            if state["pending_test_index"] is None:
                state.update(
                    last_test_index=index, test_count=state["test_count"] + 1,
                    pending_test_index=index, rejection_atr=0.0,
                )
            state["state"] = SRInteractionState.SUPPORT_TESTING.value if support else SRInteractionState.RESISTANCE_TESTING.value
            return
        pending = state["pending_test_index"]
        if pending is None:
            if state["state"] not in {SRInteractionState.SUPPORT_HELD.value, SRInteractionState.RESISTANCE_HELD.value, SRInteractionState.SUPPORT_BROKEN.value, SRInteractionState.RESISTANCE_BROKEN.value}:
                state["state"] = SRInteractionState.APPROACHING_SUPPORT.value if support else SRInteractionState.APPROACHING_RESISTANCE.value
            return
        bars_since = index - pending
        if bars_since > self.hold_confirmation_bars:
            state.update(state=SRInteractionState.APPROACHING_SUPPORT.value if support else SRInteractionState.APPROACHING_RESISTANCE.value, pending_test_index=None)
            return
        rejection = max(0.0, (close[index] - level.zone_top) / atr) if support else max(0.0, (level.zone_bottom - close[index]) / atr)
        state["rejection_atr"] = max(float(state.get("rejection_atr", 0.0)), rejection)
        if self.enable_hold_confirmation and rejection >= self.hold_confirmation_atr:
            state.update(state=SRInteractionState.SUPPORT_HELD.value if support else SRInteractionState.RESISTANCE_HELD.value, held_index=index, pending_test_index=None)

    def _advance_to(self, index: int, open_prices: NDArray, high: NDArray[np.float64], low: NDArray[np.float64], close: NDArray, atr_values: NDArray) -> None:
        if index < self._last_processed_index:
            self._reset_incremental_state()
        for current_index in range(self._last_processed_index + 1, index + 1):
            candidate_index = current_index - self.swing_detector.pivot_right
            if candidate_index >= self.swing_detector.pivot_left:
                if self._is_swing_high(high, candidate_index):
                    level = self._make_confirmed_level(
                        support=False,
                        pivot_index=candidate_index,
                        confirmation_index=current_index,
                        open_prices=open_prices,
                        high=high,
                        low=low,
                        close=close,
                        atr_values=atr_values,
                    )
                    if level is not None:
                        self._append_confirmed_level(self._confirmed_highs, level)
                if self._is_swing_low(low, candidate_index):
                    level = self._make_confirmed_level(
                        support=True,
                        pivot_index=candidate_index,
                        confirmation_index=current_index,
                        open_prices=open_prices,
                        high=high,
                        low=low,
                        close=close,
                        atr_values=atr_values,
                    )
                    if level is not None:
                        self._append_confirmed_level(self._confirmed_lows, level)
            self._expire_levels(current_index)
            current_atr = float(atr_values[current_index]) if current_index < len(atr_values) else np.nan
            for zone in self._find_support_levels(high, low, current_index, current_atr):
                self._update_zone_interaction(zone, current_index, open_prices, high, low, close, current_atr)
            for zone in self._find_resistance_levels(high, low, current_index, current_atr):
                self._update_zone_interaction(zone, current_index, open_prices, high, low, close, current_atr)
        self._last_processed_index = index
    
    def analyze_price_location(
        self,
        index: int,
        open_prices: NDArray,
        high_prices: NDArray,
        low_prices: NDArray,
        close_prices: NDArray,
        atr_values: NDArray,
        direction: str,  # "LONG" or "SHORT"
    ) -> SRContext:
        """
        Analyze price location relative to support/resistance.
        
        Args:
            index: current candle index
            open_prices, high_prices, low_prices, close_prices: OHLC arrays
            atr_values: ATR array
            direction: "LONG" or "SHORT"
            
        Returns:
            SRContext with all structural metrics
        """
        direction = str(direction).upper()
        cache_key = (index, direction)
        input_signature = (float(close_prices[index]), float(atr_values[index]))
        if self._context_input_cache.get(index) != input_signature:
            self._base_context_cache.pop(index, None)
            for key in ((index, "LONG"), (index, "SHORT")):
                self._context_cache.pop(key, None)
            self._context_input_cache[index] = input_signature
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]

        if index < self.swing_detector.pivot_left + self.swing_detector.pivot_right:
            context = self._default_context()
            self._context_cache[cache_key] = context
            return context
        
        current_price = close_prices[index]
        current_atr = atr_values[index]
        
        if not np.isfinite(current_atr) or current_atr <= 0:
            context = self._default_context()
            self._context_cache[cache_key] = context
            return context

        self._advance_to(index, open_prices, high_prices, low_prices, close_prices, atr_values)

        if index not in self._base_context_cache:
            support_levels = self._find_support_levels(high_prices, low_prices, index, current_atr)
            resistance_levels = self._find_resistance_levels(high_prices, low_prices, index, current_atr)
            nearest_support = self._nearest_level(support_levels, current_price, below=True)
            nearest_resistance = self._nearest_level(resistance_levels, current_price, below=False)
            support_dist_price, support_dist_atr = self._calculate_distance(current_price, nearest_support, current_atr)
            resistance_dist_price, resistance_dist_atr = self._calculate_distance(current_price, nearest_resistance, current_atr)
            self._base_context_cache[index] = (
                nearest_support, nearest_resistance,
                support_dist_price, support_dist_atr,
                resistance_dist_price, resistance_dist_atr,
            )
        (
            nearest_support, nearest_resistance,
            support_dist_price, support_dist_atr,
            resistance_dist_price, resistance_dist_atr,
        ) = self._base_context_cache[index]
        
        # Classify location
        location = self._classify_location(
            nearest_support, nearest_resistance, support_dist_atr, resistance_dist_atr
        )
        
        rating = self._rate_location(location, direction)
        
        # Calculate room in direction
        room = self._calculate_room_in_direction(
            nearest_support, nearest_resistance, current_price, direction, current_atr
        )
        support_metrics = self._interaction_metrics(nearest_support, index, True)
        resistance_metrics = self._interaction_metrics(nearest_resistance, index, False)
        if nearest_support is None:
            support_metrics = self._interaction_metrics_for_active_state(index, True, SRInteractionState.SUPPORT_BROKEN.value, current_atr)
        if nearest_resistance is None:
            resistance_metrics = self._interaction_metrics_for_active_state(index, False, SRInteractionState.RESISTANCE_BROKEN.value, current_atr)
        confirmation_rating = self._confirmation_rating(direction, support_metrics["state"], resistance_metrics["state"])
        broken_support = self._latest_broken_zone(True)
        broken_resistance = self._latest_broken_zone(False)
        
        context = SRContext(
            nearest_support_price=nearest_support.price if nearest_support else None,
            nearest_support_bar_index=nearest_support.bar_index if nearest_support else None,
            nearest_support_distance_atr=support_dist_atr,
            nearest_support_distance_price=support_dist_price,
            
            nearest_resistance_price=nearest_resistance.price if nearest_resistance else None,
            nearest_resistance_bar_index=nearest_resistance.bar_index if nearest_resistance else None,
            nearest_resistance_distance_atr=resistance_dist_atr,
            nearest_resistance_distance_price=resistance_dist_price,
            
            price_location=location,
            trade_location_rating=rating,
            
            near_support=np.isfinite(support_dist_atr) and support_dist_atr <= self.near_distance_atr,
            near_resistance=np.isfinite(resistance_dist_atr) and resistance_dist_atr <= self.near_distance_atr,
            
            inside_support_zone=bool(
                nearest_support and
                nearest_support.zone_bottom <= current_price <= nearest_support.zone_top
            ),
            inside_resistance_zone=bool(
                nearest_resistance and
                nearest_resistance.zone_bottom <= current_price <= nearest_resistance.zone_top
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
            support_tested=support_metrics["tested"], resistance_tested=resistance_metrics["tested"],
            support_held=support_metrics["held"], resistance_held=resistance_metrics["held"],
            support_rejection_atr=support_metrics["rejection_atr"], resistance_rejection_atr=resistance_metrics["rejection_atr"],
            support_test_count=support_metrics["test_count"], resistance_test_count=resistance_metrics["test_count"],
            bars_since_support_test=support_metrics["bars_since_test"], bars_since_resistance_test=resistance_metrics["bars_since_test"],
            support_last_test_index=support_metrics["last_test_index"], resistance_last_test_index=resistance_metrics["last_test_index"],
            confirmation_rating=confirmation_rating,
            support_zone_low=nearest_support.zone_bottom if nearest_support else None,
            support_zone_high=nearest_support.zone_top if nearest_support else None,
            resistance_zone_low=nearest_resistance.zone_bottom if nearest_resistance else None,
            resistance_zone_high=nearest_resistance.zone_top if nearest_resistance else None,
            support_last_break_index=broken_support["index"],
            resistance_last_break_index=broken_resistance["index"],
            support_broken_zone_low=broken_support["low"],
            support_broken_zone_high=broken_support["high"],
            resistance_broken_zone_low=broken_resistance["low"],
            resistance_broken_zone_high=broken_resistance["high"],
        )
        self._context_cache[cache_key] = context
        return context

    def _interaction_metrics(self, level: Optional[SRLevel], index: int, support: bool) -> dict:
        default_state = SRInteractionState.NO_SUPPORT_NEARBY.value if support else SRInteractionState.NO_RESISTANCE_NEARBY.value
        if level is None:
            return {"state": default_state, "tested": False, "held": False, "rejection_atr": np.nan, "test_count": 0, "bars_since_test": None, "last_test_index": None}
        state = self._interaction_state.get(self._zone_key(level), {})
        state_value = state.get("state", SRInteractionState.APPROACHING_SUPPORT.value if support else SRInteractionState.APPROACHING_RESISTANCE.value)
        last_test = state.get("last_test_index")
        held_value = SRInteractionState.SUPPORT_HELD.value if support else SRInteractionState.RESISTANCE_HELD.value
        return {"state": state_value, "tested": bool(state.get("test_count", 0)), "held": state_value == held_value, "rejection_atr": state.get("rejection_atr", np.nan), "test_count": int(state.get("test_count", 0)), "bars_since_test": index - last_test if last_test is not None else None, "last_test_index": last_test}

    def _interaction_metrics_for_active_state(self, index: int, support: bool, wanted_state: str, atr: float) -> dict:
        current_levels = self._confirmed_lows if support else self._confirmed_highs
        current_sources = {int(level.bar_index) for level in current_levels}
        matches = [
            state
            for (kind, sources), state in self._interaction_state.items()
            if kind == (
                SRLevelType.SUPPORT.value if support else SRLevelType.RESISTANCE.value
            )
            and state.get("state") == wanted_state
            and any(int(source) in current_sources for source in sources)
        ]
        if not matches:
            return self._interaction_metrics(None, index, support)
        state = max(
            matches,
            key=lambda item: (
                item.get("held_index") or -1,
                item.get("last_test_index") or -1,
            ),
        )
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
        current_levels = self._confirmed_lows if support else self._confirmed_highs
        current_sources = {int(level.bar_index) for level in current_levels}
        broken_state = (
            SRInteractionState.SUPPORT_BROKEN.value
            if support
            else SRInteractionState.RESISTANCE_BROKEN.value
        )
        candidates = []
        for (kind, sources), state in self._interaction_state.items():
            if kind != (
                SRLevelType.SUPPORT.value
                if support
                else SRLevelType.RESISTANCE.value
            ):
                continue
            if state.get("state") != broken_state:
                continue
            if not any(int(source) in current_sources for source in sources):
                continue
            broken_index = state.get("broken_index")
            low = state.get("broken_zone_low")
            high = state.get("broken_zone_high")
            if broken_index is None or low is None or high is None:
                continue
            candidates.append(
                {
                    "index": int(broken_index),
                    "low": float(low),
                    "high": float(high),
                }
            )
        if not candidates:
            return {"index": None, "low": None, "high": None}
        return max(candidates, key=lambda item: item["index"])

    def _confirmation_rating(self, direction: str, support_state: str, resistance_state: str) -> str:
        held = SRInteractionState.SUPPORT_HELD.value if direction == "LONG" else SRInteractionState.RESISTANCE_HELD.value
        broken = SRInteractionState.SUPPORT_BROKEN.value if direction == "LONG" else SRInteractionState.RESISTANCE_BROKEN.value
        relevant = support_state if direction == "LONG" else resistance_state
        if relevant == held:
            return "CONFIRMED_GOOD"
        if relevant == broken:
            return "CONFIRMED_BAD"
        if relevant in {SRInteractionState.SUPPORT_TESTING.value, SRInteractionState.RESISTANCE_TESTING.value}:
            return "UNCONFIRMED"
        return "NEUTRAL"
    
    def _zone_is_broken(self, level: SRLevel) -> bool:
        state = self._interaction_state.get(self._zone_key(level), {})
        return state.get("state") in {
            SRInteractionState.SUPPORT_BROKEN.value,
            SRInteractionState.RESISTANCE_BROKEN.value,
        }

    def _retired_sources(self, level_type: SRLevelType) -> set[int]:
        broken_state = (
            SRInteractionState.SUPPORT_BROKEN.value
            if level_type == SRLevelType.SUPPORT
            else SRInteractionState.RESISTANCE_BROKEN.value
        )
        retired: set[int] = set()
        for (kind, sources), state in self._interaction_state.items():
            if kind == level_type.value and state.get("state") == broken_state:
                retired.update(int(source) for source in sources)
        return retired

    def _all_support_levels(self, atr: float) -> list[SRLevel]:
        return self.zone_merger.merge_levels(self._confirmed_lows, atr)

    def _all_resistance_levels(self, atr: float) -> list[SRLevel]:
        return self.zone_merger.merge_levels(self._confirmed_highs, atr)

    def _find_support_levels(
        self, high: NDArray, low: NDArray, index: int, atr: float
    ) -> list[SRLevel]:
        """Return validated support zones whose source pivots remain active."""
        retired = self._retired_sources(SRLevelType.SUPPORT)
        active = [
            level for level in self._confirmed_lows
            if level.bar_index not in retired
        ]
        return self.zone_merger.merge_levels(active, atr)
    
    def _find_resistance_levels(
        self, high: NDArray, low: NDArray, index: int, atr: float
    ) -> list[SRLevel]:
        """Return validated resistance zones whose source pivots remain active."""
        retired = self._retired_sources(SRLevelType.RESISTANCE)
        active = [
            level for level in self._confirmed_highs
            if level.bar_index not in retired
        ]
        return self.zone_merger.merge_levels(active, atr)
    
    def _nearest_level(
        self, levels: list[SRLevel], price: float, below: bool
    ) -> Optional[SRLevel]:
        """Find nearest support (below) or resistance (above)."""
        if not levels:
            return None
        
        if below:
            # A padded support zone remains valid while price is inside it, even
            # if the raw pivot price itself sits slightly above current price.
            candidates = [l for l in levels if l.zone_bottom <= price]
            return max(candidates, key=lambda x: x.zone_top) if candidates else None
        else:
            # Same principle for resistance: price inside a padded zone should
            # still resolve to that resistance instead of losing structure.
            candidates = [l for l in levels if l.zone_top >= price]
            return min(candidates, key=lambda x: x.zone_bottom) if candidates else None
    
    def _calculate_distance(
        self, price: float, level: Optional[SRLevel], atr: float
    ) -> tuple[float, float]:
        """Calculate distance in price and ATR units."""
        if level is None or atr <= 0:
            return np.nan, np.nan

        if level.zone_bottom <= price <= level.zone_top:
            price_dist = 0.0
        elif price > level.zone_top:
            price_dist = price - level.zone_top
        else:
            price_dist = level.zone_bottom - price
        atr_dist = price_dist / atr
        return price_dist, atr_dist
    
    def _classify_location(
        self,
        support: Optional[SRLevel],
        resistance: Optional[SRLevel],
        support_dist_atr: float,
        resistance_dist_atr: float,
    ) -> LocationClassification:
        """Classify price location."""
        near_support = (
            support is not None and 
            np.isfinite(support_dist_atr) and
            support_dist_atr <= self.near_distance_atr
        )
        near_resistance = (
            resistance is not None and
            np.isfinite(resistance_dist_atr) and
            resistance_dist_atr <= self.near_distance_atr
        )
        
        if near_support:
            return LocationClassification.NEAR_SUPPORT
        elif near_resistance:
            return LocationClassification.NEAR_RESISTANCE
        elif support is not None and resistance is not None:
            return LocationClassification.BETWEEN_LEVELS
        else:
            return LocationClassification.NO_STRUCTURE
    
    def _rate_location(
        self, location: LocationClassification, direction: str
    ) -> TradeLocationRating:
        """Rate whether location is good for the direction."""
        if location == LocationClassification.NO_STRUCTURE:
            return TradeLocationRating.NEUTRAL_LOCATION
        
        if direction == "LONG":
            if location == LocationClassification.NEAR_SUPPORT:
                return TradeLocationRating.GOOD_LOCATION
            elif location == LocationClassification.NEAR_RESISTANCE:
                return TradeLocationRating.BAD_LOCATION
            else:
                return TradeLocationRating.NEUTRAL_LOCATION
        else:  # SHORT
            if location == LocationClassification.NEAR_RESISTANCE:
                return TradeLocationRating.GOOD_LOCATION
            elif location == LocationClassification.NEAR_SUPPORT:
                return TradeLocationRating.BAD_LOCATION
            else:
                return TradeLocationRating.NEUTRAL_LOCATION
    
    def _calculate_room_in_direction(
        self,
        support: Optional[SRLevel],
        resistance: Optional[SRLevel],
        price: float,
        direction: str,
        atr: float,
    ) -> float:
        """Calculate room in trade direction before opposing structure blocks."""
        if atr <= 0:
            return np.nan
        
        if direction == "LONG":
            if resistance is not None:
                room_price = resistance.zone_bottom - price
                return room_price / atr if room_price > 0 else np.nan
        else:  # SHORT
            if support is not None:
                room_price = price - support.zone_top
                return room_price / atr if room_price > 0 else np.nan
        
        return np.nan
    
    def _default_context(self) -> SRContext:
        """Return default context (no structure detected)."""
        return SRContext(
            nearest_support_price=None,
            nearest_support_bar_index=None,
            nearest_support_distance_atr=np.nan,
            nearest_support_distance_price=np.nan,
            nearest_resistance_price=None,
            nearest_resistance_bar_index=None,
            nearest_resistance_distance_atr=np.nan,
            nearest_resistance_distance_price=np.nan,
            price_location=LocationClassification.NO_STRUCTURE,
            trade_location_rating=TradeLocationRating.NEUTRAL_LOCATION,
            near_support=False,
            near_resistance=False,
            inside_support_zone=False,
            inside_resistance_zone=False,
            room_in_direction_atr=np.nan,
            structure_conflict=False,
        )
