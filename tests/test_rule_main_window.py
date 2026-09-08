from __future__ import annotations

import os

import pytest

from crypto_strategy_lab.strategy_rule_model import new_rule


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

    return app, MainWindow(service=Service())


def test_active_strategy_page_is_rule_based_and_has_no_profile_or_sr_preset_surface():
    _app, window = _window()
    try:
        from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton

        page = window.pages.widget(1)
        group_titles = {box.title() for box in page.findChildren(QGroupBox)}
        labels = "\n".join(label.text() for label in page.findChildren(QLabel))
        buttons = "\n".join(
            button.text() for button in page.findChildren(QPushButton)
        )
        checks = "\n".join(
            check.text() for check in page.findChildren(QCheckBox)
        )

        assert "Strategy Summary" in group_titles
        assert "1. Signal Strategy & Market Eligibility" in group_titles
        assert "2. Entry Groups — ALL conditions inside; ANY group may qualify" in group_titles
        assert "3. Avoid / Veto Groups — ALL conditions inside; ANY group vetoes" in group_titles
        assert "DI Pressure State" not in group_titles
        assert "Support / Resistance Veto Presets" not in group_titles
        assert "Profile Overrides" not in group_titles
        assert "Copy Overrides" not in buttons
        assert "Paste Overrides" not in buttons
        assert "Show Support / Resistance veto presets" not in checks
        assert "Evidence is grouped and searchable" in labels
        assert "MR Trade-Direction Stretch is positive" in labels
        assert "Any MR or S/R rule automatically enables its causal calculation" in labels
    finally:
        window.close()


def test_direction_selector_contains_di_control_and_dmi_trend_strategy():
    _app, window = _window()
    try:
        selector = window.rule_builder.direction_mode
        assert selector.count() == 3
        assert selector.currentData() == "DI"
        assert selector.currentText() == "DI Direction"
        assert selector.findData("DMI_TREND") >= 0
        assert selector.itemText(selector.findData("DMI_TREND")) == "DMI Trend — Baseline"
        assert selector.findData("MACD_PULLBACK") >= 0
        assert selector.itemText(selector.findData("MACD_PULLBACK")) == "MACD Pullback — 12/26/9"
        assert selector.findData("LONG_ONLY") == -1
        assert selector.findData("SHORT_ONLY") == -1
    finally:
        window.close()


def test_evidence_picker_groups_every_current_indicator_once_and_preserves_ids():
    _app, window = _window()
    try:
        from crypto_strategy_lab.gui.rule_strategy_builder import (
            EVIDENCE_GROUPS,
            EvidenceComboBox,
        )
        from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS

        grouped = [
            evidence
            for _group, evidence_ids in EVIDENCE_GROUPS
            for evidence in evidence_ids
        ]
        assert len(grouped) == len(set(grouped))
        assert set(grouped) == set(RULE_INDICATORS)

        rule = new_rule(kind="REQUIRED", evidence="SR_ROOM_IN_DIRECTION_ATR")
        table = window.rule_builder.required_rules
        table.set_rules((rule,))
        picker = table.cellWidget(0, 1)
        assert isinstance(picker, EvidenceComboBox)
        assert picker.currentData() == "SR_ROOM_IN_DIRECTION_ATR"
        assert picker.findData("DI_SPREAD") >= 0
        assert picker.findData("SR_TRADE_LOCATION_RATING") >= 0
    finally:
        window.close()


def test_di_spread_30_rule_builds_one_rule_thesis_across_allowed_markets():
    _app, window = _window()
    try:
        rule = new_rule(kind="REQUIRED", evidence="DI_SPREAD")
        rule.update(operator="GTE", value=30.0, regime="ALL", side="ALL")
        window.rule_builder.required_rules.set_rules((rule,))
        config = window.build_config()

        assert config.strategy.strategy_profile_run_mode == "COMBINED_SHARED_CAPITAL"
        for profile in config.strategy.profiles.values():
            assert profile.enabled is True
            assert len(profile.entry_rules) == 1
            native = profile.entry_rules[0]
            assert native["indicator"] == "DI_SPREAD"
            assert native["condition"] == "OUTSIDE"
            assert native["minimum"] == 30.0
    finally:
        window.close()


