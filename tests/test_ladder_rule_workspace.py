from __future__ import annotations

import os

import pytest

from crypto_strategy_lab.gui.ladder_rule_install import apply_ladder_rule_workspace
from crypto_strategy_lab.gui.research_feature_ownership import apply_research_feature_ownership
from crypto_strategy_lab.gui.risk_execution_install import apply_risk_execution_workspace


def _window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from crypto_strategy_lab.gui.rule_main_window import MainWindow

    app = widgets.QApplication.instance() or widgets.QApplication([])

    class Catalog:
        def symbols(self):
            return ["BTCUSDT"]

        def coverage(self, _request):
            return []

    class Service:
        catalog = Catalog()

        def refresh_catalog(self):
            return 0

    window = MainWindow(service=Service())
    apply_research_feature_ownership(window)
    apply_risk_execution_workspace(window)
    apply_ladder_rule_workspace(window)
    return app, window


def test_ladder_rules_adds_visual_s1_to_s4_workspace_and_hides_raw_json():
    app, window = _window()
    try:
        workspace = window.ladder_rule_workspace
        assert window.ladder_rule_nav_button.text() == "Ladder Rules"
        assert workspace.tabs.count() == 4
        assert [workspace.tabs.tabText(i) for i in range(4)] == ["S1", "S2", "S3", "S4"]
        assert window.execution_form.widgets["di_ladder_layers"].isHidden()
        assert hasattr(window, "ladder_rule_open_button")
        assert "0 ladder entry condition" in workspace.summary.text().lower()
    finally:
        window.close()
        app.processEvents()


def test_ladder_condition_editor_compiles_numeric_and_categorical_rules():
    app, window = _window()
    try:
        workspace = window.ladder_rule_workspace
        panel = workspace.panels[0]

        numeric = panel.add_condition()
        numeric.evidence.setCurrentIndex(numeric.evidence.findData("ADX"))
        app.processEvents()
        numeric.operator.setCurrentIndex(numeric.operator.findData("GTE"))
        numeric.value.setValue(20.0)
        app.processEvents()

        categorical = panel.add_condition()
        categorical.evidence.setCurrentIndex(
            categorical.evidence.findData("DI_PRESSURE_STATE")
        )
        app.processEvents()
        categorical.operator.setCurrentIndex(categorical.operator.findData("IS"))
        categorical.value.setCurrentIndex(categorical.value.findData("EXPANDING"))
        app.processEvents()

        layers = window.execution_form.widgets["di_ladder_layers"].tuple_value()
        assert len(layers[0]["entry_rules"]) == 2

        adx = layers[0]["entry_rules"][0]
        assert adx["indicator"] == "ADX"
        assert adx["condition"] == "INSIDE"
        assert adx["minimum"] == 20.0
        assert adx["maximum"] == 1e308
        assert adx["_ladder_operator"] == "GTE"

        pressure = layers[0]["entry_rules"][1]
        assert pressure["indicator"] == "DI_PRESSURE_STATE"
        assert pressure["condition"] == "INSIDE"
        assert pressure["minimum"] == pressure["maximum"] == 1.0
        assert pressure["_ladder_value"] == "EXPANDING"
    finally:
        window.close()
        app.processEvents()


def test_ladder_context_rule_round_trips_timeframe_and_auto_enables_dependency():
    app, window = _window()
    try:
        workspace = window.ladder_rule_workspace
        workspace.enabled.setChecked(True)
        panel = workspace.panels[0]
        condition = panel.add_condition()
        condition.evidence.setCurrentIndex(
            condition.evidence.findData("SR_OPPOSING_ROOM_R")
        )
        app.processEvents()
        condition.timeframe.setCurrentIndex(condition.timeframe.findData(240))
        condition.operator.setCurrentIndex(condition.operator.findData("GTE"))
        condition.value.setValue(3.0)
        app.processEvents()

        window.feature_form.widgets["enable_support_resistance_analysis"].setChecked(False)
        config = window.build_config()

        rule = config.execution.di_ladder_layers[0]["entry_rules"][0]
        assert rule["indicator"] == "SR_OPPOSING_ROOM_R"
        assert rule["_builder_sr_timeframe_minutes"] == 240
        assert config.features.enable_support_resistance_analysis is True

        window.apply_config(config)
        app.processEvents()
        loaded = window.ladder_rule_workspace.panels[0].conditions[0]
        assert loaded.evidence.currentData() == "SR_OPPOSING_ROOM_R"
        assert loaded.timeframe.currentData() == 240
        assert loaded.operator.currentData() == "GTE"
        assert loaded.value.value() == pytest.approx(3.0)
    finally:
        window.close()
        app.processEvents()
