"""Safety and presentation-boundary tests for GUI UX Phase 1."""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from crypto_strategy_lab.data_lake_config import ReportingConfig, ResearchRunConfig
from crypto_strategy_lab.gui.ux_presentation import (ENUM_LABELS, PROFILE_LABELS,
    REPORT_PRESETS, apply_report_preset, clone_profile_pair, display_percentage,
    parse_percentage)
from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "crypto_strategy_lab/gui/v2_main_window.py"


@pytest.mark.parametrize(("native", "shown"), ((.01,"1.00%"),(.0002,"0.02%"),(.0005,"0.05%"),(.002,"0.20%")))
def test_percentage_display_and_edit_roundtrip(native, shown):
    assert display_percentage(native) == shown
    assert parse_percentage(shown) == native


def test_friendly_enum_labels_preserve_native_values():
    assert ENUM_LABELS["strategy_profile_run_mode"]["COMBINED_SHARED_CAPITAL"] == "Combined — Shared Account"
    assert ENUM_LABELS["tie_policy"]["PESSIMISTIC"] == "Conservative — Stop First"
    assert set(PROFILE_LABELS) == {"bull_long","bull_short","bear_long","bear_short","sideways_long","sideways_short"}


def test_report_preset_mapping_is_explicit_and_deterministic():
    base = ReportingConfig(run_name="keep-me", output_dir="keep/this")
    for preset in REPORT_PRESETS:
        first = apply_report_preset(base, preset)
        second = apply_report_preset(base, preset)
        assert first == second and first.run_name == "keep-me" and first.output_dir == "keep/this"
    assert apply_report_preset(base,"QUICK").create_standard_charts is False
    assert apply_report_preset(base,"STANDARD").create_standard_charts is True
    assert apply_report_preset(base,"DEEP_RESEARCH").enable_trade_telemetry is True


def test_copy_profile_pair_does_not_alias_rule_payloads():
    config=ResearchRunConfig(); strategy=config.strategy.profiles["bull_long"]
    strategy=replace(strategy,entry_rules=({"indicator":"ADX","advanced":{"future":1}},))
    copied_strategy,copied_execution=clone_profile_pair(strategy,config.execution.profiles["bull_long"])
    copied_strategy.entry_rules[0]["advanced"]["future"]=2
    assert strategy.entry_rules[0]["advanced"]["future"] == 1
    assert copied_execution == config.execution.profiles["bull_long"]


def test_active_gui_has_workflow_and_no_unsafe_or_parallel_execution_path():
    source=GUI.read_text(encoding="utf-8")
    for page in ("Setup","Strategy & Profiles","Research Features","Risk & Execution","Reports & Diagnostics","Review & Run","Results Dashboard","Data Library","ChatGPT / MCP","GitHub"):
        assert page in source
    assert "QThread.terminate" not in source and "run_manifest.json\").write" not in source
    assert "ResearchRunner" not in source and "BacktestWorker" not in source


def test_structured_rules_retain_private_payload_without_json_primary_editor():
    source=GUI.read_text(encoding="utf-8")
    tree=ast.parse(source)
    entry=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="EntryRuleEditor")
    assert entry and "_payloads" in source and "Advanced Entry Rules" in source
    assert "Entry Rules (structured JSON array)" not in source


def _window():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    widgets=pytest.importorskip("PySide6.QtWidgets",exc_type=ImportError)
    from crypto_strategy_lab.gui.v2_main_window import MainWindow
    app=widgets.QApplication.instance() or widgets.QApplication([])
    class Catalog:
        def symbols(self): return ["BTCUSDT"]
        def coverage(self,_request): return []
        def inventory(self,*_args): return []
    class Service:
        catalog=Catalog()
        def refresh_catalog(self): return 0
    return app,MainWindow(service=Service())


