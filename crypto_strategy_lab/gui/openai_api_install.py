"""Install the OpenAI API credential page into the active desktop shell."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from .openai_api_settings import OpenAIAPISettingsWidget


def _sidebar_layout(window):
    central = window.centralWidget()
    shell = central.layout() if central is not None else None
    if shell is None or shell.count() < 1:
        return None
    first = shell.itemAt(0)
    return first.layout() if first is not None else None


def apply_openai_api_settings(window) -> None:
    """Add an OpenAI API page under Tools without mutating research config."""
    if getattr(window, "_openai_api_settings_installed", False):
        return
    if not hasattr(window, "pages") or not hasattr(window, "_page"):
        return

    widget = OpenAIAPISettingsWidget(window)
    page = window._page("OpenAI API", widget)
    page_index = window.pages.addWidget(page)

    button = QPushButton("OpenAI API")
    button.setFlat(True)
    button.clicked.connect(
        lambda _checked=False, index=page_index: window.pages.setCurrentIndex(index)
    )

    nav = _sidebar_layout(window)
    if nav is not None:
        insert_at = None
        for position in range(nav.count()):
            item = nav.itemAt(position)
            candidate = item.widget() if item is not None else None
            if isinstance(candidate, QPushButton) and candidate.text() == "GitHub":
                insert_at = position
                break
        if insert_at is None:
            # Base shell ends with stretch + research summary + RUN BACKTEST.
            insert_at = max(0, nav.count() - 3)
        nav.insertWidget(insert_at, button)

    window.openai_api_settings = widget
    window.openai_api_page = page
    window.openai_api_nav_button = button
    window._openai_api_settings_installed = True
