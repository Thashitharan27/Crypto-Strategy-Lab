from dataclasses import replace
import pandas as pd
import pandas.testing as pdt
import pytest
from crypto_strategy_lab.config import BacktestConfig, EntryTimingMode, RandomEntryStartMode, RiskMode, TradeDirectionMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def candles(n=8):
    return pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=n,freq="15min",tz="UTC"),"open":[100+i for i in range(n)],"high":[100+i for i in range(n)],"low":[100+i for i in range(n)],"close":[999 if i==0 else 100+i for i in range(n)],"volume":1.0})


def config(**kw):
    base=dict(risk_mode=RiskMode.FIXED,fixed_r=10,use_intrabar_data=False,enable_trade_telemetry=False,taker_fee=0,slippage=0,enable_random_entry=True,entry_timing_mode=EntryTimingMode.RANDOM_AFTER_PAIR_CLOSE,random_entry_probability=.5,random_seed=1)
    base.update(kw)
    sl = float(base.get("sl_mult", 2.0))
    tp = float(base.get("tp_mult", 3.0))
    profile = StrategyProfile(enabled=True, stop_loss_multiple=sl, reward_risk_ratio=tp / sl)
    base["enable_strategy_profiles"] = True
    base["strategy_profiles"] = {key: profile for key in PROFILE_KEYS}
    return BacktestConfig(**base)


def test_heads_first_eligible_opens_pair_at_open_with_lagged_indicator():
    engine=BacktestEngine(candles(),config(random_seed=1)) # first draw .134 < .5
    trades=engine.run()
    assert trades.iloc[0].entry_time == candles().timestamp.iloc[1]
    assert trades.iloc[0].strategy_entry_price == candles().open.iloc[1]
    assert trades.iloc[0].r_distance == 10
    assert engine.random_entry_decisions[0]["decision"] == "OPEN"
    assert trades.iloc[0].long_entry_price == trades.iloc[0].short_entry_price


def test_tails_then_heads_delays_both_legs():
    engine=BacktestEngine(candles(),config(random_seed=10)) # .571 skip, .429 open
    trades=engine.run(); decisions=engine.random_entry_decisions
    assert [r["decision"] for r in decisions[:2]] == ["SKIP","OPEN"]
    assert trades.iloc[0].entry_time == candles().timestamp.iloc[2]
    assert trades.iloc[0].side == "BOTH"


def test_multiple_tails_and_exactly_one_draw_per_eligible_candle():
    engine=BacktestEngine(candles(),config(random_seed=5)) # .62, .74, .79...
    engine.run()
    assert [r["decision"] for r in engine.random_entry_decisions[:3]] == ["SKIP"]*3
    assert len({r["decision_id"] for r in engine.random_entry_decisions}) == len(engine.random_entry_decisions)


def test_no_draw_while_pair_or_partial_leg_is_open():
    engine=BacktestEngine(candles(),config(random_seed=1))
    engine.run()
    # Stable candles leave both legs open until end-of-data, hence only entry decision.
    assert len(engine.random_entry_decisions) == 1


def test_seed_reproducibility_and_report_independence():
    a=BacktestEngine(candles(),config(random_seed=10)); ta=a.run(); _=a.results_frame(); _=a.telemetry_frame()
    b=BacktestEngine(candles(),config(random_seed=10)); tb=b.run()
    assert [x["random_draw"] for x in a.random_entry_decisions] == [x["random_draw"] for x in b.random_entry_decisions]
    pdt.assert_series_equal(ta.entry_time,tb.entry_time)
    c=BacktestEngine(candles(),config(random_seed=11)); c.run()
    assert [x["random_draw"] for x in a.random_entry_decisions] != [x["random_draw"] for x in c.random_entry_decisions]


def test_max_wait_zero_never_forces_and_positive_forces_next_candle():
    pure=BacktestEngine(candles(),config(random_seed=5,max_random_wait_candles=0)); pure.run()
    assert not any(r["forced_entry"] for r in pure.random_entry_decisions)
    forced=BacktestEngine(candles(),config(random_seed=5,max_random_wait_candles=2)); trades=forced.run()
    assert forced.random_entry_decisions[2]["decision"] == "FORCED_OPEN"
    assert trades.iloc[0].random_entry_forced


def test_randomize_first_entry_false_consumes_no_initial_draw():
    engine=BacktestEngine(candles(),config(randomize_first_entry=False)); trades=engine.run()
    assert len(trades)==1 and not engine.random_entry_decisions
    assert pd.isna(trades.iloc[0].random_decision_id)


def test_disabled_is_exact_baseline_and_daily_schedule_cannot_duplicate():
    data=candles()
    baseline=BacktestEngine(data,replace(config(),enable_random_entry=False,entry_timing_mode=EntryTimingMode.CURRENT)).run()
    disabled=BacktestEngine(data,replace(config(),enable_random_entry=False,entry_timing_mode=EntryTimingMode.RANDOM_AFTER_PAIR_CLOSE)).run()
    pdt.assert_frame_equal(baseline,disabled)
    random=BacktestEngine(data,config(enable_daily_entry_schedule=True,daily_entry_time="00:00",random_seed=1)); random.run()
    assert random.daily_entry_opportunities == 0


def test_validation_probability_and_integer_seed():
    with pytest.raises(ValueError,match="probability"): config(random_entry_probability=0)
    with pytest.raises(ValueError,match="integer"): config(random_seed=1.5)
