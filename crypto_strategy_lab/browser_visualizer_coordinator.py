"""Internal composition of the verified visualizer loader and existing session owner.

No HTTP route or automatic session creation is exposed by this component.
"""
from __future__ import annotations

from pathlib import Path
from threading import RLock

from crypto_strategy_lab.browser_visualizer_adapter import load_browser_visualizer
from crypto_strategy_lab.browser_visualizer_session_owner import BrowserVisualizerSessionOwner


class BrowserVisualizerCoordinator:
    """Explicitly open one *verified* completed run in the existing browser chart."""

    def __init__(self, application_service, completed_run_root: str | Path, *, owner=None, original_completed_run_root=None):
        self._service = application_service
        self._root = Path(completed_run_root)
        self._original_root = Path(original_completed_run_root) if original_completed_run_root is not None else None
        self._owner = owner if owner is not None else BrowserVisualizerSessionOwner()
        self._lock = RLock()

    def open_completed_run(self, run_id: str) -> str:
        """Fail closed; never expose a session from an unverified run."""
        with self._lock:
            # Stop any previous model/session before attempting a new selection.
            self._owner.stop()
            root = self._root
            if self._original_root is not None:
                try:
                    (root / run_id).lstat()
                except FileNotFoundError:
                    root = self._original_root
            model = load_browser_visualizer(self._service, root, run_id)
            return self._owner.replace(model)

    def stop(self) -> None:
        with self._lock:
            self._owner.stop()
