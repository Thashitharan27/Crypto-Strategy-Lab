"""Wire the reusable GitHub Sync widget to the active v3 window lifecycle."""
from __future__ import annotations

from .github_manager import GitHubIntegrationWidget


def apply_github_sync_safety(window) -> None:
    """Bind source-changing Git actions to the authoritative run-worker state."""
    widget = window.findChild(GitHubIntegrationWidget)
    if widget is None:
        return

    def active_work() -> bool:
        thread = getattr(window, "_thread", None)
        return bool(thread is not None and thread.isRunning())

    widget.active_work = active_work
    window.github_sync = widget
