import pandas as pd
import pytest

from crypto_strategy_lab.config import BacktestConfig, EntryMode, RiskMode
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.statistics import summarize
from crypto_strategy_lab.strategy_profiles import PROFILE_KEYS, StrategyProfile


def strategy(rows):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=15*i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1,
    })


def intrabar(rows, start="2024-01-01 00:15"):
    start = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame({
        "timestamp": [start + pd.Timedelta(minutes=i) for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1,
    })


def config(**overrides):
    values = dict(risk_mode=RiskMode.FIXED, fixed_r=10, atr_period=1,
                  initial_equity=1000, risk_per_leg=.01, sl_mult=1, tp_mult=5,
                  maker_fee=0, taker_fee=0, slippage=0,
                  entry_mode=EntryMode.WAIT_UNTIL_CLOSED, use_intrabar_data=True,
                  enable_remaining_leg_timeout_after_first_sl=True,
                  remaining_leg_timeout_after_first_sl_minutes=5)
    values.update(overrides)
    sl = float(values.get("sl_mult", 1.0))
    tp = float(values.get("tp_mult", 5.0))
    profile = StrategyProfile(enabled=True, stop_loss_multiple=sl, reward_risk_ratio=tp / sl)
    values["enable_strategy_profiles"] = True
    values.setdefault("strategy_profiles", {key: profile for key in PROFILE_KEYS})
    return BacktestConfig(**values)


def quiet_strategy():
    return strategy([(100, 100, 100, 100)] * 3)


def test_intrabar_long_sl_starts_exact_timer_and_times_out_short_at_deadline_open():
    rows = [(100, 100, 100, 100), (100, 100, 89, 100)] + [(100, 101, 99, 100)] * 4 + [(97, 98, 96, 97)] + [(97, 98, 96, 97)] * 23
    row = BacktestEngine(quiet_strategy(), config(slippage=.01, taker_fee=.001), intrabar(rows)).run().iloc[0]
    assert row.long_exit_reason == "SL"
    assert row.short_exit_reason == "REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"
    assert row.first_sl_side == "LONG"
    assert row.first_sl_time == pd.Timestamp("2024-01-01 00:16", tz="UTC")
    assert row.remaining_leg_timeout_deadline == pd.Timestamp("2024-01-01 00:21", tz="UTC")
    assert row.remaining_leg_timeout_exit_time == row.remaining_leg_timeout_deadline
    assert row.short_exit_price == pytest.approx(97 * 1.01)
    assert row.short_exit_fee == pytest.approx(row.short_exit_price * row.short_quantity * .001)
    assert row.remaining_leg_timeout_exit_side == "SHORT"


def test_intrabar_short_sl_times_out_long_with_directional_costs():
    rows = [(100, 100, 100, 100), (100, 111, 100, 100)] + [(100, 101, 99, 100)] * 4 + [(103, 104, 102, 103)] + [(103, 104, 102, 103)] * 23
    row = BacktestEngine(quiet_strategy(), config(slippage=.01, taker_fee=.001), intrabar(rows)).run().iloc[0]
    assert row.short_exit_reason == "SL"
    assert row.long_exit_reason == "REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"
    assert row.first_sl_side == "SHORT"
    assert row.long_exit_price == pytest.approx(103 * .99)
    assert row.long_exit_fee == pytest.approx(row.long_exit_price * row.long_quantity * .001)


def test_natural_tp_before_deadline_is_preserved_and_timeout_not_triggered():
    rows = [(100, 100, 100, 100), (100, 100, 89, 100), (100, 101, 49, 50)] + [(50, 51, 49, 50)] * 27
    row = BacktestEngine(quiet_strategy(), config(), intrabar(rows)).run().iloc[0]
    assert row.short_exit_reason == "TP"
    assert row.remaining_leg_timeout_after_first_sl_started
    assert not row.remaining_leg_timeout_triggered
    assert summarize(pd.DataFrame([row]))["remaining_legs_reaching_tp_before_timeout"] == 1


def test_strategy_candle_fallback_uses_first_open_at_or_after_deadline():
    data = strategy([(100,100,100,100), (100,100,89,100), (96,101,95,96), (95,100,94,95)])
    row = BacktestEngine(data, config(use_intrabar_data=False, remaining_leg_timeout_after_first_sl_minutes=5)).run().iloc[0]
    assert row.first_sl_time == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert row.remaining_leg_timeout_deadline == pd.Timestamp("2024-01-01 00:20", tz="UTC")
    assert row.remaining_leg_timeout_exit_time == pd.Timestamp("2024-01-01 00:30", tz="UTC")
    assert row.short_exit_price == 96
    assert row.short_exit_source == "15M_FALLBACK"
    assert row.short_fallback_reason == "remaining_leg_timeout_intrabar_unavailable"


def test_disabled_and_end_of_data_behavior_and_summary_audit():
    data = strategy([(100,100,100,100), (100,100,89,100)])
    disabled = BacktestEngine(data, config(use_intrabar_data=False, enable_remaining_leg_timeout_after_first_sl=False)).run().iloc[0]
    enabled = BacktestEngine(data, config(use_intrabar_data=False, remaining_leg_timeout_after_first_sl_minutes=60)).run().iloc[0]
    assert disabled.short_exit_reason == enabled.short_exit_reason == "END_OF_DATA"
    assert not disabled.remaining_leg_timeout_after_first_sl_started
    assert enabled.remaining_leg_timeout_after_first_sl_started
    assert not enabled.remaining_leg_timeout_triggered
    stats = summarize(pd.DataFrame([enabled]))
    assert stats["pairs_where_remaining_leg_timeout_started"] == 1
    assert stats["pairs_closed_by_remaining_leg_timeout"] == 0
    assert stats["total_pnl_of_remaining_leg_timeout_pairs"] == pytest.approx(enabled.pair_net_pnl)


def test_enabled_duration_must_be_positive():
    with pytest.raises(ValueError, match="remaining_leg_timeout_after_first_sl_minutes"):
        config(remaining_leg_timeout_after_first_sl_minutes=0)


def test_profitable_remaining_leg_gets_another_interval_and_can_reach_tp():
    rows = (
        [(100, 100, 100, 100), (100, 100, 89, 100)]
        + [(100, 101, 99, 100)] * 4
        + [(80, 81, 79, 80), (80, 81, 49, 50)]
        + [(50, 51, 49, 50)] * 22
    )
    row = BacktestEngine(
        quiet_strategy(),
        config(enable_remaining_leg_timeout_profit_extension=True,
               remaining_leg_timeout_profit_threshold_r=2),
        intrabar(rows),
    ).run().iloc[0]
    assert row.short_exit_reason == "TP"
    assert not row.remaining_leg_timeout_triggered
    assert row.remaining_leg_timeout_checkpoint_count == 1
    assert row.remaining_leg_timeout_extension_count == 1
    assert row.remaining_leg_timeout_last_checkpoint_profit_r == pytest.approx(2)
    assert row.remaining_leg_timeout_deadline == pd.Timestamp("2024-01-01 00:26", tz="UTC")


def test_extended_leg_is_rechecked_and_closed_when_profit_falls_below_threshold():
    rows = (
        [(100, 100, 100, 100), (100, 100, 89, 100)]
        + [(100, 101, 99, 100)] * 4
        + [(80, 81, 79, 80)]
        + [(90, 91, 89, 90)] * 4
        + [(95, 96, 94, 95)]
        + [(95, 96, 94, 95)] * 18
    )
    row = BacktestEngine(
        quiet_strategy(),
        config(enable_remaining_leg_timeout_profit_extension=True,
               remaining_leg_timeout_profit_threshold_r=2),
        intrabar(rows),
    ).run().iloc[0]
    assert row.short_exit_reason == "REMAINING_LEG_TIMEOUT_AFTER_FIRST_SL"
    assert row.remaining_leg_timeout_triggered
    assert row.remaining_leg_timeout_exit_time == pd.Timestamp("2024-01-01 00:26", tz="UTC")
    assert row.remaining_leg_timeout_checkpoint_count == 2
    assert row.remaining_leg_timeout_extension_count == 1
    assert row.remaining_leg_timeout_last_checkpoint_profit_r == pytest.approx(.5)


def test_profit_extension_requires_timeout_and_nonnegative_threshold():
    with pytest.raises(ValueError, match="requires remaining-leg timeout"):
        config(enable_remaining_leg_timeout_after_first_sl=False,
               enable_remaining_leg_timeout_profit_extension=True)
    with pytest.raises(ValueError, match="remaining_leg_timeout_profit_threshold_r"):
        config(remaining_leg_timeout_profit_threshold_r=-1)


def test_checkpoint_reentry_gate_releases_for_entry_on_virtual_boundary_candle():
    data = strategy([
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 100, 89, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 49, 50),
        (50, 51, 49, 50),
        (50, 51, 49, 50),
    ])
    trades = BacktestEngine(
        data,
        config(
            use_intrabar_data=False,
            remaining_leg_timeout_after_first_sl_minutes=15,
            enable_reentry_gate_after_remaining_leg_timeout=True,
        ),
    ).run()

    assert len(trades) == 2
    first, replacement = trades.iloc[0], trades.iloc[1]
    assert first.checkpoint_reentry_gate_started
    assert first.checkpoint_reentry_gate_side == "SHORT"
    assert first.checkpoint_reentry_gate_release_reason == "TP"
    assert first.checkpoint_reentry_gate_release_time == pd.Timestamp("2024-01-01 01:15", tz="UTC")
    assert replacement.strategy_candle_open_time == pd.Timestamp("2024-01-01 01:15", tz="UTC")
    assert replacement.strategy_entry_time == pd.Timestamp("2024-01-01 01:30", tz="UTC")
    stats = summarize(trades)
    assert stats["checkpoint_reentry_gates_started"] == 1
    assert stats["checkpoint_reentry_gates_released_by_tp"] == 1


