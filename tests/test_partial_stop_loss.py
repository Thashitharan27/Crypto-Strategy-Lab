import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, RiskMode, TiePolicy, TrailActivationTrigger, TradeDirectionMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def candles(*bars):
    return pd.DataFrame([
        {
            "timestamp": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
            "open": 100,
            "close": 100,
            "high": high,
            "low": low,
            "volume": 1,
        }
        for i, (high, low) in enumerate(bars)
    ])


def partial_stop_profiles(*, sl1_r, sl1_close_pct, sl2_r, target_r, trailing=False, trailing_distance_r=1.0):
    profile = StrategyProfile(
        enabled=True,
        stop_loss_multiple=1.0,
        reward_risk_ratio=float(target_r),
        partial_stop_enabled=True,
        sl1_r=float(sl1_r),
        sl1_close_pct=float(sl1_close_pct),
        sl2_r=float(sl2_r),
        trailing_enabled=trailing,
        trailing_distance_r=float(trailing_distance_r),
    )
    return {key: profile for key in PROFILE_KEYS}


def run(*bars):
    cfg = BacktestConfig(
        risk_mode=RiskMode.FIXED,
        fixed_r=1,
        atr_period=1,
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        enable_partial_stop_loss=True,
        sl1_r=0.5,
        sl1_close_pct=50,
        sl2_r=8,
        tp_mult=8,
        maker_fee=0,
        taker_fee=0,
        slippage=0,
        tie_policy=TiePolicy.PESSIMISTIC,
        enable_strategy_profiles=True,
        strategy_profiles=partial_stop_profiles(sl1_r=.5, sl1_close_pct=50, sl2_r=8, target_r=8),
    )
    engine = BacktestEngine(candles(*bars), cfg)
    engine.run()
    return engine.completed_pairs[0]


def weighted_price_r(position):
    return position.gross_pnl / (position.risk * position.original_quantity)


def test_both_sl1_then_sl2_and_tp_net_minus_half_r():
    pair = run((100, 100), (100.5, 99.5), (100, 92))
    assert pair.long.sl1_hit and pair.short.sl1_hit
    assert pair.long.final_exit_reason == "SL1_THEN_SL2"
    assert pair.short.final_exit_reason == "SL1_THEN_TP"
    assert weighted_price_r(pair.long) + weighted_price_r(pair.short) == pytest.approx(-0.5)


def test_one_sl1_sl2_and_other_full_tp_net_three_point_seven_five_r():
    pair = run((100, 100), (100, 99.5), (100, 92))
    assert pair.long.sl1_hit and not pair.short.sl1_hit
    assert weighted_price_r(pair.long) + weighted_price_r(pair.short) == pytest.approx(3.75)


def test_partial_stop_loss_requires_ordered_levels():
    with pytest.raises(ValueError, match="SL2_R"):
        BacktestConfig(enable_partial_stop_loss=True, sl1_r=8, sl2_r=8)


def test_partial_stop_reporting_uses_weighted_stop_not_ignored_core_stop():
    cfg = BacktestConfig(
        risk_mode=RiskMode.FIXED,
        fixed_r=1,
        atr_period=1,
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        enable_partial_stop_loss=True,
        sl_mult=10,
        sl1_r=2,
        sl1_close_pct=75,
        sl2_r=10,
        tp_mult=10,
        maker_fee=0,
        taker_fee=0,
        slippage=0,
        enable_strategy_profiles=True,
        strategy_profiles=partial_stop_profiles(sl1_r=2, sl1_close_pct=75, sl2_r=10, target_r=10),
    )
    results = BacktestEngine(candles((100, 100), (110, 100)), cfg).run()
    assert results.iloc[0]["expected_gross_winning_pair_pnl"] > 0
    assert results.iloc[0]["fees_as_percentage_of_expected_winning_profit"] == 0


def test_trailing_can_activate_after_sl1_and_keeps_sl2_as_final_boundary():
    cfg = BacktestConfig(
        risk_mode=RiskMode.FIXED,
        fixed_r=10,
        atr_period=1,
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        trade_direction=TradeDirectionMode.LONG_ONLY,
        enable_partial_stop_loss=True,
        sl1_r=.5,
        sl1_close_pct=50,
        sl2_r=2,
        tp_mult=3,
        enable_trailing_profit=True,
        trail_activation_trigger=TrailActivationTrigger.AFTER_SL1,
        trail_distance_r=.5,
        maker_fee=0,
        taker_fee=0,
        slippage=0,
        enable_strategy_profiles=True,
        strategy_profiles=partial_stop_profiles(sl1_r=.5, sl1_close_pct=50, sl2_r=2, target_r=3, trailing=True, trailing_distance_r=.5),
    )
    engine = BacktestEngine(candles((100, 100), (100, 94), (96, 89)), cfg)
    row = engine.run().iloc[0]
    assert row.long_sl1_hit
    assert row.long_trailing_activated
    assert row.long_exit_reason == "TRAILING_STOP"
    assert row.long_exit_price > row.long_sl2_price
