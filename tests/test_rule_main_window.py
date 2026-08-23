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
        buttons = "\n".join(button.text() for button in page.findChildren(QPushButton))

        assert "Strategy Summary" in group_titles
        assert "1. Direction & Market Eligibility" in group_titles
        assert "2. Entry Rules — all applicable rules must pass" in group_titles
        assert "3. Avoid / Veto Rules — matching conditions reject the trade" in group_titles
        assert "Profile Overrides" not in group_titles
        assert "Copy Overrides" not in buttons
        assert "Paste Overrides" not in buttons
        assert "six separate strategies" in labels
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


def test_rule_builder_roundtrip_recovers_rules_and_one_base_execution_plan():
    _app, window = _window()
    try:
        required = new_rule(kind="REQUIRED", evidence="RSI")
        required.update(operator="BETWEEN", value=20.0, value2=45.0, regime="BULL", side="LONG")
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

        assert window.rule_builder.required_rules.rules() == (required,)
        assert window.rule_builder.veto_rules.rules() == (veto,)
        rebuilt = window.build_config()
        assert rebuilt == config
        assert all(profile.stop_loss_multiple == 3.0 for profile in rebuilt.execution.profiles.values())
        assert all(profile.reward_risk_ratio == 2.0 for profile in rebuilt.execution.profiles.values())
    finally:
        window.close()


def test_market_permissions_are_not_strategy_profiles_in_the_visible_model():
    _app, window = _window()
    try:
        for key, check in window.rule_builder.permission_checks.items():
            check.setChecked(key in {"BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG"})
        index = window.rule_builder.direction_mode.findData("LONG_ONLY")
        window.rule_builder.direction_mode.setCurrentIndex(index)
        config = window.build_config()

        assert window.rule_builder.market_permissions() == (
            "BULL_LONG", "BEAR_LONG", "SIDEWAYS_LONG"
        )
        # Both source-DI branches are internally enabled because either may occur
        # on a candle, but both compile to the same actual LONG thesis.
        assert config.strategy.profiles["bull_long"].enabled
        assert config.strategy.profiles["bull_short"].enabled
        assert config.strategy.profiles["bull_short"].flip_direction
    finally:
        window.close()
