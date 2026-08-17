import json
import os
import sys
from dataclasses import replace

import pytest

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.gui.config_logic import load_config_json, save_config_json, validate_config_values

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication

from crypto_strategy_lab.gui.main_window import MainWindow, REPORT_TARGETS, report_button_states


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


def test_completion_sound_uses_system_notification(monkeypatch):
    calls=[]
    monkeypatch.setattr(QApplication,"beep",lambda: calls.append(True))
    MainWindow._play_completion_sound()
    assert calls == [True]


def test_completion_sound_failure_is_non_fatal(monkeypatch):
    def unavailable(): raise RuntimeError("No audio device")
    monkeypatch.setattr(QApplication,"beep",unavailable)
    MainWindow._play_completion_sound()


def test_missing_intrabar_policy_uses_friendly_labels_and_stable_values():
    app(); window=MainWindow()
    try:
        assert window.missing_policy.itemText(0)=="Use strategy candle for affected interval"
        assert window.missing_policy.currentText()=="WARN_AND_USE_15M"
        window.missing_policy.setCurrentText("ERROR")
        window.update_dynamic()
        assert window.missing_policy.itemText(window.missing_policy.currentIndex())=="Stop the run"
        assert window.values()["intrabar_missing_policy"]=="ERROR"
        assert "run stops" in window.data_help.text()
    finally: window.close()


def test_market_ready_tabs_use_profile_only_strategy_workflow():
    app()
    window = MainWindow()
    try:
        tab_names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        assert tab_names == ["Backtest Setup", "Direction Voting", "Support & Resistance", "Strategy Profiles", "Summary", "Portfolio", "Logs", "GitHub", "ChatGPT"]
        assert "Legacy Strategy" not in tab_names
        values=window.values()
        assert values["enable_strategy_profiles"] is True
        assert values["di_execution_mode"] == "PREFERRED_SIDE_ONLY"
    finally:
        window.close()


def test_profile_workspace_round_trip_includes_regime_definition(tmp_path):
    path=tmp_path/"profile.json"; app(); window=MainWindow()
    try:
        window.profile_editor.regime_lookback.setValue(60); window.profile_editor.bull_threshold.setValue(15); window.profile_editor.bear_threshold.setValue(-12)
        window.profile_editor.profiles["bull_long"]=replace(window.profile_editor.profiles["bull_long"],enabled=True,reward_risk_ratio=2.5,adx_enabled=True,adx_minimum=20,adx_maximum=45)
        save_config_json(path,window.values()); saved=json.loads(path.read_text())
        assert saved["enable_strategy_profiles"] is True
        assert "enable_directional_adx_filter" not in saved
        window.apply_values(load_config_json(path)); values=window.values()
        assert values["bull_regime_lookback_days"]==60
        assert values["bull_regime_return_threshold"]==pytest.approx(.15)
        assert values["strategy_profiles"]["bull_long"]["reward_risk_ratio"]==pytest.approx(2.5)
    finally: window.close()


def test_profile_trade_management_uses_one_switch_per_feature():
    app(); window=MainWindow()
    try:
        controls=window.profile_editor.controls
        assert "trailing_override" not in controls and "break_even_override" not in controls and "timeout_override" not in controls
        assert not controls["trailing_activation_r"].isEnabled()
        assert not controls["break_even_activation_r"].isEnabled()
        assert not controls["timeout_minutes"].isEnabled()
        controls["trailing_enabled"].setChecked(True); controls["break_even_enabled"].setChecked(True); controls["timeout_enabled"].setChecked(True)
        assert controls["trailing_activation_r"].isEnabled()
        assert controls["break_even_activation_r"].isEnabled()
        assert controls["timeout_minutes"].isEnabled()
    finally: window.close()


def test_profile_test_mode_help_explains_actual_execution():
    app(); window=MainWindow()
    try:
        editor=window.profile_editor
        editor.mode.setCurrentIndex(editor.mode.findData("ISOLATED_PROFILES"))
        assert "no shared-account run" in editor.mode_help.text()
        editor.mode.setCurrentIndex(editor.mode.findData("BOTH"))
        assert "shared account first" in editor.mode_help.text()
    finally: window.close()


def test_profile_editor_supports_unified_action_rules():
    app(); window=MainWindow()
    try:
        editor=window.profile_editor; editor.list.setCurrentRow(3)
        editor._add_entry_rule(rule={"action":"FLIP","indicator":"CLOSE_LOCATION","condition":"INSIDE","minimum":.45,"maximum":.68})
        editor._add_entry_rule(rule={"action":"REJECT","indicator":"ADX","condition":"OUTSIDE","minimum":10,"maximum":17})
        rules=editor.values()["strategy_profiles"]["bear_short"]["entry_rules"]
        assert len(rules)==2
        assert rules[0]=={"action":"FLIP","indicator":"CLOSE_LOCATION","condition":"INSIDE","minimum":.45,"maximum":.68}
        assert rules[1]=={"action":"REJECT","indicator":"ADX","condition":"OUTSIDE","minimum":10.0,"maximum":17.0}
        editor.entry_rules_table.selectRow(0); editor._remove_entry_rule()
        assert len(editor.values()["strategy_profiles"]["bear_short"]["entry_rules"])==1
    finally: window.close()


