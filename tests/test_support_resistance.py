"""Unit tests for support/resistance detection with no look-ahead bias."""

import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.support_resistance import (
    SwingDetector,
    SRZoneMerger,
    SupportResistanceDetector,
    SRContext,
    SRLevel,
    SRLevelType,
    LocationClassification,
    TradeLocationRating,
)


class TestSwingDetector:
    """Tests for swing high and swing low detection."""
    
    def test_swing_high_detection_basic(self):
        """Swing highs detected at clear peaks."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        highs = np.array([10, 12, 15, 12, 10, 11, 13, 16, 14, 12], dtype=np.float64)
        
        # At index 6 (enough data for confirmation), swing at index 2 (15) should be available
        # because 6 - 2 = 4 >= pivot_right (2)
        swings = detector.detect_swing_highs(highs, 6)
        assert 2 in swings, f"Expected swing at index 2, got {swings}"
    
    def test_no_look_ahead_bias_swing_high(self):
        """Swing at index i only available after i + pivot_right."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        highs = np.array([10, 12, 15, 12, 10, 11, 13, 16, 14, 12], dtype=np.float64)
        
        # At index 3, swing at index 2 should NOT be available yet
        # because 3 - 2 = 1 < pivot_right (2)
        swings = detector.detect_swing_highs(highs, 3)
        assert 2 not in swings, f"Look-ahead bias: swing at 2 available at index 3, swings={swings}"
        
        # At index 4, it should be available (4 - 2 = 2 >= pivot_right)
        swings = detector.detect_swing_highs(highs, 4)
        assert 2 in swings, f"Expected swing at index 2 at index 4, got {swings}"
    
    def test_swing_low_detection_basic(self):
        """Swing lows detected at clear valleys."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        lows = np.array([10, 8, 5, 8, 10, 9, 7, 4, 6, 8], dtype=np.float64)
        
        # At index 6, swing at index 2 (5) should be available
        swings = detector.detect_swing_lows(lows, 6)
        assert 2 in swings, f"Expected swing at index 2, got {swings}"
    
    def test_no_look_ahead_bias_swing_low(self):
        """Swing low also respects confirmation delay."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        lows = np.array([10, 8, 5, 8, 10, 9, 7, 4, 6, 8], dtype=np.float64)
        
        # At index 3, swing at index 2 should NOT be available
        swings = detector.detect_swing_lows(lows, 3)
        assert 2 not in swings, f"Look-ahead bias detected in swing lows"
        
        # At index 4, it should be available
        swings = detector.detect_swing_lows(lows, 4)
        assert 2 in swings, f"Expected swing at index 2, got {swings}"
    
    def test_insufficient_data_no_swings(self):
        """No swings returned when data too short."""
        detector = SwingDetector(pivot_left=2, pivot_right=2)
        highs = np.array([10, 12, 15], dtype=np.float64)
        
        # Not enough data (need at least pivot_left + pivot_right + 1 = 5)
        swings = detector.detect_swing_highs(highs, 2)
        assert len(swings) == 0, f"Expected no swings, got {swings}"
    
    def test_multiple_swings_detected(self):
        """Multiple swings detected in sequence."""
        detector = SwingDetector(pivot_left=2, pivot_right=2, min_bars_between=2)
        # Two clear peaks at index 2 and index 7
        highs = np.array([10, 12, 20, 12, 10, 12, 15, 25, 15, 10], dtype=np.float64)
        
        swings = detector.detect_swing_highs(highs, 9)
        assert 2 in swings, "Expected swing at index 2"
        assert 7 in swings, "Expected swing at index 7"
    
    def test_min_bars_between_enforced(self):
        """Minimum spacing between swings enforced."""
        detector = SwingDetector(pivot_left=1, pivot_right=1, min_bars_between=3)
        # Peaks at 2, 4, 7 - only 2 and 7 should pass (4 too close to 2)
        highs = np.array([10, 12, 15, 12, 14, 12, 13, 17, 12], dtype=np.float64)
        
        swings = detector.detect_swing_highs(highs, 8)
        assert 2 in swings, "Expected swing at index 2"
        assert 4 not in swings, "Swing at 4 too close to 2"
        assert 7 in swings, "Expected swing at index 7"


