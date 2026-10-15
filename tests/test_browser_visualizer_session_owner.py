from unittest.mock import Mock

import pytest

from crypto_strategy_lab.browser_visualizer_session_owner import BrowserVisualizerSessionOwner


def test_session_owner_replaces_and_stops_previous_server():
    first, second = Mock(), Mock()
    first.start.return_value = "http://127.0.0.1:1111/session/first/"
    second.start.return_value = "http://127.0.0.1:2222/session/second/"
    factory = Mock(side_effect=[first, second])
    owner = BrowserVisualizerSessionOwner(server_factory=factory)
    assert owner.replace("model-1") == first.start.return_value
    assert owner.replace("model-2") == second.start.return_value
    first.stop.assert_called_once_with()
    owner.stop()
    second.stop.assert_called_once_with()
    owner.stop()
    assert second.stop.call_count == 1
    assert factory.call_args_list[0].args == ("model-1",)


def test_session_owner_cleans_up_failure_and_leaves_no_active_session():
    first, broken = Mock(), Mock()
    first.start.return_value = "http://127.0.0.1:1111/session/first/"
    broken.start.side_effect = RuntimeError("bind failed")
    owner = BrowserVisualizerSessionOwner(server_factory=Mock(side_effect=[first, broken]))
    owner.replace("first")
    with pytest.raises(RuntimeError, match="bind failed"):
        owner.replace("broken")
    first.stop.assert_called_once()
    broken.stop.assert_called_once()
    owner.stop()
    assert first.stop.call_count == 1
    assert broken.stop.call_count == 1


def test_session_owner_context_manager_releases_session():
    server = Mock()
    server.start.return_value = "http://127.0.0.1:1234/session/token/"
    with BrowserVisualizerSessionOwner(server_factory=Mock(return_value=server)) as owner:
        owner.replace("model")
    server.stop.assert_called_once()


def test_replacement_stops_previous_server_before_starting_next():
    events = []

    class FakeServer:
        def __init__(self, name):
            self.name = name
        def start(self):
            events.append(("start", self.name))
            return f"http://127.0.0.1:1234/session/{self.name}/"
        def stop(self):
            events.append(("stop", self.name))

    names = iter(("one", "two"))
    owner = BrowserVisualizerSessionOwner(server_factory=lambda _model: FakeServer(next(names)))
    owner.replace(object())
    owner.replace(object())
    owner.stop()
    assert events == [
        ("start", "one"), ("stop", "one"),
        ("start", "two"), ("stop", "two"),
    ]
