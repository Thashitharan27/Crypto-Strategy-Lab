from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app


def test_opt_in_guarded_integration_closed_at_app_shutdown():
    integration = Mock()
    visualizer = Mock()
    app = create_browser_app(
        token="z" * 48, guarded_integration=integration,
        guarded_enabled=True, visualizer_coordinator=visualizer,
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/health", headers={
            "Authorization": "Bearer " + "z" * 48,
        }).status_code == 200
        integration.close.assert_not_called()
    integration.close.assert_called_once_with()
    visualizer.stop.assert_called_once_with()


def test_default_browser_does_not_close_unmounted_guarded_service():
    integration = Mock()
    app = create_browser_app(token="z" * 48, guarded_integration=integration)
    with TestClient(app, base_url="http://localhost"):
        pass
    integration.close.assert_not_called()


def test_visualizer_stops_even_if_guarded_shutdown_raises():
    integration = Mock()
    visualizer = Mock()
    integration.close.side_effect = RuntimeError("guarded shutdown failed")
    app = create_browser_app(
        token="z" * 48, guarded_integration=integration,
        guarded_enabled=True, visualizer_coordinator=visualizer,
    )
    import pytest
    with pytest.raises(RuntimeError, match="guarded shutdown failed"):
        with TestClient(app, base_url="http://localhost"):
            pass
    visualizer.stop.assert_called_once_with()
