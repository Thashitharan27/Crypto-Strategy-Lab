from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from crypto_strategy_lab.config import BacktestConfig, EntryTimingMode
from crypto_strategy_lab.data_lake_config import ExecutionConfig, ResearchRunConfig
from crypto_strategy_lab.engine import BacktestEngine
from crypto_strategy_lab.rule_native_engine import RuleAwareDataLakeProductionBacktestEngine
from crypto_strategy_lab.sr_dynamic_tp_engine import SRDynamicTPBacktestEngine


def test_entry_timing_defaults_preserve_historical_signal_close():
    assert BacktestConfig().entry_timing_mode == EntryTimingMode.SIGNAL_CLOSE
    assert ExecutionConfig().entry_timing_mode == "SIGNAL_CLOSE"
    config = ResearchRunConfig(execution=ExecutionConfig(entry_timing_mode="NEXT_CANDLE_OPEN"))
    config.validate()


def test_next_open_decision_defers_one_strategy_candle_without_reading_price():
    engine = object.__new__(BacktestEngine)
    engine.config = SimpleNamespace(enable_daily_entry_schedule=False, entry_timing_mode="NEXT_CANDLE_OPEN")
    engine.times = np.array([
        np.datetime64("2026-01-01T00:00"),
        np.datetime64("2026-01-01T00:05"),
        np.datetime64("2026-01-01T00:10"),
    ])
    engine._should_enter = lambda i: i == 1
    decision = BacktestEngine._entry_decision(engine, 1, False)
    assert decision["indicator_index"] == 1
    assert decision["execution_index"] == 2
    assert decision["defer_to_next_open"] is True
    assert decision["actual_entry_timestamp"] is None
    assert decision["fill_price_source"] == "NEXT_CANDLE_OPEN"


def test_structural_geometry_uses_execution_candle_open_for_deferred_entry():
    engine = object.__new__(SRDynamicTPBacktestEngine)
    engine.config = SimpleNamespace(enable_daily_entry_schedule=False, slippage=0.001)
    engine.close = np.array([100.0, 101.0])
    engine.open = np.array([99.0, 110.0])
    assert engine._expected_entry_price(0, 1, "LONG") == 110.0 * 1.001
    assert engine._expected_entry_price(0, 1, "SHORT") == 110.0 * 0.999


def test_ema_next_open_gap_through_micro_swing_stop_is_rejected_explicitly():
    engine = object.__new__(RuleAwareDataLakeProductionBacktestEngine)
    engine.config = SimpleNamespace(strategy_timeframe_minutes=5, slippage=0.0, enable_daily_entry_schedule=False)
    engine.open = np.full(12, 110.0)
    engine.open[11] = 98.0
    engine.close = np.full(12, 110.0)
    engine.high = np.full(12, 111.0)
    engine.low = np.full(12, 109.0)
    engine.atr_values = np.full(12, 2.0)
    engine._effective_trade_direction = lambda _i: "LONG"
    engine._latest_confirmed_micro_swing = lambda _i, _direction: (7, 100.0)
    plan = engine._ema_920_micro_swing_stop_plan(10, 11)
    assert plan["passed"] is False
    assert plan["reason"] == "ENTRY_INVALIDATED_GAP_THROUGH_STOP"
    assert plan["stop_price"] == 99.9


def test_queued_next_open_entry_is_opened_before_execution_candle_is_processed():
    events = []

    class Probe(BacktestEngine):
        def __init__(self):
            self.config = SimpleNamespace(
                enable_daily_entry_schedule=False,
                entry_timing_mode="NEXT_CANDLE_OPEN",
                max_active_pairs=1,
            )
            self.times = np.array([
                np.datetime64("2026-01-01T00:00"),
                np.datetime64("2026-01-01T00:05"),
            ])
            self.active_pairs = []
            self.completed_pairs = []
            self.pending_next_open_entry = None
            self.signals_evaluated = 0
            self.progress_interval = 50
            self.next_pair_id = 1

        def _should_enter(self, i):
            return i == 0

        def _entry_filter_result(self, indicator_i, execution_i=None):
            events.append(("filter", indicator_i, execution_i))
            return True, "passed"

        def _open_pair(self, i, entry_filter_passed=True, entry_filter_reason="", schedule=None):
            events.append(("open", i, schedule["indicator_index"]))
            self.active_pairs.append(object())

        def _update_positions_to_strategy_index(self, i):
            events.append(("update", i, bool(self.active_pairs)))

        def _record_active_telemetry(self, _i):
            return None

        def _collect_closed_pairs(self, force=False):
            return None

        def _record_skipped_signal(self, i, reason):
            events.append(("skip", i, reason))

        def _force_close_end(self):
            return None

        def _emit_progress(self, *_args):
            return None

        def results_frame(self):
            return pd.DataFrame()

    Probe().run()
    open_position = events.index(("open", 1, 0))
    process_execution_candle = events.index(("update", 1, True))
    assert open_position < process_execution_candle


def test_rule_gui_user_selection_applies_ema_next_open_default_without_forcing_loaded_configs(monkeypatch):
    import os
    import pytest

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.rule_main_window import MainWindow

    app = widgets.QApplication.instance() or widgets.QApplication([])

    class Catalog:
        def symbols(self): return ["BTCUSDT"]
        def coverage(self, _request): return []

    class Service:
        catalog = Catalog()
        def refresh_catalog(self): return 0

    window = MainWindow(service=Service())
    try:
        timing = window.execution_form.widgets["entry_timing_mode"]
        selector = window.rule_builder.direction_mode
        assert timing.currentData() == "SIGNAL_CLOSE"

        ema_index = selector.findData("EMA_9_20_PULLBACK")
        selector.setCurrentIndex(ema_index)
        # Programmatic selection models config loading: no user-activation default.
        assert timing.currentData() == "SIGNAL_CLOSE"
        selector.activated.emit(ema_index)
        assert timing.currentData() == "NEXT_CANDLE_OPEN"

        di_index = selector.findData("DI")
        selector.setCurrentIndex(di_index)
        selector.activated.emit(di_index)
        assert timing.currentData() == "SIGNAL_CLOSE"
    finally:
        window.close()
        _ = app
