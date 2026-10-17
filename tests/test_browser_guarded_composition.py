"""Optional guarded router must use production app's localhost security perimeter."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app


TOKEN = "g" * 48


def test_default_browser_does_not_mount_guarded_routes():
    integration = Mock()
    app = create_browser_app(token=TOKEN, guarded_integration=integration)
    assert not any(getattr(r, "path", "").startswith("/api/v1/guarded") for r in app.routes)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/guarded/jobs/job-1", headers={"Authorization": "Bearer " + TOKEN}).status_code == 404
    integration.status.assert_not_called()


def test_test_only_opt_in_routes_retain_localhost_origin_and_auth_guards():
    integration = Mock()
    integration.status.return_value = {"request_id": "job-1", "status": "RUNNING"}
    app = create_browser_app(token=TOKEN, guarded_integration=integration, guarded_enabled=True)
    with TestClient(app, base_url="http://localhost") as client:
        url = "/api/v1/guarded/jobs/job-1"
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer bad"}).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer " + TOKEN, "Host": "attacker.invalid"}).status_code == 403
        assert client.get(url, headers={"Authorization": "Bearer " + TOKEN, "Origin": "https://attacker.invalid"}).status_code == 403
        result = client.get(url, headers={"Authorization": "Bearer " + TOKEN})
        assert result.status_code == 200
        assert result.json() == {"request_id": "job-1", "status": "RUNNING"}
    integration.status.assert_called_once_with("job-1")


def test_opt_in_without_server_integration_fails_closed():
    with pytest.raises(ValueError, match="Guarded integration"):
        create_browser_app(token=TOKEN, guarded_enabled=True)