def test_profile_feature_details_follow_switches_and_rules_table_is_visible():
    app(); window=MainWindow()
    try:
        controls=window.profile_editor.controls
        form=window.profile_editor.control_forms["trailing_enabled"]
        assert form is window.profile_editor.control_forms["partial_profit_enabled"]
        assert form.parentWidget().title()=="Exit & Trade Management"
        assert form.getWidgetPosition(controls["trailing_activation_r"])[0] == form.getWidgetPosition(controls["trailing_enabled"])[0] + 1
        assert window.profile_editor.entry_rules_table.columnCount()==5
        assert window.profile_editor.add_rule_btn.text()=="+ Add rule"
    finally: window.close()


def test_analysis_presets_hide_advanced_controls_and_apply_expected_outputs():
    app(); window=MainWindow()
    try:
        assert window.analysis_level.currentText()=="Standard (Recommended)"
        assert window.enable_trade_telemetry.isHidden()
        assert window.save_indicator_reports.isChecked() and window.create_standard_charts.isChecked()
        window.analysis_level.setCurrentText("Fast")
        assert not window.save_indicator_reports.isChecked() and not window.create_standard_charts.isChecked()
        window.analysis_level.setCurrentText("Research")
        assert window.enable_trade_telemetry.isChecked() and window.enable_lifecycle.isChecked() and window.save_feature_reports.isChecked()
        window.analysis_advanced.setChecked(True)
        assert not window.enable_trade_telemetry.isHidden() and not window.enable_lifecycle.parentWidget().isHidden()
    finally: window.close()


def test_setup_separates_sizing_period_intrabar_and_cost_controls():
    app(); window=MainWindow()
    try:
        assert window.account_form.parentWidget().title()=="Account & Position Sizing"
        assert window.period_form.parentWidget().title()=="Backtest Period"
        assert window.intrabar_form.parentWidget().title()=="Intrabar Execution Rules"
        assert "Binance Market Data" in window.shared_data_note.text()
        assert window.market_symbol.currentText()=="XRPUSDT"
        assert window.risk_leg.text()=="1%"
        assert window.max_lev_leg.text()=="3.0"
        assert window.max_lev_combined.text()=="5.0"
        assert window.slippage.text()=="0.05%"
        assert "one trade (entry + final exit): 0.2%" in window.cost.text()
        window.maker_entry.setChecked(True); window.maker_exit.setChecked(True)
        assert "one trade (entry + final exit): 0.14%" in window.cost.text()
        assert window.zero_cost.parentWidget() is window.cost.parentWidget()
        assert window.account_form.labelForField(window.max_lev_leg).text()=="Maximum Leverage Per Trade"
        assert window.account_form.isRowVisible(window.atr_period)
        assert not window.account_form.isRowVisible(window.percent_r)
        window.risk_mode.setCurrentText("PERCENT")
        assert not window.account_form.isRowVisible(window.atr_period)
        assert window.account_form.isRowVisible(window.percent_r)
        assert not window.period_form.isRowVisible(window.trading_start)
        window.entire_dataset.setChecked(False)
        assert window.period_form.isRowVisible(window.trading_start)
        window.trading_start.setText("2024-01-01")
        assert window.values()["trading_start_date"]=="2024-01-01"
    finally: window.close()


def test_pair_and_timeframe_changes_select_matching_local_dataset(tmp_path):
    app(); window=MainWindow()
    try:
        strategy=tmp_path/"SOLUSDT_1h.csv"; intrabar=tmp_path/"SOLUSDT_1m.csv"
        strategy.write_text("timestamp,open,high,low,close,volume\n"); intrabar.write_text("timestamp,open,high,low,close,volume\n")
        window.market_data_folder=tmp_path
        window.market_symbol.setCurrentText("SOLUSDT"); window.strategy_timeframe.setCurrentText("1h"); window.intrabar_timeframe.setCurrentText("1m")
        assert window.input_csv.text()==str(strategy.resolve())
        assert window.intrabar_csv.text()==str(intrabar.resolve())
        window.market_symbol.setCurrentText("ETHUSDT")
        assert window.input_csv.text()=="" and window.intrabar_csv.text()==""
        assert "No matching dataset" in window.dataset_info.text()
        assert "Binance Data Hub" in window.dataset_info.text()
    finally: window.close()


