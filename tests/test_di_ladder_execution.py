import pandas as pd
import pytest

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.enhanced_config import (
    build_enhanced_backtest_config,
    enhanced_default_gui_config,
)


def _strategy_candles():
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
            "open": [100.0, 100.0],
            "high": [100.0, 112.0],
            "low": [100.0, 88.0],
            "close": [100.0, 100.0],
            "volume": [1.0, 1.0],
        }
    )


def _intrabar(rows):
    start = pd.Timestamp("2024-01-01 00:15:00", tz="UTC")
    padded = list(rows)
    while len(padded) < 15:
        last = padded[-1][3] if padded else 100.0
        padded.append((last, last, last, last))
    return pd.DataFrame(
        {
            "timestamp": [start + pd.Timedelta(minutes=i) for i in range(15)],
            "open": [row[0] for row in padded],
            "high": [row[1] for row in padded],
            "low": [row[2] for row in padded],
            "close": [row[3] for row in padded],
            "volume": [1.0] * 15,
        }
    )


def _config(*, layers=None):
    values = enhanced_default_gui_config()
    values.update(
        {
            "strategy_timeframe_minutes": 15,
            "intrabar_timeframe_minutes": 1,
            "use_intrabar_data": True,
            "telemetry_interval_minutes": 15,
            "risk_mode": "FIXED",
            "fixed_r": 10.0,
            "initial_equity": 1000.0,
            "risk_per_leg": 0.05,
            "maker_fee": 0.0,
            "taker_fee": 0.0,
            "slippage": 0.0,
            "max_effective_leverage_per_leg": None,
            "max_combined_effective_leverage": None,
            "entry_mode": "WAIT_UNTIL_CLOSED",
            "entry_timing_mode": "SIGNAL_CLOSE",
            "tie_policy": "PESSIMISTIC",
            "enable_trade_telemetry": False,
            "di_ladder_enabled": True,
            "di_ladder_level_r": 0.20,
        }
    )
    if layers is not None:
        values["di_ladder_layers"] = tuple(layers)
    for profile in values["strategy_profiles"].values():
        profile.update(
            {
                "enabled": True,
                "flip_direction": False,
                "entry_rules": [],
                "stop_loss_multiple": 1.0,
                "reward_risk_ratio": 0.20,
                "risk_multiplier": 1.0,
                "position_sizing_stop_override_enabled": False,
                "partial_stop_enabled": False,
                "partial_profit_enabled": False,
                "break_even_enabled": False,
                "trailing_enabled": False,
                "r_step_trailing_enabled": False,
                "atr_checkpoint_tp_extension_enabled": False,
                "timeout_enabled": False,
            }
        )
    return build_enhanced_backtest_config(values, require_paths=False)


def _engine(intrabar, *, direction="LONG", config=None):
    engine = BacktestEngine(_strategy_candles(), config or _config(), intrabar)
    engine.market_regime_values[:] = "SIDEWAYS"
    if direction == "LONG":
        engine.plus_di_values[:] = 50.0
        engine.minus_di_values[:] = 10.0
    else:
        engine.plus_di_values[:] = 10.0
        engine.minus_di_values[:] = 50.0
    engine.di_spread[:] = 40.0
    engine.adx_values[:] = 25.0
    return engine


def test_di_ladder_direct_initial_tp_opens_no_children():
    trades = _engine(_intrabar([(100, 102, 100, 102)])).run()

    assert len(trades) == 1
    row = trades.iloc[0]
    assert row.ladder_layer == "INITIAL"
    assert row.ladder_episode_trade_count == 1
    assert row.ladder_deepest_reached_level == pytest.approx(0.0)
    assert row.ladder_episode_gross_pnl == pytest.approx(10.0)
    assert row.ladder_episode_net_pnl == pytest.approx(10.0)