def test_checkpoint_reentry_gate_requires_timeout():
    with pytest.raises(ValueError, match="checkpoint re-entry gate"):
        config(
            enable_remaining_leg_timeout_after_first_sl=False,
            enable_reentry_gate_after_remaining_leg_timeout=True,
        )


def test_checkpoint_score_extends_when_required_conditions_pass():
    rows = (
        [(100, 100, 100, 100), (100, 100, 89, 100)]
        + [(100, 101, 99, 100)] * 4
        + [(80, 81, 79, 80), (80, 81, 49, 50)]
        + [(50, 51, 49, 50)] * 22
    )
    row = BacktestEngine(
        quiet_strategy(),
        config(
            enable_remaining_leg_checkpoint_score_extension=True,
            checkpoint_score_use_profit=True,
            checkpoint_score_min_profit_r=2,
            checkpoint_score_use_atr_pct=False,
            checkpoint_score_use_directional_di=False,
            checkpoint_score_use_bb_width_pct=False,
            checkpoint_score_min_conditions=1,
        ),
        intrabar(rows),
    ).run().iloc[0]
    assert row.short_exit_reason == "TP"
    assert row.remaining_leg_timeout_extension_count == 1
    assert row.checkpoint_score_last_pass_count == 1
    assert row.checkpoint_score_last_condition_count == 1
    assert row.checkpoint_score_last_passed


