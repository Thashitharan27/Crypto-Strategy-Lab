"""Final GUI composition for the organized Reports & Diagnostics workspace."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from .reports_diagnostics_workspace import ReportsDiagnosticsWorkspace


def apply_reports_diagnostics_workspace(window) -> None:
    """Replace the raw ReportingConfig form with a researcher-facing workspace."""
    if getattr(window, "reports_diagnostics_workspace", None) is not None:
        return
    if not all(
        hasattr(window, name)
        for name in ("reporting_form", "_page", "_scroll", "_replace_page")
    ):
        return

    workspace = ReportsDiagnosticsWorkspace(window)
    note = QLabel(
        "Canonical run data is always preserved. Choose only the optional human review and diagnostic work you want for this run; expensive diagnostics stay explicit."
    )
    note.setWordWrap(True)
    note.setStyleSheet("background:#eef5fb; padding:8px; border:1px solid #c8d9e8")
    page = window._page("Reports & Diagnostics", note, window._scroll(workspace))
    window._replace_page(4, page)
    window.reports_diagnostics_workspace = workspace

    # Loading a config updates the hidden authoritative form. Refresh the composed
    # workspace afterwards so profile detection and the friendly checkpoint editor
    # always reflect the loaded values.
    original_apply_config = window.apply_config

    def apply_config_and_refresh(config):
        result = original_apply_config(config)
        workspace.refresh_from_config(config.reporting)
        return result

    window.apply_config = apply_config_and_refresh
    workspace.refresh_from_config(window.config.reporting)
