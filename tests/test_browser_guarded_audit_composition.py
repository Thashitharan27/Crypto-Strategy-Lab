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
    assert events == [{"operation": "STATUS", "outcome": "SUCCESS"}, {"operation": "AUTH", "outcome": "DENIED"}]
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


def test_rejected_guarded_config_is_audited_without_native_error_details():
    events = []
    integration = Mock()
    integration.save_config.side_effect = PermissionError("private path")
    app = create_browser_app(
        token=TOKEN, guarded_integration=integration, guarded_enabled=True,
        guarded_audit_callback=events.append,
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.put("/api/v1/guarded/configs/test", json={},
                              headers=HEADERS)
        assert response.status_code == 403
        assert "private path" not in response.text
    assert events == [{"operation": "CONFIG_SAVE", "outcome": "DENIED"}]
