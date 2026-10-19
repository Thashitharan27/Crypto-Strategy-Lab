"""Opt-in routes must be absent by default and require bearer auth."""
from unittest.mock import Mock
import pytest

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


def test_job_submission_route_absent_by_default():
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=Mock()))
    client = TestClient(app)
    assert client.post("/api/v1/guarded/jobs", json={}).status_code == 404


def test_job_submission_is_authenticated_and_rejects_malformed_payload():
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    path = "/api/v1/guarded/jobs"
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, json={}, headers={"Authorization": "Bearer bad"}).status_code == 401
    auth = {"Authorization": "Bearer " + TOKEN}
    for bad in ({}, {"request_id": "../bad", "request": {}, "config": {}},
                {"request_id": "ok", "request": {}, "config": {}}):
        assert client.post(path, json=bad, headers=auth).status_code == 422
    integration.submit.assert_not_called()


def test_guarded_submission_delegates_native_types_without_result_leak(monkeypatch):
    import crypto_strategy_lab.data_lake_config as native
    config = Mock(spec=native.ResearchRunConfig)
    monkeypatch.setattr(native, "normalize_data_lake_config", lambda _: config)
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    payload = {
        "request_id": "job-2",
        "request": {
            "exchange": "binance", "market": "futures_um", "symbol": "btcusdt",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-01-02T00:00:00Z",
            "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
        },
        "config": {"native": "test-only"},
    }
    response = client.post("/api/v1/guarded/jobs", json=payload,
                           headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 202
    assert response.json() == {"request_id": "job-2", "status": "ACCEPTED"}
    integration.submit.assert_called_once()
    args = integration.submit.call_args.args
    assert args[0] == "job-2"
    assert args[1].symbol == "BTCUSDT"
    assert args[2] is config
    config.validate.assert_called_once()


def test_submission_permission_and_duplicate_fail_closed(monkeypatch):
    import crypto_strategy_lab.data_lake_config as native
    config = Mock(spec=native.ResearchRunConfig)
    monkeypatch.setattr(native, "normalize_data_lake_config", lambda _: config)
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(token=TOKEN, integration=integration, enabled=True))
    client = TestClient(app)
    payload = {
        "request_id": "job-2",
        "request": {
            "exchange": "binance", "market": "spot", "symbol": "BTCUSDT",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-01-02T00:00:00Z",
            "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
        }, "config": {},
    }
    integration.submit.side_effect = PermissionError("private disk")
    response = client.post("/api/v1/guarded/jobs", json=payload,
                           headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 403
    assert response.json() == {"detail": "Guarded operations disabled"}
    integration.submit.side_effect = ValueError("private output path")
    response = client.post("/api/v1/guarded/jobs", json=payload,
                           headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 409
    assert response.json() == {"detail": "Job submission rejected"}


def test_audit_events_are_bounded_and_exclude_identifiers_and_payloads():
    events = []
    integration = Mock()
    integration.status.return_value = {"request_id": "sensitive-run", "status": "RUNNING"}
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True, audit_callback=events.append,
    ))
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/v1/guarded/jobs/sensitive-run", headers=headers).status_code == 200
    assert events == [{"operation": "STATUS", "outcome": "SUCCESS"}]
    assert client.get("/api/v1/guarded/jobs/sensitive-run").status_code == 401
    assert events == [{"operation": "STATUS", "outcome": "SUCCESS"}, {"operation": "AUTH", "outcome": "DENIED"}]


def test_failing_audit_callback_does_not_break_guarded_response():
    integration = Mock()
    integration.progress.return_value = {}
    app = FastAPI()
    def broken_audit(_):
        raise RuntimeError("logging unavailable")
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True, audit_callback=broken_audit,
    ))
    client = TestClient(app)
    result = client.get("/api/v1/guarded/jobs/valid/progress",
        headers={"Authorization": "Bearer " + TOKEN})
    assert result.status_code == 200


@pytest.mark.parametrize("failure", [
    OSError("private C:/original/configs/secret.json"),
    PermissionError(13, "Windows sharing/permission failure", "C:/original/configs/secret.json"),
])
def test_config_persistence_os_failure_is_audited_and_sanitized(failure):
    events = []
    integration = Mock()
    integration.save_config.side_effect = failure
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=events.append,
    ))
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/guarded/configs/valid", json={},
            headers={"Authorization": "Bearer " + TOKEN},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration persistence unavailable"}
    assert "secret" not in response.text
    assert events == [{"operation": "CONFIG_SAVE", "outcome": "PERSISTENCE_FAILED"}]
    integration.save_config.assert_called_once_with("valid", {})


