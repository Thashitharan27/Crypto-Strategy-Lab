# Support/Resistance Analysis - Comprehensive Implementation Guide

## Overview
This document outlines the complete implementation of support/resistance (SR) analysis for the Crypto Strategy Lab. The feature will:
- **NOT** modify existing backtest results (analysis_only mode by default)
- **ADD** structural metrics to every entry candidate
- **PROVIDE** detailed reports on location-based performance
- **INTEGRATE** with existing market regime analysis
- **AVOID** all look-ahead bias

---

## Architecture

### Current Data Flow (Reference)
```
CSV Data
  ↓
Calculate: ATR, ADX, BB, RSI, DI
  ↓
Per-Candle Loop (i = 0 to len(data)):
  1. _selected_direction(i) → LONG/SHORT (via DI/voting)
  2. _entry_decision(i) → timing check
  3. _entry_filter_result(i) → 15+ validation checks
  4. _open_pair(i) → create Position(s)
  5. Telemetry capture
  6. Exit detection
  7. Collect closed trades
  ↓
Post-Backtest Reports:
  - trade_list.csv
  - lifecycle_analysis.csv
  - summary statistics
```

### New Data Flow with SR
```
CSV Data
  ↓
Calculate: ATR, ADX, BB, RSI, DI + SWING DETECTION
  ↓
Per-Candle Loop:
  1. _selected_direction(i) → LONG/SHORT
  2. _detect_support_resistance(i, direction) ← NEW
     ├─ Find nearest support/resistance
     ├─ Calculate distance in ATR
     ├─ Classify location type
     └─ Return SR context dict
  3. _entry_filter_result(i) → existing checks + optional SR filter
  4. _open_pair(i) → store SR fields in Position
  5. Telemetry capture
  6. Exit detection
  7. Collect closed trades
  ↓
Post-Backtest Reports:
  - trade_list.csv (+ SR columns)
  - lifecycle_analysis.csv (+ SR columns)
  - support_resistance_analysis.csv (NEW)
  - support_resistance_regime_analysis.csv (NEW)
  - support_resistance_distance_buckets.csv (NEW)
  - summary with SR metrics
```

---

## Phase 1: Support/Resistance Calculation Module

### 1.1 Create `crypto_strategy_lab/support_resistance.py`

