from __future__ import annotations

import os

import pytest

from crypto_strategy_lab.gui.research_feature_ownership import (
    apply_research_feature_ownership,
)


def test_mean_reversion_research_control_moves_out_of_strategy_builder():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    app = widgets.QApplication.instance() or widgets.QApplication([])

    window = widgets.QWidget()
    window.pages = widgets.QStackedWidget(window)

    strategy_page = widgets.QWidget()
    strategy_layout = widgets.QVBoxLayout(strategy_page)
    strategy_layout.addWidget(widgets.QLabel("Strategy Builder"))
    window.pages.addWidget(strategy_page)

    feature_page = widgets.QWidget()
    feature_layout = widgets.QVBoxLayout(feature_page)
    feature_layout.addWidget(widgets.QLabel("Research Features"))
    feature_layout.addWidget(widgets.QLabel("Feature calculation settings"))
    window.pages.addWidget(feature_page)

    builder = widgets.QWidget()
    builder_layout = widgets.QVBoxLayout(builder)
    old_research = widgets.QGroupBox("4. Research-only Evidence")
    old_layout = widgets.QHBoxLayout(old_research)
    builder.enable_mr = widgets.QCheckBox("Attach Mean Reversion context")
    builder.enable_mr.setChecked(False)
    old_layout.addWidget(builder.enable_mr)
    builder_layout.addWidget(old_research)
    builder.advanced = widgets.QGroupBox("5. Advanced")
    builder_layout.addWidget(builder.advanced)
    window.rule_builder = builder

    apply_research_feature_ownership(window)

    assert old_research.isHidden()
    assert builder.advanced.title() == "4. Advanced"
    assert window.mean_reversion_research_box.title() == "Mean Reversion Research"
    assert window.mean_reversion_research_box.layout().indexOf(builder.enable_mr) >= 0
    assert builder.enable_mr.isChecked() is False
    assert feature_page.layout().indexOf(window.mean_reversion_research_box) == 1

    # The helper is safe if final GUI composition is applied more than once.
    original_box = window.mean_reversion_research_box
    apply_research_feature_ownership(window)
    assert window.mean_reversion_research_box is original_box

    window.close()
    app.processEvents()
