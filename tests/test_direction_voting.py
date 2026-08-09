import numpy as np
import pandas as pd

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


def test_five_independent_votes_choose_three_to_two_majority():
    engine=BacktestEngine(candles(),voting_config())
    i=100
    engine.plus_di_values[i]=30; engine.minus_di_values[i]=10
    engine.direction_vote_momentum_values[i]=.05
    engine.direction_vote_higher_timeframe_values[i]=-1
    direction,result=engine._direction_vote(i)
    assert direction=="LONG"
    assert (result["long"],result["short"],result["abstain"])==(3,2,0)
    assert result["votes"]=={"di":"LONG","structure":"LONG","momentum":"LONG","volume_pressure":"SHORT","higher_timeframe":"SHORT"}


def test_tied_vote_abstains_from_direction():
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