def test_submit_native_io_failure_is_audited_and_sanitized(monkeypatch):
    import crypto_strategy_lab.data_lake_config as native

    config = Mock(spec=native.ResearchRunConfig)
    monkeypatch.setattr(native, "normalize_data_lake_config", lambda _: config)
    events = []
    integration = Mock()
    integration.submit.side_effect = OSError("private /srv/output/run-id")
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=events.append,
    ))
    payload = {
        "request_id": "valid-job",
        "request": {
            "exchange": "binance", "market": "spot", "symbol": "BTCUSDT",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-01-02T00:00:00Z",
            "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
        },
        "config": {},
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/guarded/jobs", json=payload,
            headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 503
    assert response.json() == {"detail": "Native research service unavailable"}
    assert "/srv/" not in response.text
    assert events == [{"operation": "JOB_SUBMIT", "outcome": "EXECUTION_UNAVAILABLE"}]
    integration.submit.assert_called_once()


def test_guarded_inspection_io_failures_are_sanitized_and_audited():
    for operation, method, path, integration_method in (
        ("STATUS", "get", "/api/v1/guarded/jobs/safe", "status"),
        ("PROGRESS", "get", "/api/v1/guarded/jobs/safe/progress", "progress"),
        ("CANCEL", "post", "/api/v1/guarded/jobs/safe/cancel", "cancel"),
    ):
        events = []
        integration = Mock()
        getattr(integration, integration_method).side_effect = OSError(
            "private /srv/native/output/credentials"
        )
        app = FastAPI()
        app.include_router(create_guarded_job_router(
            token=TOKEN, integration=integration, enabled=True,
            audit_callback=events.append,
        ))
        with TestClient(app) as client:
            response = getattr(client, method)(
                path, headers={"Authorization": "Bearer " + TOKEN},
            )
        assert response.status_code == 503
        assert response.json() == {"detail": "Guarded job service unavailable"}
        assert "private" not in response.text
        assert events == [{"operation": operation, "outcome": "UNAVAILABLE"}]
        getattr(integration, integration_method).assert_called_once_with("safe")


def test_guarded_native_runtime_errors_are_sanitized_with_bounded_audit():
    for operation, method, path, delegated in (
        ("STATUS", "get", "/api/v1/guarded/jobs/job-1", "status"),
        ("PROGRESS", "get", "/api/v1/guarded/jobs/job-1/progress", "progress"),
        ("CANCEL", "post", "/api/v1/guarded/jobs/job-1/cancel", "cancel"),
        ("CONFIG_SAVE", "put", "/api/v1/guarded/configs/test", "save_config"),
    ):
        audit_events = []
        integration = Mock()
        getattr(integration, delegated).side_effect = RuntimeError(
            "private C:/native/secrets/credentials"
        )
        app = FastAPI()
        app.include_router(create_guarded_job_router(
            token=TOKEN, integration=integration, enabled=True,
            audit_callback=audit_events.append,
        ))
        with TestClient(app) as client:
            args = {"json": {}} if method == "put" else {}
            response = getattr(client, method)(
                path, headers={"Authorization": "Bearer " + TOKEN}, **args,
            )
        assert response.status_code == 503
        expected = ("Configuration persistence unavailable" if method == "put"
                    else "Guarded job service unavailable")
        assert response.json() == {"detail": expected}
        assert "secrets" not in response.text
        assert audit_events == [{
            "operation": operation,
            "outcome": "PERSISTENCE_FAILED" if method == "put" else "UNAVAILABLE",
        }]
        getattr(integration, delegated).assert_called_once()


def test_guarded_mutations_authenticate_before_malformed_body_validation():
    integration = Mock()
    events = []
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=events.append,
    ))
    cases = (
        ("post", "/api/v1/guarded/jobs"),
        ("put", "/api/v1/guarded/configs/safe"),
    )
    with TestClient(app) as client:
        for method, path in cases:
            for body in ('{not-json', '[]', '"scalar"'):
                unauthorized = getattr(client, method)(
                    path, content=body, headers={"Content-Type": "application/json"},
                )
                assert unauthorized.status_code == 401
                assert unauthorized.json() == {"detail": "Unauthorized"}
                authorized = getattr(client, method)(
                    path, content=body, headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + TOKEN,
                    },
                )
                assert authorized.status_code == 422
                assert "private" not in authorized.text
    assert events.count({"operation": "AUTH", "outcome": "DENIED"}) == 6
    assert events.count({"operation": "JOB_SUBMIT", "outcome": "INVALID_INPUT"}) == 3
    assert events.count({"operation": "CONFIG_SAVE", "outcome": "INVALID_INPUT"}) == 3
    integration.submit.assert_not_called()
    integration.save_config.assert_not_called()


