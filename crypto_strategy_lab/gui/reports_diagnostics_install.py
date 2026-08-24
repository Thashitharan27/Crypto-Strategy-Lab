"""Final GUI composition for the redesigned Reports & Diagnostics workspace."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from .reports_diagnostics_workspace import ReportsDiagnosticsWorkspace


def _hide_legacy_output_controls(window) -> None:
    """Run Details now owns output-folder editing; keep the native sink hidden."""
    output = getattr(window, "output_root", None)
    if output is None:
        return
    parent = output.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is None:
        output.hide()
        return
    index = layout.indexOf(output)
    for position in (index - 1, index, index + 1):
        if position < 0 or position >= layout.count():
            continue
        widget = layout.itemAt(position).widget()
        if widget is not None:
            widget.hide()


def apply_reports_diagnostics_workspace(window) -> None:
    """Replace legacy preset/form UI with the native profile-driven workspace."""
    if getattr(window, "reports_diagnostics_workspace", None) is not None:
        return
    if not all(
        hasattr(window, name)
        for name in (
            "reporting_form", "output_root", "_page", "_scroll", "_replace_page",
        )
    ):
        return

    workspace = ReportsDiagnosticsWorkspace(window)
    note = QLabel(
        "Choose the output depth for this research run. Canonical completed-run and provenance artifacts "
        "are always saved; optional reports below are derived after the simulation from those artifacts."
    )
    note.setWordWrap(True)
    note.setStyleSheet("background:#eef5fb; padding:8px; border:1px solid #c8d9e8")
    page = window._page("Reports & Diagnostics", note, window._scroll(workspace))
    window._replace_page(4, page)
    window.reports_diagnostics_workspace = workspace
    _hide_legacy_output_controls(window)

    # The stable shell renders the internal analysis_level in Review & Run.
    # Keep that field serialized for v3 runs but translate the visible summary
    # back to the researcher-facing profile name after every summary render.
    original_render_summary = window._render_research_summary

    def render_summary_with_profile(config):
        result = original_render_summary(config)
        workspace.refresh_review_summary()
        return result

    window._render_research_summary = render_summary_with_profile

    # Config loads use blocked widget updates in parts of the stable shell.
    # Refresh the visible profile after the canonical config has been applied.
    original_apply_config = window.apply_config

    def apply_config_and_refresh(config):
        workspace._rendering = True
        try:
            result = original_apply_config(config)
        finally:
            workspace._rendering = False
        workspace.refresh_from_form()
        return result

    window.apply_config = apply_config_and_refresh
    workspace.refresh_from_form()
    workspace.refresh_review_summary()