def test_intrabar_checkpoint_maps_to_strategy_indicator_index():
    rows = (
        [(100, 100, 100, 100), (100, 100, 89, 100)]
        + [(100, 101, 99, 100)] * 4
        + [(80, 81, 79, 80), (80, 81, 49, 50)]
        + [(50, 51, 49, 50)] * 22
    )
    row = BacktestEngine(
        quiet_strategy(),
        config(
            enable_remaining_leg_checkpoint_score_extension=True,
            checkpoint_score_use_profit=False,
            checkpoint_score_use_atr_pct=True,
            checkpoint_score_max_atr_pct=1,
            checkpoint_score_use_directional_di=False,
            checkpoint_score_use_bb_width_pct=False,
            checkpoint_score_min_conditions=1,
        ),
        intrabar(rows),
    ).run().iloc[0]

    assert row.short_exit_reason == "TP"
    assert row.remaining_leg_timeout_extension_count == 1
    assert row.checkpoint_score_last_atr_pct == pytest.approx(0)
    assert row.checkpoint_score_last_passed


def test_checkpoint_score_rejects_ambiguous_extension_configuration():
    with pytest.raises(ValueError, match="either profit-only extension or checkpoint score"):
        config(
            enable_remaining_leg_timeout_profit_extension=True,
            enable_remaining_leg_checkpoint_score_extension=True,
        )


def test_first_sl_partial_realizes_configured_survivor_fraction_and_keeps_remainder():
    rows = [(100, 100, 100, 100), (100, 100, 89, 100), (100, 101, 49, 50)] + [(50, 51, 49, 50)] * 27
    row = BacktestEngine(
        quiet_strategy(),
        config(enable_first_sl_survivor_partial_close=True, first_sl_survivor_partial_close_pct=25),
        intrabar(rows),
    ).run().iloc[0]
    assert row.first_sl_survivor_partial_taken
    assert row.first_sl_survivor_partial_side == "SHORT"
    assert row.first_sl_survivor_partial_pct == 25
    assert row.first_sl_survivor_partial_quantity == pytest.approx(.25)
    assert row.first_sl_survivor_partial_gross_pnl == pytest.approx(2.5)
    assert row.short_quantity == pytest.approx(.75)
    assert row.pair_gross_pnl == pytest.approx(30)


def test_two_consecutive_zero_scores_recheck_then_close():
    data = strategy([(100,100,100,100), (100,100,89,100), (96,101,95,96), (95,100,94,95), (95,96,94,95)])
    row = BacktestEngine(
        data,
        config(
            use_intrabar_data=False,
            remaining_leg_timeout_after_first_sl_minutes=5,
            enable_remaining_leg_checkpoint_score_extension=True,
            checkpoint_score_use_profit=True,
            checkpoint_score_min_profit_r=.85,
            checkpoint_score_use_atr_pct=False,
            checkpoint_score_use_directional_di=False,
            checkpoint_score_use_bb_width_pct=False,
            checkpoint_score_min_conditions=1,
            enable_checkpoint_zero_score_confirmation=True,
            checkpoint_zero_score_confirmations_required=2,
            checkpoint_zero_score_recheck_minutes=5,
        ),
    ).run().iloc[0]
    assert row.remaining_leg_timeout_triggered
    assert row.remaining_leg_timeout_checkpoint_count == 2
    assert row.remaining_leg_timeout_extension_count == 1
    assert row.checkpoint_zero_score_max_streak == 2
    assert row.checkpoint_zero_score_confirmed_close
    assert row.remaining_leg_timeout_exit_time == pd.Timestamp("2024-01-01 00:45", tz="UTC")
