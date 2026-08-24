"""Final GUI composition for the human-focused Results Dashboard."""
from __future__ import annotations

from .results_dashboard_workspace import ResultsDashboardWorkspace


def _preserve_legacy_result_widgets(window, workspace) -> None:
    """Keep native completion sinks alive while removing their old presentation."""
    widgets = []
    widgets.extend(getattr(window, "kpi_cards", {}).values())
    widgets.append(getattr(window, "summary", None))
    widgets.append(getattr(window, "timings", None))
    widgets.extend(getattr(window, "artifact_buttons", {}).values())
    widgets.append(getattr(window, "open_folder", None))
    for widget in widgets:
        if widget is None:
            continue
        widget.setParent(workspace)
        widget.hide()


def apply_results_dashboard_workspace(window) -> None:
    """Replace the legacy debug-like result dump without changing completion semantics."""
    if getattr(window, "results_dashboard_workspace", None) is not None:
        return
    required = (
        "_page",
        "_replace_page",
        "_finished",
        "open_artifact",
        "open_folder",
        "artifact_buttons",
        "kpi_cards",
        "summary",
        "timings",
    )
    if not all(hasattr(window, name) for name in required):
        return

    workspace = ResultsDashboardWorkspace(window)
    _preserve_legacy_result_widgets(window, workspace)
    page = window._page("Results Dashboard", workspace)
    window._replace_page(6, page)
    window.results_dashboard_workspace = workspace

    original_finished = window._finished

    def finished_and_refresh(result):
        original_finished(result)
        workspace.refresh_completed_run()

    window._finished = finished_and_refresh
    workspace.refresh_completed_run()
