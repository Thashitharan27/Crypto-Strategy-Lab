from unittest.mock import Mock, patch

import pytest

from crypto_strategy_lab.browser_visualizer_coordinator import BrowserVisualizerCoordinator


def test_coordinator_loads_verified_model_before_creating_session(tmp_path):
    events = []
    owner = Mock()
    owner.stop.side_effect = lambda: events.append("stop")
    owner.replace.side_effect = lambda model: (events.append(("replace", model)), "http://127.0.0.1:1234/session/token/")[1]
    service = Mock()
    model = Mock()
    with patch("crypto_strategy_lab.browser_visualizer_coordinator.load_browser_visualizer", side_effect=lambda *args: (events.append("validated"), model)[1]) as load:
        result = BrowserVisualizerCoordinator(service, tmp_path, owner=owner).open_completed_run("BTCUSDT_4h")
    assert result == "http://127.0.0.1:1234/session/token/"
    load.assert_called_once_with(service, tmp_path, "BTCUSDT_4h")
    assert events == ["stop", "validated", ("replace", model)]


def test_coordinator_refuses_unverified_run_without_starting_session(tmp_path):
    owner = Mock()
    with patch("crypto_strategy_lab.browser_visualizer_coordinator.load_browser_visualizer", side_effect=ValueError("invalid manifest")):
        with pytest.raises(ValueError, match="invalid manifest"):
            BrowserVisualizerCoordinator(Mock(), tmp_path, owner=owner).open_completed_run("BAD")
    owner.stop.assert_called_once_with()
    owner.replace.assert_not_called()


def test_coordinator_stop_delegates_to_session_owner(tmp_path):
    owner = Mock()
    coordinator = BrowserVisualizerCoordinator(Mock(), tmp_path, owner=owner)
    coordinator.stop()
    owner.stop.assert_called_once_with()
