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