def test_portfolio_tab_uses_dynamic_asset_rows():
    app()
    window = MainWindow()
    try:
        tab_names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        portfolio_page = window.tabs.widget(tab_names.index("Portfolio"))
        assert len(window.portfolio_assets)==4
        assert [row["pair"].currentText() for row in window.portfolio_assets]==["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
        assert all(portfolio_page.isAncestorOf(row["config"]) for row in window.portfolio_assets)
        assert window.portfolio_run_btn.text()=="Run Portfolio Backtest"
        assert window.portfolio_maximum_total_risk.text()=="5%"
        assert "approximately 4%" in window.portfolio_help.text()
        window._add_portfolio_asset("ADAUSDT"); assert len(window.portfolio_assets)==5
        window.portfolio_assets[-1]["enabled"].setChecked(False); assert "4 assets enabled" in window.portfolio_help.text()
        window._remove_portfolio_asset(window.portfolio_assets[-1]); assert len(window.portfolio_assets)==4
        assert window.portfolio_status.text()=="Select configurations for at least two enabled assets."
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


def test_direction_voting_defaults_to_runnable_di_only_config():
    app(); window=MainWindow()
    try:
        values=window.values()
        assert values["enable_direction_voting"] is True
        assert values["direction_vote_use_di"] is True
        assert values["direction_vote_minimum_votes"]==1
        assert values["direction_vote_use_structure"] is False
        assert values["direction_vote_use_momentum"] is False
        assert values["direction_vote_use_volume_pressure"] is False
        assert values["direction_vote_use_higher_timeframe"] is False
        assert window.direction_vote_test_mode.currentData()=="di"
        assert validate_config_values(values, require_paths=False)==[]
    finally:
        window.close()


def test_direction_voting_tab_only_shows_settings_that_affect_the_run():
    app(); window=MainWindow()
    try:
        form=window.direction_voting_form
        assert "DI pressure alone" in window.direction_vote_status.text()
        assert form.isRowVisible(window.direction_vote_use_di)
        assert not form.isRowVisible(window.direction_vote_use_structure)
        assert not form.isRowVisible(window.direction_vote_use_momentum)
        assert not form.isRowVisible(window.direction_vote_use_volume)
        assert not form.isRowVisible(window.direction_vote_use_htf)
        assert not form.isRowVisible(window.direction_vote_structure_lookback)
        assert not form.isRowVisible(window.direction_vote_htf_dataset)
    finally:
        window.close()


def test_direction_vote_required_count_is_clamped_to_enabled_signals():
    app(); window=MainWindow()
    try:
        window.enable_direction_voting.setChecked(True)
        window.direction_vote_minimum.setValue(5)
        window.direction_vote_use_structure.setChecked(False)
        window.direction_vote_use_momentum.setChecked(False)
        window.direction_vote_use_volume.setChecked(False)
        window.direction_vote_use_htf.setChecked(False)
        assert window.direction_vote_minimum.value()==1
        assert "DI pressure alone" in window.direction_vote_status.text()
    finally:
        window.close()


def test_support_resistance_tab_exists_with_expected_sections():
    app(); window=MainWindow()
    try:
        idx=[window.tabs.tabText(i) for i in range(window.tabs.count())].index("Support & Resistance")
        assert idx >= 0
        window.enable_support_resistance_analysis.setChecked(True)
        window.sr_filter_mode.setCurrentIndex(window.sr_filter_mode.findData("APPLY_ENTRY_RULES"))
        window.sr_long_avoid_near_resistance.setChecked(True)
        window.sr_long_min_room_to_resistance_atr.setValue(1.5)
        window.update_dynamic()
        assert "Avoid near resistance" in window.sr_summary_label.text()
        assert "Minimum room: 1.50 ATR" in window.sr_summary_label.text()
        assert [window.sr_filter_mode.itemData(i) for i in range(window.sr_filter_mode.count())] == [
            "ANALYSIS_ONLY", "APPLY_ENTRY_RULES"
        ]
    finally:
        window.close()


def test_sr_summary_panel_reports_best_and_worst_context():
    import pandas as pd
    app(); window=MainWindow()
    try:
        rows=[]
        for i in range(10):
            rows.append({
                "side": "LONG",
                "long_sr_context": "SUPPORT_BOUNCE" if i < 5 else "NO_NEARBY_SR",
                "long_pair_net_r": 0.5 if i < 5 else -0.4,
                "long_pair_net_pnl": 5.0 if i < 5 else -4.0,
            })
        trades=pd.DataFrame(rows)
        window._update_sr_summary_panel(trades)
        text=window.sr_summary_panel_label.text()
        assert "Best S/R Context" in text
        assert "Weakest S/R Context" in text
        assert "Support Bounce" in text
        assert "Analysis Only" in text
        assert "No trades filtered" in text
    finally:
        window.close()


def test_summary_is_scrollable_and_creates_report_buttons():
    app(); window=MainWindow()
    try:
        assert isinstance(window.summary_scroll_area, qtwidgets.QScrollArea)
        assert window.summary_scroll_area.widgetResizable()
        assert [button.text() for button in window.report_buttons.values()] == [
            "Open Backtest Report", "Open Indicator Analysis", "Open S/R Analysis",
            "Open Trade List", "Open Charts Folder", "Open Output Folder",
        ]
        assert all(window.summary_content.isAncestorOf(button) for button in window.report_buttons.values())
    finally: window.close()


def test_report_button_availability_matches_files(tmp_path):
    (tmp_path / REPORT_TARGETS["backtest"]).touch(); (tmp_path / "charts").mkdir()
    states=report_button_states(tmp_path)
    assert states == {"backtest":True,"indicators":False,"sr":False,"trades":False,"charts":True,"output":True}
    app(); window=MainWindow()
    try:
        window.output_dir=tmp_path; window._refresh_report_buttons()
        assert {name:button.isEnabled() for name,button in window.report_buttons.items()} == states
    finally: window.close()


def test_normal_summary_uses_six_direction_regime_rows():
    app(); window=MainWindow()
    try:
        trades=pd.DataFrame({"market_regime":["BULL"],"long_pair_net_pnl":[10.0],"long_pair_net_r":[1.0]})
        window.populate_summary({"total_trades":1},trades)
        assert window.comparison_box.title()=="Direction / Regime Performance"
        assert window.combo_table.rowCount()==6
        assert window.combo_table.item(0,0).text()=="Bull"
        assert window.combo_table.item(0,1).text()=="Long"
        assert window.combo_table.height() < 300
    finally: window.close()


def test_isolated_profile_summary_keeps_profile_performance():
    app(); window=MainWindow()
    try:
        window.populate_summary({"isolated_profile_comparison":[{"profile":"bull_long","trades":2,"win_rate":.5,"profit_factor":1.2,"net_profit":10}]})
        assert window.comparison_box.title()=="Profile Performance"
        assert window.combo_table.rowCount()==1
        assert window.combo_table.item(0,0).text()=="Bull Long"
    finally: window.close()


def test_sr_apply_mode_uses_friendly_summary_label():
    app(); window=MainWindow()
    try:
        window.sr_filter_mode.setCurrentIndex(window.sr_filter_mode.findData("APPLY_ENTRY_RULES"))
        window._update_sr_summary_panel(pd.DataFrame())
        assert "Mode: Apply Entry Rules" in window.sr_summary_panel_label.text()
        assert "APPLY_ENTRY_RULES" not in window.sr_summary_panel_label.text()
    finally: window.close()


def legacy_vwap_volume_breakout_controls_round_trip():
    app()
    window = MainWindow()
    try:
        assert "VWAP_VOLUME_BREAKOUT" in [window.entry_mode.itemText(i) for i in range(window.entry_mode.count())]
        window.entry_mode.setCurrentText("VWAP_VOLUME_BREAKOUT")
        window.vwap_breakout_hours.setValue(6)
        window.vwap_volume_multiplier.setValue(2.25)
        window.vwap_confirmation_mode.setCurrentText("RETEST")
        window.vwap_retest_window.setValue(6)
        window.vwap_retest_tolerance.setValue(0.4)
        values = window.values()
        assert values["entry_mode"] == "VWAP_VOLUME_BREAKOUT"
        assert values["vwap_breakout_lookback_hours"] == pytest.approx(6)
        assert values["vwap_volume_multiplier"] == pytest.approx(2.25)
        assert values["vwap_confirmation_mode"] == "RETEST"
        assert values["vwap_retest_window_candles"] == 6
        assert values["vwap_retest_tolerance_atr"] == pytest.approx(0.4)
        window.reset_defaults()
        assert window.vwap_breakout_hours.value() == pytest.approx(4)
        assert window.vwap_volume_multiplier.value() == pytest.approx(1.5)
        assert window.vwap_confirmation_mode.currentText() == "IMMEDIATE"
        assert not window.vwap_retest_window.isEnabled()
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


def legacy_entry_filter_controls_save_and_load(tmp_path):
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
    from crypto_strategy_lab.gui.config_logic import default_gui_config, format_percentage

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
        assert window.risk_leg.text() == format_percentage(0.01)
        assert window.maker.text() == format_percentage(0.0002)
        assert window.taker.text() == format_percentage(0.0005)
        assert window.slippage.text() == format_percentage(0.0005)
        assert values["use_intrabar_data"] is True
    finally:
        window.close()


def legacy_remaining_leg_timeout_gui_hours_save_load_round_trip(tmp_path):
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