```python
"""Support and resistance level detection with ATR-based zones."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence
import numpy as np
from numpy.typing import NDArray
import pandas as pd


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


@dataclass
class SRLevel:
    """A single support or resistance level."""
    price: float
    level_type: SRLevelType
    bar_index: int  # where it was confirmed
    first_touch_index: int  # earliest touch
    touch_count: int = 1
    confirmed_at_index: int = field(default=None)  # after pivot_right delay
    zone_bottom: float = field(default=None)
    zone_top: float = field(default=None)
    
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
    
    room_in_direction_atr: float  # ATR distance to opposing structure before trade invalidation


class SwingDetector:
    """Detects swing highs and swing lows."""
    
    def __init__(
        self,
        pivot_left: int = 5,
        pivot_right: int = 5,
        min_bars_between: int = 1
    ):
        """
        Args:
            pivot_left: candles to left of candidate peak/valley
            pivot_right: candles to right of candidate peak/valley
            min_bars_between: minimum bars between adjacent swings
        """
        self.pivot_left = pivot_left
        self.pivot_right = pivot_right
        self.min_bars_between = min_bars_between
        
    def detect_swing_highs(
        self, high: NDArray[np.float64], index: int
    ) -> list[int]:
        """
        Detect swing highs available at candle index.
        
        A swing high at bar i is only available from bar i + pivot_right onward.
        This prevents look-ahead bias.
        
        Args:
            high: numpy array of high prices
            index: current candle index
            
        Returns:
            List of bar indices where swing highs were confirmed
        """
        swings = []
        # Scan from 0 to current - pivot_right (cutoff for confirmation)
        cutoff = index - self.pivot_right
        if cutoff < self.pivot_left:
            return swings
            
        for i in range(self.pivot_left, cutoff + 1):
            # Check if high[i] is highest within pivot_left to pivot_right
            left_max = np.max(high[max(0, i - self.pivot_left):i])
            right_max = np.max(high[i + 1:min(len(high), i + self.pivot_right + 1)])
            
            if high[i] >= left_max and high[i] >= right_max:
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
        """
        swings = []
        cutoff = index - self.pivot_right
        if cutoff < self.pivot_left:
            return swings
            
        for i in range(self.pivot_left, cutoff + 1):
            left_min = np.min(low[max(0, i - self.pivot_left):i])
            right_min = np.min(low[i + 1:min(len(low), i + self.pivot_right + 1)])
            
            if low[i] <= left_min and low[i] <= right_min:
                if not swings or (i - swings[-1] >= self.min_bars_between):
                    swings.append(i)
        
        return swings


class SRZoneMerger:
    """Merges nearby SR levels into zones."""
    
    def __init__(self, zone_width_atr: float = 0.5):
        """
        Args:
            zone_width_atr: merge levels within this many ATRs
        """
        self.zone_width_atr = zone_width_atr
    
    def merge_levels(
        self, levels: list[SRLevel], atr: float
    ) -> list[SRLevel]:
        """
        Merge levels that are close together into zones.
        
        Args:
            levels: list of SRLevel objects
            atr: current ATR value for distance calculation
            
        Returns:
            List of merged SRLevel objects with zone_bottom/zone_top set
        """
        if not levels:
            return []
        
        # Sort by price
        sorted_levels = sorted(levels, key=lambda x: x.price)
        merged = []
        current_zone = [sorted_levels[0]]
        
        merge_distance = self.zone_width_atr * atr
        
        for level in sorted_levels[1:]:
            # If within merge distance, add to current zone
            if abs(level.price - current_zone[-1].price) <= merge_distance:
                current_zone.append(level)
            else:
                # Finalize current zone and start new one
                merged.append(self._finalize_zone(current_zone))
                current_zone = [level]
        
        # Finalize last zone
        merged.append(self._finalize_zone(current_zone))
        return merged
    
    def _finalize_zone(self, zone_levels: list[SRLevel]) -> SRLevel:
        """Create a zone from multiple levels."""
        prices = [l.price for l in zone_levels]
        level_type = zone_levels[0].level_type
        
        # Use extreme of zone as price
        if level_type == SRLevelType.SUPPORT:
            zone_price = min(prices)  # lowest point
        else:
            zone_price = max(prices)  # highest point
        
        # Combine metadata
        result = SRLevel(
            price=zone_price,
            level_type=level_type,
            bar_index=max(l.bar_index for l in zone_levels),
            first_touch_index=min(l.first_touch_index for l in zone_levels),
            touch_count=sum(l.touch_count for l in zone_levels),
        )
        result.zone_bottom = min(prices)
        result.zone_top = max(prices)
        return result


class SupportResistanceDetector:
    """Detects and manages support/resistance levels."""
    
    def __init__(
        self,
        pivot_left: int = 5,
        pivot_right: int = 5,
        lookback_bars: int = 200,
        zone_width_atr: float = 0.5,
        near_distance_atr: float = 0.75,
    ):
        """
        Args:
            pivot_left: bars to left for swing detection
            pivot_right: bars to right for swing detection (delays level availability)
            lookback_bars: how many historical bars to scan for levels
            zone_width_atr: merge levels within this ATR distance
            near_distance_atr: distance to be considered "near" a level
        """
        self.swing_detector = SwingDetector(
            pivot_left=pivot_left, pivot_right=pivot_right
        )
        self.zone_merger = SRZoneMerger(zone_width_atr=zone_width_atr)
        self.lookback_bars = lookback_bars
        self.zone_width_atr = zone_width_atr
        self.near_distance_atr = near_distance_atr
    
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
        if index < self.swing_detector.pivot_left + self.swing_detector.pivot_right:
            # Not enough data
            return self._default_context()
        
        current_price = close_prices[index]
        current_atr = atr_values[index]
        
        # Find support/resistance levels
        support_levels = self._find_support_levels(
            high_prices, low_prices, index, current_atr
        )
        resistance_levels = self._find_resistance_levels(
            high_prices, low_prices, index, current_atr
        )
        
        # Find nearest levels
        nearest_support = self._nearest_level(
            support_levels, current_price, below=True
        )
        nearest_resistance = self._nearest_level(
            resistance_levels, current_price, below=False
        )
        
        # Calculate distances
        support_dist_price, support_dist_atr = self._calculate_distance(
            current_price, nearest_support, current_atr
        )
        resistance_dist_price, resistance_dist_atr = self._calculate_distance(
            current_price, nearest_resistance, current_atr
        )
        
        # Classify location
        location = self._classify_location(
            nearest_support, nearest_resistance, support_dist_atr, resistance_dist_atr
        )
        
        rating = self._rate_location(location, direction)
        
        # Calculate room in direction
        room = self._calculate_room_in_direction(
            nearest_support, nearest_resistance, current_price, direction, current_atr
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
            
            price_location=location,
            trade_location_rating=rating,
            
            near_support=support_dist_atr <= self.near_distance_atr,
            near_resistance=resistance_dist_atr <= self.near_distance_atr,
            
            inside_support_zone=(
                nearest_support and
                nearest_support.zone_bottom <= current_price <= nearest_support.zone_top
            ),
            inside_resistance_zone=(
                nearest_resistance and
                nearest_resistance.zone_bottom <= current_price <= nearest_resistance.zone_top
            ),
            
            room_in_direction_atr=room,
        )
    
    def _find_support_levels(
        self, high: NDArray, low: NDArray, index: int, atr: float
    ) -> list[SRLevel]:
        """Find all support levels visible at index."""
        start = max(0, index - self.lookback_bars)
        swing_indices = self.swing_detector.detect_swing_lows(
            low[start:index + 1], index - start
        )
        
        # Convert back to absolute indices
        swing_indices = [idx + start for idx in swing_indices]
        
        levels = [
            SRLevel(
                price=low[i],
                level_type=SRLevelType.SUPPORT,
                bar_index=i,
                first_touch_index=i,
            )
            for i in swing_indices
        ]
        
        # Merge into zones
        return self.zone_merger.merge_levels(levels, atr)
    
    def _find_resistance_levels(
        self, high: NDArray, low: NDArray, index: int, atr: float
    ) -> list[SRLevel]:
        """Find all resistance levels visible at index."""
        start = max(0, index - self.lookback_bars)
        swing_indices = self.swing_detector.detect_swing_highs(
            high[start:index + 1], index - start
        )
        
        swing_indices = [idx + start for idx in swing_indices]
        
        levels = [
            SRLevel(
                price=high[i],
                level_type=SRLevelType.RESISTANCE,
                bar_index=i,
                first_touch_index=i,
            )
            for i in swing_indices
        ]
        
        return self.zone_merger.merge_levels(levels, atr)
    
    def _nearest_level(
        self, levels: list[SRLevel], price: float, below: bool
    ) -> Optional[SRLevel]:
        """Find nearest support (below) or resistance (above)."""
        if not levels:
            return None
        
        if below:
            candidates = [l for l in levels if l.price <= price]
            return max(candidates, key=lambda x: x.price) if candidates else None
        else:
            candidates = [l for l in levels if l.price >= price]
            return min(candidates, key=lambda x: x.price) if candidates else None
    
    def _calculate_distance(
        self, price: float, level: Optional[SRLevel], atr: float
    ) -> tuple[float, float]:
        """Calculate distance in price and ATR units."""
        if level is None:
            return np.nan, np.nan
        
        price_dist = abs(price - level.price)
        atr_dist = price_dist / atr if atr > 0 else np.nan
        return price_dist, atr_dist
    
    def _classify_location(
        self,
        support: Optional[SRLevel],
        resistance: Optional[SRLevel],
        support_dist_atr: float,
        resistance_dist_atr: float,
    ) -> LocationClassification:
        """Classify price location."""
        near_support = support is not None and support_dist_atr <= self.near_distance_atr
        near_resistance = resistance is not None and resistance_dist_atr <= self.near_distance_atr
        
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
        if direction == "LONG":
            if resistance is not None:
                room_price = resistance.zone_bottom - price
                return room_price / atr if atr > 0 else np.nan
        else:  # SHORT
            if support is not None:
                room_price = price - support.zone_top
                return room_price / atr if atr > 0 else np.nan
        
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
        )
```