def test_arbitrary_native_float_precision_survives_untouched_gui_roundtrip():
    _app,window=_window()
    try:
        base=ResearchRunConfig()
        config=replace(base,
            features=replace(base.features,bb_stddevs=2.1234567890123),
            execution=replace(base.execution,maker_fee=.00123456,risk_per_leg=.0123456789,
                taker_fee=.000543219876,slippage=.000501234567,percent_r=.00234567891))
        window.apply_config(config)
        assert window.build_config() == config
    finally: window.close()


def test_friendly_profile_selector_retains_native_keys():
    _app,window=_window()
    try:
        selector=window.profile_editor.selector
        assert [selector.itemText(i) for i in range(selector.count())] == list(PROFILE_LABELS.values())
        selector.setCurrentText("bear_short")
        assert selector.currentData() == "bear_short" and selector.itemText(selector.currentIndex()) == "Bear Short"
    finally: window.close()


def test_entry_rule_widget_roundtrip_order_unknown_payload_and_one_edit():
    _app,window=_window()
    try:
        editor=window.profile_editor.entry_rules
        rules=({"action":"FLIP","indicator":"RSI","condition":"INSIDE","minimum":20.25,"maximum":31.75,"future":{"keep":1}},
               {"action":"REJECT","indicator":"ADX","condition":"OUTSIDE","minimum":10.0,"maximum":40.0,"private":"yes"})
        editor.set_tuple(rules); assert editor.tuple_value() == rules
        editor.item(0,3).setText("21.5")
        edited=editor.tuple_value()
        assert edited[0]["minimum"] == 21.5 and edited[0]["future"] == {"keep":1}
        assert edited[1] == rules[1]
    finally: window.close()


def test_entry_rule_editor_exposes_every_native_indicator_without_mutation():
    _app,window=_window()
    try:
        editor=window.profile_editor.entry_rules
        rules=tuple({"action":"FLIP","indicator":name,"condition":"INSIDE","minimum":0.0,"maximum":1.0}
                    for name in RULE_INDICATORS)
        editor.set_tuple(rules)
        for row,name in enumerate(RULE_INDICATORS):
            combo=editor.cellWidget(row,1)
            assert [combo.itemData(index) for index in range(combo.count())] == list(RULE_INDICATORS)
            assert combo.currentData() == name
        assert editor.tuple_value() == rules
    finally: window.close()


def test_entry_rule_combo_edits_emit_live_change_signal():
    _app,window=_window()
    try:
        editor=window.profile_editor.entry_rules
        rule=({"action":"FLIP","indicator":"RSI","condition":"INSIDE","minimum":20.0,"maximum":30.0},)
        editor.set_tuple(rule)
        events=[]
        editor.changed.connect(lambda: events.append(editor.tuple_value()[0]["indicator"]))
        combo=editor.cellWidget(0,1)
        combo.setCurrentIndex(combo.findData("ADX"))
        assert events and events[-1] == "ADX"
        assert editor.tuple_value()[0]["indicator"] == "ADX"
    finally: window.close()


def test_readiness_distinguishes_required_candles_from_optional_context():
    _app,window=_window()
    try:
        classify=window.data_readiness
        assert classify([],"4h","1m")[0] == "BLOCKED"
        candles=[{"dataset":"klines","interval":"4h","state":"AVAILABLE"},{"dataset":"klines","interval":"1m","state":"AVAILABLE"}]
        assert classify(candles,"4h","1m")[0] == "READY"
        assert classify(candles+[{"dataset":"funding","interval":None,"state":"UNAVAILABLE"}],"4h","1m")[0] == "WARN"
    finally: window.close()


def test_optional_price_context_cannot_satisfy_required_execution_candles():
    _app,window=_window()
    try:
        substitutes=[
            {"dataset":"mark_price_klines","interval":"4h","state":"AVAILABLE"},
            {"dataset":"index_price_klines","interval":"1m","state":"AVAILABLE"},
            {"dataset":"premium_index_klines","interval":"4h","state":"AVAILABLE"},
        ]
        assert window.data_readiness(substitutes,"4h","1m")[0] == "BLOCKED"
    finally: window.close()