def test_guarded_config_and_job_posts_reject_large_bodies_before_native_calls():
    from crypto_strategy_lab.browser_guarded_http import _MAX_GUARDED_JSON_BYTES

    integration = Mock()
    events = []
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=events.append,
    ))
    oversized = b'{"padding":"' + b"x" * _MAX_GUARDED_JSON_BYTES + b'"}'
    auth = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
    with TestClient(app) as client:
        for method, path, operation in (
            ("put", "/api/v1/guarded/configs/safe", "CONFIG_SAVE"),
            ("post", "/api/v1/guarded/jobs", "JOB_SUBMIT"),
        ):
            # Authorization always wins over request-body validation.
            denied = getattr(client, method)(path, content=oversized,
                                              headers={"Content-Type": "application/json"})
            assert denied.status_code == 401
            response = getattr(client, method)(path, content=oversized, headers=auth)
            assert response.status_code == 413
            assert response.json() == {"detail": "Guarded JSON payload too large"}
            assert {"operation": operation, "outcome": "OVERSIZED"} in events
    integration.save_config.assert_not_called()
    integration.submit.assert_not_called()


def test_guarded_streamed_payload_size_is_checked_without_content_length():
    from crypto_strategy_lab.browser_guarded_http import _MAX_GUARDED_JSON_BYTES

    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
    ))
    def chunks():
        yield b'{"padding":"'
        yield b"x" * _MAX_GUARDED_JSON_BYTES
        yield b'"}'
    headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
    with TestClient(app) as client:
        response = client.put("/api/v1/guarded/configs/safe",
                              content=chunks(), headers=headers)
    assert response.status_code == 413
    integration.save_config.assert_not_called()


def test_guarded_declared_oversize_rejected_without_reading_or_native_write():
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
    ))
    auth = {
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Content-Length": str(4 * 1024 * 1024 + 1),
    }
    with TestClient(app) as client:
        response = client.put("/api/v1/guarded/configs/safe",
                              content=b"{}", headers=auth)
    assert response.status_code == 413
    integration.save_config.assert_not_called()


@pytest.mark.parametrize("method,path,payload,attribute", [
    ("put", "/api/v1/guarded/configs/test", {"valid": True}, "save_config"),
    ("post", "/api/v1/guarded/jobs/run-1/cancel", None, "cancel"),
])
def test_b4_audit_failure_blocks_native_mutation_before_it_starts(method, path, payload, attribute):
    integration = Mock()
    def broken_audit(_event):
        raise OSError("private path /sensitive/audit.log")
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=broken_audit, require_audit_admission=True,
    ))
    with TestClient(app) as client:
        kwargs = {"headers": {"Authorization": "Bearer " + TOKEN}}
        if payload is not None:
            kwargs["json"] = payload
        result = getattr(client, method)(path, **kwargs)
    assert result.status_code == 503
    assert result.json() == {"detail": "Guarded audit unavailable"}
    getattr(integration, attribute).assert_not_called()


def test_b4_audit_failure_blocks_job_submit_before_claim(monkeypatch):
    import crypto_strategy_lab.data_lake_config as native
    config = Mock(spec=native.ResearchRunConfig)
    monkeypatch.setattr(native, "normalize_data_lake_config", lambda _: config)
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=lambda event: (_ for _ in ()).throw(OSError("secret"))
        if event["outcome"] == "ATTEMPT" else None,
        require_audit_admission=True,
    ))
    payload = {
        "request_id": "run-1",
        "request": {
            "exchange": "binance", "market": "futures_um", "symbol": "BTCUSDT",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-01-02T00:00:00Z",
            "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
        },
        "config": {},
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/guarded/jobs", json=payload,
                               headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 503
    assert response.json() == {"detail": "Guarded audit unavailable"}
    integration.submit.assert_not_called()


def test_b4_post_operation_audit_failure_does_not_claim_rollback():
    integration = Mock()
    seen = []
    def post_error(event):
        seen.append(event)
        if event["outcome"] == "SUCCESS":
            raise OSError("after commit")
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        audit_callback=post_error, require_audit_admission=True,
    ))
    with TestClient(app) as client:
        response = client.put("/api/v1/guarded/configs/test", json={"native": "data"},
                              headers={"Authorization": "Bearer " + TOKEN})
        retry = client.put("/api/v1/guarded/configs/test", json={"native": "data"},
                           headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200
    assert retry.status_code == 503
    assert retry.json() == {"detail": "Guarded audit unavailable"}
    integration.save_config.assert_called_once()
    assert seen == [
        {"operation": "CONFIG_SAVE", "outcome": "ATTEMPT"},
        {"operation": "CONFIG_SAVE", "outcome": "SUCCESS"},
    ]
    # The native save already ran. Post-commit audit loss is *not* rollback
    # evidence and remains a separate release blocker.


def test_b4_strict_mode_without_audit_callback_refuses_write():
    integration = Mock()
    app = FastAPI()
    app.include_router(create_guarded_job_router(
        token=TOKEN, integration=integration, enabled=True,
        require_audit_admission=True,
    ))
    with TestClient(app) as client:
        response = client.put("/api/v1/guarded/configs/id", json={},
                              headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 503
    integration.save_config.assert_not_called()
