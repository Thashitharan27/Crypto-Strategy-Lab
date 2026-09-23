"""Install the dedicated DI ladder rule workspace into the desktop shell."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from .desktop_style import NAVIGATION_BUTTON_STYLE
from .ladder_rule_workspace import (
    LadderRuleWorkspace,
    apply_ladder_rule_dependencies,
)


def _navigation_layout(window):
    central = window.centralWidget()
    shell = central.layout() if central is not None else None
    if shell is None or shell.count() < 1:
        return None
    first = shell.itemAt(0)
    return first.layout() if first is not None else None


def _new_research_insert_index(nav) -> int:
    """Place Ladder Rules with the normal research workflow, before RESULTS."""
    for index in range(nav.count()):
        item = nav.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, QLabel) and widget.text().strip().upper() == "RESULTS":
            return index
    for index in range(nav.count()):
        item = nav.itemAt(index)
        if item is not None and item.spacerItem() is not None:
            return index
    return nav.count()


def apply_ladder_rule_workspace(window) -> None:
    """Add a visual S1/S2/S3/S4 editor without changing ladder execution semantics."""
    if getattr(window, "ladder_rule_workspace", None) is not None:
        return
    if not all(
        hasattr(window, name)
        for name in ("pages", "execution_form", "_page", "_scroll")
    ):
        return
    nav = _navigation_layout(window)
    if nav is None:
        return

    workspace = LadderRuleWorkspace(window)
    page = window._page("Ladder Rules", window._scroll(workspace))
    page_index = window.pages.addWidget(page)

    button = QPushButton("Ladder Rules")
    button.setFlat(False)
    button.setMinimumWidth(240)
    button.setStyleSheet(NAVIGATION_BUTTON_STYLE)
    button.setProperty("cslNavigationButton", True)
    button.clicked.connect(
        lambda _checked=False, index=page_index: window.pages.setCurrentIndex(index)
    )
    insert_at = _new_research_insert_index(nav)
    nav.insertWidget(insert_at, button)

    # The visual workspace is now authoritative for ladder layer editing. Keep the
    # legacy JSON tuple widget alive for config serialization, but stop asking the
    # researcher to edit it directly.
    risk_workspace = getattr(window, "risk_execution_workspace", None)
    if risk_workspace is not None and hasattr(risk_workspace, "ladder_card"):
        risk_workspace.ladder_card.set_row_visible("di_ladder_layers", False)
        open_button = QPushButton("Open Ladder Rules")
        open_button.setToolTip("Edit S1/S2/S3/S4 geometry and entry filters visually")
        open_button.clicked.connect(
            lambda _checked=False, index=page_index: window.pages.setCurrentIndex(index)
        )
        risk_workspace.ladder_card.layout().addWidget(open_button)
        window.ladder_rule_open_button = open_button

    # Loading/resetting a config may update the hidden tuple editor with signals
    # blocked. Refresh the visible workspace after every successful apply.
    original_apply_config = window.apply_config

    def apply_config_and_refresh(config):
        result = original_apply_config(config)
        workspace.load_from_authoritative()
        return result

    window.apply_config = apply_config_and_refresh

    # Ladder filters use the same causal evidence as Strategy Builder rules.
    # Automatically enable any required feature block before the final validation.
    original_build_config = window.build_config

    def build_config_with_ladder_dependencies():
        return apply_ladder_rule_dependencies(original_build_config())

    window.build_config = build_config_with_ladder_dependencies

    window.ladder_rule_workspace = workspace
    window.ladder_rule_nav_button = button