### 1.2 Modify `crypto_strategy_lab/config.py`

Add new fields to `BacktestConfig` dataclass:

```python
# Add to BacktestConfig class:

# Support/Resistance Analysis
enable_support_resistance_analysis: bool = False
sr_pivot_left: int = 5
sr_pivot_right: int = 5
sr_lookback_bars: int = 200
sr_zone_width_atr: float = 0.5
sr_near_distance_atr: float = 0.75
sr_filter_mode: str = "ANALYSIS_ONLY"  # ANALYSIS_ONLY | BLOCK_BAD_LOCATION | REQUIRE_GOOD_LOCATION
```

### 1.3 Modify `crypto_strategy_lab/trade.py`

Add fields to `Position` dataclass:

```python
# Add to Position class:

sr_nearest_support: Optional[float] = None
sr_nearest_resistance: Optional[float] = None
sr_support_distance_atr: float = np.nan
sr_resistance_distance_atr: float = np.nan
sr_support_distance_price: float = np.nan
sr_resistance_distance_price: float = np.nan
sr_near_support: bool = False
sr_near_resistance: bool = False
sr_inside_support_zone: bool = False
sr_inside_resistance_zone: bool = False
sr_location: str = "NO_STRUCTURE"  # NEAR_SUPPORT | NEAR_RESISTANCE | BETWEEN_LEVELS | NO_STRUCTURE
sr_trade_location_rating: str = "NEUTRAL"  # GOOD | NEUTRAL | BAD
sr_room_in_direction_atr: float = np.nan
```

