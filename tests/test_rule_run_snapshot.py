from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest

from crypto_strategy_lab.strategy_rule_model import new_rule


def _window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.setup_main_window import MainWindow

    app = widgets.QApplication.instance() or widgets.QApplication([])

    class Catalog:
        def symbols(self):
            return ["BTCUSDT"]

        def inventory(self, *_args):
            return []

        def coverage(self, request):
            base = {
                "dataset": "klines",
                "first_period": datetime(2019, 1, 1, tzinfo=timezone.utc),
                "last_period": datetime(2027, 1, 1, tzinfo=timezone.utc),
                "archive_count": 1,
                "state": "AVAILABLE",
            }
            rows = [
                {**base, "interval": request.strategy_timeframe},
            ]
            if request.intrabar_timeframe:
                rows.append({**base, "interval": request.intrabar_timeframe})
            return rows

    class Service:
        catalog = Catalog()

        def refresh_catalog(self):
            return 0

    window = MainWindow(service=Service())
    window._validation_debounce.stop()
    return app, window


def _bull_long_builder_rules(config):
    return tuple(
        rule
        for rule in config.strategy.profiles["bull_long"].entry_rules
        if "_builder_id" in rule
    )


def _bull_veto():
    rule = new_rule(kind="VETO", evidence="MR_STATE")
    rule.update(
        operator="IS",
        value="ABOVE_MEAN",
        regime="BULL",
        side="LONG",
        group_name="Regression veto",
    )
    return rule


def test_rule_add_then_remove_builds_fresh_second_run_snapshot():
    _app, window = _window()
    try:
        table = window.rule_builder.veto_rules
        table.set_rules((_bull_veto(),))

        _request1, config1 = window._capture_run_snapshot()
        assert len(_bull_long_builder_rules(config1)) == 1

        table.selectRow(0)
        table.remove_selected()
        assert table.rowCount() == 0
        assert table.rules() == ()

        _request2, config2 = window._capture_run_snapshot()
        assert _bull_long_builder_rules(config2) == ()
        assert config2 != config1
    finally:
        window.close()


def test_ruleless_then_add_rule_builds_fresh_second_run_snapshot():
    _app, window = _window()
    try:
        table = window.rule_builder.veto_rules
        table.set_rules(())

        _request1, config1 = window._capture_run_snapshot()
        assert _bull_long_builder_rules(config1) == ()

        table.set_rules((_bull_veto(),))
        _request2, config2 = window._capture_run_snapshot()
        assert len(_bull_long_builder_rules(config2)) == 1
        assert config2 != config1
    finally:
        window.close()


def test_two_consecutive_launches_receive_their_exact_current_rule_snapshots():
    _app, window = _window()
    launched = []
    try:
        window._start_run_snapshot = (
            lambda request, config: launched.append((request, config))
        )
        table = window.rule_builder.veto_rules

        table.set_rules((_bull_veto(),))
        request1, config1 = window._capture_run_snapshot()
        window._set_pending_run_snapshot(request1, config1)
        assert window._launch_pending_run_snapshot()
        assert len(_bull_long_builder_rules(launched[-1][1])) == 1

        table.set_rules(())
        request2, config2 = window._capture_run_snapshot()
        window._set_pending_run_snapshot(request2, config2)
        assert window._launch_pending_run_snapshot()
        assert _bull_long_builder_rules(launched[-1][1]) == ()

        table.set_rules((_bull_veto(),))
        request3, config3 = window._capture_run_snapshot()
        window._set_pending_run_snapshot(request3, config3)
        assert window._launch_pending_run_snapshot()
        assert len(_bull_long_builder_rules(launched[-1][1])) == 1

        assert [item[1] for item in launched] == [config1, config2, config3]
    finally:
        window.close()


def test_config_edit_during_validation_never_silently_runs_stale_or_new_rules():
    _app, window = _window()
    launched = []
    try:
        window._start_run_snapshot = (
            lambda request, config: launched.append((request, config))
        )
        table = window.rule_builder.veto_rules
        table.set_rules((_bull_veto(),))
        request, config = window._capture_run_snapshot()
        window._set_pending_run_snapshot(request, config)

        # The visible authoring changes while validation is still in flight.
        table.set_rules(())

        assert not window._launch_pending_run_snapshot()
        assert launched == []
        assert window._pending_run_snapshot is None
        assert "changed while validation was running" in window.range_validation.text()
    finally:
        window.close()


def test_run_pressed_during_background_validation_freezes_visible_rule_snapshot():
    _app, window = _window()
    try:
        table = window.rule_builder.veto_rules
        table.set_rules((_bull_veto(),))

        # Reproduce Setup's normal state when automatic candle validation is
        # already underway and the researcher presses Run.
        window._validation_thread = object()
        window.start_run()

        assert window._validation_auto_run is True
        assert window._pending_run_snapshot is not None
        _request, config = window._pending_run_snapshot
        assert len(_bull_long_builder_rules(config)) == 1
    finally:
        window._validation_thread = None
        window.close()
