import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, RiskMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.config_logic import build_backtest_config


def candles(count=120):
    close=np.linspace(100,160,count)
    return pd.DataFrame({
        "timestamp":pd.date_range("2024-01-01",periods=count,freq="15min",tz="UTC"),
        "open":close+1,
        "high":close+2,
        "low":close-2,
        "close":close,
        "volume":np.ones(count),
    })


def voting_config(**overrides):
    values=dict(use_intrabar_data=False,risk_mode=RiskMode.FIXED,fixed_r=2,
        enable_di_direction_sizing=True,enable_direction_voting=True,
        direction_vote_minimum_votes=2,di_direction_long_minimum_spread=0,
        di_direction_short_minimum_spread=0)
    values.update(overrides)
    return BacktestConfig(**values)


def test_five_independent_votes_choose_three_to_two_majority(monkeypatch):
    monkeypatch.setattr(BacktestEngine,"_higher_timeframe_trend_array",lambda self: np.full(len(self.data),np.nan))
    engine=BacktestEngine(candles(),voting_config())
    i=100
    engine._market_structure_snapshot=lambda _: {"market_structure_direction":"LONG"}
    engine.plus_di_values[i]=30; engine.minus_di_values[i]=10
    engine.direction_vote_momentum_values[i]=.05
    engine.direction_vote_higher_timeframe_values[i]=-1
    direction,result=engine._direction_vote(i)
    assert direction=="LONG"
    assert (result["long"],result["short"],result["abstain"])==(3,2,0)
    assert result["votes"]=={"di":"LONG","structure":"LONG","momentum":"LONG","volume_pressure":"SHORT","higher_timeframe":"SHORT"}


def test_confirmed_swing_structure_is_causal_and_exports_strength_telemetry():
    engine=BacktestEngine(candles(40),voting_config(
        direction_vote_use_di=False,direction_vote_use_structure=True,
        direction_vote_use_momentum=False,direction_vote_use_volume_pressure=False,
        direction_vote_use_higher_timeframe=False,direction_vote_minimum_votes=1,
    ))
    engine.high[:]=100; engine.low[:]=95; engine.close[:]=100
    engine.high[5]=110; engine.high[11]=115
    engine.low[7]=85; engine.low[13]=90
    engine.close[15]=116

    before_confirmation=engine._market_structure_snapshot(14)
    confirmed=engine._market_structure_snapshot(15)

    assert before_confirmation["market_structure_direction"]=="ABSTAIN"
    assert before_confirmation["market_structure_reason"]=="INSUFFICIENT_CONFIRMED_SWINGS"
    assert confirmed["market_structure_direction"]=="LONG"
    assert confirmed["market_structure_reason"]=="HIGHER_HIGH_AND_HIGHER_LOW"
    assert confirmed["market_structure_latest_swing_high"]==115
    assert confirmed["market_structure_latest_swing_low"]==90
    assert confirmed["market_structure_breakout_confirmed_by_close"] is True
    assert "market_structure_minimum_displacement_atr" in confirmed


def test_skipped_signal_records_specific_market_structure_telemetry():
    engine=BacktestEngine(candles(40),voting_config(
        direction_vote_use_di=False,direction_vote_use_structure=True,
        direction_vote_use_momentum=False,direction_vote_use_volume_pressure=False,
        direction_vote_use_higher_timeframe=False,direction_vote_minimum_votes=1,
    ))
    engine._record_skipped_signal(5,"test skip")
    row=engine.skipped_signals[-1]
    assert row["market_structure_direction"]=="ABSTAIN"
    assert row["market_structure_reason"]=="INSUFFICIENT_CONFIRMED_SWINGS"


def test_tied_vote_abstains_from_direction(monkeypatch):
    monkeypatch.setattr(BacktestEngine,"_higher_timeframe_trend_array",lambda self: np.full(len(self.data),np.nan))
    engine=BacktestEngine(candles(),voting_config(direction_vote_use_structure=False))
    i=100
    engine.plus_di_values[i]=30; engine.minus_di_values[i]=10
    engine.direction_vote_momentum_values[i]=.05
    engine.direction_vote_higher_timeframe_values[i]=-1
    direction,result=engine._direction_vote(i)
    assert direction is None
    assert (result["long"],result["short"])==(2,2)


def test_gui_config_round_trips_direction_vote_settings():
    cfg=build_backtest_config({"enable_di_direction_sizing":True,"enable_direction_voting":True,
        "direction_vote_structure_lookback":32,"direction_vote_momentum_lookback_hours":12,
        "direction_vote_volume_threshold":.2,"direction_vote_higher_timeframe_hours":6,
        "direction_vote_higher_timeframe_sma_period":30,"direction_vote_minimum_votes":3},require_paths=False)
    assert cfg.enable_direction_voting
    assert cfg.direction_vote_structure_lookback==32
    assert cfg.direction_vote_momentum_lookback_hours==12
    assert cfg.direction_vote_volume_threshold==.2
    assert cfg.direction_vote_higher_timeframe_hours==6
    assert cfg.direction_vote_higher_timeframe_sma_period==30
    assert cfg.direction_vote_minimum_votes==3


def test_direction_voting_rejects_more_required_votes_than_enabled_voters():
    with pytest.raises(ValueError, match="cannot exceed enabled voters"):
        voting_config(
            direction_vote_use_di=False,
            direction_vote_use_structure=True,
            direction_vote_use_momentum=False,
            direction_vote_use_volume_pressure=False,
            direction_vote_use_higher_timeframe=False,
            direction_vote_minimum_votes=2,
        ).validate(require_paths=False)
