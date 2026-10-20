from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.ema100_300_reversal import MODE, reversal_directions
from crypto_strategy_lab.strategy_rule_model import compile_profiles, infer_direction_mode, MARKET_PERMISSIONS


@pytest.mark.parametrize("opens,closes,fast,slow,side", [
    ([10,12,11],[11,11,10],9,12,"SHORT"),
    ([12,10,11],[11,11,12],13,10,"LONG"),
    ([10,12,11],[11,12,10],9,12,None),
    ([10,12,11],[11,11,10],12,9,None),
    ([10,12,11],[11,11,10],9,9,None),
])
def test_pattern_requires_two_consecutive_candles_and_matching_ema_order(opens, closes, fast, slow, side):
    result = reversal_directions(opens, closes, [fast]*3, [slow]*3)
    assert list(result[:2]) == [None,None]
    assert result[-1] == side


def test_strategy_marker_round_trip():
    profiles,_ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    assert infer_direction_mode(profiles) == MODE


def test_missing_next_candle_does_not_enter_at_a_later_open():
    from types import SimpleNamespace
    from crypto_strategy_lab.ema100_300_reversal import Ema100300ReversalMixin
    p = Ema100300ReversalMixin()
    p.signal_strategy_mode = MODE
    p.config = SimpleNamespace(strategy_timeframe_minutes=15)
    p.times = pd.date_range("2026-01-01", periods=2, freq="30min")
    p._should_enter = lambda i: True
    assert p._entry_decision(0) is None


@pytest.mark.parametrize("side,entry,target,slow,passed", [
    ("SHORT",100.,98.,99.,True), ("SHORT",97.,98.,101.,False),
    ("LONG",100.,102.,101.,True), ("LONG",103.,102.,99.,False),
    ("SHORT",100.,98.,101.,False), ("LONG",100.,102.,99.,False),
    ("SHORT",101.,98.,101.,False), ("LONG",101.,102.,101.,False),
    ("SHORT",101.000001,98.,101.,True), ("LONG",100.999999,102.,101.,True),
    ("SHORT",9440.187545,9425.50943469679,9579.288691828522,False),
])
def test_entry_must_be_outside_both_emas_with_profitable_target(side,entry,target,slow,passed):
    from types import SimpleNamespace
    from crypto_strategy_lab.ema100_300_reversal import Ema100300ReversalMixin
    p = Ema100300ReversalMixin()
    p.config = SimpleNamespace(strategy_timeframe_minutes=15)
    p.signal_strategy_mode = MODE
    p.ema100_low_values = np.array([target])
    p.ema300_high_values = np.array([slow])
    p.atr_values = np.array([1.])
    p._effective_trade_direction = lambda i:side
    p._expected_entry_price = lambda i,j,d:entry
    plan=p._sr_stop_plan(0,1)
    assert plan['passed'] == passed
    if passed:
        assert plan['stop_price'] == 2*entry-target
    elif (entry>target if side == "SHORT" else entry<target):
        assert plan['reason'] == "EMA100_300_ENTRY_POSITION_REJECTED"


def test_native_engine_uses_last_closed_low_ema_and_fixed_one_r():
    from crypto_strategy_lab.config import BacktestConfig
    from crypto_strategy_lab.strategy_profiles import StrategyProfile
    from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
    rng = np.random.default_rng(31)
    n = 2400
    close = 100 + 10*np.sin(np.arange(n)/90) + rng.normal(0,.5,n)
    opens = np.r_[close[0],close[:-1]]
    high = np.maximum(opens,close)+.15
    low = np.minimum(opens,close)-.15
    times = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame(dict(timestamp=times,open=opens,high=high,low=low,close=close,volume=np.ones(n)))
    profiles,_ = compile_profiles(direction_mode=MODE, market_permissions=MARKET_PERMISSIONS)
    native = {k:replace(StrategyProfile(**asdict(p)), reward_risk_ratio=3., stop_loss_multiple=2.,
                      trailing_enabled=True, break_even_enabled=True) for k,p in profiles.items()}
    config = BacktestConfig(strategy_profiles=native, use_intrabar_data=False,
                            enable_support_resistance_analysis=False, market_regime_method="ASSET_RETURN",
                            entry_timing_mode="SIGNAL_CLOSE", enable_trade_telemetry=False)
    engine = RuleAwareDataLakeProductionBacktestEngine(frame,config)
    engine.market_regime_values[:] = "SIDEWAYS"
    trades = engine.run()
    assert len(trades)>0
    assert set(trades.side) == {"LONG","SHORT"}
    for row in trades.itertuples():
        signal = pd.Timestamp(row.signal_candle_time)
        entry = pd.Timestamp(row.entry_time)
        assert entry == signal+pd.Timedelta(minutes=15)
        prefix=row.side.lower()
        tp=getattr(row,prefix+'_tp')
        stop=getattr(row,prefix+'_original_sl')
        assert tp == pytest.approx(row.ema100_low)
        assert abs(tp-row.entry_price) == pytest.approx(abs(row.entry_price-stop))
        assert (row.ema300_high>row.ema100_low) == (row.side=='SHORT')
        assert (tp<row.entry_price) == (row.side=='SHORT')
        assert (row.entry_price>max(row.ema100_low,row.ema300_high) if row.side=='SHORT'
                else row.entry_price<min(row.ema100_low,row.ema300_high))
        assert row.ema_reversal_entry_position_rule == "SHORT_ABOVE_BOTH_LONG_BELOW_BOTH_V1"
    # Prefix-only features must agree with full-history decisions.
    prefix = RuleAwareDataLakeProductionBacktestEngine(frame.iloc[:1200],config)
    assert np.allclose(engine.ema100_low_values[:1200], prefix.ema100_low_values,equal_nan=True)
    assert engine.ema100_300_directions[:1200].tolist() == prefix.ema100_300_directions.tolist()
