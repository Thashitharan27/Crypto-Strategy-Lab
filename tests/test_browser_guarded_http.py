"""Opt-in routes must be absent by default and require bearer auth."""
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_guarded_http import create_guarded_job_router

TOKEN = "x" * 40


def test_default_router_exposes_no_routes():
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=Mock()))
    client = TestClient(app)
    assert client.get("/api/v1/guarded/jobs/job-1").status_code == 404
    assert client.post("/api/v1/guarded/jobs/job-1/cancel").status_code == 404


def test_explicit_test_router_authenticates_every_operation():
    integration = Mock()
    integration.status.return_value = {"request_id": "job-1", "status": "RUNNING"}
    integration.progress.return_value = {"phase": "preparing"}
    integration.cancel.return_value = {"request_id": "job-1", "status": "CANCELLATION_UNAVAILABLE"}
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    paths = (
        ("get", "/api/v1/guarded/jobs/job-1"),
        ("get", "/api/v1/guarded/jobs/job-1/progress"),
        ("post", "/api/v1/guarded/jobs/job-1/cancel"),
    )
    for method, path in paths:
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert getattr(client, method)(path, headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    integration.status.assert_called_once_with("job-1")
    integration.progress.assert_called_once_with("job-1")
    integration.cancel.assert_called_once_with("job-1")


def test_disabled_integration_denies_even_with_valid_token():
    integration = Mock()
    integration.status.side_effect = PermissionError("internal")
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    result = client.get("/api/v1/guarded/jobs/job-1", headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 403
    assert result.json() == {"detail": "Guarded operations disabled"}


def test_guarded_routes_reject_invalid_ids_before_native_inspection():
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    for bad in ("bad.name", "space%20id", "é", "a" * 101):
        for method, suffix in (("get", ""), ("get", "/progress"), ("post", "/cancel")):
            response = getattr(client, method)(
                "/api/v1/guarded/jobs/" + bad + suffix,
                headers={"Authorization": "Bearer " + TOKEN},
            )
            assert response.status_code == 404
    integration.status.assert_not_called()
    integration.progress.assert_not_called()
    integration.cancel.assert_not_called()


def test_guarded_config_write_absent_by_default():
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=Mock()))
    client = TestClient(app)
    assert client.put("/api/v1/guarded/configs/test", json={}).status_code == 404


def test_opt_in_config_write_requires_auth_and_returns_no_server_path():
    integration = Mock()
    integration.save_config.return_value = "/private/configs/test.json"
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    url = "/api/v1/guarded/configs/test"
    assert client.put(url, json={}).status_code == 401
    assert client.put(url, json={}, headers={"Authorization": "Bearer bad"}).status_code == 401
    assert integration.save_config.call_count == 0
    result = client.put(url, json={"native": "payload"}, headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 200
    assert result.json() == {"config_id": "test", "status": "SAVED"}
    integration.save_config.assert_called_once_with("test", {"native": "payload"})


def test_opt_in_config_write_rejects_bad_ids_and_sanitizes_native_errors():
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.put("/api/v1/guarded/configs/bad.name", json={}, headers=headers).status_code == 404
    integration.save_config.assert_not_called()
    integration.save_config.side_effect = ValueError("private C:/original/path")
    response = client.put("/api/v1/guarded/configs/valid", json={}, headers=headers)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid native configuration"}
    integration.save_config.side_effect = PermissionError("internal")
    response = client.put("/api/v1/guarded/configs/valid", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Guarded operations disabled"}
