"""Install the browser-only Strategy Visualizer launcher."""
from __future__ import annotations

from pathlib import Path
import webbrowser

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
from crypto_strategy_lab.strategy_visualizer_browser import (
    StrategyVisualizerBrowserServer,
)


class StrategyVisualizerBrowserLauncher(QObject):
    """Own the loopback browser server without embedding a desktop chart."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.model: CompletedRunVisualizer | None = None
        self.server: StrategyVisualizerBrowserServer | None = None
        self._run_key: tuple[str, str] | None = None

    def _current_run(self):
        manifest = getattr(self.window, "_manifest", None)
        run_dir = getattr(self.window, "_run_dir", None)
        if not manifest or not run_dir:
            return None, None
        return Path(run_dir), manifest

    def _ensure_model(self) -> CompletedRunVisualizer | None:
        run_dir, manifest = self._current_run()
        if run_dir is None or manifest is None:
            QMessageBox.information(
                self.window,
                "Strategy Visualizer",
                "No completed run is currently loaded. Load or complete a run first, then open Strategy Visualizer.",
            )
            return None

        run_id = str(manifest.get("run_id") or run_dir.name)
        run_key = (str(run_dir.resolve()), run_id)
        if self.model is not None and self._run_key == run_key:
            return self.model

        self.stop()
        self.model = CompletedRunVisualizer.load(
            self.window.service,
            run_dir,
            manifest,
        )
        self._run_key = run_key
        return self.model

    @Slot()
    def open_browser(self) -> None:
        try:
            model = self._ensure_model()
            if model is None:
                return
            if self.server is None:
                self.server = StrategyVisualizerBrowserServer(model)
            url = self.server.start()
            if not webbrowser.open(url, new=2):
                QMessageBox.information(
                    self.window,
                    "Strategy Visualizer",
                    f"Browser visualizer is ready at:\n{url}",
                )
        except Exception as exc:
            QMessageBox.critical(self.window, "Strategy Visualizer", str(exc))

    def stop(self) -> None:
        server = self.server
        self.server = None
        if server is not None:
            server.stop()
        self.model = None
        self._run_key = None


def apply_strategy_visualizer_workspace(window) -> None:
    """Add a sidebar action that opens the browser visualizer directly."""
    if getattr(window, "strategy_visualizer_launcher", None) is not None:
        return
    if not hasattr(window, "centralWidget"):
        return

    shell = window.centralWidget().layout()
    nav = shell.itemAt(0).layout() if shell is not None and shell.count() else None
    if nav is None:
        return

    launcher = StrategyVisualizerBrowserLauncher(window)
    button = QPushButton("Strategy Visualizer")
    button.setFlat(True)
    button.setToolTip("Open the completed-run Strategy Visualizer in your browser")
    button.clicked.connect(launcher.open_browser)

    insert_at = None
    for index in range(nav.count()):
        widget = nav.itemAt(index).widget()
        if isinstance(widget, QPushButton) and widget.text() == "Results Dashboard":
            insert_at = index + 1
            break
    if insert_at is None:
        for index in range(nav.count()):
            widget = nav.itemAt(index).widget()
            if isinstance(widget, QLabel) and widget.text() == "DATA":
                insert_at = index
                break
    if insert_at is None:
        insert_at = max(0, nav.count() - 3)
    nav.insertWidget(insert_at, button)

    try:
        window.destroyed.connect(lambda *_args: launcher.stop())
    except (AttributeError, RuntimeError):
        pass

    window.strategy_visualizer_launcher = launcher
    window.strategy_visualizer_button = button