### 1.4 Modify `crypto_strategy_lab/engine.py`

Add support/resistance detection:

```python
# In BacktestEngine class __init__, after self.adx, add:

from crypto_strategy_lab.support_resistance import SupportResistanceDetector

self.sr_detector = SupportResistanceDetector(
    pivot_left=config.sr_pivot_left,
    pivot_right=config.sr_pivot_right,
    lookback_bars=config.sr_lookback_bars,
    zone_width_atr=config.sr_zone_width_atr,
    near_distance_atr=config.sr_near_distance_atr,
) if config.enable_support_resistance_analysis else None

# Add method:

def _analyze_support_resistance(self, i: int, direction: str):
    """Analyze price location relative to support/resistance."""
    if self.sr_detector is None or self.sr_detector is None:
        return None
    
    try:
        return self.sr_detector.analyze_price_location(
            i,
            self.data["o"],
            self.data["h"],
            self.data["l"],
            self.data["c"],
            self.atr,
            direction,
        )
    except Exception as e:
        self.log(f"SR analysis failed at {i}: {e}")
        return None

# Modify _open_pair() to capture SR data:

def _open_pair(self, ind_i, reason_entry, reason_reject):
    # ... existing code ...
    
    if self.config.enable_support_resistance_analysis:
        sr_context = self._analyze_support_resistance(ind_i, di_direction)
        if sr_context:
            long_pos.sr_nearest_support = sr_context.nearest_support_price
            long_pos.sr_nearest_resistance = sr_context.nearest_resistance_price
            # ... populate other SR fields ...
            
            short_pos.sr_nearest_support = sr_context.nearest_support_price
            short_pos.sr_nearest_resistance = sr_context.nearest_resistance_price
            # ... populate other SR fields ...
```

