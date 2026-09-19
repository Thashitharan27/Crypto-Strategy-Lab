"""Install Strategy Visualizer into the active stable desktop shell."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from .strategy_visualizer_workspace import StrategyVisualizerWorkspace


def apply_strategy_visualizer_workspace(window) -> None:
    """Add one read-only visualization page under RESULTS."""
    if getattr(window, "strategy_visualizer_workspace", None) is not None:
        return
    required = ("_page", "pages", "centralWidget")
    if not all(hasattr(window, name) for name in required):
        return

    workspace = StrategyVisualizerWorkspace(window)
    page = window._page("Strategy Visualizer", workspace)
    page_index = window.pages.addWidget(page)

    shell = window.centralWidget().layout()
    nav = shell.itemAt(0).layout() if shell is not None and shell.count() else None
    if nav is None:
        return

    button = QPushButton("Strategy Visualizer")
    button.setFlat(True)
    button.clicked.connect(
        lambda _checked=False, i=page_index: window.pages.setCurrentIndex(i)
    )

    insert_at = None
    for index in range(nav.count()):
        widget = nav.itemAt(index).widget()
        if isinstance(widget, QPushButton) and widget.text() == "Results Dashboard":
            insert_at = index + 1
            break
    if insert_at is None:
        for index in range(nav.count()):
            widget = nav.itemAt(index).widget()
            if isinstance(widget, QLabel) and widget.text() == "DATA":
                insert_at = index
                break
    if insert_at is None:
        insert_at = max(0, nav.count() - 3)
    nav.insertWidget(insert_at, button)

    window.strategy_visualizer_workspace = workspace
    window.strategy_visualizer_button = button
