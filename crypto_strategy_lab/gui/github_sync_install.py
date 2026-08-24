"""Wire the reusable GitHub Sync widget to the active v3 window lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .github_manager import GitHubIntegrationWidget


_DEPENDENCY_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "uv.lock",
    "pipfile",
    "pipfile.lock",
    "environment.yml",
    "environment.yaml",
}


@dataclass(frozen=True)
class GitUpdateResult:
    output: str
    before_head: str
    after_head: str
    changed_files: tuple[str, ...]

    @property
    def updated(self) -> bool:
        return bool(self.before_head and self.after_head and self.before_head != self.after_head)

    @property
    def dependency_files(self) -> tuple[str, ...]:
        return tuple(path for path in self.changed_files if is_dependency_file(path))


def is_dependency_file(path: str) -> bool:
    """Return whether a changed repository path can require environment refresh."""
    normalized = path.replace("\\", "/").strip("/")
    lower = normalized.lower()
    name = PurePosixPath(lower).name
    return (
        (name.startswith("requirements") and name.endswith(".txt"))
        or lower.startswith("requirements/")
        or name in _DEPENDENCY_NAMES
    )


def _pull_with_metadata(manager, pull_fn) -> GitUpdateResult:
    """Run the existing safe pull and capture exactly what changed."""
    before = manager._run("rev-parse", "HEAD").stdout.strip()
    output = pull_fn()
    after = manager._run("rev-parse", "HEAD").stdout.strip()
    changed_files: tuple[str, ...] = ()
    if before and after and before != after:
        diff = manager._run("diff", "--name-only", f"{before}..{after}").stdout
        changed_files = tuple(line.strip() for line in diff.splitlines() if line.strip())
    return GitUpdateResult(output, before, after, changed_files)


def apply_github_sync_safety(window) -> None:
    """Bind Git actions to run safety and controlled application restart."""
    if getattr(window, "_github_sync_safety_installed", False):
        return

    widget = window.findChild(GitHubIntegrationWidget)
    if widget is None:
        return

    def active_work() -> bool:
        thread = getattr(window, "_thread", None)
        return bool(thread is not None and thread.isRunning())

    widget.active_work = active_work
    window.github_sync = widget
    window._restart_after_exit = False

    original_pull = widget.manager.pull

    def pull_with_metadata():
        return _pull_with_metadata(widget.manager, original_pull)

    widget.manager.pull = pull_with_metadata

    def request_restart() -> None:
        if active_work():
            widget._error("Restart is disabled while a backtest or portfolio run is active.")
            return
        window._restart_after_exit = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def close_without_restart() -> None:
        window._restart_after_exit = False
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def update_completed(result: GitUpdateResult) -> None:
        widget._log("Update completed")
        if not result.updated:
            widget.refresh_status(False)
            return

        dependency_files = result.dependency_files
        if dependency_files:
            changed = "\n".join(f"• {path}" for path in dependency_files)
            QMessageBox.information(
                widget,
                "Update downloaded — dependency refresh required",
                "The GitHub update was downloaded, but Python dependency files changed:\n\n"
                f"{changed}\n\n"
                "Crypto Strategy Lab will close now instead of reopening with stale packages.\n\n"
                "For the current Windows setup, run:\n"
                ".venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n"
                "Then reopen Crypto Strategy Lab.",
            )
            close_without_restart()
            return

        widget.state.setText("● Update installed")
        widget.status_detail.setText("Restarting Crypto Strategy Lab with the new version…")
        widget.pull_btn.setEnabled(False)
        widget.refresh.setEnabled(False)
        widget.review.setEnabled(False)
        widget.commit_btn.setEnabled(False)
        # Pull completion is already delivered on the GUI thread. Restart
        # immediately instead of depending on a delayed timer callback surviving
        # the async Git task handoff.
        request_restart()

    widget._pulled = update_completed
    window.request_application_restart = request_restart
    window._github_sync_safety_installed = True
