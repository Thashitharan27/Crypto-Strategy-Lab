import pandas as pd
import pytest

from crypto_strategy_lab.config import AfterTP1StopMode, BacktestConfig, RiskMode, TrailActivationTrigger, TiePolicy, TradeDirectionMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def candles(*bars):
    return pd.DataFrame([{"timestamp":pd.Timestamp("2024-01-01",tz="UTC")+pd.Timedelta(minutes=15*i),"open":100,"close":100,"high":h,"low":l,"volume":1} for i,(h,l) in enumerate(bars)])


def _profile_value(value):
    return getattr(value, "value", value)


def _profiles_for(values):
    partial_profit = bool(values.get("enable_partial_take_profit", False))
    partial_stop = bool(values.get("enable_partial_stop_loss", False))
    sl = float(values.get("sl_mult", 2.0))
    tp = float(values.get("tp_mult", 3.0))
    profile = StrategyProfile(
        enabled=True,
        stop_loss_multiple=float(values.get("stop_loss_r", sl)) if partial_profit else sl,
        reward_risk_ratio=tp / sl,
        partial_profit_enabled=partial_profit,
        tp1_r=float(values.get("tp1_r", 1.0)),
        tp1_close_pct=float(values.get("tp1_close_pct", 50.0)),
        tp2_r=float(values.get("tp2_r", 2.0)),
        after_tp1_stop_mode=_profile_value(values.get("after_tp1_stop_mode", "KEEP_ORIGINAL_SL")),
        after_tp1_stop_offset_r=float(values.get("after_tp1_stop_offset_r", 0.0)),
        partial_stop_enabled=partial_stop,
        sl1_r=float(values.get("sl1_r", 0.5)),
        sl1_close_pct=float(values.get("sl1_close_pct", 50.0)),
        sl2_r=float(values.get("sl2_r", 2.0)),
        trailing_enabled=bool(values.get("enable_trailing_profit", False)),
        trailing_activation_r=float(values.get("trail_activation_r", 3.0)),
        trailing_distance_r=float(values.get("trail_distance_r", 1.0)),
    )
    return {key: profile for key in PROFILE_KEYS}


def config(**kw):
    base=dict(risk_mode=RiskMode.FIXED,fixed_r=10,atr_period=1,use_intrabar_data=False,enable_trade_telemetry=False,
              enable_partial_take_profit=True,tp1_r=1,tp2_r=2,stop_loss_r=2,tp1_close_pct=50,tp2_close_pct=50,
              maker_fee=0,taker_fee=0,slippage=0,trade_direction=TradeDirectionMode.LONG_ONLY)
    base.update(kw)
    base["enable_strategy_profiles"] = True
    base.setdefault("strategy_profiles", _profiles_for(base))
    return BacktestConfig(**base)


def run(bars, **kw):
    return BacktestEngine(candles(*bars),config(**kw)).run().iloc[0]


def test_long_tp1_then_stop_closes_only_remainder():
    row=run([(100,100),(111,99),(105,79)])
    assert row.long_tp1_hit and not row.long_tp2_hit
    assert row.long_stop_exit_quantity == pytest.approx(row.long_original_quantity/2)
    assert row.long_final_exit_reason == "TP1_THEN_SL"
    assert row.long_tp1_quantity + row.long_tp2_quantity == pytest.approx(row.long_original_quantity)


def test_long_tp1_then_tp2_and_fee_reconciliation():
    row=run([(100,100),(121,99)],taker_fee=.001,tie_policy=TiePolicy.OPTIMISTIC)
    assert row.long_tp1_hit and row.long_tp2_hit
    assert row.long_remaining_quantity == 0
    expected=row.long_entry_fee+row.long_tp1_exit_price*row.long_tp1_quantity*.001+row.long_tp2_exit_price*row.long_tp2_quantity*.001
    assert row.long_total_fees == pytest.approx(expected)
    assert row.pair_net_pnl == pytest.approx(row.long_total_net_pnl)


def test_pessimistic_same_candle_stop_precedes_tp1():
    row=run([(100,100),(111,79)],tie_policy=TiePolicy.PESSIMISTIC)
    assert not row.long_tp1_hit
    assert row.long_final_exit_reason == "SL"


def test_optimistic_same_candle_runs_tp1_then_tp2():
    row=run([(100,100),(121,79)],tie_policy=TiePolicy.OPTIMISTIC)
    assert row.long_tp1_hit and row.long_tp2_hit
    assert row.long_stop_exit_time is None or pd.isna(row.long_stop_exit_time)


@pytest.mark.parametrize("mode,offset,expected",[
    (AfterTP1StopMode.KEEP_ORIGINAL_SL,0,80),
    (AfterTP1StopMode.MOVE_TO_ENTRY,0,100),
    (AfterTP1StopMode.MOVE_TO_R_OFFSET,1,110),
])
def test_after_tp1_stop_modes(mode,offset,expected):
    engine=BacktestEngine(candles((100,100),(111,99),(100,100)),config(after_tp1_stop_mode=mode,after_tp1_stop_offset_r=offset))
    engine.run(); assert engine.completed_pairs[0].long.sl == expected


def test_trailing_after_tp1_coexists_with_fixed_tp2():
    row=run(
        [(100,100),(111,100),(121,110)],
        enable_trailing_profit=True,
        trail_activation_trigger=TrailActivationTrigger.AFTER_TP1,
        trail_distance_r=1,
        tie_policy=TiePolicy.PESSIMISTIC,
    )
    assert row.long_tp1_hit and row.long_tp2_hit
    assert row.long_remaining_quantity == 0


def test_disabled_mode_is_identical_to_non_partial_profile_configuration():
    data=candles((100,100),(111,89))
    common=dict(risk_mode=RiskMode.FIXED,fixed_r=10,atr_period=1,use_intrabar_data=False,enable_trade_telemetry=False,
                sl_mult=1,tp_mult=1,maker_fee=0,taker_fee=0,slippage=0,enable_strategy_profiles=True,
                strategy_profiles={key:StrategyProfile(enabled=True,stop_loss_multiple=1,reward_risk_ratio=1) for key in PROFILE_KEYS})
    baseline=BacktestEngine(data,BacktestConfig(**common)).run()
    disabled=BacktestEngine(data,BacktestConfig(**common,enable_partial_take_profit=False)).run()
    pd.testing.assert_frame_equal(baseline,disabled)


def test_combined_ladders_allow_sl1_then_tp1_then_tp2():
    row=run(
        [(100,100),(100,94),(111,100),(121,100)],
        enable_partial_stop_loss=True,
        sl1_r=.5,
        sl1_close_pct=25,
        sl2_r=2,
    )
    assert row.long_sl1_hit and row.long_tp1_hit and row.long_tp2_hit
    assert row.long_sl1_quantity + row.long_tp1_quantity + row.long_tp2_quantity == pytest.approx(row.long_original_quantity)
    assert row.long_remaining_quantity == 0


def test_combined_move_to_entry_after_tp1_overrides_pending_sl_ladder():
    row=run(
        [(100,100),(111,100),(100,99)],
        enable_partial_stop_loss=True,
        sl1_r=.5,
        sl1_close_pct=25,
        sl2_r=2,
        after_tp1_stop_mode=AfterTP1StopMode.MOVE_TO_ENTRY,
    )
    assert row.long_tp1_hit
    assert not row.long_sl1_hit
    assert row.long_stop_exit_price == pytest.approx(100)
    assert row.long_stop_exit_quantity == pytest.approx(row.long_original_quantity/2)