def test_di_ladder_s1_reversal_is_plus_10_minus_20():
    trades = _engine(
        _intrabar(
            [
                (100, 100, 98, 98),
                (98, 102, 98, 102),
            ]
        )
    ).run()

    assert list(trades.ladder_layer) == ["INITIAL", "S1"]
    s1 = trades.loc[trades.ladder_layer == "S1"].iloc[0]
    assert s1.ladder_frozen_quantity == pytest.approx(5.0)
    assert s1.pair_gross_pnl == pytest.approx(-20.0)
    assert trades.iloc[0].pair_gross_pnl == pytest.approx(10.0)
    assert trades.iloc[0].ladder_episode_gross_pnl == pytest.approx(-10.0)


def test_di_ladder_full_adverse_path_reduces_five_level_loss_to_one_level():
    trades = _engine(
        _intrabar(
            [
                (100, 100, 98, 98),
                (98, 98, 96, 96),
                (96, 96, 94, 94),
                (94, 94, 92, 92),
                (92, 92, 90, 90),
            ]
        )
    ).run()

    assert list(trades.ladder_layer) == ["INITIAL", "S1", "S2", "S3", "S4"]
    initial = trades.loc[trades.ladder_layer == "INITIAL"].iloc[0]
    children = trades[trades.ladder_is_child]
    assert initial.pair_gross_pnl == pytest.approx(-50.0)
    assert list(children.pair_gross_pnl) == pytest.approx([10.0, 10.0, 10.0, 10.0])
    assert initial.ladder_episode_gross_pnl == pytest.approx(-10.0)
    assert initial.ladder_deepest_reached_level == pytest.approx(-4.0)


def test_skipping_s1_then_continuing_makes_the_later_reversal_10_dollars_worse():
    layers = [
        {
            "name": "S1",
            "enabled": True,
            "entry_level": -1.0,
            "target_level": -2.0,
            "stop_level": 1.0,
            "filter_match_mode": "ALL",
            "entry_rules": [
                {
                    "indicator": "ADX",
                    "condition": "INSIDE",
                    "minimum": 999.0,
                    "maximum": 1000.0,
                }
            ],
        },
        {
            "name": "S2",
            "enabled": True,
            "entry_level": -2.0,
            "target_level": -3.0,
            "stop_level": 1.0,
            "filter_match_mode": "ALL",
            "entry_rules": [],
        },
    ]
    engine = _engine(
        _intrabar(
            [
                (100, 100, 98, 98),
                (98, 98, 96, 96),
                (96, 102, 96, 102),
            ]
        ),
        config=_config(layers=layers),
    )
    trades = engine.run()

    assert list(trades.ladder_layer) == ["INITIAL", "S2"]
    initial = trades.loc[trades.ladder_layer == "INITIAL"].iloc[0]
    s2 = trades.loc[trades.ladder_layer == "S2"].iloc[0]
    assert initial.pair_gross_pnl == pytest.approx(10.0)
    assert s2.pair_gross_pnl == pytest.approx(-30.0)
    assert initial.ladder_episode_gross_pnl == pytest.approx(-20.0)

    ladder_skips = [
        row for row in engine.skipped_signals
        if row.get("ladder_layer") == "S1"
    ]
    assert len(ladder_skips) == 1
    episode = engine._di_ladder_episode_history[int(initial.ladder_episode_id)]
    s1_state = next(layer for layer in episode["layers"] if layer["name"] == "S1")
    assert s1_state["skip_outcome"] == "WRONG_CONTINUATION"


def test_di_ladder_mirrors_for_initial_short():
    trades = _engine(
        _intrabar(
            [
                (100, 102, 100, 102),
                (102, 104, 102, 104),
                (104, 106, 104, 106),
                (106, 108, 106, 108),
                (108, 110, 108, 110),
            ]
        ),
        direction="SHORT",
    ).run()

    initial = trades.loc[trades.ladder_layer == "INITIAL"].iloc[0]
    children = trades[trades.ladder_is_child]
    assert initial.side == "SHORT"
    assert set(children.side) == {"LONG"}
    assert initial.pair_gross_pnl == pytest.approx(-50.0)
    assert list(children.pair_gross_pnl) == pytest.approx([10.0, 10.0, 10.0, 10.0])
    assert initial.ladder_episode_gross_pnl == pytest.approx(-10.0)