---

## Phase 2: Telemetry & Data Fields

### 2.1 Modify `crypto_strategy_lab/output_manager.py`

Add SR columns to results frame:

```python
# In engine.py results_frame() method, add SR columns to output dataframe:

sr_columns = {
    "sr_nearest_support": [],
    "sr_nearest_resistance": [],
    "sr_support_distance_atr": [],
    "sr_resistance_distance_atr": [],
    "sr_location": [],
    "sr_trade_location_rating": [],
    "sr_room_in_direction_atr": [],
}

# Populate from Position objects during frame construction
```

---

## Phase 3: Analysis Reports

### 3.1 Create SR Analysis Reports

Add to `output_manager.py`:

```python
def create_sr_analysis_report(self, trades_df):
    """
    Generate support_resistance_analysis.csv
    
    Rows: Location × Direction combinations
    Columns: Trade count, Wins, Losses, Win Rate, Avg R, Avg PnL, Holding Time
    """
    pass

def create_sr_regime_analysis_report(self, trades_df):
    """
    Generate support_resistance_regime_analysis.csv
    
    Cross-tab: Market Regime × Direction × Location
    """
    pass

def create_sr_distance_buckets_report(self, trades_df):
    """
    Generate support_resistance_distance_buckets.csv
    
    Buckets: 0-0.25 ATR, 0.25-0.50, 0.50-0.75, etc.
    Rows: Support distance × Resistance distance
    """
    pass
```

---

## Phase 4: Config Integration

Update GUI config logic in `crypto_strategy_lab/gui/config_logic.py`:

```python
# Add to DEFAULT_GUI_CONFIG:
"enable_support_resistance_analysis": False,
"sr_pivot_left": 5,
"sr_pivot_right": 5,
"sr_lookback_bars": 200,
"sr_zone_width_atr": 0.5,
"sr_near_distance_atr": 0.75,
"sr_filter_mode": "ANALYSIS_ONLY",

# Add validation checks:
if values.get("enable_support_resistance_analysis") and not values.get("sr_pivot_right"):
    errors.append("Support/resistance pivot_right must be positive.")
```

---

## Phase 5: GUI Controls

Add to main_window.py after Direction Voting section:

```python
# New section: Price Structure / Support Resistance

self.enable_sr = QCheckBox("Enable Support/Resistance Analysis")
self.sr_pivot_left = self._spin(5, 1, 50, 0)
self.sr_pivot_right = self._spin(5, 1, 50, 0)
self.sr_lookback = self._spin(200, 20, 1000, 0)
self.sr_zone_width = self._spin(0.5, 0.01, 5, 2)
self.sr_near_distance = self._spin(0.75, 0.01, 5, 2)
self.sr_filter_mode = QComboBox()
self.sr_filter_mode.addItems([
    "Analysis Only (no trade changes)",
    "Block Bad Locations",
    "Require Good Locations"
])

# Add explanatory text:
sr_info = QLabel(
    "DI continues to select Long/Short. "
    "Support/Resistance evaluates whether the entry location is structurally favorable."
)
sr_info.setWordWrap(True)
```

---

## Phase 6: Entry Filtering (Optional)

Add to engine.py:

```python
def _should_reject_for_sr(self, i, direction, sr_context):
    """Optional SR-based entry filtering."""
    if self.config.sr_filter_mode == "ANALYSIS_ONLY":
        return None  # Never block
    
    if sr_context is None:
        return None
    
    if self.config.sr_filter_mode == "BLOCK_BAD_LOCATION":
        if sr_context.trade_location_rating == TradeLocationRating.BAD_LOCATION:
            reason = f"SR_BAD_LOCATION_{direction}"
            return (False, reason)
    
    elif self.config.sr_filter_mode == "REQUIRE_GOOD_LOCATION":
        if sr_context.trade_location_rating != TradeLocationRating.GOOD_LOCATION:
            reason = f"SR_NOT_GOOD_LOCATION_{direction}"
            return (False, reason)
    
    return None

# Integrate into _entry_filter_result() after other checks
```