def test_value_carrying_qt_signals_bridge_to_zero_argument_form_signal():
    _app,window=_window()
    try:
        events=[]
        window.feature_form.changed.connect(lambda: events.append(True))
        spin=window.feature_form.widgets["atr_period"]
        spin.setValue(spin.value()+1)
        assert events
    finally: window.close()


def test_report_presets_change_only_reporting_config_in_window():
    _app,window=_window()
    try:
        before=window.build_config()
        for index in range(window.report_preset.count()):
            window.report_preset.setCurrentIndex(index); window.apply_reporting_preset(); after=window.build_config()
            assert (after.data,after.features,after.strategy,after.execution) == (before.data,before.features,before.strategy,before.execution)
    finally: window.close()


def test_strategy_workspace_uses_authoritative_native_widgets_not_duplicate_state():
    _app,window=_window()
    try:
        workspace=window.strategy_workspace
        assert workspace.widgets is window.strategy_form.widgets
        assert workspace.widgets["enable_di_direction_selection"] is window.strategy_form.widgets["enable_di_direction_selection"]
        assert workspace.widgets["strategy_profile_run_mode"] is window.strategy_form.widgets["strategy_profile_run_mode"]
        assert window.profile_editor.profile_details.isHidden()
        assert workspace.advanced_strategy.isHidden()
        assert workspace.sr_filter_details.isHidden()
    finally: window.close()


def test_market_permission_matrix_edits_native_profile_enabled_flag_only():
    _app,window=_window()
    try:
        base=ResearchRunConfig(); window.apply_config(base)
        before=window.build_config()
        box=window.profile_editor.permission_checks["bull_short"]
        box.setChecked(False)
        after=window.build_config()
        assert after.strategy.profiles["bull_short"].enabled is False
        assert after.execution == before.execution
        assert after.strategy.profiles["bull_long"] == before.strategy.profiles["bull_long"]
        box.setChecked(True)
        assert window.build_config() == before
    finally: window.close()


def test_plain_english_strategy_thesis_tracks_native_strategy_controls():
    _app,window=_window()
    try:
        text=window.strategy_workspace.thesis_summary.text()
        assert "Trade in:" in text and "DI selects direction" in text
        assert "Support/Resistance is analysis-only" in text
        window.strategy_form.widgets["enable_di_pressure_analysis"].setChecked(False)
        assert "DI pressure logic is off" in window.strategy_workspace.thesis_summary.text()
        window.strategy_form.widgets["sr_filter_mode"].setCurrentIndex(
            window.strategy_form.widgets["sr_filter_mode"].findData("APPLY_ENTRY_RULES"))
        assert "can block entries" in window.strategy_workspace.thesis_summary.text()
        assert not window.strategy_workspace.sr_filter_details.isHidden()
    finally: window.close()


def test_profile_details_are_optional_but_roundtrip_still_lossless():
    _app,window=_window()
    try:
        base=ResearchRunConfig()
        profiles=dict(base.strategy.profiles)
        executions=dict(base.execution.profiles)
        profiles["bear_long"]=replace(profiles["bear_long"],enabled=False,flip_direction=True,
            entry_rules=({"action":"REJECT","indicator":"ATR_PCT","condition":"OUTSIDE","minimum":0.1,"maximum":3.2},))
        executions["bear_long"]=replace(executions["bear_long"],risk_multiplier=.75,reward_risk_ratio=2.5,
            break_even_enabled=True)
        config=replace(base,strategy=replace(base.strategy,profiles=profiles),
            execution=replace(base.execution,profiles=executions))
        window.apply_config(config)
        assert window.profile_editor.profile_details.isHidden()
        assert window.build_config() == config
        assert "Bear Long" in window.profile_editor.profile_summary.text() or window.profile_editor.selector.currentData() != "bear_long"
    finally: window.close()