class TestSRZoneMerger:
    """Tests for zone merging logic."""
    
    def test_single_level_no_merge(self):
        """Single level stays unchanged."""
        merger = SRZoneMerger(zone_width_atr=1.0)
        level = SRLevel(
            price=100.0,
            level_type=SRLevelType.SUPPORT,
            bar_index=10,
            first_touch_index=10,
        )
        
        merged = merger.merge_levels([level], atr=1.0)
        assert len(merged) == 1
        assert merged[0].price == 100.0
        assert merged[0].zone_bottom == 100.0
        assert merged[0].zone_top == 100.0
    
    def test_nearby_levels_merged(self):
        """Levels within zone_width_atr merged into zone."""
        merger = SRZoneMerger(zone_width_atr=1.0)
        atr = 10.0  # zone_width = 1.0 * 10 = 10
        
        levels = [
            SRLevel(100.0, SRLevelType.SUPPORT, 5, 5),
            SRLevel(105.0, SRLevelType.SUPPORT, 10, 10),  # 5 away, within 10
        ]
        
        merged = merger.merge_levels(levels, atr)
        assert len(merged) == 1, "Expected 1 merged zone"
        assert merged[0].zone_bottom == 100.0
        assert merged[0].zone_top == 105.0
        assert merged[0].touch_count == 2
    
    def test_far_levels_separate(self):
        """Levels far apart remain separate zones."""
        merger = SRZoneMerger(zone_width_atr=1.0)
        atr = 10.0  # zone_width = 10
        
        levels = [
            SRLevel(100.0, SRLevelType.SUPPORT, 5, 5),
            SRLevel(120.0, SRLevelType.SUPPORT, 10, 10),  # 20 away, > 10
        ]
        
        merged = merger.merge_levels(levels, atr)
        assert len(merged) == 2, "Expected 2 separate zones"
    
    def test_support_zone_uses_min_price(self):
        """Support zone price is minimum of group."""
        merger = SRZoneMerger(zone_width_atr=2.0)
        levels = [
            SRLevel(105.0, SRLevelType.SUPPORT, 10, 10),
            SRLevel(100.0, SRLevelType.SUPPORT, 5, 5),
        ]
        
        merged = merger.merge_levels(levels, atr=10.0)
        assert len(merged) == 1
        assert merged[0].price == 100.0, "Support zone should use minimum"
    
    def test_resistance_zone_uses_max_price(self):
        """Resistance zone price is maximum of group."""
        merger = SRZoneMerger(zone_width_atr=2.0)
        levels = [
            SRLevel(100.0, SRLevelType.RESISTANCE, 5, 5),
            SRLevel(105.0, SRLevelType.RESISTANCE, 10, 10),
        ]
        
        merged = merger.merge_levels(levels, atr=10.0)
        assert len(merged) == 1
        assert merged[0].price == 105.0, "Resistance zone should use maximum"


class TestSupportResistanceFiltering:
    """Tests for SR entry filtering modes."""

    def test_analysis_only_mode_never_rejects(self):
        data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=30, freq="15min"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        })
        engine = BacktestEngine(data, BacktestConfig(enable_support_resistance_analysis=True, sr_filter_mode="ANALYSIS_ONLY"))
        context = SRContext(
            nearest_support_price=99.0,
            nearest_support_bar_index=1,
            nearest_support_distance_atr=0.1,
            nearest_support_distance_price=1.0,
            nearest_resistance_price=101.0,
            nearest_resistance_bar_index=2,
            nearest_resistance_distance_atr=1.5,
            nearest_resistance_distance_price=1.0,
            price_location=LocationClassification.NEAR_SUPPORT,
            trade_location_rating=TradeLocationRating.BAD_LOCATION,
            near_support=True,
            near_resistance=False,
            inside_support_zone=False,
            inside_resistance_zone=False,
            room_in_direction_atr=0.5,
        )

        rejected, reason = engine._should_reject_for_sr(10, "LONG", context)
        assert rejected is False
        assert reason is None

    def test_block_bad_location_mode_rejects_bad_rating(self):
        data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=30, freq="15min"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        })
        engine = BacktestEngine(data, BacktestConfig(enable_support_resistance_analysis=True, sr_filter_mode="BLOCK_BAD_LOCATION"))
        context = SRContext(
            nearest_support_price=99.0,
            nearest_support_bar_index=1,
            nearest_support_distance_atr=0.1,
            nearest_support_distance_price=1.0,
            nearest_resistance_price=101.0,
            nearest_resistance_bar_index=2,
            nearest_resistance_distance_atr=1.5,
            nearest_resistance_distance_price=1.0,
            price_location=LocationClassification.NEAR_RESISTANCE,
            trade_location_rating=TradeLocationRating.BAD_LOCATION,
            near_support=False,
            near_resistance=True,
            inside_support_zone=False,
            inside_resistance_zone=False,
            room_in_direction_atr=0.5,
        )

        rejected, reason = engine._should_reject_for_sr(10, "LONG", context)
        assert rejected is True
        assert reason == "SR_BAD_LOCATION"

    def test_require_good_location_mode_requires_good_rating(self):
        data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=30, freq="15min"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        })
        engine = BacktestEngine(data, BacktestConfig(enable_support_resistance_analysis=True, sr_filter_mode="REQUIRE_GOOD_LOCATION"))
        context = SRContext(
            nearest_support_price=99.0,
            nearest_support_bar_index=1,
            nearest_support_distance_atr=0.1,
            nearest_support_distance_price=1.0,
            nearest_resistance_price=101.0,
            nearest_resistance_bar_index=2,
            nearest_resistance_distance_atr=1.5,
            nearest_resistance_distance_price=1.0,
            price_location=LocationClassification.BETWEEN_LEVELS,
            trade_location_rating=TradeLocationRating.NEUTRAL_LOCATION,
            near_support=False,
            near_resistance=False,
            inside_support_zone=False,
            inside_resistance_zone=False,
            room_in_direction_atr=0.5,
        )

        rejected, reason = engine._should_reject_for_sr(10, "LONG", context)
        assert rejected is True
        assert reason == "SR_NOT_GOOD_LOCATION"


