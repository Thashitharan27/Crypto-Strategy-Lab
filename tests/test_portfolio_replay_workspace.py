from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

qtwidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QApplication = qtwidgets.QApplication
QHBoxLayout = qtwidgets.QHBoxLayout
QLabel = qtwidgets.QLabel
QLineEdit = qtwidgets.QLineEdit
QMainWindow = qtwidgets.QMainWindow
QStackedWidget = qtwidgets.QStackedWidget
QVBoxLayout = qtwidgets.QVBoxLayout
QWidget = qtwidgets.QWidget

from crypto_strategy_lab.gui.portfolio_replay_install import (
    apply_portfolio_replay_workspace,
)


def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(sys.argv)


class HostWindow(QMainWindow):
    def __init__(self, output_root):
        super().__init__()
        root = QWidget()
        shell = QHBoxLayout(root)
        self.nav = QVBoxLayout()
        shell.addLayout(self.nav)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages)
        self.nav.addWidget(QLabel("TOOLS"))
        self.nav.addStretch()
        self.current_research = QLabel("Current research")
        self.nav.addWidget(self.current_research)
        self.setCentralWidget(root)
        self.output_root = QLineEdit(str(output_root))
        self.config = SimpleNamespace(
            execution=SimpleNamespace(initial_equity=1000.0),
            reporting=SimpleNamespace(output_dir=str(output_root)),
        )

    @staticmethod
    def _page(title, *widgets):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(title))
        for widget in widgets:
            layout.addWidget(widget)
        return page


def test_portfolio_replay_installer_adds_one_current_workstation_page(tmp_path):
    app()
    window = HostWindow(tmp_path)
    try:
        apply_portfolio_replay_workspace(window)
        assert window.pages.count() == 1
        assert window.portfolio_replay_nav_button.text() == "Portfolio Replay"
        assert window.portfolio_replay_workspace.initial_equity.value() == 1000.0
        assert window.portfolio_replay_workspace.one_active_per_symbol.isChecked()
        assert window.portfolio_replay_workspace.common_period_only.isChecked()
        assert window.portfolio_replay_workspace.table.rowCount() == 0

        apply_portfolio_replay_workspace(window)
        assert window.pages.count() == 1
    finally:
        window.close()
