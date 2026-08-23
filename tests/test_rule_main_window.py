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


def test_active_strategy_page_is_rule_based_and_has_no_profile_editor_surface():
    _app, window = _window()
    try:
        from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton

        page = window.pages.widget(1)
        group_titles = {box.title() for box in page.findChildren(QGroupBox)}
        labels = "\n".join(label.text() for label in page.findChildren(QLabel))
        buttons = "\n".join(
            button.text() for button in page.findChildren(QPushButton)
        )

        assert "Strategy Summary" in group_titles
        assert "1. Direction & Market Eligibility" in group_titles
        assert "2. Entry Rules — all applicable rules must pass" in group_titles
        assert "3. Avoid / Veto Rules — matching conditions reject the trade" in group_titles
        assert "DI Pressure State" not in group_titles
        assert "Profile Overrides" not in group_titles
        assert "Copy Overrides" not in buttons
        assert "Paste Overrides" not in buttons
        assert "DI Pressure is calculated automatically" in labels
    finally:
        window.close()


def test_direction_selector_contains_only_current_di_strategy():
    _app, window = _window()
    try:
        selector = window.rule_builder.direction_mode
        assert selector.count() == 1
        assert selector.currentData() == "DI"
        assert selector.currentText() == "DI Direction"
        assert selector.findData("LONG_ONLY") == -1
        assert selector.findData("SHORT_ONLY") == -1
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

        assert isinstance(table.cellWidget(0, 1), QComboBox)
        assert table.cellWidget(0, 1).currentData() == "IS"
        assert isinstance(table.cellWidget(0, 2), QComboBox)
        assert table.cellWidget(0, 2).currentData() == "EXPANDING"
        assert isinstance(table.cellWidget(0, 3), QLabel)

        config = window.build_config()
        native = config.strategy.profiles["bull_long"].entry_rules[0]
        assert native["indicator"] == "DI_PRESSURE_STATE"
        assert native["condition"] == "OUTSIDE"
        assert native["minimum"] == native["maximum"] == 1.0
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
        required = new_rule(kind="REQUIRED", evidence="DI_PRESSURE_STATE")
        required.update(
            operator="IS", value="EXPANDING", regime="BULL", side="LONG"
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

        assert window.rule_builder.required_rules.rules() == (
            window.rule_builder.required_rules.rules()[0],
        )
        recovered = window.rule_builder.required_rules.rules()[0]
        assert recovered["evidence"] == "DI_PRESSURE_STATE"
        assert recovered["operator"] == "IS"
        assert recovered["value"] == "EXPANDING"
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
