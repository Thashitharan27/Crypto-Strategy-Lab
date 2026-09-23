from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication

from crypto_strategy_lab.gui.strategy_visualizer_workspace import (
    StrategyVisualizerWorkspace,
)


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


def test_strategy_visualizer_exposes_dedicated_sr_review_controls_and_inspector():
    app()
    workspace = StrategyVisualizerWorkspace(
        SimpleNamespace(_manifest=None, _run_dir=None)
    )
    try:
        assert workspace.view_mode.currentData() == "normal"
        assert workspace.open_browser.text() == "Open in Browser"
        assert not workspace.open_browser.isEnabled()
        assert workspace.sr_review_timeframe.currentData() == "strategy"
        assert workspace.sr_review_snapshot.currentData() == "live"
        assert workspace.sr_review_details.currentData() == "zones"
        assert not workspace.sr_review_timeframe.isEnabled()

        workspace.view_mode.setCurrentIndex(
            workspace.view_mode.findData("sr-review")
        )
        assert workspace.sr_review_timeframe.isEnabled()
        assert workspace.sr_review_snapshot.isEnabled()
        assert workspace.sr_review_details.isEnabled()
        assert all(
            not check.isEnabled()
            for check in workspace.overlay_checks.values()
        )

        workspace.view_mode.setCurrentIndex(
            workspace.view_mode.findData("normal")
        )
        assert all(
            check.isEnabled()
            for check in workspace.overlay_checks.values()
        )
        workspace.view_mode.setCurrentIndex(
            workspace.view_mode.findData("sr-review")
        )

        labels = [
            workspace.inspector_tabs.tabText(index)
            for index in range(workspace.inspector_tabs.count())
        ]
        assert labels == ["Trade", "Strategy Inspector", "S/R Inspector"]
    finally:
        workspace.close()


def test_sr_review_timeframe_selection_controls_visible_contexts():
    app()
    workspace = StrategyVisualizerWorkspace(
        SimpleNamespace(_manifest=None, _run_dir=None)
    )
    try:
        workspace.view_mode.setCurrentIndex(
            workspace.view_mode.findData("sr-review")
        )
        workspace.sr_review_timeframe.setCurrentIndex(
            workspace.sr_review_timeframe.findData("4h")
        )
        assert workspace._selected_sr_timeframes() == {"4h"}

        workspace.sr_review_timeframe.setCurrentIndex(
            workspace.sr_review_timeframe.findData("compare")
        )
        assert workspace._selected_sr_timeframes() == {
            "strategy",
            "1h",
            "4h",
            "1d",
        }
    finally:
        workspace.close()
