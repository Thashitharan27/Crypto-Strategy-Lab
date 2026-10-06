from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from crypto_strategy_lab.gui import strategy_visualizer_install


def test_strategy_visualizer_install_is_browser_only():
    source = inspect.getsource(strategy_visualizer_install)

    assert "StrategyVisualizerBrowserServer" in source
    assert "webbrowser.open" in source
    assert "StrategyVisualizerWorkspace" not in source
    assert "from .strategy_visualizer_workspace import" not in source
    assert "QWebEngineView" not in source
    assert "build_visualizer_html" not in source
    assert "window.pages.addWidget" not in source
    assert 'QPushButton("Strategy Visualizer")' in source


def test_strategy_visualizer_launcher_reuses_current_run_server_until_run_changes():
    source = inspect.getsource(
        strategy_visualizer_install.StrategyVisualizerBrowserLauncher
    )

    assert "self._run_key" in source
    assert "if self.model is not None and self._run_key == run_key" in source
    assert "self.stop()" in source
    assert "StrategyVisualizerBrowserServer(model)" in source
