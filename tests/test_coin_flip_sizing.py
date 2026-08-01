import pandas as pd
import pandas.testing as pdt
import pytest

from config import BacktestConfig, RiskMode, TradeDirectionMode, DIExecutionMode
from engine import BacktestEngine


def candles():
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=3, freq="15min", tz="UTC"),
            "open": [100.0, 100.0, 100.0],
            "high": [100.0, 100.0, 100.0],
            "low": [100.0, 100.0, 100.0],
            "close": [100.0, 100.0, 100.0],
            "volume": 1.0,
        }
    )


def config(**overrides):
    values = dict(
        risk_mode=RiskMode.FIXED,
        fixed_r=10,
        sl_mult=1,
        tp_mult=99,  # Coin-flip mode must override this to the 1:1 stop distance.
        use_intrabar_data=False,
        enable_trade_telemetry=False,
        maker_fee=0,
        taker_fee=0,
        slippage=0,
        enable_coin_flip_sizing=True,
        coin_flip_seed=1,
        coin_flip_large_multiplier=3,
        coin_flip_small_multiplier=1,
    )
    values.update(overrides)
    return BacktestConfig(**values)


def test_heads_assigns_three_to_long_and_one_to_short_with_mirrored_one_to_one_levels():
    row = BacktestEngine(candles(), config(coin_flip_seed=1)).run().iloc[0]
    assert row.coin_flip_result == "HEADS"
    assert row.long_size_multiplier == 3
    assert row.short_size_multiplier == 1
    assert row.long_quantity == pytest.approx(3 * row.short_quantity)
    assert row.long_entry_price == row.short_entry_price == 100
    assert row.long_sl == row.short_tp == 90
    assert row.long_tp == row.short_sl == 110


def test_tails_reverses_the_three_to_one_assignment():
    row = BacktestEngine(candles(), config(coin_flip_seed=2)).run().iloc[0]
    assert row.coin_flip_result == "TAILS"
    assert row.long_size_multiplier == 1
    assert row.short_size_multiplier == 3
    assert row.short_quantity == pytest.approx(3 * row.long_quantity)


def test_coin_flip_is_reproducible_and_does_not_change_baseline_when_disabled():
    first = BacktestEngine(candles(), config()).run()
    second = BacktestEngine(candles(), config()).run()
    pdt.assert_frame_equal(first, second)

    base = BacktestConfig(risk_mode=RiskMode.FIXED, fixed_r=10, use_intrabar_data=False, enable_trade_telemetry=False)
    explicit_off = BacktestConfig(risk_mode=RiskMode.FIXED, fixed_r=10, use_intrabar_data=False, enable_trade_telemetry=False, enable_coin_flip_sizing=False)
    pdt.assert_frame_equal(BacktestEngine(candles(), base).run(), BacktestEngine(candles(), explicit_off).run())


def test_coin_flip_requires_two_full_legs():
    with pytest.raises(ValueError, match="both long and short"):
        config(trade_direction=TradeDirectionMode.LONG_ONLY)
    with pytest.raises(ValueError, match="partial TP"):
        config(enable_partial_take_profit=True)


def di_engine(plus, minus, minimum=30):
    engine = BacktestEngine(
        candles(),
        config(
            enable_coin_flip_sizing=False,
            enable_di_direction_sizing=True,
            di_direction_minimum_spread=minimum,
            slippage=0.0001,
        ),
    )
    engine.plus_di_values[:] = plus
    engine.minus_di_values[:] = minus
    engine.di_spread[:] = abs(plus - minus)
    return engine


def test_di_direction_assigns_large_size_to_stronger_positive_di():
    row = di_engine(50, 15).run().iloc[0]
    assert row.di_direction_sizing_enabled
    assert row.di_sizing_direction == "LONG"
    assert row.sizing_direction == "LONG"
    assert row.long_quantity == pytest.approx(3 * row.short_quantity)
    assert row.long_sl == row.short_tp
    assert row.long_tp == row.short_sl
    combined_risk = row.long_risk_amount + row.short_risk_amount
    assert row.pair_net_r == pytest.approx(row.pair_net_pnl / combined_risk)
    assert row.pair_net_r == pytest.approx(row.pair_net_account_r)
    assert row.pair_leg_net_r_sum == pytest.approx(row.long_net_r + row.short_net_r)


def test_di_direction_assigns_large_size_to_stronger_negative_di():
    row = di_engine(10, 45).run().iloc[0]
    assert row.di_sizing_direction == "SHORT"
    assert row.short_quantity == pytest.approx(3 * row.long_quantity)


