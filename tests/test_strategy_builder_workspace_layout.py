from __future__ import annotations

import os

import pytest

from crypto_strategy_lab.gui.rule_strategy_builder import RuleStrategyBuilder
from crypto_strategy_lab.strategy_rule_model import new_rule


def _builder():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    app = widgets.QApplication.instance() or widgets.QApplication([])
    builder = RuleStrategyBuilder()
    return app, builder, widgets


def test_strategy_builder_uses_tabbed_master_detail_rule_workspace():
    app, builder, widgets = _builder()
    try:
        first = new_rule(
            kind="REQUIRED",
            group_name="Bull Pullback",
            regime="BULL",
            side="LONG",
            evidence="ADX",
        )
        second = new_rule(
            kind="REQUIRED",
            group_name="Bear Recovery",
            regime="BEAR",
            side="LONG",
            evidence="RSI",
        )
        builder.required_rules.set_rules((first, second))
        builder.refresh_summary()

        assert builder.rule_tabs.count() == 3
        assert builder.rule_tabs.tabText(0) == "Entry  2/2"
        assert builder.rule_tabs.tabText(1).startswith("Veto")
        assert builder.rule_tabs.tabText(2).startswith("Flip")

        table = builder.required_rules
        assert table.group_list.count() == 2
        assert table.detail_stack.count() == 3  # empty state + two focused group cards
        assert table.splitter.orientation() == pytest.importorskip(
            "PySide6.QtCore", exc_type=ImportError
        ).Qt.Horizontal

        # RuleTable no longer owns an inner scrollbar; the page's outer scroll
        # remains the single scrolling surface.
        assert table.findChildren(widgets.QScrollArea) == []
    finally:
        builder.close()
        app.processEvents()


def test_group_logic_preview_is_collapsed_and_market_section_can_collapse():
    app, builder, _widgets = _builder()
    try:
        rule = new_rule(
            kind="REQUIRED",
            group_name="Entry Group 1",
            regime="BULL",
            side="LONG",
            evidence="ADX",
        )
        builder.required_rules.set_rules((rule,))
        group = builder.required_rules._groups[rule["group_id"]]

        assert group["preview"].isHidden()
        group["logic_toggle"].setChecked(True)
        assert not group["preview"].isHidden()

        assert not builder.direction_box.isHidden()
        builder.direction_toggle.setChecked(False)
        assert builder.direction_box.isHidden()
        builder.direction_toggle.setChecked(True)
        assert not builder.direction_box.isHidden()
    finally:
        builder.close()
        app.processEvents()


def test_condition_editor_keeps_evidence_separate_from_compact_value_controls():
    app, builder, _widgets = _builder()
    try:
        rule = new_rule(
            kind="REQUIRED",
            group_name="HTF Support",
            regime="BULL",
            side="LONG",
            evidence="SR_NEAR_SUPPORT",
        )
        rule["sr_timeframe_minutes"] = 60
        builder.required_rules.set_rules((rule,))
        row = builder.required_rules._rows[0]

        # Evidence gets its own top row; timeframe/operator/value live in the
        # compact controls row beneath it so narrow windows do not crush labels.
        assert row["evidence"].parentWidget() is row["widget"]
        assert row["sr_timeframe"].currentData() == 60
        assert not row["sr_timeframe"].isHidden()
        assert row["sr_timeframe"].findData(0) >= 0
        assert row["sr_timeframe"].findData(60) >= 0
        assert row["sr_timeframe"].findData(240) >= 0
        assert row["sr_timeframe"].findData(1440) >= 0
    finally:
        builder.close()
        app.processEvents()


def test_adding_condition_keeps_the_edited_group_selected_and_inserts_at_top():
    app, builder, _widgets = _builder()
    try:
        rule = new_rule(
            kind="VETO",
            group_name="Weak Pocket",
            regime="SIDEWAYS",
            side="LONG",
            evidence="ADX",
        )
        builder.veto_rules.set_rules((rule,))
        group_id = rule["group_id"]
        builder.veto_rules.add_condition_to_group_id(group_id)

        assert builder.veto_rules.current_group_id() == group_id
        assert builder.veto_rules.rowCount() == 2
        assert builder.veto_rules._rows[0]["group_id"] == group_id
        assert builder.veto_rules._rows[1]["group_id"] == group_id
    finally:
        builder.close()
        app.processEvents()
