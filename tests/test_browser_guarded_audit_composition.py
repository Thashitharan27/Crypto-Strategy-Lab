"""Audit composition checks do not enable production browser mutation."""
from unittest.mock import Mock

from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_http import create_browser_app

TOKEN = "a" * 48
HEADERS = {"Authorization": "Bearer " + TOKEN}


def test_explicit_guarded_http_composition_forwards_redacted_audit():
    events = []
    integration = Mock()
    integration.status.return_value = {"request_id": "secret_job", "status": "RUNNING"}
    app = create_browser_app(
        token=TOKEN, guarded_integration=integration, guarded_enabled=True,
        guarded_audit_callback=events.append,
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/guarded/jobs/secret_job", headers=HEADERS).status_code == 200
        assert client.get("/api/v1/guarded/jobs/secret_job").status_code == 401
        assert client.get("/api/v1/guarded/jobs/secret_job", headers={
            **HEADERS, "Origin": "https://attacker.invalid",
        }).status_code == 403
    assert events == [{"operation": "STATUS", "outcome": "SUCCESS"}]
    assert "secret_job" not in str(events)


def test_disabled_guarded_composition_never_calls_audit_callback():
    events = []
    integration = Mock()
    app = create_browser_app(
        token=TOKEN, guarded_integration=integration,
        guarded_audit_callback=events.append,
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/v1/guarded/jobs/job", headers=HEADERS).status_code == 404
    assert events == []
    integration.status.assert_not_called()