def test_di_direction_uses_separate_long_and_short_minimums():
    long_engine = di_engine(44, 10)
    object.__setattr__(long_engine.config, "di_direction_long_minimum_spread", 35)
    object.__setattr__(long_engine.config, "di_direction_short_minimum_spread", 40)
    assert not long_engine._entry_filter_result(0)[0]

    short_engine = di_engine(10, 46)
    object.__setattr__(short_engine.config, "di_direction_long_minimum_spread", 40)
    object.__setattr__(short_engine.config, "di_direction_short_minimum_spread", 35)
    assert short_engine._entry_filter_result(0)[0]


def test_direction_specific_adx_filter_uses_long_maximum_and_short_minimum():
    long_engine = di_engine(50, 15)
    object.__setattr__(long_engine.config, "enable_directional_adx_filter", True)
    object.__setattr__(long_engine.config, "directional_long_adx_maximum", 60)
    object.__setattr__(long_engine.config, "directional_short_adx_minimum", 25)
    long_engine.adx_values[:] = 61
    passed, reason = long_engine._entry_filter_result(0)
    assert not passed
    assert "Long DI signal skipped" in reason
    long_engine.adx_values[:] = 60
    assert long_engine._entry_filter_result(0)[0]

    short_engine = di_engine(10, 45)
    object.__setattr__(short_engine.config, "enable_directional_adx_filter", True)
    object.__setattr__(short_engine.config, "directional_long_adx_maximum", 60)
    object.__setattr__(short_engine.config, "directional_short_adx_minimum", 25)
    short_engine.adx_values[:] = 24
    passed, reason = short_engine._entry_filter_result(0)
    assert not passed
    assert "Short DI signal skipped" in reason
    short_engine.adx_values[:] = 25
    assert short_engine._entry_filter_result(0)[0]


def test_di_preferred_side_only_opens_long_with_direct_risk_and_one_to_one_levels():
    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{**engine.config.__dict__, "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY, "risk_per_leg": 0.01}
    )
    row = engine.run().iloc[0]
    assert row.side == "LONG"
    assert row.di_execution_mode == "PREFERRED_SIDE_ONLY"
    assert row.long_size_multiplier == 1
    assert row.short_size_multiplier == 0
    assert row.strategy_entry_price == 100
    assert row.long_entry_price == pytest.approx(100.01)
    assert row.long_risk_amount == pytest.approx(10.0)
    assert "short_quantity" not in row.index
    assert row.long_tp - row.long_entry_price == pytest.approx(row.long_entry_price - row.long_sl)


def test_di_preferred_side_only_opens_short():
    engine = di_engine(10, 45)
    engine.config = BacktestConfig(
        **{**engine.config.__dict__, "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY, "risk_per_leg": 0.01}
    )
    row = engine.run().iloc[0]
    assert row.side == "SHORT"
    assert row.strategy_entry_price == 100
    assert row.short_entry_price == pytest.approx(99.99)
    assert row.short_risk_amount == pytest.approx(10.0)
    assert "long_quantity" not in row.index


def test_di_preferred_side_only_supports_two_to_one_reward_risk():
    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "di_reward_risk_ratio": 2.0,
            "di_long_reward_risk_ratio": 2.0,
            "di_short_reward_risk_ratio": 2.0,
        }
    )
    row = engine.run().iloc[0]
    stop_distance = row.long_entry_price - row.long_sl
    target_distance = row.long_tp - row.long_entry_price
    assert target_distance == pytest.approx(2 * stop_distance)
    assert row.di_reward_risk_ratio == pytest.approx(2.0)


def test_di_preferred_side_only_supports_asymmetric_reward_risk():
    long_engine = di_engine(50, 15)
    long_engine.config = BacktestConfig(
        **{
            **long_engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "di_long_reward_risk_ratio": 2.0,
            "di_short_reward_risk_ratio": 1.0,
        }
    )
    long_row = long_engine.run().iloc[0]
    assert long_row.long_tp - long_row.long_entry_price == pytest.approx(
        2 * (long_row.long_entry_price - long_row.long_sl)
    )

    short_engine = di_engine(10, 45)
    short_engine.config = BacktestConfig(
        **{
            **short_engine.config.__dict__,
            "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY,
            "di_long_reward_risk_ratio": 2.0,
            "di_short_reward_risk_ratio": 1.0,
        }
    )
    short_row = short_engine.run().iloc[0]
    assert short_row.short_entry_price - short_row.short_tp == pytest.approx(
        short_row.short_sl - short_row.short_entry_price
    )


def test_di_both_sides_remains_the_default_execution_mode():
    row = di_engine(50, 15).run().iloc[0]
    assert row.di_execution_mode == "BOTH_SIDES"
    assert row.long_entry_price == row.short_entry_price == row.strategy_entry_price == 100
    assert row.long_quantity == pytest.approx(3 * row.short_quantity)


def test_preferred_side_only_requires_di_selection():
    with pytest.raises(ValueError, match="requires DI-direction"):
        BacktestConfig(di_execution_mode=DIExecutionMode.PREFERRED_SIDE_ONLY)