---

## Phase 7: Testing

Create `tests/test_support_resistance.py`:

```python
"""Test support/resistance detection for correctness and no look-ahead bias."""

import numpy as np
import pytest
from crypto_strategy_lab.support_resistance import (
    SwingDetector,
    SRZoneMerger,
    SupportResistanceDetector,
    LocationClassification,
    TradeLocationRating,
)


class TestSwingDetector:
    def test_swing_high_detection(self):
        """Swing highs detected correctly."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        highs = np.array([10, 12, 15, 12, 10, 11, 13, 16, 14, 12])
        
        # At index 6, swing high at index 2 (value 15) should be available
        # because 6 - 2 = 4 >= pivot_right (2)
        swings = detector.detect_swing_highs(highs, 6)
        assert 2 in swings
    
    def test_no_look_ahead_bias(self):
        """Swing at index i only available after i + pivot_right."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        highs = np.array([10, 12, 15, 12, 10, 11, 13, 16, 14, 12])
        
        # At index 3, swing at index 2 should NOT be available yet
        # because 3 - 2 = 1 < pivot_right (2)
        swings = detector.detect_swing_highs(highs, 3)
        assert 2 not in swings
        
        # But at index 4, it should be available (4 - 2 = 2 >= pivot_right)
        swings = detector.detect_swing_highs(highs, 4)
        assert 2 in swings
    
    def test_zone_merging(self):
        """Nearby levels merged into zones."""
        merger = SRZoneMerger(zone_width_atr=1.0)
        # ... test zone merging logic ...
    
    def test_good_location_for_long(self):
        """Long near support = GOOD_LOCATION."""
        detector = SupportResistanceDetector()
        context = detector.analyze_price_location(
            50,
            opens, highs, lows, closes, atrs,
            direction="LONG"
        )
        # Should classify as GOOD if near support
        # ...
```

---

## Integration Checklist

### Before Phase 1 Complete
- [ ] `support_resistance.py` created with SwingDetector, SRZoneMerger, SupportResistanceDetector
- [ ] No look-ahead bias tests passing
- [ ] Swing detection tested with historical data

### Before Phase 2 Complete
- [ ] `config.py` updated with SR fields
- [ ] `trade.py` updated with SR columns
- [ ] `engine.py` integrated with SR detector initialization
- [ ] SR data captured in `_open_pair()`

### Before Phase 3 Complete
- [ ] Trade list exports include SR columns
- [ ] SR analysis CSV report structure defined
- [ ] Regime analysis cross-tab implemented

### Before Phase 4 Complete
- [ ] GUI controls added
- [ ] Config validation updated
- [ ] Backward compatibility verified (disabled=false → same results)

### Before Phase 6 Complete
- [ ] Entry filtering modes implemented
- [ ] Block/require logic tested

### Before Phase 7 Complete
- [ ] Regression tests: disabled SR matches baseline
- [ ] Unit tests for all SR components
- [ ] Integration tests: full backtest with SR enabled

---

## Key Design Principles

1. **Analysis First**: Default mode doesn't change trades
2. **No Look-Ahead**: Pivot confirmation delay enforced
3. **Backward Compatible**: Disabled SR = identical results
4. **Reusable Data**: SR context usable by future features
5. **Measurable**: Detailed reports show location-based performance
6. **Extensible**: Easy to add Fibonacci, trendlines, etc. in v2

---

## Success Criteria

The implementation is complete when:
- ✓ Same backtest with `sr_filter_mode = ANALYSIS_ONLY` produces identical trades
- ✓ SR metrics are populated in trade_list.csv
- ✓ Reports show Longs near support outperform Longs near resistance
- ✓ No look-ahead bias in swing detection (tests pass)
- ✓ Existing configs with `enable_sr = false` run unchanged

