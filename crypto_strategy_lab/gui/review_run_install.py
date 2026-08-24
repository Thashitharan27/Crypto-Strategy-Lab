"""Final GUI composition for the compact Review & Run workspace."""
from __future__ import annotations

from .review_run_workspace import ReviewRunWorkspace


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

    original_apply_config = window.apply_config

    def apply_config_and_review(config):
        result = original_apply_config(config)
        workspace.refresh(config)
        return result

    window.apply_config = apply_config_and_review
    workspace.refresh()
