import os
import sys

import pytest

from config import BacktestConfig
from gui.config_logic import load_config_json, save_config_json

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication

from gui.main_window import MainWindow


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


def test_di_strategy_controls_have_a_dedicated_tab():
    app()
    window = MainWindow()
    try:
        tab_names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        assert tab_names[:3] == ["Configuration", "DI Direction Strategy", "Summary"]
        di_page = window.tabs.widget(tab_names.index("DI Direction Strategy"))
        assert di_page.isAncestorOf(window.enable_di_direction_sizing)
        assert di_page.isAncestorOf(window.di_long_reward_risk_ratio)
        assert di_page.isAncestorOf(window.enable_directional_adx_filter)
        assert di_page.isAncestorOf(window.enable_bull_regime_short_filter)
        assert di_page.isAncestorOf(window.enable_bull_long_conditional_reward_risk)
    finally:
        window.close()


def test_gui_default_atr_period_matches_backtest_config():
    app()
    window = MainWindow()
    try:
        assert window.atr_period.value() == BacktestConfig().atr_period == 14
        window.atr_period.setValue(7)
        window.reset_defaults()
        assert window.atr_period.value() == BacktestConfig().atr_period == 14
    finally:
        window.close()


def test_partial_stop_disables_ignored_core_stop_control():
    app()
    window = MainWindow()
    try:
        assert window.sl.isEnabled()
        window.enable_partial_sl.setChecked(True)
        assert not window.sl.isEnabled()
        window.enable_partial_sl.setChecked(False)
        assert window.sl.isEnabled()
    finally:
        window.close()


def test_partial_take_profit_disables_ignored_core_controls_and_calculates_remainder():
    app()
    window = MainWindow()
    try:
        window.enable_partial_tp.setChecked(True)
        assert not window.sl.isEnabled()
        assert not window.tp.isEnabled()
        window.tp1_close_pct.setValue(65)
        assert window.tp2_close_pct.value() == pytest.approx(35)
        assert not window.tp2_close_pct.isEnabled()

        assert window.tp2_r.isEnabled()
        assert window.enable_trailing_profit.isEnabled()
        window.enable_trailing_profit.setChecked(True)
        window.trail_activation_trigger.setCurrentText("AFTER_TP1")
        assert not window.trail_activation_r.isEnabled()
        assert window.trail_distance_r.isEnabled()
        assert "fixed TP2 and SL2 stay active" in window.trailing_help.text()
    finally:
        window.close()


def test_partial_take_profit_and_partial_stop_loss_can_be_enabled_together():
    app()
    window = MainWindow()
    try:
        window.enable_partial_tp.setChecked(True)
        window.enable_partial_sl.setChecked(True)
        assert window.enable_partial_tp.isChecked()
        assert window.enable_partial_sl.isChecked()
        assert not window.stop_loss_r.isEnabled()
        assert window.enable_trailing_profit.isEnabled()
        assert window.sl1_r.isEnabled()
        assert window.tp1_r.isEnabled()
        assert "ladder remains active" in window.protective_stop_help.text()

        window.after_tp1_stop_mode.setCurrentText("MOVE_TO_ENTRY")
        assert "replaced by one stop at the entry price" in window.protective_stop_help.text()
    finally:
        window.close()


def test_strategy_and_intrabar_timeframe_controls_default_and_update():
    app()
    window = MainWindow()
    try:
        assert [window.strategy_timeframe.itemText(i) for i in range(window.strategy_timeframe.count())] == ["1m", "5m", "15m", "30m", "1h", "4h"]
        assert window.strategy_timeframe.currentText() == "15m"
        assert window.intrabar_timeframe.currentText() == "1m"
        assert window.use_intrabar.isChecked()
        assert window.values()["strategy_timeframe_minutes"] == 15
        assert window.values()["intrabar_timeframe_minutes"] == 1

        window.strategy_timeframe.setCurrentText("1h")
        window.intrabar_timeframe.setCurrentText("5m")
        assert window.values()["strategy_timeframe_minutes"] == 60
        assert window.values()["intrabar_timeframe_minutes"] == 5

        window.strategy_timeframe.setCurrentText("1m")
        assert not window.use_intrabar.isChecked()
        assert not window.use_intrabar.isEnabled()
        assert window.values()["use_intrabar_data"] is False
    finally:
        window.close()


def test_saved_and_loaded_gui_config_preserves_atr_period(tmp_path):
    path = tmp_path / "backtest_config.json"
    save_config_json(path, {"atr_period": 21})

    app()
    window = MainWindow()
    try:
        window.apply_values(load_config_json(path))
        assert window.atr_period.value() == 21
        assert window.values()["atr_period"] == 21
    finally:
        window.close()


