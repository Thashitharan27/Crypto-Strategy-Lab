"""Composition hook that adds portfolio replay to the current v2 workstation."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from .portfolio_replay_workspace import PortfolioReplayWorkspace


def _navigation_layout(window):
    central = window.centralWidget()
    shell = central.layout() if central is not None else None
    if shell is None or shell.count() < 1:
        return None
    first = shell.itemAt(0)
    return first.layout() if first is not None else None


def _navigation_insert_index(nav) -> int:
    """Insert before the v2 navigation stretch / bottom quick-run card."""
    for index in range(nav.count()):
        item = nav.itemAt(index)
        if item is not None and item.spacerItem() is not None:
            return index
    return nav.count()


def apply_portfolio_replay_workspace(window) -> None:
    """Add the output-based Portfolio workspace without changing native run semantics."""
    if getattr(window, "portfolio_replay_workspace", None) is not None:
        return
    if not hasattr(window, "pages"):
        return
    nav = _navigation_layout(window)
    if nav is None:
        return

    workspace = PortfolioReplayWorkspace(window)
    page = window._page("Portfolio", workspace) if hasattr(window, "_page") else workspace
    page_index = window.pages.addWidget(page)

    heading = QLabel("PORTFOLIO")
    heading.setStyleSheet("font-weight:bold; color:#52606d; margin-top:10px")
    button = QPushButton("Portfolio Replay")
    button.setFlat(True)
    button.clicked.connect(
        lambda _checked=False, index=page_index: window.pages.setCurrentIndex(index)
    )

    insert_at = _navigation_insert_index(nav)
    nav.insertWidget(insert_at, heading)
    nav.insertWidget(insert_at + 1, button)

    window.portfolio_replay_workspace = workspace
    window.portfolio_replay_nav_heading = heading
    window.portfolio_replay_nav_button = button