def test_di_pressure_state_is_authored_as_categorical_entry_rule():
    _app, window = _window()
    try:
        from PySide6.QtWidgets import QComboBox, QLabel

        rule = new_rule(kind="REQUIRED", evidence="DI_PRESSURE_STATE")
        rule.update(operator="IS", value="EXPANDING")
        table = window.rule_builder.required_rules
        table.set_rules((rule,))

        assert isinstance(table.cellWidget(0, 2), QComboBox)
        assert table.cellWidget(0, 2).currentData() == "IS"
        assert isinstance(table.cellWidget(0, 3), QComboBox)
        assert table.cellWidget(0, 3).currentData() == "EXPANDING"
        assert isinstance(table.cellWidget(0, 4), QLabel)

        config = window.build_config()
        native = config.strategy.profiles["bull_long"].entry_rules[0]
        assert native["indicator"] == "DI_PRESSURE_STATE"
        assert native["condition"] == "OUTSIDE"
        assert native["minimum"] == native["maximum"] == 1.0
    finally:
        window.close()


def test_sr_veto_rule_is_categorical_and_automatically_enables_sr_features():
    _app, window = _window()
    try:
        from PySide6.QtWidgets import QComboBox, QLabel

        feature_toggle = window.feature_form.widgets["enable_support_resistance_analysis"]
        feature_toggle.setChecked(False)
        rule = new_rule(kind="VETO", evidence="SR_NEAR_RESISTANCE")
        rule.update(operator="IS", value="TRUE", side="LONG")
        table = window.rule_builder.veto_rules
        table.set_rules((rule,))

        assert isinstance(table.cellWidget(0, 2), QComboBox)
        assert table.cellWidget(0, 2).currentData() == "IS"
        assert isinstance(table.cellWidget(0, 3), QComboBox)
        assert table.cellWidget(0, 3).currentData() == "TRUE"
        assert isinstance(table.cellWidget(0, 4), QLabel)

        config = window.build_config()
        assert config.features.enable_support_resistance_analysis is True
        assert config.strategy.sr_filter_mode == "ANALYSIS_ONLY"
        assert config.strategy.sr_long_avoid_near_resistance is False
        native = config.strategy.profiles["bull_long"].entry_rules[0]
        assert native["indicator"] == "SR_NEAR_RESISTANCE"
        assert native["condition"] == "INSIDE"
        assert native["minimum"] == native["maximum"] == 1.0
        assert not config.strategy.profiles["bull_short"].entry_rules
    finally:
        window.close()


def test_mean_reversion_rule_automatically_enables_mr_context():
    _app, window = _window()
    try:
        window.rule_builder.enable_mr.setChecked(False)
        window.feature_form.widgets["mean_reversion_track_atr_distance"].setChecked(False)
        rule = new_rule(kind="VETO", evidence="MR_TRADE_STRETCH_ATR")
        rule.update(operator="GTE", value=1.25, regime="ALL", side="ALL")
        window.rule_builder.veto_rules.set_rules((rule,))

        config = window.build_config()
        assert config.strategy.enable_mean_reversion_analysis is True
        assert config.features.mean_reversion_track_atr_distance is True
        native = config.strategy.profiles["bull_long"].entry_rules[0]
        assert native["indicator"] == "MR_TRADE_STRETCH_ATR"
        assert native["condition"] == "INSIDE"
        assert native["minimum"] == 1.25
    finally:
        window.close()


def test_sr_numeric_room_rule_uses_same_entry_rule_table():
    _app, window = _window()
    try:
        rule = new_rule(kind="REQUIRED", evidence="SR_ROOM_IN_DIRECTION_ATR")
        rule.update(operator="GTE", value=2.0, side="LONG")
        window.rule_builder.required_rules.set_rules((rule,))
        config = window.build_config()

        native = config.strategy.profiles["bear_long"].entry_rules[0]
        assert native["indicator"] == "SR_ROOM_IN_DIRECTION_ATR"
        assert native["condition"] == "OUTSIDE"
        assert native["minimum"] == 2.0
        assert config.features.enable_support_resistance_analysis is True
    finally:
        window.close()


def test_pressure_calculation_stays_on_but_global_pressure_filter_is_neutral():
    _app, window = _window()
    try:
        config = window.build_config()
        assert config.strategy.enable_di_pressure_analysis is True
        assert config.strategy.di_pressure_allow_expanding is True
        assert config.strategy.di_pressure_allow_contracting is True
        assert config.strategy.di_pressure_allow_mixed is True
    finally:
        window.close()


