"""Final GUI composition for the compact Review & Run workspace."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from .review_run_workspace import ReviewRunWorkspace


def _retire_sidebar_run_shortcut(window) -> None:
    """Hide the legacy duplicate run action; Review & Run owns execution UX."""
    for button in window.findChildren(QPushButton):
        if button is window.run_button:
            continue
        if button.text().strip().upper() == "RUN BACKTEST":
            button.setEnabled(False)
            button.hide()


def apply_review_run_workspace(window) -> None:
    """Replace the legacy review/run strip without changing run semantics."""
    if getattr(window, "review_run_workspace", None) is not None:
        return
    required = (
        "_page",
        "_replace_page",
        "save",
        "load",
        "run_button",
        "output_root",
        "review_summary",
        "_render_research_summary",
    )
    if not all(hasattr(window, name) for name in required):
        return

    workspace = ReviewRunWorkspace(window)
    _retire_sidebar_run_shortcut(window)

    # Keep native compatibility targets alive when the legacy page is deleted.
    # They remain authoritative sinks used by config/reporting plumbing but are
    # no longer researcher-facing controls on this page.
    window.review_summary.setParent(workspace)
    window.review_summary.hide()
    window.output_root.setParent(workspace)
    window.output_root.hide()

    page = window._page("Review & Run", workspace)
    window._replace_page(5, page)
    window.review_run_workspace = workspace

    original_render_summary = window._render_research_summary

    def render_summary_and_review(config):
        result = original_render_summary(config)
        workspace.refresh(config)
        return result

    window._render_research_summary = render_summary_and_review

    if hasattr(window, "_set_readiness"):
        original_set_readiness = window._set_readiness

        def set_readiness_and_review(title, detail, *, state="pending"):
            result = original_set_readiness(title, detail, state=state)
            workspace.refresh_readiness()
            return result

        window._set_readiness = set_readiness_and_review

    # Native completion enables the button but historically never restored its
    # presentation text. Refresh after the worker thread actually stops so the
    # Review workspace owns the final idle state deterministically.
    original_finished = window._finished

    def finished_and_review(result):
        thread = getattr(window, "_thread", None)
        value = original_finished(result)
        window.run_button.setText("Run Backtest")
        window.run_button.setEnabled(True)
        if thread is not None:
            try:
                thread.finished.connect(workspace.refresh_readiness)
            except RuntimeError:
                workspace.refresh_readiness()
        else:
            workspace.refresh_readiness()
        return value

    window._finished = finished_and_review

    original_failed = window._failed

    def failed_and_review(message):
        thread = getattr(window, "_thread", None)
        value = original_failed(message)
        window.run_button.setText("Run Backtest")
        if thread is not None:
            try:
                thread.finished.connect(workspace.refresh_readiness)
            except RuntimeError:
                workspace.refresh_readiness()
        else:
            workspace.refresh_readiness()
        return value

    window._failed = failed_and_review

    original_apply_config = window.apply_config

    def apply_config_and_review(config):
        result = original_apply_config(config)
        workspace.refresh(config)
        return result

    window.apply_config = apply_config_and_review
    workspace.refresh()