def test_entry_filter_controls_save_and_load(tmp_path):
    path = tmp_path / "entry-filters.json"
    app()
    window = MainWindow()
    try:
        assert window.bb_width_min.value() == pytest.approx(0.012)
        assert not window.skip_monday_entries.isChecked()
        assert not window.skip_monday_timezone.isEnabled()

        window.enable_bb_width.setChecked(True)
        window.bb_width_mode.setCurrentText("Minimum Width")
        window.bb_width_min.setValue(0.012)
        window.skip_monday_entries.setChecked(True)
        window.skip_monday_timezone.setText("UTC")
        values = window.values()
        save_config_json(path, values)

        window.reset_defaults()
        window.apply_values(load_config_json(path))
        assert window.enable_bb_width.isChecked()
        assert window.bb_width_mode.currentText() == "Minimum Width"
        assert window.bb_width_min.value() == pytest.approx(0.012)
        assert window.skip_monday_entries.isChecked()
        assert window.skip_monday_timezone.text() == "UTC"
        assert window.skip_monday_timezone.isEnabled()
    finally:
        window.close()


def test_gui_reset_restores_all_default_values_and_run_name():
    from gui.config_logic import default_gui_config, format_percentage

    app()
    window = MainWindow()
    defaults = default_gui_config()
    try:
        window.apply_values({
            "run_name": "custom",
            "atr_period": 7,
            "atr_multiplier": 2.5,
            "sl_mult": 9,
            "tp_mult": 10,
            "initial_equity": 555,
            "risk_per_leg": 0.123,
            "maker_fee": 0.1,
            "taker_fee": 0.2,
            "slippage": 0.3,
            "strategy_timeframe_minutes": 99,
            "intrabar_timeframe_minutes": 3,
            "use_intrabar_data": False,
        })
        assert window.values()["run_name"] == "custom"

        window.reset_defaults()
        values = window.values()

        for key in [
            "run_name", "input_csv", "strategy_csv", "intrabar_csv", "use_intrabar_data",
            "output_dir", "sl_mult", "tp_mult", "entry_mode", "entry_interval",
            "max_active_pairs", "tie_policy", "risk_mode", "atr_period", "atr_multiplier",
            "trading_start_date", "trading_end_date", "max_effective_leverage_per_leg",
            "max_combined_effective_leverage", "intrabar_missing_policy", "zero_cost_comparison",
            "percent_r", "fixed_r", "initial_equity", "risk_per_leg", "maker_fee",
            "taker_fee", "use_maker_entry", "use_maker_exit", "slippage",
        ]:
            assert values[key] == defaults[key]

        assert window.atr_period.value() == 14
        assert window.atr_mult.value() == 1.0
        assert window.sl.value() == 2.0
        assert window.tp.value() == 3.0
        assert window.equity.value() == 1000
        assert window.risk_leg.text() == format_percentage(0.005)
        assert window.maker.text() == format_percentage(0.0002)
        assert window.taker.text() == format_percentage(0.0005)
        assert window.slippage.text() == format_percentage(0.0001)
        assert values["use_intrabar_data"] is True
    finally:
        window.close()


def test_remaining_leg_timeout_gui_hours_save_load_round_trip(tmp_path):
    path = tmp_path / "timeout.json"
    app()
    window = MainWindow()
    try:
        assert not window.remaining_leg_timeout.isChecked()
        assert not window.remaining_leg_timeout_duration.isEnabled()
        window.remaining_leg_timeout.setChecked(True)
        window.remaining_leg_timeout_unit.setCurrentText("Hours")
        window.remaining_leg_timeout_duration.setValue(4)
        window.remaining_leg_timeout_profit_extension.setChecked(True)
        window.remaining_leg_timeout_profit_threshold_r.setValue(10)
        window.reentry_gate_after_timeout.setChecked(True)
        values = window.values()
        assert values["remaining_leg_timeout_after_first_sl_minutes"] == 240
        assert values["enable_remaining_leg_timeout_profit_extension"] is True
        assert values["remaining_leg_timeout_profit_threshold_r"] == 10
        assert values["enable_reentry_gate_after_remaining_leg_timeout"] is True
        save_config_json(path, values)
        window.apply_values(load_config_json(path))
        assert window.remaining_leg_timeout.isChecked()
        assert window.remaining_leg_timeout_unit.currentText() == "Hours"
        assert window.remaining_leg_timeout_duration.value() == 4
        assert window.remaining_leg_timeout_profit_extension.isChecked()
        assert window.remaining_leg_timeout_profit_threshold_r.value() == 10
        assert window.reentry_gate_after_timeout.isChecked()

        window.remaining_leg_timeout_profit_extension.setChecked(False)
        window.checkpoint_score_extension.setChecked(True)
        window.first_sl_survivor_partial.setChecked(True)
        window.first_sl_survivor_partial_pct.setValue(25)
        window.zero_score_confirmation.setChecked(True)
        window.zero_score_confirmations.setValue(2)
        window.zero_score_recheck_unit.setCurrentText("Hours")
        window.zero_score_recheck_duration.setValue(2)
        score_values = window.values()
        assert score_values["enable_remaining_leg_checkpoint_score_extension"] is True
        assert score_values["checkpoint_score_min_conditions"] == 3
        assert score_values["checkpoint_score_max_atr_pct"] == pytest.approx(0.08)
        assert score_values["enable_first_sl_survivor_partial_close"] is True
        assert score_values["first_sl_survivor_partial_close_pct"] == 25
        assert score_values["enable_checkpoint_zero_score_confirmation"] is True
        assert score_values["checkpoint_zero_score_confirmations_required"] == 2
        assert score_values["checkpoint_zero_score_recheck_minutes"] == 120
    finally:
        window.close()