def test_rule_builder_roundtrip_recovers_rules_and_one_base_execution_plan():
    _app, window = _window()
    try:
        required = new_rule(kind="REQUIRED", evidence="SR_SUPPORT_STATE")
        required.update(
            operator="IS_NOT", value="SUPPORT_BROKEN", regime="BULL", side="LONG"
        )
        veto = new_rule(kind="VETO", evidence="ADX")
        veto.update(operator="LTE", value=18.0, regime="SIDEWAYS", side="ALL")
        window.rule_builder.required_rules.set_rules((required,))
        window.rule_builder.veto_rules.set_rules((veto,))

        stop = window.base_execution_form.widgets["stop_loss_multiple"]
        target = window.base_execution_form.widgets["reward_risk_ratio"]
        stop.setValue(3.0)
        target.setValue(2.0)

        config = window.build_config()
        window.apply_config(config)

        recovered = window.rule_builder.required_rules.rules()[0]
        assert recovered["evidence"] == "SR_SUPPORT_STATE"
        assert recovered["operator"] == "IS_NOT"
        assert recovered["value"] == "SUPPORT_BROKEN"
        assert window.rule_builder.veto_rules.rules()[0]["evidence"] == "ADX"
        rebuilt = window.build_config()
        assert rebuilt == config
        assert all(
            profile.stop_loss_multiple == 3.0
            for profile in rebuilt.execution.profiles.values()
        )
        assert all(
            profile.reward_risk_ratio == 2.0
            for profile in rebuilt.execution.profiles.values()
        )
    finally:
        window.close()


def test_long_only_trading_uses_permissions_without_forcing_direction():
    _app, window = _window()
    try:
        for key, check in window.rule_builder.permission_checks.items():
            check.setChecked(
                key in {"BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG"}
            )
        config = window.build_config()

        assert window.rule_builder.direction_mode.currentData() == "DI"
        assert window.rule_builder.market_permissions() == (
            "BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG"
        )
        assert config.strategy.profiles["bull_long"].enabled
        assert not config.strategy.profiles["bull_short"].enabled
        assert config.strategy.profiles["bear_long"].enabled
        assert not config.strategy.profiles["bear_short"].enabled
        assert config.strategy.profiles["sideways_long"].enabled
        assert not config.strategy.profiles["sideways_short"].enabled
        assert all(
            not profile.flip_direction
            for profile in config.strategy.profiles.values()
        )
    finally:
        window.close()


def test_rule_builder_groups_conditions_and_keeps_scope_owned_by_group():
    _app, window = _window()
    try:
        from PySide6.QtWidgets import QLineEdit

        table = window.rule_builder.veto_rules
        first = new_rule(
            kind="VETO",
            evidence="MR_STATE",
            group_id="mr-pocket",
            group_name="Above mean and extending",
            regime="BULL",
            side="LONG",
        )
        first.update(operator="IS", value="ABOVE_MEAN")
        second = new_rule(
            kind="VETO",
            evidence="MR_MOTION",
            group_id="mr-pocket",
            group_name="Above mean and extending",
            regime="BULL",
            side="LONG",
        )
        second.update(operator="IS", value="AWAY_FROM_MEAN")
        table.set_rules((first, second))

        assert table.group_count() == 1
        assert isinstance(table.cellWidget(0, 0), QLineEdit)
        assert table.cellWidget(0, 0).text() == "Above mean and extending"
        assert table.cellWidget(1, 0).text() == "Above mean and extending"

        # Editing group scope on one condition updates the whole group.
        market = table.cellWidget(0, 5)
        market.setCurrentIndex(market.findData("BEAR"))
        assert table.cellWidget(1, 5).currentData() == "BEAR"

        side = table.cellWidget(1, 6)
        side.setCurrentIndex(side.findData("SHORT"))
        assert table.cellWidget(0, 6).currentData() == "SHORT"

        name = table.cellWidget(1, 0)
        name.setText("Renamed pocket")
        assert table.cellWidget(0, 0).text() == "Renamed pocket"

        rules = table.rules()
        assert len({rule["group_id"] for rule in rules}) == 1
        assert {rule["regime"] for rule in rules} == {"BEAR"}
        assert {rule["side"] for rule in rules} == {"SHORT"}
        assert {rule["group_name"] for rule in rules} == {"Renamed pocket"}
    finally:
        window.close()


def test_add_condition_reuses_selected_group_and_new_items_appear_at_top():
    _app, window = _window()
    try:
        table = window.rule_builder.required_rules
        table.add_group()
        original = table.rules()[0]
        first_group = original["group_id"]

        table.selectRow(0)
        table.add_condition_to_group()

        rules = table.rules()
        assert len(rules) == 2
        assert {rule["group_id"] for rule in rules} == {first_group}
        assert rules[0]["id"] != original["id"]
        assert rules[1]["id"] == original["id"]

        table.add_group()
        rules = table.rules()
        assert len(rules) == 3
        assert table.group_count() == 2
        assert rules[0]["group_id"] != first_group
        assert {rule["group_id"] for rule in rules[1:]} == {first_group}
    finally:
        window.close()