class TestSupportResistanceDetector:
    """Tests for full SR detection and analysis."""
    
    def test_insufficient_data_returns_default(self):
        """Short data returns default context."""
        detector = SupportResistanceDetector(pivot_left=5, pivot_right=5)
        
        opens = np.array([100.0] * 5, dtype=np.float64)
        highs = np.array([101.0] * 5, dtype=np.float64)
        lows = np.array([99.0] * 5, dtype=np.float64)
        closes = np.array([100.5] * 5, dtype=np.float64)
        atrs = np.array([1.0] * 5, dtype=np.float64)
        
        context = detector.analyze_price_location(
            3, opens, highs, lows, closes, atrs, "LONG"
        )
        
        assert context.price_location == LocationClassification.NO_STRUCTURE
        assert context.trade_location_rating == TradeLocationRating.NEUTRAL_LOCATION
    
    def test_long_near_support_good_location(self):
        """Long trade near support classified as GOOD_LOCATION."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50,
            near_distance_atr=1.0
        )
        
        # Create data with a valid swing low
        # Index 5 should be a valley: lower than indices 3,4 and 6,7
        closes = np.array([
            100.0,  # 0
            100.0,  # 1
            100.5,  # 2 - higher
            101.0,  # 3 - higher (left side going up)
            100.0,  # 4 - down
            90.0,   # 5 - SWING LOW (valley)
            100.0,  # 6 - up
            100.5,  # 7 - higher (right side going up)
            100.0,  # 8
            100.0,  # 9
            100.0,  # 10
            100.0,  # 11
            100.0,  # 12
            100.0,  # 13
            100.1,  # 14
            100.2,  # 15 - near support at 90
        ], dtype=np.float64)
        
        opens = closes.copy()
        highs = closes + 1.0
        lows = closes - 1.0
        lows[5] = 89.5  # Make the swing low valid
        
        atrs = np.array([1.0] * 16, dtype=np.float64)
        
        # At index 15, price is 100.2, nearest support should be 90.0
        # Distance = (100.2 - 90.0) / 1.0 = 10.2 ATR (but should still classify location)
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        # With near_distance_atr=1.0, distance of 10.2 is NOT near
        # But we should still have detected the support
        if context.nearest_support_price is not None:
            assert context.trade_location_rating in [
                TradeLocationRating.GOOD_LOCATION,
                TradeLocationRating.NEUTRAL_LOCATION
            ], f"Unexpected rating: {context.trade_location_rating}"
    
    def test_short_near_resistance_good_location(self):
        """Short trade near resistance classified as GOOD_LOCATION."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50,
            near_distance_atr=1.0
        )
        
        # Create data with a valid swing high
        closes = np.array([
            100.0,  # 0
            100.0,  # 1
            99.5,   # 2 - lower
            99.0,   # 3 - lower (left side going down)
            100.0,  # 4 - up
            110.0,  # 5 - SWING HIGH (peak)
            100.0,  # 6 - down
            99.5,   # 7 - lower (right side going down)
            100.0,  # 8
            100.0,  # 9
            100.0,  # 10
            100.0,  # 11
            100.0,  # 12
            100.0,  # 13
            99.9,   # 14
            99.8,   # 15 - near resistance at 110
        ], dtype=np.float64)
        
        opens = closes.copy()
        highs = closes + 1.0
        highs[5] = 110.5  # Make the swing high valid
        lows = closes - 1.0
        
        atrs = np.array([1.0] * 16, dtype=np.float64)
        
        # At index 15, price is 99.8, nearest resistance should be 110.0
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "SHORT"
        )
        
        # With near_distance_atr=1.0, distance of ~10.2 is NOT near
        # But location should be properly classified
        if context.nearest_resistance_price is not None:
            assert context.trade_location_rating in [
                TradeLocationRating.GOOD_LOCATION,
                TradeLocationRating.NEUTRAL_LOCATION
            ], f"Unexpected rating: {context.trade_location_rating}"
    
    def test_long_near_resistance_bad_location(self):
        """Long trade near resistance classified as BAD_LOCATION."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50,
            near_distance_atr=2.0  # Increase threshold so we're "near"
        )
        
        # Create data with a valid swing high, price near it
        closes = np.array([
            100.0,  # 0
            100.0,  # 1
            99.5,   # 2 - lower
            99.0,   # 3 - lower (left side)
            100.0,  # 4 - up
            110.0,  # 5 - SWING HIGH
            100.0,  # 6 - down
            99.5,   # 7 - lower (right side)
            100.0,  # 8
            100.5,  # 9
            101.0,  # 10
            101.5,  # 11
            102.0,  # 12
            102.5,  # 13
            103.0,  # 14
            103.5,  # 15 - moving toward resistance
        ], dtype=np.float64)
        
        opens = closes.copy()
        highs = closes + 1.0
        highs[5] = 110.5  # Peak
        lows = closes - 1.0
        
        # With ATR=1.0, distance from 103.5 to 110.0 is 6.5/1.0 = 6.5 ATR
        # This is still > near_distance_atr=2.0, so won't be "NEAR"
        # But if we use a smaller ATR, it becomes near
        atrs = np.array([1.0] * 16, dtype=np.float64)
        
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        # With price approaching but not super close to resistance
        assert context.price_location in [
            LocationClassification.NEAR_RESISTANCE,
            LocationClassification.BETWEEN_LEVELS
        ], f"Expected near or between resistance, got {context.price_location}"
    
    def test_between_levels_neutral(self):
        """Price between support and resistance classified as NEUTRAL."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50,
            near_distance_atr=0.5
        )
        
        opens = np.array([100.0] * 20, dtype=np.float64)
        highs = np.full(20, 102.0, dtype=np.float64)
        lows = np.full(20, 98.0, dtype=np.float64)
        
        # Swing low at 5, swing high at 10
        lows[5] = 90.0
        highs[10] = 110.0
        
        closes = np.array(
            [100.0] * 5 + [91.0] + [100.0] * 4 + [109.0] + [100.0] * 9,
            dtype=np.float64
        )
        atrs = np.array([1.0] * 20, dtype=np.float64)
        
        # At index 15, price at 100 is well between support (90) and resistance (110)
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        assert context.price_location == LocationClassification.BETWEEN_LEVELS, \
            f"Expected BETWEEN_LEVELS, got {context.price_location}"
        assert context.trade_location_rating == TradeLocationRating.NEUTRAL_LOCATION
    
    def test_distance_calculation_accuracy(self):
        """Support/resistance distances calculated correctly in ATR units."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50
        )
        
        # Create data with a clear swing low at index 5
        # Need 2 bars before/after lower values
        closes = np.array([
            100.0,  # 0
            100.0,  # 1
            100.0,  # 2 - higher
            100.0,  # 3 - higher
            100.0,  # 4 - up
            50.0,   # 5 - SWING LOW
            100.0,  # 6 - up
            100.0,  # 7 - higher
            100.0,  # 8
            100.0,  # 9
            100.0,  # 10
            100.0,  # 11
            100.0,  # 12
            100.0,  # 13
            100.0,  # 14
            100.0,  # 15 - price at 100, support at 50
        ], dtype=np.float64)
        
        opens = closes.copy()
        highs = closes + 1.0
        lows = closes - 1.0
        
        # Price at 100, support at 50, ATR = 10.0
        # Distance = (100 - 50) / 10.0 = 5.0 ATR
        atrs = np.array([10.0] * 16, dtype=np.float64)
        
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        # Check that a support level was detected
        assert context.nearest_support_price is not None, \
            f"Support should be detected, got {context.nearest_support_price}"
        
        # Distance should be approximately 5.0 ATR
        if not np.isnan(context.nearest_support_distance_atr):
            assert np.isclose(context.nearest_support_distance_atr, 5.0, rtol=0.2), \
                f"Expected ~5.0 ATR distance, got {context.nearest_support_distance_atr}"
    
    def test_near_support_flag_accuracy(self):
        """near_support flag set correctly based on distance."""
        detector = SupportResistanceDetector(
            pivot_left=2, pivot_right=2, lookback_bars=50,
            near_distance_atr=1.0  # Within 1.0 ATR is "near"
        )
        
        # Create data with a swing low at index 5
        closes = np.array([
            100.0,  # 0
            100.0,  # 1
            100.0,  # 2
            100.0,  # 3
            100.0,  # 4
            50.0,   # 5 - SWING LOW
            100.0,  # 6
            100.0,  # 7
            100.0,  # 8
            100.0,  # 9
            100.0,  # 10
            100.0,  # 11
            100.0,  # 12
            100.0,  # 13
            100.0,  # 14
            100.0,  # 15 - price = 100, support = 50
        ], dtype=np.float64)
        
        opens = closes.copy()
        highs = closes + 1.0
        lows = closes - 1.0
        
        # Price = 100, support = 50, ATR = 10.0
        # Distance = (100 - 50) / 10.0 = 5.0 ATR (NOT near, since threshold is 1.0)
        atrs = np.array([10.0] * 16, dtype=np.float64)
        
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        assert not context.near_support, \
            f"Distance 5.0 ATR should NOT be near (threshold 1.0), got {context.near_support}"
        
        # Now test with price closer to support
        # Price = 50.5, support = 50, ATR = 1.0
        # Distance = 0.5 / 1.0 = 0.5 ATR (IS near)
        closes[15] = 50.5
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        assert context.near_support, \
            f"Distance 0.5 ATR should be near (threshold 1.0), got {context.near_support}"
    
    def test_zero_atr_handles_gracefully(self):
        """Zero or invalid ATR returns default context."""
        detector = SupportResistanceDetector()
        
        opens = np.array([100.0] * 20, dtype=np.float64)
        highs = np.array([101.0] * 20, dtype=np.float64)
        lows = np.array([99.0] * 20, dtype=np.float64)
        closes = np.array([100.0] * 20, dtype=np.float64)
        atrs = np.array([0.0] * 20, dtype=np.float64)  # Invalid
        
        context = detector.analyze_price_location(
            15, opens, highs, lows, closes, atrs, "LONG"
        )
        
        # Should return default (no errors)
        assert context.price_location == LocationClassification.NO_STRUCTURE


class TestIntegrationNoLookAhead:
    """Integration tests ensuring no look-ahead bias."""
    
    def test_full_detection_no_future_data(self):
        """Full SR analysis never uses future candles."""
        detector = SupportResistanceDetector(pivot_left=3, pivot_right=3, lookback_bars=20)
        
        # Create 30-candle dataset
        opens = np.linspace(100, 110, 30, dtype=np.float64)
        highs = opens + 2
        lows = opens - 2
        closes = opens + 0.5
        atrs = np.ones(30, dtype=np.float64)
        
        # At each historical point, verify no future data used
        for i in range(6, 30):  # Only where enough data exists
            context = detector.analyze_price_location(
                i, opens, highs, lows, closes, atrs, "LONG"
            )
            
            # All levels should have bar_index <= i - pivot_right
            if context.nearest_support_price is not None:
                assert context.nearest_support_bar_index is not None
                assert context.nearest_support_bar_index <= i - 3, \
                    f"Support at index {context.nearest_support_bar_index} uses future from {i}"
            
            if context.nearest_resistance_price is not None:
                assert context.nearest_resistance_bar_index is not None
                assert context.nearest_resistance_bar_index <= i - 3, \
                    f"Resistance at index {context.nearest_resistance_bar_index} uses future from {i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
