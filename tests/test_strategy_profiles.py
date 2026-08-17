import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import StrategyProfile, default_profiles, normalize_profiles, profiles_to_dict


def rising_candles(count=160):
    timestamps=pd.date_range("2024-01-01",periods=count,freq="60min",tz="UTC")
    close=[100+i*.5 for i in range(count)]
    return pd.DataFrame({"timestamp":timestamps,"open":close,"high":[v+1 for v in close],"low":[v-1 for v in close],"close":close,"volume":1})


def profile_config(**changes):
    profiles=default_profiles()
    profiles["bull_long"]=StrategyProfile(enabled=True,reward_risk_ratio=2.5,risk_multiplier=1.5,di_spread_enabled=True,di_spread_minimum=0,di_spread_maximum=1000)
    base=dict(risk_mode=RiskMode.FIXED,fixed_r=2,entry_mode=EntryMode.WAIT_UNTIL_CLOSED,strategy_timeframe_minutes=60,telemetry_interval_minutes=60,initial_equity=1000,risk_per_leg=.01,taker_fee=0,maker_fee=0,slippage=0,bull_regime_lookback_days=1,bull_regime_return_threshold=.01,enable_strategy_profiles=True,strategy_profiles=profiles)
    base.update(changes)
    return BacktestConfig(**base)


def test_profile_serialization_round_trip_preserves_all_six_profiles():
    profiles=default_profiles(); profiles["bear_short"]=StrategyProfile(enabled=True,adx_enabled=True,adx_minimum=15,adx_maximum=40)
    restored=normalize_profiles(profiles_to_dict(profiles))
    assert tuple(restored)==tuple(profiles)
    assert restored["bear_short"].enabled
    assert restored["bear_short"].entry_rules==({"action":"REJECT","indicator":"ADX","condition":"OUTSIDE","minimum":15,"maximum":40},)


def test_profile_filter_bypasses_legacy_global_entry_filters():
    engine=BacktestEngine(rising_candles(),profile_config(enable_di_spread_filter=True,di_spread_minimum=999,di_spread_maximum=1000))
    passed,reason=engine._entry_filter_result(len(engine.data)-1)
    assert passed
    assert "bull_long" in reason


def test_profile_reward_risk_and_risk_multiplier_are_applied_to_trade():
    engine=BacktestEngine(rising_candles(),profile_config())
    i=len(engine.data)-1
    passed,reason=engine._entry_filter_result(i)
    assert passed
    engine._open_pair(i,passed,reason)
    pair=engine.active_pairs[0]
    assert pair.strategy_profile_key=="bull_long"
    assert pair.di_applied_long_reward_risk_ratio==2.5
    assert pair.long is not None
    assert pair.long.risk_amount==15


def test_profile_can_flip_its_filtered_di_entry_direction():
    profiles=default_profiles()
    profiles["bull_long"]=StrategyProfile(enabled=True,flip_direction=True)
    engine=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles))
    i=len(engine.data)-1
    passed,reason=engine._entry_filter_result(i)
    assert passed

    engine._open_pair(i,passed,reason)

    pair=engine.active_pairs[0]
    assert pair.di_sizing_direction=="LONG"
    assert pair.sizing_direction=="SHORT"
    assert pair.long is None
    assert pair.short is not None


def test_profile_filter_action_flips_matches_and_keeps_nonmatches_normal():
    profiles=default_profiles()
    profiles["bull_long"]=StrategyProfile(enabled=True,entry_rules=({"action":"FLIP","indicator":"ADX","condition":"INSIDE","minimum":10,"maximum":20},{"action":"FLIP","indicator":"CLOSE_LOCATION","condition":"INSIDE","minimum":.45,"maximum":.68},{"action":"FLIP","indicator":"RSI","condition":"INSIDE","minimum":30,"maximum":40}),flip_rule_match_mode="ANY")

    matching=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles))
    i=len(matching.data)-1
    matching.adx_values[i]=15
    passed,reason=matching._entry_filter_result(i)
    assert passed and "will be flipped" in reason
    matching._open_pair(i,passed,reason)
    assert matching.active_pairs[0].sizing_direction=="SHORT"

    secondary=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles))
    secondary.adx_values[i]=25
    passed,reason=secondary._entry_filter_result(i)
    assert passed and "will be flipped" in reason
    secondary._open_pair(i,passed,reason)
    assert secondary.active_pairs[0].sizing_direction=="SHORT"

    normal=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles))
    normal.adx_values[i]=25; normal.close_location_values[i]=.9
    passed,reason=normal._entry_filter_result(i)
    assert passed and "normal direction" in reason
    normal._open_pair(i,passed,reason)
    assert normal.active_pairs[0].sizing_direction=="LONG"


def test_unified_profile_rules_apply_reject_before_flip():
    profiles=default_profiles()
    profiles["bull_long"]=StrategyProfile(enabled=True,entry_rules=({"action":"FLIP","indicator":"ADX","condition":"INSIDE","minimum":10,"maximum":20},{"action":"REJECT","indicator":"CLOSE_LOCATION","condition":"INSIDE","minimum":.4,"maximum":.6}))
    engine=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles)); i=len(engine.data)-1; engine.adx_values[i]=15
    passed,reason=engine._entry_filter_result(i)
    assert not passed and "rejected by entry rules" in reason


def test_disabled_profile_rejects_its_regime_direction():
    config=profile_config(strategy_profiles={key:StrategyProfile() for key in default_profiles()})
    engine=BacktestEngine(rising_candles(),config)
    passed,reason=engine._entry_filter_result(len(engine.data)-1)
    assert not passed
    assert "bull_long is disabled" in reason


def test_profile_owns_stop_and_partial_profit_exit_plan():
    profiles=default_profiles()
    profiles["bull_long"]=StrategyProfile(enabled=True,reward_risk_ratio=9,risk_multiplier=1,stop_loss_multiple=1.5,partial_profit_enabled=True,tp1_r=1,tp1_close_pct=40,tp2_r=3,after_tp1_stop_mode="MOVE_TO_ENTRY")
    engine=BacktestEngine(rising_candles(),profile_config(strategy_profiles=profiles))
    engine._open_pair(len(engine.data)-1)
    pair=engine.active_pairs[0]; position=pair.long
    assert position is not None and position.partial_tp_enabled
    assert position.entry_price-position.sl==pytest.approx(3)
    assert position.tp1_price-position.entry_price==pytest.approx(3)
    assert position.tp2_price-position.entry_price==pytest.approx(9)
    assert position.tp1_quantity/position.original_quantity==pytest.approx(.40)
    assert position.after_tp1_stop_mode=="MOVE_TO_ENTRY"
