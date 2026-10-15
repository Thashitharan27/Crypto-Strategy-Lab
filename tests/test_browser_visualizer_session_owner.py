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


def test_real_visualizer_server_closes_socket_if_thread_cannot_start():
    from unittest.mock import patch
    from crypto_strategy_lab.strategy_visualizer_browser import StrategyVisualizerBrowserServer
    from threading import Thread
    model = Mock()
    owner = StrategyVisualizerBrowserServer(model)
    with patch.object(Thread, "start", side_effect=RuntimeError("thread creation failed")):
        with pytest.raises(RuntimeError, match="thread creation failed"):
            owner.start()
    assert owner._server is None
    assert owner._thread is None
    owner.stop()  # harmless following partial startup failure


def test_visualizer_server_interrupt_after_worker_started_stops_worker():
    from threading import Thread
    from unittest.mock import patch
    from crypto_strategy_lab.strategy_visualizer_browser import StrategyVisualizerBrowserServer

    original_start = Thread.start

    def start_then_interrupt(thread):
        original_start(thread)
        raise KeyboardInterrupt("interrupted after start")

    server = StrategyVisualizerBrowserServer(Mock())
    with patch.object(Thread, "start", start_then_interrupt):
        with pytest.raises(KeyboardInterrupt, match="interrupted after start"):
            server.start()
    assert server._server is None
    assert server._thread is None
    server.stop()


def test_visualizer_server_releases_socket_if_thread_construction_interrupts():
    from unittest.mock import patch
    from crypto_strategy_lab.strategy_visualizer_browser import StrategyVisualizerBrowserServer
    server = StrategyVisualizerBrowserServer(Mock())
    with patch(
        "crypto_strategy_lab.strategy_visualizer_browser.Thread",
        side_effect=KeyboardInterrupt("construction interrupted"),
    ):
        with pytest.raises(KeyboardInterrupt, match="construction interrupted"):
            server.start()
    assert server._server is None
    assert server._thread is None
    server.stop()
