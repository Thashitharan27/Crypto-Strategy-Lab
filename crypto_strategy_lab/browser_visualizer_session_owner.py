"""Lifecycle boundary for the existing read-only visualizer browser server.

Internal component only: no HTTP route creates a session, and no execution,
configuration write, or market-data implementation is exposed.
"""
from __future__ import annotations

from threading import RLock

from crypto_strategy_lab.strategy_visualizer_browser import StrategyVisualizerBrowserServer


class BrowserVisualizerSessionOwner:
    """Own at most one browser chart session and stop it on replacement."""

    def __init__(self, server_factory=StrategyVisualizerBrowserServer):
        self._factory = server_factory
        self._lock = RLock()
        self._server = None

    def replace(self, model) -> str:
        """Explicit caller-only session replacement; failure leaves none active."""
        with self._lock:
            self._stop_locked()
            server = self._factory(model)
            try:
                url = server.start()
            except BaseException:
                server.stop()
                raise
            self._server = server
            return url

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        previous, self._server = self._server, None
        if previous is not None:
            previous.stop()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.stop()