def test_one_sided_rows_do_not_create_false_be_same_candle_ambiguities():
    from statistics import summarize

    long_engine = di_engine(50, 15)
    long_engine.config = BacktestConfig(
        **{**long_engine.config.__dict__, "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY}
    )
    short_engine = di_engine(10, 45)
    short_engine.config = BacktestConfig(
        **{**short_engine.config.__dict__, "di_execution_mode": DIExecutionMode.PREFERRED_SIDE_ONLY}
    )
    trades = pd.concat([long_engine.run(), short_engine.run()], ignore_index=True)
    trades["equity_after_trade"] = 1000 + trades["pair_net_pnl"].cumsum()
    assert summarize(trades, 1000)["be_same_candle_ambiguity_count"] == 0


def test_di_direction_skips_entries_below_minimum_spread():
    engine = di_engine(35, 20, minimum=30)
    assert engine.run().empty
    assert engine.skipped_signals
    assert all("below direction-sizing minimum" in row["entry_filter_reason"] for row in engine.skipped_signals)


def test_coin_and_di_direction_modes_are_mutually_exclusive():
    with pytest.raises(ValueError, match="cannot both"):
        config(enable_di_direction_sizing=True)


def test_journey_enrichment_preserves_skipped_signal_metadata():
    from telemetry import INDICATORS, add_journey_columns

    trades = pd.DataFrame({"pair_id": [1], "holding_minutes": [0]})
    skipped = [{"entry_filter_reason": "DI spread below minimum"}]
    trades.attrs["skipped_signals"] = skipped
    telemetry = pd.DataFrame({"pair_id": [1], "elapsed_minutes": [0], **{name: [1.0] for name in INDICATORS}})
    enriched = add_journey_columns(trades, telemetry)
    assert enriched.attrs["skipped_signals"] == skipped


def test_bull_regime_filter_skips_short_di_signal():
    engine = di_engine(10, 45)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "enable_bull_regime_short_filter": True,
            "bull_regime_lookback_days": 90,
            "bull_regime_return_threshold": 0.20,
        }
    )
    engine.bull_regime_return_values[:] = 0.25
    assert engine.run().empty
    assert all("Short DI signal skipped in bull regime" in row["entry_filter_reason"] for row in engine.skipped_signals)


def test_bull_regime_filter_allows_long_di_signal():
    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "enable_bull_regime_short_filter": True,
            "bull_regime_lookback_days": 90,
            "bull_regime_return_threshold": 0.20,
        }
    )
    engine.bull_regime_return_values[:] = 0.25
    row = engine.run().iloc[0]
    assert row.sizing_direction == "LONG"
    assert row.bull_regime


def test_bull_long_conditional_reward_risk_uses_override_only_when_both_conditions_pass():
    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "enable_di_regime_reward_risk": True,
            "di_long_bull_reward_risk_ratio": 2,
            "enable_bull_long_conditional_reward_risk": True,
            "bull_long_conditional_bb_width_minimum": 0.05,
            "bull_long_conditional_adx_maximum": 40,
            "bull_long_conditional_reward_risk_ratio": 1,
        }
    )
    engine.bull_regime_return_values[:] = 0.25
    engine.bb_width[:] = 0.05
    engine.adx_values[:] = 39.99
    row = engine.run().iloc[0]
    assert row.di_reward_risk_regime == "BULL"
    assert row.bull_long_conditional_reward_risk_applied
    assert row.di_applied_long_reward_risk_ratio == 1

    engine = di_engine(50, 15)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "enable_di_regime_reward_risk": True,
            "di_long_bull_reward_risk_ratio": 2,
            "enable_bull_long_conditional_reward_risk": True,
            "bull_long_conditional_bb_width_minimum": 0.05,
            "bull_long_conditional_adx_maximum": 40,
            "bull_long_conditional_reward_risk_ratio": 1,
        }
    )
    engine.bull_regime_return_values[:] = 0.25
    engine.bb_width[:] = 0.0499
    engine.adx_values[:] = 39.99
    row = engine.run().iloc[0]
    assert not row.bull_long_conditional_reward_risk_applied
    assert row.di_applied_long_reward_risk_ratio == 2


def test_bull_regime_filter_allows_short_outside_bull_regime():
    engine = di_engine(10, 45)
    engine.config = BacktestConfig(
        **{
            **engine.config.__dict__,
            "enable_bull_regime_short_filter": True,
            "bull_regime_lookback_days": 90,
            "bull_regime_return_threshold": 0.20,
        }
    )
    engine.bull_regime_return_values[:] = 0.10
    row = engine.run().iloc[0]
    assert row.sizing_direction == "SHORT"
    assert not row.bull_regime
