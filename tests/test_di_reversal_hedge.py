import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.gui.enhanced_config import (
    build_enhanced_backtest_config,
    enhanced_default_gui_config,
)
from crypto_strategy_lab.trade import Position, Side, TradePair


def _strategy():
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="4h", tz="UTC"),
            "open": [100.0, 100.0],
            "high": [100.0, 100.0],
            "low": [100.0, 100.0],
            "close": [100.0, 100.0],
            "volume": [1.0, 1.0],
        }
    )


def _intrabar():
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=32, freq="15min", tz="UTC"),
            "open": [100.0] * 32,
            "high": [100.0] * 32,
            "low": [100.0] * 32,
            "close": [100.0] * 32,
            "volume": [1.0] * 32,
        }
    )


def _config():
    values = enhanced_default_gui_config()
    values.update(
        {
            "strategy_timeframe_minutes": 240,
            "intrabar_timeframe_minutes": 15,
            "use_intrabar_data": True,
            "telemetry_interval_minutes": 240,
            "risk_mode": "FIXED",
            "fixed_r": 10.0,
            "initial_equity": 1000.0,
            "maker_fee": 0.0,
            "taker_fee": 0.0,
            "slippage": 0.0,
            "max_effective_leverage_per_leg": None,
            "max_combined_effective_leverage": None,
            "entry_mode": "WAIT_UNTIL_CLOSED",
            "entry_timing_mode": "SIGNAL_CLOSE",
            "enable_trade_telemetry": False,
            "di_ladder_enabled": True,
            "di_ladder_mode": "DI_REVERSAL",
            "di_reversal_target_r": 0.20,
        }
    )
    for profile in values["strategy_profiles"].values():
        profile.update(
            {
                "enabled": True,
                "flip_direction": False,
                "entry_rules": [],
                "stop_loss_multiple": 1.0,
                "reward_risk_ratio": 1.0,
                "risk_multiplier": 1.0,
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


def _engine_with_parent():
    engine = BacktestEngine(_strategy(), _config(), _intrabar())
    engine.market_regime_values[:] = "SIDEWAYS"
    engine._di_reversal_plus = np.full(32, 10.0)
    engine._di_reversal_minus = np.full(32, 30.0)
    engine._di_reversal_plus[0] = 30.0
    engine._di_reversal_minus[0] = 10.0

    parent_pos = Position(
        side=Side.LONG,
        entry_time=pd.Timestamp("2026-01-01", tz="UTC"),
        entry_index=0,
        entry_price=100.0,
        risk=10.0,
        sl=90.0,
        tp=110.0,
        quantity=1.0,
        risk_amount=10.0,
        entry_notional=100.0,
        atr_at_entry=10.0,
        uncapped_quantity=1.0,
        effective_leverage=0.1,
        distance_unit=10.0,
        position_sizing_reference_distance=10.0,
        original_sl=90.0,
    )
    parent = TradePair(
        1,
        parent_pos,
        None,
        1000.0,
        pd.Timestamp("2026-01-01", tz="UTC"),
        pd.Timestamp("2026-01-01", tz="UTC"),
        100.0,
        False,
    )
    parent.trade_direction = "LONG"
    engine.active_pairs = [parent]
    engine.next_pair_id = 2
    engine._maybe_start_di_ladder_episode(parent, None)
    return engine, parent


def test_di_reversal_child_uses_parent_tp_as_one_r_stop_and_point_two_r_target():
    engine, parent = _engine_with_parent()
    episode = engine._di_ladder_episode

    engine._maybe_trigger_di_reversal(
        episode,
        execution_i=1,
        intrabar_i=2,
        timestamp=pd.Timestamp("2026-01-01 00:30:00", tz="UTC"),
        raw_open=100.0,
    )

    children = [
        pair for pair in engine.active_pairs
        if getattr(pair, "ladder_is_child", False)
    ]
    assert len(children) == 1
    child = children[0]
    pos = child.position

    assert child.signal_strategy_mode == "DI_REVERSAL_HEDGE"
    assert child.trade_direction == "SHORT"
    assert pos.sl == pytest.approx(parent.position.tp)
    assert pos.risk == pytest.approx(10.0)
    assert pos.risk_amount == pytest.approx(10.0)
    assert pos.quantity == pytest.approx(1.0)
    assert pos.tp == pytest.approx(98.0)
    assert (pos.entry_price - pos.tp) / pos.risk == pytest.approx(0.20)
    assert child.ladder_parent_progress_r == pytest.approx(0.0)


def test_di_reversal_requires_a_fresh_cross_and_does_not_repeat_same_di_state():
    engine, _parent = _engine_with_parent()
    episode = engine._di_ladder_episode

    # No cross: both completed 15m decisions are SHORT.
    engine._di_reversal_plus[0] = 10.0
    engine._di_reversal_minus[0] = 30.0
    engine._maybe_trigger_di_reversal(
        episode,
        execution_i=1,
        intrabar_i=2,
        timestamp=pd.Timestamp("2026-01-01 00:30:00", tz="UTC"),
        raw_open=100.0,
    )
    assert not any(getattr(pair, "ladder_is_child", False) for pair in engine.active_pairs)

    # Fresh parent-direction -> opposite-direction cross enters exactly once.
    engine._di_reversal_plus[0] = 30.0
    engine._di_reversal_minus[0] = 10.0
    engine._maybe_trigger_di_reversal(
        episode,
        execution_i=1,
        intrabar_i=2,
        timestamp=pd.Timestamp("2026-01-01 00:30:00", tz="UTC"),
        raw_open=100.0,
    )
    assert sum(bool(getattr(pair, "ladder_is_child", False)) for pair in engine.active_pairs) == 1

    # Same bearish state is not another fresh signal, and an open child blocks overlap.
    engine._maybe_trigger_di_reversal(
        episode,
        execution_i=1,
        intrabar_i=3,
        timestamp=pd.Timestamp("2026-01-01 00:45:00", tz="UTC"),
        raw_open=99.0,
    )
    assert sum(bool(getattr(pair, "ladder_is_child", False)) for pair in engine.active_pairs) == 1


def test_di_reversal_initializes_from_prepared_intrabar_execution_data():
    from crypto_strategy_lab.prepared_backtest import IntrabarExecutionData

    strategy = _strategy()
    raw = _intrabar()
    prepared_intrabar = IntrabarExecutionData(
        raw["timestamp"].to_numpy(),
        pd.Timedelta(minutes=15),
        raw["open"].to_numpy(float),
        raw["high"].to_numpy(float),
        raw["low"].to_numpy(float),
        raw["close"].to_numpy(float),
    )

    engine = BacktestEngine.__new__(BacktestEngine)
    engine.config = _config()
    engine.intrabar_data = prepared_intrabar

    # Must accept the array-backed production intrabar contract used by Data Lake.
    engine._initialize_di_ladder_state()

    assert engine._di_reversal_plus is not None
    assert engine._di_reversal_minus is not None
    assert len(engine._di_reversal_plus) == len(raw)
    assert len(engine._di_reversal_minus) == len(raw)


def test_di_reversal_parent_close_path_has_exit_reason_symbol_available():
    import crypto_strategy_lab.di_ladder as module

    assert module.ExitReason.PARENT_CLOSED.value == "PARENT_CLOSED"
